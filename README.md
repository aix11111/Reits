# REITsMonitor

**China's first open, structured operational dataset for public REITs — plus the post-investment analytics that only an industry insider can write.**

> 中国公募REITs投后经营数据基础设施 + 投后分析规则引擎

---

## Why this exists

China's public REITs (公募REITs) market launched in 2021 and now spans 70+ funds. Yet there is **no free, structured dataset of their operational data**.

- Market data (price, volume) is freely available via libraries like `akshare` — that's the easy part.
- **Operational data** — toll revenue, traffic volume, distributable amount, NOI, NAV — is scattered across hundreds of PDF announcements on exchange websites, in inconsistent formats, with no API.

Wind and Choice have this data — behind expensive paywalls. **No one maintains it in the open.** That's the gap this project fills.

This is not another price-charting dashboard. The dataset is the product; the app is its interface.

---

## What it provides

### 1. A curated operational dataset (the core asset)

Structured, standardized, free — maintained manually from exchange disclosures:

| Coverage | 14 highway/toll-road REITs (all listed in China) |
|---|---|
| History | Full history since first listing (2021) |
| Monthly | Toll revenue, daily traffic volume, YoY growth |
| Quarterly | Revenue, cost, net profit, **distributable amount**, EBITDA, NAV |
| Static | Asset, region, mileage, concession life remaining |

### 2. Post-investment analytics (the domain layer)

Analytics rules that generic market trackers cannot produce, because they require hands-on post-investment (投后管理) experience:

- **Distributable amount completion vs. prospectus forecast** — the core post-investment KPI for Chinese REITs (the FFO equivalent)
- **Traffic/revenue divergence detection** — traffic up but toll revenue flat signals anomalies (waivers, tariff changes, route diversion)
- **Concession decay curve** — how shrinking remaining concession life pressures valuation
- **Peer benchmarking** (Phase 2) — ranking across all highway REITs against industry averages

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
| Operational data | Exchange monthly/quarterly announcements → `data/REITsMonitor_数据模板_v1.xlsx` | Manual, monthly |
| Market data | `akshare` (realtime + daily history) | Automatic |

The Excel template (`data/`) is the dataset's maintenance interface: fill it once, reuse forever.

## Project structure

```
app.py                  Streamlit entry point
src/data_loader.py      Excel → normalized DataFrame (Chinese cols → English)
src/metrics.py          Derived metrics (NOI margin, net margin, distributable yield)
src/market_data.py      akshare wrapper with graceful degradation
src/charts.py           plotly chart builders
data/                   Excel data template
tests/                  pytest suite
```

## Roadmap

- [x] **Phase 1** — Highway REITs: single-fund operational dashboard + dataset foundation
- [ ] **Phase 2** — Peer benchmarking: cross-fund ranking, industry averages
- [ ] **Phase 3** — Full market (70+ funds) + NAV premium/discount, FFO-yield ranking, user-uploaded asset comparison

## Why this matters

- **For analysts / post-investment teams** — free, structured operational data that previously required Wind/Choice licenses or hours of PDF digging
- **For researchers** — the first open dataset of China REIT operational performance
- **Built by someone who did the job** — the metrics and rules come from real post-investment work at a state-owned fund, not from a textbook

---

*REITsMonitor — infrastructure assets deserve infrastructure data.*
