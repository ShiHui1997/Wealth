#!/usr/bin/env python3
"""
大乐透预测系统 - 主入口
用法：
  python main.py init          初始化数据库
  python main.py fetch-all    获取全部历史数据（首次运行，约2885期）
  python main.py fetch        获取最新一期开奖数据（日常增量更新）
  python main.py verify       验证最新一期预测 vs 真实开奖
  python main.py verify --issue 2024001   验证指定期号
  python main.py calibrate    根据验证结果校准权重
  python main.py stats       显示预测效果统计
  python main.py predict [--no-push]  生成并推送本期预测
  python main.py run         完整运行一次：获取+验证+校准+预测+推送
"""
import sys
import os
import argparse
from datetime import datetime
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.storage import LotteryStorage
from src.data.fetcher import DaletouFetcher
from src.analysis.analyzer import DaletouAnalyzer
from src.analysis.regression import BatchRegressionAnalyzer
from src.analysis.calibration import SelfCalibrator
from src.prediction.predictor import DaletouPredictor
from src.notification.pushplus import PushPlusNotifier


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
    """执行自我校准"""
    storage = LotteryStorage(config["database"]["path"])
    calibrator = SelfCalibrator(storage)
    calibrator.calibrate(force=args.force)
    calibrator.print_calibration_status()


def cmd_stats(args, config):
    """显示预测效果统计"""
    storage = LotteryStorage(config["database"]["path"])
    stats = storage.get_verification_stats()
    calibrator = SelfCalibrator(storage)

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


def cmd_predict(args, config):
    """生成预测并推送"""
    storage = LotteryStorage(config["database"]["path"])
    draws = storage.get_draws_recent(config["analysis"]["recent_periods"])

    if len(draws) < 10:
        print(f"[预测] 历史数据不足（仅{len(draws)}期），至少需要10期")
        return

    predictor = DaletouPredictor()
    top_n = config["prediction"]["recommend_count"]
    candidates_count = config["prediction"]["candidate_count"]

    prediction = predictor.predict(
        draws,
        top_n=top_n,
        candidates_count=candidates_count,
        storage=storage,  # 传入storage以加载校准权重
    )

    # 打印结果
    print("\n" + predictor.format_prediction(prediction))

    # 保存预测记录到数据库
    latest_issue = storage.get_latest_issue()
    next_issue = _calc_next_issue(latest_issue) if latest_issue else "未知"
    storage.save_prediction(next_issue, prediction)

    # 推送到PushPlus
    if not getattr(args, 'no_push', False):
        notifier = PushPlusNotifier(config["pushplus"]["token"])
        submit_url = config.get("submit", {}).get("url", "")
        html_content = predictor.format_prediction_html(prediction, submit_url=submit_url)
        notifier.send_prediction(html_content, next_issue)
    else:
        submit_url = config.get("submit", {}).get("url", "")
        print(f"[预测] --no-push 已指定，跳过推送")
        if submit_url:
            print(f"[预测] 提交链接: {submit_url}")
        else:
            print(predictor.format_prediction_html(prediction))


def cmd_run(args, config):
    """完整运行一次：获取最新开奖 + 验证上期预测 + 校准 + 预测下期 + 推送"""
    storage = LotteryStorage(config["database"]["path"])

    print(f"\n{'='*50}")
    print(f"[完整运行] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 第一步：尝试获取最新开奖（失败不阻断，用数据库现有数据继续）
    print("\n[步骤1/4] 尝试获取最新开奖数据...")
    try:
        cmd_fetch(args, config)
    except Exception as e:
        print(f"[步骤1/4] 获取最新数据失败（可能为国外服务器，无法访问体彩API）")
        print(f"[步骤1/4] 将使用数据库中已有数据继续...")

    # 第二步：验证上期预测
    print("\n[步骤2/4] 验证上期预测...")
    storage_r = LotteryStorage(config["database"]["path"])
    cmd_verify(argparse.Namespace(issue=None), config)

    # 第三步：校准（如果数据足够）
    stats = storage_r.get_verification_stats()
    if stats["total_verified"] >= 5:
        print("\n[步骤3/4] 执行自我校准...")
        cmd_calibrate(argparse.Namespace(force=False), config)
    else:
        print(f"\n[步骤3/4] 跳过校准（已验证{stats['total_verified']}期，需要>=5期）")

    # 第四步：预测下期并推送（run 模式下始终推送）
    print("\n[步骤4/4] 生成并推送下期预测...")
    predict_args = argparse.Namespace(no_push=False)
    cmd_predict(predict_args, config)

    print(f"\n{'='*50}")
    print(f"[完整运行] 完成！")
    print(f"{'='*50}\n")


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _calc_next_issue(current_issue: str) -> str:
    """计算下一期期号"""
    try:
        year = int(current_issue[:4])
        seq = int(current_issue[4:])
        if seq >= 170:  # 一年约170期（每周3期）
            return f"{year+1}001"
        return f"{year}{seq+1:03d}"
    except Exception:
        return current_issue


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
    p_calibrate = subparsers.add_parser("calibrate", help="执行自我校准")
    p_calibrate.add_argument("--force", action="store_true", help="强制执行（即使数据不足）")
    subparsers.add_parser("stats", help="显示预测效果统计")
    p_predict = subparsers.add_parser("predict", help="生成并推送预测")
    p_predict.add_argument("--no-push", action="store_true", help="不推送到PushPlus")
    subparsers.add_parser("fetch-all", help="获取全部历史数据（首次运行，约2885期）")
    subparsers.add_parser("run", help="完整运行一次（获取+验证+校准+预测+推送）")

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
        "stats": cmd_stats,
        "predict": cmd_predict,
        "run": cmd_run,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
