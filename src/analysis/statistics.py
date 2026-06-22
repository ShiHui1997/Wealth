"""
统计验证模块
对预测系统和开奖数据进行统计检验，评估系统有效性

包含：
1. 频率分布的卡方检验（检验号码是否均匀分布）
2. 预测命中率的显著性检验（对比随机基线）
3. 特征维度的区分力分析（哪些特征对预测有帮助）
4. 系统运行健康度评估
"""
import math
import json
from typing import List, Dict, Tuple, Optional
from collections import Counter


class StatisticalValidator:
    """
    统计验证器
    用统计方法评估预测系统的有效性
    """

    # 卡方分布临界值 (df=自由度, alpha=0.05)
    # 前区35个号码 → df=34, 后区12个号码 → df=11
    CHI_SQUARE_CRITICAL = {
        34: 48.60,   # df=34, alpha=0.05
        11: 19.68,   # df=11, alpha=0.05
        4: 9.49,     # df=4, alpha=0.05
        6: 12.59,    # df=6, alpha=0.05
    }

    def __init__(self, storage=None):
        self.storage = storage

    # ═══════════════════════════════════════════════
    # 1. 卡方检验：号码频率是否均匀分布
    # ═══════════════════════════════════════════════

    def chi_square_frequency(self, draws: List[Dict]) -> Dict:
        """
        对前区和后区号码频率做卡方检验
        
        H0: 每个号码出现概率相等（均匀分布）
        H1: 不是均匀分布
        
        如果 p < 0.05，拒绝H0，说明频率分布不均匀
        （但大乐透理论上应该接近均匀，如果不均匀可能存在短期偏态）
        """
        total = len(draws)
        if total < 30:
            return {"status": "数据不足", "total": total}

        # 前区频率
        front_counter = Counter()
        back_counter = Counter()
        for draw in draws:
            for n in draw["front"]:
                front_counter[n] += 1
            for n in draw["back"]:
                back_counter[n] += 1

        # 前区卡方: 期望频率 = total * 5 / 35
        front_expected = total * 5 / 35
        front_chi = 0
        for i in range(1, 36):
            observed = front_counter.get(i, 0)
            front_chi += (observed - front_expected) ** 2 / front_expected

        # 后区卡方: 期望频率 = total * 2 / 12
        back_expected = total * 2 / 12
        back_chi = 0
        for i in range(1, 13):
            observed = back_counter.get(i, 0)
            back_chi += (observed - back_expected) ** 2 / back_expected

        # 判断
        front_df = 34
        back_df = 11
        front_uniform = front_chi < self.CHI_SQUARE_CRITICAL.get(front_df, 48.60)
        back_uniform = back_chi < self.CHI_SQUARE_CRITICAL.get(back_df, 19.68)

        return {
            "total_draws": total,
            "front": {
                "chi_square": round(front_chi, 2),
                "df": front_df,
                "critical_005": self.CHI_SQUARE_CRITICAL.get(front_df, 48.60),
                "is_uniform": front_uniform,
                "expected_per_number": round(front_expected, 1),
                "actual_range": f"{min(front_counter.get(i,0) for i in range(1,36))}~"
                                f"{max(front_counter.get(i,0) for i in range(1,36))}",
            },
            "back": {
                "chi_square": round(back_chi, 2),
                "df": back_df,
                "critical_005": self.CHI_SQUARE_CRITICAL.get(back_df, 19.68),
                "is_uniform": back_uniform,
                "expected_per_number": round(back_expected, 1),
                "actual_range": f"{min(back_counter.get(i,0) for i in range(1,13))}~"
                                f"{max(back_counter.get(i,0) for i in range(1,13))}",
            },
            "conclusion": (
                "前区和后区频率均符合均匀分布" if front_uniform and back_uniform
                else "存在频率偏态，可能存在短期规律" if not front_uniform or not back_uniform
                else "部分区域存在偏态"
            ),
        }

    # ═══════════════════════════════════════════════
    # 2. 预测命中率显著性检验
    # ═══════════════════════════════════════════════

    def prediction_significance(self, verification_details: List[Dict]) -> Dict:
        """
        检验预测命中率是否显著高于随机基线
        
        随机基线（大乐透规则下）：
        - 前区命中≥3的概率 ≈ 2.07%（单注）
        - 后区命中≥1的概率 ≈ 30.30%（单注）
        - 3注中至少1注前区≥3的概率 ≈ 6.08%
        - 3注中至少1注后区≥1的概率 ≈ 64.2%
        
        如果实际命中率显著高于这些基线，说明预测有效
        """
        n = len(verification_details)
        if n < 5:
            return {
                "status": "验证数据不足",
                "verified_count": n,
                "min_required": 5,
            }

        # 实际命中率
        front_3plus = sum(1 for v in verification_details if v["front_match"] >= 3)
        back_1plus = sum(1 for v in verification_details if v["back_match"] >= 1)
        front_rate = front_3plus / n
        back_rate = back_1plus / n

        # 随机基线（3注）
        # P(前区≥3 | 单注) = C(5,3)*C(30,2) / C(35,5) ≈ 2.07%
        # P(至少1注前区≥3 | 3注) = 1-(1-0.0207)^3 ≈ 6.08%
        baseline_front = 0.0608
        # P(后区≥1 | 单注) = 1-C(10,2)/C(12,2) ≈ 30.30%
        # P(至少1注后区≥1 | 3注) = 1-(1-0.3030)^3 ≈ 64.2%
        baseline_back = 0.642

        # 二项检验（简化版：用正态近似）
        # z = (p - p0) / sqrt(p0*(1-p0)/n)
        front_z = (front_rate - baseline_front) / math.sqrt(
            baseline_front * (1 - baseline_front) / n
        ) if n > 0 else 0
        back_z = (back_rate - baseline_back) / math.sqrt(
            baseline_back * (1 - baseline_back) / n
        ) if n > 0 else 0

        # z > 1.64 → 单侧 p < 0.05（显著优于随机）
        front_significant = front_z > 1.64
        back_significant = back_z > 1.64

        return {
            "verified_count": n,
            "front_3plus_count": front_3plus,
            "front_3plus_rate": round(front_rate, 4),
            "front_baseline": baseline_front,
            "front_z_score": round(front_z, 3),
            "front_significant": front_significant,
            "back_1plus_count": back_1plus,
            "back_1plus_rate": round(back_rate, 4),
            "back_baseline": baseline_back,
            "back_z_score": round(back_z, 3),
            "back_significant": back_significant,
            "conclusion": self._significance_conclusion(
                front_significant, back_significant, front_z, back_z
            ),
        }

    def _significance_conclusion(self, front_sig, back_sig, front_z, back_z) -> str:
        if front_sig and back_sig:
            return "预测系统在前区和后区均显著优于随机基线！"
        elif front_sig:
            return f"前区预测显著优于随机（z={front_z:.2f}），后区未达显著水平"
        elif back_sig:
            return f"后区预测显著优于随机（z={back_z:.2f}），前区未达显著水平"
        else:
            if front_z > 0 and back_z > 0:
                return (f"预测命中率高于随机基线但未达统计显著"
                        f"（前区z={front_z:.2f}, 后区z={back_z:.2f}），"
                        f"需要更多验证数据")
            else:
                return (f"预测命中率未优于随机基线"
                        f"（前区z={front_z:.2f}, 后区z={back_z:.2f}），"
                        f"系统可能需要进一步优化")

    # ═══════════════════════════════════════════════
    # 3. 特征区分力分析
    # ═══════════════════════════════════════════════

    def feature_discrimination(self, verification_details: List[Dict],
                               analyzer) -> Dict:
        """
        分析各特征维度对"命中 vs 未命中"的区分能力
        
        对每个特征维度，计算命中期和未命中期的平均得分差异，
        差异越大说明该特征的区分力越强
        """
        if len(verification_details) < 5:
            return {"status": "验证数据不足", "count": len(verification_details)}

        # 由于 verification_details 中没有各维度的独立得分，
        # 我们用 avg_similarity 作为整体指标
        hit_sims = []
        miss_sims = []

        for v in verification_details:
            is_hit = v["front_match"] >= 3 or v["back_match"] >= 1
            sim = v.get("avg_similarity", 0)
            if is_hit:
                hit_sims.append(sim)
            else:
                miss_sims.append(sim)

        result = {
            "total": len(verification_details),
            "hit_count": len(hit_sims),
            "miss_count": len(miss_sims),
        }

        if hit_sims and miss_sims:
            hit_avg = sum(hit_sims) / len(hit_sims)
            miss_avg = sum(miss_sims) / len(miss_sims)
            result["hit_avg_similarity"] = round(hit_avg, 6)
            result["miss_avg_similarity"] = round(miss_avg, 6)
            result["discrimination_ratio"] = round(hit_avg / miss_avg, 4) if miss_avg > 0 else 0
            result["conclusion"] = (
                f"命中组相似度({hit_avg:.4f}) "
                f"{'高于' if hit_avg > miss_avg else '低于'} "
                f"未命中组({miss_avg:.4f})，"
                f"区分比={hit_avg/miss_avg:.3f if miss_avg > 0 else 'N/A'}"
            )
        else:
            result["conclusion"] = "命中期或未命中期数据不足，无法计算区分力"

        return result

    # ═══════════════════════════════════════════════
    # 4. 系统健康度评估
    # ═══════════════════════════════════════════════

    def system_health(self, draws: List[Dict], storage) -> Dict:
        """
        评估系统整体健康度
        
        检查项：
        1. 数据完整性（是否有缺失期号）
        2. 数据新鲜度（最新数据距今多久）
        3. 预测覆盖率（有多少期有预测记录）
        4. 验证覆盖率（预测中有多少被验证）
        5. 校准状态（校准次数和权重）
        """
        health = {
            "checks": [],
            "overall": "healthy",
        }

        # 1. 数据完整性
        total_draws = len(draws)
        if total_draws < 100:
            health["checks"].append({
                "name": "数据量",
                "status": "warning",
                "detail": f"仅{total_draws}期，建议至少100期",
            })
        else:
            health["checks"].append({
                "name": "数据量",
                "status": "ok",
                "detail": f"{total_draws}期历史数据",
            })

        # 2. 数据新鲜度
        if draws:
            latest_issue = draws[-1].get("issue", "")
            try:
                # 期号格式 YYNNN，如 26069
                year = 2000 + int(latest_issue[:2])
                seq = int(latest_issue[2:])
                # 粗略估算：每年约170期
                expected_latest = (2026 - 2007) * 170 + 69  # 粗略期望
                if total_draws < expected_latest - 20:
                    health["checks"].append({
                        "name": "数据新鲜度",
                        "status": "warning",
                        "detail": f"最新期号{latest_issue}，可能有缺失",
                    })
                else:
                    health["checks"].append({
                        "name": "数据新鲜度",
                        "status": "ok",
                        "detail": f"最新期号{latest_issue}",
                    })
            except (ValueError, IndexError):
                health["checks"].append({
                    "name": "数据新鲜度",
                    "status": "ok",
                    "detail": f"最新期号{latest_issue}",
                })

        # 3. 预测覆盖率
        pred_issues = storage.get_all_predicted_issues()
        if len(pred_issues) == 0:
            health["checks"].append({
                "name": "预测记录",
                "status": "warning",
                "detail": "无预测记录",
            })
        else:
            health["checks"].append({
                "name": "预测记录",
                "status": "ok",
                "detail": f"{len(pred_issues)}期有预测记录",
            })

        # 4. 验证覆盖率
        verified_issues = storage.get_all_verified_issues()
        pending = pred_issues - verified_issues
        if len(pred_issues) > 0:
            verify_rate = len(verified_issues & pred_issues) / len(pred_issues)
            if verify_rate < 0.5:
                health["checks"].append({
                    "name": "验证覆盖",
                    "status": "warning",
                    "detail": f"验证率{verify_rate:.0%}，{len(pending)}期待验证",
                })
            else:
                health["checks"].append({
                    "name": "验证覆盖",
                    "status": "ok",
                    "detail": f"验证率{verify_rate:.0%}",
                })
        else:
            health["checks"].append({
                "name": "验证覆盖",
                "status": "ok",
                "detail": "暂无预测需要验证",
            })

        # 5. 校准状态
        calib_count = storage.get_calibration_count()
        if calib_count == 0:
            health["checks"].append({
                "name": "校准状态",
                "status": "info",
                "detail": "尚未执行校准（需≥5期验证）",
            })
        else:
            health["checks"].append({
                "name": "校准状态",
                "status": "ok",
                "detail": f"已校准{calib_count}次，种子={storage.get_current_seed()}",
            })

        # 总体评估
        warnings = [c for c in health["checks"] if c["status"] == "warning"]
        if len(warnings) >= 2:
            health["overall"] = "needs_attention"
        elif len(warnings) == 1:
            health["overall"] = "minor_issues"

        return health

    # ═══════════════════════════════════════════════
    # 5. 综合报告
    # ═══════════════════════════════════════════════

    def full_report(self, draws: List[Dict], storage, analyzer=None) -> str:
        """生成完整的统计验证报告"""
        lines = [
            f"\n{'='*60}",
            f"  大乐透预测系统 - 统计验证报告",
            f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"{'='*60}",
        ]

        # 1. 卡方检验
        lines.append("\n── 1. 频率分布卡方检验 ──")
        chi_result = self.chi_square_frequency(draws)
        if "status" in chi_result:
            lines.append(f"  {chi_result['status']}")
        else:
            lines.append(f"  总期数: {chi_result['total_draws']}")
            lines.append(f"  前区: χ²={chi_result['front']['chi_square']:.2f} "
                        f"(临界值={chi_result['front']['critical_005']:.2f}) "
                        f"{'✅均匀' if chi_result['front']['is_uniform'] else '⚠️偏态'}")
            lines.append(f"  后区: χ²={chi_result['back']['chi_square']:.2f} "
                        f"(临界值={chi_result['back']['critical_005']:.2f}) "
                        f"{'✅均匀' if chi_result['back']['is_uniform'] else '⚠️偏态'}")
            lines.append(f"  结论: {chi_result['conclusion']}")

        # 2. 预测显著性检验
        lines.append("\n── 2. 预测命中率显著性检验 ──")
        ver_details = storage.get_verification_details()
        sig_result = self.prediction_significance(ver_details)
        if "status" in sig_result:
            lines.append(f"  {sig_result['status']}（{sig_result.get('verified_count', 0)}期）")
        else:
            lines.append(f"  验证期数: {sig_result['verified_count']}")
            lines.append(f"  前区≥3命中: {sig_result['front_3plus_count']}次 "
                        f"({sig_result['front_3plus_rate']:.1%}) "
                        f"| 基线={sig_result['front_baseline']:.1%} "
                        f"| z={sig_result['front_z_score']:.2f} "
                        f"{'✅显著' if sig_result['front_significant'] else '❌不显著'}")
            lines.append(f"  后区≥1命中: {sig_result['back_1plus_count']}次 "
                        f"({sig_result['back_1plus_rate']:.1%}) "
                        f"| 基线={sig_result['back_baseline']:.1%} "
                        f"| z={sig_result['back_z_score']:.2f} "
                        f"{'✅显著' if sig_result['back_significant'] else '❌不显著'}")
            lines.append(f"  结论: {sig_result['conclusion']}")

        # 3. 特征区分力
        if analyzer:
            lines.append("\n── 3. 特征区分力分析 ──")
            disc_result = self.feature_discrimination(ver_details, analyzer)
            if "status" in disc_result:
                lines.append(f"  {disc_result['status']}")
            else:
                lines.append(f"  命中{disc_result['hit_count']}期 / "
                            f"未命中{disc_result['miss_count']}期")
                if "discrimination_ratio" in disc_result:
                    lines.append(f"  命中组均分: {disc_result['hit_avg_similarity']:.4f}")
                    lines.append(f"  未命中组均分: {disc_result['miss_avg_similarity']:.4f}")
                    lines.append(f"  区分比: {disc_result['discrimination_ratio']:.3f}")
                lines.append(f"  结论: {disc_result['conclusion']}")

        # 4. 系统健康度
        lines.append("\n── 4. 系统健康度 ──")
        health = self.system_health(draws, storage)
        for check in health["checks"]:
            icon = {"ok": "✅", "warning": "⚠️", "info": "ℹ️"}.get(check["status"], "?")
            lines.append(f"  {icon} {check['name']}: {check['detail']}")
        lines.append(f"  总体: {health['overall']}")

        lines.append(f"\n{'='*60}\n")
        return "\n".join(lines)


# 延迟导入 datetime
from datetime import datetime
