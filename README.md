# REITsMonitor

**A structured operational dataset for public REITs across markets, with post-investment analytics.**

> 多市场REITs投后经营数据基础设施 + 投后分析规则引擎（中国公募REITs + 香港 REITs）

---

## Why this exists

China's public REITs (公募REITs) market launched in 2021 and now spans 70+ funds. Yet there is **no free, structured dataset of their operational data**.

- Market data (price, volume) is freely available via libraries like `akshare` — that's the easy part.
- **Operational data** — toll revenue, traffic volume, distributable amount, NOI, NAV — is scattered across hundreds of PDF announcements on exchange websites, in inconsistent formats, with no API.

Wind and Choice have this data — behind expensive paywalls. This project opens up that data layer.

This is not another price-charting dashboard. The dataset is the product; the app is its interface.

---

## What it provides

### 1. A curated operational dataset (the core asset)

Structured, standardized, free — collected automatically from exchange PDF announcements (cninfo for Shenzhen-listed, SSE for Shanghai-listed) and parsed into a normalized schema:

| Coverage | **87 funds · 8 asset types** (highway, industrial park, warehouse, residential rental, energy, consumer, eco-environment, commercial) — China market |
| Monthly operations | 398 rows — toll revenue, daily traffic volume, YoY growth (highway funds, 2023-06 ~ 2026-06) |
| Quarterly financials | 782 rows — revenue, net profit, **distributable amount**, EBITDA, NAV (2021Q3 ~ 2026Q2) |
| Annual completion & NAV | 149 rows — actual vs. prospectus-forecast distributable amount, year-end net asset value |
| Rental ops | 460 rows — occupancy rate, rent levels (52 funds) |
| Energy ops | generation, utilization hours, settlement price |
| Static | Asset, region, mileage, concession years left (verified from public disclosures) |
| **Hong Kong (PoC)** | **Link REIT (823.HK)** — annual report parsed (Revenue/NPI/DPU/NAV per unit/occupancy), Sina daily price snapshot, DPU yield & P/NAV valuation |

### 2. Post-investment analytics (the domain layer)

Analytics rules that generic market trackers cannot produce, because they require hands-on post-investment (投后管理) experience:

- **Distributable amount completion vs. prospectus forecast** — actual annual distributable amount vs. the forecast in the prospectus (disclosed in annual reports), with status flags
- **Valuation benchmark** — TTM distributable yield ranking (rolling 4-quarter actual ÷ market cap), NAV premium/discount vs. year-end NAV, aggregated risk flags
- **Concession IRR** — buy at market price, hold to concession expiry (asset value → 0), solve for IRR — a valuation unique to China's concession-based REITs
- **HK valuation (PoC)** — DPU yield, P/NAV premium/discount, NPI margin for Hong Kong REITs (international-style metrics, market dimension in the dashboard)
- **Distributable amount YoY & peer benchmark** — quarterly growth vs. prior-year quarter, ranked against the industry median
- **Traffic/revenue divergence detection** — traffic up but toll revenue flat signals anomalies (waivers, tariff changes, route diversion)
- **Monthly MoM spike detection** — abnormal month-over-month jumps in revenue or traffic
- **Concession decay risk levels** — remaining concession life bucketed into near-expiry / watch / normal

### 3. A dark-terminal dashboard

A Bloomberg-meets-Apple Streamlit app: market-wide **status wall** (fund health dots), asset-type linked fund navigation across all 87 funds, KPI cards, operational trends, valuation tables — all in a dark financial-terminal theme with a teal accent. Network failures degrade gracefully.

---

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501`.

## Data

| Layer | Source | Frequency |
|---|---|---|
| Operational data (CN) | Exchange monthly/quarterly announcements (cninfo + SSE) → `data/REITsMonitor_数据模板_v1.xlsx` + `data/market_*.json` | Incremental updater (`tools/reits_collector/update.py`), monthly |
| Annual completion & NAV | Annual report disclosures (actual vs. forecast) → `data/annual_completion.json` | Annual |
| Market data (CN) | `akshare` (realtime + daily history) → `data/market_snapshot.json` | Monthly snapshot |
| HK annual financials | HKEX annual report PDF → `data/hk_annual.json` | Annual |
| HK market data | Sina HK daily (akshare `stock_hk_daily`) → `data/hk_market_snapshot.json` | Manual/PoC |

The Excel template (`data/`) is the dataset's maintenance interface: fill it once, reuse forever.

## Project structure

```
app.py                  Streamlit entry point (4 tabs: operations, market, rules, valuation; market dimension CN/HK)
src/data_loader.py      Excel/JSON → normalized DataFrame (Chinese cols → English)
src/metrics.py          Derived metrics (NOI margin, net margin, distributable yield)
src/rules.py            Post-investment rule engine (divergence, MoM spikes, distributable YoY, benchmark, concession decay)
src/valuation.py        Valuation module (TTM yield, NAV premium, concession IRR, risk flags, HK DPU yield/P-NAV)
src/market_data.py      akshare wrapper with graceful degradation
src/charts.py           plotly chart builders (dark theme)
tools/reits_collector/  Announcement collectors (cninfo/SSE/HKEX), PDF parsers, incremental updater
data/                   Excel data template + market JSON datasets (CN + HK)
tests/                  pytest suite (450+ tests)
```

## Tech stack

- **Streamlit + Plotly** — interactive dashboard, dark theme
- **pandas / openpyxl** — data normalization and template maintenance
- **PyMuPDF** — PDF announcement parsing (format-tolerant, coordinate-based)
- **akshare** — market data with graceful degradation
- **pytest** — TDD, 413 tests

---

*REITsMonitor — infrastructure assets deserve infrastructure data.*
