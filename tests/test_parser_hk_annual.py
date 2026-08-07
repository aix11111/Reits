"""tools.reits_collector.parser_hk_annual 模块（港年报财务摘要解析）的单元测试。

真实港年报 fixture（hk_linkreit_ar2425_financials.txt，领展 2024/25 年报
Financial Highlights 段落 + 财年句）解析出 fiscal_year="2024/25" /
revenue_wan=1422300.0 / npi_wan=1061900.0 / dpu_hk_cents=272.34 /
nav_per_unit_hkd=63.30 / occupancy 为 dict 或 None。

覆盖：财年提取（3 月末 → "2024/25"、12 月末 → "2025"、缺失 → None）、
断行数字（HK$14,223\\nM）+ label 前后顺序、缺字段 → None、
_parse_hk_annual_text 真实 fixture 端到端、parse_hk_annual PDF 薄封装
（fitz 生成临时 PDF 实测提取路径）。
"""

from pathlib import Path

from tools.reits_collector import parser_hk_annual

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "hk_linkreit_ar2425_financials.txt").read_text(
    encoding="utf-8"
)


def test_extract_fiscal_year_march_end():
    assert (
        parser_hk_annual._extract_fiscal_year(
            "Average all-in borrowing cost for the year ended 31 March 2025"
        )
        == "2024/25"
    )


def test_extract_fiscal_year_december_end():
    assert (
        parser_hk_annual._extract_fiscal_year(
            "for the year ended 31 December 2025"
        )
        == "2025"
    )


def test_extract_fiscal_year_missing():
    assert parser_hk_annual._extract_fiscal_year("no fiscal year here") is None


def test_parse_hk_annual_text_fixture():
    result = parser_hk_annual._parse_hk_annual_text(FIXTURE_TEXT)
    assert result["fiscal_year"] == "2024/25"
    assert result["revenue_wan"] == 1422300.0
    assert result["npi_wan"] == 1061900.0
    assert result["dpu_hk_cents"] == 272.34
    assert result["nav_per_unit_hkd"] == 63.30
    assert result["occupancy"] is None or isinstance(result["occupancy"], dict)


def test_parse_hk_annual_text_broken_line_numbers():
    text = (
        "Financial Highlights\n"
        "HK$14,223\nM\n"
        "Revenue\n"
        "HK$10,619\nM\n"
        "Net Property Income\n"
        "HK¢272.34\n"
        "Distribution per Unit\n"
        "HK$63.30\n"
        "Net Asset Value per Unit\n"
        "Retail\n"
        "97.8%\n"
        "for the year ended 31 March 2025\n"
    )
    result = parser_hk_annual._parse_hk_annual_text(text)
    assert result["fiscal_year"] == "2024/25"
    assert result["revenue_wan"] == 1422300.0
    assert result["npi_wan"] == 1061900.0
    assert result["dpu_hk_cents"] == 272.34
    assert result["nav_per_unit_hkd"] == 63.30
    assert result["occupancy"] == {"retail": 0.978}


def test_parse_hk_annual_text_label_before_value():
    text = (
        "Financial Highlights\n"
        "Revenue HK$14,223M\n"
        "Net Property Income HK$10,619M\n"
        "Distribution per Unit HK¢272.34\n"
        "Net Asset Value per Unit HK$63.30\n"
        "Retail 97.8%\n"
        "for the year ended 31 December 2025\n"
    )
    result = parser_hk_annual._parse_hk_annual_text(text)
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 1422300.0
    assert result["npi_wan"] == 1061900.0
    assert result["dpu_hk_cents"] == 272.34
    assert result["nav_per_unit_hkd"] == 63.30
    assert result["occupancy"] == {"retail": 0.978}


def test_parse_hk_annual_text_missing_fields():
    result = parser_hk_annual._parse_hk_annual_text(
        "Financial Highlights\nNothing relevant here\n"
    )
    assert result["fiscal_year"] is None
    assert result["revenue_wan"] is None
    assert result["npi_wan"] is None
    assert result["dpu_hk_cents"] is None
    assert result["nav_per_unit_hkd"] is None
    assert result["occupancy"] is None


def test_parse_hk_annual_pdf_wrapper(tmp_path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 559, 800), FIXTURE_TEXT, fontsize=7)
    pdf_path = tmp_path / "ar.pdf"
    doc.save(pdf_path)
    result = parser_hk_annual.parse_hk_annual(pdf_path)
    assert result["fiscal_year"] == "2024/25"
    assert result["revenue_wan"] == 1422300.0
    assert result["npi_wan"] == 1061900.0
    assert result["dpu_hk_cents"] == 272.34
    assert result["nav_per_unit_hkd"] == 63.30
    assert result["occupancy"] is None or isinstance(result["occupancy"], dict)
