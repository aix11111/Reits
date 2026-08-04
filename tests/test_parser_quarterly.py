"""tools.reits_collector.parser_quarterly 模块（季度报告解析）的单元测试。

使用 4 份真实 2026 年第 2 季度报告 PDF 做全链路断言
（extract_text + parse_quarterly_report），覆盖沪深两市 4 家管理人
（平安广河 / 浙商沪杭甬 / 平安宁波交投 / 国金铁建）在同一模板下的
字段差异（净利润为负、单位可供分配金额带脚注标记等）；并覆盖
报告期三种写法（标题「2026年第2季度报告」、正文
「报告期(2026年04月01日-2026年06月30日)」、中文数字年份）与
字段缺失返回 None 的容错路径。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_quarterly

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED = {
    "quarterly_180201_2026Q2.pdf": {
        "period": "2026Q2",
        "revenue_wan": 16539.127560,
        "net_profit_wan": 3032.096994,
        "distributable_wan": 9917.015159,
        "unit_distributable": 0.1417,
        "ebitda_wan": 13618.275213,
        "cash_distribution_rate": 1.84,
    },
    "quarterly_508001_2026Q2.pdf": {
        "period": "2026Q2",
        "revenue_wan": 16029.587681,
        "net_profit_wan": -476.757443,
        "distributable_wan": 5404.764238,
        "unit_distributable": 0.1081,
        "ebitda_wan": 13007.825301,
        "cash_distribution_rate": 2.08,
    },
    "quarterly_508036_2026Q2.pdf": {
        "period": "2026Q2",
        "revenue_wan": 53483.862546,
        "net_profit_wan": 9227.091730,
        "distributable_wan": 28693.356135,
        "unit_distributable": 0.2869,
        "ebitda_wan": 46204.682430,
        "cash_distribution_rate": 3.70,
    },
    "quarterly_508008_2026Q2.pdf": {
        "period": "2026Q2",
        "revenue_wan": 15562.191942,
        "net_profit_wan": 943.423879,
        "distributable_wan": 9031.251929,
        "unit_distributable": 0.1806,
        "ebitda_wan": 12812.048081,
        "cash_distribution_rate": 2.38,
    },
    "quarterly_180201_2024Q3.pdf": {
        "period": "2024Q3",
        "revenue_wan": 20958.508005,
        "net_profit_wan": 7496.249847,
        "distributable_wan": 17271.714174,
        "unit_distributable": 0.2467,
        "ebitda_wan": None,
        "cash_distribution_rate": None,
    },
}

VALUE_KEYS = (
    "revenue_wan",
    "net_profit_wan",
    "distributable_wan",
    "unit_distributable",
    "ebitda_wan",
    "cash_distribution_rate",
)


@pytest.mark.parametrize("pdf_name", list(EXPECTED))
def test_parse_quarterly_report_real_pdf(pdf_name):
    result = parser_quarterly.parse_quarterly_report(FIXTURES_DIR / pdf_name)
    exp = EXPECTED[pdf_name]

    assert result["period"] == exp["period"]
    for key in VALUE_KEYS:
        if exp[key] is None:
            assert result[key] is None
        else:
            assert result[key] == pytest.approx(exp[key])


@pytest.mark.parametrize(
    "period_raw, expected",
    [
        ("2026年第2季度报告", "2026Q2"),
        ("二〇二六年第二季度报告", "2026Q2"),
        ("报告期(2026年04月01日-2026年06月30日)", "2026Q2"),
        ("报告期（2026年4月1日-2026年6月30日）", "2026Q2"),
        ("本报告期自2026年4月1日至2026年6月30日止", "2026Q2"),
    ],
)
def test_parse_period_supports_title_body_and_chinese_digits(period_raw, expected):
    assert parser_quarterly._parse_period(period_raw) == expected


def test_parse_period_missing_returns_none():
    assert parser_quarterly._parse_period("没有报告期的文本") is None


def test_parse_quarterly_missing_fields_return_none():
    """任一核心字段缺失时返回 None，不抛异常。"""
    result = parser_quarterly.parse_quarterly("某某基金2026年第2季度报告")

    assert result["period"] == "2026Q2"
    for key in VALUE_KEYS:
        assert result[key] is None


# ---------------------------------------------------------------------------
# 全市场产业园模板（508000 华安张江产业园 2026Q2）
# ---------------------------------------------------------------------------


def test_parse_quarterly_508000_industrial_park_fixture():
    """产业园季报：3.1 行标签带「1.」序号，收入列标签为「本期收入」；
    「3.3.1 本报告期的可供分配金额」表给出 本期 可供分配金额/单位可供分配金额。
    金额元→万换算正确。"""
    text = (FIXTURES_DIR / "quarterly_508000_2026Q2.txt").read_text(encoding="utf-8")
    result = parser_quarterly.parse_quarterly(text)

    assert result["period"] == "2026Q2"
    assert result["revenue_wan"] == pytest.approx(3065.07, rel=1e-3)
    assert result["net_profit_wan"] == pytest.approx(-1164.45, rel=1e-3)
    assert result["distributable_wan"] == pytest.approx(2369.54, rel=1e-3)
    assert result["unit_distributable"] == pytest.approx(0.0247, rel=1e-3)


def test_distributable_title_variant_this_period_only():
    """「3.3.1 本报告期的可供分配金额」标题变体：本期行两个数值正常解析。"""
    text = (
        "3.3.1 本报告期的可供分配金额\n"
        "期间\n可供分配金额\n单位可供分配金额\n备注\n"
        "本期\n23,695,441.92\n0.0247\n-\n"
        "本年累计\n49,484,408.58\n0.0515\n-"
    )
    distributable, unit = parser_quarterly._parse_distributable(text)

    assert distributable == pytest.approx(23695441.92)
    assert unit == pytest.approx(0.0247)


def test_distributable_title_variant_three_years():
    """「3.3.1 本报告期及近三年的可供分配金额」标题变体：本期行两个数值正常解析。"""
    text = (
        "3.3.1 本报告期及近三年的可供分配金额\n"
        "期间\n可供分配金额\n单位可供分配金额\n备注\n"
        "本期\n23,695,441.92\n0.0247\n-\n"
        "本年累计\n49,484,408.58\n0.0515\n-"
    )
    distributable, unit = parser_quarterly._parse_distributable(text)

    assert distributable == pytest.approx(23695441.92)
    assert unit == pytest.approx(0.0247)


def test_revenue_income_label_alias_zhaiwu_total_revenue():
    """3.1 主要财务指标收入列标签可为「营业总收入」（部分管理人表述）；
    「本期收入」缺省时回退到「营业总收入」。"""
    text = (
        "3.1 主要财务指标\n"
        "1.营业总收入\n30,650,710.62\n"
        "2.本期净利润\n-11,644,536.88"
    )
    result = parser_quarterly.parse_quarterly(text)

    assert result["revenue_wan"] == pytest.approx(3065.07)


def test_revenue_income_label_prefers_period_income():
    """同一文本同时含「本期收入」与「营业总收入」时，优先取「本期收入」。"""
    text = (
        "3.1 主要财务指标\n"
        "1.本期收入\n31,111,111.11\n"
        "2.营业总收入\n30,650,710.62"
    )
    result = parser_quarterly.parse_quarterly(text)

    assert result["revenue_wan"] == pytest.approx(3111.11)


def test_ebitda_skips_narrative_mention_and_uses_table_value():
    """EBITDA 叙述段（如「收入和EBITDA同比下降超过10%」）不应被当作财务值；
    应取财务表格行的当期 EBITDA。"""
    text = (
        "可供分配金额较上年同期下降超过10%，使得基金收入和EBITDA同比\n"
        "下降超过10%。\n"
        "序号\n科目名称\n报告期金额（元）\n上年同期金额（元）\n"
        "3\nEBITDA\n264,743,937.70\n311,638,399.00\n-16.39\n"
    )
    result = parser_quarterly.parse_quarterly(text)

    assert result["ebitda_wan"] == pytest.approx(26474.39)


def test_ebitda_missing_returns_none():
    """无 EBITDA 表格（且无叙述提及）→ ebitda_wan 为 None。"""
    result = parser_quarterly.parse_quarterly("3.1 主要财务指标\n1.本期收入\n30,650,710.62")

    assert result["ebitda_wan"] is None
