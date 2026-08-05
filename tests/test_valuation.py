"""估值模块的测试。

覆盖 ttm_distributable / distribution_yield / nav_premium / risk_flags 四个
纯函数的数值正确性与边界情况：
- ttm_distributable：近 4 季滚动加总、不足 4 季按最新季年化、窗口内含 NaN、
  无数据与空 DataFrame
- distribution_yield：TTM 金额折算收益率的精确计算与缺失输入
- nav_premium：净值溢折价的正确性与缺失输入
- risk_flags：完成度/溢价/剩余年限风险组合与全正常、全 NaN 边界

输入列名与 src.rules 的季度/年报输入约定一致：季度列
code/period/distributable_wan，完成度列 code/completion_pct。
"""

import pandas as pd
import pytest

from src.valuation import (
    concession_irr,
    distribution_yield,
    nav_premium,
    risk_flags,
    ttm_distributable,
)


def make_quarterly(rows):
    return pd.DataFrame(rows, columns=["code", "period", "distributable_wan"])


def test_ttm_sums_last_four_quarters():
    df = make_quarterly(
        [
            ["180201", "2025Q1", 100.0],
            ["180201", "2025Q2", 110.0],
            ["180201", "2025Q3", 120.0],
            ["180201", "2025Q4", 130.0],
            ["180201", "2026Q1", 140.0],
        ]
    )
    result = ttm_distributable(df)

    assert list(result.index) == ["180201"]
    assert result.loc["180201", "dist_ttm_wan"] == pytest.approx(110 + 120 + 130 + 140)
    assert result.loc["180201", "is_annualized"] == False


def test_ttm_nan_inside_window_yields_nan():
    df = make_quarterly(
        [
            ["180202", "2025Q1", 100.0],
            ["180202", "2025Q2", None],
            ["180202", "2025Q3", 120.0],
            ["180202", "2025Q4", 130.0],
        ]
    )
    result = ttm_distributable(df)

    assert pd.isna(result.loc["180202", "dist_ttm_wan"])


def test_ttm_fewer_than_four_quarters_annualizes_latest():
    df = make_quarterly(
        [
            ["180203", "2025Q4", 130.0],
            ["180203", "2026Q1", 140.0],
            ["180203", "2026Q2", 150.0],
        ]
    )
    result = ttm_distributable(df)

    assert result.loc["180203", "dist_ttm_wan"] == pytest.approx(150 * 4)
    assert result.loc["180203", "is_annualized"] == True


def test_ttm_no_data_yields_nan():
    df = make_quarterly([["180204", "2026Q1", None]])
    result = ttm_distributable(df)

    assert pd.isna(result.loc["180204", "dist_ttm_wan"])


def test_ttm_empty_df_returns_empty():
    result = ttm_distributable(make_quarterly([]))

    assert result.empty
    assert set(result.columns) == {"dist_ttm_wan", "is_annualized"}


def test_yield_exact_value():
    dist_df = pd.DataFrame({"dist_ttm_wan": [1000.0]}, index=["180201"])
    snapshot = {"180201": {"price": 5.0, "market_cap_wan": 20000}}
    shares = {"180201": 40_000_000}
    result = distribution_yield(dist_df, snapshot, shares)

    assert result["180201"] == pytest.approx(0.05)


def test_yield_missing_inputs_is_nan():
    dist_df = pd.DataFrame(
        {"dist_ttm_wan": [1000.0, 1000.0, float("nan"), 1000.0]},
        index=["180201", "180202", "180203", "180204"],
    )
    snapshot = {
        "180201": {"price": 5.0, "market_cap_wan": 20000},
        "180202": {"market_cap_wan": 20000},
        "180203": {"price": 5.0, "market_cap_wan": 20000},
        "180204": {"price": 5.0, "market_cap_wan": 20000},
    }
    shares = {"180201": 40_000_000, "180203": 40_000_000, "180204": 40_000_000}
    result = distribution_yield(dist_df, snapshot, shares)

    assert result["180201"] == pytest.approx(0.05)
    assert pd.isna(result["180202"])
    assert pd.isna(result["180203"])


def test_nav_premium_positive_negative_zero():
    price = pd.Series([2.5, 2.0, 1.5], index=["180201", "180202", "180203"])
    nav = pd.Series([2.0, 2.0, 2.0], index=["180201", "180202", "180203"])
    result = nav_premium(price, nav)

    assert result["180201"] == pytest.approx(0.25)
    assert result["180202"] == pytest.approx(0.0)
    assert result["180203"] == pytest.approx(-0.25)


def test_nav_premium_missing_is_nan():
    price = pd.Series([2.5, float("nan"), 1.5], index=["180201", "180202", "180203"])
    nav = pd.Series([float("nan"), 2.0, 2.0], index=["180201", "180202", "180203"])
    result = nav_premium(price, nav)

    assert pd.isna(result["180201"])
    assert pd.isna(result["180202"])
    assert result["180203"] == pytest.approx(-0.25)


