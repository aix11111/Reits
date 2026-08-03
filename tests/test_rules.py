"""投后分析规则引擎的测试。

覆盖 detect_divergence / peer_compare（月度数据）与
distributable_yoy / distribution_rate_benchmark（季度数据）四个规则的
数值正确性、阈值边界、方向标记、排序与空数据边界情况。
输入列名与 src.data_loader 的输出保持一致。
"""

import pandas as pd
import pytest

from src.rules import (
    concession_decay,
    detect_divergence,
    detect_mom_spikes,
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


# ---------------------------------------------------------------------------
# 规则 3：detect_mom_spikes（月度环比异动检测）
# ---------------------------------------------------------------------------

# 月度 fixture：3 只基金 × 4-6 月，含上涨/下跌/无标记/首月 None/缺月 None/单边 None
MOM_ROWS = [
    # 180201 平安广州广河REIT：6 个月，覆盖上涨/下跌/无标记/首月
    ["2026-01", "180201", "平安广州广河REIT", 100, 10000],
    ["2026-02", "180201", "平安广州广河REIT", 100, 10000],  # 0.0 / 0.0 → 无标记
    ["2026-03", "180201", "平安广州广河REIT", 160, 10000],  # +60 / 0.0 → 收入上涨异动
    ["2026-04", "180201", "平安广州广河REIT", 160, 15000],  # 0.0 / +50 → 车流量上涨异动
    ["2026-05", "180201", "平安广州广河REIT", 80, 15000],   # -50 / 0.0 → 收入下跌异动
    ["2026-06", "180201", "平安广州广河REIT", 80, 7500],    # 0.0 / -50 → 车流量下跌异动
    # 180202 华夏越秀高速REIT：5 个月，2026-01 缺月（首月前无上月）
    ["2026-02", "180202", "华夏越秀高速REIT", 100, 10000],
    ["2026-03", "180202", "华夏越秀高速REIT", 100, 10000],  # 0.0 / 0.0 → 无标记
    ["2026-04", "180202", "华夏越秀高速REIT", 125, 10000],  # +25 / 0.0 → 低于阈值
    ["2026-05", "180202", "华夏越秀高速REIT", 125, 10000],  # 0.0 / 0.0 → 无标记
    ["2026-06", "180202", "华夏越秀高速REIT", 225, 10000],  # +80 / 0.0 → 收入上涨异动
    # 180203 华夏中国交建REIT：含缺月（2026-05 缺失）与单边 None
    ["2026-04", "180203", "华夏中国交建REIT", 100, 10000],
    ["2026-06", "180203", "华夏中国交建REIT", None, 10000],  # 缺月 + 收入 None → 收入 mom None
    ["2026-07", "180203", "华夏中国交建REIT", 200, 20000],  # 收入 None→200 → 收入 mom None；+100 → 车流量异动
    ["2026-08", "180203", "华夏中国交建REIT", 100, 10000],  # -50 / -50 → 双下跌异动
]


def make_mom_df(rows):
    """将形如 [period, code, name, rev, traffic] 的行补全为月度 DataFrame。

    其余数值列（toll_revenue_yoy / traffic_yoy）填入默认值 None，
    source 填 "公告"。
    """
    entries = [[p, c, n, rev, traffic, None, None, "公告"] for p, c, n, rev, traffic in rows]
    return pd.DataFrame(entries, columns=MONTHLY_COLUMNS)


def test_mom_spikes_revenue_up_flag():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    assert row.loc[("180201", "2026-03"), "revenue_mom"] == pytest.approx(60.0)
    assert row.loc[("180201", "2026-03"), "revenue_spike"]
    assert not row.loc[("180201", "2026-03"), "traffic_spike"]


def test_mom_spikes_revenue_down_flag():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    assert row.loc[("180201", "2026-05"), "revenue_mom"] == pytest.approx(-50.0)
    assert row.loc[("180201", "2026-05"), "revenue_spike"]


def test_mom_spikes_traffic_up_and_down_flags():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    assert row.loc[("180201", "2026-04"), "traffic_mom"] == pytest.approx(50.0)
    assert row.loc[("180201", "2026-04"), "traffic_spike"]
    assert row.loc[("180201", "2026-06"), "traffic_mom"] == pytest.approx(-50.0)
    assert row.loc[("180201", "2026-06"), "traffic_spike"]


def test_mom_spikes_within_threshold_not_flagged():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    # +25 与 0.0 均低于阈值 30
    assert row.loc[("180202", "2026-04"), "revenue_mom"] == pytest.approx(25.0)
    assert not row.loc[("180202", "2026-04"), "revenue_spike"]
    assert not row.loc[("180201", "2026-02"), "revenue_spike"]
    assert not row.loc[("180201", "2026-02"), "traffic_spike"]


def test_mom_spikes_threshold_boundary_is_strict():
    rows = [
        ["2026-03", "180204", "华夏四川绕城REIT", 100, 10000],
        ["2026-04", "180204", "华夏四川绕城REIT", 125, 10000],  # 恰为 +25 边界
        ["2026-05", "180204", "华夏四川绕城REIT", 100, 10000],  # 回到基准
        ["2026-06", "180204", "华夏四川绕城REIT", 75, 10000],   # 恰为 -25 边界
        ["2026-07", "180204", "华夏四川绕城REIT", 100, 10000],  # 回到基准
        ["2026-08", "180204", "华夏四川绕城REIT", 126, 10000],  # +26 高于阈值
    ]
    result = detect_mom_spikes(make_mom_df(rows), threshold=25.0)
    row = result.set_index(["code", "period"])

    assert row.loc[("180204", "2026-04"), "revenue_mom"] == pytest.approx(25.0)
    assert not row.loc[("180204", "2026-04"), "revenue_spike"]
    assert row.loc[("180204", "2026-06"), "revenue_mom"] == pytest.approx(-25.0)
    assert not row.loc[("180204", "2026-06"), "revenue_spike"]
    assert row.loc[("180204", "2026-08"), "revenue_mom"] == pytest.approx(26.0)
    assert row.loc[("180204", "2026-08"), "revenue_spike"]


def test_mom_spikes_custom_threshold():
    rows = [
        ["2026-03", "180204", "华夏四川绕城REIT", 100, 10000],
        ["2026-04", "180204", "华夏四川绕城REIT", 105, 10000],  # +5 → 低于阈值 10
        ["2026-05", "180204", "华夏四川绕城REIT", 120, 10000],  # +14.3 → 高于阈值 10
    ]
    result = detect_mom_spikes(make_mom_df(rows), threshold=10.0)
    row = result.set_index(["code", "period"])

    assert not row.loc[("180204", "2026-04"), "revenue_spike"]
    assert row.loc[("180204", "2026-05"), "revenue_spike"]


def test_mom_spikes_first_month_mom_is_none():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    assert pd.isna(row.loc[("180201", "2026-01"), "revenue_mom"])
    assert pd.isna(row.loc[("180201", "2026-01"), "traffic_mom"])
    assert not row.loc[("180201", "2026-01"), "revenue_spike"]
    assert not row.loc[("180201", "2026-01"), "traffic_spike"]
    # 180202 首月为 2026-02（2026-01 无数据）→ mom None
    assert pd.isna(row.loc[("180202", "2026-02"), "revenue_mom"])
    assert pd.isna(row.loc[("180202", "2026-02"), "traffic_mom"])


def test_mom_spikes_missing_prior_month_mom_is_none():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    # 180203 缺 2026-05，2026-06 的上月（2026-05）缺失 → mom None
    assert pd.isna(row.loc[("180203", "2026-06"), "revenue_mom"])
    assert pd.isna(row.loc[("180203", "2026-06"), "traffic_mom"])
    assert not row.loc[("180203", "2026-06"), "revenue_spike"]
    assert not row.loc[("180203", "2026-06"), "traffic_spike"]


def test_mom_spikes_none_side_mom_is_none():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))
    row = result.set_index(["code", "period"])

    # 180203 2026-06 收入 None → 收入 mom None；车流量 2026-04=10000 因缺月也 None
    assert pd.isna(row.loc[("180203", "2026-06"), "revenue_mom"])
    # 180203 2026-07 收入从 None→200 → 收入 mom None，车流量 10000→20000 → +100 异动
    assert pd.isna(row.loc[("180203", "2026-07"), "revenue_mom"])
    assert row.loc[("180203", "2026-07"), "traffic_mom"] == pytest.approx(100.0)
    assert row.loc[("180203", "2026-07"), "traffic_spike"]


