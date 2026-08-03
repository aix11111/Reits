"""tools.reits_collector.parser_annual 模块（年报可供分配完成度解析）的单元测试。

监管要求 REITs 年报披露「实际可供分配金额与招募说明书测算的差异」：
真实年报段落 fixture（annual_180201_2022_completion.txt，180201 2022 年报
「3.3.3 本期可供分配金额与招募说明书中刊载的可供分配金额测算报告的差异
情况说明」段落）解析出 year=2022 / predicted_wan=62628.76 /
actual_wan=47691.19 / completion_pct=76.15。

覆盖：fixture 真实段落直测、无千分位、完成率措辞变体（「完成预测的」）、
找不到段落/年份/完成率抛 ValueError、空文本/None 不崩溃、
parse_annual_completion 经 _find_completion_section 定位段落的端到端路径。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_annual

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "annual_180201_2022_completion.txt").read_text(
    encoding="utf-8"
)

EXPECTED = {
    "year": 2022,
    "predicted_wan": 62628.76,
    "actual_wan": 47691.19,
    "completion_pct": 76.15,
}

EMPTY_RESULT = {}


def test_parse_completion_text_fixture():
    result = parser_annual._parse_completion_text(FIXTURE_TEXT)

    assert result["year"] == EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(EXPECTED["completion_pct"])


def test_parse_completion_text_without_thousands_separator():
    text = FIXTURE_TEXT.replace("626,287,596.94", "626287596.94").replace(
        "476,911,864.89", "476911864.89"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(62628.76)
    assert result["actual_wan"] == pytest.approx(47691.19)


def test_parse_completion_text_short_wording():
    """兼容「完成预测的」措辞（中间无「招募说明书」）。"""
    text = FIXTURE_TEXT.replace("完成招募说明书预测的76.15%", "完成预测的76.15%")

    result = parser_annual._parse_completion_text(text)

    assert result["completion_pct"] == pytest.approx(76.15)


def test_parse_completion_text_missing_marker_raises_value_error():
    with pytest.raises(ValueError):
        parser_annual._parse_completion_text("没有刊载的可供分配金额测算报告的文本")


def test_parse_completion_text_missing_year_raises_value_error():
    text = FIXTURE_TEXT.replace("预测本基金2022 年度", "预测本基金20XX 年度")
    assert "预测本基金2022 年度" not in text

    with pytest.raises(ValueError):
        parser_annual._parse_completion_text(text)


def test_parse_completion_text_missing_completion_pct_raises_value_error():
    text = FIXTURE_TEXT.replace("完成招募说明书预测的76.15%。", "完成招募说明书预测的。")

    with pytest.raises(ValueError):
        parser_annual._parse_completion_text(text)


def test_parse_completion_text_empty_or_none_no_crash():
    assert parser_annual._parse_completion_text("") == EMPTY_RESULT
    assert parser_annual._parse_completion_text(None) == EMPTY_RESULT


def test_find_completion_section_missing_marker_raises_value_error():
    with pytest.raises(ValueError):
        parser_annual._find_completion_section("没有预测段落的正文")


def test_parse_annual_completion_extracts_from_pdf_text(monkeypatch):
    monkeypatch.setattr(
        parser_annual, "extract_text", lambda path: FIXTURE_TEXT
    )

    result = parser_annual.parse_annual_completion("180201 2022 年报.pdf")

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(62628.76)
    assert result["actual_wan"] == pytest.approx(47691.19)
    assert result["completion_pct"] == pytest.approx(76.15)


def test_parse_annual_completion_missing_paragraph_raises_value_error(monkeypatch):
    monkeypatch.setattr(
        parser_annual, "extract_text", lambda path: "没有预测段落的正文"
    )

    with pytest.raises(ValueError):
        parser_annual.parse_annual_completion("180201 2022 年报.pdf")
