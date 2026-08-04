# 估值对标升级实施计划（Phase 4: Valuation Benchmark）

> **For agentic workers:** 任务按序执行；每个任务独立 TDD 红绿循环 + commit。代码实现由 opencode 完成，本计划只定接口规范与测试意图。
> 日期：2026-08-04 | 前置 Spec：`docs/superpowers/specs/2026-08-04-valuation-benchmark-design.md`

**Goal:** 看板新增「📊 估值对标」——分派率收益率排名（TTM）、NAV 折溢价、风险聚合提示（一期）；特许经营 IRR 与性价比评分（二期）。

**Architecture:** 数据前置（年报净值 + 季报份额 + 市值快照三个数据源）→ 纯函数估值模块 `src/valuation.py` → 看板 Tab 渲染。市值走本地快照（cron 内 akshare 抓取），看板不依赖运行时网络。

**Tech Stack:** Python 3.11、pandas、plotly、streamlit（现有）；akshare（cron 内）；二分法手写（无 scipy 依赖）。

## Global Constraints

- 模板 Excel 结构**严格不变**（列名/Sheet 名不得增改）；新数据一律独立文件（`data/*.json`）
- 代码由 opencode 写（TDD 红绿循环）；助手独立复跑 pytest 后 commit（前缀 `feat:`/`fix:`/`data:`/`test:`/`docs:`）
- git 身份 noreply；`.wayfinder/` 与 `*.bak` 不入库
- 沪市接口限流防护：15s 基金间隔 + 90s×3 重试（沿用现有模式）
- 全量 pytest 基线 224，不回归
- 纯函数模块禁止网络/文件 I/O（可测性）；I/O 只在 update.py 侧

---

### Task 1: 年报解析器扩展 NAV 字段

**Files:**
- Modify: `tools/reits_collector/parser_annual.py`
- Test: `tests/test_parser_annual.py`
- Data: `data/annual_completion.json`（重写补字段）

**Interfaces:**
- 扩展 `parse_annual_completion(pdf_path)` 返回 dict 增加：
  - `nav_unit_price: float | None` — 年报「3.2 其他财务指标·期末基金份额净值」（元/份）
  - `nav_wan: float | None` — 「期末基金净资产」（万元）
- 字段缺失（早期年报无净值披露）→ None，不抛错

**测试意图（opencode 补全断言）：**
- fixture `tests/fixtures/annual_180201_2022_completion.txt` 已含 3.2 节片段（净值 12.2867 / 净资产 8,600,664,096.81）→ 解析得 nav_unit_price=12.2867、nav_wan=860066.41（万元，÷10000）
- 新 fixture：`annual_180201_2022_nav.txt`（3.2 节完整片段，含断行/千分位变体）——已存在（工作区 `tests/fixtures/annual_180201_2022_nav.txt` 未提交，先提交为 test: fixture）
- 无净值披露的旧年报 → 字段为 None
- 完成度/年份解析逻辑不回归（现有 5 格式测试全绿）

