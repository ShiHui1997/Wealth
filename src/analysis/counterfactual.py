"""
反事实对照组模块

每次模型预测时，同时生成一组纯随机号码作为对照。
开奖后分别验证模型组和对照组，长期比较以判断模型是否有效。
"""
import random
from typing import List, Dict, Optional


class CounterfactualTracker:
    """
    反事实跟踪器

    核心假设：如果模型真有用，那么长期来看模型组的命中率
    应该显著优于纯随机对照组。否则差异只是随机波动。
    """

    def __init__(self, storage=None):
        self.storage = storage

    def generate_random_control(self, count: int = 3,
                                front_range: int = 35,
                                back_range: int = 12) -> List[Dict]:
        """
        生成 count 注纯随机对照号码。

        返回: [{"front": [...], "back": [...], "score": 0, "model_version": "random_control"}, ...]
        """
        predictions = []
        for _ in range(count):
            front = sorted(random.sample(range(1, front_range + 1), 5))
            back = sorted(random.sample(range(1, back_range + 1), 2))
            predictions.append({
                "front": front,
                "back": back,
                "score": 0.0,
                "model_version": "random_control",
            })
        return predictions

    def save(self, target_issue: str, predictions: List[Dict]) -> None:
        """保存一期反事实对照组预测"""
        if self.storage is None:
            return
        self.storage.save_counterfactual_predictions(target_issue, predictions)
        print(f"[反事实对照] 已保存第 {target_issue} 期随机对照组")

    def verify(self, issue: str) -> Optional[Dict]:
        """验证某期反事实对照组"""
        if self.storage is None:
            return None
        result = self.storage.verify_counterfactual_prediction(issue)
        if result:
            print(f"[反事实对照] 第 {issue} 期验证完成: "
                  f"前区{result['best_front_match']} 后区{result['best_back_match']}")
        return result

    def compare(self, issue: Optional[str] = None) -> Dict:
        """
        比较模型组与反事实对照组的验证结果。

        issue: 如果指定，只比较该期；否则比较所有历史已验证期。
        """
        if self.storage is None:
            return {"error": "no storage available"}

        model_rows = self.storage.get_verification_details()
        cf_rows = self._get_cf_verification_details()

        if issue:
            model_rows = [r for r in model_rows if r["issue"] == issue]
            cf_rows = [r for r in cf_rows if r["issue"] == issue]

        if not model_rows or not cf_rows:
            return {
                "model_count": len(model_rows),
                "cf_count": len(cf_rows),
                "error": "数据不足，无法比较",
            }

        # 只保留两表都有的期号
        common_issues = {r["issue"] for r in model_rows} & {r["issue"] for r in cf_rows}
        model_rows = [r for r in model_rows if r["issue"] in common_issues]
        cf_rows = [r for r in cf_rows if r["issue"] in common_issues]
        cf_rows_sorted = {r["issue"]: r for r in cf_rows}

        stats = {
            "common_issues": sorted(common_issues),
            "count": len(common_issues),
            "model": self._summarize(model_rows),
            "control": self._summarize(cf_rows),
            "by_issue": [],
        }

        for mr in model_rows:
            issue = mr["issue"]
            cr = cf_rows_sorted[issue]
            stats["by_issue"].append({
                "issue": issue,
                "model_front": mr["front_match"],
                "model_back": mr["back_match"],
                "control_front": cr["front_match"],
                "control_back": cr["back_match"],
                "model_any_front_3plus": mr["any_front_3plus"],
                "control_any_front_3plus": cr["any_front_3plus"],
            })

        return stats

    def _summarize(self, rows: List[Dict]) -> Dict:
        """对验证结果做汇总"""
        if not rows:
            return {}
        total = len(rows)
        return {
            "count": total,
            "avg_front_match": sum(r["front_match"] for r in rows) / total,
            "avg_back_match": sum(r["back_match"] for r in rows) / total,
            "any_front_3plus_rate": sum(r["any_front_3plus"] for r in rows) / total,
            "any_back_1plus_rate": sum(r["any_back_1plus"] for r in rows) / total,
        }

    def _get_cf_verification_details(self) -> List[Dict]:
        """从数据库读取反事实对照组验证详情"""
        if self.storage is None:
            return []
        import json
        with self.storage.get_conn() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute("""
                SELECT issue, best_front_match AS front_match,
                       best_back_match AS back_match,
                       any_front_match AS any_front_3plus,
                       any_back_match AS any_back_1plus,
                       avg_similarity, actual_front, actual_back
                FROM counterfactual_verifications
                ORDER BY issue ASC
            """).fetchall()
            for r in rows:
                r["any_front_3plus"] = bool(r["any_front_3plus"])
                r["any_back_1plus"] = bool(r["any_back_1plus"])
                r["actual_front"] = json.loads(r["actual_front"])
                r["actual_back"] = json.loads(r["actual_back"])
            return rows

    def print_comparison(self, issue: Optional[str] = None) -> None:
        """打印模型组 vs 对照组对比"""
        stats = self.compare(issue)
        print("\n" + "=" * 50)
        print("[模型 vs 反事实对照组对比]")
        print("=" * 50)

        if "error" in stats:
            print(f"\n{stats['error']}")
            print("=" * 50 + "\n")
            return

        print(f"\n共同验证期数: {stats['count']}")
        print(f"期号范围: {stats['common_issues'][:5]} ... {stats['common_issues'][-5:]}")

        model = stats["model"]
        control = stats["control"]
        print(f"\n模型组 ({model['count']} 期):")
        print(f"  平均前区命中: {model['avg_front_match']:.3f}")
        print(f"  平均后区命中: {model['avg_back_match']:.3f}")
        print(f"  前区≥3命中占比: {model['any_front_3plus_rate']:.3f}")
        print(f"  后区≥1命中占比: {model['any_back_1plus_rate']:.3f}")

        print(f"\n随机对照组 ({control['count']} 期):")
        print(f"  平均前区命中: {control['avg_front_match']:.3f}")
        print(f"  平均后区命中: {control['avg_back_match']:.3f}")
        print(f"  前区≥3命中占比: {control['any_front_3plus_rate']:.3f}")
        print(f"  后区≥1命中占比: {control['any_back_1plus_rate']:.3f}")

        print(f"\n解读:")
        if model["avg_front_match"] > control["avg_front_match"] + 0.05:
            print("  ✅ 模型前区命中略高于随机对照，可能存在微弱优势")
        elif model["avg_front_match"] < control["avg_front_match"] - 0.05:
            print("  ⚠️ 模型前区命中低于随机对照，建议审视策略")
        else:
            print("  ℹ️  模型与随机对照差异很小，符合随机彩票预期")

        print("=" * 50 + "\n")
