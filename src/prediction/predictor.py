"""
大乐透预测器
基于历史特征生成候选号码，并按与真实开奖的相似度排序
支持多尺度窗口融合打分（Walk-Forward优化权重）
"""
import random
from typing import List, Dict, Tuple, Optional
from src.analysis.analyzer import DaletouAnalyzer


class DaletouPredictor:
    """
    预测器核心逻辑：
    ① 分析历史数据，学习"随机性特征"
    ② 生成大量候选号码
    ③ 按相似度打分，选出最"像"真实开奖的号码
    ④ 支持多尺度窗口融合打分（Walk-Forward回测优化）
    """

    def __init__(self, front_range: int = 35, back_range: int = 12):
        self.analyzer = DaletouAnalyzer(front_range, back_range)
        self._wf_backtester = None  # 延迟初始化

    def _get_wf_backtester(self, storage):
        """延迟初始化 Walk-Forward 回测器"""
        if self._wf_backtester is None and storage:
            from src.analysis.walk_forward import WalkForwardBacktester
            self._wf_backtester = WalkForwardBacktester(self.analyzer, storage)
        return self._wf_backtester

    def predict(self, draws: List[Dict], top_n: int = 3,
                candidates_count: int = 1000,
                storage=None,
                random_seed: int = None,
                next_issue: str = None,
                use_multi_scale: bool = True) -> List[Tuple[Dict, float]]:
        """
        预测下一期号码
        使用固定随机种子，确保同样的历史数据每次得出相同结果

        参数:
            draws: 全部历史开奖数据
            top_n: 返回前N注
            candidates_count: 候选号码生成数量
            storage: 数据库实例（用于加载校准权重和种子）
            random_seed: 随机种子（None时自动从数据库读取）
            next_issue: 要预测的期号（纳入种子计算）
            use_multi_scale: 是否启用多尺度窗口融合打分

        Returns: [(号码dict, 相似度得分), ...] 按得分降序
        """
        # 种子计算策略:
        #   base_seed (来自数据库/校准轮换) + 当前要预测的期号数值
        #   效果: 同一期多次运行 → 结果相同(确定性); 不同期 → 自然不同
        if random_seed is None:
            base_seed = 42
            if storage:
                base_seed = storage.get_current_seed()
            issue_offset = 0
            if next_issue:
                try:
                    issue_offset = int(next_issue)
                except (ValueError, TypeError):
                    pass
            random_seed = base_seed + issue_offset
        random.seed(random_seed)
        print(f"[预测] 使用种子: {random_seed} "
              f"(基础={base_seed if storage else 42} + 期号={next_issue or 'N/A'})")

        print(f"\n[预测] 基于全部 {len(draws)} 期数据进行分析...")

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

        # 检查是否有多尺度窗口权重
        wf_weights = None
        if use_multi_scale and storage:
            wf_backtester = self._get_wf_backtester(storage)
            if wf_backtester:
                wf_weights = wf_backtester.get_window_weights()
                print(f"[预测] 多尺度窗口权重: {wf_weights}")

        # 第一步：从历史数据中提取特征（"学习随机性"）
        features = self.analyzer.build_features(draws)

        # 第二步：用智能策略生成候选号码（按历史特征定向构造）
        # 使用固定随机种子（已在函数开头设置），确保结果可复现
        all_candidates = self.analyzer.generate_candidates(
            features, candidates_count, "smart"
        )

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
        if wf_weights and use_multi_scale:
            # 多尺度融合打分
            print("[预测] 使用多尺度窗口融合打分...")
            wf_backtester = self._get_wf_backtester(storage)
            for cand in all_candidates:
                score = wf_backtester.multi_scale_score(
                    cand, draws, weights=wf_weights,
                    feature_weights=weights
                )
                scored.append((cand, score))
        else:
            # 单尺度打分（原有逻辑）
            for cand in all_candidates:
                score = self.analyzer.compute_similarity_score(
                    cand, features, weights=weights
                )
                scored.append((cand, score))

        # 按得分降序排列
        scored.sort(key=lambda x: x[1], reverse=True)

        print(f"[预测] 打分完成，Top3得分: "
              f"{scored[0][1]:.4f}, {scored[1][1]:.4f}, {scored[2][1]:.4f}")
        if wf_weights:
            print(f"[预测] 多尺度融合打分模式 "
                  f"(窗口: {', '.join(f'{k}={v:.2f}' for k,v in wf_weights.items())})")

        # 使用投资组合优化选择最终3注（不再简单取Top3）
        return self.select_portfolio(
            scored, top_n=top_n, storage=storage
        )

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

    def format_prediction_html(self, prediction: List[Tuple[Dict, float]],
                                submit_url: str = "", issue: str = "") -> str:
        """格式化为HTML（适合PushPlus推送，手机端优化）"""
        from datetime import datetime, timezone, timedelta

        # 每次生成唯一内容（避免PushPlus反垃圾code=999）
        bj = datetime.now(timezone(timedelta(hours=8)))
        ts = bj.strftime('%m-%d %H:%M')
        issue_tag = f" 第{issue}期" if issue else ""

        rows = ""
        for i, (nums, score) in enumerate(prediction, 1):
            front_str = " ".join(f"{n:02d}" for n in nums["front"])
            back_str = " ".join(f"{n:02d}" for n in nums["back"])
            rows += f"""
            <tr>
                <td style="padding:10px 12px;white-space:nowrap;font-size:14px;">第{i}注</td>
                <td style="padding:10px 12px;white-space:nowrap;font-weight:bold;color:#e74c3c;font-size:15px;letter-spacing:1px;">{front_str}</td>
                <td style="padding:10px 12px;white-space:nowrap;font-weight:bold;color:#3498db;font-size:15px;letter-spacing:1px;">{back_str}</td>
                <td style="padding:10px 12px;white-space:nowrap;color:#888;font-size:13px;">{score:.2f}</td>
            </tr>"""

        # 底部附加：开奖数据更新链接
        submit_section = ""
        if submit_url:
            submit_section = f"""
            <div style="margin-top:20px;padding:14px;background:#f0f7ff;border-radius:10px;border-left:4px solid #3498db;">
                <p style="margin:0 0 8px 0;font-size:14px;color:#2c3e50;font-weight:bold;">
                    📝 开奖后请更新数据
                </p>
                <p style="margin:0;font-size:12px;color:#666;line-height:1.5;">
                    已知最新开奖号码？点击填写，系统将自动更新并重新预测 👇
                </p>
                <a href="{submit_url}" target="_blank"
                   style="display:inline-block;margin-top:10px;padding:11px 24px;
                          background:linear-gradient(135deg,#3498db,#2980b9);
                          color:#fff;border-radius:8px;text-decoration:none;
                          font-weight:bold;font-size:14px;white-space:nowrap;">
                    ✏️ 提交最新开奖号码
                </a>
            </div>"""

        return f"""
        <div style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:16px;max-width:100%;overflow-x:auto;">
            <h2 style="color:#2c3e50;font-size:18px;margin-bottom:4px;">🎯 大乐透{issue_tag}预测</h2>
            <p style="color:#aaa;font-size:11px;margin-bottom:12px;">生成于 {ts} (北京时间)</p>
            <p style="color:#888;font-size:13px;margin-bottom:14px;">
                基于历史开奖数据的相似度分析，以下3注与真实开奖随机性最为接近：
            </p>
            <table style="border-collapse:collapse;margin-top:12px;width:100%;min-width:340px;">
                <tr style="background:#f5f6fa;">
                    <th style="padding:8px 12px;font-size:13px;white-space:nowrap;">序号</th>
                    <th style="padding:8px 12px;font-size:13px;white-space:nowrap;color:#e74c3c;">前区(5个)</th>
                    <th style="padding:8px 12px;font-size:13px;white-space:nowrap;color:#3498db;">后区(2个)</th>
                    <th style="padding:8px 12px;font-size:13px;white-space:nowrap;">相似度</th>
                </tr>
                {rows}
            </table>
            <p style="margin-top:14px;color:#e74c3c;font-size:12px;">
                ⚠️ 彩票具有随机性，本预测仅供娱乐参考，请理性购彩
            </p>
            {submit_section}
        </div>
        """

    # ═══════════════════════════════════════════════
    # 投资组合优化（注间分散度控制）
    # ═════════════════════════════════════════════════

    def select_portfolio(self, scored: List[Tuple[Dict, float]],
                         top_n: int = 3,
                         storage = None,
                         beta: float = None,
                         gamma: float = None) -> List[Tuple[Dict, float]]:
        """
        从已打分的候选中选择最优3注组合（投资组合优化）
        不再简单取Top3，而是考虑注间分散度和核心覆盖度

        算法:
          1. 锚点: 取个体得分最高的候选作为第1注 (b1)
          2. 识别核心号码: 从Top-50候选中找出高频共享号
          3. 第2注选择: 在Top-50中找使组合得分最高的候选
             (约束: 与前2注至少共享2个前区号)
          4. 第3注选择: 同理，进一步扩大覆盖

        参数:
            scored: 已打分的候选列表 [(candidate, score), ...] 按得分降序
            top_n: 返回注数（默认3）
            storage: 数据库实例（用于读取校准参数β, γ）
            beta: 分散度惩罚系数（None时从DB读取）
            gamma: 核心覆盖奖励系数（None时从DB读取）

        返回:
            [(候选, 得分), ...] 优化后的组合
        """
        if len(scored) < top_n:
            return scored

        # 从数据库读取校准参数
        if beta is None:
            beta = 0.15  # 默认值
            if storage:
                val = storage.get_calibration("portfolio_beta")
                if val is not None:
                    beta = val
        if gamma is None:
            gamma = 0.10  # 默认值
            if storage:
                val = storage.get_calibration("portfolio_gamma")
                if val is not None:
                    gamma = val

        print(f"[组合优化] β={beta:.3f}, γ={gamma:.3f}")

        # Top-K候选用于核心号识别（取前50个）
        top_k = min(50, len(scored))
        top_candidates = [s[0] for s in scored[:top_k]]

        # 识别核心号码
        core_numbers = self.analyzer.find_core_numbers(top_candidates, threshold=0.20)
        print(f"[组合优化] 核心号码({len(core_numbers)}个): {core_numbers[:10]}")

        # Step 1: 锚点 — 个体得分最高的候选
        b1_cand, b1_score = scored[0]
        portfolio = [b1_cand]
        portfolio_scores = [b1_score]
        used_indices = {0}

        # Step 2: 选择第2注
        best_idx2 = -1
        best_portfolio_score2 = -1.0

        search_range = min(80, len(scored))  # 在前80个候选中搜索
        for idx in range(1, search_range):
            if idx in used_indices:
                continue
            cand, score = scored[idx]

            # 约束: 与已有注至少共享2个前区号（确保不过度分散）
            min_overlap = 2
            max_overlap = 4  # 也不能完全相同
            overlap_ok = False
            for existing in portfolio:
                overlap = len(set(cand["front"]) & set(existing["front"]))
                if min_overlap <= overlap <= max_overlap:
                    overlap_ok = True
                    break
            if not overlap_ok:
                continue

            # 计算组合得分
            test_portfolio = portfolio + [cand]
            test_scores = portfolio_scores + [score]
            disp = self.analyzer.compute_dispersion(test_portfolio)
            cov = self.analyzer.compute_core_coverage(test_portfolio, top_candidates)
            ps = self.analyzer.compute_portfolio_score(
                test_portfolio, test_scores, disp, cov, beta, gamma
            )

            if ps > best_portfolio_score2:
                best_portfolio_score2 = ps
                best_idx2 = idx

        if best_idx2 >= 0:
            cand, score = scored[best_idx2]
            portfolio.append(cand)
            portfolio_scores.append(score)
            used_indices.add(best_idx2)
            disp = self.analyzer.compute_dispersion(portfolio)
            print(f"[组合优化] 第2注选定: idx={best_idx2}, "
                  f"个体得分={score:.4f}, 分散度={disp:.3f}")

        # Step 3: 选择第3注
        best_idx3 = -1
        best_portfolio_score3 = -1.0

        for idx in range(1, search_range):
            if idx in used_indices:
                continue
            cand, score = scored[idx]

            # 约束: 与第1注或第2注至少共享2个前区号
            overlap_ok = False
            min_overlap = 2
            max_overlap = 4
            for existing in portfolio:
                overlap = len(set(cand["front"]) & set(existing["front"]))
                if min_overlap <= overlap <= max_overlap:
                    overlap_ok = True
                    break
            if not overlap_ok:
                continue

            test_portfolio = portfolio + [cand]
            test_scores = portfolio_scores + [score]
            disp = self.analyzer.compute_dispersion(test_portfolio)
            cov = self.analyzer.compute_core_coverage(test_portfolio, top_candidates)
            ps = self.analyzer.compute_portfolio_score(
                test_portfolio, test_scores, disp, cov, beta, gamma
            )

            if ps > best_portfolio_score3:
                best_portfolio_score3 = ps
                best_idx3 = idx

        if best_idx3 >= 0:
            cand, score = scored[best_idx3]
            portfolio.append(cand)
            portfolio_scores.append(score)
            disp = self.analyzer.compute_dispersion(portfolio)
            print(f"[组合优化] 第3注选定: idx={best_idx3}, "
                  f"个体得分={score:.4f}, 分散度={disp:.3f}")

        # 如果选不满3注，用最高分候选补齐
        while len(portfolio) < top_n and len(used_indices) < len(scored):
            for idx in range(len(scored)):
                if idx not in used_indices:
                    cand, score = scored[idx]
                    portfolio.append(cand)
                    portfolio_scores.append(score)
                    used_indices.add(idx)
                    break

        # 打印组合信息
        disp = self.analyzer.compute_dispersion(portfolio)
        cov = self.analyzer.compute_core_coverage(portfolio, top_candidates)
        print(f"[组合优化] 最终组合: 分散度={disp:.3f}, 核心覆盖度={cov:.3f}")
        for i, (cand, score) in enumerate(zip(portfolio, portfolio_scores), 1):
            front_str = " ".join(f"{n:02d}" for n in cand["front"])
            back_str = " ".join(f"{n:02d}" for n in cand["back"])
            print(f"  第{i}注: [{front_str}] + [{back_str}] 得分={score:.4f}")

        return list(zip(portfolio, portfolio_scores))
