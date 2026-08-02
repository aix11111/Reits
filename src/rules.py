"""投后分析规则引擎。

基于月度数据 DataFrame 实现投后管理分析规则：
- 规则 1：流量/收入背离检测 detect_divergence
- 规则 2：同类基金月度同比对标 peer_compare

输入列名与 src.data_loader.load_monthly 的输出保持一致。
注意：月度数据无环比列，环比异动检测（规则 3）暂不实现。
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
