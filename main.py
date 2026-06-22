#!/usr/bin/env python3
"""
大乐透预测系统 - 主入口
用法：
  python main.py init          初始化数据库
  python main.py fetch-all    获取全部历史数据（首次运行，约2885期）
  python main.py fetch        获取最新一期开奖数据（日常增量更新）
  python main.py verify       验证最新一期预测 vs 真实开奖
  python main.py verify --issue 2024001   验证指定期号
  python main.py calibrate    根据验证结果校准权重（含Walk-Forward回测）
  python main.py backtest     单独运行Walk-Forward回测
  python main.py validate     统计验证报告（卡方检验/显著性检验/系统健康度）
  python main.py health       系统健康检查
  python main.py stats        显示预测效果统计
  python main.py predict [--no-push]  生成并推送本期预测
  python main.py run          完整运行一次：获取+验证+校准+预测+推送
"""
import sys
import os
import argparse
import traceback
from datetime import datetime
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.storage import LotteryStorage
from src.data.fetcher import DaletouFetcher
from src.analysis.analyzer import DaletouAnalyzer
from src.analysis.regression import BatchRegressionAnalyzer
from src.analysis.calibration import SelfCalibrator
from src.analysis.walk_forward import WalkForwardBacktester
from src.analysis.statistics import StatisticalValidator
from src.prediction.predictor import DaletouPredictor
from src.notification.pushplus import PushPlusNotifier
from src.utils.logger import RunLogger, HealthChecker


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ═══════════════════════════════════════════════
# 命令实现
# ═══════════════════════════════════════════════

