"""src.charts 图表构建器的测试。

覆盖 line_chart / bar_chart 的 trace 数据、标题、样式
以及空 DataFrame 的边界行为。
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pytest

from src.charts import bar_chart, line_chart

TITLE = "营业收入趋势"
Y_LABEL = "营业收入(万元)"


def make_df():
    return pd.DataFrame(
        {
            "period": ["2025Q1", "2025Q2", "2025Q3"],
            "revenue": [24500, 25000, 26800],
        }
    )


def test_line_chart_single_trace_with_data():
    df = make_df()
    fig = line_chart(df, "period", "revenue", TITLE, Y_LABEL)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == list(df["period"])
    assert list(fig.data[0].y) == list(df["revenue"])
    assert fig.data[0].mode == "lines+markers"


def test_bar_chart_single_trace_with_data():
    df = make_df()
    fig = bar_chart(df, "period", "revenue", TITLE, Y_LABEL)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == list(df["period"])
    assert list(fig.data[0].y) == list(df["revenue"])


def test_charts_title_and_y_axis_label():
    df = make_df()
    fig_line = line_chart(df, "period", "revenue", TITLE, Y_LABEL)
    fig_bar = bar_chart(df, "period", "revenue", TITLE, Y_LABEL)

    assert fig_line.layout.title.text == TITLE
    assert fig_line.layout.yaxis.title.text == Y_LABEL
    assert fig_bar.layout.title.text == TITLE
    assert fig_bar.layout.yaxis.title.text == Y_LABEL


def test_charts_use_plotly_dark_and_chinese_font():
    df = make_df()
    for fig in (line_chart(df, "period", "revenue", TITLE, Y_LABEL),
                bar_chart(df, "period", "revenue", TITLE, Y_LABEL)):
        assert fig.layout.template == pio.templates["plotly_dark"]
        assert fig.layout.font.family == "Microsoft YaHei, SimHei, sans-serif"


def test_empty_dataframe_returns_figure_with_empty_trace():
    df = pd.DataFrame({"period": [], "revenue": []})

    fig_line = line_chart(df, "period", "revenue", TITLE, Y_LABEL)
    fig_bar = bar_chart(df, "period", "revenue", TITLE, Y_LABEL)

    assert isinstance(fig_line, go.Figure)
    assert len(fig_line.data) == 1
    assert len(fig_line.data[0].x) == 0
    assert len(fig_line.data[0].y) == 0
    assert len(fig_bar.data[0].x) == 0
    assert len(fig_bar.data[0].y) == 0


@pytest.mark.parametrize(
    "chart_fn",
    [line_chart, bar_chart],
)
def test_empty_dataframe_does_not_raise(chart_fn):
    df = pd.DataFrame({"period": [], "revenue": []})
    fig = chart_fn(df, "period", "revenue", TITLE, Y_LABEL)
    assert isinstance(fig, go.Figure)
