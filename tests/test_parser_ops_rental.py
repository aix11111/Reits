"""tools.reits_collector.parser_ops_rental 模块（租赁类运营指标解析）的单元测试。

使用真实季报 PDF（data/_cache/quarterly_market/508000_2026Q2.pdf，
华安张江产业园 2026Q2，4.1.2 节整体运营指标）做全链路断言：
- 期末出租率 88.12%、平均租金单价 5.44 元/平/天、
  期末租金收缴率 100.00%、期末剩余租期 554 天；
- 标签断行（「期末租金收缴/率」「期末剩余租/期」）与标签变体
  （「出租率」不带「期末」前缀）均可解析；
- 千分位数值容忍；
- 无出租率字段（非租赁类资产）→ 返回 None。
"""

import json
from pathlib import Path

import pytest

from tools.reits_collector import parser_ops_rental

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REAL_PDF = DATA_DIR / "_cache" / "quarterly_market" / "508000_2026Q2.pdf"

RENTAL_KEYS = (
    "occupancy_pct",
    "avg_rent_yuan",
    "collection_pct",
    "remaining_lease_days",
)


def test_parse_rental_ops_real_pdf():
    """真实产业园季报 PDF：4.1.2 节整体运营指标四字段正确解析。"""
    result = parser_ops_rental.parse_rental_ops(REAL_PDF)

    assert result is not None
    assert set(result) == set(RENTAL_KEYS)
    assert result["occupancy_pct"] == pytest.approx(88.12)
    assert result["avg_rent_yuan"] == pytest.approx(5.44)
    assert result["collection_pct"] == pytest.approx(100.0)
    assert result["remaining_lease_days"] == pytest.approx(554.0)


def test_parse_rental_ops_broken_line_labels():
    """标签断行（PDF 表格单元格换行）：解析结果与连续标签一致。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "序号\n指标名称\n指标单位\n"
        "3\n期末出租\n率\n%\n88.12\n"
        "4\n平均租金单\n价\n元/平/天\n5.44\n"
        "5\n期末剩余租\n期\n天\n554.00\n"
        "6\n期末租金收缴\n率\n%\n100.00\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(88.12)
    assert result["avg_rent_yuan"] == pytest.approx(5.44)
    assert result["collection_pct"] == pytest.approx(100.0)
    assert result["remaining_lease_days"] == pytest.approx(554.0)


def test_parse_rental_ops_label_variant_without_period_prefix():
    """标签变体：仅「出租率」「租金收缴率」不带「期末」前缀也能解析。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "3\n出租率\n%\n88.12\n"
        "4\n平均租金单价\n元/平/天\n5.44\n"
        "5\n剩余租期\n天\n554.00\n"
        "6\n租金收缴率\n%\n100.00\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(88.12)
    assert result["remaining_lease_days"] == pytest.approx(554.0)


def test_parse_rental_ops_thousand_separators():
    """千分位数值（如 1,554.00 天）正常转数字。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "3\n期末出租率\n%\n88.12\n"
        "4\n平均租金单价\n元/平/天\n5.44\n"
        "5\n期末剩余租期\n天\n1,554.00\n"
        "6\n期末租金收缴率\n%\n100.00\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["remaining_lease_days"] == pytest.approx(1554.0)


def test_parse_rental_ops_no_occupancy_returns_none():
    """无出租率字段（非租赁类资产，如高速/能源季报）→ 返回 None。"""
    text = (
        "某高速公路封闭式基础设施证券投资基金2026年第2季度报告\n"
        "3.1 主要财务指标\n"
        "1.本期收入\n30,650,710.62\n"
        "2.本期净利润\n-11,644,536.88\n"
    )
    assert parser_ops_rental.parse_rental_ops_text(text) is None


def test_parse_rental_ops_skips_digits_in_formula_column():
    """公式列含数字（收缴率「=1-截至6月30日…」、出租率「×100%」）不污染取值：
    取值锚定单位单元格之后。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "3\n报告期末出租率\n实际出租面积/可供出租面积×100%\n%\n99.20\n98.73\n0.48\n"
        "6\n租金收缴率\n=1-截至6月30日报告期内尚未回收的租金收入/报告期内应收租金收入\n%\n89.80\n90.24\n-0.49\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(99.20)
    assert result["collection_pct"] == pytest.approx(89.80)


def test_parse_rental_ops_ignores_non_conforming_units():
    """租金接受各口径披露（元/㎡/月 按披露值 46.05 如实取）；剩余租期年
    口径不折算 → remaining_lease_days 为 None。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "3\n出租率\n%\n95.55\n"
        "4\n平均合同单价\n报告期末按实际出租面积加权计算的合同签约价格\n元/㎡/月\n46.05\n"
        "5\n租约剩余期限\n按实际出租面积加权计算的合同剩余租期\n年\n2.38\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(95.55)
    assert result["avg_rent_yuan"] == pytest.approx(46.05)
    assert result["remaining_lease_days"] is None


def test_parse_rental_ops_partial_fields_are_none():
    """有出租率但其余字段缺失 → 缺失字段如实为 None，仍返回 dict。"""
    text = "4.1.2 报告期整体运营指标\n3\n期末出租率\n%\n88.12\n"
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(88.12)
    assert result["avg_rent_yuan"] is None
    assert result["collection_pct"] is None
    assert result["remaining_lease_days"] is None


def test_parse_rental_ops_narrative_fallback_without_table():
    """旧报告无 4.1.2 表格，仅叙述段披露（「整体出租率为82.31%」「租金
    收缴率为98.67%」，数值在前、% 在后）→ 出租率/收缴率兜底取值。"""
    text = (
        "某产业园封闭式基础设施证券投资基金2023年第2季度报告\n"
        "4.1 对报告期内基础设施项目公司运营情况的整体说明\n"
        "报告期内，截至2023年6月末的整体出租率为82.31%。租赁业态分布主要\n"
        "为先进制造业31.34%、集成电路21.11%、TMT（含在线新经济）18.39%。\n"
        "租金收缴率为98.67%。\n"
    )
    result = parser_ops_rental.parse_rental_ops_text(text)

    assert result is not None
    assert result["occupancy_pct"] == pytest.approx(82.31)
    assert result["collection_pct"] == pytest.approx(98.67)
    assert result["avg_rent_yuan"] is None
    assert result["remaining_lease_days"] is None


def test_market_ops_rental_row_schema_from_real_pdf():
    """批量行结构：code/period 由调用方补充，运营指标四字段为数值。"""
    result = parser_ops_rental.parse_rental_ops(REAL_PDF)
    row = {"code": "508000", "period": "2026Q2", **result}

    assert row["code"] == "508000"
    assert row["period"] == "2026Q2"
    for key in RENTAL_KEYS:
        assert isinstance(row[key], (int, float))
