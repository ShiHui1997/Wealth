"""
蒙特卡洛标定模块

在历史数据上做 Walk-Forward 模拟：
对最近 N 期中的每一期，用“此前所有数据”训练模型并预测当期，
然后将模型预测与纯随机选号对比，判断模型是否有统计优势。

注意：这是一个耗时操作，计算量随 history 长度线性增长。
"""
import random
import json
from typing import List, Dict, Optional
from datetime import datetime

from src.analysis.analyzer import DaletouAnalyzer
from src.prediction.predictor import DaletouPredictor
from src.analysis.counterfactual import CounterfactualTracker


class MonteCarloCalibrator:
    """
    蒙特卡洛标定器

    核心功能：
    1. walk_forward_test: 对最近 test_periods 期做滚动预测
    2. random_baseline: 为每期生成随机对照
    3. compare: 对比模型 vs 随机对照的命中分布
    """

    def __init__(self, storage=None, predictor: Optional[DaletouPredictor] = None):
        self.storage = storage
        self.predictor = predictor or DaletouPredictor()
        self.counterfactual = CounterfactualTracker(storage)

    def walk_forward_test(self, test_periods: int = 50,
                          candidates_count: int = 1000,
                          use_multi_scale: bool = True) -> Dict:
        """
        对最近 test_periods 期做滚动 Walk-Forward 测试。

        对每一期 t：
        - 使用 [1, t-1] 的历史数据训练/预测
        - 得到模型推荐的 3 注
        - 同时生成 3 注随机对照
        - 用 t 期的真实开奖验证两者

        返回详细结果。
        """
        if self.storage is None:
            raise ValueError("MonteCarloCalibrator 需要 storage 实例")

        all_draws = self.storage.get_all_draws()
        if len(all_draws) < test_periods + 50:
            raise ValueError(f"历史数据不足：需要至少 {test_periods + 50} 期，"
                             f"当前只有 {len(all_draws)} 期")

        test_draws = all_draws[-test_periods:]
        results = []

        for i, target_draw in enumerate(test_draws, 1):
            target_issue = target_draw["issue"]
            # 该期在 all_draws 中的索引
            idx = all_draws.index(target_draw)
            history = all_draws[:idx]

            print(f"[MonteCarlo] {i}/{test_periods}: 回测第 {target_issue} 期 "
                  f"(历史 {len(history)} 期)")

            # 模型预测（需要暂时“忘掉” target_issue 后面的数据）
            pred = self.predictor.predict(
                history,
                top_n=3,
                candidates_count=candidates_count,
                storage=self.storage,
                next_issue=target_issue,
                use_multi_scale=use_multi_scale,
            )
            model_bets = [{"front": p["front"], "back": p["back"]} for p, _ in pred]
            control_bets = self.counterfactual.generate_random_control(count=3)

            # 验证
            model_hit = self._evaluate_bets(model_bets, target_draw)
            control_hit = self._evaluate_bets(control_bets, target_draw)

            results.append({
                "issue": target_issue,
                "model": model_hit,
                "control": control_hit,
            })

        return self._summarize_results(results)

    def _evaluate_bets(self, bets: List[Dict], actual: Dict) -> Dict:
        """评估一组号码 vs 真实开奖"""
        actual_front = set(actual["front"])
        actual_back = set(actual["back"])

        best_f = 0
        best_b = 0
        any_f3 = False
        any_b1 = False

        for b in bets:
            f = len(set(b["front"]) & actual_front)
            bb = len(set(b["back"]) & actual_back)
            best_f = max(best_f, f)
            best_b = max(best_b, bb)
            if f >= 3:
                any_f3 = True
            if bb >= 1:
                any_b1 = True

        return {
            "best_front_match": best_f,
            "best_back_match": best_b,
            "any_front_3plus": any_f3,
            "any_back_1plus": any_b1,
        }

    def _summarize_results(self, results: List[Dict]) -> Dict:
        """汇总 Walk-Forward 结果"""
        n = len(results)
        if n == 0:
            return {}

        model_front = sum(r["model"]["best_front_match"] for r in results) / n
        model_back = sum(r["model"]["best_back_match"] for r in results) / n
        control_front = sum(r["control"]["best_front_match"] for r in results) / n
        control_back = sum(r["control"]["best_back_match"] for r in results) / n

        model_f3 = sum(r["model"]["any_front_3plus"] for r in results) / n
        model_b1 = sum(r["model"]["any_back_1plus"] for r in results) / n
        control_f3 = sum(r["control"]["any_front_3plus"] for r in results) / n
        control_b1 = sum(r["control"]["any_back_1plus"] for r in results) / n

        return {
            "test_periods": n,
            "model": {
                "avg_front_match": model_front,
                "avg_back_match": model_back,
                "any_front_3plus_rate": model_f3,
                "any_back_1plus_rate": model_b1,
            },
            "control": {
                "avg_front_match": control_front,
                "avg_back_match": control_back,
                "any_front_3plus_rate": control_f3,
                "any_back_1plus_rate": control_b1,
            },
            "diff": {
                "front_match": model_front - control_front,
                "back_match": model_back - control_back,
                "any_front_3plus": model_f3 - control_f3,
                "any_back_1plus": model_b1 - control_b1,
            },
            "details": results,
        }

    def run(self, test_periods: int = 50,
            candidates_count: int = 1000,
            use_multi_scale: bool = True) -> Dict:
        """入口方法：运行完整蒙特卡洛标定并打印结果"""
        print("\n" + "=" * 50)
        print(f"[蒙特卡洛标定] 开始 Walk-Forward 回测")
        print(f"  测试期数: {test_periods}")
        print(f"  候选数: {candidates_count}")
        print(f"  多尺度融合: {use_multi_scale}")
        print("=" * 50)

        start = datetime.now()
        report = self.walk_forward_test(
            test_periods=test_periods,
            candidates_count=candidates_count,
            use_multi_scale=use_multi_scale,
        )
        elapsed = (datetime.now() - start).total_seconds()

        self.print_report(report, elapsed)
        return report

    def print_report(self, report: Dict, elapsed: Optional[float] = None) -> None:
        """打印蒙特卡洛标定报告"""
        print("\n" + "=" * 50)
        print("[蒙特卡洛标定报告]")
        print("=" * 50)
        print(f"\n测试期数: {report['test_periods']}")
        if elapsed is not None:
            print(f"耗时: {elapsed:.1f} 秒")

        m = report["model"]
        c = report["control"]
        d = report["diff"]

        print(f"\n模型组:")
        print(f"  平均前区命中: {m['avg_front_match']:.3f}")
        print(f"  平均后区命中: {m['avg_back_match']:.3f}")
        print(f"  前区≥3占比:   {m['any_front_3plus_rate']:.3f}")
        print(f"  后区≥1占比:   {m['any_back_1plus_rate']:.3f}")

        print(f"\n随机对照组:")
        print(f"  平均前区命中: {c['avg_front_match']:.3f}")
        print(f"  平均后区命中: {c['avg_back_match']:.3f}")
        print(f"  前区≥3占比:   {c['any_front_3plus_rate']:.3f}")
        print(f"  后区≥1占比:   {c['any_back_1plus_rate']:.3f}")

        print(f"\n模型 - 对照 (差值):")
        print(f"  前区命中差: {d['front_match']:+.3f}")
        print(f"  后区命中差: {d['back_match']:+.3f}")
        print(f"  前区≥3差:   {d['any_front_3plus']:+.3f}")
        print(f"  后区≥1差:   {d['any_back_1plus']:+.3f}")

        print(f"\n结论:")
        if abs(d["front_match"]) < 0.03 and abs(d["back_match"]) < 0.03:
            print("  ℹ️  模型与随机对照差异很小，符合随机彩票预期。")
            print("     当前策略主要是方差管理，而非概率优势。")
        elif d["front_match"] > 0.03 or d["back_match"] > 0.03:
            print("  ✅ 模型在回测中表现出一定优势，可能与历史特征学习有关。")
            print("     建议继续观察并在未来开奖中验证。")
        else:
            print("  ⚠️ 模型表现弱于随机对照，建议检查特征或权重。")

        print("=" * 50 + "\n")
