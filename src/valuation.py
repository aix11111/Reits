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

import pandas as pd


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