def cmd_init(args, config):
    db_path = config["database"]["path"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    storage = LotteryStorage(db_path)
    print(f"[初始化] 数据库已就绪: {db_path}")
    print(f"  当前期数: {storage.count()}")


def cmd_fetch(args, config):
    storage = LotteryStorage(config["database"]["path"])
    fetcher = DaletouFetcher(
        delay=config["data_source"].get("request_delay", 0.5),
    )
    print("[获取最新] 开始...")
    latest = fetcher.fetch_latest()
    if not latest:
        print("[获取最新] 无法获取最新数据，请检查网络")
        return

    saved = storage.save_draw(
        latest["issue"], latest["draw_date"],
        latest["front"], latest["back"]
    )
    if saved:
        print(f"[获取最新] 成功保存 第{latest['issue']}期: "
              f"前区{latest['front']} 后区{latest['back']}")
    else:
        print(f"[获取最新] 第{latest['issue']}期已存在，跳过")

    # 获取后自动验证
    _auto_verify(storage, latest["issue"])


def cmd_fetch_all(args, config):
    """获取全部历史数据（首次运行，一次性拉完2885期）"""
    storage = LotteryStorage(config["database"]["path"])
    fetcher = DaletouFetcher(
        delay=config["data_source"].get("request_delay", 0.5),
    )
    analyzer = DaletouAnalyzer()
    regression_analyzer = BatchRegressionAnalyzer(analyzer)

    existing = storage.count()
    if existing > 0:
        print(f"[全量获取] 数据库已有 {existing} 期数据")
        print(f"[全量获取] 如需重新获取，请先删除 data/daletou.db 后运行 init")

    # 一步到位：分页拉取全部历史
    all_data = fetcher.fetch_all()
    if not all_data:
        print("[全量获取] 未获取到任何数据，退出")
        return

    # 批量保存（自动去重）
    new_count = storage.save_draws_batch(all_data)
    total = storage.count()

    print(f"\n[全量获取] 新增 {new_count} 期，数据库现有 {total} 期")
    print(f"[全量获取] 范围: {storage.get_first_issue()} ~ {storage.get_latest_issue()}")

    # 对每50期做批次回归分析
    batch_size = config["analysis"].get("batch_size", 50)
    total_draws = storage.get_all_draws()
    batch_no = 0
    for start_i in range(0, len(total_draws), batch_size):
        batch_draws = total_draws[start_i:start_i + batch_size]
        global_draws = total_draws[:start_i] + total_draws[start_i + batch_size:]

        if len(global_draws) >= 50:
            batch_no += 1
            report = regression_analyzer.analyze_batch(batch_draws, global_draws)
            storage.save_batch_analysis(
                batch_no,
                batch_draws[0]["issue"],
                batch_draws[-1]["issue"],
                report["diffs"],
                report["notes"]
            )

    if batch_no > 0:
        print(f"[全量获取] 已完成 {batch_no} 批次回归分析")


def cmd_verify(args, config):
    """验证预测 vs 真实开奖"""
    storage = LotteryStorage(config["database"]["path"])

    if args.issue:
        result = storage.verify_prediction(args.issue)
    else:
        result = storage.verify_latest()

    if result:
        # 验证后尝试校准
        stats = storage.get_verification_stats()
        if stats["total_verified"] >= 5:
            print("\n[验证] 已验证 >= 5 期，建议运行校准: python main.py calibrate")
    else:
        print("\n[验证] 暂无预测或开奖数据可验证")


def cmd_calibrate(args, config):
    """执行自我校准（含Walk-Forward回测）"""
    storage = LotteryStorage(config["database"]["path"])
    analyzer = DaletouAnalyzer()
    calibrator = SelfCalibrator(storage, analyzer=analyzer)
    calibrator.calibrate(force=args.force)
    calibrator.print_calibration_status()


def cmd_backtest(args, config):
    """单独运行Walk-Forward回测"""
    storage = LotteryStorage(config["database"]["path"])
    analyzer = DaletouAnalyzer()
    wf = WalkForwardBacktester(analyzer, storage)

    draws = storage.get_all_draws()
    if len(draws) < 100:
        print(f"[回测] 数据不足100期（当前{len(draws)}期），无法回测")
        return

    test_periods = args.periods if args.periods else 100
    candidate_sample = args.sample if args.sample else 50

    result = wf.run_backtest(
        draws,
        test_periods=test_periods,
        candidate_sample=candidate_sample,
    )

    print(result.get("backtest_summary", ""))

    # 打印详细窗口对比
    print(f"\n{'='*60}")
    print(f"  Walk-Forward 回测详细结果")
    print(f"{'='*60}")
    for label, wr in result.get("window_results", {}).items():
        print(f"\n  窗口 {label}:")
        print(f"    测试期数: {wr['test_count']}")
        print(f"    实际开奖均分: {wr['avg_actual_score']:.6f}")
        print(f"    随机候选均分: {wr['avg_random_score']:.6f}")
        print(f"    均分比: {wr['avg_ratio']:.4f}")
        print(f"    命中率(超P90): {wr['hit_rate']:.1%}")
        print(f"    预测力: {wr['predictive_power']:.6f}")
        print(f"    融合权重: {result['window_weights'].get(label, 0):.4f}")
    print(f"\n{'='*60}")


def cmd_validate(args, config):
    """统计验证报告"""
    storage = LotteryStorage(config["database"]["path"])
    analyzer = DaletouAnalyzer()
    validator = StatisticalValidator(storage)

    draws = storage.get_all_draws()
    if not draws:
        print("[验证] 无数据")
        return

    report = validator.full_report(draws, storage, analyzer)
    print(report)


def cmd_health(args, config):
    """系统健康检查"""
    storage = LotteryStorage(config["database"]["path"])
    validator = StatisticalValidator(storage)
    draws = storage.get_all_draws()

    health = validator.system_health(draws, storage)

    print(f"\n{'='*50}")
    print(f"  系统健康检查")
    print(f"{'='*50}")
    for check in health["checks"]:
        icon = {"ok": "✅", "warning": "⚠️", "info": "ℹ️"}.get(check["status"], "?")
        print(f"  {icon} {check['name']}: {check['detail']}")

    status_map = {
        "healthy": "✅ 系统健康",
        "minor_issues": "⚠️ 存在小问题",
        "needs_attention": "❌ 需要关注",
    }
    print(f"\n  总体状态: {status_map.get(health['overall'], health['overall'])}")
    print(f"{'='*50}\n")


def cmd_stats(args, config):
    """显示预测效果统计"""
    storage = LotteryStorage(config["database"]["path"])
    stats = storage.get_verification_stats()
    analyzer = DaletouAnalyzer()
    calibrator = SelfCalibrator(storage, analyzer=analyzer)

    print(f"\n{'='*50}")
    print(f"  大乐透预测系统 - 效果统计")
    print(f"{'='*50}")
    print(f"  已验证期数: {stats['total_verified']}")

    if stats["total_verified"] > 0:
        print(f"\n  前区命中分布:")
        for k in sorted(stats.get("front_match_dist", {}).keys()):
            v = stats["front_match_dist"][k]
            rate = v / stats["total_verified"] * 100
            bar = "█" * int(rate / 2)
            print(f"    命中 {k} 个: {v:3d} 期 ({rate:5.1f}%) {bar}")

        print(f"\n  后区命中分布:")
        for k in sorted(stats.get("back_match_dist", {}).keys()):
            v = stats["back_match_dist"][k]
            rate = v / stats["total_verified"] * 100
            bar = "█" * int(rate / 2)
            print(f"    命中 {k} 个: {v:3d} 期 ({rate:5.1f}%) {bar}")

        print(f"\n  前区命中>=3 比例: {stats.get('any_front_3plus_rate', 0)*100:.1f}%")
        print(f"  后区命中>=1 比例: {stats.get('any_back_1plus_rate', 0)*100:.1f}%")

    print(f"\n{'='*50}")
    calibrator.print_calibration_status()

    # 显示Walk-Forward权重
    wf = WalkForwardBacktester(analyzer, storage)
    wf_weights = wf.get_window_weights()
    if wf_weights:
        print(f"\n  Walk-Forward 窗口权重:")
        for label, weight in wf_weights.items():
            print(f"    窗口 {label}: {weight:.4f}")


def cmd_predict(args, config):
    """生成预测并推送"""
    storage = LotteryStorage(config["database"]["path"])
    # 使用全部历史数据（而非仅最近N期），确保特征学习最充分
    draws = storage.get_all_draws()

    if len(draws) < 10:
        print(f"[预测] 历史数据不足（仅{len(draws)}期），至少需要10期")
        return

    predictor = DaletouPredictor()
    top_n = config["prediction"]["recommend_count"]
    candidates_count = config["prediction"]["candidate_count"]
    latest_issue = storage.get_latest_issue()
    next_issue = _calc_next_issue(latest_issue) if latest_issue else "未知"
    prediction = predictor.predict(
        draws,
        top_n=top_n,
        candidates_count=candidates_count,
        storage=storage,
        next_issue=next_issue,
        use_multi_scale=True,
    )

    # 打印结果
    print("\n" + predictor.format_prediction(prediction))

    # 保存预测记录到数据库
    storage.save_prediction(next_issue, prediction)

    # 推送到PushPlus
    push_result = "SKIPPED"
    if not getattr(args, 'no_push', False):
        token = config.get("pushplus", {}).get("token", "")
        print("=" * 50)
        print(f"[推送] PushPlus Token: {'已配置 ({}字符)'.format(len(token)) if token else '❌ 未配置/为空!'}")

        if not token:
            print("[推送] ⚠️ Token为空，跳过推送！请检查Secrets中PUSHPLUS_TOKEN是否正确设置")
            push_result = "FAILED_NO_TOKEN"
            # 写入推送结果文件供工作流检查
            _write_push_result({"status": "failed", "reason": "token_empty", "issue": next_issue})
        else:
            notifier = PushPlusNotifier(token)
            submit_url = config.get("submit", {}).get("url", "")
            html_content = predictor.format_prediction_html(prediction, submit_url=submit_url)
            success = notifier.send_prediction(html_content, next_issue)
            if not success:
                print("[推送] ❌ 推送发送失败！检查Token是否有效: http://www.pushplus.plus/")
                push_result = "FAILED_API_ERROR"
                _write_push_result({"status": "failed", "reason": "api_error", "issue": next_issue})
            else:
                print(f"[推送] ✅ 第{next_issue}期预测已推送到微信")
                push_result = "SUCCESS"
                _write_push_result({"status": "success", "issue": next_issue})
            print("=" * 50)
    else:
        push_result = "NO_PUSH_FLAG"
        submit_url = config.get("submit", {}).get("url", "")
        print(f"[预测] --no-push 已指定，跳过推送")
        if submit_url:
            print(f"[预测] 提交链接: {submit_url}")
        else:
            print(predictor.format_prediction_html(prediction))


def cmd_run(args, config):
    """完整运行一次：获取最新开奖 + 回归分析 + 验证上期预测 + 校准 + 预测下期 + 推送"""
    storage = LotteryStorage(config["database"]["path"])
    notifier = PushPlusNotifier(config["pushplus"]["token"])
    health_checker = HealthChecker(notifier)
    logger = RunLogger()

    print(f"\n{'='*50}")
    print(f"[完整运行] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    try:
        # 第一步：尝试获取最新开奖（失败不阻断，用数据库现有数据继续）
        step1 = logger.step_start("获取最新开奖", "从体彩API拉取")
        try:
            cmd_fetch(args, config)
            logger.step_end(step1, "ok", "获取完成")
        except Exception as e:
            logger.step_end(step1, "warning", f"获取失败，使用现有数据: {e}")
            health_checker.alert_on_warning(
                f"体彩API获取失败: {e}",
                "步骤1-获取最新开奖（不影响后续流程）"
            )

        # 第二步：批次回归分析
        step2 = logger.step_start("回归分析", "最近50期 vs 历史")
        try:
            analyzer = DaletouAnalyzer()
            regression_analyzer = BatchRegressionAnalyzer(analyzer)
            all_draws = storage.get_all_draws()
            if len(all_draws) >= 100:
                recent_batch = all_draws[-50:]
                earlier_draws = all_draws[:-50]
                report = regression_analyzer.analyze_batch(recent_batch, earlier_draws)
                storage.save_batch_analysis(
                    0,
                    recent_batch[0]["issue"],
                    recent_batch[-1]["issue"],
                    report["diffs"],
                    report["notes"]
                )
                logger.step_end(step2, "ok", "回归分析完成")
            else:
                logger.step_end(step2, "warning", "数据不足100期，跳过")
        except Exception as e:
            logger.step_end(step2, "error", f"回归分析失败: {e}")

        # 第三步：验证上期预测 + 自动补验证所有遗漏的期号
        step3 = logger.step_start("验证预测", "验证上期 + 补验证遗漏")
        try:
            storage_r = LotteryStorage(config["database"]["path"])
            cmd_verify(argparse.Namespace(issue=None), config)

            # 自动补验证
            all_draws = storage_r.get_all_draws()
            draw_issues = {d["issue"] for d in all_draws}
            pred_issues = storage_r.get_all_predicted_issues()
            verified_issues = storage_r.get_all_verified_issues()

            pending = set(pred_issues) & draw_issues - verified_issues
            if pending:
                print(f"[自动补验] 发现 {len(pending)} 期待补验证: {sorted(pending)}")
                for issue in sorted(pending):
                    result = storage_r.verify_prediction(issue)
                    if result:
                        front_m = result.get("best_front_match", 0)
                        back_m = result.get("best_back_match", 0)
                        print(f"  ✓ {issue}期: 前区命中{front_m} 后区命中{back_m}")
            else:
                print("[自动补验] 无遗漏的验证项")

            ver_count = len(storage_r.get_all_verified_issues())
            logger.step_end(step3, "ok", f"已验证{ver_count}期")
        except Exception as e:
            logger.step_end(step3, "error", f"验证失败: {e}")

        # 第四步：校准（如果数据足够）
        step4 = logger.step_start("自我校准", "权重调整 + Walk-Forward")
        try:
            stats = storage_r.get_verification_stats()
            if stats["total_verified"] >= 5:
                analyzer = DaletouAnalyzer()
                calibrator = SelfCalibrator(storage_r, analyzer=analyzer)
                calibrator.calibrate(force=False, run_walk_forward=True)
                logger.step_end(step4, "ok", "校准完成（含WF回测）")
            else:
                logger.step_end(step4, "warning",
                    f"跳过校准（已验证{stats['total_verified']}期，需要>=5期）")
        except Exception as e:
            logger.step_end(step4, "error", f"校准失败: {e}")

        # 第五步：预测下期并推送
        step5 = logger.step_start("生成预测", "多尺度融合打分 + 推送")
        try:
            predict_args = argparse.Namespace(no_push=getattr(args, 'no_push', False))
            cmd_predict(predict_args, config)
            logger.step_end(step5, "ok", "预测完成")
        except Exception as e:
            logger.step_end(step5, "error", f"预测失败: {e}")
            health_checker.alert_on_error(
                e, "步骤5-生成预测"
            )
            raise  # 预测失败是致命错误

        # 保存运行日志
        log_path = logger.save()
        print(f"\n[运行日志] 已保存: {log_path}")
        logger.print_summary()

    except Exception as e:
        # 致命错误：发送告警
        health_checker.alert_on_error(e, "cmd_run 完整运行")
        logger.print_summary()
        print(f"\n[完整运行] ❌ 发生错误: {e}")
        traceback.print_exc()
        raise


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _calc_next_issue(current_issue: str) -> str:
    """计算下一期期号（大乐透格式: YYNNN，如 07001=2007年第1期）"""
    try:
        issue_str = str(current_issue).strip()
        if len(issue_str) == 7 and issue_str[0:4].isdigit():
            issue_str = issue_str[2:]

        if len(issue_str) >= 5:
            year_suffix = int(issue_str[:2])
            seq = int(issue_str[2:])
        else:
            year_suffix = int(str(int(issue_str)) // 1000)
            seq = int(str(int(issue_str)) % 1000)

        max_per_year = 170
        if seq >= max_per_year:
            return f"{(year_suffix % 99) + 1:02d}001"
        return f"{year_suffix:02d}{seq + 1:03d}"
    except Exception:
        try:
            n = int(current_issue)
            return str(n + 1)
        except Exception:
            return current_issue


def _write_push_result(result: dict):
    """写入推送结果文件供 GitHub Actions 检查"""
    import json
    with open("push_result.json", "w") as f:
        json.dump(result, f)


def _auto_verify(storage, issue: str):
    """获取开奖后自动验证（如果有该期预测记录）"""
    preds = storage.get_predictions_by_issue(issue)
    if preds:
        print(f"[自动验证] 发现第{issue}期预测记录，自动验证...")
        storage.verify_prediction(issue)


def main():
    parser = argparse.ArgumentParser(description="大乐透智能预测系统")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="初始化数据库")

    p_fetch = subparsers.add_parser("fetch", help="获取最新一期开奖")
    p_verify = subparsers.add_parser("verify", help="验证预测 vs 真实开奖")
    p_verify.add_argument("--issue", type=str, default=None, help="指定期号")
    p_calibrate = subparsers.add_parser("calibrate", help="执行自我校准（含WF回测）")
    p_calibrate.add_argument("--force", action="store_true", help="强制执行（即使数据不足）")
    p_backtest = subparsers.add_parser("backtest", help="单独运行Walk-Forward回测")
    p_backtest.add_argument("--periods", type=int, default=100, help="回测期数（默认100）")
    p_backtest.add_argument("--sample", type=int, default=50, help="每期随机候选数（默认50）")
    subparsers.add_parser("validate", help="统计验证报告")
    subparsers.add_parser("health", help="系统健康检查")
    subparsers.add_parser("stats", help="显示预测效果统计")
    p_predict = subparsers.add_parser("predict", help="生成并推送预测")
    p_predict.add_argument("--no-push", action="store_true", help="不推送到PushPlus")
    subparsers.add_parser("fetch-all", help="获取全部历史数据（首次运行，约2885期）")
    p_run = subparsers.add_parser("run", help="完整运行一次（获取+验证+校准+预测+推送）")
    p_run.add_argument("--no-push", action="store_true", help="不推送到PushPlus")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    config = load_config()
    commands = {
        "init": cmd_init,
        "fetch": cmd_fetch,
        "fetch-all": cmd_fetch_all,
        "verify": cmd_verify,
        "calibrate": cmd_calibrate,
        "backtest": cmd_backtest,
        "validate": cmd_validate,
        "health": cmd_health,
        "stats": cmd_stats,
        "predict": cmd_predict,
        "run": cmd_run,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
