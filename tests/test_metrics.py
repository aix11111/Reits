"""派生指标计算模块的测试。

覆盖 noi_margin / net_margin / annualized_distributable_yield /
latest_metrics 四个接口的数值正确性与边界情况。
"""

import pandas as pd
import pytest

from src.metrics import (
    annualized_distributable_yield,
    latest_metrics,
    net_margin,
    noi_margin,
)

COLUMNS = [
    "period",
    "code",
    "name",
    "total_revenue_wan",
    "total_cost_wan",
    "net_profit_wan",
    "distributable_wan",
    "ebitda_wan",
    "nav_wan",
    "source",
]


def make_df(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


SAMPLE_ROWS = [
    ["2025Q1", "180201", "平安广州广河REIT", 24500, 8500, 6800, 5200, 15800, 685000, "一季报"],
    ["2025Q2", "180201", "平安广州广河REIT", 25000, 8700, 7000, 5400, 16200, 688000, "中报"],
    ["2025Q1", "180202", "华夏越秀高速REIT", 15000, 6000, 4000, 3000, 9500, 210000, "一季报"],
]


def test_noi_margin_value_and_index():
    df = make_df(SAMPLE_ROWS)
    result = noi_margin(df)

    expected = (df["total_revenue_wan"] - df["total_cost_wan"]) / df["total_revenue_wan"]
    pd.testing.assert_series_equal(result, expected, check_names=False)
    assert list(result.index) == list(df.index)


def test_net_margin_value_and_index():
    df = make_df(SAMPLE_ROWS)
    result = net_margin(df)

    expected = df["net_profit_wan"] / df["total_revenue_wan"]
    pd.testing.assert_series_equal(result, expected, check_names=False)
    assert list(result.index) == list(df.index)


def test_annualized_distributable_yield_value_and_index():
    df = make_df(SAMPLE_ROWS)
    result = annualized_distributable_yield(df)

    expected = df["distributable_wan"] * 4 / df["nav_wan"]
    pd.testing.assert_series_equal(result, expected, check_names=False)
    assert list(result.index) == list(df.index)


def test_noi_margin_numeric_values():
    df = make_df(SAMPLE_ROWS)
    result = noi_margin(df)

    assert result.iloc[0] == pytest.approx((24500 - 8500) / 24500)
    assert result.iloc[1] == pytest.approx((25000 - 8700) / 25000)
    assert result.iloc[2] == pytest.approx((15000 - 6000) / 15000)


def test_latest_metrics_takes_latest_quarter():
    df = make_df(SAMPLE_ROWS)
    result = latest_metrics(df, "180201")

    assert result["period"] == "2025Q2"
    assert result["noi_margin"] == pytest.approx((25000 - 8700) / 25000)
    assert result["net_margin"] == pytest.approx(7000 / 25000)
    assert result["distributable_yield"] == pytest.approx(5400 * 4 / 688000)


def test_latest_metrics_uses_external_nav_when_provided():
    """显式传入年报净值时，年化可供分配收益率改用该 NAV（不再依赖季度行）。"""
    df = make_df(SAMPLE_ROWS)
    result = latest_metrics(df, "180201", nav_wan=860066.41)

    assert result["distributable_yield"] == pytest.approx(5400 * 4 / 860066.41)


def test_latest_metrics_yield_none_when_nav_missing():
    """外部 NAV 与季度列 NAV 均缺失 → distributable_yield 为 None（看板显示「—」）。"""
    df = make_df(
        [
            [
                "2026Q2",
                "180201",
                "平安广州广河REIT",
                16539.13,
                23043.99,
                3032.10,
                9917.02,
                13618.28,
                float("nan"),
                "季报",
            ]
        ]
    )
    result = latest_metrics(df, "180201")

    assert result["distributable_yield"] is None


def test_latest_metrics_unknown_code_returns_empty_dict():
    df = make_df(SAMPLE_ROWS)
    assert latest_metrics(df, "999999") == {}


def test_empty_dataframe_does_not_raise():
    df = make_df([])
    assert len(noi_margin(df)) == 0
    assert len(net_margin(df)) == 0
    assert len(annualized_distributable_yield(df)) == 0
