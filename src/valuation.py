"""估值模块：TTM 可供分配、分红收益率、NAV 溢折价与风险标记。

纯函数设计（与 src.rules 一致），不做任何文件/网络 I/O，所有数据以
参数传入。输入列名与 src.data_loader / data 目录 JSON 保持一致：
- 季度列：code / period / distributable_wan（万元）
- 市场快照：{code: {price, market_cap_wan}}
- 份额：{code: 份}
- 年报完成度列：code / completion_pct
- 净值单价列：nav_unit_price

缺失数据一律以 NaN 表达，不抛异常。
"""

import math

import pandas as pd


def backfill_nav(
    quarterly_df: pd.DataFrame, annual_nav: dict[str, dict[int, float | None]]
) -> pd.DataFrame:
    """按年报年末基金净资产（nav_wan，万元）回填季度行的 NAV 列。

    annual_nav：{code: {报告年: nav_wan}}，报告年与季度行按 code + 年份匹配：
    - 报告期 Q4 行（年末）→ 当年年报 nav_wan（报告年 == 季度年）；
    - Q1-Q3 行 → 前向填充：沿用最近可得、报告年早于季度年的年报值
      （通常即上年年报值，缺失时回退更早年份）；
    - 无任何年报数据的基金/期间 → nav_wan 置 NaN。

    以年报年末值为准重算：既有值亦被覆盖。返回副本，不改动输入。
    纯函数，不做 I/O；缺失数据以 NaN 表达。
    """
    df = quarterly_df.copy()
    for idx, row in df.iterrows():
        series = annual_nav.get(str(row.get("code")))
        if not series:
            df.at[idx, "nav_wan"] = float("nan")
            continue
        period = str(row.get("period"))
        try:
            year = int(period[:4])
            quarter = int(period[-1])
        except (ValueError, IndexError):
            df.at[idx, "nav_wan"] = float("nan")
            continue
        if quarter == 4:
            value = series.get(year)
        else:
            prior_years = [y for y in series if y < year and series[y] is not None]
            value = series[max(prior_years)] if prior_years else None
        df.at[idx, "nav_wan"] = value if value is not None else float("nan")
    return df


def concession_irr(
    price: float,
    shares: float,
    annual_distributable_wan: float,
    years_left: float,
    growth: float = 0.0,
) -> float | None:
    """计算特许经营到期前的内含收益率（IRR）。

    现金流模型：期初 t=0 支出 price×shares 买入；此后每年 t=1..years_left
    收回 annual_distributable_wan×10000×(1+growth)^t 元（万元换算为元）；
    特许经营到期价值归零，无终值。剩余年限非整数时，最后一个不满年份
    按比例 prorate（当年分派 × 剩余分数）。

    用二分法在 [−0.99, 1.0] 内解 NPV(r)=Σ CF_t/(1+r)^t=0（NPV 对 r 单调
    递减保证收敛）；精度 1e-6、最大迭代 100 次。输入非法（price/shares/
    years_left 非正数、annual<0、growth≤−1、任一为 NaN/None）或区间内无解
    → 返回 None。

    纯函数，手写二分，不依赖 scipy。
    """
    if not _valid_positive(price):
        return None
    if not _valid_positive(shares):
        return None
    if not _valid_nonnegative(annual_distributable_wan):
        return None
    if not _valid_positive(years_left):
        return None
    if not _valid_above_minus_one(growth):
        return None

    annual_yuan = annual_distributable_wan * 10000
    flows = [-price * shares]
    n_full = int(years_left)
    frac = years_left - n_full
    for t in range(1, n_full + 1):
        flows.append(annual_yuan * (1 + growth) ** t)
    if frac > 0:
        flows.append(annual_yuan * (1 + growth) ** years_left * frac)

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(flows))

    lo, hi = -0.99, 1.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None

    for _ in range(100):
        mid = (lo + hi) / 2
        if hi - lo < 1e-6:
            return mid
        f_mid = npv(mid)
        if f_mid == 0.0:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2


def _valid_positive(value) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(value) and value > 0


def _valid_nonnegative(value) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(value) and value >= 0


def _valid_above_minus_one(value) -> bool:
    return (
        isinstance(value, (int, float)) and not math.isnan(value) and value > -1
    )


def ttm_distributable(quarterly_df: pd.DataFrame) -> pd.DataFrame:
    """计算每只基金近 4 个季度的可供分配金额之和（TTM，万元）。

    按 code / period 排序后取最近 4 季：
    - 恰有 4 季 → 四者之和（窗口内含 NaN 时结果亦为 NaN）；
    - 不足 4 季 → 最新一季 × 4 年化，is_annualized=True；
    - 无有效数据 → NaN。

    返回 DataFrame，index=code，列 dist_ttm_wan / is_annualized(bool)。
    空输入返回仅含上述两列的空 DataFrame，不崩溃。
    """
    df = quarterly_df.copy()
    if df.empty:
        return pd.DataFrame(columns=["dist_ttm_wan", "is_annualized"])

    df = df.sort_values(["code", "period"])
    rows = []
    for code, sub in df.groupby("code", sort=False):
        vals = sub["distributable_wan"].tail(4)
        if len(vals) < 4:
            latest = vals.iloc[-1]
            dist = latest * 4 if pd.notna(latest) else float("nan")
            annualized = True
        else:
            dist = vals.sum(skipna=False)
            annualized = False
        rows.append([code, dist, annualized])

    result = pd.DataFrame(rows, columns=["code", "dist_ttm_wan", "is_annualized"])
    return result.set_index("code")


