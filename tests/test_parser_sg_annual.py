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
A17U_FIXTURE_TEXT = (FIXTURES_DIR / "sg_ascendas_ar2025.txt").read_text(
    encoding="utf-8"
)
KEPPEL_FIXTURE_TEXT = (FIXTURES_DIR / "sg_keppel_ar2025.txt").read_text(
    encoding="utf-8"
)
ODBU_FIXTURE_TEXT = (FIXTURES_DIR / "sg_odbu_ar2025.txt").read_text(encoding="utf-8")
UD1U_FIXTURE_TEXT = (FIXTURES_DIR / "sg_ud1u_ar2025.txt").read_text(encoding="utf-8")
INTERIM_FIXTURE_TEXT = (FIXTURES_DIR / "sg_cict_interim_2025.txt").read_text(
    encoding="utf-8"
)


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


def test_parse_sg_interim_text_fixture():
    """C38U 1H 2025 半年业绩公告：period=interim、fy=2025H1；
    S$'000 损益表 ×0.1（787,646 → 78764.6）；DPU 取「for the period / year」
    首列半年值 5.62（不能与 annual 10.88 混用）。"""
    result = parser_sg_annual._parse_sg_annual_text(
        INTERIM_FIXTURE_TEXT, period="interim"
    )
    assert result["period"] == "interim"
    assert result["fy"] == "2025H1"
    assert result["currency"] == "SGD"
    assert result["revenue_wan"] == 78764.6
    assert result["npi_wan"] == 57986.5
    assert result["distributable_wan"] == 41188.9
    assert result["dpu_cents"] == 5.62


def test_parse_sg_interim_text_missing_fields_none():
    result = parser_sg_annual._parse_sg_annual_text("No data.", period="interim")
    assert result["period"] == "interim"
    assert result["fy"] is None
    assert result["revenue_wan"] is None
    assert result["dpu_cents"] is None


def test_parse_sg_interim_pdf_wrapper(tmp_path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 559, 800), INTERIM_FIXTURE_TEXT, fontsize=7)
    pdf_path = tmp_path / "sg_interim.pdf"
    doc.save(pdf_path)
    result = parser_sg_annual.parse_sg_interim(pdf_path)
    assert result["period"] == "interim"
    assert result["fiscal_year"] == "2025H1"
    assert result["revenue_wan"] == 78764.6
    assert result["dpu_cents"] == 5.62


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


def test_parse_sg_annual_text_a17u_before_label_five_year_table():
    """A17U 凯德系五年表：数字序列在行标签**前**（文本序首个值 = FY2025，最新列）。

    现有 parser 只找标签后数字 → 失败。标签前取文本序第一个值：
    revenue_wan = 1,538.6m → 153860.0（1,523.0 为 FY2024 值，见年报合并利润表
    "Revenue Group 2025 $'000 2024 $'000 ... 1,538,574 1,523,046"）；
    dpu = 15.005（财务表第一列 = FY2025）。
    """
    result = parser_sg_annual._parse_sg_annual_text(A17U_FIXTURE_TEXT)
    assert result["fy"] == "2025"
    assert result["revenue_wan"] == 153860.0
    assert result["dpu_cents"] == 15.005


def test_parse_sg_annual_text_keppel_narrative_dpu():
    """K71U 吉宝：叙述式 DPU「Distribution per Unit of 5.23 cents.」（of X cents 模式）。"""
    result = parser_sg_annual._parse_sg_annual_text(KEPPEL_FIXTURE_TEXT)
    assert result["fy"] == "2025"
    assert result["dpu_cents"] == 5.23


def test_parse_sg_annual_text_fiscal_year_cover_fallback():
    """3 月财年：封面「Annual Report 2024/25」→ "2024/25"。"""
    text = "Annual Report 2024/25  Active Rejuvenation Building Resilience"
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["fy"] == "2024/25"


def test_parse_sg_annual_text_two_column_fy_fy_take_first():
    """双列 FY2025 FY2024 模式：取第一列（最新财年）。"""
    text = (
        "The Manager's Review of FY 2025 Financial Performance\n"
        "FY 2025 FY 2024 Variance\n"
        "Gross Revenue (S$ million) 1,538.6 1,523.0 1.0%\n"
        "Net Property Income (S$ million) 1,067.6 1,049.9 1.7%\n"
        "Distribution Per Unit (cents) 15.005 15.205 -1.3%\n"
    )
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["revenue_wan"] == 153860.0
    assert result["npi_wan"] == 106760.0
    assert result["dpu_cents"] == 15.005


def test_parse_sg_annual_pdf_wrapper(tmp_path):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 559, 800), FIXTURE_TEXT, fontsize=7)
    pdf_path = tmp_path / "sg_ar.pdf"
    doc.save(pdf_path)
    result = parser_sg_annual.parse_sg_annual(pdf_path)
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 161920.0
    assert result["npi_wan"] == 118970.0
    assert result["dpu_cents"] == 11.58
    assert result["nav_per_unit"] == 2.14
    assert result["occupancy"] == 0.969


def test_parse_sg_annual_text_odbu_fixture():
    """ODBU UHREIT（US 计价）：dpu=4.39 US cents、nav=0.73、rev=7197.8
    （US$'000 表 ×0.1）保持；currency 按年报实际应为 USD。"""
    result = parser_sg_annual._parse_sg_annual_text(ODBU_FIXTURE_TEXT)
    assert result["fy"] == "2025"
    assert result["revenue_wan"] == 7197.8
    assert result["dpu_cents"] == 4.39
    assert result["nav_per_unit"] == 0.73
    assert result["currency"] == "USD"


def test_parse_sg_annual_text_ud1u_fixture_rev_reasonable():
    """UD1U IREIT Global（EUR 计价）：表格式提取抓到 46,328（EUR'000 被当
    million → 4632800）→ 量级防护拒绝；叙述式「gross revenue of €50.4
    million」→ 5040.0。rev 合理值（非 4632800）。"""
    result = parser_sg_annual._parse_sg_annual_text(UD1U_FIXTURE_TEXT)
    assert result["fy"] == "2025"
    assert result["revenue_wan"] != 4632800.0
    assert result["revenue_wan"] is None or result["revenue_wan"] < 20000


def test_parse_sg_annual_text_magnitude_guard():
    """量级防护：rev 提取值 4,632,800（> 上限 3,000,000）→ None。"""
    text = "Gross Revenue (S$ million)\n46,328\nNet Property Income (S$ million)\n34,623\n"
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["revenue_wan"] is None
    assert result["npi_wan"] is None


def test_parse_sg_annual_text_cover_fiscal_year_no_slash():
    """封面无斜线「Annual Report 2025」→ "2025"。"""
    text = "Annual Report 2025  Reaching New Heights"
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["fy"] == "2025"


def test_parse_sg_annual_text_cover_fiscal_year_fy_token():
    """封面「FY2025」→ "2025"。"""
    text = "FY2025  Annual Report"
    result = parser_sg_annual._parse_sg_annual_text(text)
    assert result["fy"] == "2025"
