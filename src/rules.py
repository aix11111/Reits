"""投后分析规则引擎。

基于月度/季度/静态数据 DataFrame 实现投后管理分析规则：
- 规则 1：流量/收入背离检测 detect_divergence
- 规则 2：同类基金月度同比对标 peer_compare
- 规则 3：可供分配金额同比增速 distributable_yoy
- 规则 4：可供分配金额同行对标 distribution_rate_benchmark
- 规则 5：特许经营权衰减 concession_decay

月度输入列名与 src.data_loader.load_monthly、季度输入列名与
load_quarterly、静态输入列名与 load_static 的输出保持一致。
注意：月度数据无环比列，环比异动检测由 detect_mom_spikes 自行计算。
"""

import pandas as pd


def detect_divergence(df: pd.DataFrame, threshold: float = 5.0) -> pd.DataFrame:
    """检测每行的收入同比与车流量同比背离。

    背离度 divergence_pct = toll_revenue_yoy - traffic_yoy（百分点）。
    |divergence_pct| >= threshold 的行标记为背离：
    - diff > 0 → direction="revenue_above"：收入增速显著高于流量增速，提示单车收入提升/费率因素；
    - diff < 0 → direction="traffic_above"：流量增速显著高于收入增速。

    返回 DataFrame：原列 + divergence(bool) + divergence_pct(float) + direction(str)，
    按 |divergence_pct| 降序排列。
    """
    result = df.copy()
    result["divergence_pct"] = result["toll_revenue_yoy"] - result["traffic_yoy"]
    result["divergence"] = result["divergence_pct"].abs() >= threshold
    result["direction"] = result["divergence_pct"].map(
        lambda diff: "revenue_above" if diff > 0 else "traffic_above"
    )
    return result.sort_values("divergence_pct", key=abs, ascending=False)


def peer_compare(df: pd.DataFrame) -> pd.DataFrame:
    """按报告期分组，与同类基金同比增速中位数对比。

    每组至少 3 只基金（按 code 去重计数）才计算车流量同比与收入同比中位数；
    不足 3 只时 median_* 与 below_peer_* 均为 NaN，不做对标标记。

    返回 DataFrame：原列 + median_traffic_yoy + median_revenue_yoy
    + below_peer_traffic(bool) + below_peer_revenue(bool)。
    """
    result = df.copy()
    if result.empty:
        return result

    group_counts = result.groupby("period")["code"].transform("nunique")
    median_traffic = result.groupby("period")["traffic_yoy"].transform("median")
    median_revenue = result.groupby("period")["toll_revenue_yoy"].transform("median")

    result["median_traffic_yoy"] = median_traffic.where(group_counts >= 3)
    result["median_revenue_yoy"] = median_revenue.where(group_counts >= 3)
    result["below_peer_traffic"] = (
        result["traffic_yoy"] < result["median_traffic_yoy"]
    ).where(group_counts >= 3)
    result["below_peer_revenue"] = (
        result["toll_revenue_yoy"] < result["median_revenue_yoy"]
    ).where(group_counts >= 3)
    return result


def distributable_yoy(quarterly_df: pd.DataFrame, threshold: float = 20.0) -> pd.DataFrame:
    """计算可供分配金额同比增速。

    同基金、同季度序号（period 的 QN 相同）对比上年同期
    （YYYYQN → (YYYY-1)QN）：yoy = (本期 / 上年同期 - 1) * 100。
    上年同期缺失或任一方为 None → 该行 distributable_yoy 为 None，不做标记。

    返回 DataFrame：原列 + distributable_yoy(float) + decline_flag(bool，
    yoy < -threshold) + growth_flag(bool，yoy > +threshold)，按 yoy 降序排序。
    """
    result = quarterly_df.copy()
    if result.empty:
        return result

    period = result["period"].astype(str)
    result["_prior_period"] = (period.str[:4].astype(int) - 1).astype(str) + period.str[4:]

    prior = result[["code", "period", "distributable_wan"]].rename(
        columns={
            "period": "_prior_period",
            "distributable_wan": "_prior_distributable_wan",
        }
    )
    result = result.merge(prior, on=["code", "_prior_period"], how="left")

    current = result["distributable_wan"]
    prior_val = result["_prior_distributable_wan"]
    yoy = (current / prior_val - 1) * 100
    yoy = yoy.where(current.notna() & prior_val.notna())

    result["distributable_yoy"] = yoy
    result["decline_flag"] = (yoy < -threshold).fillna(False)
    result["growth_flag"] = (yoy > threshold).fillna(False)
    return result.drop(columns=["_prior_period", "_prior_distributable_wan"]).sort_values(
        "distributable_yoy", ascending=False, na_position="last"
    )


