"""
自我校准模块
根据历史验证结果，自动调整预测策略的权重和参数
让系统随着数据积累越来越"懂"大乐透的随机性
"""
from typing import Dict, List
import json


class SelfCalibrator:
    """
    自我校准器
    读取历史验证结果 → 分析哪类特征最"准" → 调整相似度权重
    """

    def __init__(self, storage):
        self.storage = storage
        self.default_weights = {
            "front_sum":    0.25,
            "odd_even":    0.15,
            "zone":         0.20,
            "span":         0.15,
            "consecutive":  0.10,
            "back_sum":     0.10,
            "frequency":    0.05,
        }

    def calibrate(self, force: bool = False):
        """
        执行一次校准
        读取所有验证结果，计算各维度与命中率的相关性
        返回新的权重配置
        """
        stats = self.storage.get_verification_stats()
        # 首次校准门槛: 5期（让系统尽早开始学习）
        # 后续校准: 每积累新数据就重新校准
        min_threshold = 5
        if stats["total_verified"] < min_threshold and not force:
            print(f"[校准] 验证数据不足（{stats['total_verified']}期），"
                  f"需要至少{min_threshold}期才能校准")
            return self._load_current_weights()

        print(f"\n[校准] 基于 {stats['total_verified']} 期验证结果进行自我调整...")

        # 获取验证详情
        details = self.storage.get_verification_details()

        # 分析并生成新权重
        new_weights = self._compute_new_weights(details, stats)

        # 保存到数据库
        for name, value in new_weights.items():
            self.storage.save_calibration(
                f"weight_{name}",
                value,
                f"基于{stats['total_verified']}期验证结果自动校准"
            )

        # 校准次数 +1，并自动轮换种子
        calib_count = self.storage.incr_calibration_count()
        new_seed = 42 + calib_count * 7
        self.storage.set_current_seed(new_seed)
        print(f"[校准] 校准次数更新为 {calib_count}，种子已轮换为 {new_seed}")

        # 也保存命中率统计
        self._save_hit_stats(stats)

        print(f"[校准] 完成！新权重：")
        for name, weight in new_weights.items():
            default = self.default_weights[name]
            arrow = "↑" if weight > default else ("↓" if weight < default else "→")
            print(f"  {name}: {default:.4f} → {weight:.4f}  {arrow}")

        return new_weights

    def _compute_new_weights(self, details: List[Dict], stats: Dict) -> Dict:
        """
        根据验证结果调整权重
        逻辑：
        - 命中期（前区>=3 或 后区>=1）的平均相似度
          若明显高于未命中期 → 相似度指标有效，提高权重集中度
        - 若两批平均相似度接近 → 指标区分度低，降低权重
        """
        hit_scores = []
        miss_scores = []

        for v in details:
            is_hit = (v["front_match"] >= 3) or (v["back_match"] >= 1)
            if is_hit:
                hit_scores.append(v["avg_similarity"])
            else:
                miss_scores.append(v["avg_similarity"])

        new_weights = dict(self.default_weights)

        if hit_scores and miss_scores:
            hit_avg = sum(hit_scores) / len(hit_scores)
            miss_avg = sum(miss_scores) / len(miss_scores)
            ratio = hit_avg / miss_avg if miss_avg > 0 else 1.0

            print(f"[校准] 命中期内均相似度: {hit_avg:.4f}")
            print(f"[校准] 未命中期平均相似度: {miss_avg:.4f}")
            print(f"[校准] 命中/未命中比: {ratio:.3f}")

            if ratio > 1.15:
                # 相似度指标有效，向区分度高的维度集中
                new_weights["front_sum"] = min(0.35, self.default_weights["front_sum"] * 1.25)
                new_weights["zone"]      = min(0.30, self.default_weights["zone"] * 1.25)
                new_weights["frequency"]  = max(0.01, self.default_weights["frequency"] * 0.75)
            elif ratio < 0.95:
                # 区分度低，降低确定性权重，提高随机性
                new_weights["front_sum"] = max(0.10, self.default_weights["front_sum"] * 0.8)
                new_weights["zone"]      = max(0.10, self.default_weights["zone"] * 0.8)
                new_weights["frequency"]  = min(0.15, self.default_weights["frequency"] * 1.5)
        else:
            # 数据不足，轻微基于命中率调整
            hit_rate = stats.get("any_front_3plus_rate", 0)
            if hit_rate < 0.10:
                new_weights["front_sum"] = min(0.35, self.default_weights["front_sum"] * 1.2)
                new_weights["zone"]      = min(0.30, self.default_weights["zone"] * 1.2)
            elif hit_rate > 0.40:
                # 命中率已经不错，轻微向默认值回归
                pass

        # 归一化权重（使总和为1）
        total = sum(new_weights.values())
        new_weights = {k: v / total for k, v in new_weights.items()}

        return new_weights

    def _save_hit_stats(self, stats: Dict):
        """保存命中率统计到校准表"""
        self.storage.save_calibration(
            "stats_total_verified",
            float(stats["total_verified"]),
            f"截至最近校准"
        )
        self.storage.save_calibration(
            "stats_front_3plus_rate",
            stats.get("any_front_3plus_rate", 0),
            "前区命中>=3的比例"
        )
        self.storage.save_calibration(
            "stats_back_1plus_rate",
            stats.get("any_back_1plus_rate", 0),
            "后区命中>=1的比例"
        )

    def _load_current_weights(self) -> Dict:
        """从数据库加载当前权重（若无则返回默认）"""
        weights = {}
        for name in self.default_weights:
            val = self.storage.get_calibration(f"weight_{name}")
            weights[name] = val if val is not None else self.default_weights[name]
        return weights

    def get_current_weights(self) -> Dict:
        """获取当前生效的权重（供 predictor 使用）"""
        return self._load_current_weights()

    def print_calibration_status(self):
        """打印当前校准状态"""
        weights = self._load_current_weights()
        stats = self.storage.get_verification_stats()

        print(f"\n{'='*45}")
        print(f"[校准状态] 已验证 {stats['total_verified']} 期")
        if stats["total_verified"] > 0:
            print(f"  前区命中>=3比例: {stats.get('any_front_3plus_rate', 0)*100:.1f}%")
            print(f"  后区命中>=1比例: {stats.get('any_back_1plus_rate', 0)*100:.1f}%")
            print(f"  前区命中分布: {stats.get('front_match_dist', {})}")
            print(f"  后区命中分布: {stats.get('back_match_dist', {})}")
        print(f"\n  当前权重配置:")
        for name, weight in weights.items():
            default = self.default_weights[name]
            sign = "+" if weight > default else ("-" if weight < default else " ")
            print(f"    {name:15s}: {weight:.4f}  ({sign}{abs(weight-default):.4f})")
        print(f"{'='*45}\n")
