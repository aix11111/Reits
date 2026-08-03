"""投后分析规则引擎的测试。

覆盖 detect_divergence / peer_compare（月度数据）与
distributable_yoy / distribution_rate_benchmark（季度数据）四个规则的
数值正确性、阈值边界、方向标记、排序与空数据边界情况。
输入列名与 src.data_loader 的输出保持一致。
"""

import pandas as pd
import pytest

from src.rules import (
    detect_divergence,
    distribution_rate_benchmark,
    distributable_yoy,
    peer_compare,
)

MONTHLY_COLUMNS = [
    "period",
    "code",
    "name",
    "toll_revenue_wan",
    "daily_traffic",
    "toll_revenue_yoy",
    "traffic_yoy",
    "source",
]


def make_df(rows):
    """将形如 [[period, code, name, rev, traffic, rev_yoy, traffic_yoy, source], ...] 的行转为 DataFrame。"""
    return pd.DataFrame(rows, columns=MONTHLY_COLUMNS)


# detect_divergence 的 fixture：含正常行 + 收入显著高于流量 + 流量显著高于收入 + 阈值边界行
DIVERGENCE_ROWS = [
    ["2026-06", "180201", "平安广州广河REIT", 1000, 10000, 10.0, 2.0, "公告"],  # diff=8.0  收入背离
    ["2026-06", "180202", "华夏越秀高速REIT", 1000, 10000, -3.0, 5.0, "公告"],  # diff=-8.0 流量背离
    ["2026-06", "180203", "华夏中国交建REIT", 1000, 10000, 7.0, 2.0, "公告"],  # diff=5.0  阈值边界触发
    ["2026-06", "180204", "华夏四川绕城REIT", 1000, 10000, 4.0, 9.0, "公告"],  # diff=-5.0 阈值边界触发
    ["2026-06", "180205", "中金安徽交控REIT", 1000, 10000, 2.0, 1.0, "公告"],  # diff=1.0  正常
]

# peer_compare 的 fixture：2026-06 组 4 只基金，2026-05 组仅 2 只（不足 3 只）
PEER_ROWS = [
    ["2026-06", "180201", "平安广州广河REIT", 1000, 10000, 20.0, 10.0, "公告"],
    ["2026-06", "180202", "华夏越秀高速REIT", 1000, 10000, 8.0, 5.0, "公告"],
    ["2026-06", "180203", "华夏中国交建REIT", 1000, 10000, 2.0, 3.0, "公告"],
    ["2026-06", "180204", "华夏四川绕城REIT", 1000, 10000, 5.0, 6.0, "公告"],
    ["2026-05", "180201", "平安广州广河REIT", 1000, 10000, 1.0, 1.0, "公告"],
    ["2026-05", "180202", "华夏越秀高速REIT", 1000, 10000, 2.0, 2.0, "公告"],
]


def test_divergence_threshold_boundary_triggers_at_5():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    assert result.loc[result["code"] == "180203", "divergence"].item()
    assert result.loc[result["code"] == "180203", "direction"].iloc[0] == "revenue_above"
    assert result.loc[result["code"] == "180204", "divergence"].item()
    assert result.loc[result["code"] == "180204", "direction"].iloc[0] == "traffic_above"


def test_divergence_below_threshold_is_not_flagged():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    assert not result.loc[result["code"] == "180205", "divergence"].item()


def test_divergence_direction_correct():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    assert result.loc[result["code"] == "180201", "direction"].iloc[0] == "revenue_above"
    assert result.loc[result["code"] == "180202", "direction"].iloc[0] == "traffic_above"


def test_divergence_pct_equals_yoy_gap():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    assert result.loc[result["code"] == "180201", "divergence_pct"].iloc[0] == pytest.approx(8.0)
    assert result.loc[result["code"] == "180202", "divergence_pct"].iloc[0] == pytest.approx(-8.0)
    assert result.loc[result["code"] == "180205", "divergence_pct"].iloc[0] == pytest.approx(1.0)


def test_divergence_sorted_by_abs_diff_desc():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    abs_diffs = result["divergence_pct"].abs().tolist()
    assert abs_diffs == sorted(abs_diffs, reverse=True)


def test_divergence_keeps_original_columns():
    df = make_df(DIVERGENCE_ROWS)
    result = detect_divergence(df)

    for col in MONTHLY_COLUMNS:
        assert col in result.columns
    assert result["code"].tolist() == df["code"].tolist()


