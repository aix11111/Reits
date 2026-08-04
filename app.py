"""REITsMonitor Streamlit 看板入口。

Phase 1：面向高速公路 REITs 的投后分析看板。
经营数据来自本地模板 Excel（data/REITsMonitor_数据模板_v1.xlsx），
行情数据来自 akshare（网络异常时自动降级为空数据）。
分析规则页签基于 src.rules 的规则引擎展示可供分配对标与背离检测。
UI 为「彭博×苹果」深色金融终端风格（Linear 暗色系统）。
"""

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.charts import bar_chart, line_chart
from src.data_loader import load_all, load_fund_shares, load_market_snapshot
from src.market_data import get_hist, get_realtime_quotes
from src.metrics import latest_metrics
from src.rules import (
    concession_decay,
    detect_divergence,
    detect_mom_spikes,
    distributable_completion,
    distribution_rate_benchmark,
    distributable_yoy,
)
from src.valuation import (
    concession_irr,
    distribution_yield,
    nav_premium,
    risk_flags,
    ttm_distributable,
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

# 年报可供分配完成度数据文件路径
_ANNUAL_COMPLETION_PATH = Path(__file__).parent / "data" / "annual_completion.json"

# 估值对标页签数据文件路径
_MARKET_SNAPSHOT_PATH = Path(__file__).parent / "data" / "market_snapshot.json"
_FUND_SHARES_PATH = Path(__file__).parent / "data" / "fund_shares.json"

# 估值对标页签：收益率排名展示列
_VALUATION_RANK_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("yield_pct", "分派率收益率"),
    ("caliber", "口径"),
    ("irr_pct", "特许经营IRR"),
]

# 估值对标页签：NAV 折溢价展示列
_VALUATION_PREMIUM_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("price", "市价(元)"),
    ("nav_unit_price", "单位净值(元)"),
    ("premium_pct", "折溢价"),
]

# risk_flags 英文标记 → 中文风险提示
_RISK_FLAG_LABELS = {
    "completion_risk": "完成度未达标",
    "completion_watch": "完成度偏低",
    "premium_risk": "折溢价过高",
    "concession_risk": "剩余年限不足10年",
}

# 分析规则页签：可供分配完成度展示列
_RULES_COMPLETION_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("year", "年份"),
    ("predicted_wan", "预测(万元)"),
    ("actual_wan", "实际(万元)"),
    ("completion_pct", "完成率(%)"),
    ("status", "状态"),
]

# ---- 深色金融终端配色（Linear 暗色系统：亮度分层，不做 box-shadow）----
_BG = "#0A0E17"                 # 页面背景
_SIDEBAR_BG = "#0F121C"         # 侧边栏背景
_TEXT_PRIMARY = "#F7F8F8"       # 主文本
_TEXT_SECONDARY = "#D0D6E0"     # 次文本
_TEXT_TERTIARY = "#8A8F98"      # 三级灰（标签、说明）
_ACCENT = "#2DD4BF"             # 强调青绿（KPI 高亮、图表主线、链接）
_CARD_BG = "rgba(255,255,255,0.03)"
_CARD_BORDER = "rgba(255,255,255,0.08)"
_MET_GREEN = "#10B981"          # 达标
_WARN_ORANGE = "#FBBF24"        # 警告
_RISK_RED = "#F87171"           # 风险
_NO_RECORD_GRAY = "#4B5563"     # 无记录
_MONO_FONT = "'JetBrains Mono', ui-monospace, monospace"

# 特许经营权衰减风险等级 → 条形图颜色（三态语义色）
_RISK_LEVEL_COLORS = {
    "临近到期": _RISK_RED,
    "关注": _WARN_ORANGE,
    "正常": _MET_GREEN,
    "未知": _NO_RECORD_GRAY,
}

# 全局深色终端样式（经 st.markdown unsafe_allow_html 注入）
_GLOBAL_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"] {{
    background-color: {_BG};
}}

[data-testid="stHeader"] {{
    background: transparent;
}}

[data-testid="stSidebar"] {{
    background-color: {_SIDEBAR_BG};
    border-right: 1px solid {_CARD_BORDER};
}}

[data-testid="stMarkdownContainer"] {{
    color: {_TEXT_PRIMARY};
}}

[data-testid="stCaptionContainer"], [data-testid="stWidgetLabel"] p {{
    color: {_TEXT_TERTIARY};
}}

[data-testid="stApp"] a {{
    color: {_ACCENT};
}}

