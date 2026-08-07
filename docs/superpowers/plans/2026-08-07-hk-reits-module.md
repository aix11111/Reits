# 香港 REITs 模块实施计划（HK Module — Link REIT PoC）

> **For agentic workers:** 任务按序执行，每任务独立 TDD 红绿循环 + commit。代码实现由 opencode 完成，本计划只定接口规范与测试意图。
> 日期：2026-08-07 | 前置 Spec：`docs/superpowers/specs/2026-08-07-hk-reits-module-design.md`

**Goal:** REITsMonitor 升级多市场——香港模块 PoC（领展 823.HK 全链路）+ 侧边栏「市场」筛选。

**Architecture:** HKEX 直链下载 → 年报解析（parser_hk_annual）→ HK 指标纯函数 → 看板市场维度（中国默认零变化）。数据文件 `data/hk_*.json`，不动模板 Excel。

**Tech Stack:** 现有 + akshare（新浪港股 `stock_hk_daily`）、PyMuPDF（复用）、pytest。

## Global Constraints

- 模板 Excel 结构严格不变；HK 数据一律独立 JSON（`data/hk_*.json`）
- 中国模式（默认）渲染路径零变化（硬约束）
- 代码 opencode TDD；助手独立复跑 pytest 后 commit（`feat:`/`data:`/`test:`/`docs:`）
- git 身份 noreply；`.wayfinder`/`*.bak`/`data/_cache/` 不入库
- 全量 pytest 基线 413 不回归

---

### Task 1: HKEX 年报下载器 + hk_funds.json

**Files:**
- Create: `tools/reits_collector/hkex.py`
- Create: `data/hk_funds.json`
- Test: `tests/test_hkex.py`

**Interfaces:**
- `download_annual_report(url: str, dest: Path) -> Path`：requests + UA，成功返回 dest；失败抛异常（调用方捕获）
- `HKEX_UA = "Mozilla/5.0..."` 常量
- `data/hk_funds.json`：`{"funds": [{"code": "00823", "name": "领展房产基金", "name_en": "Link REIT", "market": "HK", "annual_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0616/2025061600521.pdf", "fiscal_year_end": "0331"}]}`（PoC 领展 1 条）

**测试意图：** download 用 mock requests（成功写文件/异常传播）；hk_funds.json 可加载且含领展条目。

**完成后：** commit `feat: hkex downloader + hk_funds.json (Link REIT)`。

---

### Task 2: 港年报解析器 parser_hk_annual.py

**Files:**
- Create: `tools/reits_collector/parser_hk_annual.py`
- Test: `tests/test_parser_hk_annual.py`
- Fixture: `tests/fixtures/hk_linkreit_ar2425_financials.txt`（从 `data/_cache/hk/linkreit_ar2425.pdf` 提取的财务摘要段落，含断行/千分位）

**Interfaces:**
- `parse_hk_annual(pdf_path: Path | str) -> dict`：
  - `fiscal_year: str` — 「for the year ended 31 March 2025」→ "FY2024/25"（或 "2024/25"）
  - `revenue_wan: float | None` — Revenue（港元万元：14223M → 1422300 万）
  - `npi_wan: float | None` — Net Property Income（10619M → 1061900 万）
  - `dpu_hk_cents: float | None` — DPU（272.34）
  - `nav_per_unit_hkd: float | None` — NAV per Unit（63.30）
  - `occupancy: dict | None` — 出租率（按地区/组合，如 {"overall": 0.978}，提取不到 None）
  - 字段缺失 → None 不抛错
- `_extract_fiscal_year(text) -> str | None`（辅助纯函数）

**测试意图（真实文本 fixture）：**
- FY2024/25 全年值精确断言：revenue=1422300、npi=1061900、dpu=272.34、nav=63.30
- 断行/千分位变体容错；缺失字段 → None
- 注意：年报含「Financial Highlights」（Financial Position 页的 Revenue/NPI/DPU/NAV 快照）——以该段落为主提取点；「for the year ended 31 March 2025」定位财年

**完成后：** 对 `data/_cache/hk/linkreit_ar2425.pdf` 实跑 → `data/hk_annual.json`（`{"annual": [{"code": "00823", "fiscal_year": "2024/25", ...}]}`）。commit `feat: HK annual report parser (Link REIT financials)`。