def test_peer_compare_median_correct():
    df = make_df(PEER_ROWS)
    result = peer_compare(df)

    row_2026_06 = result[result["period"] == "2026-06"]
    # traffic_yoy = [10, 5, 3, 6] → 中位数 5.5；revenue_yoy = [20, 8, 2, 5] → 中位数 6.5
    assert row_2026_06["median_traffic_yoy"].unique().tolist() == [pytest.approx(5.5)]
    assert row_2026_06["median_revenue_yoy"].unique().tolist() == [pytest.approx(6.5)]


def test_peer_compare_below_peer_flagged():
    df = make_df(PEER_ROWS)
    result = peer_compare(df)
    row = result[result["period"] == "2026-06"].set_index("code")

    # 收入同比 2.0 < 中位数 6.5 → 收入跑输；车流量同比 3.0 < 5.5 → 流量也跑输
    assert row.loc["180203", "below_peer_revenue"]
    assert row.loc["180203", "below_peer_traffic"]
    # 收入 20.0 > 6.5、流量 10.0 > 5.5 → 均不跑输
    assert not row.loc["180201", "below_peer_revenue"]
    assert not row.loc["180201", "below_peer_traffic"]
    # 收入 5.0 < 6.5 → 跑输；流量 6.0 > 5.5 → 不跑输
    assert row.loc["180204", "below_peer_revenue"]
    assert not row.loc["180204", "below_peer_traffic"]


def test_peer_compare_group_under_3_funds_is_nan():
    df = make_df(PEER_ROWS)
    result = peer_compare(df)

    row_2026_05 = result[result["period"] == "2026-05"]
    assert row_2026_05["median_traffic_yoy"].isna().all()
    assert row_2026_05["median_revenue_yoy"].isna().all()
    assert row_2026_05["below_peer_traffic"].isna().all()
    assert row_2026_05["below_peer_revenue"].isna().all()


def test_peer_compare_group_exactly_3_funds_computes_median():
    rows = [
        ["2026-04", "180201", "平安广州广河REIT", 1000, 10000, 12.0, 10.0, "公告"],
        ["2026-04", "180202", "华夏越秀高速REIT", 1000, 10000, 7.0, 6.0, "公告"],
        ["2026-04", "180203", "华夏中国交建REIT", 1000, 10000, 3.0, 2.0, "公告"],
    ]
    result = peer_compare(make_df(rows))

    assert result["median_traffic_yoy"].tolist() == [pytest.approx(6.0)] * 3
    assert result["median_revenue_yoy"].tolist() == [pytest.approx(7.0)] * 3


def test_empty_dataframe_does_not_raise():
    empty = make_df([])

    assert len(detect_divergence(empty)) == 0
    assert len(peer_compare(empty)) == 0


# ---------------------------------------------------------------------------
# 规则 1：distributable_yoy（可供分配金额同比增速）
# ---------------------------------------------------------------------------

