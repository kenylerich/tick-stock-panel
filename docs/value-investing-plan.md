# 价值投资 · 经营分析体系 — 需求跟踪

> 目标:从经营视角(行业/商业模式/护城河/经营态势)自动分析公司,量化证据 + AI 框架化推理。
> 状态标记:⬜ 未开始 | 🔄 进行中 | ✅ 完成 | ⏸ 暂停/阻塞
> **Issue 跟踪:https://github.com/kenylerich/tick-stock-panel/issues**(标签 `value-investing`,#1-#9)**

## 阶段 〇:地基检查

- [ ] **0.1 财务数据同步完成** → [#1](https://github.com/kenylerich/tick-stock-panel/issues/1) — 五张表全部落盘(metrics 已完成 5574 只;income/balance_sheet/cash_flow 排队中;shares 扶摇无接口跳过)。验收:「数据」页财务五表 rows > 0,`syncing=false`。

## 阶段 A:财务指标扩充(量化地基)

- [x] **A1 新增 ~10 个财务指标** → [#2](https://github.com/kenylerich/tick-stock-panel/issues/2) — PE(由 PB/ROE 换算)、ROA、每股经营现金流、净现比、流动/速动比率、长期资本负债比、总资产增速等。改动:`backtest/fundamentals.py` 映射表 + `factors/registry.py` 注册(只追加不重排)。验收:策略条件编辑器可选新因子;AI 可查 `pe_latest` 排名;定向 pytest 通过。
- [x] **A2 新增 5 个经营趋势指标** → [#3](https://github.com/kenylerich/tick-stock-panel/issues/3) — roe_avg_4q / roe_min_8q / revenue_yoy_improving / net_margin_trend / eps_trend。报告期空间预计算 + 公告日 PIT 戳(防未来函数,专项测试)。验收:"连续4季 ROE>10% 且增速改善"类条件可回测。

## 阶段 B:商业模式数据接入

- [x] **B1 AKShare 免费数据桥** → [#4](https://github.com/kenylerich/tick-stock-panel/issues/4) — 独立侧车容器(Docker),桥接东财/同花顺公开数据,接入面板自定义源通道。可插拔:桥故障不影响面板其它功能。验收:设置页新增数据源且健康。
- [ ] **B2 主营构成数据** → [#5](https://github.com/kenylerich/tick-stock-panel/issues/5) — 分产品/分地区收入与毛利率拆解(每公司一张)。来源 AKShare F10;财报季更新。验收:个股页出现"主营构成"区块。
- [ ] **B3 公司概况与同行清单** → [#6](https://github.com/kenylerich/tick-stock-panel/issues/6) — 主营描述 + 同行业可比公司名单(横向对比用)。验收:AI 能自动答"它的同行是谁、各自表现"。

## 阶段 C:AI 经营分析工作流

- [ ] **C1 AI 经营分析工具包** → [#7](https://github.com/kenylerich/tick-stock-panel/issues/7) — 提示词+工具编排:行业归属→同行对比→主营构成→财务趋势→现金流质量,固定取数顺序。验收:对话"从经营角度分析 600519"产出完整流程报告,取数过程可见可核对。
- [ ] **C2 结构化报告模板** → [#8](https://github.com/kenylerich/tick-stock-panel/issues/8) — 固定骨架:①行业特点 ②商业模式 ③护城河(量化+业务证据→归类) ④经营态势与风险。每条结论带数据出处。验收:报告页出现"经营分析"类型,两次分析结构一致可比。
- [ ] **C3 自选股定时体检** → [#9](https://github.com/kenylerich/tick-stock-panel/issues/9) — 调度器定期对自选跑 C2,重要变化(毛利率骤降/现金流恶化/业务结构大变)自动提醒。**待用户定:频率(日/周)、范围(全部自选/分组)、报告风格(精炼数据型/叙述型)、token 成本上限**。验收:报告页定期自动更新,异动有通知。

## 批次与依赖

```
批次1: A1+A2+B1  →  批次2: B2+B3  →  批次3: C1+C2  →  批次4: C3
0.1 为 C3 前置;A/B 批次间无强依赖可并行。
```

## 决策记录

- 2026-10-21:确认方向为"经营视角"(非纯因子打分);PE 用 PB/ROE 换算(无需股本数据);护城河定位为"证据链+框架推理",AI 不做荐股判断。
- 待定:C3 参数(频率/范围/风格);股息率与自由现金流指标(需分红数据/跨表计算,列二期)。

## 变更日志

- 2026-10-21:初版,任务 0-13 项。
- 2026-10-21:**批次1 完成**(fc10b2f): A1+A2+B1, issue #2/#3/#4 已关闭。B3 风险已记录在 #6(东财板块成分接口不稳,同行清单降级)。
