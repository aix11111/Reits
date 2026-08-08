"""tools.reits_collector.parser_us_10k 模块（美国 10-K HTML 解析）的单元测试。

真实 PLD FY2025 10-K 关键段 fixture（us_pld_10k_2025.txt，EDGAR HTML 剥离后文本）
解析出 fiscal_year="2025" / revenue_wan=879012.7（Total revenues $000 → ×0.1）
/ dpu_usd=4.04（quarterly cash dividends of $1.01 ×4）/ currency="USD"。

覆盖：strip_html 纯函数（标签剥离、&#160;/&nbsp;→空格、&#8217;→'、空白压缩）、
损益表 Total revenues 行提取、股息季度/年度/每股措辞、缺失字段 → None。
NOI/FFO 在 10-K 中常缺失（PLD 实际在补充材料），如实 None，不强制。
"""

from pathlib import Path

from tools.reits_collector import parser_us_10k

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "us_pld_10k_2025.txt").read_text(encoding="utf-8")


def test_strip_html_removes_tags():
    html = "<html><body><p>Hello <b>World</b></p></body></html>"
    assert parser_us_10k.strip_html(html) == "Hello World"


def test_strip_html_entities_and_whitespace():
    html = (
        "<p>Total&#160;&#160;revenues&#160;8,790,127</p>"
        "<p>It&#8217;s&nbsp;fine</p>"
    )
    result = parser_us_10k.strip_html(html)
    assert "&#160;" not in result
    assert "&#8217;" not in result
    assert "&nbsp;" not in result
    assert "8,790,127" in result
    assert "It's fine" in result


def test_strip_html_collapses_whitespace():
    html = "<tr>\n  <td>  Total   revenues  </td>\n</tr>"
    assert parser_us_10k.strip_html(html) == "Total revenues"


def test_parse_us_10k_pld_fixture():
    result = parser_us_10k.parse_us_10k(FIXTURE_TEXT)
    assert result["period"] == "annual"
    assert result["currency"] == "USD"
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 879012.7
    assert result["dpu_usd"] == 4.04


def test_parse_us_10k_pld_fixture_noi_ffo_optional():
    """PLD 10-K 损益表无 NOI 行、FFO 实际在补充材料——如实 None（不强制）。"""
    result = parser_us_10k.parse_us_10k(FIXTURE_TEXT)
    assert result["noi_wan"] is None or result["noi_wan"] > 0
    assert result["ffo_wan"] is None or result["ffo_wan"] > 0


def test_parse_us_10k_missing_fields_none():
    result = parser_us_10k.parse_us_10k("No financial data here at all.")
    assert result["fiscal_year"] is None
    assert result["revenue_wan"] is None
    assert result["noi_wan"] is None
    assert result["ffo_wan"] is None
    assert result["dpu_usd"] is None
    assert result["occupancy"] is None
    assert result["currency"] == "USD"
    assert result["period"] == "annual"


def test_parse_us_10k_fiscal_year():
    html = "PROLOGIS, INC. CONSOLIDATED STATEMENTS OF INCOME (In thousands) Years Ended December 31, 2025 2024 2023"
    result = parser_us_10k.parse_us_10k(html)
    assert result["fiscal_year"] == "2025"


def test_parse_us_10k_revenue_thousands_scale():
    html = (
        "CONSOLIDATED STATEMENTS OF INCOME (In thousands, except per share amounts)\n"
        "Years Ended December 31, 2025 2024 2023\n"
        "Revenues: Rental $ 8,158,904 $ 7,514,705 $ 6,818,542\n"
        "Total revenues 8,790,127 8,201,610 8,023,469\n"
        "Expenses: Rental 1,964,137 1,765,385 1,624,793\n"
    )
    result = parser_us_10k.parse_us_10k(html)
    assert result["fiscal_year"] == "2025"
    assert result["revenue_wan"] == 879012.7


def test_parse_us_10k_revenue_millions_scale():
    html = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS (in millions, except per share data)\n"
        "Year Ended December 31, 2025 2024 2023\n"
        "REVENUES: Property $ 10,305.0 $ 9,933.5 $ 9,869.2\n"
        "Total operating revenues 10,644.6 10,127.2 10,012.2\n"
        "OPERATING EXPENSES: Costs of operations 2,574.1 2,481.8\n"
    )
    result = parser_us_10k.parse_us_10k(html)
    assert result["revenue_wan"] == 1064460.0


def test_parse_us_10k_dpu_quarterly():
    result = parser_us_10k.parse_us_10k(
        "We paid quarterly cash dividends of $1.01 and $0.96 per common share in 2025."
    )
    assert result["dpu_usd"] == 4.04


def test_parse_us_10k_dpu_annual():
    result = parser_us_10k.parse_us_10k(
        "We declared annual dividends of $2.50 per share."
    )
    assert result["dpu_usd"] == 2.50


def test_parse_us_10k_dpu_declared_per_share():
    result = parser_us_10k.parse_us_10k(
        "We paid dividends declared per share $3.10 during the year."
    )
    assert result["dpu_usd"] == 3.10


def test_parse_us_10k_dpu_missing_none():
    result = parser_us_10k.parse_us_10k("We retained all cash for reinvestment.")
    assert result["dpu_usd"] is None


def test_parse_us_10k_occupancy_default_none():
    """美国 10-K 常不披露出租率——默认 None。"""
    result = parser_us_10k.parse_us_10k(
        "Consolidated occupancy across the portfolio was stable."
    )
    assert result["occupancy"] is None
