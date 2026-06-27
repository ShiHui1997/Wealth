"""
大乐透开奖数据分析模块
学习历史开奖数据的统计特征，用于生成"相似度最高"的号码
"""
import json
import math
from typing import List, Dict, Tuple, Optional
from collections import Counter
import random


class DaletouAnalyzer:
    """
    大乐透数据分析器
    从历史数据中学习统计特征，计算与"真实随机性"的相似度
    """

    def __init__(self, front_range: int = 35, back_range: int = 12):
        self.front_range = front_range  # 前区范围 1-35
        self.back_range = back_range    # 后区范围 1-12

    # ═══════════════════════════════════════════════
    # 1. 基础统计分析
    # ═══════════════════════════════════════════════

    def frequency_analysis(self, draws: List[Dict]) -> Dict:
        """
        号码出现频率分析
        Returns: {
            "front_freq": [前区1-35的出现次数],
            "back_freq": [后区1-12的出现次数],
            "front_hot": [(号码, 次数), ...] 前区热号,
            "front_cold": [(号码, 次数), ...] 前区冷号,
            "back_hot": [...],
            "back_cold": [...],
        }
        """
        front_counter = Counter()
        back_counter = Counter()

        for draw in draws:
            for n in draw["front"]:
                front_counter[n] += 1
            for n in draw["back"]:
                back_counter[n] += 1

        total = len(draws)

        return {
            "front_freq": [front_counter.get(i, 0) for i in range(1, self.front_range + 1)],
            "back_freq": [back_counter.get(i, 0) for i in range(1, self.back_range + 1)],
            "front_avg_freq": total * 5 / self.front_range,  # 理论平均出现次数
            "back_avg_freq": total * 2 / self.back_range,
            "total_draws": total,
        }

    def sum_analysis(self, draws: List[Dict]) -> Dict:
        """
        前区和值分析（5个前区号码相加）
        大乐透前区和值范围：15（1+2+3+4+5）~ 165（31+32+33+34+35）
        理论平均值约90
        """
        sums = [sum(d["front"]) for d in draws]
        back_sums = [sum(d["back"]) for d in draws]

        def stats(nums):
            if not nums:
                return {}
            return {
                "min": min(nums),
                "max": max(nums),
                "mean": sum(nums) / len(nums),
                "median": sorted(nums)[len(nums) // 2],
                "std": math.sqrt(sum((x - sum(nums)/len(nums))**2 for x in nums) / len(nums)),
            }

        return {
            "front_sum": stats(sums),
            "back_sum": stats(back_sums),
        }

    def odd_even_analysis(self, draws: List[Dict]) -> Dict:
        """奇偶比分析"""
        front_patterns = Counter()
        back_patterns = Counter()

        for draw in draws:
            f_odd = sum(1 for n in draw["front"] if n % 2 == 1)
            b_odd = sum(1 for n in draw["back"] if n % 2 == 1)
            front_patterns[(f_odd, 5 - f_odd)] += 1
            back_patterns[(b_odd, 2 - b_odd)] += 1

        return {
            "front_odd_even": dict(front_patterns),
            "back_odd_even": dict(back_patterns),
        }

    def zone_analysis(self, draws: List[Dict]) -> Dict:
        """
        区间分布分析
        前区三分：1-12（小）、13-24（中）、25-35（大）
        后区二分：1-6（小）、7-12（大）
        """
        front_zones = Counter()
        back_zones = Counter()

        for draw in draws:
            fz = [0, 0, 0]
            for n in draw["front"]:
                if n <= 12:
                    fz[0] += 1
                elif n <= 24:
                    fz[1] += 1
                else:
                    fz[2] += 1
            front_zones[tuple(fz)] += 1

            bz = [0, 0]
            for n in draw["back"]:
                if n <= 6:
                    bz[0] += 1
                else:
                    bz[1] += 1
            back_zones[tuple(bz)] += 1

        return {
            "front_zone": dict(front_zones),
            "back_zone": dict(back_zones),
        }

    def span_analysis(self, draws: List[Dict]) -> Dict:
        """跨度分析（最大号-最小号）"""
        front_spans = [max(d["front"]) - min(d["front"]) for d in draws]
        back_spans = [max(d["back"]) - min(d["back"]) for d in draws]

        return {
            "front_span_avg": sum(front_spans) / len(front_spans) if front_spans else 0,
            "back_span_avg": sum(back_spans) / len(back_spans) if back_spans else 0,
        }

    def consecutive_analysis(self, draws: List[Dict]) -> Dict:
        """连号分析（如12-13或34-35-36这样的相邻号码）"""
        front_consecutive = Counter()  # key: 连号组数
        back_consecutive = Counter()

        for draw in draws:
            f_sorted = sorted(draw["front"])
            b_sorted = sorted(draw["back"])

            f_groups = self._count_consecutive_groups(f_sorted)
            b_groups = self._count_consecutive_groups(b_sorted)

            front_consecutive[len(f_groups)] += 1
            back_consecutive[len(b_groups)] += 1

        return {
            "front_consecutive": dict(front_consecutive),
            "back_consecutive": dict(back_consecutive),
        }

    def _count_consecutive_groups(self, nums: List[int]) -> List[List[int]]:
        """找出连续的号码组"""
        if not nums:
            return []
        groups = [[nums[0]]]
        for n in nums[1:]:
            if n == groups[-1][-1] + 1:
                groups[-1].append(n)
            else:
                groups.append([n])
        return groups

    # ═══════════════════════════════════════════════
    # 2. 相似度计算（核心）
    # ═══════════════════════════════════════════════

    def compute_similarity_score(self, candidate: Dict,
                                 features: Dict,
                                 weights: Optional[Dict] = None) -> float:
        """
        计算候选号码与历史数据特征的相似度得分
        得分越高，越"像"真实开奖号码

        candidate: {"front": [1,5,12,23,35], "back": [3,8]}
        features: 由 build_features 生成的历史特征
        weights: 各维度权重字典（可选，默认使用内置权重）
        Returns: 0~1 之间的相似度得分
        """
        # 默认权重（与 calibration 模块中的 default_weights 保持一致）
        if weights is None:
            weights = {
                "front_sum": 0.25,
                "odd_even": 0.15,
                "zone":      0.20,
                "span":      0.15,
                "consecutive": 0.10,
                "back_sum":  0.10,
                "frequency":  0.05,
            }

        score = 0.0
        total_weight = 0.0

        # ① 和值相似度
        w = weights.get("front_sum", 0.25)
        total_weight += w
        cand_front_sum = sum(candidate["front"])
        fs = features["front_sum"]
        if fs["std"] > 0:
            z = abs(cand_front_sum - fs["mean"]) / fs["std"]
            score += w * max(0, 1 - z / 3)

        # ② 奇偶比相似度
        w = weights.get("odd_even", 0.15)
        total_weight += w
        f_odd = sum(1 for n in candidate["front"] if n % 2 == 1)
        f_pattern = (f_odd, 5 - f_odd)
        if f_pattern in features["front_odd_even"]:
            freq = features["front_odd_even"][f_pattern]
            score += w * (freq / features["total_draws"])

        # ③ 区间分布相似度
        w = weights.get("zone", 0.20)
        total_weight += w
        fz = [0, 0, 0]
        for n in candidate["front"]:
            if n <= 12: fz[0] += 1
            elif n <= 24: fz[1] += 1
            else: fz[2] += 1
        fz_tuple = tuple(fz)
        if fz_tuple in features["front_zone"]:
            freq = features["front_zone"][fz_tuple]
            score += w * (freq / features["total_draws"])

        # ④ 跨度相似度
        w = weights.get("span", 0.15)
        total_weight += w
        cand_front_span = max(candidate["front"]) - min(candidate["front"])
        expected_span = features["front_span_avg"]
        span_diff = abs(cand_front_span - expected_span)
        max_span = self.front_range - 1
        score += w * max(0, 1 - span_diff / max_span)

        # ⑤ 连号特征相似度
        w = weights.get("consecutive", 0.10)
        total_weight += w
        f_groups = self._count_consecutive_groups(sorted(candidate["front"]))
        num_groups = len(f_groups)
        if num_groups in features["front_consecutive"]:
            freq = features["front_consecutive"][num_groups]
            score += w * (freq / features["total_draws"])

        # ⑥ 后区和值
        w = weights.get("back_sum", 0.10)
        total_weight += w
        cand_back_sum = sum(candidate["back"])
        bs = features["back_sum"]
        if bs["std"] > 0:
            z = abs(cand_back_sum - bs["mean"]) / bs["std"]
            score += w * max(0, 1 - z / 2)

        # ⑦ 号码频率偏离度
        w = weights.get("frequency", 0.05)
        total_weight += w
        ff = features["front_freq"]
        avg_ff = features["front_avg_freq"]
        cand_avg_freq = sum(ff[n-1] for n in candidate["front"]) / 5
        freq_diff = abs(cand_avg_freq - avg_ff) / avg_ff if avg_ff > 0 else 1
        score += w * max(0, 1 - freq_diff)

        return score / total_weight if total_weight > 0 else 0.0

    # ═══════════════════════════════════════════════
    # 3. 特征构建
    # ═══════════════════════════════════════════════

    def build_features(self, draws: List[Dict]) -> Dict:
        """
        从历史事件中提取所有统计特征
        这是"学习"的核心——把历史数据的随机性特征提炼出来
        """
        print(f"[分析] 正在分析 {len(draws)} 期历史数据...")

        features = {}
        features.update(self.frequency_analysis(draws))
        features.update(self.sum_analysis(draws))
        features.update(self.odd_even_analysis(draws))
        features.update(self.zone_analysis(draws))
        features.update(self.span_analysis(draws))
        features.update(self.consecutive_analysis(draws))

        print(f"[分析] 特征构建完成")
        print(f"  前区和值均值: {features['front_sum']['mean']:.1f} "
              f"(范围:{features['front_sum']['min']}~{features['front_sum']['max']})")
        print(f"  前区跨度均值: {features['front_span_avg']:.1f}")
        print(f"  总期数: {features['total_draws']}")

        return features

    # ═══════════════════════════════════════════════
    # 4. 生成候选号码（基于特征）
    # ═══════════════════════════════════════════════

    def generate_candidates(self, features: Dict, count: int = 1000,
                           strategy: str = "smart") -> List[Dict]:
        """
        基于历史特征生成候选号码
        strategy:
          - "smart": 智能生成（按特征定向构造，非随机搜索）← 默认
          - "weighted": 按历史频率加权随机
          - "pattern": 按历史模式约束随机
          - "uniform": 纯随机基线
        """
        candidates = []
        attempts = 0
        max_attempts = count * 50

        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            cand = self._generate_one(features, strategy)
            if cand and cand not in candidates:
                candidates.append(cand)

        print(f"[生成] 生成 {len(candidates)} 个候选（尝试{attempts}次，策略={strategy}）")
        return candidates

    def _generate_one(self, features: Dict, strategy: str) -> Dict:
        """生成一组号码"""
        if strategy == "uniform":
            front = sorted(random.sample(range(1, self.front_range + 1), 5))
            back = sorted(random.sample(range(1, self.back_range + 1), 2))
        elif strategy == "weighted":
            front = self._weighted_sample(features, "front")
            back = self._weighted_sample(features, "back")
        elif strategy == "pattern":
            front = self._pattern_sample(features)
            back = sorted(random.sample(range(1, self.back_range + 1), 2))
        else:  # smart — 按特征定向构造
            front = self._smart_front(features)
            back = self._smart_back(features)

        return {"front": front, "back": back}

    def _smart_front(self, features: Dict) -> List[int]:
        """
        智能生成前区5个号码：
        按历史特征定向构造，使生成的号码在7维特征空间里接近历史分布
        """
        fs = features["front_sum"]
        target_sum = int(fs["mean"])
        span_avg = int(features["front_span_avg"])

        # 决定奇偶比（按历史频率加权随机选一个）
        fe = features["front_odd_even"]
        fe_patterns = list(fe.keys())
        fe_weights = [fe[p] for p in fe_patterns]
        target_odd, target_even = random.choices(fe_patterns, weights=fe_weights)[0]

        # 决定区间分布（按历史频率加权随机选一个）
        fz = features["front_zone"]
        fz_patterns = list(fz.keys())
        fz_weights = [fz[p] for p in fz_patterns]
        target_zone = random.choices(fz_patterns, weights=fz_weights)[0]

        # 决定连号组数（按历史频率加权随机选一个）
        fc = features["front_consecutive"]
        fc_patterns = list(fc.keys())
        fc_weights = [fc[p] for p in fc_patterns]
        target_groups = random.choices(fc_patterns, weights=fc_weights)[0]

        # 在约束下生成
        front = []
        # 按区间分布选号
        for i, count_in_zone in enumerate(target_zone):
            if count_in_zone == 0:
                continue
            if i == 0:
                low, high = 1, 12
            elif i == 1:
                low, high = 13, 24
            else:
                low, high = 25, 35
            pool = list(range(low, high + 1))
            chosen = random.sample(pool, min(count_in_zone, len(pool)))
            front.extend(chosen)

        # 补足到5个
        while len(front) < 5:
            n = random.randint(1, 35)
            if n not in front:
                front.append(n)
        front = sorted(front[:5])

        # 调整奇偶比
        cur_odd = sum(1 for n in front if n % 2 == 1)
        attempts = 0
        while cur_odd != target_odd and attempts < 200:
            attempts += 1
            if cur_odd < target_odd:
                evens = [n for n in front if n % 2 == 0]
                odds_avail = [n for n in range(1, 36) if n % 2 == 1 and n not in front]
                if evens and odds_avail:
                    front.remove(random.choice(evens))
                    front.append(random.choice(odds_avail))
                    cur_odd += 1
            else:
                odds = [n for n in front if n % 2 == 1]
                evens_avail = [n for n in range(1, 36) if n % 2 == 0 and n not in front]
                if odds and evens_avail:
                    front.remove(random.choice(odds))
                    front.append(random.choice(evens_avail))
                    cur_odd -= 1
            front = sorted(front)

        # 调整和值（微调1-2个号）
        cur_sum = sum(front)
        attempts = 0
        while abs(cur_sum - target_sum) > fs["std"] and attempts < 100:
            attempts += 1
            if cur_sum < target_sum:
                # 换一个更大的号
                smallest = min(front)
                larger_avail = [n for n in range(smallest + 1, 36) if n not in front]
                if larger_avail:
                    front.remove(smallest)
                    front.append(random.choice(larger_avail))
                    front = sorted(front)
                    cur_sum = sum(front)
            else:
                largest = max(front)
                smaller_avail = [n for n in range(1, largest) if n not in front]
                if smaller_avail:
                    front.remove(largest)
                    front.append(random.choice(smaller_avail))
                    front = sorted(front)
                    cur_sum = sum(front)

        return sorted(front[:5])

    def _smart_back(self, features: Dict) -> List[int]:
        """智能生成后区2个号码"""
        bs = features["back_sum"]
        target_sum = int(bs["mean"])

        # 按频率加权选
        freq = features["back_freq"]
        nums = list(range(1, self.back_range + 1))
        weights = [f + 0.5 for f in freq]
        chosen = []
        pool = nums.copy()
        pool_w = weights.copy()
        for _ in range(2):
            idx = random.choices(range(len(pool)), weights=pool_w)[0]
            chosen.append(pool[idx])
            pool.pop(idx)
            pool_w.pop(idx)

        # 微调和值
        cur_sum = sum(chosen)
        if abs(cur_sum - target_sum) > bs["std"]:
            if cur_sum < target_sum:
                smallest = min(chosen)
                larger = [n for n in range(smallest + 1, 13) if n not in chosen]
                if larger:
                    chosen.remove(smallest)
                    chosen.append(random.choice(larger))
            else:
                largest = max(chosen)
                smaller = [n for n in range(1, largest) if n not in chosen]
                if smaller:
                    chosen.remove(largest)
                    chosen.append(random.choice(smaller))

        return sorted(chosen)

    def _weighted_sample(self, features: Dict, area: str) -> List[int]:
        """按历史频率加权随机抽样"""
        if area == "front":
            freq = features["front_freq"]
            nums = list(range(1, self.front_range + 1))
            # 频率越高，被选中概率越大（但加一点噪声避免总是选热号）
            weights = [f + 1 for f in freq]  # +1避免0权重
            chosen = []
            pool = nums.copy()
            pool_weights = weights.copy()
            for _ in range(5):
                if not pool:
                    break
                chosen_idx = random.choices(range(len(pool)), weights=pool_weights)[0]
                chosen.append(pool[chosen_idx])
                pool.pop(chosen_idx)
                pool_weights.pop(chosen_idx)
            return sorted(chosen)
        else:  # back
            freq = features["back_freq"]
            nums = list(range(1, self.back_range + 1))
            weights = [f + 1 for f in freq]
            chosen = []
            pool = nums.copy()
            pool_weights = weights.copy()
            for _ in range(2):
                if not pool:
                    break
                chosen_idx = random.choices(range(len(pool)), weights=pool_weights)[0]
                chosen.append(pool[chosen_idx])
                pool.pop(chosen_idx)
                pool_weights.pop(chosen_idx)
            return sorted(chosen)

    def _pattern_sample(self, features: Dict) -> List[int]:
        """
        按历史模式约束生成
        先决定奇偶比、区间分布，再在这个约束下随机选号
        """
        import random

        # 随机选一个历史上出现过的奇偶比
        fe = features["front_odd_even"]
        patterns = list(fe.keys())
        weights = [fe[p] for p in patterns]
        target_odd, target_even = random.choices(patterns, weights=weights)[0]

        # 随机选一个历史上出现过的区间分布
        fz = features["front_zone"]
        zone_patterns = list(fz.keys())
        zone_w = [fz[p] for p in zone_patterns]
        target_zone = random.choices(zone_patterns, weights=zone_w)[0]

        # 在奇偶+区间双重约束下选号
        front = []
        for i, count_in_zone in enumerate(target_zone):
            low = i * 12 + 1
            high = (i + 1) * 12
            if i == 2:  # 第三区间 25-35
                low = 25
                high = 35
            candidates = [n for n in range(low, high + 1)]
            if not candidates or count_in_zone == 0:
                continue
            chosen = random.sample(candidates, min(count_in_zone, len(candidates)))
            front.extend(chosen)

        # 如果数量不够5个，随机补足（满足奇偶比）
        while len(front) < 5:
            n = random.randint(1, 35)
            if n not in front:
                front.append(n)
        front = sorted(front[:5])

        # 校验奇偶比，若不符合则微调
        cur_odd = sum(1 for n in front if n % 2 == 1)
        attempts = 0
        while cur_odd != target_odd and attempts < 100:
            attempts += 1
            if cur_odd < target_odd:
                # 需要一个奇数替换偶数
                evens = [n for n in front if n % 2 == 0]
                odds_avail = [n for n in range(1, 36) if n % 2 == 1 and n not in front]
                if evens and odds_avail:
                    replace = random.choice(evens)
                    new_num = random.choice(odds_avail)
                    front.remove(replace)
                    front.append(new_num)
                    front = sorted(front)
                    cur_odd += 1
            else:
                odds = [n for n in front if n % 2 == 1]
                evens_avail = [n for n in range(1, 36) if n % 2 == 0 and n not in front]
                if odds and evens_avail:
                    replace = random.choice(odds)
                    new_num = random.choice(evens_avail)
                    front.remove(replace)
                    front.append(new_num)
                    front = sorted(front)
                    cur_odd -= 1

        return front

    # ═══════════════════════════════════════════════
    # 5. 注间分散度分析（投资组合优化）
    # ═══════════════════════════════════════════════

    def compute_dispersion(self, portfolio: List[Dict]) -> float:
        """
        计算注间分散度 D(B)
        D(B) = 1 - 平均重叠率

        参数:
            portfolio: [{"front": [...], "back": [...]}, ...]  3注号码

        返回:
            0~1 之间的分散度（0=完全相同，1=完全不重叠）
        """
        if len(portfolio) < 2:
            return 0.0

        total_pairs = 0
        total_overlap = 0

        for i in range(len(portfolio)):
            for j in range(i + 1, len(portfolio)):
                set_i = set(portfolio[i]["front"])
                set_j = set(portfolio[j]["front"])
                overlap = len(set_i & set_j)
                total_pairs += 1
                total_overlap += overlap

        avg_overlap = total_overlap / total_pairs if total_pairs > 0 else 0
        dispersion = 1 - avg_overlap / 5  # 5个前区号
        return max(0.0, min(1.0, dispersion))

    def compute_core_coverage(self, portfolio: List[Dict],
                              top_candidates: List[Dict]) -> float:
        """
        计算核心覆盖度 C(B)
        衡量3注共享的号码是否在高质量候选中高频出现

        参数:
            portfolio: 选出的3注号码
            top_candidates: Top-K候选（如Top-50），用于频率参考

        返回:
            0~1 之间的核心覆盖度
        """
        if not top_candidates:
            return 0.0

        # 统计 Top-K 候选中每个号码的出现频率
        front_counter = Counter()
        for cand in top_candidates:
            for n in cand["front"]:
                front_counter[n] += 1

        total_cands = len(top_candidates)

        # 找出3注中共享的前区号码（出现在至少2注中）
        from collections import Counter as _Counter
        all_front = []
        for p in portfolio:
            all_front.extend(p["front"])
        appear_count = _Counter(all_front)
        core_numbers = {n for n, cnt in appear_count.items() if cnt >= 2}

        if not core_numbers:
            return 0.0

        # 核心号在Top-K中的平均频率占比
        avg_freq_ratio = sum(
            front_counter[n] / total_cands for n in core_numbers
        ) / len(core_numbers)

        return avg_freq_ratio

    def compute_portfolio_score(self, portfolio: List[Dict],
                                individual_scores: List[float],
                                dispersion: float,
                                core_coverage: float,
                                beta: float = 0.15,
                                gamma: float = 0.10) -> float:
        """
        计算组合得分（带分散度惩罚和核心覆盖奖励）

        组合得分 = 平均个体得分 - β×分散度 + γ×核心覆盖度

        参数:
            portfolio: 3注号码
            individual_scores: 每注的个体相似度得分
            dispersion: 注间分散度
            core_coverage: 核心覆盖度
            beta: 分散度惩罚系数（越大→越偏好聚合）
            gamma: 核心覆盖奖励系数（越大→越偏好高频共享号）

        返回:
            组合得分（越高越好）
        """
        avg_individual = sum(individual_scores) / len(individual_scores)
        portfolio_score = avg_individual - beta * dispersion + gamma * core_coverage
        return portfolio_score

    def find_core_numbers(self, top_candidates: List[Dict],
                          threshold: float = 0.5) -> List[int]:
        """
        从Top-K候选中识别核心号码

        参数:
            top_candidates: Top-K候选列表
            threshold: 出现频率阈值（占Top-K的比例）

        返回:
            核心号码列表（按频率降序）
        """
        front_counter = Counter()
        for cand in top_candidates:
            for n in cand["front"]:
                front_counter[n] += 1

        total = len(top_candidates)
        core = []
        for n, cnt in front_counter.most_common(35):
            freq = cnt / total
            if freq >= threshold:
                core.append(n)
            else:
                break
        return core
