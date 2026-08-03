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
