# 香港 REITs 模块设计（HK REITs Module — Link REIT PoC）

> 日期：2026-08-07
> 状态：grill 定案 + 侦察确认（2026-08-07 侦察：HKEX 直链可下载、新浪港股行情可用、领展披露 DPU/NAV/无 FFO）
> 前置：REITsMonitor 现有中国模块（87 只/8 类/4 Tab/深色终端 UI）

## 目标

REITsMonitor 升级为**多市场**：新增香港 REITs 模块。PoC 阶段用**单只领展（823.HK）**验证全链路（HKEX 年报抓取 → 国际指标 → 看板「市场」筛选接入），跑通后扩展 11 只港 REITs。

## 定案（grill + 侦察，不得随意更改）

| 决策点 | 定案 |
|---|---|
| 定位 | REITsMonitor = 多市场 REITs 投后分析（README/看板标题同步升级） |
| 方法框架（HK） | **国际通用（香港版）**：分派收益率 = DPU ÷ 市价、P/NAV 折溢价 = 市价 ÷ NAV/单位 − 1、NPI 利润率、DPU 同比、出租率；**FFO/AFFO 系留待美国市场**（领展不披露，侦察确认） |
| 数据源 | HKEX 年报直链 `https://www.hkexnews.hk/listedco/listconews/sehk/{yyyymmdd}/{id}.pdf`（无需爬搜索接口）；行情用**新浪港股**（akshare `stock_hk_daily`，东财被拒） |
| 财年 | HK 财年 4 月-3 月（FY24/25 = 2024-04-01~2025-03-31）——指标带财年标签，不与日历年混用 |
| 数据文件 | `data/hk_funds.json`（基金清单+代码）、`data/hk_annual.json`（年报指标：财年/revenue_wan/npi_wan/dpu_hk_cents/nav_per_unit/occupancy）——不动模板 Excel（结构铁律） |
| 看板架构 | 侧边栏**「市场」筛选**（中国/香港，默认中国=现状零变化）→ 基金列表与全部 Tab 切换；香港视图：经营数据 Tab（NPI/DPU/出租率+趋势）+ 估值对标 Tab（分派收益率/P-NAV 折溢价，单只先行） |
| 行情 | 新浪港股日线 → `data/hk_market_snapshot.json`（复用中国快照模式，update 管线扩展） |

## 领展 PoC 侦察基准（2026-08-07 实测）

- 年报：HKEX 直链 483 页 38MB 已下载（`data/_cache/hk/linkreit_ar2425.pdf`，gitignore）
- FY2024/25 关键值：Revenue HK$14,223M、NPI HK$10,619M、DPU 272.34 港仙、NAV/Unit HK$63.30、出租率 97.8%（HK Retail）
- 行情：新浪 00823 最新收 38.78（5091 天历史）
- 派生：分派收益率 ≈ 272.34¢/38.78 ≈ 7.0%；P/NAV ≈ 38.78/63.30 − 1 ≈ −38.7%（折价）

## 任务分解（一期 PoC）

1. **HKEX 年报下载器** `tools/reits_collector/hkex.py`：`download_annual_report(stock_code, url, dest)`——直链下载+UA；基金-年报 URL 清单从 `hk_funds.json` 读（PoC 阶段领展 1 条）
2. **年报解析器** `tools/reits_collector/parser_hk_annual.py`：`parse_hk_annual(pdf_path) -> dict`——提取财年（「for the year ended 31 March 2025」）、Revenue、NPI（Net Property Income）、DPU（cents）、NAV per Unit（HK$）、出租率（按地区）；TDD + 真实年报文本 fixture（`data/_cache/hk/` 提取段落）
3. **行情快照**：update.py 或独立 `tools/reits_collector/hk_market.py`——新浪 `stock_hk_daily` 最新收盘 → `data/hk_market_snapshot.json`
4. **指标计算** `src/valuation.py` 或 `src/valuation_hk.py`：`hk_distribution_yield(dpu_cents, price)`、`hk_nav_premium(price, nav_per_unit)`、NPI 利润率——纯函数 TDD
5. **看板接入**：侧边栏「市场」selectbox（中国/香港，默认中国）；香港模式：基金选择器=hk_funds 清单、经营数据 Tab=HK 指标卡+趋势图（NPI/DPU/出租率）、估值对标 Tab=分派收益率/折溢价；中国模式**零变化**（硬约束，同联动 spec）
6. **README/标题**：副标题升级「多市场 REITs」；看板标题 REITsMonitor — 多市场 REITs 投后分析

## 降级与数据缺失

- HKEX 下载失败 → errors 记录（复用限流/重试模式）
- 新浪行情失败 → 快照保留上次值；无快照 → HK 估值 Tab「行情数据缺失」st.info
- 出租率按地区字段缺失 → 「—」列
- 中国模式（默认）完全不受 HK 模块影响（数据/渲染路径不变）

## 测试策略

- `test_parser_hk_annual.py`：真实年报文本 fixture——财年/Revenue/NPI/DPU/NAV/出租率精确断言；断行/单位变体容错
- `test_valuation` HK 函数：收益率/折溢价正负/缺失
- `test_app.py`：市场切换 AppTest（选香港 → 基金选择器=HK 清单、经营 Tab 渲染 HK 指标；选中国 → 现状 87 只联动不回归）
- 全量 pytest 不回归（413 基线）
