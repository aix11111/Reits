"""REITs 年报可供分配完成度解析（Phase 3 可供分配完成度）。

监管要求 REITs 年报披露「实际可供分配金额与招募说明书测算的差异」，
对应年报「3.3.3 本期可供分配金额与招募说明书中刊载的可供分配金额测算
报告的差异情况说明」段落。

深市（180201 2022 年报）：
「预测本基金2022 年度可供分配金额626,287,596.94 元，报告期内本基金实现
可供分配金额476,911,864.89 元，完成招募说明书预测的76.15%。」

沪市（508018 2022 年报）以「偏离度」表述、无年份：
「本报告期内，本基金实现可供分配金额为250,597,919.87 元，相较招募说明书
中披露的可供分配金额同期目标数（……为290,818,170.72 元），偏离度
为-13.83%。」→ completion_pct = round(100 + 偏离度, 2) = 86.17。

另一深市措辞（508008 2022 年报）：「预测的2022 年度可供分配金额为
427,054,548.82 元，本报告期实现可供分配金额为390,321,619.58 元，完成
《招募说明书》预测值的91.40%。」与深市共用宽松正则（年份「预测本基金」/
「预测的」、金额「为」可选、完成率「预测/预测值」及「的」可选）。

深市 180202 2022 年报（格式 D）：「本报告期内，本基金实现可供分配金额为
137,426,821.43 元，相较招募说明书中披露的2022 年可供分配金额（153,838,106.00
元），偏离度为-10.67%。」走沪市「偏离度」分支（括号内无「为」的预测金额），
年份从「披露的{YYYY} 年」提取，completion_pct = round(100 + (-10.67), 2) = 89.33。

深市 180203 2024 年报（格式 E）：「本报告期，本基金实现可供分配金额为
235,347,428.99 元，相较招募说明书中披露的可供分配同期目标数235,299,621.65 元，
完成招募说明书预测的100.02%。」预测金额取「同期目标数{X} 元」备选，段落无
年份 → year=None（调用方/页眉标题兜底）。

508066 2023 年报（格式 F）：混合单位——预测「22,512.32 万元」、实际
「227,778,602.49 元」；508009 2023 偏离度双万元（预测「同期目标数88,871.81 万元」
无括号）；508007 2023（格式 G）：「实际可供分配金额{X} 元，与招募说明书中刊载的
{YYYY} 年度可供分配预测金额{Y} 元相比，实际金额约为预测金额的{Z}%」；508086 2025
偏离度但预测「同期目标数600,017,286.71 元」无括号。所有金额正则统一捕获单位
（元|万元），经 _to_wan 换算为万元。

extract_text 用 pymupdf 逐页抽取 PDF 全文（与 parser_generic 一致）；
parse_annual_completion 定位「刊载的可供分配金额测算报告」段落（其后
窗口）后交给纯函数 _parse_completion_text 解析，找不到段落抛 ValueError。
年份：深市从段落「预测本基金{YYYY} 年度」/「预测的{YYYY} 年度」提取；沪市
「偏离度」段落从「披露的{YYYY} 年」提取（180202 格式），180203 格式段落无
年份可由调用方经 year 参数传入，未传时从全文「{YYYY} 年年度报告」/「{YYYY}
年度报告」标题兜底，仍找不到 → year=None。
金额统一 元→万元 除以 10000。
"""

import re
from pathlib import Path

import fitz

SECTION_MARKER = "刊载的可供分配金额测算报告"
SECTION_LIMIT = 800

YEAR_RE = re.compile(r"(?:预测本基金|预测的?)\s*(\d{4})\s*年度")
PREDICTED_RE = re.compile(
    r"(?:"
    r"(?<!实现)可供\s*分\s*配\s*金\s*额\s*为?\s*(?P<predicted>\d[\d,]*(?:\.\d+)?)\s*(?P<predicted_unit>万元|元)"
    r"|同期目标数\s*(?P<target>\d[\d,]*(?:\.\d+)?)\s*(?P<target_unit>万元|元)"
    r")"
)
ACTUAL_RE = re.compile(r"实现\s*可\s*供\s*分\s*配\s*金\s*额\s*为?\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)")
COMPLETION_RE = re.compile(r"完成[^%\d]{0,14}预测值?\s*的?\s*(\d+(?:\.\d+)?)\s*%")

SH_ACTUAL_RE = re.compile(r"实现\s*可\s*供\s*分\s*配\s*金\s*额\s*为?\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)")
SH_PREDICTED_RE = re.compile(
    r"(?:"
    r"[（(][^（）()]{0,100}?(\d[\d,]*(?:\.\d+)?)\s*(万元|元)\s*[）)]"
    r"|同期目标数\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
    r")"
)
SH_YEAR_RE = re.compile(r"披露的\s*(\d{4})\s*年")
DEVIATION_RE = re.compile(r"偏离度为\s*(-?\d+(?:\.\d+)?)\s*%")

