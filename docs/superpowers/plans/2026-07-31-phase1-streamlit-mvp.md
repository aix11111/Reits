# Phase 1: REITsMonitor Streamlit MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 REITsMonitor Phase 1 —— 一个可运行的 Streamlit Web 应用，展示 14 只中国高速公路公募REITs 的经营数据看板（通行费收入、车流量、NOI利润率、可供分配收益率）与实时行情走势。

**Architecture:** 纯本地 Streamlit 单应用。数据分两层：`data_loader.py` 读取手动维护的 Excel 经营数据（data/REITsMonitor_数据模板_v1.xlsx，三个 Sheet：静态信息/月度数据/季度数据）；`market_data.py` 封装 akshare 行情接口。`metrics.py` 计算派生指标，`charts.py` 生成 plotly 图表，`app.py` 组装 UI。所有纯逻辑层有 pytest 测试，akshare 调用通过 mock 测试，Streamlit UI 手动验证。

**Tech Stack:** Python 3.11 · Streamlit ≥1.36 · pandas ≥2.0 · plotly ≥5.20 · akshare ≥1.14 · openpyxl ≥3.1 · pytest ≥8.0

## Global Constraints

- 项目根目录：`D:\tool\REITsMonitor\`（bash 路径 `/d/tool/REITsMonitor/`）
- Python 3.11（用户机器已装 `python` = 3.11.15）
- Excel 文件名与 Sheet 名**必须严格匹配**模板：文件 `data/REITsMonitor_数据模板_v1.xlsx`，Sheet `静态信息`/`月度数据`/`季度数据`，列名与模板完全一致（见 Task 2 的列名常量）
- 界面文字用中文；代码标识符用英文；所有数值单位以模板列名为准（万元、辆/日、%）
- akshare 网络调用可能失败（用户环境已实测过连接错误）：所有行情调用必须 try/except，失败时返回空 DataFrame，UI 层显示警告而非崩溃
- 测试用 pytest；TDD 顺序：先写失败测试，再写实现，再跑通，再 commit
- 每个 Task 结束必须 `git commit`；commit message 前缀：`feat:` / `test:` / `chore:`
- 不要引入模板中没有的字段；NAV 折溢价（需要基金份额数据）属于 Phase 3，**不在本计划内**
- 中文文件/Sheet 名在代码中统一用 `pathlib.Path` 和 utf-8 处理

---

### Task 1: 项目脚手架（requirements + .gitignore + git init）

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md`（占位，Task 7 完善）

**Interfaces:**
- Consumes: 无
- Produces: 项目目录结构与依赖清单；后续所有 Task 依赖此环境

- [ ] **Step 1: 创建 requirements.txt**

写 `D:\tool\REITsMonitor\requirements.txt`：

```
streamlit>=1.36
pandas>=2.0
plotly>=5.20
akshare>=1.14
openpyxl>=3.1
pytest>=8.0
```

- [ ] **Step 2: 创建 .gitignore**

写 `D:\tool\REITsMonitor\.gitignore`：

```
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
.streamlit/secrets.toml
*.egg-info/
dist/
build/
```

- [ ] **Step 3: 创建包目录**

```bash
mkdir -p /d/tool/REITsMonitor/src /d/tool/REITsMonitor/tests
touch /d/tool/REITsMonitor/src/__init__.py /d/tool/REITsMonitor/tests/__init__.py
```

- [ ] **Step 4: 验证环境**

```bash
cd /d/tool/REITsMonitor && python -m pip install -r requirements.txt -q
python -c "import streamlit, pandas, plotly, akshare, openpyxl; print('deps ok')"
```

Expected: `deps ok`

- [ ] **Step 5: git init 并提交**

```bash
cd /d/tool/REITsMonitor && git init && git add -A && git commit -m "chore: project scaffold (requirements, gitignore, package dirs)"
```

Expected: commit 成功，`git log --oneline` 显示 1 条记录

---

### Task 2: data_loader.py — Excel 经营数据读取

