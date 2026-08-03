"""tools.reits_collector.parser_prospectus 模块（招募说明书可供分配预测解析）的单元测试。

Phase 3「可供分配完成度」：实际年度可供分配 vs 招募说明书预测。
招募说明书「可供分配金额测算结果」章节的「可供分配金额计算表」末尾行
「四、本期/本年可供分配金额」给出两个期间（首年=上市部分年，次年=首个
完整年度）的预测可供分配金额，列序为 [次年, 首年]，单位为万元。

真实段落 fixture（prospectus_180201_predict.txt，180201 招募说明书 1068 页
中的「可供分配金额测算结果」段落）解析出 years == {2022: 62628.76,
2021: 53842.11}；并覆盖标题年份顺序颠倒、无千分位、单年预测容错 None、
找不到段落 ValueError、空文本/None 不崩溃等纯文本变体。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_prospectus

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "prospectus_180201_predict.txt").read_text(
    encoding="utf-8"
)

EMPTY_RESULT = {"years": {}, "unit": "万元"}


def test_parse_prospectus_text_fixture():
    result = parser_prospectus._parse_prospectus_text(FIXTURE_TEXT)

    assert result["unit"] == "万元"
    assert result["years"][2022] == pytest.approx(62628.76)
    assert result["years"][2021] == pytest.approx(53842.11)


def test_parse_prospectus_text_title_year_order_reversed():
    """标题年份顺序颠倒（次年在前）时仍正确提取两期间。"""
    text = FIXTURE_TEXT.replace(
        "2021 年6 月1 日至12 月31 日及2022 年度可供分配金额计算表",
        "2022 年度及2021 年6 月1 日至12 月31 日可供分配金额计算表",
    )
    assert "2022 年度及2021" in text

    result = parser_prospectus._parse_prospectus_text(text)

    assert result["years"][2022] == pytest.approx(62628.76)
    assert result["years"][2021] == pytest.approx(53842.11)


def test_parse_prospectus_text_without_thousands_separator():
    text = FIXTURE_TEXT.replace("62,628.76", "62628.76").replace(
        "53,842.11", "53842.11"
    )
    assert "," not in "62628.76 53842.11"

    result = parser_prospectus._parse_prospectus_text(text)

    assert result["years"][2022] == pytest.approx(62628.76)
    assert result["years"][2021] == pytest.approx(53842.11)


def test_parse_prospectus_text_single_year_prediction():
    """只有单年预测时，缺失期间对应 None。"""
    text = FIXTURE_TEXT.replace("\n53,842.11", "")

    result = parser_prospectus._parse_prospectus_text(text)

    assert result["years"][2022] == pytest.approx(62628.76)
    assert result["years"][2021] is None


def test_parse_prospectus_text_missing_table_raises_value_error():
    with pytest.raises(ValueError):
        parser_prospectus._parse_prospectus_text("没有可供分配金额计算表的文本")


def test_find_predict_section_missing_marker_raises_value_error():
    with pytest.raises(ValueError):
        parser_prospectus._find_predict_section("没有预测段落的正文")


def test_parse_prospectus_text_empty_or_none_no_crash():
    assert parser_prospectus._parse_prospectus_text("") == EMPTY_RESULT
    assert parser_prospectus._parse_prospectus_text(None) == EMPTY_RESULT


def test_parse_prospectus_extracts_from_pdf_text(monkeypatch):
    monkeypatch.setattr(parser_prospectus, "extract_text", lambda path: FIXTURE_TEXT)

    result = parser_prospectus.parse_prospectus("180201 招募说明书.pdf")

    assert result["unit"] == "万元"
    assert result["years"][2022] == pytest.approx(62628.76)
    assert result["years"][2021] == pytest.approx(53842.11)


def test_parse_prospectus_missing_paragraph_raises_value_error(monkeypatch):
    monkeypatch.setattr(
        parser_prospectus, "extract_text", lambda path: "没有预测段落的正文"
    )

    with pytest.raises(ValueError):
        parser_prospectus.parse_prospectus("180201 招募说明书.pdf")
