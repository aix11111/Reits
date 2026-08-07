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
from src.data_loader import (
    load_all,
    load_fund_shares,
    load_hk_annual,
    load_hk_funds,
    load_hk_snapshot,
    load_market_completion,
    load_market_funds,
    load_market_ops_energy,
    load_market_ops_environment,
    load_market_ops_rental,
    load_market_quarterly,
    load_market_shares,
    load_market_snapshot,
    load_sg_annual,
    load_sg_funds,
    load_sg_snapshot,
)
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
    hk_distribution_yield,
    hk_nav_premium,
    nav_premium,
    npi_margin,
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

# 全市场季度经营明细展示列（Phase 5 market_quarterly 数据；列有则显示）
_MARKET_QUARTERLY_COLUMNS = [
    ("period", "报告期"),
    ("revenue_wan", "总收入"),
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

# 全市场数据文件路径（M4：看板全市场视图）
_MARKET_FUNDS_PATH = Path(__file__).parent / "data" / "market_funds.json"
_MARKET_QUARTERLY_PATH = Path(__file__).parent / "data" / "market_quarterly.json"
_MARKET_COMPLETION_PATH = Path(__file__).parent / "data" / "market_completion.json"
_MARKET_SHARES_PATH = Path(__file__).parent / "data" / "market_shares.json"
_MARKET_OPS_RENTAL_PATH = Path(__file__).parent / "data" / "market_ops_rental.json"
_MARKET_OPS_ENERGY_PATH = Path(__file__).parent / "data" / "market_ops_energy.json"
_MARKET_OPS_ENV_PATH = Path(__file__).parent / "data" / "market_ops_environment.json"

# 香港数据文件路径（HK 模块 PoC：领展）
_HK_FUNDS_PATH = Path(__file__).parent / "data" / "hk_funds.json"
_HK_ANNUAL_PATH = Path(__file__).parent / "data" / "hk_annual.json"
_HK_MARKET_SNAPSHOT_PATH = Path(__file__).parent / "data" / "hk_market_snapshot.json"

# 新加坡数据文件路径（SG 模块：凯德综合商业信托 C38U）
_SG_FUNDS_PATH = Path(__file__).parent / "data" / "sg_funds.json"
_SG_ANNUAL_PATH = Path(__file__).parent / "data" / "sg_annual.json"
_SG_MARKET_SNAPSHOT_PATH = Path(__file__).parent / "data" / "sg_market_snapshot.json"

# 市场维度：侧边栏「市场」选择（中国为默认，渲染路径零变化）
_MARKET_OPTIONS = ["中国", "香港", "新加坡"]

# 资产类型枚举（与 data/market_funds.json 的 asset_type 对齐）
_ASSET_TYPES = [
    "高速",
    "产业园",
    "仓储物流",
    "能源",
    "生态环保",
    "保障房",
    "消费",
    "商业不动产",
]
_ASSET_TYPE_OPTIONS = ["全部"] + _ASSET_TYPES

# 产权类（非特许经营）资产类型：IRR 列显示「不适用（产权类）」
_PROPERTY_ASSET_TYPES = {"产业园", "仓储物流", "保障房", "消费", "商业不动产"}

# 资产类型 → 条形图着色（plotly 离散色板 Dark24 子集，深色底可读）
_ASSET_TYPE_COLORS = {
    "高速": "#8dd3c7",
    "产业园": "#fb8072",
    "仓储物流": "#80b1d3",
    "能源": "#fdb462",
    "生态环保": "#b3de69",
    "保障房": "#fccde5",
    "消费": "#bc80bd",
    "商业不动产": "#ffed6f",
}

# 估值对标页签：收益率排名展示列
_VALUATION_RANK_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("asset_type", "资产类型"),
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

# 估值对标页签（香港）：分派收益率排名展示列
_HK_VALUATION_RANK_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("yield_pct", "分派收益率"),
    ("fiscal_year", "财年"),
]

# 估值对标页签（香港）：P/NAV 折溢价展示列
_HK_VALUATION_PREMIUM_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("price", "市价(港元)"),
    ("nav_unit_price", "单位NAV(港元)"),
    ("premium_pct", "折溢价"),
]

# 估值对标页签（新加坡）：分派收益率排名展示列（复用香港列定义）
_SG_VALUATION_RANK_COLUMNS = _HK_VALUATION_RANK_COLUMNS

# 估值对标页签（新加坡）：P/NAV 折溢价展示列
_SG_VALUATION_PREMIUM_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("price", "市价(SGD)"),
    ("nav_unit_price", "单位NAV(SGD)"),
    ("premium_pct", "折溢价"),
]

