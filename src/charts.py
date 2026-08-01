"""Plotly 图表构建器。

统一提供折线图与柱状图的构建入口，封装中文字体、plotly_white
模板与标题配置，供上层分析页面直接调用。
"""

import pandas as pd
import plotly.graph_objects as go

FONT_FAMILY = "Microsoft YaHei, SimHei, sans-serif"


def _apply_common_layout(fig: go.Figure, title: str, y_label: str) -> go.Figure:
    """统一设置标题、y 轴标题、中文字体与模板。"""
    fig.update_layout(
        title=title,
        yaxis_title=y_label,
        template="plotly_white",
        font=dict(family=FONT_FAMILY),
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
        )
    )
    return _apply_common_layout(fig, title, y_label)
