# 新加坡 REITs 模块设计（SG REITs Module — CICT PoC → 15 只主流）

> 日期：2026-08-07
> 状态：grill 确认 + 侦察完成（SGX 官方 42 只清单、官网 IR 年报直链、雅虎 .SI 行情、英文国际标准披露）
> 前置：REITsMonitor 多市场（中国 87 只 + 香港 11 只，465 passed）

## 目标

REITsMonitor 市场维度扩展至**新加坡**（S-REITs）。PoC 用**单只 C38U（凯德综合商业信托，最大 S-REIT）**验证全链路（官网年报 → 解析 → 雅虎行情 → 看板接入），跑通后批量扩展 **15 只主流**（凯德系/丰树系/吉宝系/星狮系）。

## 侦察结论（2026-08-07，不得更改）

| 项 | 结论 |
|---|---|
| 清单 | SGX 官方 42 只（Chartbook 2023-02 时点；PoC 先做前 15 只主流） |
| 年报 | 各 REIT 官网 IR 直链（C38U: `https://investor.cict.com.sg/misc/ar2025.pdf`；ir 页面 `.../ar.html` 模式） |
| 披露 | **英文国际标准**：Gross Revenue / Net Property Income / Distributable Income / **DPU (¢)** / **NAV per Unit (S$)** / 出租率 / 杠杆；**五年财务摘要表**（2021-2025 每行一指标，行标签+5 年数字序列） |
| 财年 | 12 月 31 日（自然年） |
| 行情 | **雅虎 finance**：`https://query1.finance.yahoo.com/v8/finance/chart/{CODE}.SI`（实测 C38U.SI=2.46 SGD；akshare 无新加坡） |
| 币种 | SGD 为主（部分美元/人民币计价——解析器标注 currency） |
| 中期 | S-REITs 有半年业绩公告（financial results announcement，非完整年报）——一期不做，后续 |

## CICT FY2025 基准（侦察实测）

- Gross Revenue S$1,619.2m（161,920 万 SGD）、NPI S$1,189.7m（118,970 万）
- Distributable Income S$860.9m、**DPU 11.58¢**、**NAV/Unit S$2.14**
- 出租率 96.9%、杠杆 38.6%、债务成本 3.2%
- 行情 2.46 SGD（2026-08-06）→ 分派收益率 ≈ 11.58¢/246¢ ≈ **4.71%**、P/NAV ≈ 2.46/2.14 − 1 ≈ **+15.0%（溢价——与香港折价常态相反，验证 S-REIT 溢价交易特征）**

## 数据文件（不动模板 Excel）

- `data/sg_funds.json`：`{"funds": [{"code": "C38U", "name": "CapitaLand Integrated Commercial Trust", "name_zh": "凯德综合商业信托", "market": "SG", "annual_url": "...", "currency": "SGD"}]}`（15 只）
- `data/sg_annual.json`：`{"annual": [{"code", "fiscal_year": "2025", "period": "annual", "revenue_wan", "npi_wan", "distributable_wan", "dpu_cents", "nav_per_unit", "occupancy", "currency": "SGD"}]}`
- `data/sg_market_snapshot.json`：雅虎快照（`{"snapshots": [...], "latest": {code: price}}`）

## 指标（复用 HK 纯函数模式）

- 分派收益率 = dpu_cents/100 ÷ price（**SGD 同币种直接算**；美元计价 REIT 需汇率——一期标注 currency 不做换算，收益率同币种可算）
- P/NAV 折溢价 = price/nav − 1（同币种）
- NPI 利润率 = npi/revenue
- → 复用 `hk_distribution_yield`/`hk_nav_premium`/`npi_margin`（通用重命名或包装）

## 任务分解

1. **下载器**：`tools/reits_collector/sg_annual.py`——`download_sg_annual(url, dest)`（复用 hkex.py 模式：UA+流式）；sg_funds.json 15 只清单（含 annual_url）
2. **解析器**：`tools/reits_collector/parser_sg_annual.py`——`parse_sg_annual(pdf_path) -> dict`：
   - 英文标签：Gross Revenue / Net Property Income / Distributable Income / Distribution Per Unit (¢) / Net Asset Value Per Unit (S$)
   - **五年摘要表优先**（行标签 + 数字序列取最新列）；叙述式（"DPU rose 6.4% YoY to 11.58 cents"）兜底
   - 财年：FY ended 31 December 2025 → "2025"
   - 容错：缺失 None；S$m/S$b 单位换算（m→万×100、b→万×100000）
   - TDD：真实年报文本 fixture（`tests/fixtures/sg_cict_ar2025.txt`，从 PDF 提取 Financial Highlights + 五年表）
3. **行情**：`tools/reits_collector/sg_market.py`——`fetch_sg_prices(codes)`（雅虎 chart API，5s 超时）+ `update_sg_snapshot`（复用 hk_market 快照模式）
4. **看板**：市场维度 `中国/香港/新加坡`——SG 模式：基金选择器=sg_funds；经营 Tab=英文指标卡（FY/Revenue/NPI/DPU/NAV/出租率+币种标注）+ 数据表；估值 Tab=分派收益率排名+P/NAV（复用 HK 排名渲染，通用化 `render_market_valuation`）；中国/香港**零变化**
5. **15 只批量**：年报逐只下载（官网 IR 侦察 URL）→ 解析（格式变体预期：凯德系/丰树系/吉宝系模板 3-5 种）→ 行情 15 只 → 入库
6. **README**：多市场列表 + SG 层

## 降级

- 雅虎失败 → 快照保留旧值；无快照 → st.info
- 年报解析字段缺失 → 「—」（同 HK 模式）
- 美元计价 REIT（如 Prime US REIT）→ currency 标注，收益率同币种计算

## 测试策略

- `test_parser_sg_annual.py`：CICT fixture 精确断言（revenue=161920.0/npi=118970.0/dpu=11.58/nav=2.14/fy=2025）；断行/单位变体；缺失 None
- `test_sg_market.py`：mock 雅虎响应 → 价格提取；失败 errors
- `test_app.py`：市场=新加坡 → SG 基金选择器 + 指标渲染；中国/香港不回归
- 全量 pytest 不回归（465 基线）
