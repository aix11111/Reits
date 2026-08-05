# REITsMonitor

**A structured operational dataset for China's public REITs, with post-investment analytics.**

> 中国公募REITs投后经营数据基础设施 + 投后分析规则引擎

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

| Coverage | 14 highway/toll-road REITs (all listed in China) |
|---|---|
| History | Full history since first listing (2021) |
| Monthly | 398 rows: toll revenue, daily traffic volume, YoY growth (2023-06 ~ 2026-06) |
| Quarterly | 168 rows: revenue, net profit, **distributable amount**, unit distributable, EBITDA, distribution rate (2021Q3 ~ 2026Q2) |
| Static | Asset, region, mileage, concession years left (verified from public disclosures) |

### 2. Post-investment analytics (the domain layer)

Analytics rules that generic market trackers cannot produce, because they require hands-on post-investment (投后管理) experience:

- **Distributable amount completion vs. prospectus forecast** — actual annual distributable amount vs. the forecast in the prospectus (disclosed in annual reports), with status flags
- **Distributable amount YoY & peer benchmark** — quarterly distributable amount growth vs. prior-year quarter, and ranking against the industry median per period
- **Traffic/revenue divergence detection** — traffic up but toll revenue flat signals anomalies (waivers, tariff changes, route diversion)
- **Monthly MoM spike detection** — abnormal month-over-month jumps in revenue or traffic
- **Concession decay risk levels** — remaining concession life bucketed into near-expiry / watch / normal
- **Peer benchmarking** — cross-fund ranking against industry averages

### 3. A clean, interactive dashboard

Streamlit web app: pick a fund → operational trend charts, KPI cards (NOI margin, net margin, annualized distributable yield), price history. Network failures degrade gracefully.

---

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data

| Layer | Source | Frequency |
|---|---|---|
| Operational data | Exchange monthly/quarterly announcements (cninfo + SSE) → `data/REITsMonitor_数据模板_v1.xlsx` | Incremental updater (`tools/reits_collector/update.py`), monthly |
| Annual completion | Annual report 3.3.3 disclosure (actual vs. forecast) → `data/annual_completion.json` | Annual |
| Market data | `akshare` (realtime + daily history) | Automatic |

The Excel template (`data/`) is the dataset's maintenance interface: fill it once, reuse forever.

## Project structure

```
app.py                  Streamlit entry point (3 tabs: operations, market, rules)
src/data_loader.py      Excel → normalized DataFrame (Chinese cols → English)
src/metrics.py          Derived metrics (NOI margin, net margin, distributable yield)
src/rules.py            Post-investment rule engine (divergence, MoM spikes, distributable YoY, benchmark, concession decay)
src/market_data.py      akshare wrapper with graceful degradation
src/charts.py           plotly chart builders
tools/reits_collector/  Announcement collectors (cninfo/SSE), PDF parsers, incremental updater
data/                   Excel data template
tests/                  pytest suite
```

## Roadmap

- [x] **Phase 1** — Highway REITs: single-fund operational dashboard + dataset foundation
- [x] **Phase 2** — Rule engine: peer benchmarking, divergence detection, distributable YoY, concession decay
- [x] **Phase 3** — Distributable amount vs. prospectus forecast (10 funds, 11 rows)
- [x] **Phase 4 (一期)** — Valuation benchmark: TTM yield ranking, NAV premium, risk flags, market snapshot
- [x] **Phase 4 (二期)** — Concession IRR (bisection solver, expiry-aware valuation)
- [x] **Phase 5** — Full market (87 funds, 8 types): quarterly financials (782 rows), annual completion/NAV (149 rows), market-wide valuation, type filter, rental ops (460 rows, 52 funds)
- [ ] **Phase 6** — Energy/consumption ops metrics (发电量/客流), IRR for energy funds

---

*REITsMonitor — infrastructure assets deserve infrastructure data.*
