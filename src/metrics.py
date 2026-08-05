"""派生指标计算模块。

基于季度数据 DataFrame 计算各类财务派生指标，并提取最新季度的指标摘要。
输入列名与 src.data_loader.load_quarterly 的输出保持一致。
"""

import pandas as pd


def noi_margin(df):
    """计算每行的营业利润率：(营业总收入 - 营业成本) / 营业总收入。

    index 与输入 DataFrame 保持一致。
    """
    return (df["total_revenue_wan"] - df["total_cost_wan"]) / df["total_revenue_wan"]


def net_margin(df):
    """计算每行的净利润率：净利润 / 营业总收入。

    index 与输入 DataFrame 保持一致。
    """
    return df["net_profit_wan"] / df["total_revenue_wan"]


def annualized_distributable_yield(df):
    """计算每行的年化可供分配收益率：可供分配金额 * 4 / 基金净资产（年化近似）。

    index 与输入 DataFrame 保持一致。
    """
    return df["distributable_wan"] * 4 / df["nav_wan"]


def latest_metrics(df, code, nav_wan=None):
    """返回指定 code 最新一季度（按 period 字符串排序取最后一行）的指标摘要。

    返回 dict，键为 period（str）、noi_margin、net_margin、distributable_yield。
    年化可供分配收益率 = 最新季度 distributable_wan×4 ÷ 最新年报净值 nav_wan
    （显式传入）；缺省回退季度数据 nav_wan 列（历史行为）。NAV 或可供分配
    缺失时 distributable_yield 为 None（看板显示「—」）。
    该 code 无数据时返回空 dict {}。
    """
    sub = df[df["code"] == code]
    if sub.empty:
        return {}
    latest = sub.sort_values("period").iloc[-1]
    effective_nav = nav_wan if nav_wan is not None else latest.get("nav_wan")
    if pd.isna(effective_nav) or pd.isna(latest["distributable_wan"]):
        yield_value = None
    else:
        yield_value = float(latest["distributable_wan"] * 4 / effective_nav)
    return {
        "period": latest["period"],
        "noi_margin": float(
            (latest["total_revenue_wan"] - latest["total_cost_wan"])
            / latest["total_revenue_wan"]
        ),
        "net_margin": float(latest["net_profit_wan"] / latest["total_revenue_wan"]),
        "distributable_yield": yield_value,
    }
