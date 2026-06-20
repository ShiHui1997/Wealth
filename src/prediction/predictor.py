"""
大乐透预测器
基于历史特征生成候选号码，并按与真实开奖的相似度排序
"""
import random
from typing import List, Dict, Tuple
from src.analysis.analyzer import DaletouAnalyzer


class DaletouPredictor:
    """
    预测器核心逻辑：
    ① 分析历史数据，学习"随机性特征"
    ② 生成大量候选号码
    ③ 按相似度打分，选出最"像"真实开奖的号码
    """

    def __init__(self, front_range: int = 35, back_range: int = 12):
        self.analyzer = DaletouAnalyzer(front_range, back_range)

    def predict(self, draws: List[Dict], top_n: int = 3,
                candidates_count: int = 100,
                storage=None) -> List[Tuple[Dict, float]]:
        """
        预测下一期号码
        storage: 可选，传入则以它加载校准权重
        Returns: [(号码dict, 相似度得分), ...] 按得分降序
        """
        print(f"\n[预测] 基于最近 {len(draws)} 期数据进行分析...")

        # 加载校准权重（如果可用）
        weights = None
        if storage:
            calibrations = storage.get_all_calibrations()
            weight_keys = {
                "front_sum": 0.25,
                "odd_even": 0.15,
                "zone":      0.20,
                "span":      0.15,
                "consecutive": 0.10,
                "back_sum":  0.10,
                "frequency":  0.05,
            }
            loaded = {}
            for key in weight_keys:
                cal_key = f"weight_{key}"
                if cal_key in calibrations:
                    loaded[key] = calibrations[cal_key]
            if loaded:
                # 归一化
                total = sum(loaded.values())
                weights = {k: v / total for k, v in loaded.items()}
                print(f"[预测] 使用校准权重: {weights}")
            else:
                print("[预测] 使用默认权重")

        # 第一步：从历史数据中提取特征（"学习随机性"）
        features = self.analyzer.build_features(draws)

        # 第二步：用多种策略生成候选号码
        all_candidates = []

        # 策略1：频率加权（占60%）
        c1 = self.analyzer.generate_candidates(features, candidates_count // 2, "weighted")
        all_candidates.extend(c1)

        # 策略2：模式约束（占30%）
        c2 = self.analyzer.generate_candidates(features, candidates_count // 3, "pattern")
        all_candidates.extend(c2)

        # 策略3：纯随机基线（占10%）
        c3 = self.analyzer.generate_candidates(features, candidates_count // 10, "uniform")
        all_candidates.extend(c3)

        # 去重
        unique = []
        seen = set()
        for c in all_candidates:
            key = (tuple(c["front"]), tuple(c["back"]))
            if key not in seen:
                seen.add(key)
                unique.append(c)
        all_candidates = unique

        print(f"[预测] 共生成 {len(all_candidates)} 个不重复候选号码")

        # 第三步：对每个候选计算相似度得分
        scored = []
        for cand in all_candidates:
            score = self.analyzer.compute_similarity_score(
                cand, features, weights=weights
            )
            scored.append((cand, score))

        # 按得分降序排列
        scored.sort(key=lambda x: x[1], reverse=True)

        print(f"[预测] 相似度打分完成，Top3得分: "
              f"{scored[0][1]:.4f}, {scored[1][1]:.4f}, {scored[2][1]:.4f}")

        return scored[:top_n]

    def format_prediction(self, prediction: List[Tuple[Dict, float]]) -> str:
        """格式化预测结果为可读文本"""
        lines = ["🎯 大乐透预测推荐（按与历史开奖相似度排序）\n"]
        for i, (nums, score) in enumerate(prediction, 1):
            front_str = " ".join(f"{n:02d}" for n in nums["front"])
            back_str = " ".join(f"{n:02d}" for n in nums["back"])
            lines.append(
                f"第{i}注: 前区 [{front_str}]  后区 [{back_str}]  "
                f"(相似度: {score:.4f})"
            )
        lines.append("\n⚠️  温馨提示：彩票具有随机性，本预测仅供娱乐参考")
        return "\n".join(lines)

    def format_prediction_html(self, prediction: List[Tuple[Dict, float]]) -> str:
        """格式化为HTML（适合PushPlus推送）"""
        rows = ""
        for i, (nums, score) in enumerate(prediction, 1):
            front_str = " ".join(f"{n:02d}" for n in nums["front"])
            back_str = " ".join(f"{n:02d}" for n in nums["back"])
            rows += f"""
            <tr>
                <td style="padding:8px 15px;">第{i}注</td>
                <td style="padding:8px 15px;font-weight:bold;color:#e74c3c;">{front_str}</td>
                <td style="padding:8px 15px;font-weight:bold;color:#3498db;">{back_str}</td>
                <td style="padding:8px 15px;color:#888;">{score:.4f}</td>
            </tr>"""
        return f"""
        <div style="font-family:雅黑,sans-serif;padding:20px;">
            <h2 style="color:#2c3e50;">🎯 大乐透本期预测</h2>
            <p style="color:#888;">基于历史开奖数据的相似度分析，以下3注与真实开奖随机性最为接近：</p>
            <table style="border-collapse:collapse;margin-top:15px;width:100%;">
                <tr style="background:#f5f6fa;">
                    <th style="padding:8px 15px;">序号</th>
                    <th style="padding:8px 15px;">前区(5个)</th>
                    <th style="padding:8px 15px;">后区(2个)</th>
                    <th style="padding:8px 15px;">相似度</th>
                </tr>
                {rows}
            </table>
            <p style="margin-top:20px;color:#e74c3c;font-size:13px;">
                ⚠️ 彩票具有随机性，本预测仅供娱乐参考，请理性购彩
            </p>
        </div>
        """
