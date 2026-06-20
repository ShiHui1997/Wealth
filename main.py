#!/usr/bin/env python3
"""
大乐透预测系统 - 主入口
用法：
  python main.py init       初始化数据库（首次运行）
  python main.py fetch     获取最新一期数据
  python main.py fetch-all 批量获取历史数据（50期/批，直到第一期）
  python main.py analyze   分析历史数据并打印统计特征
  python main.py predict   生成并推送本期预测（推送到PushPlus）
  python main.py run-once  完整运行一次：获取最新 + 预测 + 推送
"""
import sys
import os
import argparse
from datetime import datetime
import yaml

# 将项目根目录加入sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.storage import LotteryStorage
from src.data.fetcher import DaletouFetcher
from src.analysis.analyzer import DaletouAnalyzer
from src.prediction.predictor import DaletouPredictor
from src.notification.pushplus import PushPlusNotifier


def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_init(args, config):
    """初始化数据库"""
    db_path = config["database"]["path"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    storage = LotteryStorage(db_path)
    print(f"[初始化] 数据库已就绪: {db_path}")
    print(f"  当前期数: {storage.count()}")


def cmd_fetch(args, config):
    """获取最新一期数据"""
    storage = LotteryStorage(config["database"]["path"])
    fetcher = DaletouFetcher(
        batch_size=config["data_source"]["batch_size"],
        delay=config["data_source"]["request_delay"],
    )

    print("[获取最新] 开始...")
    latest = fetcher.fetch_latest()
    if not latest:
        print("[获取最新] 无法获取最新数据，请检查网络连接")
        return

    saved = storage.save_draw(
        latest["issue"],
        latest["draw_date"],
        latest["front"],
        latest["back"]
    )
    if saved:
        print(f"[获取最新] 成功保存 第{latest['issue']}期: "
              f"前区{latest['front']} 后区{latest['back']}")
    else:
        print(f"[获取最新] 第{latest['issue']}期已存在，跳过")


def cmd_fetch_all(args, config):
    """批量获取历史数据，50期/批，直到第一期"""
    storage = LotteryStorage(config["database"]["path"])
    fetcher = DaletouFetcher(
        batch_size=config["data_source"]["batch_size"],
        delay=config["data_source"]["request_delay"],
    )

    def on_progress(batch, new_count, total_new):
        print(f"  批次{batch}: +{new_count}期，累计+{total_new}期")

    total = fetcher.fetch_all_history(storage, on_progress)
    print(f"\n[全量获取] 完成！数据库现有 {storage.count()} 期")


def cmd_analyze(args, config):
    """分析历史数据"""
    storage = LotteryStorage(config["database"]["path"])
    draws = storage.get_all_draws()

    if not draws:
        print("[分析] 数据库无数据，请先运行 fetch-all")
        return

    print(f"[分析] 共 {len(draws)} 期数据")
    analyzer = DaletouAnalyzer()
    features = analyzer.build_features(draws)

    # 打印更多分析结论
    print("\n=== 前区号码频率Top10（热号）===")
    ff = features["front_freq"]
    top10 = sorted(enumerate(ff, 1), key=lambda x: -x[1])[:10]
    for num, cnt in top10:
        print(f"  号码{num:02d}: {cnt}次")

    print("\n=== 前区奇偶比分布 ===")
    for pattern, cnt in sorted(features["front_odd_even"].items()):
        print(f"  奇{patern[0]}/偶{patern[1]}: {cnt}次 ({cnt/features['total_draws']*100:.1f}%)")

    print("\n=== 前区区间分布（1-12/13-24/25-35）===")
    for zone, cnt in sorted(features["front_zone"].items()):
        print(f"  {zone}: {cnt}次")


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

    prediction = predictor.predict(draws, top_n=top_n, candidates_count=candidates_count)

    # 打印结果
    print("\n" + predictor.format_prediction(prediction))

    # 推送到PushPlus
    notifier = PushPlusNotifier(config["pushplus"]["token"])
    html_content = predictor.format_prediction_html(prediction)
    latest_issue = storage.get_latest_issue()
    next_issue = _calc_next_issue(latest_issue) if latest_issue else ""
    notifier.send_prediction(html_content, next_issue)

    # 保存预测记录
    _save_prediction_log(prediction, next_issue)


def _calc_next_issue(current_issue: str) -> str:
    """计算下一期期号（简单实现）"""
    try:
        year = int(current_issue[:4])
        seq = int(current_issue[4:])
        if seq >= 365 // 2:  # 一年约170期（每周3期）
            return f"{year+1}001"
        return f"{year}{seq+1:03d}"
    except Exception:
        return current_issue


def _save_prediction_log(prediction, issue: str):
    """保存预测记录到日志文件"""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "predictions.log")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 预测 ===\n")
        for i, (nums, score) in enumerate(prediction, 1):
            f.write(f"第{i}注: 前区{nums['front']} 后区{nums['back']} (相似度:{score:.4f})\n")


def cmd_run_once(args, config):
    """完整运行一次：获取最新 + 预测 + 推送"""
    print(f"[完整运行] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    cmd_fetch(args, config)
    cmd_predict(args, config)


def main():
    parser = argparse.ArgumentParser(description="大乐透预测系统")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="初始化数据库")
    subparsers.add_parser("fetch", help="获取最新一期")
    subparsers.add_parser("fetch-all", help="批量获取所有历史数据")
    subparsers.add_parser("analyze", help="分析历史数据")
    subparsers.add_parser("predict", help="生成并推送预测")
    subparsers.add_parser("run-once", help="完整运行一次（获取+预测+推送）")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    config = load_config()
    commands = {
        "init": cmd_init,
        "fetch": cmd_fetch,
        "fetch-all": cmd_fetch_all,
        "analyze": cmd_analyze,
        "predict": cmd_predict,
        "run-once": cmd_run_once,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
