"""
批次回归分析模块
每获取50期数据后，分析这批数据的特征与全局特征的差异
持续学习"随机性"是否在某些批次中有漂移或规律
"""
import json
from typing import List, Dict, Tuple
from datetime import datetime


class BatchRegressionAnalyzer:
    """
    批次回归分析器
    对比「这批50期」vs「全局历史」的统计特征，发现潜在规律或异常
    """

    def __init__(self, analyzer):
        """
        analyzer: DaletouAnalyzer 实例（用于提取特征）
        """
        self.analyzer = analyzer

    def analyze_batch(self, batch_draws: List[Dict],
                     global_draws: List[Dict]) -> Dict:
        """
        对比一批数据 vs 全局数据的特征差异
        Returns: 差异分析报告 dict
        """
        print(f"\n[批次回归] 分析 {len(batch_draws)} 期 vs 全局 {len(global_draws)} 期")

        # 提取两批特征
        batch_feat = self.analyzer.build_features(batch_draws)
        global_feat = self.analyzer.build_features(global_draws)

        report = {
            "batch_size": len(batch_draws),
            "global_size": len(global_draws),
            "diffs": {},          # 各项特征差异
            "anomalies": [],      # 异常发现
            "notes": "",          # 文字结论
        }

        # ── 1. 前区和值差异 ──
        bf = batch_feat["front_sum"]
        gf = global_feat["front_sum"]
        sum_diff = bf["mean"] - gf["mean"]
        sum_diff_pct = (sum_diff / gf["mean"] * 100) if gf["mean"] else 0
        report["diffs"]["front_sum_mean"] = {
            "batch": round(bf["mean"], 2),
            "global": round(gf["mean"], 2),
            "diff": round(sum_diff, 2),
            "diff_pct": round(sum_diff_pct, 2),
        }
        # 判断异常：和值偏离全局均值超过 1.5 个标准差
        if abs(sum_diff) > gf["std"] * 1.5:
            report["anomalies"].append(
                f"前区和值异常：这批均值{bf['mean']:.1f}，"
                f"偏离全局均值{gf['mean']:.1f} 达 {sum_diff_pct:.1f}%"
            )

        # ── 2. 奇偶比分布差异 ──
        report["diffs"]["odd_even"] = self._compare_distributions(
            batch_feat["front_odd_even"],
            global_feat["front_odd_even"],
            "奇偶比"
        )

        # ── 3. 区间分布差异 ──
        report["diffs"]["zone"] = self._compare_distributions(
            batch_feat["front_zone"],
            global_feat["front_zone"],
            "区间分布"
        )

        # ── 4. 前区跨度差异 ──
        span_diff = batch_feat["front_span_avg"] - global_feat["front_span_avg"]
        report["diffs"]["front_span"] = {
            "batch": round(batch_feat["front_span_avg"], 2),
            "global": round(global_feat["front_span_avg"], 2),
            "diff": round(span_diff, 2),
        }

        # ── 5. 连号特征差异 ──
        report["diffs"]["consecutive"] = self._compare_distributions(
            batch_feat["front_consecutive"],
            global_feat["front_consecutive"],
            "连号组数"
        )

        # ── 6. 号码频率异常（热号/冷号分析） ──
        freq_anomalies = self._detect_frequency_anomalies(
            batch_feat["front_freq"],
            global_feat["front_freq"],
            len(batch_draws),
            len(global_draws),
        )
        if freq_anomalies:
            report["anomalies"].extend(freq_anomalies)

        # ── 生成文字结论 ──
        report["notes"] = self._generate_notes(report)

        self._print_report(report)
        return report

    def _compare_distributions(self, batch_dist: Dict,
                                global_dist: Dict, name: str) -> Dict:
        """比较两个分布（Counter/字典格式）的差异"""
        all_keys = set(batch_dist.keys()) | set(global_dist.keys())
        batch_total = sum(batch_dist.values())
        global_total = sum(global_dist.values())

        comparison = {"name": name, "details": []}
        for key in all_keys:
            b_cnt = batch_dist.get(key, 0)
            g_cnt = global_dist.get(key, 0)
            b_rate = b_cnt / batch_total if batch_total else 0
            g_rate = g_cnt / global_total if global_total else 0
            diff = b_rate - g_rate
            comparison["details"].append({
                "key": str(key),
                "batch_rate": round(b_rate, 4),
                "global_rate": round(g_rate, 4),
                "diff": round(diff, 4),
            })
        return comparison

    def _detect_frequency_anomalies(self, batch_freq: List[int],
                                     global_freq: List[int],
                                     batch_n: int, global_n: int) -> List[str]:
        """
        检测号码频率异常
        某号码在这批中出现频率显著偏离全局预期 → 可能是短期规律
        """
        anomalies = []
        expected_per_num = batch_n * 5 / 35  # 每号码在N期中预期出现次数

        for i in range(35):
            num = i + 1
            batch_cnt = batch_freq[i]
            global_cnt = global_freq[i]
            # 计算这批中的出现率 vs 全局出现率
            batch_rate = batch_cnt / batch_n if batch_n else 0
            global_rate = global_cnt / global_n if global_n else 0

            # 用简单的阈值判断：这批出现率超全局 50% 以上算异常
            if global_rate > 0 and batch_rate > global_rate * 1.5:
                anomalies.append(
                    f"号码{num:02d}短期偏热：这批出现{batch_cnt}次 "
                    f"(预期约{expected_per_num:.1f}次)，"
                    f"全局频率{global_rate:.3f}，这批频率{batch_rate:.3f}"
                )
            elif global_rate > 0 and batch_rate < global_rate * 0.5 and batch_cnt == 0:
                anomalies.append(
                    f"号码{num:02d}短期偏冷：这批出现0次，"
                    f"全局频率{global_rate:.3f}"
                )

        return anomalies[:5]  # 最多返回5条，避免刷屏

    def _generate_notes(self, report: Dict) -> str:
        """根据差异报告生成文字结论"""
        notes = []
        if report["anomalies"]:
            notes.append("⚠️ 发现异常：")
            for a in report["anomalies"]:
                notes.append(f"  - {a}")
        else:
            notes.append("✅ 这批数据与全局特征基本一致，未发现明显异常")

        # 添加和值结论
        sum_info = report["diffs"].get("front_sum_mean", {})
        if sum_info:
            diff_pct = sum_info.get("diff_pct", 0)
            if abs(diff_pct) > 5:
                notes.append(
                    f"📊 前区和值：这批{diff_pct:+.1f}% "
                    f"({'偏高' if diff_pct > 0 else '偏低'}于全局)"
                )

        return "\n".join(notes)

    def _print_report(self, report: Dict):
        """打印回归分析报告"""
        print(f"\n{'─'*50}")
        print(f"[批次回归分析] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  批次: {report['batch_size']}期  |  "
              f"全局: {report['global_size']}期")
        print(f"\n{report['notes']}")
        print(f"{'─'*50}\n")

    def compute_feature_diff_vector(self, batch_feat: Dict, global_feat: Dict) -> List[float]:
        """
        计算两批特征之间的差异向量（用于后续的校准/学习）
        返回归一化的差异向量
        """
        diff_vector = []

        # 和值差异（归一化到0~1）
        gf = global_feat["front_sum"]
        bf = batch_feat["front_sum"]
        if gf["std"] > 0:
            diff_vector.append(abs(bf["mean"] - gf["mean"]) / (gf["std"] * 3))
        else:
            diff_vector.append(0.0)

        # 跨度差异
        span_diff = abs(batch_feat["front_span_avg"] - global_feat["front_span_avg"])
        diff_vector.append(min(span_diff / 34, 1.0))  # 34 = 最大可能跨度

        return diff_vector
