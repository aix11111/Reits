"""REITsMonitor Streamlit 看板入口。

Phase 1：面向高速公路 REITs 的投后分析看板。
经营数据来自本地模板 Excel（data/REITsMonitor_数据模板_v1.xlsx），
行情数据来自 akshare（网络异常时自动降级为空数据）。
分析规则页签基于 src.rules 的规则引擎展示可供分配对标与背离检测。
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.charts import bar_chart, line_chart
from src.data_loader import load_all
from src.market_data import get_hist, get_realtime_quotes
from src.metrics import latest_metrics
from src.rules import (
    concession_decay,
    detect_divergence,
    detect_mom_spikes,
    distribution_rate_benchmark,
    distributable_yoy,
)

# 数据文件路径：位于本文件同级的 data 目录下
DATA_PATH = Path(__file__).parent / "data" / "REITsMonitor_数据模板_v1.xlsx"

# 季度经营明细展示列：英文列名 → 中文列名
_QUARTERLY_COLUMNS = [
    ("period", "报告期"),
    ("total_revenue_wan", "总收入"),
    ("total_cost_wan", "总成本"),
    ("net_profit_wan", "净利润"),
    ("distributable_wan", "可供分配"),
    ("ebitda_wan", "EBITDA"),
    ("nav_wan", "NAV"),
]

# 分析规则页签：可供分配对标展示列
_RULES_BENCHMARK_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("distributable_wan", "可供分配(万元)"),
    ("distributable_yoy", "同比(%)"),
    ("median_distributable_wan", "行业中位数(万元)"),
    ("below_peer_distributable", "低于行业中位数"),
    ("decline_flag", "下滑标记"),
]

# 分析规则页签：背离检测展示列
_RULES_DIVERGENCE_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("period", "月份"),
    ("toll_revenue_yoy", "收入同比(%)"),
    ("traffic_yoy", "车流量同比(%)"),
    ("divergence_pct", "背离幅度(百分点)"),
    ("direction", "方向"),
]

# 背离方向：英文标记 → 中文说明
_DIRECTION_LABELS = {
    "revenue_above": "收入显著高于流量",
    "traffic_above": "流量显著高于收入",
}

# 分析规则页签：环比异动展示列
_RULES_MOM_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("period", "月份"),
    ("revenue_mom", "收入环比(%)"),
    ("traffic_mom", "车流量环比(%)"),
    ("revenue_spike", "收入异动"),
    ("traffic_spike", "车流量异动"),
]

# 分析规则页签：特许经营权衰减展示列
_RULES_CONCESSION_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("concession_years_left", "剩余年限(年)"),
    ("risk_level", "风险等级"),
]

# 特许经营权衰减风险等级 → 条形图颜色
_RISK_LEVEL_COLORS = {
    "临近到期": "#d62728",
    "关注": "#ff7f0e",
    "正常": "#2ca02c",
    "未知": "#7f7f7f",
}


def render_operations(code, name, monthly_df, quarterly_df):
    """经营数据页签：最新指标 KPI、月度图表与季度明细表。"""
    st.subheader(f"基金：{code} {name}")

    metrics = latest_metrics(quarterly_df, code)
    if metrics:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最新季度", metrics["period"])
        c2.metric("NOI利润率", f"{metrics['noi_margin']:.1%}")
        c3.metric("净利润率", f"{metrics['net_margin']:.1%}")
        c4.metric("年化可供分配收益率", f"{metrics['distributable_yield']:.1%}")
    else:
        st.warning("暂无季度数据，无法计算经营指标。")

    monthly = monthly_df[monthly_df["code"] == code].sort_values("period")
    if not monthly.empty:
        st.plotly_chart(
            line_chart(
                monthly, "period", "toll_revenue_wan",
                "通行费收入（万元）", "通行费收入（万元）",
            ),
            width="stretch",
        )
        st.plotly_chart(
            bar_chart(
                monthly, "period", "daily_traffic",
                "日均自然车流量（辆/日）", "日均自然车流量（辆/日）",
            ),
            width="stretch",
        )
    else:
        st.info("暂无月度数据。")

    quarterly = quarterly_df[quarterly_df["code"] == code]
    if not quarterly.empty:
        st.subheader("季度经营明细")
        display = (
            quarterly.sort_values("period", ascending=False)
            .copy()
            .rename(columns=dict(_QUARTERLY_COLUMNS))
        )
        st.dataframe(
            display[[label for _, label in _QUARTERLY_COLUMNS]],
            hide_index=True,
            width="stretch",
        )


def render_market(code):
    """行情走势页签：实时行情 KPI 与历史收盘价走势图。"""
    quotes = get_realtime_quotes()
    row = quotes[quotes["code"] == code]
    if not row.empty:
        q = row.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("最新价", f"{q['price']:.3f}")
        c2.metric("涨跌幅", f"{q['pct_change']:.2f}%")
        c3.metric("成交额（万元）", f"{q['amount'] / 10000:.1f} 万")
    else:
        st.warning("未获取到实时行情（网络异常已降级），本页签行情数据跳过。")

    hist = get_hist(code)
    if not hist.empty:
        st.plotly_chart(
            line_chart(hist, "date", "close", "收盘价走势", "收盘价"),
            width="stretch",
        )
    else:
        st.info("暂无历史行情数据。")


def _tristate_label(value):
    """三态布尔转中文：True → 是，False → 否，NaN → 一。"""
    if pd.isna(value):
        return "—"
    return "是" if value else "否"


def render_rules(monthly_df, quarterly_df, static_df):
    """分析规则页签：全行业可供分配对标、月度背离检测、环比异动与特许经营权衰减。"""
    st.subheader("分析规则引擎")
    st.caption(
        "基于季度数据：可供分配金额同比与同行对标；基于月度数据：收入/车流量背离检测与环比异动检测；"
        "基于静态数据：特许经营权剩余年限衰减。"
    )

    st.markdown("### 1. 全行业可供分配对标（最新季度）")
    if quarterly_df.empty:
        st.info("暂无季度数据，可供分配对标跳过。")
    else:
        latest_period = sorted(quarterly_df["period"].unique())[-1]
        yoy_result = distributable_yoy(quarterly_df)
        bench_result = distribution_rate_benchmark(quarterly_df)
        latest = bench_result[bench_result["period"] == latest_period].merge(
            yoy_result[["code", "period", "distributable_yoy", "decline_flag"]],
            on=["code", "period"],
            how="left",
        )
        latest = latest.sort_values(
            "distributable_yoy", ascending=False, na_position="last"
        )

        # 横向条形图：按可供分配金额升序，最大者位于顶部；低于行业中位数标红
        chart_df = latest.sort_values("distributable_wan", ascending=True)
        fig = go.Figure(
            go.Bar(
                x=chart_df["distributable_wan"],
                y=chart_df["name"],
                orientation="h",
                marker_color=[
                    "#d62728" if below else "#2ca02c"
                    for below in chart_df["below_peer_distributable"]
                    .fillna(False)
                    .astype(bool)
                ],
            )
        )
        fig.update_layout(
            title=f"最新季度（{latest_period}）可供分配金额对标",
            xaxis_title="可供分配金额（万元）",
            template="plotly_white",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif"),
        )
        st.plotly_chart(fig, width="stretch")

        st.markdown(f"**{latest_period} 行业明细**")
        display = latest.copy()
        display["below_peer_distributable"] = display["below_peer_distributable"].map(
            _tristate_label
        )
        display["decline_flag"] = display["decline_flag"].map(
            lambda v: "下滑" if v else ""
        )
        display = display.rename(columns=dict(_RULES_BENCHMARK_COLUMNS))
        st.dataframe(
            display[[label for _, label in _RULES_BENCHMARK_COLUMNS]],
            hide_index=True,
            width="stretch",
        )

    st.markdown("### 2. 背离检测（最新月度）")
    if monthly_df.empty:
        st.info("暂无月度数据，背离检测跳过。")
    else:
        latest_month = sorted(monthly_df["period"].unique())[-1]
        diverged = detect_divergence(monthly_df)
        flagged = diverged[
            (diverged["period"] == latest_month) & diverged["divergence"]
        ]
        if flagged.empty:
            st.info(f"最新月度（{latest_month}）无收入/车流量背离记录。")
        else:
            display = flagged.copy()
            display["direction"] = display["direction"].map(_DIRECTION_LABELS)
            display = display.rename(columns=dict(_RULES_DIVERGENCE_COLUMNS))
            st.markdown(f"**{latest_month} 背离记录**")
            st.dataframe(
                display[[label for _, label in _RULES_DIVERGENCE_COLUMNS]],
                hide_index=True,
                width="stretch",
            )

    st.markdown("### 3. 环比异动（最新月度）")
    if monthly_df.empty:
        st.info("暂无月度数据，环比异动跳过。")
    else:
        latest_month = sorted(monthly_df["period"].unique())[-1]
        spikes = detect_mom_spikes(monthly_df)
        flagged = spikes[
            (spikes["period"] == latest_month)
            & (spikes["revenue_spike"] | spikes["traffic_spike"])
        ]
        if flagged.empty:
            st.info(f"最新月度（{latest_month}）无环比异动记录。")
        else:
            display = flagged.copy()
            display["revenue_spike"] = display["revenue_spike"].map(
                lambda v: "收入异动" if v else ""
            )
            display["traffic_spike"] = display["traffic_spike"].map(
                lambda v: "车流量异动" if v else ""
            )
            display = display.rename(columns=dict(_RULES_MOM_COLUMNS))
            st.markdown(f"**{latest_month} 环比异动记录**")
            st.dataframe(
                display[[label for _, label in _RULES_MOM_COLUMNS]],
                hide_index=True,
                width="stretch",
            )

    st.markdown("### 4. 特许经营权衰减（剩余年限）")
    if static_df.empty:
        st.info("暂无静态数据，特许经营权衰减分析跳过。")
    else:
        decay = concession_decay(static_df)

        # 横向条形图：剩余年限最短者（风险最高）位于顶部；
        # 临近到期红色、关注橙色、正常绿色，未知不参与绘图
        chart_df = decay[decay["concession_years_left"].notna()].sort_values(
            "concession_years_left", ascending=False
        )
        if not chart_df.empty:
            fig = go.Figure(
                go.Bar(
                    x=chart_df["concession_years_left"],
                    y=chart_df["name"],
                    orientation="h",
                    marker_color=[
                        _RISK_LEVEL_COLORS[level] for level in chart_df["risk_level"]
                    ],
                )
            )
            fig.update_layout(
                title="特许经营权剩余年限（年）",
                xaxis_title="剩余年限（年）",
                template="plotly_white",
                font=dict(family="Microsoft YaHei, SimHei, sans-serif"),
            )
            st.plotly_chart(fig, width="stretch")

        display = decay.rename(columns=dict(_RULES_CONCESSION_COLUMNS))
        st.dataframe(
            display[[label for _, label in _RULES_CONCESSION_COLUMNS]],
            hide_index=True,
            width="stretch",
        )


def main():
    """看板主流程：加载数据、渲染侧边栏选择器与两个页签。"""
    st.set_page_config(page_title="REITsMonitor", page_icon="📊", layout="wide")
    st.title("📊 REITsMonitor — 公募REITs投后分析看板")
    st.caption(
        "Phase 1：高速公路 REITs | 经营数据来自本地模板，行情数据来自 akshare"
    )

    try:
        data = load_all(DATA_PATH)
    except FileNotFoundError:
        st.error(f"未找到数据文件：{DATA_PATH}")
        st.info("请按模板填写数据并保存至 data/REITsMonitor_数据模板_v1.xlsx 后重试。")
        st.stop()

    static_df = data["static"]
    if static_df.empty:
        st.error("静态信息表为空，无法生成看板。")
        st.stop()

    monthly_df = data["monthly"]
    quarterly_df = data["quarterly"]
    name_map = dict(zip(static_df["code"], static_df["name"]))

    with st.sidebar:
        st.header("选择REIT")
        selected_code = st.selectbox(
            "选择REIT",
            options=sorted(static_df["code"].tolist()),
            format_func=lambda code: f"{code} {name_map.get(code, '')}",
        )
        st.caption("行情数据来自 akshare，网络异常时自动降级。")

    tab_ops, tab_mkt, tab_rules = st.tabs(["📈 经营数据", "📉 行情走势", "📐 分析规则"])

    with tab_ops:
        render_operations(
            selected_code, name_map.get(selected_code, ""), monthly_df, quarterly_df
        )

    with tab_mkt:
        render_market(selected_code)

    with tab_rules:
        render_rules(monthly_df, quarterly_df, static_df)


if __name__ == "__main__":
    main()