/* 表格：数字/代码列等宽（JetBrains Mono + 本地回退，中文走系统字体） */
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] th {{
    font-family: {_MONO_FONT};
    font-size: 13px;
}}

/* 原生指标卡与终端卡对齐：亮度分层（无阴影） */
[data-testid="stMetric"] {{
    background: {_CARD_BG};
    border: 1px solid {_CARD_BORDER};
    border-radius: 8px;
    padding: 12px 16px;
}}

[data-testid="stMetricLabel"] p {{
    color: {_TEXT_TERTIARY};
    font-size: 12px;
}}

[data-testid="stMetricValue"] {{
    font-family: {_MONO_FONT};
    color: {_ACCENT};
}}
"""


def _fmt_pct(v) -> str:
    """数值为 nan/None 时显示 \"—\"，否则格式化为百分比。"""
    if pd.isna(v):
        return "—"
    return f"{v:.1%}"


def _kpi_card(label: str, value: str, note: str) -> str:
    """终端读数 KPI 卡：标签（三级灰）→ 大号等宽青绿数值 → 单位说明（三级灰）。"""
    return (
        '<div class="reit-kpi-card" style="background:rgba(255,255,255,0.03);'
        'border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:16px;">'
        f'<div style="font-size:12px;color:#8A8F98;margin-bottom:8px;">{label}</div>'
        f'<div style="font-family:\'JetBrains Mono\',ui-monospace,monospace;font-size:28px;'
        f'color:#2DD4BF;font-weight:600;line-height:1.2;">{value}</div>'
        f'<div style="font-size:12px;color:#8A8F98;margin-top:8px;">{note}</div>'
        "</div>"
    )


def render_operations(code, name, monthly_df, quarterly_df):
    """经营数据页签：最新指标 KPI、月度图表与季度明细表。"""
    st.subheader(f"基金：{code} {name}")

    metrics = latest_metrics(quarterly_df, code)
    if metrics:
        cards = "".join(
            [
                _kpi_card("最新季度", str(metrics["period"]), "报告期"),
                _kpi_card("NOI利润率", _fmt_pct(metrics["noi_margin"]),
                          "(营业总收入-营业成本)/营业总收入"),
                _kpi_card("净利润率", _fmt_pct(metrics["net_margin"]), "净利润/营业总收入"),
                _kpi_card("年化可供分配收益率", _fmt_pct(metrics["distributable_yield"]),
                          "可供分配×4/NAV（年化）"),
            ]
        )
        st.markdown(
            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'
            'margin:8px 0 16px;">' + cards + "</div>",
            unsafe_allow_html=True,
        )
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
    quotes = _quotes_cached()
    row = quotes[quotes["code"] == code]
    if not row.empty:
        q = row.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("最新价", f"{q['price']:.3f}")
        c2.metric("涨跌幅", f"{q['pct_change']:.2f}%")
        c3.metric("成交额（万元）", f"{q['amount'] / 10000:.1f} 万")
    else:
        st.warning("未获取到实时行情（网络异常已降级），本页签行情数据跳过。")

    hist = _hist_cached(code)
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


@st.cache_data(ttl=3600, show_spinner=False)
def _load_all_cached():
    """缓存加载本地模板数据，ttl 1 小时。"""
    return load_all(DATA_PATH)


@st.cache_data(ttl=300, show_spinner=False)
def _quotes_cached():
    """缓存全市场实时行情，ttl 5 分钟。"""
    return get_realtime_quotes()


@st.cache_data(ttl=300, show_spinner=False)
def _hist_cached(code):
    """缓存单只 REIT 历史日线，ttl 5 分钟。"""
    return get_hist(code)


def _load_annual_completion() -> pd.DataFrame:
    """加载 data/annual_completion.json 的 completion 数组。

    文件缺失、内容为空或损坏时返回空 DataFrame（看板降级提示）。
    除完成度列外，还保留 nav_unit_price / nav_wan 供估值对标页签使用。
    """
    columns = [col for col, _ in _RULES_COMPLETION_COLUMNS] + [
        "nav_unit_price",
        "nav_wan",
    ]
    if not _ANNUAL_COMPLETION_PATH.exists():
        return pd.DataFrame(columns=columns)
    try:
        data = json.loads(_ANNUAL_COMPLETION_PATH.read_text(encoding="utf-8"))
        rows = data.get("completion", [])
    except (ValueError, OSError):
        rows = []
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _completion_color(value):
    """完成率着色：<80 风险红、<100 警告橙、其余达标绿；缺失灰色。"""
    if pd.isna(value):
        return f"color: {_NO_RECORD_GRAY}"
    if value < 80:
        return f"color: {_RISK_RED}"
    if value < 100:
        return f"color: {_WARN_ORANGE}"
    return f"color: {_MET_GREEN}"


