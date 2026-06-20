# 大乐透智能预测系统 🎯

基于历史开奖数据的统计分析，学习大乐透的"随机性特征"，在每期开奖前生成与真实开奖随机性最相似的推荐号码，并通过 PushPlus 推送到微信。

## 功能特性

- **历史数据管理**：以50期为一批，持续获取从第一期至今的所有开奖数据（SQLite存储，自动去重）
- **统计特征学习**：频率分析、和值分布、奇偶比、区间分布、跨度、连号等7维特征提取
- **多策略候选生成**：频率加权 / 模式约束 / 纯随机 三种策略混合生成候选
- **相似度评分**：综合7项指标计算候选与历史开奖的相似度，选出最接近的3注
- **自动推送**：通过 PushPlus 推送预测结果到微信（HTML格式，表格展示）
- **定时调度**：GitHub Actions 自动在每周一/三/六 19:30（北京时间）运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 PushPlus Token

编辑 `config/config.yaml`，填入你的 PushPlus token（从 https://www.pushplus.plus/ 获取）：

```yaml
pushplus:
  token: "your_pushplus_token_here"
```

### 3. 初始化数据库

```bash
python main.py init
```

### 4. 获取历史数据（首次运行，会获取从第一期至今的所有数据）

```bash
python main.py fetch-all
```

> ⚠️ 初次运行会逐批（50期/批）获取历史数据，直到第一期为止，可能需要几分钟。

### 5. 分析历史数据（可选，查看统计特征）

```bash
python main.py analyze
```

### 6. 生成并推送预测

```bash
python main.py predict
```

### 7. 完整运行（获取最新 + 预测 + 推送）

```bash
python main.py run-once
```

## 命令行全集

| 命令 | 说明 |
|------|------|
| `python main.py init` | 初始化数据库 |
| `python main.py fetch` | 获取最新一期开奖数据 |
| `python main.py fetch-all` | 批量获取所有历史数据（50期/批） |
| `python main.py analyze` | 分析历史数据，打印统计特征 |
| `python main.py predict` | 生成预测并通过 PushPlus 推送 |
| `python main.py run-once` | 完整运行一次（获取最新+预测+推送） |

## 定时自动运行（GitHub Actions）

项目已配置 GitHub Actions 定时任务，在每周一/三/六 19:30（北京时间）自动运行。

### 启用步骤

1. Fork 或 push 本仓库到你的 GitHub
2. 在仓库 **Settings → Secrets and variables → Actions** 中添加 secret：
   - Name: `PUSHPLUS_TOKEN`
   - Value: 你的 PushPlus token
3. 确保 GitHub Actions 已启用（Settings → Actions → General）
4. 可手动触发测试：**Actions → 大乐透定时预测推送 → Run workflow**

## 相似度评分说明

系统从7个维度评估候选号码与历史开奖的相似度：

| 维度 | 权重 | 说明 |
|------|------|------|
| 前区和值 | 0.25 | 5个前区号码之和，越接近历史均值得分越高 |
| 奇偶比 | 0.15 | 前区奇偶数比例，匹配历史最常见模式 |
| 区间分布 | 0.20 | 前区三区间（1-12/13-24/25-35）号码分布 |
| 前区跨度 | 0.15 | 最大号-最小号，越接近历史平均跨度得分越高 |
| 连号特征 | 0.10 | 是否有连号（如12-13）及连号组数 |
| 后区和值 | 0.10 | 2个后区号码之和 |
| 频率偏离度 | 0.05 | 候选号码的历史出现频率，避免过热或过冷 |

## 项目结构

```
Wealth/
├── config/
│   └── config.yaml          # 配置文件
├── data/
│   └── daletou.db         # SQLite数据库（运行后自动生成）
├── src/
│   ├── data/
│   │   ├── storage.py     # 数据存储（SQLite）
│   │   └── fetcher.py   # 多数据源获取（500彩票/官方API）
│   ├── analysis/
│   │   └── analyzer.py   # 统计分析 + 相似度计算
│   ├── prediction/
│   │   └── predictor.py  # 候选生成 + 相似度排序
│   └── notification/
│       └── pushplus.py    # PushPlus 微信推送
├── logs/
│   └── predictions.log    # 预测记录日志
├── main.py                 # CLI 主入口
├── requirements.txt        # Python 依赖
└── .github/
    └── workflows/
        └── predict.yml    # GitHub Actions 定时任务
```

## 注意事项

- 🎲 **彩票具有随机性，本系统仅供娱乐参考，不构成任何购彩建议**
- 📊 历史数据越多，统计分析越准确（建议至少积累100期数据后再依赖预测结果）
- 🔄 系统会在每次 `fetch` 和 `predict` 后自动更新本地数据库
- 🔔 如果使用 GitHub Actions 定时运行，数据库文件会随每次运行更新并提交回仓库

## 数据来源

系统支持多数据源自动容错：
- 中国体彩网（官方）
- 500彩票网（HTML解析）
- 本地种子数据（可手动导入）

## License

MIT
