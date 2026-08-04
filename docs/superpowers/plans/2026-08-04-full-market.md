# 全市场扩展实施计划（Phase 5）

> **For agentic workers:** 任务按序执行；每个任务独立 TDD 红绿循环 + commit。代码实现由 opencode 完成，本计划只定接口规范与测试意图。
> 日期：2026-08-04 | 前置 Spec：`docs/superpowers/specs/2026-08-04-full-market-design.md` | 基线 261 passed

**Goal:** 全市场 86+ 只 REITs 的季度核心财务数据层 + 估值对标覆盖 + 看板全市场视图。

**Architecture:** 独立 JSON 数据层（模板不动）→ 复用 src/valuation.py 估值函数 → 看板类型筛选视图。沪市限流沿用 15s/90s 模式。

**Tech Stack:** 现有（Python/pandas/plotly/streamlit/akshare/pymupdf）+ 交易所公告接口（sse/cninfo 复用）。

## Global Constraints

- 模板 Excel 结构严格不变；新数据全部独立 JSON（data/market_*.json）
- 清单/数据必须有来源（接口/公告/web 交叉核验），**禁止编造**；无法确认的基金不入库
- 代码由 opencode 写（TDD）；助手复跑 pytest 后 commit（feat:/data:/test:/docs:）
- 沪市接口限流：15s 基金间隔 + 90s×3 重试
- 全量 pytest 基线 261 不回归；纯函数禁 I/O

---

### Task 1（M1）: 全市场清单 market_funds.json

**Files:**
- Create: `data/market_funds.json`、`tools/reits_collector/market_funds.py`（可选——若清单获取需代码）
- Test: `tests/test_market_funds.py`（若建模块）

**Interfaces:**
- `data/market_funds.json`：`{"funds": [{"code": "508000", "name": "华安张江产业园REIT", "asset_type": "产业园", "listed_date": "2021-06-21", "manager": "华安基金", "exchange": "SSE"}]}`（86+ 只）
- `asset_type` 枚举：高速/产业园/仓储物流/能源/生态环保/保障房/消费/商业不动产

**获取路径（按序尝试）：**
1. 上交所 REITs 板块列表接口（commonSoaQuery.do 探测 REITs 基金列表 sqlId——curl 测试；参考现有 sqlId=REITS_BULLETIN 模式）
2. 深交所 cninfo 基金列表（orgId 搜索模式）
3. akshare 备用（`ak.reits_realtime_em` 曾被拒——重试或换接口）
4. 上述全失败 → 从 web 抓取清单（curl 东财 fundmobapi 或静态页），双源交叉核验

**测试意图：**
- 清单 JSON schema 校验（必填字段、code 唯一、asset_type 枚举合法）
- 若建 market_funds.py：加载函数返回 DataFrame；文件缺失 → 空
- 数量断言：>= 80 只（2026-08 全市场 86-93 只）

**完成后**：手动核验 5 只抽样（名称/类型与公开信息一致）→ commit `data: full-market fund list (N funds, 8 types)`。

---

### Task 2（M2）: 全市场季度核心财务

**Files:**
- Modify: `tools/reits_collector/parser_quarterly.py`、`tools/reits_collector/update.py`
- Create: `data/market_quarterly.json`
- Test: `tests/test_parser_quarterly.py`、`tests/test_update.py`

**Interfaces:**
- parser_quarterly 扩展：可供分配表标题匹配放宽（「本报告期的可供分配金额」/「本报告期及近三年的可供分配金额」）；收入字段别名（「本期收入」vs「营业总收入」）——保持现有 14 只高速解析不回归
- 新函数 `fetch_market_quarterly(market_funds: list, errors: list | None = None) -> list[dict]`：
  - 逐基金拉季度报告公告（起 2021-01-01）→ PDF 缓存 `data/_cache/quarterly_market/`（复用跳过）→ parser_quarterly 解析 → 行 dict `{code, period, revenue_wan, net_profit_wan, distributable_wan, unit_distributable, ebitda_wan}`（None 缺失如实留空）
  - 沪市 15s 间隔 + 列表失败 90s×3 重试；深市 cninfo 自适应翻页
  - 已存在 (code, period) 跳过（读 market_quarterly.json 现有行）
  - 汇总写回 `data/market_quarterly.json`：`{"quarters": [...]}`
- fixture：`tests/fixtures/quarterly_508000_2026Q2.txt`（产业园真实段落：3.1 主要财务指标 + 本报告期的可供分配金额 23,695,441.92/0.0247）——源 PDF 在 `%TEMP%/reits_market_probe/508000_2026Q2.pdf`（拷入 data/_cache 供 opencode）