def _premium_color(value):
    """NAV 折溢价着色：溢价红（风险语义）、折价绿、平水三级灰；缺失灰色。"""
    if pd.isna(value):
        return f"color: {_NO_RECORD_GRAY}"
    if value > 0:
        return f"color: {_RISK_RED}"
    if value < 0:
        return f"color: {_MET_GREEN}"
    return f"color: {_TEXT_TERTIARY}"


def render_status_wall(static_df, completion_df):
    """签名元素 1：行业状态墙——title 下方一行基金完成度色点带。

    每只基金 = 圆点 12px + 4 位代码 10px 三级灰小字（flex 一行）。
    状态取每基金最新年份 completion_pct：>=100 达标绿、>=80 警告橙、<80
    风险红、无记录灰。title 属性携带「{code} {name}：完成率 {pct}%（{year}）」。
    空数据降级为 st.info。
    """
    if completion_df.empty:
        st.info("暂无年度可供分配完成度数据，行业状态墙跳过。")
        return

    latest = distributable_completion(completion_df).sort_values("year")
    latest = latest.groupby("code").tail(1)
    by_code = {str(r.code): r for r in latest.itertuples(index=False)}

    dots = []
    for _, fund in static_df.iterrows():
        code = str(fund["code"])
        name = fund["name"]
        rec = by_code.get(code)
        if rec is None or pd.isna(rec.completion_pct):
            color, title = _NO_RECORD_GRAY, "暂无完成度数据"
        else:
            color = (
                _MET_GREEN if rec.completion_pct >= 100
                else (_WARN_ORANGE if rec.completion_pct >= 80 else _RISK_RED)
            )
            title = f"{code} {name}：完成率 {rec.completion_pct:g}%（{rec.year}）"
        dots.append(
            f'<div title="{title}" style="display:flex;align-items:center;gap:6px;'
            f'cursor:default;">'
            f'<span class="reit-dot" style="width:12px;height:12px;border-radius:50%;'
            f'background-color:{color};display:inline-block;flex:none;"></span>'
            f'<span style="font-family:\'JetBrains Mono\',ui-monospace,monospace;'
            f'font-size:10px;color:#8A8F98;">{code[-4:]}</span>'
            "</div>"
        )

    st.markdown(
        '<div class="reit-status-wall" style="display:flex;flex-wrap:wrap;align-items:center;'
        'gap:12px 18px;padding:16px;background:rgba(255,255,255,0.03);'
        'border:1px solid rgba(255,255,255,0.08);border-radius:8px;'
        'margin:8px 0 16px;">' + "".join(dots) + "</div>",
        unsafe_allow_html=True,
    )


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

        # 横向条形图：按可供分配金额升序，最大者位于顶部；低于行业中位数标风险红
        chart_df = latest.sort_values("distributable_wan", ascending=True)
        fig = go.Figure(
            go.Bar(
                x=chart_df["distributable_wan"],
                y=chart_df["name"],
                orientation="h",
                marker_color=[
                    _RISK_RED if below else _MET_GREEN
                    for below in chart_df["below_peer_distributable"]
                    .fillna(False)
                    .astype(bool)
                ],
            )
        )
        fig.update_layout(
            title=f"最新季度（{latest_period}）可供分配金额对标",
            xaxis_title="可供分配金额（万元）",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
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
        # 临近到期风险红、关注警告橙、正常达标绿，未知不参与绘图
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
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
                xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            )
            st.plotly_chart(fig, width="stretch")

        display = decay.rename(columns=dict(_RULES_CONCESSION_COLUMNS))
        st.dataframe(
            display[[label for _, label in _RULES_CONCESSION_COLUMNS]],
            hide_index=True,
            width="stretch",
        )

    st.markdown("### 5. 可供分配完成度（实际 vs 招募说明书预测）")
    st.caption("完成率 = 年报披露口径：实际可供分配金额 / 招募说明书测算预测金额。")
    completion_df = _load_annual_completion()
    if completion_df.empty:
        st.info("暂无年度可供分配完成度数据（data/annual_completion.json 缺失或为空）。")
    else:
        completion = distributable_completion(completion_df)
        display = completion.rename(columns=dict(_RULES_COMPLETION_COLUMNS))
        styled = display.style.map(_completion_color, subset=["完成率(%)"])
        st.dataframe(styled, hide_index=True, width="stretch")