def test_mom_spikes_sorted_by_max_abs_desc_none_last():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))

    max_abs = result[["revenue_mom", "traffic_mom"]].abs().max(axis=1)
    non_null = max_abs[result["code"].ne("")].dropna()
    assert non_null.tolist() == sorted(non_null.tolist(), reverse=True)
    # 首行应为最大异动幅度（180203 2026-07 车流量 +100）
    assert result.iloc[0]["period"] == "2026-07"
    assert result.iloc[0]["code"] == "180203"
    # NaN 置于尾部：所有 NaN 行都应排在最后一个非 NaN 行之后
    nan_positions = max_abs[max_abs.isna()].index
    last_finite = result["revenue_mom"].last_valid_index()
    finite_rows = result.index[: result.index.get_loc(last_finite) + 1]
    assert all(idx not in finite_rows for idx in nan_positions)


def test_mom_spikes_keeps_original_columns():
    result = detect_mom_spikes(make_mom_df(MOM_ROWS))

    for col in MONTHLY_COLUMNS:
        assert col in result.columns
    assert set(result.columns) == set(MONTHLY_COLUMNS) | {
        "revenue_mom",
        "traffic_mom",
        "revenue_spike",
        "traffic_spike",
    }


def test_mom_spikes_empty_dataframe_does_not_raise():
    result = detect_mom_spikes(make_mom_df([]))

    assert len(result) == 0