# 估值对标页签（新加坡）：NPI 利润率排名展示列
_SG_NPI_MARGIN_COLUMNS = [
    ("code", "基金代码"),
    ("name", "基金简称"),
    ("npi_margin_pct", "NPI利润率"),
    ("fiscal_year", "财年"),
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


def _fmt_wan(v) -> str:
    """万港元数值格式化：None/NaN → "—"，否则千分位整数。"""
    if pd.isna(v):
        return "—"
    return f"{v:,.0f}"


def _fmt_num(v) -> str:
    """通用数值格式化：None/NaN → "—"，否则保留两位小数。"""
    if pd.isna(v):
        return "—"
    return f"{v:,.2f}"


def _hk_occupancy_pct(occupancy):
    """从 HK 年报 occupancy 字典取综合出租率小数；缺失/空 → None。"""
    if not isinstance(occupancy, dict) or not occupancy:
        return None
    return next(iter(occupancy.values()))


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


def _render_rental_ops(rental_df):
    """租赁类运营指标区块：出租率/平均租金/收缴率/剩余租期 KPI 卡 + 出租率趋势图。

    数据来自 data/market_ops_rental.json（租赁类季报 4.1.2/4.1.3 节）。
    KPI 取最新报告期；趋势图按报告期升序画出租率折线（plotly 深色）。
    平均租金卡按 rent_unit 标注单位口径（元/㎡/月 / 元/㎡/天），无单位时
    保持默认「元/平/天」。
    """
    latest = rental_df.sort_values("period").iloc[-1]

    def fmt(v, render):
        if pd.isna(v):
            return "—"
        return render(v)

    rent_unit_labels = {
        "yuan_per_sqm_day": "元/㎡/天",
        "yuan_per_sqm_month": "元/㎡/月",
    }
    rent_note = rent_unit_labels.get(latest.get("rent_unit"), "元/平/天")

    cards = "".join(
        [
            _kpi_card(
                "出租率",
                fmt(latest["occupancy_pct"], lambda v: f"{v:.2f}%"),
                f"报告期 {latest['period']}",
            ),
            _kpi_card(
                "平均租金",
                fmt(latest["avg_rent_yuan"], lambda v: f"{v:.2f}"),
                rent_note,
            ),
            _kpi_card(
                "租金收缴率",
                fmt(latest["collection_pct"], lambda v: f"{v:.2f}%"),
                "期末",
            ),
            _kpi_card(
                "剩余租期",
                fmt(latest["remaining_lease_days"], lambda v: f"{v:,.0f}"),
                "天",
            ),
        ]
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'
        'margin:8px 0 16px;">' + cards + "</div>",
        unsafe_allow_html=True,
    )

    chart_df = rental_df.sort_values("period")
    if chart_df["occupancy_pct"].notna().any():
        fig = go.Figure(
            go.Scatter(
                x=chart_df["period"],
                y=chart_df["occupancy_pct"],
                mode="lines+markers",
                line=dict(color=_ACCENT, width=2),
                marker=dict(color=_ACCENT),
            )
        )
        fig.update_layout(
            title="出租率趋势",
            xaxis_title="报告期",
            yaxis_title="出租率（%）",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig, width="stretch")


def _render_energy_ops(energy_df):
    """能源类运营指标区块：发电量/利用小时/结算电量/结算电价 KPI 卡 + 发电量趋势图。

    数据来自 data/market_ops_energy.json（能源类季报 4.1.3 节）。
    KPI 取最新报告期；趋势图按报告期升序画出 发电量 折线（plotly 深色）。
    """
    latest = energy_df.sort_values("period").iloc[-1]

    def fmt(v, render):
        if pd.isna(v):
            return "—"
        return render(v)

    cards = "".join(
        [
            _kpi_card(
                "发电量",
                fmt(latest["generation_wan_kwh"], lambda v: f"{v:,.2f}"),
                f"报告期 {latest['period']}",
            ),
            _kpi_card(
                "等效利用小时",
                fmt(latest["utilization_hours"], lambda v: f"{v:.0f}"),
                "小时",
            ),
            _kpi_card(
                "结算电量",
                fmt(latest["grid_wan_kwh"], lambda v: f"{v:,.2f}"),
                "万千瓦时",
            ),
            _kpi_card(
                "结算电价",
                fmt(latest["price_yuan_kwh"], lambda v: f"{v:.4f}"),
                "元/千瓦时",
            ),
        ]
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'
        'margin:8px 0 16px;">' + cards + "</div>",
        unsafe_allow_html=True,
    )

    chart_df = energy_df.sort_values("period")
    if chart_df["generation_wan_kwh"].notna().any():
        fig = go.Figure(
            go.Scatter(
                x=chart_df["period"],
                y=chart_df["generation_wan_kwh"],
                mode="lines+markers",
                line=dict(color=_ACCENT, width=2),
                marker=dict(color=_ACCENT),
            )
        )
        fig.update_layout(
            title="发电量趋势",
            xaxis_title="报告期",
            yaxis_title="发电量（万千瓦时）",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig, width="stretch")


def _render_env_ops(env_df):
    """生态环保类运营指标区块：处理量/产能利用率/服务费单价 KPI 卡 + 处理量趋势图。

    数据来自 data/market_ops_environment.json（生态环保类季报 4.1.3 节）。
    KPI 取最新报告期；趋势图按报告期升序画出 处理量 折线（plotly 深色）。
    多项目表时取第一个项目值，KPI 卡注明「第一项目」。
    """
    latest = env_df.sort_values("period").iloc[-1]

    def fmt(v, render):
        if pd.isna(v):
            return "—"
        return render(v)

    cards = "".join(
        [
            _kpi_card(
                "处理量",
                fmt(latest["volume_wan_ton"], lambda v: f"{v:,.2f}"),
                f"报告期 {latest['period']}（第一项目）",
            ),
            _kpi_card(
                "产能利用率",
                fmt(latest["capacity_utilization_pct"], lambda v: f"{v:.2f}%"),
                "实际处理量/设计产能",
            ),
            _kpi_card(
                "服务费单价",
                fmt(latest["unit_price_yuan"], lambda v: f"{v:.4f}"),
                "元/吨",
            ),
        ]
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;'
        'margin:8px 0 16px;">' + cards + "</div>",
        unsafe_allow_html=True,
    )

    chart_df = env_df.sort_values("period")
    if chart_df["volume_wan_ton"].notna().any():
        fig = go.Figure(
            go.Scatter(
                x=chart_df["period"],
                y=chart_df["volume_wan_ton"],
                mode="lines+markers",
                line=dict(color=_ACCENT, width=2),
                marker=dict(color=_ACCENT),
            )
        )
        fig.update_layout(
            title="处理量趋势",
            xaxis_title="报告期",
            yaxis_title="处理量（万吨）",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig, width="stretch")


def render_operations(code, name, monthly_df, quarterly_df, rental_df=None,
                      energy_df=None, env_df=None, nav_wan=None,
                      fund_asset_type="高速", market_quarterly=None):
    """经营数据页签：最新指标 KPI、月度图表与季度明细表。

    选中基金有租赁类运营指标（data/market_ops_rental.json）时，在 KPI 区下方
    追加出租率 KPI 卡与出租率趋势图；有能源类运营指标
    （data/market_ops_energy.json）时追加发电量 KPI 卡与发电量趋势图；
    有生态环保类运营指标（data/market_ops_environment.json）时追加处理量
    KPI 卡与处理量趋势图；均无数据（其他类）保持原视图不变。

    nav_wan：该基金最新年报净值（万元），用于年化可供分配收益率
    （不再依赖季度 Sheet 的 nav_wan 列）；缺失基金该 KPI 显示「—」。

    fund_asset_type：选中基金的资产类型（8 类）。高速基金保持现状（月度+
    季度+KPI）；非高速基金在月度区块如实提示「该资产类型暂无月度披露」，
    仅渲染季度数据表（Phase 5 market_quarterly 数据，列有则显示）；
    该基金无季度数据时降级 st.info「该资产类型暂无数据」。
    """
    st.subheader(f"基金：{code} {name}")

    if fund_asset_type == "高速":
        metrics = latest_metrics(quarterly_df, code, nav_wan=nav_wan)
        if metrics:
            cards = "".join(
                [
                    _kpi_card("最新季度", str(metrics["period"]), "报告期"),
                    _kpi_card("NOI利润率", _fmt_pct(metrics["noi_margin"]),
                              "(营业总收入-营业成本)/营业总收入"),
                    _kpi_card("净利润率", _fmt_pct(metrics["net_margin"]), "净利润/营业总收入"),
                    _kpi_card("年化可供分配收益率", _fmt_pct(metrics["distributable_yield"]),
                              "可供分配×4/NAV（年化，年报净值）"),
                ]
            )
            st.markdown(
                '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'
                'margin:8px 0 16px;">' + cards + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.warning("暂无季度数据，无法计算经营指标。")

    if rental_df is not None and not rental_df.empty:
        rental = rental_df[rental_df["code"] == code]
        if not rental.empty:
            st.markdown("### 租赁运营指标（出租率）")
            _render_rental_ops(rental)

    if energy_df is not None and not energy_df.empty:
        energy = energy_df[energy_df["code"] == code]
        if not energy.empty:
            st.markdown("### 能源运营指标（发电量）")
            _render_energy_ops(energy)

    if env_df is not None and not env_df.empty:
        env = env_df[env_df["code"] == code]
        if not env.empty:
            st.markdown("### 生态环保运营指标（处理量）")
            _render_env_ops(env)

    if fund_asset_type == "高速":
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
    else:
        # 非高速基金：月度区块如实提示「该资产类型暂无月度披露」，随后仅渲染季度表
        st.info("该资产类型暂无月度披露")
        if market_quarterly is not None and not market_quarterly.empty:
            mq = market_quarterly[market_quarterly["code"] == code]
        else:
            mq = pd.DataFrame()
        if not mq.empty:
            st.subheader("季度经营明细")
            display = mq.sort_values("period", ascending=False).copy()
            cols = [
                (src, label)
                for src, label in _MARKET_QUARTERLY_COLUMNS
                if src in display.columns
            ]
            display = display.rename(columns=dict(cols))
            st.dataframe(
                display[[label for _, label in cols]],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("该资产类型暂无数据")


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


def _nav_map_from_completion(completion_df) -> dict:
    """从年报完成度 DataFrame 提取每基金最新（含净值披露的）年报 nav_wan。

    返回 {code: nav_wan}；无净值记录的行被跳过。年化可供分配收益率的
    NAV 数据源：14 只高速读 annual_completion.json，全市场其余基金读
    market_completion.json，缺失基金保留「—」。
    """
    nav = {}
    if completion_df is None or completion_df.empty or "nav_wan" not in completion_df:
        return nav
    for code, sub in completion_df.groupby("code"):
        valid = sub[sub["nav_wan"].notna()]
        if valid.empty:
            continue
        latest = valid.sort_values("year").iloc[-1]
        nav[str(code)] = float(latest["nav_wan"])
    return nav


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


def render_status_wall(static_df, completion_df, market_funds=None,
                       market_completion=None, asset_type="全部"):
    """签名元素 1：行业状态墙——title 下方一行基金完成度色点带。

    每只基金 = 圆点 12px + 4 位代码 10px 三级灰小字（flex 一行）。
    状态取每基金最新年份 completion_pct：>=100 达标绿、>=80 警告橙、<80
    风险红、无记录灰。title 属性携带「{code} {name}：完成率 {pct}%（{year}）」。
    空数据降级为 st.info。

    跟随 asset_type 联动：选中具体非高速类型时，色点带取该类型基金
    （market_funds 过滤），完成度取全市场完成度记录（market_completion）；
    无完成度记录的基金为灰点。「全部」/「高速」保持现状（14 只静态 +
    annual_completion）。market_funds 缺失时非高速类型如实提示
    「暂无基金数据」（不静默回退 14 只高速）。"""
    if asset_type not in ("全部", "高速"):
        if market_funds is not None and not market_funds.empty:
            funds = market_funds[market_funds["asset_type"] == asset_type]
            completion = market_completion
            if funds.empty:
                st.info(f"资产类型「{asset_type}」暂无基金数据。")
                return
        else:
            st.info(f"资产类型「{asset_type}」暂无基金数据。")
            return
    else:
        funds = static_df
        completion = completion_df

    if completion is None or completion.empty:
        st.info("暂无年度可供分配完成度数据，行业状态墙跳过。")
        return

    latest = distributable_completion(completion).sort_values("year")
    latest = latest.groupby("code").tail(1)
    by_code = {str(r.code): r for r in latest.itertuples(index=False)}

    dots = []
    for _, fund in funds.iterrows():
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


def render_valuation(quarterly_df, completion_df, snapshot_data, shares, static_df,
                     market_funds=None, market_quarterly=None, market_completion=None,
                     market_shares=None, asset_type="全部", market_ops_energy=None):
    """估值对标页签：分派率收益率排名、NAV 折溢价与风险聚合提示。

    市值数据来自本地快照（market_snapshot.json），不依赖运行时网络。
    全市场模式（market_funds 非空）：排名/折溢价/风险用全市场 JSON 数据，
    并按「资产类型」筛选；market JSON 缺失时回退现有 14 只高速视图。
    快照缺失时降级为 st.info + 仅显示 TTM 分派表。
    剩余年限口径：高速用静态表 concession_years_left；能源类用
    market_ops_energy 的 ops_until_year（最新报告期，基准年 2026 约算）；
    产权类 IRR 不适用。
    """
    st.subheader("估值对标")
    st.caption(
        "分派率收益率=TTM 可供分配（近4季）/最新市值；NAV 折溢价=市价/最新年报单位净值-1。"
    )

    snapshot_latest = snapshot_data.get("latest") or {}
    years_left = static_df.set_index("code")["concession_years_left"]

    # 能源类剩余年限：market_ops_energy 最新报告期的 ops_until_year，
    # 基准年 2026 约算（years_left = ops_until_year − 2026）
    _ENERGY_BASE_YEAR = 2026
    energy_left = {}
    if market_ops_energy is not None and not market_ops_energy.empty:
        for ecode, sub in market_ops_energy.groupby("code"):
            latest = sub.sort_values("period").iloc[-1]
            until = latest.get("ops_until_year")
            if pd.notna(until):
                energy_left[str(ecode)] = int(until) - _ENERGY_BASE_YEAR

    full_market = market_funds is not None and not market_funds.empty
    if full_market:
        funds = market_funds
        if asset_type != "全部":
            funds = funds[funds["asset_type"] == asset_type]
        if funds.empty:
            st.info(f"资产类型「{asset_type}」暂无基金数据。")
            return
        active_codes = set(funds["code"])
        snapshot_latest = {
            c: i for c, i in snapshot_latest.items() if c in active_codes
        }
        name_map = dict(zip(funds["code"], funds["name"]))
        asset_type_map = dict(zip(funds["code"], funds["asset_type"]))
        shares_map = market_shares or {}
        ttm = (
            ttm_distributable(market_quarterly)
            if market_quarterly is not None and not market_quarterly.empty
            else pd.DataFrame(columns=["dist_ttm_wan", "is_annualized"])
        )
        if market_completion is not None and not market_completion.empty:
            completion_df = market_completion
    else:
        name_map = dict(zip(static_df["code"], static_df["name"]))
        asset_type_map = dict(zip(static_df["code"], static_df["asset_type"]))
        shares_map = shares.get("shares") or {}
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
        a_type = asset_type_map.get(code, "")
        if a_type == "能源" and code in energy_left:
            left = energy_left[code]
        if a_type in _PROPERTY_ASSET_TYPES:
            irr = None
            irr_label = "不适用（产权类）"
        elif pd.notna(annual) and pd.notna(left):
            irr = concession_irr(info["price"], shares_map.get(code), annual, left)
            irr_label = _fmt_pct(irr) if irr is not None else "—"
        else:
            irr = None
            irr_label = "—"
        rank_rows.append(
            {
                "code": code,
                "name": name_map.get(code, ""),
                "asset_type": a_type,
                "yield": yield_series.get(code, float("nan")),
                "is_annualized": (
                    ttm.loc[code, "is_annualized"] if code in ttm.index else None
                ),
                "years_left": left,
                "irr": irr,
                "irr_label": irr_label,
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
                marker_color=[
                    _ASSET_TYPE_COLORS.get(t, _ACCENT) for t in chart["asset_type"]
                ],
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
    display["irr_pct"] = display["irr_label"]
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


_PERIOD_LABELS = {"annual": "年度", "interim": "中期"}


def _hk_annual_rec(records):
    """估值对标用年度记录：仅取 period="annual"（DPU 全年口径；
    interim 半年 DPU 混入会虚高）。"""
    if not records:
        return None
    for rec in records:
        if rec.get("period") == "annual":
            return rec
    return None


def _hk_latest_rec(records):
    """最新报告：interim 优先（更新鲜），否则取列表最后一条。"""
    for rec in records:
        if rec.get("period") == "interim":
            return rec
    return records[-1]


def render_hk_operations(code, name, annual_data):
    """经营数据页签（香港）：HK 指标 KPI 卡 + 财务摘要表，无月度区块。

    数据来自 data/hk_annual.json（annual + interim 多期记录）。KPI 卡显示
    最新报告（interim 优先），财务摘要表列出该基金全部记录并标注「年度/中期」
    报告类型列；无数据时降级 st.info。港 REITs 无月度披露，不渲染月度图表区块。
    """
    st.subheader(f"基金：{code} {name}")
    records = annual_data.get(code) or []
    if not records:
        st.info("香港数据缺失")
        return

    rec = _hk_latest_rec(records)
    occupancy = _hk_occupancy_pct(rec.get("occupancy"))
    cards = "".join(
        [
            _kpi_card("财务年", str(rec.get("fiscal_year", "—")), "报告期"),
            _kpi_card("Revenue", _fmt_wan(rec.get("revenue_wan")), "万港元"),
            _kpi_card("NPI", _fmt_wan(rec.get("npi_wan")), "万港元"),
            _kpi_card("DPU", _fmt_num(rec.get("dpu_hk_cents")), "港仙"),
            _kpi_card("NAV", _fmt_num(rec.get("nav_per_unit_hkd")), "港元/单位"),
            _kpi_card(
                "出租率",
                f"{occupancy * 100:.1f}%" if occupancy is not None else "—",
                "综合出租率",
            ),
        ]
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;'
        'margin:8px 0 16px;">' + cards + "</div>",
        unsafe_allow_html=True,
    )

    rows = []
    for rec in records:
        occ = _hk_occupancy_pct(rec.get("occupancy"))
        rows.append(
            {
                "报告类型": _PERIOD_LABELS.get(rec.get("period"), rec.get("period")),
                "财务年": rec.get("fiscal_year"),
                "Revenue(万港元)": rec.get("revenue_wan"),
                "NPI(万港元)": rec.get("npi_wan"),
                "DPU(港仙)": rec.get("dpu_hk_cents"),
                "NAV(港元/单位)": rec.get("nav_per_unit_hkd"),
                "出租率(%)": (
                    f"{occ * 100:.1f}" if occ is not None else None
                ),
            }
        )
    st.subheader("财务摘要")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_hk_market(code, snapshot_latest):
    """行情走势页签（香港）：港股价格快照文本；快照缺失降级 st.info。"""
    st.subheader("行情走势")
    price = snapshot_latest.get(code)
    if price is None:
        st.info("香港数据缺失")
        return
    st.markdown(f"**{code} 最新收盘价：{price:.2f} 港元**")
    st.caption("行情快照来自 data/hk_market_snapshot.json（新浪日线）。")


def render_hk_rules():
    """分析规则页签（香港）：模块建设中占位提示，不崩。"""
    st.subheader("分析规则引擎")
    st.info("香港模块分析规则建设中")


def render_hk_valuation(funds_map, annual_data, snapshot_latest):
    """估值对标页签（香港）：分派收益率排名 + P/NAV 折溢价表。

    分派收益率 = hk_distribution_yield(DPU, 市价)，DPU 或市价缺失 → 该行「—」；
    少于 3 只有效收益率时降级 st.info「香港分派数据不足」。P/NAV 折溢价 =
    hk_nav_premium(市价, NAV)，NAV 缺失 → 「—」；语义色复用中国版
    _premium_color（溢价红 / 折价绿）。行情快照缺失降级 st.info（沿用现有）。
    """
    st.subheader("估值对标")
    st.caption(
        "分派收益率=DPU/市价；P/NAV 折溢价=市价/NAV-1（溢价红、折价绿）。"
    )
    if not snapshot_latest:
        st.info("香港数据缺失")
        return

    # ---- 1. 分派收益率排名 ----
    st.markdown("### 1. 分派收益率排名")
    rank_rows = []
    for code, name in funds_map.items():
        rec = _hk_annual_rec(annual_data.get(code))
        price = snapshot_latest.get(code)
        if rec is None or price is None:
            continue
        rank_rows.append(
            {
                "code": code,
                "name": name,
                "yield": hk_distribution_yield(rec.get("dpu_hk_cents"), price),
                "fiscal_year": rec.get("fiscal_year"),
            }
        )
    rank = pd.DataFrame(rank_rows)

    valid = rank[rank["yield"].notna()]
    if len(valid) < 3:
        st.info("香港分派数据不足")
        return

    chart = valid.sort_values("yield", ascending=True)
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
        annotation_text="中位数",
        annotation_font_color=_TEXT_TERTIARY,
    )
    fig.update_layout(
        title="分派收益率排名",
        xaxis_title="分派收益率",
        xaxis_tickformat=".0%",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
    )
    st.plotly_chart(fig, width="stretch")

    display = rank.sort_values("yield", ascending=False, na_position="last").copy()
    display["yield_pct"] = display["yield"].map(_fmt_pct)
    display = display.rename(columns=dict(_HK_VALUATION_RANK_COLUMNS))
    st.dataframe(
        display[[label for _, label in _HK_VALUATION_RANK_COLUMNS]],
        hide_index=True,
        width="stretch",
    )

    # ---- 2. P/NAV 折溢价 ----
    st.markdown("### 2. P/NAV 折溢价（最新年报单位净值）")
    prem_rows = []
    for code, name in funds_map.items():
        rec = _hk_annual_rec(annual_data.get(code))
        price = snapshot_latest.get(code)
        nav = rec.get("nav_per_unit_hkd") if rec is not None else None
        prem_rows.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "nav_unit_price": nav,
                "premium_pct": hk_nav_premium(price, nav),
            }
        )
    prem_df = pd.DataFrame(prem_rows)
    prem_display = prem_df.rename(columns=dict(_HK_VALUATION_PREMIUM_COLUMNS))
    styled = prem_display.style.map(_premium_color, subset=["折溢价"]).format(
        {"市价(港元)": "{:.3f}", "单位NAV(港元)": "{:.4f}", "折溢价": _fmt_pct},
        na_rep="—",
    )
    st.dataframe(styled, hide_index=True, width="stretch")


def render_hk_status_wall(funds_map):
    """状态墙（香港）：香港基金色点带，暂无完成度记录全部为灰点。"""
    if not funds_map:
        return
    dots = []
    for code, name in funds_map.items():
        dots.append(
            f'<div title="{code} {name}：暂无完成度数据" '
            f'style="display:flex;align-items:center;gap:6px;cursor:default;">'
            f'<span class="reit-dot" style="width:12px;height:12px;border-radius:50%;'
            f'background-color:{_NO_RECORD_GRAY};display:inline-block;flex:none;"></span>'
            f'<span style="font-family:\'JetBrains Mono\',ui-monospace,monospace;'
            f'font-size:10px;color:#8A8F98;">{code[-4:]}</span>'
            "</div>"
        )
    st.markdown(
        '<div class="reit-status-wall" style="display:flex;flex-wrap:wrap;'
        'align-items:center;gap:12px 18px;padding:16px;'
        'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
        'border-radius:8px;margin:8px 0 16px;">' + "".join(dots) + "</div>",
        unsafe_allow_html=True,
    )


def _sg_occupancy_pct(occupancy):
    """从 SG 年报 occupancy 取综合出租率小数；支持 float/dict 两种形态，缺失 → None。"""
    if isinstance(occupancy, dict):
        return next(iter(occupancy.values())) if occupancy else None
    if isinstance(occupancy, (int, float)):
        return float(occupancy)
    return None


def render_sg_operations(code, name, annual_data):
    """经营数据页签（新加坡）：SG 指标 KPI 卡 + 财务摘要表，无月度区块。

    数据来自 data/sg_annual.json（annual 多期记录，币种 SGD）。KPI 卡显示
    最新报告，财务摘要表列出该基金全部记录并标注「报告期」列；无数据时
    降级 st.info「新加坡数据缺失」。新 REITs 无月度披露，不渲染月度图表区块。
    """
    st.subheader(f"基金：{code} {name}")
    records = annual_data.get(code) or []
    if not records:
        st.info("新加坡数据缺失")
        return

    rec = _hk_latest_rec(records)
    occupancy = _sg_occupancy_pct(rec.get("occupancy"))
    cards = "".join(
        [
            _kpi_card("FY", str(rec.get("fiscal_year", "—")), "报告期"),
            _kpi_card("Revenue", _fmt_wan(rec.get("revenue_wan")), "万SGD"),
            _kpi_card("NPI", _fmt_wan(rec.get("npi_wan")), "万SGD"),
            _kpi_card(
                "Distributable Income", _fmt_wan(rec.get("distributable_wan")), "万SGD"
            ),
            _kpi_card("DPU", _fmt_num(rec.get("dpu_cents")), "SGD分"),
            _kpi_card("NAV", _fmt_num(rec.get("nav_per_unit")), "SGD/单位"),
            _kpi_card(
                "出租率",
                f"{occupancy * 100:.1f}%" if occupancy is not None else "—",
                "综合出租率",
            ),
        ]
    )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'
        'margin:8px 0 16px;">' + cards + "</div>",
        unsafe_allow_html=True,
    )

    rows = []
    for rec in records:
        occ = _sg_occupancy_pct(rec.get("occupancy"))
        rows.append(
            {
                "报告期": _PERIOD_LABELS.get(rec.get("period"), rec.get("period")),
                "财务年": rec.get("fiscal_year"),
                "Revenue": rec.get("revenue_wan"),
                "NPI": rec.get("npi_wan"),
                "Distributable Income": rec.get("distributable_wan"),
                "DPU": rec.get("dpu_cents"),
                "NAV": rec.get("nav_per_unit"),
                "出租率(%)": (
                    f"{occ * 100:.1f}" if occ is not None else None
                ),
            }
        )
    st.subheader("财务摘要")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_sg_market(code, snapshot_latest):
    """行情走势页签（新加坡）：SG 价格快照文本；快照缺失降级 st.info。"""
    st.subheader("行情走势")
    price = snapshot_latest.get(code)
    if price is None:
        st.info("新加坡数据缺失")
        return
    st.markdown(f"**{code} 最新收盘价：{price:.2f} SGD**")
    st.caption("行情快照来自 data/sg_market_snapshot.json（Yahoo 日线）。")


def render_sg_rules():
    """分析规则页签（新加坡）：模块建设中占位提示，不崩。"""
    st.subheader("分析规则引擎")
    st.info("新加坡模块分析规则建设中")


def render_sg_valuation(funds_map, annual_data, snapshot_latest):
    """估值对标页签（新加坡）：分派收益率排名 + P/NAV 折溢价 + NPI 利润率排名。

    分派收益率 = hk_distribution_yield(DPU, 市价)（同币种 SGD 直接算），DPU 或
    市价缺失 → 该行「—」；P/NAV 折溢价 = hk_nav_premium(市价, NAV)，NAV 缺失
    →「—」，语义色复用中国版 _premium_color（溢价红 / 折价绿）。NPI 利润率 =
    npi_margin(NPI, Revenue)。行情快照缺失降级 st.info「新加坡数据缺失」。
    """
    st.subheader("估值对标")
    st.caption(
        "分派收益率=DPU/市价；P/NAV 折溢价=市价/NAV-1（溢价红、折价绿）；"
        "NPI 利润率=NPI/Revenue。"
    )
    if not snapshot_latest:
        st.info("新加坡数据缺失")
        return

    # ---- 1. 分派收益率排名 ----
    st.markdown("### 1. 分派收益率排名")
    rank_rows = []
    for code, name in funds_map.items():
        rec = _hk_annual_rec(annual_data.get(code))
        price = snapshot_latest.get(code)
        if rec is None or price is None:
            continue
        rank_rows.append(
            {
                "code": code,
                "name": name,
                "yield": hk_distribution_yield(rec.get("dpu_cents"), price),
                "fiscal_year": rec.get("fiscal_year"),
            }
        )
    rank = pd.DataFrame(rank_rows)

    valid = rank[rank["yield"].notna()]
    if not valid.empty:
        chart = valid.sort_values("yield", ascending=True)
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
            annotation_text="中位数",
            annotation_font_color=_TEXT_TERTIARY,
        )
        fig.update_layout(
            title="分派收益率排名",
            xaxis_title="分派收益率",
            xaxis_tickformat=".0%",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Microsoft YaHei, SimHei, sans-serif", color=_TEXT_SECONDARY),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
        )
        st.plotly_chart(fig, width="stretch")

    display = rank.sort_values("yield", ascending=False, na_position="last").copy()
    display["yield_pct"] = display["yield"].map(_fmt_pct)
    display = display.rename(columns=dict(_SG_VALUATION_RANK_COLUMNS))
    st.dataframe(
        display[[label for _, label in _SG_VALUATION_RANK_COLUMNS]],
        hide_index=True,
        width="stretch",
    )

    # ---- 2. P/NAV 折溢价 ----
    st.markdown("### 2. P/NAV 折溢价（最新年报单位净值）")
    prem_rows = []
    for code, name in funds_map.items():
        rec = _hk_annual_rec(annual_data.get(code))
        price = snapshot_latest.get(code)
        nav = rec.get("nav_per_unit") if rec is not None else None
        prem_rows.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "nav_unit_price": nav,
                "premium_pct": hk_nav_premium(price, nav),
            }
        )
    prem_df = pd.DataFrame(prem_rows)
    prem_display = prem_df.rename(columns=dict(_SG_VALUATION_PREMIUM_COLUMNS))
    styled = prem_display.style.map(_premium_color, subset=["折溢价"]).format(
        {"市价(SGD)": "{:.3f}", "单位NAV(SGD)": "{:.4f}", "折溢价": _fmt_pct},
        na_rep="—",
    )
    st.dataframe(styled, hide_index=True, width="stretch")

    # ---- 3. NPI 利润率排名 ----
    st.markdown("### 3. NPI 利润率排名")
    npi_rows = []
    for code, name in funds_map.items():
        rec = _hk_annual_rec(annual_data.get(code))
        if rec is None:
            continue
        npi_rows.append(
            {
                "code": code,
                "name": name,
                "npi_margin": npi_margin(
                    rec.get("npi_wan"), rec.get("revenue_wan")
                ),
                "fiscal_year": rec.get("fiscal_year"),
            }
        )
    npi_df = pd.DataFrame(npi_rows)
    npi_display = (
        npi_df.sort_values("npi_margin", ascending=False, na_position="last")
        .copy()
    )
    npi_display["npi_margin_pct"] = npi_display["npi_margin"].map(_fmt_pct)
    npi_display = npi_display.rename(columns=dict(_SG_NPI_MARGIN_COLUMNS))
    st.dataframe(
        npi_display[[label for _, label in _SG_NPI_MARGIN_COLUMNS]],
        hide_index=True,
        width="stretch",
    )