def test_risk_flags_combination():
    completion_df = pd.DataFrame(
        {
            "code": ["180201", "180202", "180203", "180204", "180205"],
            "completion_pct": [75.0, 90.0, 110.0, float("nan"), 105.0],
        }
    )
    premium = pd.Series(
        [0.25, 0.05, 0.10, 0.30, -0.10],
        index=["180201", "180202", "180203", "180204", "180205"],
    )
    years_left = pd.Series(
        [5.0, 20.0, 8.0, 12.0, 15.0],
        index=["180201", "180202", "180203", "180204", "180205"],
    )
    result = risk_flags(completion_df, premium, years_left).set_index("code")

    assert "completion_risk" in result.loc["180201", "flags"]
    assert "premium_risk" in result.loc["180201", "flags"]
    assert "concession_risk" in result.loc["180201", "flags"]
    assert "completion_watch" in result.loc["180202", "flags"]
    assert "premium_risk" not in result.loc["180202", "flags"]
    assert "concession_risk" in result.loc["180203", "flags"]
    assert "completion_risk" not in result.loc["180203", "flags"]
    assert "premium_risk" in result.loc["180204", "flags"]
    assert "180205" not in result.index


def test_risk_flags_all_normal_returns_empty():
    completion_df = pd.DataFrame(
        {"code": ["180201", "180202"], "completion_pct": [120.0, 130.0]}
    )
    premium = pd.Series([0.10, -0.05], index=["180201", "180202"])
    years_left = pd.Series([20.0, 25.0], index=["180201", "180202"])
    result = risk_flags(completion_df, premium, years_left)

    assert list(result.columns) == ["code", "flags"]
    assert result.empty


def test_risk_flags_all_nan_does_not_crash():
    completion_df = pd.DataFrame(
        {"code": ["180201"], "completion_pct": [float("nan")]}
    )
    premium = pd.Series([float("nan")], index=["180201"])
    years_left = pd.Series([float("nan")], index=["180201"])
    result = risk_flags(completion_df, premium, years_left)

    assert result.empty


def test_concession_irr_one_year_hand_calc():
    """手算案例：买价 10 亿、1 年后收回 1 亿、到期归零 → 现金流 [-10亿, +1亿]。

    1 年期单现金回收：IRR = 分派/投入 - 1 = 0.1 - 1 = -0.9。
    """
    result = concession_irr(
        price=10, shares=1e8, annual_distributable_wan=10000, years_left=1
    )

    assert result == pytest.approx(-0.9, abs=1e-4)


def test_concession_irr_perpetual_degenerates_to_distribution_yield():
    """years 很大且 growth=0 → IRR 逼近分派率（1亿/10亿 = 10%）。"""
    result = concession_irr(
        price=10, shares=1e8, annual_distributable_wan=10000, years_left=100
    )

    assert result == pytest.approx(0.1, abs=1e-3)


def test_concession_irr_zero_when_distribution_equals_buy_cost():
    """years=1 且当年分派=买入市值 → IRR = 0（分派恰好覆盖全部本金）。"""
    result = concession_irr(
        price=5, shares=4e7, annual_distributable_wan=20000, years_left=1
    )

    assert result == pytest.approx(0.0, abs=1e-6)


def test_concession_irr_growth_raises_irr():
    """growth>0 时未来现金流更高，IRR 应高于 growth=0。"""
    base = concession_irr(
        price=10, shares=1e8, annual_distributable_wan=10000, years_left=10, growth=0.0
    )
    grown = concession_irr(
        price=10, shares=1e8, annual_distributable_wan=10000, years_left=10, growth=0.05
    )

    assert base is not None
    assert grown is not None
    assert grown > base


def test_concession_irr_invalid_shares_returns_none():
    assert (
        concession_irr(
            price=10, shares=0, annual_distributable_wan=10000, years_left=10
        )
        is None
    )


def test_concession_irr_no_root_returns_none():
    """分派为 0 → NPV 恒负，区间内无解 → None。"""
    assert (
        concession_irr(
            price=10, shares=1e8, annual_distributable_wan=0, years_left=10
        )
        is None
    )


def test_concession_irr_nan_or_none_inputs_do_not_crash():
    assert concession_irr(float("nan"), 1e8, 10000, 10) is None
    assert concession_irr(10, float("nan"), 10000, 10) is None
    assert concession_irr(10, 1e8, float("nan"), 10) is None
    assert concession_irr(10, 1e8, 10000, float("nan")) is None
    assert concession_irr(None, 1e8, 10000, 10) is None
    assert concession_irr(10, None, 10000, 10) is None
    assert concession_irr(10, 1e8, None, 10) is None
    assert concession_irr(10, 1e8, 10000, None) is None
