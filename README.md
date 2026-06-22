# 大乐透智能预测系统

基于历史开奖数据的统计分析，学习大乐透的"随机性特征"，通过多尺度窗口融合打分生成与真实开奖随机性最相似的推荐号码，并通过 PushPlus 推送到微信。

## 核心特性

### 数据层
- **全量历史数据**：从第一期（07001）至今，SQLite存储，自动去重增量更新
- **体彩官方API**：直连 webapi.sporttery.cn，稳定可靠
- **手机端提交**：通过 GitHub Issue 自动解析开奖号码并入库

### 算法层
- **7维特征提取**：频率/和值/奇偶/区间/跨度/连号/后区和值
- **多尺度窗口分析**：[50/100/200/500/all] 窗口并行分析，Walk-Forward回测优化权重
- **智能候选生成**：按历史特征定向构造，非纯随机搜索
- **自我校准**：基于验证结果自动调整特征维度权重 + 种子轮换

### 验证层
- **自动验证**：预测与真实开奖自动比对，记录命中情况
- **自动补验证**：扫描遗漏的验证项，确保数据完整
- **统计检验**：卡方检验（频率分布）、显著性检验（命中率vs随机基线）
- **特征区分力分析**：评估哪些特征对预测有贡献

### 工程层
- **GitHub Actions**：定时调度（周一/三/六 19:30）+ Issue自动处理
- **数据库缓存**：DB不纳入git，用Actions Cache持久化，避免冲突
- **健康检查**：系统健康度评估 + 异常告警（PushPlus推送）
- **结构化日志**：每次运行生成JSON日志，含步骤耗时和状态

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/config.yaml`，填入你的 PushPlus token（从 https://www.pushplus.plus/ 获取）

### 3. 初始化并获取数据

```bash
python main.py init        # 初始化数据库
python main.py fetch-all   # 获取全部历史数据（约2887期，首次运行）
```

### 4. 生成预测

```bash
python main.py predict     # 生成预测并推送到微信
python main.py predict --no-push  # 仅生成不推送
```

### 5. 完整运行（推荐）

```bash
python main.py run         # 获取+验证+校准+预测+推送（一键完成）
python main.py run --no-push  # 不推送
```

## 命令行全集

| 命令 | 说明 |
|------|------|
| `python main.py init` | 初始化数据库 |
| `python main.py fetch` | 获取最新一期开奖数据 |
| `python main.py fetch-all` | 获取全部历史数据（首次运行） |
| `python main.py verify` | 验证最新一期预测 vs 真实开奖 |
| `python main.py verify --issue 26070` | 验证指定期号 |
| `python main.py calibrate` | 自我校准（权重调整 + Walk-Forward回测） |
| `python main.py calibrate --force` | 强制校准（即使数据不足） |
| `python main.py backtest` | 单独运行Walk-Forward回测 |
| `python main.py backtest --periods 100 --sample 50` | 指定回测参数 |
| `python main.py validate` | 统计验证报告（卡方检验/显著性/健康度） |
| `python main.py health` | 系统健康检查 |
| `python main.py stats` | 显示预测效果统计 |
| `python main.py predict` | 生成并推送预测 |
| `python main.py predict --no-push` | 仅生成不推送 |
| `python main.py run` | 完整运行（获取+验证+校准+预测+推送） |
| `python main.py run --no-push` | 完整运行但不推送 |

## 系统架构

```
Wealth/
├── config/
│   └── config.yaml              # 配置文件
├── data/
│   └── daletou.db               # SQLite数据库（不纳入git，Actions缓存持久化）
├── src/
│   ├── data/
│   │   ├── storage.py           # 数据存储（开奖/预测/验证/校准/批次分析）
│   │   └── fetcher.py           # 体彩官方API数据获取
│   ├── analysis/
│   │   ├── analyzer.py          # 7维特征提取 + 相似度计算 + 智能候选生成
│   │   ├── calibration.py       # 自我校准器（权重调整 + WF回测 + 种子轮换）
│   │   ├── regression.py        # 批次回归分析（特征漂移检测）
│   │   ├── walk_forward.py      # Walk-Forward回测（多窗口权重优化）
│   │   └── statistics.py        # 统计验证（卡方/显著性/区分力/健康度）
│   ├── prediction/
│   │   └── predictor.py         # 预测器（多尺度融合打分）
│   ├── notification/
│   │   └── pushplus.py          # PushPlus微信推送
│   └── utils/
│       └── logger.py            # 结构化日志 + 健康检查告警
├── web/
│   └── submit.html              # 手机端提交表单（GitHub API直连）
├── logs/                        # 运行日志（JSON格式）
├── main.py                      # CLI主入口
├── requirements.txt
└── .github/workflows/
    ├── predict.yml              # 定时预测（周一/三/六 19:30）
    └── process_submission.yml   # Issue提交自动处理
```

## 算法说明

### 多尺度窗口融合打分

系统不再仅依赖全部历史数据，而是同时用5个不同大小的窗口分析：

| 窗口 | 含义 | 捕捉的规律 |
|------|------|-----------|
| 50期 | 最近50期 | 短期热号/冷号趋势 |
| 100期 | 最近100期 | 中期模式变化 |
| 200期 | 最近200期 | 中长期特征漂移 |
| 500期 | 最近500期 | 长期趋势 |
| all | 全部历史 | 全局基准特征 |

每个窗口独立构建特征并打分，最终得分按Walk-Forward回测优化的权重融合。

### Walk-Forward 回测

用历史数据模拟"用过去W期预测下一期"的过程：
1. 对每个窗口大小W，遍历最近100期
2. 用 draws[t-W:t] 构建特征，评分真实开奖 draws[t]
3. 同时评分50个随机候选作为基线
4. 计算实际开奖得分 vs 随机基线的比率和命中率
5. 预测力 = 均分比 × 命中率
6. 权重 ∝ 预测力（归一化后）

### 自我校准流程

```
获取开奖数据 → 回归分析 → 验证预测(含补验证) → 校准权重 → Walk-Forward回测 → 种子轮换 → 生成预测 → 推送
```

1. **特征维度权重**：根据命中期vs未命中期的相似度差异调整
2. **多窗口权重**：Walk-Forward回测结果自动更新
3. **种子轮换**：每次校准后种子 = 42 + 校准次数 × 7
4. **期号因子**：种子 = 基础种子 + 期号数值，保证每期不同

## GitHub Actions 配置

### 定时预测

- 触发时间：周一/三/六 19:30（北京时间）
- 数据库通过 Actions Cache 持久化（不纳入git）
- 缓存未命中时自动从API拉取全量数据

### Issue 自动处理

- 手机端提交开奖号码 → 创建Issue → 自动解析入库 → 验证+校准+预测+推送 → 关闭Issue

### 必需的 Secrets

| 名称 | 说明 |
|------|------|
| `PUSHPLUS_TOKEN` | PushPlus推送token |
| `GITHUB_TOKEN` | 自动提供，无需配置 |

## 注意事项

- 彩票具有随机性，本系统仅供娱乐参考，不构成任何购彩建议
- 历史数据越多，统计分析越准确
- 数据库文件不纳入git，通过GitHub Actions Cache在运行间持久化
- Walk-Forward回测首次运行可能需要几分钟（100期×5窗口×50候选）

## License

MIT