def detect_mom_spikes(monthly_df: pd.DataFrame, threshold: float = 30.0) -> pd.DataFrame:
    """月度环比异动检测。

    模板月度数据无环比列，需自行计算：同基金按 period 排序（YYYY-MM 字符串
    天然有序），toll_revenue_wan 与 daily_traffic 的环比 =
    (本月 / 上月 - 1) * 100。上月缺失（前一条记录非相邻月份）或任一方为
    None → 该行对应的 mom 为 None，不做标记。

    |mom| > threshold 的行标记异动：revenue_spike / traffic_spike。
    方向由 mom 本身的正负表达（正值上涨、负值下跌）。

    返回 DataFrame：原列 + revenue_mom(float) + traffic_mom(float)
    + revenue_spike(bool) + traffic_spike(bool)，按 max(|revenue_mom|,
    |traffic_mom|) 降序排序（NaN 置尾）。
    """
    result = monthly_df.copy()
    if result.empty:
        return result

    result["_period_dt"] = pd.to_datetime(result["period"], format="%Y-%m")
    result = result.sort_values(["code", "_period_dt"])

    prior_dt = result.groupby("code")["_period_dt"].shift(1)
    adjacent = prior_dt.notna() & (result["_period_dt"] == prior_dt + pd.DateOffset(months=1))
    prior_rev = result.groupby("code")["toll_revenue_wan"].shift(1)
    prior_traffic = result.groupby("code")["daily_traffic"].shift(1)

    cur_rev = result["toll_revenue_wan"]
    cur_traffic = result["daily_traffic"]
    revenue_mom = ((cur_rev / prior_rev - 1) * 100).where(
        adjacent & cur_rev.notna() & prior_rev.notna()
    )
    traffic_mom = ((cur_traffic / prior_traffic - 1) * 100).where(
        adjacent & cur_traffic.notna() & prior_traffic.notna()
    )

    result["revenue_mom"] = revenue_mom
    result["traffic_mom"] = traffic_mom
    result["revenue_spike"] = revenue_mom.abs().gt(threshold).fillna(False)
    result["traffic_spike"] = traffic_mom.abs().gt(threshold).fillna(False)

    result["_max_abs"] = result[["revenue_mom", "traffic_mom"]].abs().max(
        axis=1, skipna=True
    )
    result = result.sort_values(
        ["_max_abs", "code", "period"],
        ascending=[False, True, True],
        na_position="last",
    )
    return result.drop(columns=["_period_dt", "_max_abs"])


def distribution_rate_benchmark(quarterly_df: pd.DataFrame) -> pd.DataFrame:
    """按报告期分组，与同行业可供分配金额中位数对标。

    每组至少 3 只基金（按 code 去重计数）才计算可供分配金额中位数；
    不足 3 只时 median_distributable_wan 为 NaN。可供分配为 None 的行
    不参与中位数计算，其 below_peer_distributable 为 NaN。

    返回 DataFrame：原列 + median_distributable_wan + below_peer_distributable(bool)。
    """
    result = quarterly_df.copy()
    if result.empty:
        return result

    group_counts = result.groupby("period")["code"].transform("nunique")
    median = result.groupby("period")["distributable_wan"].transform("median")

    result["median_distributable_wan"] = median.where(group_counts >= 3)
    result["below_peer_distributable"] = (
        result["distributable_wan"] < result["median_distributable_wan"]
    ).where((group_counts >= 3) & result["distributable_wan"].notna())
    return result


def concession_decay(
    static_df: pd.DataFrame, warn_years: float = 10, normal_years: float = 15
) -> pd.DataFrame:
    """特许经营权衰减规则：按剩余年限划分风险等级。

    按 concession_years_left 升序排序（剩余年限最短在前，风险最高）：
    - remaining < warn_years → risk_level="临近到期"
    - warn_years <= remaining < normal_years → risk_level="关注"
    - remaining >= normal_years → risk_level="正常"
    - 缺失（NaN）→ risk_level="未知"，排最后

    返回 DataFrame：原列 + risk_level(str)。空 DataFrame 不崩溃。
    """
    result = static_df.copy()

    def classify(remaining):
        if pd.isna(remaining):
            return "未知"
        if remaining < warn_years:
            return "临近到期"
        if remaining < normal_years:
            return "关注"
        return "正常"

    result["risk_level"] = result["concession_years_left"].map(classify)
    if result.empty:
        return result
    return result.sort_values(
        "concession_years_left", ascending=True, na_position="last"
    )