def distribution_yield(
    dist_df: pd.DataFrame, snapshot_latest: dict, shares: dict
) -> pd.Series:
    """计算分红收益率 = dist_ttm_wan(万元) × 10000 / (price × 份)。

    任一输入缺失（TTM 金额、快照价格、份额）或不为数值 → NaN。

    返回 Series，index 与 dist_df.index 对齐（code）。
    """
    result = pd.Series(float("nan"), index=dist_df.index, dtype=float)
    for code in dist_df.index:
        dist = dist_df.loc[code, "dist_ttm_wan"]
        info = snapshot_latest.get(code) or {}
        price = info.get("price")
        share = shares.get(code)
        if pd.isna(dist) or pd.isna(price) or pd.isna(share):
            continue
        result[code] = dist * 10000 / (price * share)
    return result


def nav_premium(price_series: pd.Series, nav_unit_series: pd.Series) -> pd.Series:
    """计算 NAV 溢折价 = price / nav_unit_price - 1。

    任一输入缺失（price 或 nav_unit_price 为 NaN）→ 对应结果 NaN。

    返回 Series，index 为两者对齐后的 code 并集。
    """
    price = pd.Series(price_series)
    nav = pd.Series(nav_unit_series)
    result = price / nav - 1
    return result.where(price.notna() & nav.notna())


def risk_flags(
    completion_df: pd.DataFrame,
    premium_series: pd.Series,
    years_left_series: pd.Series,
) -> pd.DataFrame:
    """按完成度 / NAV 溢价 / 剩余年限生成风险标记。

    - completion_pct < 80 → "completion_risk"
    - 80 <= completion_pct <= 100 → "completion_watch"
    - premium > 0.20 → "premium_risk"
    - years_left < 10 → "concession_risk"

    任一项输入缺失（NaN）则跳过该项判断；无任何标记的 code 不出现。
    全正常 / 全 NaN / 空输入均返回含 code/flags 两列的空 DataFrame，不崩溃。

    返回 DataFrame，列 code / flags(list[str])。
    """
    premium = pd.Series(premium_series)
    years_left = pd.Series(years_left_series)
    rows = []

    for row in completion_df.itertuples():
        code = row.code
        flags = []
        pct = row.completion_pct
        if pd.notna(pct):
            if pct < 80:
                flags.append("completion_risk")
            elif pct <= 100:
                flags.append("completion_watch")
        if (
            code in premium.index
            and pd.notna(premium[code])
            and premium[code] > 0.20
        ):
            flags.append("premium_risk")
        if (
            code in years_left.index
            and pd.notna(years_left[code])
            and years_left[code] < 10
        ):
            flags.append("concession_risk")
        if flags:
            rows.append([code, flags])

    return pd.DataFrame(rows, columns=["code", "flags"])


def hk_distribution_yield(dpu_hk_cents: float, price_hkd: float) -> float:
    """计算香港 REITs 年化分派收益率 = dpu(港元) / price = dpu_cents/100 / price。

    输入非法（price<=0，或任一输入为 None/NaN）→ NaN。纯函数，不做 I/O。
    """
    if not _valid_positive(price_hkd):
        return float("nan")
    if not isinstance(dpu_hk_cents, (int, float)) or math.isnan(dpu_hk_cents):
        return float("nan")
    return dpu_hk_cents / 100 / price_hkd


def hk_nav_premium(price_hkd: float, nav_per_unit: float) -> float:
    """计算香港 REITs 的 NAV 溢折价 = price / nav - 1。

    输入非法（nav<=0，或任一输入为 None/NaN）→ NaN。纯函数，不做 I/O。
    """
    if not _valid_positive(nav_per_unit):
        return float("nan")
    if not isinstance(price_hkd, (int, float)) or math.isnan(price_hkd):
        return float("nan")
    return price_hkd / nav_per_unit - 1


def us_dividend_yield(dpu_usd: float, price_usd: float) -> float:
    """计算美国 REITs 年化股息率 = dpu(美元) / 市价(美元)。

    美股 DPU 已为美元口径（非分/仙），直接相除；输入非法（price<=0，
    或任一输入为 None/NaN）→ NaN。纯函数，不做 I/O。
    """
    if not _valid_positive(price_usd):
        return float("nan")
    if not isinstance(dpu_usd, (int, float)) or math.isnan(dpu_usd):
        return float("nan")
    return dpu_usd / price_usd


def npi_margin(npi_wan: float, revenue_wan: float) -> float:
    """计算物业收入净利率（NPI margin）= npi / revenue。

    输入非法（revenue<=0，或任一输入为 None/NaN）→ NaN。纯函数，不做 I/O。
    """
    if not _valid_positive(revenue_wan):
        return float("nan")
    if not isinstance(npi_wan, (int, float)) or math.isnan(npi_wan):
        return float("nan")
    return npi_wan / revenue_wan
