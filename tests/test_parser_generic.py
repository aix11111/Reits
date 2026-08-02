"""tools.reits_collector.parser_generic 模块（通用月度运营公告解析）的单元测试。

使用 5 只高速公路 REITs 的真实月度运营公告 PDF 做全链路断言
（extract_text + parse_generic_monthly），覆盖不同基金管理人公告在
项目名、千分位逗号、收入小数位、百分比小数位、年份写法、表头换行位置
等方面的差异；并覆盖中文数字报告期转换与解析失败路径。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_generic

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED = {
    "monthly_180202_202606.pdf": {
        "period": "2026-06",
        "project_name": "湖北汉孝高速",
        "daily_traffic": 34452,
        "traffic_mom": 26.4,
        "traffic_yoy": 4.6,
        "traffic_cum": 34347,
        "traffic_cum_yoy": 0.0,
        "toll_revenue_wan": 1916,
        "revenue_mom": 16.1,
        "revenue_yoy": 6.3,
        "revenue_cum": 11431,
        "revenue_cum_yoy": 1.5,
    },
    "monthly_508008_202606.pdf": {
        "period": "2026-06",
        "project_name": "渝遂高速",
        "daily_traffic": 19809,
        "traffic_mom": -3.58,
        "traffic_yoy": -14.05,
        "traffic_cum": 22762,
        "traffic_cum_yoy": -5.33,
        "toll_revenue_wan": 5276.55,
        "revenue_mom": 15.0,
        "revenue_yoy": -13.44,
        "revenue_cum": 31375.23,
        "revenue_cum_yoy": -5.05,
    },
    "monthly_508018_202606.pdf": {
        "period": "2026-06",
        "project_name": "嘉通高速",
        "daily_traffic": 26213,
        "traffic_mom": 19.9,
        "traffic_yoy": 9.6,
        "traffic_cum": 26551,
        "traffic_cum_yoy": 5.7,
        "toll_revenue_wan": 3804,
        "revenue_mom": 5.8,
        "revenue_yoy": 19.1,
        "revenue_cum": 23520,
        "revenue_cum_yoy": 13.7,
    },
    "monthly_508066_202606.pdf": {
        "period": "2026-06",
        "project_name": "沪苏浙高速公路",
        "daily_traffic": 52634,
        "traffic_mom": 21.67,
        "traffic_yoy": 22.32,
        "traffic_cum": 49136,
        "traffic_cum_yoy": 18.18,
        "toll_revenue_wan": 4389.39,
        "revenue_mom": 13.65,
        "revenue_yoy": 21.50,
        "revenue_cum": 24803.57,
        "revenue_cum_yoy": 20.10,
    },
    "monthly_180201_202606.pdf": {
        "period": "2026-06",
        "project_name": "广河高速广州段",
        "daily_traffic": 147050,
        "traffic_mom": 21.52,
        "traffic_yoy": 0.43,
        "traffic_cum": 137359,
        "traffic_cum_yoy": 2.8,
        "toll_revenue_wan": 6106,
        "revenue_mom": 16.13,
        "revenue_yoy": -3.63,
        "revenue_cum": 35975,
        "revenue_cum_yoy": -1.22,
    },
    "monthly_180202_202605.pdf": {
        "period": "2026-05",
        "project_name": "湖北汉孝高速",
        "daily_traffic": 27250,
        "traffic_mom": -10.5,
        "traffic_yoy": -3.9,
        "traffic_cum": 34326,
        "traffic_cum_yoy": -0.9,
        "toll_revenue_wan": 1651,
        "revenue_mom": -6.4,
        "revenue_yoy": -1.1,
        "revenue_cum": 9515,
        "revenue_cum_yoy": 0.6,
    },
    "monthly_180202_202310.pdf": {
        "period": "2023-09",
        "project_name": "湖北汉孝高速",
        "daily_traffic": 31714,
        "traffic_mom": -14.5,
        "traffic_yoy": 24.0,
        "traffic_cum": 33674,
        "traffic_cum_yoy": 17.1,
        "toll_revenue_wan": 2014,
        "revenue_mom": -12.0,
        "revenue_yoy": 19.7,
        "revenue_cum": 18682,
        "revenue_cum_yoy": 16.8,
    },
}

EXPECTED_PDF = {
    "monthly_508009_202606.pdf": {
        "period": "2026-06",
        "project_name": "沿江高速",
        "daily_traffic": 19761,
        "traffic_mom": 12.55,
        "traffic_yoy": -2.12,
        "traffic_cum": 20633,
        "traffic_cum_yoy": -9.08,
        "toll_revenue_wan": 7186,
        "revenue_mom": 6.94,
        "revenue_yoy": -4.73,
        "revenue_cum": 42354,
        "revenue_cum_yoy": -8.98,
    },
    "monthly_508007_202606.pdf": {
        "period": "2026-06",
        "project_name": "鄄菏高速",
        "daily_traffic": 18835,
        "traffic_mom": 16.7,
        "traffic_yoy": 0.4,
        "traffic_cum": 18132,
        "traffic_cum_yoy": -3.8,
        "toll_revenue_wan": 2165,
        "revenue_mom": 12.4,
        "revenue_yoy": -1.0,
        "revenue_cum": 12127,
        "revenue_cum_yoy": -7.4,
    },
    "monthly_508036_202606.pdf": {
        "period": "2026-06",
        "project_name": "6月",
        "daily_traffic": 57911,
        "traffic_mom": 17.67,
        "traffic_yoy": -1.06,
        "traffic_cum": 52099,
        "traffic_cum_yoy": -4.53,
        "toll_revenue_wan": 19042,
        "revenue_mom": 9.19,
        "revenue_yoy": -1.15,
        "revenue_cum": 104686,
        "revenue_cum_yoy": -4.58,
    },
    "monthly_508020_202606.pdf": {
        "period": "2026-06",
        "project_name": "6月",
        "daily_traffic": 45237,
        "traffic_mom": 5.12,
        "traffic_yoy": 59.06,
        "traffic_cum": 44301,
        "traffic_cum_yoy": 80.04,
        "toll_revenue_wan": 4595.85,
        "revenue_mom": 2.03,
        "revenue_yoy": 58.44,
        "revenue_cum": 26294.52,
        "revenue_cum_yoy": 64.28,
    },
    "monthly_508069_202605.pdf": {
        "period": "2026-04",
        "project_name": "2026年4月",
        "daily_traffic": 37908,
        "traffic_mom": -5.5,
        "traffic_yoy": -8.0,
        "traffic_cum": 38802,
        "traffic_cum_yoy": -4.1,
        "toll_revenue_wan": 3917,
        "revenue_mom": -10.8,
        "revenue_yoy": -5.5,
        "revenue_cum": 15711,
        "revenue_cum_yoy": 0.2,
    },
}

VALUE_KEYS = (
    "daily_traffic",
    "traffic_mom",
    "traffic_yoy",
    "traffic_cum",
    "traffic_cum_yoy",
    "toll_revenue_wan",
    "revenue_mom",
    "revenue_yoy",
    "revenue_cum",
    "revenue_cum_yoy",
)


def _fixture_text(name):
    return parser_generic.extract_text(FIXTURES_DIR / name)


@pytest.mark.parametrize("pdf_name", list(EXPECTED))
def test_parse_generic_monthly_real_pdf(pdf_name):
    text = _fixture_text(pdf_name)
    result = parser_generic.parse_generic_monthly(text)
    exp = EXPECTED[pdf_name]

    assert result["period"] == exp["period"]
    assert result["project_name"] == exp["project_name"]
    for key in VALUE_KEYS:
        assert result[key] == pytest.approx(exp[key])


@pytest.mark.parametrize("pdf_name", list(EXPECTED_PDF))
def test_parse_pdf_real_pdf(pdf_name):
    """坐标版 parse_pdf 覆盖 5 种新公告格式（含“自然/通行费”表头与单项目月份列）。"""
    result = parser_generic.parse_pdf(FIXTURES_DIR / pdf_name)
    exp = EXPECTED_PDF[pdf_name]

    assert result["period"] == exp["period"]
    assert result["project_name"] == exp["project_name"]
    for key in VALUE_KEYS:
        assert result[key] == pytest.approx(exp[key])


@pytest.mark.parametrize(
    "period_raw, expected",
    [
        ("2026 年6 月", "2026-06"),
        ("2026年6月", "2026-06"),
        ("2026 年6 月", "2026-06"),
        ("二〇二六年六月", "2026-06"),
        ("二零二六年六月", "2026-06"),
        ("二〇二六年十月", "2026-10"),
        ("二〇二六年十二月", "2026-12"),
    ],
)
def test_parse_period_supports_arabic_and_chinese_digits(period_raw, expected):
    text = (
        "公告送出日期：2026年07月21日\n"
        f"关于{period_raw}主要运营数据的公告\n"
        "项目\n"
        "日均收费车流量（辆次）\n"
        "路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n变动\n当月同比\n变动\n2026年\n累计\n累计同比\n变动\n"
        "当月\n当月环比\n变动\n当月同比\n变动\n2026年\n累计\n累计同比\n变动\n"
        "测试高速\n"
        "100,000 5.0% -1.0% 90,000 3.0%\n"
        "5,000 10.0% -4.0% 40,000 -2.5%\n"
        "备注："
    )

    result = parser_generic.parse_generic_monthly(text)

    assert result["period"] == expected


def test_note_numbers_are_not_mixed_into_values():
    """备注中的大量车流量数字不得污染表格数值。"""
    text = (
        "关于二〇二六年六月主要运营数据的公告\n"
        "项目\n"
        "日均收费车流量（辆次）\n"
        "路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环\n比变动\n当月同\n比变动\n2026年\n累计\n累计同\n比变动\n"
        "当月\n当月环\n比变动\n当月同\n比变动\n2026年累计\n累计同比\n变动\n"
        "沪苏浙\n高速公路\n"
        "52,634\n21.67%\n22.32%\n49,136\n18.18%\n"
        "4,389.39\n13.65%\n21.50%\n24,803.57\n20.10%\n"
        "备注：①日均收费车流量为 52,634 辆次，同比 22.32%，"
        "累计为 63,133 辆次，同比 14.58%；②其他说明。"
    )

    result = parser_generic.parse_generic_monthly(text)

    assert result["project_name"] == "沪苏浙高速公路"
    assert result["daily_traffic"] == pytest.approx(52634)
    assert result["traffic_yoy"] == pytest.approx(22.32)
    assert result["traffic_cum"] == pytest.approx(49136)
    assert result["toll_revenue_wan"] == pytest.approx(4389.39)
    assert result["revenue_cum_yoy"] == pytest.approx(20.10)


def test_parse_generic_monthly_with_project_name_on_value_line():
    """项目名与第一个数值在同一行（如“湖北汉孝高速 27,250”）也能正确解析。"""
    text = (
        "关于二〇二六年六月主要运营数据的公告\n"
        "项目\n"
        "日均收费车流量（辆次）\n"
        "路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n变动\n当月同比\n变动\n2026年\n累计\n累计同比\n变动\n"
        "当月\n当月环比\n变动\n当月同比\n变动\n2026年\n累计\n累计同比\n变动\n"
        "测试高速 100,000\n"
        "5.0% -1.0% 90,000 3.0%\n"
        "5,000 10.0% -4.0% 40,000 -2.5%\n"
        "备注："
    )

    result = parser_generic.parse_generic_monthly(text)

    assert result["project_name"] == "测试高速"
    assert result["daily_traffic"] == pytest.approx(100000)
    assert result["traffic_mom"] == pytest.approx(5.0)
    assert result["traffic_yoy"] == pytest.approx(-1.0)
    assert result["traffic_cum"] == pytest.approx(90000)
    assert result["traffic_cum_yoy"] == pytest.approx(3.0)
    assert result["toll_revenue_wan"] == pytest.approx(5000)
    assert result["revenue_mom"] == pytest.approx(10.0)
    assert result["revenue_yoy"] == pytest.approx(-4.0)
    assert result["revenue_cum"] == pytest.approx(40000)
    assert result["revenue_cum_yoy"] == pytest.approx(-2.5)


def test_parse_generic_monthly_raises_without_table_headers():
    with pytest.raises(ValueError):
        parser_generic.parse_generic_monthly("这是一份没有运营数据表格的公告文本")


def test_parse_generic_monthly_raises_when_revenue_header_missing():
    text = (
        "关于二〇二六年六月主要运营数据的公告\n"
        "项目\n日均收费车流量（辆次）\n当月\n当月环比\n"
        "测试高速\n1 2 3 4 5\n备注："
    )

    with pytest.raises(ValueError):
        parser_generic.parse_generic_monthly(text)


def test_parse_generic_monthly_raises_when_too_few_numbers():
    text = (
        "关于二〇二六年六月主要运营数据的公告\n"
        "项目\n日均收费车流量（辆次）\n路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n2026年\n累计\n测试高速\n100,000 5.0%\n备注："
    )

    with pytest.raises(ValueError):
        parser_generic.parse_generic_monthly(text)


def test_parse_generic_monthly_raises_when_project_name_missing():
    text = (
        "关于二〇二六年六月主要运营数据的公告\n"
        "项目\n日均收费车流量（辆次）\n路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n2026年\n累计\n"
        "100,000 5.0% -1.0% 90,000 3.0%\n"
        "5,000 10.0% -4.0% 40,000 -2.5%\n备注："
    )

    with pytest.raises(ValueError):
        parser_generic.parse_generic_monthly(text)


def test_parse_generic_monthly_raises_when_period_missing():
    text = (
        "项目\n"
        "日均收费车流量（辆次）\n"
        "路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n2026年\n累计\n测试高速\n"
        "100,000 5.0% -1.0% 90,000 3.0%\n"
        "5,000 10.0% -4.0% 40,000 -2.5%\n备注："
    )

    with pytest.raises(ValueError):
        parser_generic.parse_generic_monthly(text)