**完成后**：`data/annual_completion.json` 全部 11 条记录回填 nav 字段（重跑解析已缓存 PDF——`%TEMP%\reits_annual\` 有全部年报；新增记录的写入逻辑不变）。commit `feat: parser_annual NAV fields (nav_unit_price, nav_wan)`。

---

### Task 2: 份额总额数据文件

**Files:**
- Create: `data/fund_shares.json`
- Test: `tests/test_parser_quarterly.py`（若复用季报解析）或纯数据任务

**Interfaces:**
- `data/fund_shares.json`：`{"shares": {"180201": 700000000.0, ...}}`（份，最新报告期末份额总额）
- 提取：从各基金最新季报「报告期末基金份额总额」（180201 2026Q2 已验证：700,000,000.00 份）；季报 PDF 缓存 `%TEMP%\reits_quarterly\` 已有 168 份 → 批量提取一次

**测试意图：**
- parser_quarterly 若扩展 `fund_shares` 字段：fixture `quarterly_180201_2026Q2.pdf` 解析得 700000000.0
- 份额文件缺失基金 → 市值计算时标记「份额缺失」降级

**完成后**：14 只份额全部入库（2026Q2 口径）。commit `data: fund shares snapshot (14 funds, 2026Q2)`。

---

### Task 3: 市值快照（update.py 扩展）

**Files:**
- Modify: `tools/reits_collector/update.py`
- Create: `data/market_snapshot.json`
- Test: `tests/test_update.py`

**Interfaces:**
- 新函数 `fetch_market_snapshot(shares: dict, errors: list | None = None) -> dict`：
  - akshare 抓 14 只最新收盘价（现有 `market_data.py` 的 `get_realtime_quotes()` 可复用——返回含 code→price 的映射；内部已带 5s 超时降级）
  - `market_cap_wan = price × shares[code] / 10000`
  - 失败基金：保留旧快照值 + errors 记录
  - 返回 `{"snapshots": [{"date": "2026-08-04", "code": "180201", "price": 7.56, "market_cap_wan": 529200.0}, ...], "latest": {...}}`（snapshots 追加月度历史；latest 覆盖）
- `update_template` 摘要增加 `"snapshot_updated": bool`（有快照变化时 True）

**测试意图：**
- mock market_data.get_realtime_quotes：返回全量价格 → 快照含 14 只、市值 = 价×份额/10000
- 部分失败（返回 12 只）→ 缺失 2 只从旧快照保留 + errors 2 条
- 全失败 → 返回旧快照 + errors，summary 不崩
- update_template 调用链：mock fetch_market_snapshot → 摘要键存在

**完成后**：本地跑一次生成真实快照（akshare 可用时）。commit `feat: market snapshot in update pipeline`。

---

### Task 4: 估值模块 src/valuation.py

**Files:**
- Create: `src/valuation.py`
- Test: `tests/test_valuation.py`

**Interfaces（全部纯函数，无 I/O）：**
- `ttm_distributable(quarterly_df: pd.DataFrame) -> pd.Series`：按 code 分组，取最近 4 个季度 `distributable_wan` 之和；<4 季 → 最新季度 ×4（调用方标注口径）；无数据 → NaN
- `distribution_yield(ttm: pd.Series, snapshot_latest: dict, shares: dict) -> pd.Series`：`ttm × 10000 / (price × shares)`（收益率，小数）；快照缺失基金 → NaN
- `nav_premium(price_series, nav_unit_price_series) -> pd.Series`：`price / nav_unit - 1`；任一缺失 → NaN
- `risk_flags(completion_df, premium_series, years_left_series) -> pd.DataFrame`：每基金聚合标记——完成度 <80（风险）/ 80-100（关注）/ 折溢价 >20%（风险）/ 剩余年限 <10（风险）；输出 `{"code", "flags": [str]}` 行
- `_fund_shares_latest(shares: dict) -> dict`：静态数据读取辅助（仅 dict 操作）

**测试意图：**
- ttm：构造 5 季数据（最新 4 季求和正确、含 NaN 季处理、<4 季降级×4）
- yield：已知 price/shares/ttm → 收益率精确断言
- premium：正溢价/折价/缺失 → 正负号与 NaN
- risk_flags：全组合（完成度红/橙、折溢价>20%、年限<10）→ 标记正确；无风险 → 空标记
- 全部 NaN 输入不抛错

**完成后**：commit `feat: valuation module (ttm yield, NAV premium, risk flags)`。

---

### Task 5: 看板「📊 估值对标」Tab

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces（app.py 内部函数）：**
- `render_valuation(quarterly_df, completion_df, snapshot_data, shares, static_df)`：
  - 分派率收益率排名：横向条形图（plotly，青绿主线 `#2DD4BF`、行业中位数虚线 `#8A8F98` dash）、排名表（代码/名称/收益率/口径标注「TTM/年化」）
  - NAV 折溢价表：市价/净值/折溢价%（语义色：溢价红 `#F87171`、折价绿 `#10B981`）
  - 风险聚合提示：`st.warning` 列出 risk_flags 标记的基金（「508007 山高集团：完成度未达标」格式）
  - 降级：快照缺失/过期（>45 天）→ `st.info`「市值数据缺失（等待下月 cron 更新）」+ 表格仅显示 TTM 分派；NAV 缺失 → 列「—」
