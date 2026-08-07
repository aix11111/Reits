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
SUNLIGHT_FIXTURE = (FIXTURES_DIR / "hk_sunlight_ar2025.txt").read_text(encoding="utf-8")
PROSPERITY_FIXTURE = (FIXTURES_DIR / "hk_prosperity_ar2025.txt").read_text(
    encoding="utf-8"
)
SFREIT_FIXTURE = (FIXTURES_DIR / "hk_sfreit_ar2025.txt").read_text(encoding="utf-8")
FORTUNE_FIXTURE = (FIXTURES_DIR / "hk_fortune_ar2025.txt").read_text(
    encoding="utf-8"
)
HUIXIAN_FIXTURE = (FIXTURES_DIR / "hk_huixian_ar2025.txt").read_text(
    encoding="utf-8"
)
FORTUNE_INTERIM_FIXTURE = (FIXTURES_DIR / "hk_fortune_interim_2025.txt").read_text(
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


def test_extract_fiscal_year_interim_h1():
    assert (
        parser_hk_annual._extract_fiscal_year(
            "截至2025年6月30日止六個月 收益 854.5百萬港元", period="interim"
        )
        == "2025H1"
    )
    assert (
        parser_hk_annual._extract_fiscal_year(
            "for the six months ended 30 September 2025 領展", period="interim"
        )
        == "2025H1"
    )


def test_parse_hk_annual_text_fixture():
    result = parser_hk_annual._parse_hk_annual_text(FIXTURE_TEXT)
    assert result["period"] == "annual"
    assert result["fiscal_year"] == "2024/25"
    assert result["revenue_wan"] == 1422300.0
    assert result["npi_wan"] == 1061900.0
    assert result["dpu_hk_cents"] == 272.34
    assert result["nav_per_unit_hkd"] == 63.30
    assert result["occupancy"] is None or isinstance(result["occupancy"], dict)


def test_parse_hk_annual_text_interim_fixture():
    result = parser_hk_annual._parse_hk_annual_text(
        FORTUNE_INTERIM_FIXTURE, period="interim"
    )
    assert result["period"] == "interim"
    assert result["fiscal_year"] == "2025H1"
    assert result["revenue_wan"] == 85450.0
    assert result["dpu_hk_cents"] == 18.41


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


def test_parse_hk_annual_text_sunlight():
    result = parser_hk_annual._parse_hk_annual_text(SUNLIGHT_FIXTURE)
    assert result["revenue_wan"] == 77810.0
    assert result["npi_wan"] == 60100.0
    assert result["dpu_hk_cents"] == 18.2
    assert result["nav_per_unit_hkd"] == 7.09
    assert result["fiscal_year"] == "2025"


def test_parse_hk_annual_text_prosperity():
    result = parser_hk_annual._parse_hk_annual_text(PROSPERITY_FIXTURE)
    assert result["revenue_wan"] == 40850.0
    assert result["npi_wan"] == 30520.0
    assert result["dpu_hk_cents"] == 11.56
    assert result["fiscal_year"] == "2025"


def test_parse_hk_annual_text_sfreit():
    result = parser_hk_annual._parse_hk_annual_text(SFREIT_FIXTURE)
    assert result["revenue_wan"] is not None or result["npi_wan"] is not None


def test_parse_hk_annual_text_fortune_narrative_dpu():
    result = parser_hk_annual._parse_hk_annual_text(FORTUNE_FIXTURE)
    assert result["fiscal_year"] == "2025"
    assert result["dpu_hk_cents"] == 35.22
    assert result["revenue_wan"] == 168240.0
    assert result["npi_wan"] == 118810.0


def test_parse_hk_annual_text_sfreit_summary_table():
    result = parser_hk_annual._parse_hk_annual_text(SFREIT_FIXTURE)
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 617080.0
    assert result["npi_wan"] == 46040.0
    assert result["dpu_hk_cents"] == 26.33
    assert result["nav_per_unit_hkd"] == 3.88


def test_parse_hk_annual_text_huixian_nav_per_unit():
    result = parser_hk_annual._parse_hk_annual_text(HUIXIAN_FIXTURE)
    assert result["fiscal_year"] == "2025"
    assert result["nav_per_unit_hkd"] == 3.1737


def test_cn_wan_amount():
    assert parser_hk_annual._cn_wan("二十二億零九百萬元") == 220900
    assert parser_hk_annual._cn_wan("十一億四千六百萬元") == 114600
    assert parser_hk_annual._cn_wan("一億二千八百萬元") == 12800
    assert parser_hk_annual._cn_wan("二千萬元") == 2000
    assert parser_hk_annual._cn_wan("五億") == 50000
    assert parser_hk_annual._cn_wan("一千二百萬元") == 1200


def test_parse_hk_annual_text_cn_narrative_amount():
    text = (
        "匯賢產業信託於二零二五年收益減少人民幣一億二千八百萬元至人民幣二十二億零九百萬元。"
        "物業收入淨額減少人民幣一億五千七百萬元至人民幣十一億四千六百萬元。"
        "截至二零二五年十二月三十一日止年度，每基金單位分派為人民幣0.0043元。"
    )
    result = parser_hk_annual._parse_hk_annual_text(text)
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 220900.0
    assert result["npi_wan"] == 114600.0
    assert result["dpu_hk_cents"] == 0.43


def test_parse_hk_annual_text_revenue_not_yield_ratio():
    text = (
        "財務摘要\n收益率為6.6%。\n收益 港幣100百萬元\n物業收入淨額 港幣70百萬元\n"
        "截至2025年12月31日止年度\n"
    )
    result = parser_hk_annual._parse_hk_annual_text(text)
    assert result["revenue_wan"] == 10000.0
    assert result["npi_wan"] == 7000.0


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