def render_sg_status_wall(funds_map):
    """状态墙（新加坡）：SG 基金色点带，暂无完成度记录全部为灰点。"""
    if not funds_map:
        return
    dots = []
    for code, name in funds_map.items():
        dots.append(
            f'<div title="{code} {name}：暂无完成度数据" '
            f'style="display:flex;align-items:center;gap:6px;cursor:default;">'
            f'<span class="reit-dot" style="width:12px;height:12px;border-radius:50%;'
            f'background-color:{_NO_RECORD_GRAY};display:inline-block;flex:none;"></span>'
            f'<span style="font-family:\'JetBrains Mono\',ui-monospace,monospace;'
            f'font-size:10px;color:#8A8F98;">{code[-4:]}</span>'
            "</div>"
        )
    st.markdown(
        '<div class="reit-status-wall" style="display:flex;flex-wrap:wrap;'
        'align-items:center;gap:12px 18px;padding:16px;'
        'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
        'border-radius:8px;margin:8px 0 16px;">' + "".join(dots) + "</div>",
        unsafe_allow_html=True,
    )


def main():
    """看板主流程：加载数据、渲染侧边栏选择器与四个页签。"""
    st.set_page_config(page_title="REITsMonitor", page_icon="📊", layout="wide")
    st.markdown(f"<style>{_GLOBAL_CSS}</style>", unsafe_allow_html=True)
    st.title("📊 REITsMonitor — 多市场REITs投后分析看板")
    st.caption(
        "中国市场：公募REITs（经营数据来自本地模板，行情来自 akshare）| "
        "香港市场：11 只 REITs（年报+中期报告解析 + 新浪日线快照）| "
        "新加坡市场：官网年报解析 + Yahoo 行情快照"
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

    # 全市场数据层（M4）：缺失时各 load_ 返回空结构，估值对标回退 14 只高速视图
    market_funds = load_market_funds(_MARKET_FUNDS_PATH)
    market_quarterly = load_market_quarterly(_MARKET_QUARTERLY_PATH)
    market_completion = load_market_completion(_MARKET_COMPLETION_PATH)
    market_shares = load_market_shares(_MARKET_SHARES_PATH)
    market_ops_rental = load_market_ops_rental(_MARKET_OPS_RENTAL_PATH)
    market_ops_energy = load_market_ops_energy(_MARKET_OPS_ENERGY_PATH)
    market_ops_env = load_market_ops_environment(_MARKET_OPS_ENV_PATH)

    # 年化可供分配收益率的 NAV 数据源：14 只高速读 annual_completion.json，
    # 其余基金用 market_completion.json 的年报净值补齐；缺失保留「—」。
    nav_map = _nav_map_from_completion(completion_df)
    for code, nav in _nav_map_from_completion(market_completion).items():
        nav_map.setdefault(code, nav)

    market_loaded = market_funds is not None and not market_funds.empty
    if market_loaded:
        fund_name_map = dict(zip(static_df["code"], static_df["name"]))
        fund_name_map.update(dict(zip(market_funds["code"], market_funds["name"])))
        asset_type_map = dict(zip(static_df["code"], static_df["asset_type"]))
        asset_type_map.update(dict(zip(market_funds["code"], market_funds["asset_type"])))
    else:
        # 降级：全市场基金清单缺失时，全部基金按高速处理（回退 14 只静态列表）
        fund_name_map = name_map
        asset_type_map = {code: "高速" for code in static_df["code"]}

    with st.sidebar:
        st.header("市场")
        market = st.selectbox("市场", options=_MARKET_OPTIONS, index=0)

        if market == "香港":
            # 香港模式：基金选择器 = HK 清单（data/hk_funds.json）；资产类型联动不适用
            hk_funds = load_hk_funds(_HK_FUNDS_PATH)
            st.header("选择REIT")
            if not hk_funds:
                st.info("香港数据缺失")
                hk_codes = []
            else:
                hk_codes = sorted(hk_funds.keys())
            selected_code = st.selectbox(
                "选择REIT",
                options=hk_codes,
                format_func=lambda code: f"{code} {hk_funds.get(code, '')}",
            )
            st.caption("行情快照来自 data/hk_market_snapshot.json（新浪日线）。")
        elif market == "新加坡":
            # 新加坡模式：基金选择器 = SG 清单（data/sg_funds.json）；资产类型联动不适用
            sg_funds = load_sg_funds(_SG_FUNDS_PATH)
            st.header("选择REIT")
            if not sg_funds:
                st.info("新加坡数据缺失")
                sg_codes = []
            else:
                sg_codes = sorted(sg_funds.keys())
            selected_code = st.selectbox(
                "选择REIT",
                options=sg_codes,
                format_func=lambda code: f"{code} {sg_funds.get(code, '')}",
            )
            st.caption("行情快照来自 data/sg_market_snapshot.json（Yahoo 日线）。")
        else:
            st.header("市场筛选")
            asset_type = st.selectbox(
                "资产类型",
                options=_ASSET_TYPE_OPTIONS,
                index=1,
                help="估值对标页签全市场视图按资产类型筛选",
            )

            st.header("选择REIT")
            # 联动：基金选择器 options 跟随资产类型。
            # 「全部」/「高速」保持现有 14 只高速静态列表（不从 market_funds 取）；
            # 其余类型从 market_funds 过滤。market_funds 缺失时非高速类型如实提示、
            # 选择器无可选项（不静默回退高速列表）。
            if asset_type in ("全部", "高速"):
                fund_codes = sorted(static_df["code"].tolist())
            elif not market_loaded:
                st.warning("全市场基金数据缺失（文件不存在或损坏），当前仅可浏览高速基金")
                fund_codes = []
            else:
                typed_funds = market_funds[market_funds["asset_type"] == asset_type]
                fund_codes = sorted(typed_funds["code"].tolist())
                if not fund_codes:
                    st.info("该资产类型暂无数据")

            selected_code = st.selectbox(
                "选择REIT",
                options=fund_codes,
                format_func=lambda code: f"{code} {fund_name_map.get(code, '')}",
            )
            st.caption("行情数据来自 akshare，网络异常时自动降级。")

    if market == "香港":
        hk_annual = load_hk_annual(_HK_ANNUAL_PATH)
        hk_snapshot = load_hk_snapshot(_HK_MARKET_SNAPSHOT_PATH)
        render_hk_status_wall(hk_funds)
    elif market == "新加坡":
        sg_annual = load_sg_annual(_SG_ANNUAL_PATH)
        sg_snapshot = load_sg_snapshot(_SG_MARKET_SNAPSHOT_PATH)
        render_sg_status_wall(sg_funds)
    else:
        render_status_wall(
            static_df,
            completion_df,
            market_funds=market_funds,
            market_completion=market_completion,
            asset_type=asset_type,
        )

    tab_ops, tab_mkt, tab_rules, tab_val = st.tabs(
        ["📈 经营数据", "📉 行情走势", "📐 分析规则", "📊 估值对标"]
    )

    if market == "香港":
        with tab_ops:
            render_hk_operations(
                selected_code,
                hk_funds.get(selected_code, ""),
                hk_annual,
            )

        with tab_mkt:
            render_hk_market(selected_code, hk_snapshot)

        with tab_rules:
            render_hk_rules()

        with tab_val:
            render_hk_valuation(
                hk_funds,
                hk_annual,
                hk_snapshot,
            )
    elif market == "新加坡":
        with tab_ops:
            render_sg_operations(
                selected_code,
                sg_funds.get(selected_code, ""),
                sg_annual,
            )

        with tab_mkt:
            render_sg_market(selected_code, sg_snapshot)

        with tab_rules:
            render_sg_rules()

        with tab_val:
            render_sg_valuation(
                sg_funds,
                sg_annual,
                sg_snapshot,
            )
    else:
        with tab_ops:
            render_operations(
                selected_code,
                fund_name_map.get(selected_code, ""),
                monthly_df,
                quarterly_df,
                rental_df=market_ops_rental,
                energy_df=market_ops_energy,
                env_df=market_ops_env,
                nav_wan=nav_map.get(selected_code),
                fund_asset_type=asset_type_map.get(selected_code, "高速"),
                market_quarterly=market_quarterly,
            )

        with tab_mkt:
            render_market(selected_code)

        with tab_rules:
            render_rules(monthly_df, quarterly_df, static_df)

        with tab_val:
            snapshot_data = load_market_snapshot(_MARKET_SNAPSHOT_PATH)
            shares_data = load_fund_shares(_FUND_SHARES_PATH)
            render_valuation(
                quarterly_df,
                completion_df,
                snapshot_data,
                shares_data,
                static_df,
                market_funds=market_funds,
                market_quarterly=market_quarterly,
                market_completion=market_completion,
                market_shares=market_shares,
                asset_type=asset_type,
                market_ops_energy=market_ops_energy,
            )


if __name__ == "__main__":
    main()