**测试意图：**
- 产业园 fixture → revenue_wan=3065.07（30,650,710.62→万）、net_profit_wan=-1164.45、distributable_wan=2369.54、unit_distributable=0.0247
- 标题变体（本报告期的/本报告期及近三年）都匹配
- fetch_market_quarterly：mock 接口——已存在跳过/新追加/单基金失败 errors/限流重试
- 现有高速 quarterly 测试不回归

**完成后**：批量采集全市场（后台，预计 1-2 小时限速）→ ~500 行 → commit `feat: full-market quarterly fetch + parser title variants`。

---

### Task 3（M3）: 市值快照 + 年报净值/完成度全市场

**Files:**
- Modify: `tools/reits_collector/update.py`、`tools/reits_collector/parser_annual.py`
- Create: `data/market_shares.json`、`data/market_completion.json`
- Test: `tests/test_update.py`、`tests/test_parser_annual.py`

**Interfaces:**
- `fetch_market_shares(market_funds, errors) -> dict`：各基金最新季报「报告期末基金份额总额」（复用 parser_quarterly 份额提取——Task 2 解析时顺带）；`market_shares.json` `{"shares": {"508000": ...}}`
- update.fetch_market_snapshot 扩展：接受全市场份额（现有签名兼容——shares dict 传入即可，验证代码不假设 14 只）
- parser_annual 全市场复用（3.2 净值 + 3.3.3 完成度——现有逻辑与代码无关，只需 fixture 验证非高速年报同构）；`market_completion.json` `{"completion": [...]}`（同 annual_completion 结构）

**测试意图：**
- fetch_market_shares：mock 季报解析——部分失败 errors/写回结构
- fetch_market_snapshot：全市场 shares 输入（>14 只）正常工作
- parser_annual 非高速 fixture（产业园年报 3.2/3.3.3 段落）→ nav_unit_price/completion 解析
- 现有测试不回归

**完成后**：采集全市场年报/份额 → commit `feat: full-market shares + annual completion/nav`。

---

### Task 4（M4）: 看板全市场视图

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- 数据加载：`load_market_funds()/load_market_quarterly()/load_market_completion()/load_market_shares()`（data_loader 或 app.py 内部；JSON 缺失返回空）
- app.py 顶部新增「资产类型」多选（侧边栏或顶部 selectbox：全部/高速/产业园/…，默认全部）
- 估值对标 Tab 全市场化：render_valuation 接受全市场数据——排名含类型着色（每类型一色，8 色系保持深色终端可读）、IRR 列对产权类标「不适用（产权类）」、折溢价表全市场
- 单基金详情（经营数据 Tab）：通用 KPI 不变（收入/净利/可供分配）+ 类型特有区块占位（M5 填充）
- 降级：market JSON 缺失 → 现有 14 只高速视图照常（全市场层缺失不破坏现有）

**测试意图：**
- AppTest：类型筛选「全部」→ 排名表含全市场基金；筛选「产业园」→ 仅产业园；产权类 IRR 列「不适用」
- market 数据缺失 → 现有 3+1 Tab 不回归
- 现有全部 AppTest 不回归

**完成后**：本地截图验证全市场视图 → commit `feat: full-market dashboard view (type filter, market-wide ranking)`。

---

### Task 5（M5，可选）: 产业园/保租房出租率指标

**Files:**
- Create: `tools/reits_collector/parser_ops_rental.py`、`data/market_ops_rental.json`
- Test: `tests/test_parser_ops_rental.py`

**Interfaces:**
- `parse_rental_ops(pdf_path) -> dict | None`：4.1.3 节——期末出租率/平均租金单价（元/平/天）/期末租金收缴率/期末剩余租期；`{code, period, occupancy_pct, avg_rent_yuan, collection_pct, remaining_lease_days}`
- fixture：508000 2026Q2 段落（出租率 88.12%/租金 5.44/收缴率 100.00/租期 554）
- 看板：经营数据 Tab 出租率 KPI + 趋势图（有数据基金）

**完成后**：commit `feat: rental ops parser (occupancy, rent, collection)`。

---

## 执行顺序与依赖

```
Task 1（清单）→ Task 2（季度）→ Task 3（份额+年报）→ Task 4（看板）→ Task 5（可选）
```
Task 1-4 核心（M1-M4），Task 5 可选（M5）。每任务独立可测可提交；opencode 逐任务 TDD。批量采集（Task 2/3 的实网跑）后台执行。