**Files:**
- Create: `src/data_loader.py`
- Create: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: Task 1 的依赖
- Produces:
  - 列名常量：`STATIC_COLS`（9个，中文→英文映射）、`MONTHLY_COLS`（8个）、`QUARTERLY_COLS`（10个）
  - `load_static(path: Path) -> pd.DataFrame`，列：`code, name, asset, region, mileage_km, listing_date, issue_scale_yi, concession_years_left, asset_type`
  - `load_monthly(path: Path) -> pd.DataFrame`，列：`period, code, name, toll_revenue_wan, daily_traffic, toll_revenue_yoy, traffic_yoy, source`
  - `load_quarterly(path: Path) -> pd.DataFrame`，列：`period, code, name, total_revenue_wan, total_cost_wan, net_profit_wan, distributable_wan, ebitda_wan, nav_wan, source`
  - `load_all(path: Path) -> dict[str, pd.DataFrame]`，key 为 `'static'|'monthly'|'quarterly'`
  - 文件不存在时抛 `FileNotFoundError`，提示信息含正确路径
- **中文列名映射必须与模板严格一致**：实现前先用 pandas 读取 `data/REITsMonitor_数据模板_v1.xlsx` 各 Sheet 的实际表头（注意含换行符、括号、单位等细节），以读取结果为准构建映射，不得臆造列名

- [ ] **Step 1: 写失败测试**

写 `D:\tool\REITsMonitor\tests\test_data_loader.py`：

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_data_loader.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.data_loader'`（或 import 错误）

- [ ] **Step 3: 写实现**

写 `D:\tool\REITsMonitor\src\data_loader.py`：

- [ ] **Step 4: 运行确认通过**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_data_loader.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "feat: add Excel data loader with normalized columns"
```

---

### Task 3: metrics.py — 派生指标计算

**Files:**
- Create: `src/metrics.py`
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: Task 2 的 `load_quarterly()` 输出的 DataFrame（列名见 Task 2）
- Produces:
  - `noi_margin(df: pd.DataFrame) -> pd.Series` —— (营业总收入-营业成本)/营业总收入，index 与 df 对齐
  - `net_margin(df: pd.DataFrame) -> pd.Series` —— 净利润/营业总收入
  - `annualized_distributable_yield(df: pd.DataFrame) -> pd.Series` —— 可供分配金额×4 / 基金净资产（年化近似，Phase 1 够用）
  - `latest_metrics(df: pd.DataFrame, code: str) -> dict[str, float|str]` —— 单只REIT最新一季的 `period, noi_margin, net_margin, distributable_yield`；无数据时返回空 dict

- [ ] **Step 1: 写失败测试**

写 `D:\tool\REITsMonitor\tests\test_metrics.py`：

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_metrics.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.metrics'`

- [ ] **Step 3: 写实现**

写 `D:\tool\REITsMonitor\src\metrics.py`：

- [ ] **Step 4: 运行确认通过**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_metrics.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "feat: add derived metrics (NOI margin, net margin, distributable yield)"
```

---

### Task 4: market_data.py — akshare 行情封装

**Files:**
- Create: `src/market_data.py`
- Create: `tests/test_market_data.py`

**Interfaces:**
- Consumes: 无（直接调用 akshare；测试用 monkeypatch 模拟）
- Produces:
  - `get_realtime_quotes() -> pd.DataFrame`，列：`code, name, price, pct_change, volume, amount`；失败返回空 DataFrame（列齐全）
  - `get_hist(symbol: str) -> pd.DataFrame`，列：`date(datetime64), open, high, low, close, volume, amount`；失败返回空 DataFrame
  - 两个函数在 akshare 异常时打印警告 `print(f"[market_data] {func_name} 失败: {e}")` 并返回空表

- [ ] **Step 1: 写失败测试**

写 `D:\tool\REITsMonitor\tests\test_market_data.py`：

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_market_data.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.market_data'`

- [ ] **Step 3: 写实现**

写 `D:\tool\REITsMonitor\src\market_data.py`：

- [ ] **Step 4: 运行确认通过**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_market_data.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "feat: add akshare market data wrapper with graceful failure"
```

---

### Task 5: charts.py — plotly 图表构建

**Files:**
- Create: `src/charts.py`
- Create: `tests/test_charts.py`

**Interfaces:**
- Consumes: 任意含指定列的 DataFrame
- Produces:
  - `line_chart(df: pd.DataFrame, x_col: str, y_col: str, title: str, y_label: str) -> go.Figure`
  - `bar_chart(df: pd.DataFrame, x_col: str, y_col: str, title: str, y_label: str) -> go.Figure`
  - 两者都返回 plotly Figure；空 DataFrame 时返回带空数据的 Figure（不抛异常）

- [ ] **Step 1: 写失败测试**

写 `D:\tool\REITsMonitor\tests\test_charts.py`：

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_charts.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.charts'`

