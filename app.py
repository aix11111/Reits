"""REITsMonitor Streamlit 看板入口。

Phase 1：面向高速公路 REITs 的投后分析看板。
经营数据来自本地模板 Excel（data/REITsMonitor_数据模板_v1.xlsx），
行情数据来自 akshare（网络异常时自动降级为空数据）。
"""

from pathlib import Path

import streamlit as st

from src.charts import bar_chart, line_chart
from src.data_loader import load_all
from src.market_data import get_hist, get_realtime_quotes
from src.metrics import latest_metrics

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

    tab_ops, tab_mkt = st.tabs(["📈 经营数据", "📉 行情走势"])

    with tab_ops:
        render_operations(
            selected_code, name_map.get(selected_code, ""), monthly_df, quarterly_df
        )

    with tab_mkt:
        render_market(selected_code)


if __name__ == "__main__":
    main()