G_ACTUAL_RE = re.compile(
    r"实际\s*可供\s*分配\s*金额\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
G_PREDICTED_RE = re.compile(
    r"(\d{4})\s*年度\s*可供\s*分配\s*预\s*测\s*金额\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
G_COMPLETION_RE = re.compile(r"约为预测金额的\s*(\d+(?:\.\d+)?)\s*%")

REPORT_YEAR_RE = re.compile(r"(\d{4})\s*年\s*年度报告")
REPORT_YEAR_SHORT_RE = re.compile(r"(\d{4})\s*年度报告")


def extract_text(pdf_path: str) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def _to_number(raw: str):
    """将抽取出的原始数值字符串转为数值，去除千分位逗号。"""
    normalized = raw.replace(",", "")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _to_wan(raw: str, unit: str) -> float:
    """按捕获单位将数值换算为万元：万元原值、元除以 10000。"""
    value = _to_number(raw)
    if unit == "元":
        return value / 10000.0
    return float(value)


def _find_completion_section(text: str, limit: int = SECTION_LIMIT) -> str:
    """返回「刊载的可供分配金额测算报告」标记后的段落窗口；找不到抛 ValueError。"""
    idx = text.find(SECTION_MARKER)
    if idx == -1:
        raise ValueError("未找到「刊载的可供分配金额测算报告」段落")
    return text[idx : idx + limit]


def _parse_shanghai_completion(text: str, year) -> dict:
    """解析沪市「偏离度」格式段落，返回 {year, predicted_wan, actual_wan, completion_pct}。

    实际金额取「实现可供分配金额为{X} 元」，预测金额取括号内「{X} 元)」
    （「为」可省略，如「（153,838,106.00 元）」或「（…为290,818,170.72 元）」），
    completion_pct = round(100 + 偏离度, 2)；year 由调用方传入，为 None 时从
    「披露的{YYYY} 年」（180202 格式）提取，找不到保持 None。
    """
    actual_match = SH_ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实现可供分配金额")

    predicted_match = SH_PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")

    deviation_match = DEVIATION_RE.search(text)
    if deviation_match is None:
        raise ValueError("未找到偏离度")

    if predicted_match.group(1) is not None:
        predicted_raw = predicted_match.group(1)
        predicted_unit = predicted_match.group(2)
    else:
        predicted_raw = predicted_match.group(3)
        predicted_unit = predicted_match.group(4)

    if year is None:
        year_match = SH_YEAR_RE.search(text)
        if year_match is not None:
            year = int(year_match.group(1))

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_raw, predicted_unit),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": round(100 + _to_number(deviation_match.group(1)), 2),
    }


def _parse_g_completion(text: str, year) -> dict:
    """解析「约为预测金额的」格式段落（508007），返回同构字典。

    实际金额取「实际可供分配金额{X} 元」，预测金额取「{YYYY} 年度可供分配
    预测金额{Y} 元」，完成率取「约为预测金额的{Z}%」，年份从预测正则提取。
    """
    actual_match = G_ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实际可供分配金额")

    predicted_match = G_PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")

    completion_match = G_COMPLETION_RE.search(text)
    if completion_match is None:
        raise ValueError("未找到完成率")

    if year is None:
        year = int(predicted_match.group(1))

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_match.group(2), predicted_match.group(3)),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": _to_number(completion_match.group(1)),
    }


def _parse_completion_text(text: str, year=None) -> dict:
    """解析年报可供分配完成度段落，返回 {year, predicted_wan, actual_wan, completion_pct}。

    空文本/None 返回空结构 {}；找不到段落/年份/金额/完成率时抛 ValueError。
    深市格式（含「预测本基金{YYYY} 年度」）：完成率为百分比原值（如 76.15）。
    沪市格式（含「偏离度」，无年份）：completion_pct = round(100 + 偏离度, 2)，
    year 取传入参数（可为 None）。
    预测金额 元→万元，实际金额 元→万元。
    """
    if not text:
        return {}

    if SECTION_MARKER not in text:
        raise ValueError("未找到「刊载的可供分配金额测算报告」段落")

    if "偏离度" in text:
        return _parse_shanghai_completion(text, year)

    if "约为预测金额的" in text:
        return _parse_g_completion(text, year)

    if year is None:
        year_match = YEAR_RE.search(text)
        if year_match is not None:
            year = int(year_match.group(1))
        elif "年度" in text:
            raise ValueError("未找到预测年份")

    predicted_match = PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")
    predicted_raw = predicted_match.group("predicted") or predicted_match.group("target")
    predicted_unit = predicted_match.group("predicted_unit") or predicted_match.group(
        "target_unit"
    )

    actual_match = ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实现可供分配金额")

    completion_match = COMPLETION_RE.search(text)
    if completion_match is None:
        raise ValueError("未找到完成率")

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_raw, predicted_unit),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": _to_number(completion_match.group(1)),
    }


def _find_report_year(text: str):
    """从全文「{YYYY} 年年度报告」或「{YYYY} 年度报告」标题提取年份；找不到返回 None。"""
    match = REPORT_YEAR_RE.search(text)
    if match is not None:
        return int(match.group(1))
    match = REPORT_YEAR_SHORT_RE.search(text)
    if match is not None:
        return int(match.group(1))
    return None


def parse_annual_completion(pdf_path: str, year=None) -> dict:
    """解析年报 PDF 的「可供分配完成度」段落，返回 _parse_completion_text 同构字典。

    year 可选：沪市段落无年份时传入；为 None 时从全文页眉标题
    「{YYYY} 年年度报告」/「{YYYY} 年度报告」兜底，找不到 → year=None。
    """
    text = extract_text(pdf_path)
    if year is None:
        year = _find_report_year(text)
    return _parse_completion_text(_find_completion_section(text), year)