- [ ] **Step 3: 写实现**

写 `D:\tool\REITsMonitor\src\charts.py`：

- [ ] **Step 4: 运行确认通过**

Run: `cd /d/tool/REITsMonitor && python -m pytest tests/test_charts.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "feat: add plotly chart builders"
```

---

### Task 6: app.py — Streamlit 应用组装

**Files:**
- Create: `app.py`
- Modify: 无

**Interfaces:**
- Consumes: `load_all`(Task 2)、`latest_metrics`(Task 3)、`get_realtime_quotes`/`get_hist`(Task 4)、`line_chart`/`bar_chart`(Task 5)
- Produces: 可运行的 Streamlit 应用（本地 `streamlit run app.py`），验证标准为手动清单

- [ ] **Step 1: 写应用代码**

写 `D:\tool\REITsMonitor\app.py`：

- [ ] **Step 2: 语法与导入验证**

Run: `cd /d/tool/REITsMonitor && python -c "import app; print('app import ok')"`
Expected: `app import ok`（Streamlit 应用模块可正常导入）

- [ ] **Step 3: 手动运行验证（用户操作）**

Run: `cd /d/tool/REITsMonitor && streamlit run app.py`
Expected（用户确认清单）：
- [ ] 浏览器打开本地地址（默认 http://localhost:8501）
- [ ] 页面标题「REITsMonitor — 公募REITs投后分析看板」正常显示
- [ ] 侧边栏可选择 14 只基金
- [ ] 选中「平安广州广河REIT」时：KPI 卡片显示 4 项指标；通行费收入折线图、车流量柱状图有数据（模板中的示例行）
- [ ] 「行情走势」Tab：实时行情卡片显示（网络正常时）；收盘价走势图有数据
- [ ] 无报错堆栈（Terminal 无红色 Traceback）

- [ ] **Step 4: 全量回归**

Run: `cd /d/tool/REITsMonitor && python -m pytest -v`
Expected: 17 passed（5+5+4+3）

- [ ] **Step 5: 提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "feat: assemble Phase 1 Streamlit dashboard"
```

---

### Task 7: 收尾（README 已定稿，仅回归 + 最终提交）

**Files:**
- Modify: 无（`README.md` 已由项目所有者定稿为英文叙事版，**保持不变、不覆盖**）

**Interfaces:**
- Consumes: 项目全部模块
- Produces: 项目文档与最终可交付状态

- [ ] **Step 1: 确认 README 保持定稿**

`README.md` 为项目所有者已定稿的英文叙事版（定位、数据集、路线图），本 Task 不修改、不覆盖。

- [ ] **Step 2: 最终验证**

Run: `cd /d/tool/REITsMonitor && python -m pytest -v && python -c "import app"`
Expected: 17 passed + `app import ok`

- [ ] **Step 3: 最终提交**

```bash
cd /d/tool/REITsMonitor && git add -A && git commit -m "docs: add README and finalize Phase 1"
```

---

## Self-Review 记录

1. **Spec 覆盖**：模板三 Sheet（静态/月度/季度）→ Task 2；派生指标（NOI/净利润率/可供分配）→ Task 3；akshare 行情 + 容错 → Task 4；可视化 → Task 5；UI 组装 → Task 6；文档 → Task 7。全部覆盖。
2. **实现方式**：文档中的完整代码已移除（备份见 `2026-07-31-phase1-streamlit-mvp.md.bak`）；所有测试与实现由 opencode 依据本计划的 Interfaces 规范编写，TDD 流程不变。
3. **类型一致性**：`load_all` 返回 dict key 为 `static/monthly/quarterly`，Task 6 解包一致；`latest_metrics` 返回 dict 含 `period/noi_margin/net_margin/distributable_yield`，Task 6 使用一致；`line_chart(df, x_col, y_col, title, y_label)` 签名在 Task 5/6 一致。akshare 返回列名与 Task 4 测试 mock 一致（来自真实接口字段：`代码/名称/最新价/涨跌幅/成交量/成交额`、`日期/今开/最高/最低/最新价`）。
