"""投后分析规则引擎的测试。

覆盖 detect_divergence / peer_compare 两个规则的数值正确性、
阈值边界、方向标记、排序与空数据边界情况。
输入列名与 src.data_loader.load_monthly 的输出保持一致。
"""

import pandas as pd
import pytest

from src.rules import detect_divergence, peer_compare

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
