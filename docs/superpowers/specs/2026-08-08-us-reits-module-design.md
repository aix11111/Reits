# 美国 REITs 模块设计（US REITs Module — SEC EDGAR 10-K + FFO 估值）

> 日期：2026-08-08
> 状态：侦察完成（EDGAR 统一 API、10-K HTML 直链、FFO 披露、雅虎美股行情）
> 前置：REITsMonitor 三市场（中国 87 + 香港 11 + 新加坡 38，499 passed）

## 目标

REITsMonitor 扩展**美国市场**：SEC EDGAR 10-K 解析 + 美股行情 + **FFO/AFFO 估值**（方法论定案：FFO 系留给美国）。

## 侦察结论（实测）

1. **数据源 = SEC EDGAR**（统一！）：
   - `https://www.sec.gov/files/company_tickers.json`（ticker→CIK 映射）
   - `https://data.sec.gov/submissions/CIK{10位}.json`（提交历史，10-K 最新年份）
   - 10-K 主文档 = **HTML 直链**（`/Archives/edgar/data/{cik}/{accession}/{doc}.htm`——PLD 11.5MB 实测；**比 PDF 好解析**（无 fitz，正则直接处理）；限速 10 req/s
2. **披露结构**：Total revenues / Rental revenues / NOI（净营业收入——对应 NPI）/ **FFO 明确提及**（10-K 非 GAAP 段）；股息 = 10-K Item 5「dividends declared per share」；**美股不披露 NAV**（估值用 P/FFO + 股息率）
3. **行情**：雅虎 chart API（**美股无后缀 ticker**：PLD/O/SPG 实测 140.16/62.51/222.91 USD）——复用 sg_market 模式（去 .SI 后缀）
4. **中期**：10-Q（季度报告）——美国为季度体系（本次范围：仅 10-K 年报）
5. **币种**：USD

## 范围（PoC → 扩展）

- **首批 20 只主流**（Vanguard REIT ETF 前十大 + 知名大盘）：
  PLD/WELL/EQIX/AMT/O/CCI/SPG/PSA/DLR/VICI/AVB/ARE/EXR/SUI/EQR/MAA/ESS/UDR/REG/GLPI
  （PoC 验证全链路 → 后续可扩至 Nareit 100）

## 数据模型

- `data/us_funds.json`：{code: ticker, name, market: "US", cik, currency: "USD"}
- `data/us_annual.json`：{annual: [{ticker, fiscal_year, period, revenue_wan, noi_wan, ffo_wan, affo_wan(可选), dpu_usd, occupancy, currency}]}
  - **revenue_wan/noi_wan 单位 = 万美元**（USD；10-K 报表单位通常 $000 → ×0.1）
  - **ffo_wan**：FFO（NAREIT 定义）——美股核心估值指标
  - **dpu_usd**：每股股息（10-K Item 5，非 cents——美股习惯每股美元）
- `data/us_market_snapshot.json`：{latest: {ticker: price}}（雅虎）
- 估值视图：**股息率**（dpu/price）+ **P/FFO**（price/(ffo per unit)——ffo_wan ÷ 股数？——**简化**：10-K 若有每股 FFO 用每股；否则 P/FFO 暂缺——**PoC 以股息率为主**，P/FFO 尽力）

## 看板

- 市场 selectbox 增「美国」（中国/香港/新加坡/美国，默认中国零变化）
- 美国视图：经营 KPI（FY/Revenue/NOI/FFO/每股股息/出租率）+ 估值排名（股息率 + P/FFO 若有）
- 数据缺失降级：us_*.json 缺失 → st.info「美国数据缺失」

## 任务分解（TDD）

1. Task 1：EDGAR 下载器（ticker→CIK→10-K HTML 下载；10 req/s 限速；us_funds.json 20 只）
2. Task 2：10-K 解析器（HTML 正则：fiscal_year/Revenue/NOI/FFO/dividends per share/occupancy；HTML 标签剥离；表格行标签提取）
3. Task 3：美股行情（雅虎无后缀 ticker）+ 快照
4. Task 4：估值纯函数（dividend_yield、p_ffo）+ 看板市场维度 + 排名视图
5. Task 5：20 只批量下载+解析+入库+测试