---

### Task 3: 港股行情快照

**Files:**
- Create: `tools/reits_collector/hk_market.py`
- Create: `data/hk_market_snapshot.json`
- Test: `tests/test_hk_market.py`

**Interfaces:**
- `fetch_hk_prices(codes: list[str], errors: list | None = None) -> dict`：akshare `stock_hk_daily(symbol=code)` 最新收盘价 → `{code: {"price": float, "date": "YYYY-MM-DD"}}`；单只失败 errors + 跳过；全失败返回 {}
- `update_hk_snapshot(prices: dict) -> dict`：合并写 `data/hk_market_snapshot.json`（`{"snapshots": [{date, code, price}], "latest": {code: price}}`，去重追加）
- 5s 超时包装（复用 `_call_with_timeout` 模式，akshare 慢接口）

**测试意图：** mock `stock_hk_daily`（DataFrame 返回）→ 最新收盘提取；失败 → errors；快照合并去重。

**完成后：** 本地实跑领展 → 快照含 00823 38.78 左右（新浪源）。commit `feat: HK market snapshot (sina daily)`。

---

### Task 4: HK 指标纯函数

**Files:**
- Modify: `src/valuation.py`（追加，不破坏现有）
- Test: `tests/test_valuation.py`

**Interfaces（纯函数）：**
- `hk_distribution_yield(dpu_hk_cents: float, price_hkd: float) -> float`：`dpu/100/price`（小数；领展 272.34¢/38.78 ≈ 0.0702）
- `hk_nav_premium(price_hkd: float, nav_per_unit: float) -> float`：`price/nav − 1`（小数；38.78/63.30−1 ≈ −0.387）
- `npi_margin(npi_wan: float, revenue_wan: float) -> float`：`npi/revenue`（领展 10619/14223 ≈ 0.7466）
- 非法输入（0/None）→ NaN

**测试意图：** 领展基准值精确断言（round 4）；零除/None → NaN。

**完成后：** commit `feat: HK valuation functions (DPU yield, P/NAV, NPI margin)`。

---

### Task 5: 看板「市场」筛选接入

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- 侧边栏「市场」selectbox（`中国`/`香港`，默认「中国」，现有 UI 零变化）
- 市场=中国：**现有渲染路径完全不变**（联动/87 只/4 Tab）
- 市场=香港：基金选择器 = hk_funds 清单（领展 1 条）；经营数据 Tab = HK 指标（财务年/Revenue/NPI/DPU/NAV/出租率 KPI 卡 + 数据表；无月度区块——港 REITs 无月度披露，可不显示或「—」）；估值对标 Tab = 分派收益率/P-NAV 折溢价（领展单只，表格/单行）；行情 Tab = 新浪日线图（若已实现 HK 历史可显示，否则降级）
- 数据读取：`data/hk_annual.json`/`hk_market_snapshot.json`/`hk_funds.json` 缺失 → st.info「香港数据缺失」不崩
- 副标题/标题：st.title 保持「REITsMonitor — 公募REITs投后分析看板」→ 升级「REITsMonitor — 多市场REITs投后分析看板」；caption 同步

**测试意图（AppTest）：**
- 默认中国：现有测试全过（零变化）
- 市场选香港：基金选择器=HK 清单；经营 Tab 含「NPI」「DPU」文案；无异常
- hk JSON 缺失（monkeypatch）→ st.info 不崩
- 标题含「多市场」

**完成后：** 浏览器实测（市场切换）。commit `feat: market dimension (CN/HK) in sidebar + HK views`。

---

### Task 6: README 定位升级

**Files:**
- Modify: `README.md`

**内容：** 副标题「China's public REITs」→ 多市场；Data 表加 HK 层；Features 加 HK 模块（DPU yield/P-NAV）；Project structure 加 hkex.py/parser_hk_annual.py/hk_*.json；无 Roadmap（保持）。

**完成后：** commit `docs: multi-market positioning (HK module)`。

---

## 执行顺序

```
Task 1（下载器+清单）→ Task 2（解析器+数据）→ Task 3（行情快照）→ Task 4（指标）→ Task 5（看板）→ Task 6（README）
```
每任务独立可测可提交；opencode 逐任务 TDD。
