"""tools.reits_collector.parser_annual 模块（年报可供分配完成度解析）的单元测试。

监管要求 REITs 年报披露「实际可供分配金额与招募说明书测算的差异」：
真实年报段落 fixture（annual_180201_2022_completion.txt，180201 2022 年报
「3.3.3 本期可供分配金额与招募说明书中刊载的可供分配金额测算报告的差异
情况说明」段落）解析出 year=2022 / predicted_wan=62628.76 /
actual_wan=47691.19 / completion_pct=76.15。

沪市差异格式（annual_508018_2022_completion.txt，508018 2022 年报同一段落）
以「偏离度」表述，无「预测本基金{YYYY} 年度」年份，解析出 year=None /
predicted_wan=29081.817072 / actual_wan=25059.791987 / completion_pct=86.17
（= round(100 + 偏离度, 2)）。

覆盖：两类 fixture 真实段落直测、沪市负偏离度/保留两位、年份参数传入、
全文页眉标题「{YYYY} 年年度报告」/「{YYYY} 年度报告」兜底年份、无千分位、
完成率措辞变体（「完成预测的」）、找不到段落/年份/完成率抛 ValueError、
空文本/None 不崩溃、parse_annual_completion 经 _find_completion_section
定位段落的端到端路径。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_annual

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE_TEXT = (FIXTURES_DIR / "annual_180201_2022_completion.txt").read_text(
    encoding="utf-8"
)

SH_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508018_2022_completion.txt"
).read_text(encoding="utf-8")

EXPECTED = {
    "year": 2022,
    "predicted_wan": 62628.76,
    "actual_wan": 47691.19,
    "completion_pct": 76.15,
}

SH_EXPECTED = {
    "year": None,
    "predicted_wan": 29081.817072,
    "actual_wan": 25059.791987,
    "completion_pct": 86.17,
}

C_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508008_2022_completion.txt"
).read_text(encoding="utf-8")

C_EXPECTED = {
    "year": 2022,
    "predicted_wan": 42705.454882,
    "actual_wan": 39032.161958,
    "completion_pct": 91.40,
}

D_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180202_2022_completion.txt"
).read_text(encoding="utf-8")

D_EXPECTED = {
    "year": 2022,
    "predicted_wan": 15383.8106,
    "actual_wan": 13742.682143,
    "completion_pct": 89.33,
}

E_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180203_2024_completion.txt"
).read_text(encoding="utf-8")

E_EXPECTED = {
    "year": None,
    "predicted_wan": 23529.962165,
    "actual_wan": 23534.742899,
    "completion_pct": 100.02,
}

MIXED_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508066_2023_completion.txt"
).read_text(encoding="utf-8")

MIXED_EXPECTED = {
    "year": 2023,
    "predicted_wan": 22512.32,
    "actual_wan": 22777.860249,
    "completion_pct": 101.18,
}

DEVIATION_WAN_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508009_2023_completion.txt"
).read_text(encoding="utf-8")

DEVIATION_WAN_EXPECTED = {
    "year": 2023,
    "predicted_wan": 88871.81,
    "actual_wan": 78044.60,
    "completion_pct": 87.82,
}

G_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508007_2023_completion.txt"
).read_text(encoding="utf-8")

G_EXPECTED = {
    "year": 2023,
    "predicted_wan": 32187.389444,
    "actual_wan": 35617.733507,
    "completion_pct": 110.66,
}

NOBRACKET_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508086_2025_completion.txt"
).read_text(encoding="utf-8")

NOBRACKET_EXPECTED = {
    "year": 2025,
    "predicted_wan": 60001.728671,
    "actual_wan": 58976.982308,
    "completion_pct": 98.29,
}

LINEBREAK_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508001_2022_completion.txt"
).read_text(encoding="utf-8")

LINEBREAK_EXPECTED = {
    "year": 2022,
    "predicted_wan": 43219.12,
    "actual_wan": 31508.74,
    "completion_pct": 72.90,
}

NAV_FIXTURE_TEXT = (FIXTURES_DIR / "annual_180201_2022_nav.txt").read_text(
    encoding="utf-8"
)

NAV_2023_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180201_2023_nav.txt"
).read_text(encoding="utf-8")

NAV_2024_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180201_2024_nav.txt"
).read_text(encoding="utf-8")

NAV_2025_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180201_2025_nav.txt"
).read_text(encoding="utf-8")

EMPTY_RESULT = {}

ANNUAL_DIR = Path(__file__).resolve().parents[1] / "data" / "_cache" / "annual"

SHARES_180201_2022_PDF = ANNUAL_DIR / "180201_annual_2022.pdf"


def test_parse_completion_text_fixture():
    result = parser_annual._parse_completion_text(FIXTURE_TEXT)

    assert result["year"] == EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(EXPECTED["completion_pct"])


def test_parse_completion_text_shanghai_fixture():
    result = parser_annual._parse_completion_text(SH_FIXTURE_TEXT)

    assert result["year"] is None
    assert result["predicted_wan"] == pytest.approx(SH_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(SH_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(SH_EXPECTED["completion_pct"])


def test_parse_completion_text_shanghai_negative_deviation():
    """沪市负偏离度：completion_pct = round(100 + 偏离度, 2)。"""
    text = SH_FIXTURE_TEXT.replace("-13.83%", "-5.25%")

    result = parser_annual._parse_completion_text(text)

    assert result["completion_pct"] == pytest.approx(94.75)


def test_parse_completion_text_shanghai_deviation_rounding():
    """偏离度换算后需保留两位：-13.834% → 86.166 → 86.17。"""
    text = SH_FIXTURE_TEXT.replace("-13.83%", "-13.834%")

    result = parser_annual._parse_completion_text(text)

    assert result["completion_pct"] == pytest.approx(86.17)


def test_parse_completion_text_shanghai_with_year_param():
    """沪市段落无年份，year 参数由调用方传入后直接返回。"""
    result = parser_annual._parse_completion_text(SH_FIXTURE_TEXT, year=2022)

    assert result["year"] == 2022
    assert result["completion_pct"] == pytest.approx(86.17)


def test_parse_annual_completion_shanghai_with_year_param(monkeypatch):
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: SH_FIXTURE_TEXT)

    result = parser_annual.parse_annual_completion("508018 2022 年报.pdf", year=2022)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(SH_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(SH_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(SH_EXPECTED["completion_pct"])


def test_parse_annual_completion_shanghai_year_from_full_text(monkeypatch):
    """未传 year 时从全文页眉标题「{YYYY} 年年度报告」兜底提取。"""
    full_text = "508018 2022 年年度报告\n\n" + SH_FIXTURE_TEXT
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: full_text)

    result = parser_annual.parse_annual_completion("508018 2022 年报.pdf")

    assert result["year"] == 2022
    assert result["completion_pct"] == pytest.approx(86.17)


def test_parse_annual_completion_shanghai_year_from_full_text_variant(monkeypatch):
    """未传 year 时从全文「{YYYY} 年度报告」标题兜底提取。"""
    full_text = "华夏中国交建高速公路封闭式基础设施证券投资基金2022 年度报告\n\n" + SH_FIXTURE_TEXT
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: full_text)

    result = parser_annual.parse_annual_completion("508018 2022 年报.pdf")

    assert result["year"] == 2022
    assert result["completion_pct"] == pytest.approx(86.17)


def test_parse_annual_completion_shanghai_no_year_found_is_none(monkeypatch):
    """全文无年份标题且未传 year → year=None，不抛错。"""
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: SH_FIXTURE_TEXT)

    result = parser_annual.parse_annual_completion("508018 2022 年报.pdf")

    assert result["year"] is None
    assert result["completion_pct"] == pytest.approx(86.17)


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


def test_parse_completion_text_format_c_fixture():
    """格式 C（508008 2022 年报）：「预测的{YYYY} 年度…可供分配金额为…元，
    本报告期实现可供分配金额为…元，完成《招募说明书》预测值的91.40%。」"""
    result = parser_annual._parse_completion_text(C_FIXTURE_TEXT)

    assert result["year"] == C_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(C_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(C_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(C_EXPECTED["completion_pct"])


def test_parse_completion_text_format_c_without_thousands_separator():
    text = C_FIXTURE_TEXT.replace("427,054,548.82", "427054548.82").replace(
        "390,321,619.58", "390321619.58"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(42705.454882)
    assert result["actual_wan"] == pytest.approx(39032.161958)
    assert result["completion_pct"] == pytest.approx(91.40)


def test_parse_completion_text_format_d_fixture():
    """格式 D（180202 2022 年报）：偏离度括号内无「为」——「披露的2022 年
    可供分配金额（153,838,106.00 元）」，年份从「披露的{YYYY} 年」提取，
    completion_pct = round(100 + 偏离度, 2) = 89.33。"""
    result = parser_annual._parse_completion_text(D_FIXTURE_TEXT)

    assert result["year"] == D_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(D_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(D_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(D_EXPECTED["completion_pct"])


def test_parse_completion_text_format_d_without_thousands_separator():
    text = D_FIXTURE_TEXT.replace("137,426,821.43", "137426821.43").replace(
        "153,838,106.00", "153838106.00"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(15383.8106)
    assert result["actual_wan"] == pytest.approx(13742.682143)
    assert result["completion_pct"] == pytest.approx(89.33)


def test_parse_completion_text_format_e_fixture():
    """格式 E（180203 2024 年报）：预测为「可供分配同期目标数{数字} 元」、
    完成率「完成招募说明书预测的100.02%」；段落无年份 → year=None。"""
    result = parser_annual._parse_completion_text(E_FIXTURE_TEXT)

    assert result["year"] is None
    assert result["predicted_wan"] == pytest.approx(E_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(E_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(E_EXPECTED["completion_pct"])


def test_parse_completion_text_format_e_without_thousands_separator():
    text = E_FIXTURE_TEXT.replace("235,347,428.99", "235347428.99").replace(
        "235,299,621.65", "235299621.65"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] is None
    assert result["predicted_wan"] == pytest.approx(23529.962165)
    assert result["actual_wan"] == pytest.approx(23534.742899)
    assert result["completion_pct"] == pytest.approx(100.02)


def test_parse_completion_text_mixed_unit_fixture():
    """508066 2023：预测「22,512.32 万元」、实际「227,778,602.49 元」——混合单位。"""
    result = parser_annual._parse_completion_text(MIXED_FIXTURE_TEXT)

    assert result["year"] == MIXED_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(MIXED_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(MIXED_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(MIXED_EXPECTED["completion_pct"])


def test_parse_completion_text_mixed_unit_without_thousands_separator():
    text = MIXED_FIXTURE_TEXT.replace("22,512.32", "22512.32").replace(
        "227,778,602.49", "227778602.49"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2023
    assert result["predicted_wan"] == pytest.approx(22512.32)
    assert result["actual_wan"] == pytest.approx(22777.860249)
    assert result["completion_pct"] == pytest.approx(101.18)


def test_parse_completion_text_deviation_wan_fixture():
    """508009 2023：偏离度双万元——预测「同期目标数88,871.81 万元」、实际
    「78,044.60 万元」，completion_pct = round(100 - 12.18, 2) = 87.82。"""
    result = parser_annual._parse_completion_text(
        DEVIATION_WAN_FIXTURE_TEXT, year=2023
    )

    assert result["year"] == DEVIATION_WAN_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(
        DEVIATION_WAN_EXPECTED["predicted_wan"]
    )
    assert result["actual_wan"] == pytest.approx(DEVIATION_WAN_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(
        DEVIATION_WAN_EXPECTED["completion_pct"]
    )


def test_parse_completion_text_format_g_fixture():
    """格式 G（508007 2023）：无「实现」的实际、无「完成…预测的」完成率——
    「实际可供分配金额356,177,335.07 元，与招募说明书中刊载的2023 年度可供分配
    预测金额321,873,894.44 元相比，实际金额约为预测金额的110.66%」。"""
    result = parser_annual._parse_completion_text(G_FIXTURE_TEXT)

    assert result["year"] == G_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(G_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(G_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(G_EXPECTED["completion_pct"])


def test_parse_completion_text_format_g_without_thousands_separator():
    text = G_FIXTURE_TEXT.replace("356,177,335.07", "356177335.07").replace(
        "321,873,894.44", "321873894.44"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2023
    assert result["predicted_wan"] == pytest.approx(32187.389444)
    assert result["actual_wan"] == pytest.approx(35617.733507)
    assert result["completion_pct"] == pytest.approx(110.66)


def test_parse_completion_text_nobracket_target_fixture():
    """508086 2025：有「偏离度」（走 B 分支）但预测「同期目标数600,017,286.71 元」
    无括号 → SH_PREDICTED_RE 需无括号备选。"""
    result = parser_annual._parse_completion_text(NOBRACKET_FIXTURE_TEXT, year=2025)

    assert result["year"] == NOBRACKET_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(NOBRACKET_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(NOBRACKET_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(NOBRACKET_EXPECTED["completion_pct"])


def test_parse_completion_text_nobracket_target_without_thousands_separator():
    text = NOBRACKET_FIXTURE_TEXT.replace("589,769,823.08", "589769823.08").replace(
        "600,017,286.71", "600017286.71"
    )

    result = parser_annual._parse_completion_text(text, year=2025)

    assert result["year"] == 2025
    assert result["predicted_wan"] == pytest.approx(60001.728671)
    assert result["actual_wan"] == pytest.approx(58976.982308)
    assert result["completion_pct"] == pytest.approx(98.29)


def test_parse_completion_text_linebreak_actual_fixture():
    """508001 2022：断行在「可供分」与「配金额」之间——「分配」两字被换行
    分开，ACTUAL_RE 需字间全容忍；段落无年份标记 → year=2022 由调用方传入。"""
    result = parser_annual._parse_completion_text(LINEBREAK_FIXTURE_TEXT, year=2022)

    assert result["year"] == LINEBREAK_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(LINEBREAK_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(LINEBREAK_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(LINEBREAK_EXPECTED["completion_pct"])


DIFF_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508000_2021_completion.txt"
).read_text(encoding="utf-8")

DIFF_EXPECTED = {
    "year": 2021,
    "predicted_wan": 6974.05089,
    "actual_wan": 4226.249591,
    "completion_pct": 60.60,
}

TABLE_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508000_2025_completion.txt"
).read_text(encoding="utf-8")


def test_parse_completion_text_difference_format_fixture():
    """产业园「差异情况说明」格式（508000 2021 年报）：披露本期实际与
    {YYYY} 年预测可供分配金额，但不直接给出完成率 →
    completion_pct = round(实际/预测 × 100, 2)。"""
    result = parser_annual._parse_completion_text(DIFF_FIXTURE_TEXT)

    assert result["year"] == DIFF_EXPECTED["year"]
    assert result["predicted_wan"] == pytest.approx(DIFF_EXPECTED["predicted_wan"])
    assert result["actual_wan"] == pytest.approx(DIFF_EXPECTED["actual_wan"])
    assert result["completion_pct"] == pytest.approx(DIFF_EXPECTED["completion_pct"])


def test_parse_completion_text_difference_table_no_prediction_fixture():
    """产业园 2025 年报表格格式：预测数为「-」（本期无招募说明书预测数）→
    predicted_wan/completion_pct 为 None；实际金额按表头单位「万元」照实解析。"""
    result = parser_annual._parse_completion_text(TABLE_FIXTURE_TEXT, year=2025)

    assert result["year"] == 2025
    assert result["actual_wan"] == pytest.approx(11268.57)
    assert result["predicted_wan"] is None
    assert result["completion_pct"] is None


def test_parse_annual_completion_difference_format_with_nav(monkeypatch):
    """产业园年报端到端：差异格式完成度 + 3.2 净值字段（nav fixture）。"""
    full_text = DIFF_FIXTURE_TEXT + "\n\n" + NAV_FIXTURE_TEXT
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: full_text)

    result = parser_annual.parse_annual_completion("508000 2021 年报.pdf")

    assert result["year"] == 2021
    assert result["completion_pct"] == pytest.approx(60.60)
    assert result["nav_unit_price"] == 12.2867
    assert result["nav_wan"] == 860066.41


NODATA_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_508001_2023_nodata.txt"
).read_text(encoding="utf-8")

NODISCLOSURE_FIXTURE_TEXT = (
    FIXTURES_DIR / "annual_180201_2023_nodata.txt"
).read_text(encoding="utf-8")


def test_parse_completion_text_no_data_no_difference_fixture():
    """508001 2023：差异情况说明段仅「无」——无完成度数据 → 金额字段为 None。"""
    result = parser_annual._parse_completion_text(NODATA_FIXTURE_TEXT, year=2023)

    assert result["year"] == 2023
    assert result["predicted_wan"] is None
    assert result["actual_wan"] is None
    assert result["completion_pct"] is None


def test_parse_completion_text_no_disclosure_fixture():
    """180201 2023：「招募说明书未披露2023 年可供分配金额」→ 无完成度数据。"""
    result = parser_annual._parse_completion_text(NODISCLOSURE_FIXTURE_TEXT)

    assert result["year"] == 2023
    assert result["predicted_wan"] is None
    assert result["actual_wan"] is None
    assert result["completion_pct"] is None


def test_extract_nav_price_narrative_variant():
    """508000 2023+ 净值叙述格式：「基金份额净值人民币2.9780 元，
    基金份额公允价值参考净值人民币3.0071 元」→ nav_unit_price=2.9780。"""
    text = (
        "期末基金资产净值 100.00 元\n"
        "基金份额净值人民币2.9780 元，基金份额公允价值参考净值人民币3.0071 元，"
        "基金份额总额960,326,121.00 份。"
    )

    result = parser_annual._extract_nav_fields(text)

    assert result["nav_unit_price"] == 2.9780


def test_parse_completion_text_achieved_cumulative_actual():
    """鹏华深圳能源：实际措辞「实现全年累计可供分配金额{X} 万元」。"""
    text = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "根据《鹏华深圳能源清洁能源封闭式基础设施证券投资基金招募说明书》，"
        "预测本基金2022 年度可供分配金额38,154.35 万元，报告期内本基金实现全年累计"
        "可供分配金额45,743.56 万元，完成招募说明书预测的119.89%。"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(38154.35)
    assert result["actual_wan"] == pytest.approx(45743.56)
    assert result["completion_pct"] == pytest.approx(119.89)


def test_parse_completion_text_completion_rate_variants():
    """完成率措辞变体：无「预测」字样（完成率为96% / 目标完成率达111.10%）。"""
    base = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "预计2024 年度全年的可供分配金额146,868,591.73 元。"
        "本报告期实现可供分配金额为141,627,991.95 元，完成率为96%。"
    )
    result = parser_annual._parse_completion_text(base)
    assert result["completion_pct"] == 96

    goal = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "2024 年度，本基金实现可供分配金额77,917.43 万元，较招募说明书披露的同期目标值"
        "70,131.19 万元超额完成7,786.24 万元，目标完成率达111.10%。"
    )
    result = parser_annual._parse_completion_text(goal, year=2024)
    assert result["predicted_wan"] == pytest.approx(70131.19)
    assert result["actual_wan"] == pytest.approx(77917.43)
    assert result["completion_pct"] == pytest.approx(111.10)


def test_parse_completion_text_cashflow_format():
    """博时/招商蛇口现金流格式：「项目可供分配现金流{X} 元，较可供分配金额测算报告
    {Y} 元增加…，完成《招募说明书》预测的{Z}%」。"""
    text = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "2022 年1 月1 日至2022 年12 月31 日，项目可供分配现金流86,947,616.70 元，"
        "较可供分配金额测算报告81,036,624.44 元增加5,910,992.26 元，"
        "完成《招募说明书》预测的107.29%。"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["actual_wan"] == pytest.approx(8694.76167)
    assert result["predicted_wan"] == pytest.approx(8103.662444)
    assert result["completion_pct"] == pytest.approx(107.29)


def test_parse_completion_text_2025_table_with_completion():
    """2025 表格格式带三项：实际（万元）/预测（万元）/完成度（%）。"""
    text = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "项目 本期实现金额（万元） 招募说明书预测数（万元） 完成度（%） 差异原因 "
        "可供分配金额 8,052.61 6,489.62 124.08 基金管理人通过积极督促运营管理机构拓展招商渠道"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["actual_wan"] == pytest.approx(8052.61)
    assert result["predicted_wan"] == pytest.approx(6489.62)
    assert result["completion_pct"] == pytest.approx(124.08)


def test_parse_completion_text_shanghai_deviation_no_wei():
    """沪市偏离度无「为」：『偏离度25.30%』；预测在括号内且无「为」。"""
    text = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "本报告期内，本基金实现可供分配金额为60,761,363.43 元，"
        "相较招募说明书中披露的2023 年可供分配金额（48,491,856.40 元），偏离度25.30%。"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2023
    assert result["actual_wan"] == pytest.approx(6076.136343)
    assert result["predicted_wan"] == pytest.approx(4849.18564)
    assert result["completion_pct"] == pytest.approx(125.30)


def test_parse_completion_text_shanghai_noparen_predicted():
    """沪市无括号预测：「预测的2024 年7-12 月可供分配金额6,014.02 万元，偏离度1.06%」。"""
    text = (
        "本报告期内，本基金实现可供分配金额为6,077.67 万元，"
        "相较招募说明书中刊载的可供分配金额测算报告预测的2024 年7-12 月可供分配金额"
        "6,014.02 万元，偏离度1.06%。"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2024
    assert result["actual_wan"] == pytest.approx(6077.67)
    assert result["predicted_wan"] == pytest.approx(6014.02)
    assert result["completion_pct"] == pytest.approx(101.06)


def test_parse_completion_text_no_data_bu_sheji():
    """无数据措辞变体：「不涉及。」与「未披露本期可供分配金额预测数。」。"""
    result = parser_annual._parse_completion_text(
        "刊载的可供分配金额测算报告的差异情况说明\n不涉及。", year=2024
    )
    assert result["year"] == 2024
    assert result["predicted_wan"] is None
    assert result["actual_wan"] is None
    assert result["completion_pct"] is None

    result = parser_annual._parse_completion_text(
        "刊载的可供分配金额测算报告的差异情况说明\n招募说明书未披露本期可供分配金额预测数。",
        year=2023,
    )
    assert result["year"] == 2023
    assert result["completion_pct"] is None


def test_parse_completion_text_whitespace_collapse_g_format():
    """换行落在任意字符间（「可供分\\n配预测金额」）折叠后 G 格式仍解析。"""
    text = (
        "刊载的可供分配金额测算报告的差异情况说明"
        "本报告期内实际可供分配金额265,836,477.17 元，与招募说明书中刊载的"
        "2022 年度可供分\n配预测金额251,606,801.40 元相比，实际金额约为预测金额的106%。"
    )

    result = parser_annual._parse_completion_text(text)

    assert result["year"] == 2022
    assert result["predicted_wan"] == pytest.approx(25160.68014)
    assert result["actual_wan"] == pytest.approx(26583.647717)
    assert result["completion_pct"] == pytest.approx(106)


def test_parse_completion_text_missing_marker_raises_value_error():
    with pytest.raises(ValueError):
        parser_annual._parse_completion_text("完全没有完成度段落的正文文本")


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


def test_extract_nav_fields_nav_fixture():
    """nav fixture（3.2 节完整片段）→ nav_unit_price=12.2867、
    nav_wan=860066.41（期末基金净资产 8,600,664,096.81 元 ÷10000 保留两位）。"""
    result = parser_annual._extract_nav_fields(NAV_FIXTURE_TEXT)

    assert result["nav_unit_price"] == 12.2867
    assert result["nav_wan"] == 860066.41


def test_extract_nav_fields_missing_returns_none():
    """早期年报无净值披露 → 字段为 None，不抛错。"""
    result = parser_annual._extract_nav_fields("早期年报无净值披露的文本")

    assert result["nav_unit_price"] is None
    assert result["nav_wan"] is None


def test_extract_nav_fields_linebreak_thousands():
    """净资产值跨行 + 千分位 → 拼回完整数值换算万元。"""
    text = NAV_FIXTURE_TEXT.replace("8,600,664,096.81", "8,600,66\n4,096.81")

    result = parser_annual._extract_nav_fields(text)

    assert result["nav_wan"] == 860066.41


def test_extract_nav_fields_2023_split_label_and_three_years():
    """2023 年报 3.1 节：label「期末基金\n净资产」跨行拆分 + 三列值
    （2023/2022/2021）→ 取首个（报告年）→ nav_wan=817472.93。"""
    result = parser_annual._extract_nav_fields(NAV_2023_FIXTURE_TEXT)

    assert result["nav_unit_price"] == 11.6782
    assert result["nav_wan"] == 817472.93


def test_extract_nav_fields_2024_split_label_and_three_years():
    """2024 年报 3.1/3.2 节：label「期末基金净\n资产」「期末基金份额\n净值」
    跨行拆分 + 三列值（2024/2023/2022）→ 取报告年值。"""
    result = parser_annual._extract_nav_fields(NAV_2024_FIXTURE_TEXT)

    assert result["nav_unit_price"] == 10.4979
    assert result["nav_wan"] == 734851.28


def test_extract_nav_fields_2025_immovable_property_label():
    """2025 年报 3.1/3.2 节：label 更名「期末不动产\n基金净资产」「期末不动产基\n
    金份额净值」+ 三列值（2025/2024/2023）→ 取报告年值。"""
    result = parser_annual._extract_nav_fields(NAV_2025_FIXTURE_TEXT)

    assert result["nav_unit_price"] == 10.0063
    assert result["nav_wan"] == 700438.43


def test_parse_annual_completion_nav_fixture(monkeypatch):
    """parse_annual_completion 端到端：nav fixture + completion 段落 → 全部字段。"""
    full_text = FIXTURE_TEXT + "\n\n" + NAV_FIXTURE_TEXT
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: full_text)

    result = parser_annual.parse_annual_completion("180201 2022 年报.pdf")

    assert result["year"] == 2022
    assert result["completion_pct"] == pytest.approx(76.15)
    assert result["nav_unit_price"] == 12.2867
    assert result["nav_wan"] == 860066.41


def test_parse_annual_completion_no_nav_is_none(monkeypatch):
    """全文无净值披露 → nav 字段为 None，不抛错。"""
    monkeypatch.setattr(parser_annual, "extract_text", lambda path: SH_FIXTURE_TEXT)

    result = parser_annual.parse_annual_completion("508018 2022 年报.pdf")

    assert result["nav_unit_price"] is None
    assert result["nav_wan"] is None


def test_parse_fund_shares_180201_2022_real_pdf():
    """真实 180201 2022 年报 PDF → 报告期末基金份额总额 700,000,000.00 份 = 700000000.0。"""
    if not SHARES_180201_2022_PDF.exists():
        pytest.skip("年报 PDF 缓存缺失（data/_cache 不入库），跳过真实文件断言")
    shares = parser_annual.parse_fund_shares(str(SHARES_180201_2022_PDF))

    assert shares == 700000000.0


def test_extract_fund_shares_linebreak_variant():
    """断行变体：数字中间插 \n → 仍解析正确（700,000,00\\n0.00）。"""
    text = "报告期末基金份额总额\n700,000,00\n0.00 份"

    assert parser_annual._extract_fund_shares(text) == 700000000.0


def test_extract_fund_shares_thousands_no_space():
    """无空格变体：「500,000,000.00份」（508001 沪市格式）。"""
    text = "报告期末基金份额总额\n500,000,000.00份\n基金合同存续期"

    assert parser_annual._extract_fund_shares(text) == 500000000.0


def test_extract_fund_shares_split_label():
    """label 自身跨行（180202 2025 年报「报告期末基金份额\\n总额」）→ 仍解析。"""
    text = "报告期末基金份额\n总额\n300,000,000.00 份\n基金合同存续期"

    assert parser_annual._extract_fund_shares(text) == 300000000.0


def test_extract_fund_shares_missing_label_returns_none():
    assert parser_annual._extract_fund_shares("无份额总额披露的文本") is None


def test_extract_fund_shares_unit_in_label():
    """季度报告变体：label 后跟「（单位：份）」，数值不带「份」后缀
    （508006 季报格式「报告期末基金份额总额（单位：份）500,000,000.00」）。"""
    text = "报告期末基金份额总额（单位：份）\n500,000,000.00\n基金合同存续期"

    assert parser_annual._extract_fund_shares(text) == 500000000.0


def test_build_fund_shares_snapshot_picks_latest_report_year(monkeypatch, tmp_path):
    """批量：每基金取报告年最新文件；报告年从标题解析而非文件名。

    180201_annual_2026.pdf（标题 2025 年度报告）覆盖 180201_annual_2022.pdf
    （标题 2022 年度报告）→ 取 2025 报告年的份额值；508020 无年报 → missing。"""
    texts = {
        "180201_annual_2022.pdf": "180201 2022 年年度报告\n报告期末基金份额总额\n600,000,000.00 份",
        "180201_annual_2026.pdf": "180201 2025 年年度报告\n报告期末基金份额总额\n700,000,000.00 份",
    }

    for name in texts:
        (tmp_path / name).touch()

    def fake_extract(path):
        return texts[Path(path).name]

    monkeypatch.setattr(parser_annual, "extract_text", fake_extract)

    shares, missing = parser_annual.build_fund_shares_snapshot(
        str(tmp_path), ["180201", "508020"]
    )

    assert shares == {"180201": 700000000.0}
    assert missing == ["508020"]