- 数据读取：`data/market_snapshot.json` + `data/fund_shares.json`（JSON 读取函数，文件缺失返回空 dict 不崩）

**测试意图（AppTest）：**
- 有快照数据 → Tab 渲染：排名表行数 = 有市值基金数、折溢价表存在、风险提示区存在
- 无快照文件 → Tab 显示降级 st.info，不抛异常
- 现有 3 Tab 不回归（Tab 索引 0/1/2 不变，新增 Tab 排第 3）

**完成后**：本地浏览器截图验证（深色风格一致：半透明卡片/等宽数字/语义色）。commit `feat: valuation benchmark tab (yield ranking, NAV premium, risk flags)`。

---

### Task 6: 特许经营 IRR（二期）

**Files:**
- Modify: `src/valuation.py`
- Test: `tests/test_valuation.py`

**Interfaces:**
- `concession_irr(price, shares, annual_distributable_wan, years_left, growth=0.0) -> float | None`：
  - 现金流：期初 −price×shares（买入），每年 +annual_distributable_wan×10000×（1+growth）^t，期末归零
  - 二分法解 IRR（初始区间 [−0.99, 1.0]，精度 1e-6，max_iter 100）；NPV 函数单调性保证收敛；无解 → None
  - 纯函数，无 scipy

**测试意图：**
- 已知案例：IRR = 分派率（growth=0、永续退化校验——用 2 年期小现金流手算验证二分精度）
- 极端：years_left=1、分派>市值（IRR 高）、分派 0（IRR=−100% 边界）
- growth>0 → IRR 高于 growth=0

**完成后**：看板排名表加 IRR 列（可选列，二期 Tab 呈现）+ 散点图（IRR vs 剩余年限，到期临近区域标注）。commit `feat: concession IRR (bisection solver)`。

---

### Task 7: 性价比评分（二期）

**Files:**
- Modify: `src/valuation.py`、`app.py`
- Test: `tests/test_valuation.py`

**Interfaces:**
- `composite_score(completion_pct: float | None, yield_rank: int | None, irr: float | None, n_funds: int) -> float | None`：
  - 三因子标准化：完成度（min-max 到 0-100）、收益率排名（rank/n → 100×(1−rank/n)）、IRR（min-max）
  - 缺因子 → 剩余因子加权归一；全缺 → None
- 看板：象限图（x=分派率收益率排名，y=完成度，气泡=IRR）+ Top/Bottom 5 评分卡

**测试意图：**
- 已知三因子 → 分数计算精确
- 缺 1-2 因子 → 归一化后仍 0-100
- 全缺 → None

**完成后**：commit `feat: composite value score (completion × yield × IRR)`。

---

### Task 8: cron 与文档收尾

**Files:**
- Modify: cron job（Hermes cronjob update——`31e9a33e8b1a`）
- Modify: `README.md`（Phase 4 摘要 + 估值指标口径）

**Interfaces:**
- cron prompt 增加：update.py 现含市值快照（摘要键 snapshot_updated）；推送条件含快照变化
- README：Analytics 列表加 yield ranking/NAV premium/IRR；Roadmap 勾选 Phase 4 一期

**完成后**：commit `docs: Phase 4 roadmap + README`；cron 更新。全量 pytest + push。

---

## 执行顺序与依赖

```
Task 1（年报 NAV）→ Task 2（份额）→ Task 3（快照）→ Task 4（估值模块）→ Task 5（Tab）→ [二期] Task 6（IRR）→ Task 7（评分）→ Task 8（收尾）
```
Task 1-5 一期（核心），6-7 二期，8 收尾。每任务独立可测可提交；opencode 逐任务 TDD。
