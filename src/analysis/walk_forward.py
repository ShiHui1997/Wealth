"""
Walk-Forward 回测模块
用历史数据模拟预测，评估不同窗口大小的预测能力
基于回测结果计算多窗口融合权重

核心思路：
1. 将历史数据按不同窗口大小（50/100/200/500/all）切分
2. 对每个窗口，用该窗口数据构建特征，模拟预测下一期
3. 将模拟预测与真实开奖对比，计算命中率
4. 根据各窗口的回测表现，计算融合权重
5. 预测时用多窗口加权融合打分
"""
import random
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime


class WalkForwardBacktester:
    """
    Walk-Forward 回测器
    
    对每个窗口大小，模拟"用过去W期数据预测下一期"的过程，
    评估该窗口的预测能力，最终生成多窗口融合权重。
    """

    # 多尺度窗口配置
    WINDOW_SIZES = [50, 100, 200, 500, -1]  # -1 表示全部历史

    def __init__(self, analyzer, storage=None):
        """
        analyzer: DaletouAnalyzer 实例
        storage: LotteryStorage 实例（用于持久化回测结果）
        """
        self.analyzer = analyzer
        self.storage = storage

    def run_backtest(self, draws: List[Dict], test_periods: int = 100,
                     candidate_sample: int = 50) -> Dict:
        """
        执行完整的 Walk-Forward 回测
        
        对每个窗口大小 W：
          遍历最近 test_periods 期，用 draws[t-W:t] 构建特征，
          评分真实开奖 draws[t]，并与随机候选基线对比
        
        参数:
            draws: 全部历史开奖数据（按期号升序）
            test_periods: 回测的期数（从最近往前数）
            candidate_sample: 每期生成的随机候选数（用于计算基线）
        
        返回:
            {
                "window_results": {window_label: {stats}},
                "window_weights": {window_label: weight},
                "backtest_summary": str,
            }
        """
        print(f"\n[Walk-Forward] 开始回测，测试期数={test_periods}，"
              f"候选样本={candidate_sample}")
        print(f"[Walk-Forward] 窗口配置: "
              f"{[str(w) if w > 0 else 'all' for w in self.WINDOW_SIZES]}")

        total = len(draws)
        if total < 60:
            print("[Walk-Forward] 数据不足60期，跳过回测")
            return {"window_results": {}, "window_weights": {}, "backtest_summary": "数据不足"}

        # 确定回测区间
        start_idx = max(50, total - test_periods)  # 至少留50期做训练
        actual_test_count = total - start_idx
        print(f"[Walk-Forward] 回测区间: 第{start_idx+1}期 ~ 第{total}期 "
              f"（共{actual_test_count}期）")

        window_results = {}

        for W in self.WINDOW_SIZES:
            w_label = str(W) if W > 0 else "all"
            print(f"\n[Walk-Forward] 回测窗口 '{w_label}'...")

            period_scores = []  # 每期的 (actual_score, random_avg, ratio, front_match_info)
            hit_count = 0       # actual_score > random_avg 的次数

            for t in range(start_idx, total):
                # 获取训练数据
                if W > 0:
                    train_start = max(0, t - W)
                    train_draws = draws[train_start:t]
                else:
                    train_draws = draws[:t]

                if len(train_draws) < 30:
                    continue

                # 构建特征（静默模式，不打印）
                features = self._build_features_silent(train_draws)

                # 评分真实开奖
                actual = draws[t]
                actual_candidate = {
                    "front": actual["front"],
                    "back": actual["back"],
                }
                actual_score = self.analyzer.compute_similarity_score(
                    actual_candidate, features
                )

                # 生成随机候选并评分（作为基线）
                random.seed(42 + t)  # 确定性随机
                random_scores = []
                for _ in range(candidate_sample):
                    rcand = self._generate_random_candidate()
                    rscore = self.analyzer.compute_similarity_score(
                        rcand, features
                    )
                    random_scores.append(rscore)

                random_avg = sum(random_scores) / len(random_scores)
                random_max = max(random_scores)
                random_p90 = sorted(random_scores)[int(len(random_scores) * 0.9)]

                # 计算比率（实际得分 vs 随机基线）
                ratio = actual_score / random_avg if random_avg > 0 else 1.0

                # 判断是否"命中"：实际得分超过随机P90
                is_hit = actual_score >= random_p90
                if is_hit:
                    hit_count += 1

                period_scores.append({
                    "issue": actual["issue"],
                    "actual_score": round(actual_score, 6),
                    "random_avg": round(random_avg, 6),
                    "random_p90": round(random_p90, 6),
                    "ratio": round(ratio, 4),
                    "is_hit": is_hit,
                })

            # 计算窗口统计
            test_count = len(period_scores)
            if test_count == 0:
                print(f"[Walk-Forward] 窗口 '{w_label}' 无有效回测数据")
                continue

            avg_actual = sum(s["actual_score"] for s in period_scores) / test_count
            avg_random = sum(s["random_avg"] for s in period_scores) / test_count
            avg_ratio = sum(s["ratio"] for s in period_scores) / test_count
            hit_rate = hit_count / test_count

            # 预测力指标 = avg_ratio × hit_rate（综合考量）
            # avg_ratio > 1 说明实际开奖得分高于随机
            # hit_rate 高说明实际开奖经常进入top10%
            predictive_power = avg_ratio * hit_rate

            window_results[w_label] = {
                "test_count": test_count,
                "avg_actual_score": round(avg_actual, 6),
                "avg_random_score": round(avg_random, 6),
                "avg_ratio": round(avg_ratio, 4),
                "hit_rate": round(hit_rate, 4),
                "predictive_power": round(predictive_power, 6),
                "period_details": period_scores,
            }

            print(f"[Walk-Forward] 窗口 '{w_label}' 完成:")
            print(f"  测试期数: {test_count}")
            print(f"  实际开奖均分: {avg_actual:.4f}")
            print(f"  随机候选均分: {avg_random:.4f}")
            print(f"  均分比: {avg_ratio:.4f}")
            print(f"  命中率(超P90): {hit_rate:.1%}")
            print(f"  预测力: {predictive_power:.4f}")

        # 计算融合权重
        window_weights = self._compute_window_weights(window_results)

        # 生成摘要
        summary = self._generate_summary(window_results, window_weights)

        # 持久化
        if self.storage:
            self._save_results(window_results, window_weights)

        print(f"\n[Walk-Forward] 回测完成！融合权重:")
        for w_label, weight in window_weights.items():
            print(f"  窗口 {w_label}: {weight:.4f}")

        return {
            "window_results": window_results,
            "window_weights": window_weights,
            "backtest_summary": summary,
        }

    def _build_features_silent(self, draws: List[Dict]) -> Dict:
        """静默构建特征（不打印日志）"""
        features = {}
        features.update(self.analyzer.frequency_analysis(draws))
        features.update(self.analyzer.sum_analysis(draws))
        features.update(self.analyzer.odd_even_analysis(draws))
        features.update(self.analyzer.zone_analysis(draws))
        features.update(self.analyzer.span_analysis(draws))
        features.update(self.analyzer.consecutive_analysis(draws))
        return features

    def _generate_random_candidate(self) -> Dict:
        """生成一个纯随机候选号码"""
        front = sorted(random.sample(range(1, 36), 5))
        back = sorted(random.sample(range(1, 13), 2))
        return {"front": front, "back": back}

    def _compute_window_weights(self, window_results: Dict) -> Dict[str, float]:
        """
        根据回测结果计算各窗口的融合权重
        
        权重 ∝ max(0, predictive_power)
        然后归一化使总和为1
        
        如果所有窗口预测力都<=0，则使用均匀权重
        """
        if not window_results:
            # 默认均匀权重
            labels = [str(w) if w > 0 else "all" for w in self.WINDOW_SIZES]
            return {l: 1.0 / len(labels) for l in labels}

        # 提取预测力
        powers = {}
        for label, result in window_results.items():
            # 预测力必须 > 0 才有意义
            power = result["predictive_power"]
            # 加一个小的底值，确保所有窗口都有非零权重
            powers[label] = max(0.01, power)

        # 归一化
        total_power = sum(powers.values())
        weights = {k: v / total_power for k, v in powers.items()}

        return weights

    def _generate_summary(self, window_results: Dict, weights: Dict) -> str:
        """生成回测摘要文字"""
        lines = ["[Walk-Forward 回测摘要]"]
        for label, result in window_results.items():
            w = weights.get(label, 0)
            lines.append(
                f"  窗口{label:>4s}: 预测力={result['predictive_power']:.4f}, "
                f"命中率={result['hit_rate']:.1%}, "
                f"权重={w:.4f}"
            )
        return "\n".join(lines)

    def _save_results(self, window_results: Dict, window_weights: Dict):
        """将回测结果持久化到数据库"""
        # 保存窗口权重
        for label, weight in window_weights.items():
            self.storage.save_calibration(
                f"wf_weight_{label}",
                weight,
                f"Walk-Forward回测权重 (窗口={label})"
            )

        # 保存回测摘要
        summary_data = {}
        for label, result in window_results.items():
            summary_data[label] = {
                "test_count": result["test_count"],
                "avg_ratio": result["avg_ratio"],
                "hit_rate": result["hit_rate"],
                "predictive_power": result["predictive_power"],
            }

        self.storage.save_calibration(
            "wf_backtest_summary",
            0,  # 占位值，实际数据在note里
            json.dumps(summary_data, ensure_ascii=False)
        )

        # 保存回测时间戳
        self.storage.save_calibration(
            "wf_last_backtest_time",
            0,
            datetime.now().isoformat()
        )

    def get_window_weights(self) -> Dict[str, float]:
        """
        从数据库读取当前的窗口权重
        如果没有回测记录，返回默认均匀权重
        """
        if not self.storage:
            labels = [str(w) if w > 0 else "all" for w in self.WINDOW_SIZES]
            return {l: 1.0 / len(labels) for l in labels}

        weights = {}
        for w in self.WINDOW_SIZES:
            label = str(w) if w > 0 else "all"
            val = self.storage.get_calibration(f"wf_weight_{label}")
            if val is not None:
                weights[label] = val

        if not weights:
            # 无回测记录，使用默认均匀权重
            labels = [str(w) if w > 0 else "all" for w in self.WINDOW_SIZES]
            return {l: 1.0 / len(labels) for l in labels}

        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def multi_scale_score(self, candidate: Dict,
                          draws: List[Dict],
                          weights: Optional[Dict] = None,
                          feature_weights: Optional[Dict] = None) -> float:
        """
        多尺度加权融合打分
        
        对候选号码，在每个窗口下构建特征并打分，
        然后按窗口权重融合为最终得分
        
        参数:
            candidate: {"front": [...], "back": [...]}
            draws: 全部历史开奖数据
            weights: 窗口权重 (如 {"50": 0.2, "100": 0.3, ...})
            feature_weights: 特征维度权重（传给 compute_similarity_score）
        
        返回:
            融合后的相似度得分 (0~1)
        """
        if weights is None:
            weights = self.get_window_weights()

        total_score = 0.0
        total_weight = 0.0

        for W in self.WINDOW_SIZES:
            label = str(W) if W > 0 else "all"
            w = weights.get(label, 0)
            if w <= 0:
                continue

            # 获取该窗口的训练数据
            if W > 0:
                train_draws = draws[-W:] if len(draws) > W else draws
            else:
                train_draws = draws

            if len(train_draws) < 10:
                continue

            # 构建特征
            features = self._build_features_silent(train_draws)

            # 打分
            score = self.analyzer.compute_similarity_score(
                candidate, features, weights=feature_weights
            )

            total_score += w * score
            total_weight += w

        return total_score / total_weight if total_weight > 0 else 0.0