def _ttm_display_table(ttm_df, name_map):
    """降级态：仅展示 TTM 可供分配金额（无市值快照，无收益率）。"""
    if ttm_df.empty:
        st.info("暂无季度可供分配数据，无法计算 TTM。")
        return
    display = ttm_df.reset_index()
    display["name"] = display["code"].map(name_map)
    display["口径"] = display["is_annualized"].map(
        lambda v: "年化" if pd.notna(v) and v else "TTM"
    )
    display = display.rename(
        columns={
            "code": "基金代码",
            "name": "基金简称",
            "dist_ttm_wan": "TTM可供分配(万元)",
        }
    )
    st.dataframe(
        display[["基金代码", "基金简称", "TTM可供分配(万元)", "口径"]],
        hide_index=True,
        width="stretch",
    )


def render_valuation(quarterly_df, completion_df, snapshot_data, shares, static_df):
    """估值对标页签：分派率收益率排名、NAV 折溢价与风险聚合提示。

    市值数据来自本地快照（market_snapshot.json），不依赖运行时网络。
    快照缺失时降级为 st.info + 仅显示 TTM 分派表。
    """
    st.subheader("估值对标")
    st.caption(
        "分派率收益率=TTM 可供分配（近4季）/最新市值；NAV 折溢价=市价/最新年报单位净值-1。"
    )

    snapshot_latest = snapshot_data.get("latest") or {}
    shares_map = shares.get("shares") or {}
    name_map = dict(zip(static_df["code"], static_df["name"]))
    years_left = static_df.set_index("code")["concession_years_left"]

    ttm = ttm_distributable(quarterly_df)

    if not snapshot_latest:
        st.info("市值数据缺失（等待下月 cron 更新）")
        _ttm_display_table(ttm, name_map)
        return

    yield_series = distribution_yield(ttm, snapshot_latest, shares_map)

    # ---- 1. 分派率收益率排名 ----
    st.markdown("### 1. 分派率收益率排名（TTM）")
    rank_rows = []
    for code, info in snapshot_latest.items():
        if "price" not in info:
            continue
        annual = ttm.loc[code, "dist_ttm_wan"] if code in ttm.index else None
        left = years_left.get(code) if code in years_left.index else None
        irr = (
            concession_irr(info["price"], shares_map.get(code), annual, left)
            if pd.notna(annual) and pd.notna(left)
            else None
        )
        rank_rows.append(
            {
                "code": code,
                "name": name_map.get(code, ""),
                "yield": yield_series.get(code, float("nan")),
                "is_annualized": (
                    ttm.loc[code, "is_annualized"] if code in ttm.index else None
                ),
                "years_left": left,
                "irr": irr,
            }
        )
    rank = pd.DataFrame(rank_rows)

    chart = rank.dropna(subset=["yield"]).sort_values("yield", ascending=True)
    if not chart.empty:
        median_yield = chart["yield"].median()
        fig = go.Figure(
            go.Bar(
                x=chart["yield"],
                y=chart["name"],
                orientation="h",
                marker_color=_ACCENT,
            )
        )
        fig.add_vline(
            x=median_yield,
            line_dash="dash",
            line_color=_TEXT_TERTIARY,
            annotation_text="行业中位数",
            annotation_font_color=_TEXT_TERTIARY,
        )
        fig.update_layout(
            title="分派率收益率排名",
            xaxis_title="分派率收益率",
            xaxis_tickformat=".0%",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig, width="stretch")

    scatter_df = rank.dropna(subset=["irr", "years_left"])
    if not scatter_df.empty:
        st.markdown("### 1.1 特许经营 IRR 与剩余年限")
        scat = go.Figure(
            go.Scatter(
                x=scatter_df["years_left"],
                y=scatter_df["irr"],
                mode="markers+text",
                text=scatter_df["name"],
                textposition="top center",
                marker=dict(color=_ACCENT, size=11),
            )
        )
        scat.add_vline(
            x=10,
            line_dash="dash",
            line_color=_WARN_ORANGE,
            annotation_text="到期临近",
            annotation_font_color=_WARN_ORANGE,
        )
        scat.update_layout(
            title="特许经营 IRR 与剩余年限",
            xaxis_title="剩余年限(年)",
            yaxis_title="特许经营 IRR",
            yaxis_tickformat=".1%",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(scat, width="stretch")

    display = rank.sort_values("yield", ascending=False, na_position="last").copy()
    display["yield_pct"] = display["yield"].map(_fmt_pct)
    display["caliber"] = display["is_annualized"].map(
        lambda v: "年化" if pd.notna(v) and v else "TTM"
    )
    display["irr_pct"] = display["irr"].map(_fmt_pct)
    display = display.rename(columns=dict(_VALUATION_RANK_COLUMNS))
    st.dataframe(
        display[[label for _, label in _VALUATION_RANK_COLUMNS]],
        hide_index=True,
        width="stretch",
    )

    # ---- 2. NAV 折溢价 ----
    st.markdown("### 2. NAV 折溢价（最新年报单位净值）")
    price_series = pd.Series(
        {code: info["price"] for code, info in snapshot_latest.items() if "price" in info}
    )
    if completion_df.empty:
        nav_series = pd.Series(dtype=float)
    else:
        latest_comp = completion_df.sort_values("year").groupby("code").tail(1)
        nav_series = latest_comp.set_index("code")["nav_unit_price"]
    premium = nav_premium(price_series, nav_series)

    prem_rows = []
    for code, info in snapshot_latest.items():
        price = info.get("price")
        nav = nav_series.get(code, float("nan"))
        prem_rows.append(
            {
                "code": code,
                "name": name_map.get(code, ""),
                "price": price,
                "nav_unit_price": nav,
                "premium_pct": premium.get(code, float("nan")),
            }
        )
    prem_df = pd.DataFrame(prem_rows)
    prem_display = prem_df.rename(columns=dict(_VALUATION_PREMIUM_COLUMNS))
    styled = prem_display.style.map(_premium_color, subset=["折溢价"]).format(
        {"市价(元)": "{:.3f}", "单位净值(元)": "{:.4f}", "折溢价": _fmt_pct},
        na_rep="—",
    )
    st.dataframe(styled, hide_index=True, width="stretch")

    # ---- 3. 风险聚合提示 ----
    st.markdown("### 3. 风险聚合提示")
    if completion_df.empty:
        flags = pd.DataFrame(columns=["code", "flags"])
    else:
        latest_comp = completion_df.sort_values("year").groupby("code").tail(1)
        flags = risk_flags(latest_comp, premium, years_left)

    lines = []
    for row in flags.itertuples():
        labels = " / ".join(_RISK_FLAG_LABELS[f] for f in row.flags)
        lines.append(f"{row.code} {name_map.get(row.code, '')}：{labels}")

    if lines:
        st.warning("；\n".join(lines))
    else:
        st.info("暂无风险标记：各基金完成度、折溢价与剩余年限均在正常区间。")


def main():
    """看板主流程：加载数据、渲染侧边栏选择器与四个页签。"""
    st.set_page_config(page_title="REITsMonitor", page_icon="📊", layout="wide")
    st.markdown(f"<style>{_GLOBAL_CSS}</style>", unsafe_allow_html=True)
    st.title("📊 REITsMonitor — 公募REITs投后分析看板")
    st.caption(
        "Phase 1：高速公路 REITs | 经营数据来自本地模板，行情数据来自 akshare"
    )

    try:
        data = _load_all_cached()
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

    completion_df = _load_annual_completion()
    render_status_wall(static_df, completion_df)

    with st.sidebar:
        st.header("选择REIT")
        selected_code = st.selectbox(
            "选择REIT",
            options=sorted(static_df["code"].tolist()),
            format_func=lambda code: f"{code} {name_map.get(code, '')}",
        )
        st.caption("行情数据来自 akshare，网络异常时自动降级。")

    tab_ops, tab_mkt, tab_rules, tab_val = st.tabs(
        ["📈 经营数据", "📉 行情走势", "📐 分析规则", "📊 估值对标"]
    )

    with tab_ops:
        render_operations(
            selected_code, name_map.get(selected_code, ""), monthly_df, quarterly_df
        )

    with tab_mkt:
        render_market(selected_code)

    with tab_rules:
        render_rules(monthly_df, quarterly_df, static_df)

    with tab_val:
        snapshot_data = load_market_snapshot(_MARKET_SNAPSHOT_PATH)
        shares_data = load_fund_shares(_FUND_SHARES_PATH)
        render_valuation(quarterly_df, completion_df, snapshot_data, shares_data, static_df)


if __name__ == "__main__":
    main()