# 季度数据输出列（与 src.data_loader.load_quarterly 保持一致）
QUARTERLY_COLUMNS = [
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


def make_quarterly(rows):
    """将形如 [period, code, name, distributable_wan] 的行补全为季度 DataFrame。

    其余数值列填入默认值（total_revenue_wan=10000, total_cost_wan=6000,
    net_profit_wan=2000, ebitda_wan=5000, nav_wan=100000, source="季报"）。
    """
    entries = [
        [period, code, name, 10000, 6000, 2000, distributable, 5000, 100000, "季报"]
        for period, code, name, distributable in rows
    ]
    return pd.DataFrame(entries, columns=QUARTERLY_COLUMNS)


# distributable_yoy 的 fixture：4 只基金 × 3-4 期，含增长/下滑/无标记、
# 阈值边界（恰为 +20）、本期为 None、上年同期缺失等情形
YOY_ROWS = [
    ["2024Q1", "180201", "平安广州广河REIT", 1000.0],
    ["2024Q2", "180201", "平安广州广河REIT", 1000.0],
    ["2024Q3", "180201", "平安广州广河REIT", 1000.0],
    ["2025Q1", "180201", "平安广州广河REIT", 1300.0],  # +30.0 → growth
    ["2025Q2", "180201", "平安广州广河REIT", 1100.0],  # +10.0 → 无标记
    ["2025Q3", "180201", "平安广州广河REIT", None],     # 本期为 None → None
    ["2024Q1", "180202", "华夏越秀高速REIT", 1000.0],
    ["2024Q2", "180202", "华夏越秀高速REIT", 1000.0],
    ["2024Q3", "180202", "华夏越秀高速REIT", 1000.0],
    ["2025Q1", "180202", "华夏越秀高速REIT", 700.0],   # -30.0 → decline
    ["2025Q2", "180202", "华夏越秀高速REIT", 850.0],   # -15.0 → 无标记
    ["2025Q3", "180202", "华夏越秀高速REIT", 1000.0],  # 0.0 → 无标记
    ["2025Q1", "180203", "华夏中国交建REIT", 500.0],   # 无上年同期 → None
    ["2024Q1", "180204", "华夏四川绕城REIT", 1000.0],
    ["2025Q1", "180204", "华夏四川绕城REIT", 1200.0],  # +20.0 恰为阈值 → 无标记
]


def test_distributable_yoy_calculates_growth():
    result = distributable_yoy(make_quarterly(YOY_ROWS))
    row = result.set_index(["code", "period"])

    assert row.loc[("180201", "2025Q1"), "distributable_yoy"] == pytest.approx(30.0)
    assert row.loc[("180201", "2025Q2"), "distributable_yoy"] == pytest.approx(10.0)
    assert row.loc[("180202", "2025Q3"), "distributable_yoy"] == pytest.approx(0.0)


def test_distributable_yoy_decline_and_growth_flags():
    result = distributable_yoy(make_quarterly(YOY_ROWS))
    row = result.set_index(["code", "period"])

    # -30.0 < -20.0 → 下滑；非增长
    assert row.loc[("180202", "2025Q1"), "decline_flag"]
    assert not row.loc[("180202", "2025Q1"), "growth_flag"]
    # -15.0 在阈值内 → 均不标记
    assert not row.loc[("180202", "2025Q2"), "decline_flag"]
    assert not row.loc[("180202", "2025Q2"), "growth_flag"]
    # +30.0 > +20.0 → 增长；非下滑
    assert row.loc[("180201", "2025Q1"), "growth_flag"]
    assert not row.loc[("180201", "2025Q1"), "decline_flag"]


def test_distributable_yoy_threshold_boundary_is_strict():
    result = distributable_yoy(make_quarterly(YOY_ROWS))
    row = result.set_index(["code", "period"])

    assert row.loc[("180204", "2025Q1"), "distributable_yoy"] == pytest.approx(20.0)
    assert not row.loc[("180204", "2025Q1"), "growth_flag"]
    assert not row.loc[("180204", "2025Q1"), "decline_flag"]


def test_distributable_yoy_custom_threshold():
    result = distributable_yoy(make_quarterly(YOY_ROWS), threshold=5.0)
    row = result.set_index(["code", "period"])

    # +10.0 > +5.0 → 增长
    assert row.loc[("180201", "2025Q2"), "growth_flag"]
    # 0.0 在阈值内 → 不标记
    assert not row.loc[("180202", "2025Q3"), "decline_flag"]
    assert not row.loc[("180202", "2025Q3"), "growth_flag"]


def test_distributable_yoy_missing_prior_year_is_none():
    result = distributable_yoy(make_quarterly(YOY_ROWS))
    row = result.set_index(["code", "period"])

    assert pd.isna(row.loc[("180203", "2025Q1"), "distributable_yoy"])
    assert not row.loc[("180203", "2025Q1"), "decline_flag"]
    assert not row.loc[("180203", "2025Q1"), "growth_flag"]


def test_distributable_yoy_none_current_is_none():
    result = distributable_yoy(make_quarterly(YOY_ROWS))
    row = result.set_index(["code", "period"])

    assert pd.isna(row.loc[("180201", "2025Q3"), "distributable_yoy"])
    assert not row.loc[("180201", "2025Q3"), "decline_flag"]
    assert not row.loc[("180201", "2025Q3"), "growth_flag"]


def test_distributable_yoy_none_prior_returns_none():
    rows = [
        ["2024Q1", "180201", "平安广州广河REIT", None],
        ["2025Q1", "180201", "平安广州广河REIT", 1000.0],
    ]
    result = distributable_yoy(make_quarterly(rows))
    row = result.set_index(["code", "period"])

    assert pd.isna(row.loc[("180201", "2025Q1"), "distributable_yoy"])
    assert not row.loc[("180201", "2025Q1"), "decline_flag"]


def test_distributable_yoy_sorted_by_yoy_desc_none_last():
    result = distributable_yoy(make_quarterly(YOY_ROWS))

    yoys = result["distributable_yoy"].tolist()
    finite = [v for v in yoys if not pd.isna(v)]
    assert finite == sorted(finite, reverse=True)
    assert all(pd.isna(v) for v in yoys[len(finite):])


def test_distributable_yoy_keeps_original_columns():
    result = distributable_yoy(make_quarterly(YOY_ROWS))

    for col in QUARTERLY_COLUMNS:
        assert col in result.columns
    assert set(result.columns) == set(QUARTERLY_COLUMNS) | {
        "distributable_yoy",
        "decline_flag",
        "growth_flag",
    }


def test_distributable_yoy_empty_dataframe_does_not_raise():
    result = distributable_yoy(make_quarterly([]))

    assert len(result) == 0


# ---------------------------------------------------------------------------
# 规则 2：distribution_rate_benchmark（可供分配金额同行对标）
# ---------------------------------------------------------------------------

# distribution_rate_benchmark 的 fixture：2025Q1 组 5 只（含 1 只 None），
# 2024Q4 组仅 2 只（不足 3 只）
BENCHMARK_ROWS = [
    ["2025Q1", "180201", "平安广州广河REIT", 1200.0],
    ["2025Q1", "180202", "华夏越秀高速REIT", 800.0],
    ["2025Q1", "180203", "华夏中国交建REIT", 1000.0],
    ["2025Q1", "180204", "华夏四川绕城REIT", 600.0],
    ["2025Q1", "180205", "中金安徽交控REIT", None],  # 组内可供分配为 None
    ["2024Q4", "180201", "平安广州广河REIT", 1000.0],
    ["2024Q4", "180202", "华夏越秀高速REIT", 2000.0],  # 组内仅 2 只
]


def test_distribution_rate_benchmark_median_correct():
    result = distribution_rate_benchmark(make_quarterly(BENCHMARK_ROWS))
    row_2025 = result[result["period"] == "2025Q1"]

    # [600, 800, 1000, 1200]（None 忽略）→ 中位数 900
    assert row_2025["median_distributable_wan"].unique().tolist() == [pytest.approx(900.0)]


def test_distribution_rate_benchmark_below_peer_flagged():
    result = distribution_rate_benchmark(make_quarterly(BENCHMARK_ROWS))
    row = result.set_index(["code", "period"])

    assert not row.loc[("180201", "2025Q1"), "below_peer_distributable"]  # 1200 > 900
    assert row.loc[("180202", "2025Q1"), "below_peer_distributable"]  # 800 < 900
    assert not row.loc[("180203", "2025Q1"), "below_peer_distributable"]  # 1000 > 900
    assert row.loc[("180204", "2025Q1"), "below_peer_distributable"]  # 600 < 900


def test_distribution_rate_benchmark_none_distributable_is_nan():
    result = distribution_rate_benchmark(make_quarterly(BENCHMARK_ROWS))
    row = result.set_index(["code", "period"])

    assert pd.isna(row.loc[("180205", "2025Q1"), "below_peer_distributable"])


def test_distribution_rate_benchmark_group_under_3_is_nan():
    result = distribution_rate_benchmark(make_quarterly(BENCHMARK_ROWS))
    row_2024 = result[result["period"] == "2024Q4"]

    assert row_2024["median_distributable_wan"].isna().all()
    assert row_2024["below_peer_distributable"].isna().all()


def test_distribution_rate_benchmark_group_exactly_3_computes_median():
    rows = [
        ["2025Q1", "180201", "平安广州广河REIT", 1200.0],
        ["2025Q1", "180202", "华夏越秀高速REIT", 800.0],
        ["2025Q1", "180203", "华夏中国交建REIT", 1000.0],
    ]
    result = distribution_rate_benchmark(make_quarterly(rows))

    assert result["median_distributable_wan"].tolist() == [pytest.approx(1000.0)] * 3
    assert not result.loc[0, "below_peer_distributable"]
    assert result.loc[1, "below_peer_distributable"]
    assert not result.loc[2, "below_peer_distributable"]


def test_distribution_rate_benchmark_keeps_original_columns():
    result = distribution_rate_benchmark(make_quarterly(BENCHMARK_ROWS))

    for col in QUARTERLY_COLUMNS:
        assert col in result.columns
    assert "median_distributable_wan" in result.columns
    assert "below_peer_distributable" in result.columns


def test_distribution_rate_benchmark_empty_dataframe_does_not_raise():
    result = distribution_rate_benchmark(make_quarterly([]))

    assert len(result) == 0