# ---------------------------------------------------------------------------
# 规则 4：concession_decay（特许经营权衰减）
# ---------------------------------------------------------------------------

# 静态信息输出列（与 src.data_loader.load_static 保持一致）
STATIC_COLUMNS = [
    "code",
    "name",
    "asset",
    "region",
    "mileage_km",
    "listing_date",
    "issue_scale_yi",
    "concession_years_left",
    "asset_type",
]


def make_static(rows):
    """将形如 [code, name, concession_years_left] 的行补全为静态信息 DataFrame。

    其余列填入默认值（asset="高速", region="广东", mileage_km=100,
    listing_date="2021-01-01", issue_scale_yi=10, asset_type="特许经营权"）。
    """
    entries = [
        [code, name, "高速", "广东", 100, "2021-01-01", 10, years, "特许经营权"]
        for code, name, years in rows
    ]
    return pd.DataFrame(entries, columns=STATIC_COLUMNS)


# concession_decay 的 fixture：含临近到期 / 关注 / 正常 / NaN /
# 边界 warn_years=10 恰为 10 → 关注、恰为 15 → 正常
CONCESSION_ROWS = [
    ["180201", "平安广州广河REIT", 20.0],    # >= 15 → 正常
    ["180202", "华夏越秀高速REIT", 5.0],     # < 10 → 临近到期
    ["180203", "招商高速公路REIT", 10.0],    # 恰为 warn_years=10 → 关注
    ["508001", "浙商沪杭甬REIT", 12.0],      # 10 <= x < 15 → 关注
    ["508018", "华夏中国交建REIT", 15.0],    # 恰为 15 → 正常
    ["508008", "国金中国铁建REIT", None],    # NaN → 未知，排最后
]


def test_concession_decay_risk_levels():
    result = concession_decay(make_static(CONCESSION_ROWS))
    row = result.set_index("code")

    assert row.loc["180202", "risk_level"] == "临近到期"
    assert row.loc["508001", "risk_level"] == "关注"
    assert row.loc["180201", "risk_level"] == "正常"


def test_concession_decay_boundary_warn_years_is_watch():
    """恰为 warn_years=10 → 关注（非临近到期）；恰为 15 → 正常（非关注）。"""
    result = concession_decay(make_static(CONCESSION_ROWS))
    row = result.set_index("code")

    assert row.loc["180203", "risk_level"] == "关注"
    assert row.loc["508018", "risk_level"] == "正常"


def test_concession_decay_nan_is_unknown():
    result = concession_decay(make_static(CONCESSION_ROWS))
    row = result.set_index("code")

    assert row.loc["508008", "risk_level"] == "未知"


def test_concession_decay_sorted_ascending_nan_last():
    """按剩余年限升序（最短在前，风险最高），NaN 排最后。"""
    result = concession_decay(make_static(CONCESSION_ROWS))

    assert result["code"].tolist() == [
        "180202",  # 5
        "180203",  # 10
        "508001",  # 12
        "508018",  # 15
        "180201",  # 20
        "508008",  # NaN → 最后
    ]


def test_concession_decay_custom_warn_years():
    rows = [
        ["180201", "平安广州广河REIT", 7.0],
        ["180202", "华夏越秀高速REIT", 8.0],
        ["180203", "招商高速公路REIT", 12.0],
    ]
    result = concession_decay(make_static(rows), warn_years=8)
    row = result.set_index("code")

    assert row.loc["180201", "risk_level"] == "临近到期"  # 7 < 8
    assert row.loc["180202", "risk_level"] == "关注"      # 恰为 8
    assert row.loc["180203", "risk_level"] == "关注"      # 8 <= 12 < 15


def test_concession_decay_keeps_original_columns():
    result = concession_decay(make_static(CONCESSION_ROWS))

    for col in STATIC_COLUMNS:
        assert col in result.columns
    assert set(result.columns) == set(STATIC_COLUMNS) | {"risk_level"}


def test_concession_decay_empty_dataframe_does_not_raise():
    result = concession_decay(make_static([]))

    assert len(result) == 0
    assert "risk_level" in result.columns
