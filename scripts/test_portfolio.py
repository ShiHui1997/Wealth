"""
测试投资组合优化策略 vs 旧策略（独立Top3）
对比分散度和命中表现
"""
import sys
sys.path.insert(0, ".")

from main import load_config
from src.data.storage import LotteryStorage
from src.prediction.predictor import DaletouPredictor
from src.analysis.analyzer import DaletouAnalyzer


def main():
    cfg = load_config()
    storage = LotteryStorage(cfg["database"]["path"])
    draws = storage.get_all_draws()

    print(f"历史数据: {len(draws)} 期")
    print(f"最新开奖期号: {draws[-1]['issue']}")
    next_issue = str(int(draws[-1]["issue"]) + 1)
    print(f"下一期预测: {next_issue}\n")

    predictor = DaletouPredictor()

    # 生成候选并打分
    print("[测试] 生成候选并打分...")
    random_seed = 42 + int(next_issue)
    import random
    random.seed(random_seed)

    analyzer = DaletouAnalyzer()
    features = analyzer.build_features(draws)

    all_candidates = analyzer.generate_candidates(features, 500, "smart")
    unique = []
    seen = set()
    for c in all_candidates:
        key = (tuple(c["front"]), tuple(c["back"]))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    print(f"[测试] 生成 {len(unique)} 个不重复候选")

    # 多尺度打分
    from src.analysis.walk_forward import WalkForwardBacktester
    wf = WalkForwardBacktester(analyzer, storage)
    wf_weights = wf.get_window_weights()

    scored = []
    for cand in unique:
        score = wf.multi_scale_score(cand, draws, weights=wf_weights)
        scored.append((cand, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    print(f"[测试] 打分完成，Top5得分: {[f'{score:.4f}' for _, score in scored[:5]]}\n")

    # ── 旧策略：独立Top3 ──
    print("=" * 50)
    print("  [旧策略] 独立Top3（直接取scored[:3]）")
    print("=" * 50)
    old_portfolio = scored[:3]
    _print_portfolio(old_portfolio, analyzer)

    # ── 新策略：投资组合优化 ──
    print("\n" + "=" * 50)
    print("  [新策略] 投资组合优化（select_portfolio）")
    print("=" * 50)
    new_portfolio = predictor.select_portfolio(
        scored, top_n=3, storage=storage
    )
    _print_portfolio(new_portfolio, analyzer)

    # ── 对比 ──
    print("\n" + "=" * 50)
    print("  对比总结")
    print("=" * 50)
    old_disp = analyzer.compute_dispersion([s[0] for s in old_portfolio])
    new_disp = analyzer.compute_dispersion([s[0] for s in new_portfolio])
    print(f"  旧策略分散度: {old_disp:.3f}  (越高=注间越分散)")
    print(f"  新策略分散度: {new_disp:.3f}")
    print(f"  分散度变化:   {old_disp - new_disp:+.3f}  (降低更好)")

    old_cover = analyzer.compute_core_coverage(
        [s[0] for s in old_portfolio], unique[:50]
    )
    new_cover = analyzer.compute_core_coverage(
        [s[0] for s in new_portfolio], unique[:50]
    )
    print(f"  旧策略核心覆盖度: {old_cover:.3f}")
    print(f"  新策略核心覆盖度: {new_cover:.3f}")
    print(f"  覆盖度变化:       {new_cover - old_cover:+.3f}  (升高更好)")


def _print_portfolio(portfolio, analyzer):
    """打印组合详情"""
    from collections import Counter
    all_nums = []
    for cand, score in portfolio:
        front_str = " ".join(f"{n:02d}" for n in cand["front"])
        back_str = " ".join(f"{n:02d}" for n in cand["back"])
        all_nums.extend(cand["front"])
        print(f"  [{front_str}] + [{back_str}]  得分={score:.4f}")

    # 统计注间重叠
    disp = analyzer.compute_dispersion([s[0] for s in portfolio])
    print(f"  注间分散度: {disp:.3f}")

    # 显示共享号码
    from collections import Counter
    freq = Counter(all_nums)
    shared = {n: c for n, c in freq.items() if c >= 2}
    if shared:
        shared_str = ", ".join(f"{n:02d}(×{c})" for n, c in sorted(shared.items()))
        print(f"  共享前区号: {shared_str}")


if __name__ == "__main__":
    main()
