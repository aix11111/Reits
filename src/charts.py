"""Plotly 图表构建器。

统一提供折线图与柱状图的构建入口，封装中文字体、plotly_dark
深色终端模板与标题配置，供上层分析页面直接调用。
"""

import pandas as pd
import plotly.graph_objects as go

FONT_FAMILY = "Microsoft YaHei, SimHei, sans-serif"

# 深色金融终端配色
TEXT_COLOR = "#D0D6E0"                # 轴/文本
GRID_COLOR = "rgba(255,255,255,0.06)"  # 网格线
MAIN_COLOR = "#2DD4BF"                # 主线/柱色
SECONDARY_COLOR = "#8A8F98"           # 次线
TRANSPARENT = "rgba(0,0,0,0)"


def _apply_common_layout(fig: go.Figure, title: str, y_label: str) -> go.Figure:
    """统一设置标题、y 轴标题、中文字体与深色终端模板。"""
    fig.update_layout(
        title=title,
        yaxis_title=y_label,
        template="plotly_dark",
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        font=dict(family=FONT_FAMILY, color=TEXT_COLOR),
        xaxis=dict(gridcolor=GRID_COLOR, tickfont=dict(color=SECONDARY_COLOR)),
        yaxis=dict(gridcolor=GRID_COLOR, tickfont=dict(color=SECONDARY_COLOR)),
    )
    return fig


def line_chart(
    df: pd.DataFrame, x_col: str, y_col: str, title: str, y_label: str
) -> go.Figure:
    """构建折线图（lines+markers）。"""
    fig = go.Figure(
        go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="lines+markers",
            line=dict(color=MAIN_COLOR, width=2),
            marker=dict(color=MAIN_COLOR, size=5),
        )
    )
    return _apply_common_layout(fig, title, y_label)


def bar_chart(
    df: pd.DataFrame, x_col: str, y_col: str, title: str, y_label: str
) -> go.Figure:
    """构建柱状图。"""
    fig = go.Figure(
        go.Bar(
            x=df[x_col],
            y=df[y_col],
            marker_color=MAIN_COLOR,
        )
    )
    return _apply_common_layout(fig, title, y_label)
