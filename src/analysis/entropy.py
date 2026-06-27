"""
信息熵诊断模块

用大乐透历史数据计算多种熵指标，判断系统是否仍接近“理想随机”。
不依赖 numpy/scipy，仅使用标准库。
"""
import math
import json
from collections import Counter
from typing import List, Dict, Tuple, Optional


class EntropyDiagnostics:
    """
    大乐透信息熵诊断

    关键指标：
    1. 边际熵：单个号码出现频率分布的熵（前区/后区）
    2. 组合经验熵：把每期整注当符号，计算历史样本多样性
    3. 互信息：相邻期（或lag期）号码之间的信息传递
    """

    def __init__(self, draws: List[Dict]):
        self.draws = sorted(draws, key=lambda x: x["issue"])

    # ═══════════════════════════════════════════
    # 基础工具
    # ═══════════════════════════════════════════

    @staticmethod
    def _entropy_from_counts(counts: List[int], n_bins: int) -> Tuple[float, float, float]:
        """
        根据频数计算香农熵、最大熵、归一化熵
        """
        total = sum(counts)
        if total == 0 or n_bins <= 0:
            return 0.0, 0.0, 0.0

        H = 0.0
        for c in counts:
            if c > 0:
                p = c / total
                H -= p * math.log2(p)

        H_max = math.log2(n_bins)
        ratio = H / H_max if H_max > 0 else 0.0
        return H, H_max, ratio

    # ═══════════════════════════════════════════
    # 1. 边际熵
    # ═══════════════════════════════════════════

    def marginal_entropy(self, zone: str = "front") -> Dict:
        """
        计算前区（35个号码）或后区（12个号码）号码频率的边际熵

        zone: 'front' -> 35 bins, 'back' -> 12 bins
        """
        if zone == "front":
            n_bins = 35
            min_num, max_num = 1, 35
        elif zone == "back":
            n_bins = 12
            min_num, max_num = 1, 12
        else:
            raise ValueError("zone must be 'front' or 'back'")

        counts = [0] * n_bins
        for d in self.draws:
            for num in d[zone]:
                if min_num <= num <= max_num:
                    counts[num - min_num] += 1

        H, H_max, ratio = self._entropy_from_counts(counts, n_bins)

        # 卡方均匀性检验（仅作参考，不依赖 scipy）
        total = sum(counts)
        expected = total / n_bins if n_bins > 0 else 0
        chi2 = 0.0
        if expected > 0:
            for c in counts:
                chi2 += ((c - expected) ** 2) / expected

        return {
            "zone": zone,
            "entropy": H,
            "max_entropy": H_max,
            "ratio": ratio,
            "chi2_uniform": chi2,
            "expected_per_bin": expected,
            "total_draws": len(self.draws),
            "total_occurrences": total,
        }

    # ═══════════════════════════════════════════
    # 2. 组合经验熵
    # ═══════════════════════════════════════════

    def combination_empirical_entropy(self) -> Dict:
        """
        把每期整注（前区5码 + 后区2码）当作一个离散符号，
        计算历史样本的经验熵。

        注意：由于样本空间约 2100 万种，而历史仅 ~3000 期，
        该熵远小于理论最大熵，反映的是“历史样本多样性”，
        不是“系统真实不确定度”。
        """
        symbols = []
        for d in self.draws:
            sym = tuple(sorted(d["front"])) + tuple(sorted(d["back"]))
            symbols.append(sym)

        counts = Counter(symbols)
        count_values = list(counts.values())
        total = len(symbols)

        H = 0.0
        for c in count_values:
            if c > 0 and total > 0:
                p = c / total
                H -= p * math.log2(p)

        # 理论最大熵 = log2(C(35,5) * C(12,2))
        from math import comb
        total_space = comb(35, 5) * comb(12, 2)
        H_max = math.log2(total_space)

        # 在只有 N 个样本时，经验熵的理论上限 = log2(N)
        H_sample_max = math.log2(total) if total > 0 else 0

        return {
            "entropy": H,
            "max_entropy_full": H_max,
            "max_entropy_sample": H_sample_max,
            "ratio_to_full": H / H_max if H_max > 0 else 0,
            "ratio_to_sample": H / H_sample_max if H_sample_max > 0 else 0,
            "unique_combinations": len(counts),
            "total_draws": total,
            "duplicate_rate": 1 - len(counts) / total if total > 0 else 0,
        }

    # ═══════════════════════════════════════════
    # 3. 互信息：相邻期之间的信息传递
    # ═══════════════════════════════════════════

    def _binary_series(self, zone: str, number: int) -> List[int]:
        """
        构建某个号码在每期是否出现的二进制序列（按issue排序）
        """
        return [1 if number in d[zone] else 0 for d in self.draws]

    @staticmethod
    def _binary_entropy(series: List[int]) -> float:
        """二进制序列的熵"""
        total = len(series)
        if total == 0:
            return 0.0
        p1 = sum(series) / total
        p0 = 1 - p1
        H = 0.0
        if p0 > 0:
            H -= p0 * math.log2(p0)
        if p1 > 0:
            H -= p1 * math.log2(p1)
        return H

    def _mutual_information_binary(self, series: List[int], lag: int = 1) -> float:
        """
        计算二进制序列与其 lag 滞后版本之间的互信息。
        I(X_t; X_{t-lag}) = H(X_t) + H(X_{t-lag}) - H(X_t, X_{t-lag})
        """
        if len(series) <= lag:
            return 0.0

        x = series[lag:]
        y = series[:-lag]
        n = len(x)

        # 联合分布 (0,0), (0,1), (1,0), (1,1)
        joint = [[0, 0], [0, 0]]
        for a, b in zip(x, y):
            joint[a][b] += 1

        H_x = self._binary_entropy(x)
        H_y = self._binary_entropy(y)

        H_xy = 0.0
        for i in range(2):
            for j in range(2):
                c = joint[i][j]
                if c > 0 and n > 0:
                    p = c / n
                    H_xy -= p * math.log2(p)

        mi = H_x + H_y - H_xy
        # 由于浮点误差，互信息可能为极小的负数，截断到0
        return max(0.0, mi)

    def mutual_information_summary(self, zone: str = "front", lag: int = 1) -> Dict:
        """
        对 zone 中所有号码分别计算与 lag 滞后自身的互信息，返回汇总统计。

        如果彩票是独立随机的，互信息应接近 0 bits。
        """
        if zone == "front":
            numbers = range(1, 36)
        elif zone == "back":
            numbers = range(1, 13)
        else:
            raise ValueError("zone must be 'front' or 'back'")

        mis = []
        for num in numbers:
            series = self._binary_series(zone, num)
            mi = self._mutual_information_binary(series, lag=lag)
            mis.append({"number": num, "mi": mi})

        mis.sort(key=lambda x: x["mi"], reverse=True)
        avg_mi = sum(x["mi"] for x in mis) / len(mis) if mis else 0

        return {
            "zone": zone,
            "lag": lag,
            "average_mi": avg_mi,
            "max_mi": mis[0]["mi"] if mis else 0,
            "max_mi_number": mis[0]["number"] if mis else None,
            "top5": mis[:5],
            "interpretation": (
                "互信息接近0 → 序列近似独立；"
                "若某号码MI显著>0，可能意味着相邻期间存在微弱依赖"
            ),
        }

    # ═══════════════════════════════════════════
    # 综合报告
    # ═══════════════════════════════════════════

    def full_report(self) -> Dict:
        """生成完整的熵诊断报告"""
        front_entropy = self.marginal_entropy("front")
        back_entropy = self.marginal_entropy("back")
        combo_entropy = self.combination_empirical_entropy()
        front_mi = self.mutual_information_summary("front", lag=1)
        back_mi = self.mutual_information_summary("back", lag=1)

        # 健康度判断：边际熵比值应在 0.95 以上；互信息平均应接近 0
        health_flags = []
        if front_entropy["ratio"] < 0.95:
            health_flags.append("前区边际熵偏低，号码分布不均匀")
        if back_entropy["ratio"] < 0.90:
            health_flags.append("后区边际熵偏低，号码分布不均匀")
        if front_mi["average_mi"] > 0.01:
            health_flags.append(f"前区相邻期互信息 avg={front_mi['average_mi']:.4f}，存在依赖迹象")
        if back_mi["average_mi"] > 0.02:
            health_flags.append(f"后区相邻期互信息 avg={back_mi['average_mi']:.4f}，存在依赖迹象")

        return {
            "front_entropy": front_entropy,
            "back_entropy": back_entropy,
            "combination_empirical_entropy": combo_entropy,
            "front_mi": front_mi,
            "back_mi": back_mi,
            "health_flags": health_flags,
            "health_status": "ok" if not health_flags else "warning",
        }

    def print_report(self) -> None:
        """打印可读的熵诊断报告"""
        report = self.full_report()
        print("\n" + "=" * 50)
        print("[信息熵诊断报告]")
        print("=" * 50)

        fe = report["front_entropy"]
        print(f"\n前区边际熵:")
        print(f"  H = {fe['entropy']:.4f} bits / H_max = {fe['max_entropy']:.4f} bits")
        print(f"  归一化 = {fe['ratio']:.4f} (越接近1越均匀)")
        print(f"  卡方(均匀) = {fe['chi2_uniform']:.2f}, 每期期望出现次数 = {fe['expected_per_bin']:.2f}")

        be = report["back_entropy"]
        print(f"\n后区边际熵:")
        print(f"  H = {be['entropy']:.4f} bits / H_max = {be['max_entropy']:.4f} bits")
        print(f"  归一化 = {be['ratio']:.4f}")
        print(f"  卡方(均匀) = {be['chi2_uniform']:.2f}, 每期期望出现次数 = {be['expected_per_bin']:.2f}")

        ce = report["combination_empirical_entropy"]
        print(f"\n组合经验熵:")
        print(f"  H = {ce['entropy']:.4f} bits")
        print(f"  理论最大熵 = {ce['max_entropy_full']:.2f} bits (2100万样本空间)")
        print(f"  样本最大熵 = {ce['max_entropy_sample']:.2f} bits (受N限制)")
        print(f"  唯一组合数 = {ce['unique_combinations']} / {ce['total_draws']} 期")
        print(f"  重复率 = {ce['duplicate_rate']:.4f}")

        fmi = report["front_mi"]
        bmi = report["back_mi"]
        print(f"\n相邻期互信息 (前区):")
        print(f"  平均 MI = {fmi['average_mi']:.6f} bits")
        print(f"  最大 MI = {fmi['max_mi']:.6f} bits (号码 {fmi['max_mi_number']})")
        print(f"\n相邻期互信息 (后区):")
        print(f"  平均 MI = {bmi['average_mi']:.6f} bits")
        print(f"  最大 MI = {bmi['max_mi']:.6f} bits (号码 {bmi['max_mi_number']})")

        print(f"\n健康状态: {report['health_status']}")
        if report["health_flags"]:
            for flag in report["health_flags"]:
                print(f"  ⚠️ {flag}")
        else:
            print("  ✅ 无显著异常，数据表现接近理想随机")
        print("=" * 50 + "\n")
