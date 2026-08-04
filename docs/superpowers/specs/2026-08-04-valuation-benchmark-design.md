# 估值对标升级设计（Valuation Benchmark）

> 日期：2026-08-04
> 状态：已确认（grill 探讨定案）
> 前置：REITsMonitor 现有数据（月度 398 行/季度 168 行/完成度 11 条/静态 14 只）+ 深色终端看板 + 增量管线 + cron

## 目标

让看板从「经营数据监测」升级为「投后决策支持」：用户每月巡检时能一眼看到全行业**分派率收益率排名、NAV 折溢价、风险聚合提示**（第一期），并进阶到**特许经营 IRR 与性价比评分**（第二期）。

## 核心口径（已定案，不得随意更改）

| 指标 | 口径 | 说明 |
|---|---|---|
| 分派率收益率 | **TTM**：近 4 个季度实际可供分配之和 ÷ 最新市值 | 投后机构惯例；次新基金（<4 季数据）降级为最新季度年化（×4）并在表格标注「年化口径」 |
| NAV 折溢价 | 市价 ÷ 单位净值 − 1 | 溢价红（风险语义）/折价绿；**单位净值优先取季报直接披露的「期末基金份额净值」**（无则用 期末基金净资产 ÷ 期末基金份额总额 推算，两者同一报告提取口径自洽） |
| 市值 | `data/market_snapshot.json` 本地快照 | cron/update.py 每月抓取 14 只最新收盘价×份额存入；看板只读快照不依赖运行时网络；快照含月度历史（价格变动可追溯） |
| 特许经营 IRR（二期） | 当前市值买入 → 持有至特许经营到期（concession_years_left 年）→ 每年 TTM 分派（增长率假设 0%）→ 到期归零 → 解 IRR | 高速 REITs 特有估值（区别于永续型）；IRR < 分派率收益率 说明本金回收压力 |
| 性价比评分（二期） | 完成度 × 分派率排名 × IRR 合成 | 象限图（x=分派率排名，y=完成度）+ 评分卡 |

## 架构与数据流

```
季度报告 PDF ──parser_quarterly 扩展──> NAV(万元) → 模板季度 Sheet（补全现有空列）
akshare（cron 内）──update.py 扩展──> market_snapshot.json（价格×份额→市值，月度历史）
                                                │
看板「📊 估值对标」Tab ◄── data_loader/新模块 ────┘
  ├─ 分派率收益率排名（TTM，横向条形图 + 表格 + 行业中位数标注）
  ├─ NAV 折溢价（溢价红/折价绿）
  └─ 风险聚合提示（完成度未达标 / 折溢价>20% / 剩余年限<10）
```

## 第一期任务分解

1. **NAV 解析扩展**：`parser_quarterly.py` 增加三个字段提取——期末基金份额净值（优先）、期末基金净资产、期末基金份额总额（季报「主要财务指标/基金份额净值」区域定位，TDD + 真实季报 fixture）；模板季度 Sheet NAV 列回填（净资产口径），份额净值另存 `data/quarterly_nav.json`（模板结构不变铁律）；`data_loader.load_quarterly` 输出不变
1a. **NAV 侦察前置**：先下载 2-3 份季报确认「期末基金份额净值」披露位置与措辞（180201/508018 2026Q2 已有 PDF 可复用）→ 据此定 fixture
2. **市值快照**：`update.py` 扩展——cron 运行时用 akshare 抓 14 只最新收盘价（失败降级：保留上次快照 + errors 记录）；`data/market_snapshot.json` 结构 `{"snapshots": [{date, code, price, market_cap_wan}], "latest": {...}}`；**市值 = 收盘价 × 期末基金份额总额（与 NAV 同源，来自季度报告）**
3. **估值模块**：`src/valuation.py`（新）——`ttm_distributable(quarterly_df)`、`distribution_yield(df, snapshot)`、`nav_premium(df, snapshot, static)`、`risk_flags(...)`；纯函数可 TDD
4. **看板 Tab**：`app.py` 新增「📊 估值对标」Tab——排名条形图（青绿主线/中位数虚线）+ 折溢价表（语义色）+ 风险提示；快照缺失/NAV 缺失 → 列显示「—」降级不崩溃

## 第二期任务分解（进阶）

5. **特许经营 IRR**：`src/valuation.py` 增加 `concession_irr(yield_ttm, years_left, market_cap)`——数值解（scipy 或二分法，避免额外依赖则手写二分）；表格列 + 图（IRR vs 剩余年限散点，到期临近 IRR 对估值敏感的区域可视化）
6. **性价比评分**：`composite_score(completion, yield_rank, irr)`——三因子标准化合成（0-100）；象限图（x=分派率排名，y=完成度）+ 评分卡 Top/Bottom 5

## 错误处理与降级

- 市值快照缺失/过期（>45 天）→ 估值 Tab 显示「市值数据缺失（等待下月 cron 更新）」+ 表格降级为仅显示 TTM 分派（无收益率）
- NAV 缺失（解析失败基金）→ 折溢价列「—」
- 次新基金（<4 季）→ 收益率标注「年化口径」
- akshare 抓取失败 → 保留旧快照 + cron 摘要 errors 记录

## 测试策略

- `parser_quarterly` NAV：真实季报 fixture（180201/508001 2026Q2 已有）+ 断行/单位（元/万元）容错
- `src/valuation.py`：TTM 计算（含 <4 季降级）、折溢价正负、IRR 已知案例（构造 0% 增长率简单现金流验证二分法）、评分合成边界
- AppTest：新 Tab 渲染（有快照/无快照两态）+ 既有 3 Tab 不回归
- 全量 pytest 不回归（当前 224）

## 明确不做（YAGNI）

- 异常主动提醒（邮件/Telegram）——用户未选
- 数据导出（CSV/下载按钮）——用户暂缓
- 实时行情依赖——市值走本地快照
- 全市场 70+ 只扩展——独立于本升级，另行规划
