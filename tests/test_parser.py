"""tools.reits_collector.parser 模块（公告 PDF 解析）的单元测试。

extract_text 使用 tests/fixtures/monthly_180201_202606.pdf 真实公告；
parse_monthly_announcement 覆盖广河 2026-06 实际数值、
正文日期与表头年份交错、以及解析失败的 ValueError 路径。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "monthly_180201_202606.pdf"


def _fixture_text():
    """读取真实公告 PDF 全文，用于解析测试。"""
    return parser.extract_text(FIXTURE_PDF)


def test_extract_text_returns_full_pdf_text():
    text = _fixture_text()

    assert isinstance(text, str)
    assert "日均收费车流量" in text
    assert "路费收入" in text
    assert "147,050" in text
    assert "备注" in text


def test_parse_monthly_announcement_actual_values_from_fixture():
    result = parser.parse_monthly_announcement(_fixture_text())

    assert result["period"] == "2026-06"
    assert result["daily_traffic"] == 147050
    assert result["traffic_mom"] == pytest.approx(21.52)
    assert result["traffic_yoy"] == pytest.approx(0.43)
    assert result["traffic_cum"] == 137359
    assert result["traffic_cum_yoy"] == pytest.approx(2.80)
    assert result["toll_revenue_wan"] == 6106
    assert result["revenue_mom"] == pytest.approx(16.13)
    assert result["revenue_yoy"] == pytest.approx(-3.63)
    assert result["revenue_cum"] == 35975
    assert result["revenue_cum_yoy"] == pytest.approx(-1.22)


def test_parse_period_from_body_not_send_date():
    """正文含 2026 年6 月，即使前面有 2026年07月21日 也不应误取 2026-07。"""
    text = (
        "公告送出日期：2026年07月21日\n"
        "二、\n2026 年6 月主要运营数据\n"
        "项目\n日均收费车流量（辆次）\n路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n当月同比\n累计\n累计同比\n"
        "广河高速\n广州段\n"
        "147,050 21.52% 0.43% 137,359 2.80%\n"
        "6,106 16.13% -3.63% 35,975 -1.22%\n"
        "备注：说明"
    )

    result = parser.parse_monthly_announcement(text)

    assert result["period"] == "2026-06"


def test_parse_monthly_announcement_interleaved_labels_and_commas():
    """文本中数值与中文标签交错、含千分位逗号时应稳健解析。"""
    text = (
        "二、\n2026 年6 月主要运营数据\n"
        "项目\n日均收费车流量（辆次）\n路费收入（人民币，万元，含增值税）\n"
        "当月\n当月环比\n变动\n当月同比\n变动\n累计\n累计同比\n变动\n"
        "广河高速\n广州段\n"
        "100,000 5.5% -1.2%\n90,000\n3.0%\n"
        "5,000\n10.0% -4.0% 40,000 -2.5%\n"
        "备注：以上未经审计"
    )

    result = parser.parse_monthly_announcement(text)

    assert result["period"] == "2026-06"
    assert result["daily_traffic"] == 100000
    assert result["traffic_mom"] == pytest.approx(5.5)
    assert result["traffic_yoy"] == pytest.approx(-1.2)
    assert result["traffic_cum"] == 90000
    assert result["traffic_cum_yoy"] == pytest.approx(3.0)
    assert result["toll_revenue_wan"] == 5000
    assert result["revenue_mom"] == pytest.approx(10.0)
    assert result["revenue_yoy"] == pytest.approx(-4.0)
    assert result["revenue_cum"] == 40000
    assert result["revenue_cum_yoy"] == pytest.approx(-2.5)


def test_parse_monthly_announcement_raises_without_headers():
    with pytest.raises(ValueError):
        parser.parse_monthly_announcement("这是一份没有运营数据表格的公告文本")


def test_parse_monthly_announcement_raises_when_revenue_header_missing():
    text = (
        "日均收费车流量（辆次）\n"
        "广河高速\n广州段\n147,050 21.52% 0.43% 137,359 2.80%\n备注："
    )

    with pytest.raises(ValueError):
        parser.parse_monthly_announcement(text)


def test_parse_monthly_announcement_raises_when_too_few_numbers():
    text = (
        "日均收费车流量（辆次）\n路费收入（人民币，万元，含增值税）\n"
        "广河高速\n广州段\n147,050 21.52%\n备注："
    )

    with pytest.raises(ValueError):
        parser.parse_monthly_announcement(text)
