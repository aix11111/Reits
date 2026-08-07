"""tools.reits_collector.parser_sg_annual 模块（新加坡年报财务摘要解析）的单元测试。

真实 CICT FY2025 年报 fixture（sg_cict_ar2025.txt，Financial Highlights + 五年摘要表
+ 叙述段落）解析出 revenue_wan=161920.0 / npi_wan=118970.0 / distributable_wan=86090.0
/ dpu_cents=11.58 / nav_per_unit=2.14 / occupancy=0.969 / fy="2025" / currency="SGD"
/ period="annual"。

覆盖：五年摘要表优先（行标签 + 数字序列取最新列）、S$b 单位换算、叙述式兜底
（"DPU rose 6.4% YoY to 11.58 cents"）、缺字段 → None、parse_sg_annual PDF 薄封装。
"""

from pathlib import Path

from tools.reits_collector import parser_sg_annual

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "sg_cict_ar2025.txt").read_text(encoding="utf-8")


def test_parse_sg_annual_text_fixture():
    result = parser_sg_annual._parse_sg_annual_text(FIXTURE_TEXT)
    assert result["period"] == "annual"
    assert result["fy"] == "2025"
    assert result["currency"] == "SGD"
    assert result["revenue_wan"] == 161920.0
    assert result["npi_wan"] == 118970.0
    assert result["distributable_wan"] == 86090.0
    assert result["dpu_cents"] == 11.58
    assert result["nav_per_unit"] == 2.14
    assert result["occupancy"] == 0.969


def test_parse_sg_annual_text_missing_fields_none():
    result = parser_sg_annual._parse_sg_annual_text(
        "No financial data here at all."
    )
    assert result["fy"] is None
    assert result["revenue_wan"] is None
    assert result["npi_wan"] is None
    assert result["distributable_wan"] is None
    assert result["dpu_cents"] is None
    assert result["nav_per_unit"] is None
    assert result["occupancy"] is None
    assert result["currency"] == "SGD"
    assert result["period"] == "annual"


def test_parse_sg_annual_text_sb_unit_scale():
    text = (
        "Selected Statement of Total Return and Distribution Data (S$ billion)\n"
        "Gross Revenue 1.3 1.4 1.5 1.6 1.7\n"
        "Net Property Income 0.9 1.0 1.1 1.2 1.3\n"
        "Distributable Income 0.5 0.6 0.7 0.8 0.9\n"
        "for the financial year ended 31 December 2025\n"
    )
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["fy"] == "2025"
    assert result["revenue_wan"] == 170000.0
    assert result["npi_wan"] == 130000.0
    assert result["distributable_wan"] == 90000.0


def test_parse_sg_annual_text_narrative_dpu_and_nav():
    text = (
        "DPU rose 6.4% YoY to 11.58 cents. "
        "Net asset value per Unit increased 0.9% to S$2.14. "
        "for the financial year ended 31 December 2025"
    )
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["fy"] == "2025"
    assert result["dpu_cents"] == 11.58
    assert result["nav_per_unit"] == 2.14


def test_parse_sg_annual_text_narrative_occupancy():
    text = "Committed occupancy stood at 96.9% as at 31 December 2025."
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["occupancy"] == 0.969


def test_parse_sg_annual_text_empty():
    result = parser_sg_annual._parse_sg_annual_text("")
    assert result["fy"] is None
    assert result["revenue_wan"] is None


def test_parse_sg_annual_pdf_wrapper(tmp_path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 559, 800), FIXTURE_TEXT, fontsize=7)
    pdf_path = tmp_path / "sg_ar.pdf"
    doc.save(pdf_path)
    result = parser_sg_annual.parse_sg_annual(pdf_path)
    assert result["fy"] == "2025"
    assert result["revenue_wan"] == 161920.0
    assert result["npi_wan"] == 118970.0
    assert result["dpu_cents"] == 11.58
    assert result["nav_per_unit"] == 2.14
    assert result["occupancy"] == 0.969
