"""REITs 招募说明书可供分配预测解析（Phase 3 可供分配完成度）。

招募说明书「可供分配金额测算结果」章节的「可供分配金额计算表」
（如「2021 年6 月1 日至12 月31 日及2022 年度可供分配金额计算表」）
末尾行「四、本期/本年可供分配金额」给出两个期间（首年=上市部分年，
次年=首个完整年度）的预测可供分配金额，列序为 [次年, 首年]，单位万元。

extract_text 用 pymupdf 逐页抽取 PDF 全文（与 parser_generic 一致）；
parse_prospectus 定位「可供分配金额测算结果」段落（其后 ~800 字符）后
交给纯函数 _parse_prospectus_text 解析，找不到段落抛 ValueError。
"""

import re
from pathlib import Path

import fitz

TABLE_TITLE_RE = re.compile(r"[^\n]*可供分配金额计算表")
NEXT_YEAR_RE = re.compile(r"(\d{4})\s*年度")
YEAR_RE = re.compile(r"\d{4}")
DISTRIBUTABLE_LABEL_RE = re.compile(r"四、\s*本期/本年可供分配金额")
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
TABLE_BOUNDARY_RE = re.compile(
    r"年度\s*预测\s*合并|合并(?:利润表|资产负债表|现金流量表|权益变动表|净资产变动表)"
)
NOTE_MARKERS = ("注：", "注:", "备注")

MARKER = "可供分配金额测算结果"
UNIT = "万元"
SECTION_LIMIT = 800


def extract_text(pdf_path: str) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def _find_predict_section(text: str, limit: int = SECTION_LIMIT) -> str:
    """返回「可供分配金额测算结果」标记后的段落窗口；找不到抛 ValueError。"""
    idx = text.find(MARKER)
    if idx == -1:
        raise ValueError("未找到「可供分配金额测算结果」段落")
    return text[idx : idx + limit]


def _extract_years(header: str, text: str):
    """从表头标题提取两个期间年份 (次年, 首年)。

    次年 = 紧跟「年度」的完整年份（如「及2022 年度」）；首年 = 表头中
    小于次年的年份（如「2021 年6 月1 日至12 月31 日」）；表头只有省略
    年份写法时推断 次年-1，并核对表内年份出现后采用。
    """
    next_match = NEXT_YEAR_RE.search(header)
    if next_match is None:
        raise ValueError("表头未包含「{YYYY} 年度」")
    next_year = int(next_match.group(1))

    first_candidates = [
        int(year) for year in YEAR_RE.findall(header) if int(year) < next_year
    ]
    if first_candidates:
        first_year = max(first_candidates)
    else:
        inferred = next_year - 1
        first_year = inferred if str(inferred) in text else None
    return next_year, first_year


def _distributable_numbers(text: str, label_index: int):
    """取「四、本期/本年可供分配金额」行及其后数值，遇到下一张表/注记截止。"""
    numbers = []
    lines = text[label_index:].splitlines()
    for i, line in enumerate(lines):
        if i > 0 and (
            TABLE_BOUNDARY_RE.search(line) or line.strip().startswith(NOTE_MARKERS)
        ):
            break
        numbers.extend(float(n.replace(",", "")) for n in NUMBER_RE.findall(line))
    return numbers


def _parse_prospectus_text(text: str) -> dict:
    """解析「可供分配金额计算表」末尾行，返回 {years, unit}。

    空文本/None 返回空结构 {"years": {}, "unit": "万元"}；找不到计算表标题
    或「四、本期/本年可供分配金额」行时抛 ValueError。列序 [次年, 首年]。
    """
    if not text:
        return {"years": {}, "unit": UNIT}

    title_match = TABLE_TITLE_RE.search(text)
    if title_match is None:
        raise ValueError("未找到「可供分配金额计算表」标题")
    header = text[title_match.start() : title_match.end()]
    next_year, first_year = _extract_years(header, text)

    label_match = DISTRIBUTABLE_LABEL_RE.search(text, title_match.end())
    if label_match is None:
        raise ValueError("未找到「四、本期/本年可供分配金额」行")
    numbers = _distributable_numbers(text, label_match.start())
    if not numbers:
        raise ValueError("「四、本期/本年可供分配金额」行未找到预测数值")

    years = {next_year: numbers[0]}
    if first_year is not None:
        years[first_year] = numbers[1] if len(numbers) > 1 else None
    return {"years": years, "unit": UNIT}


def parse_prospectus(pdf_path: str) -> dict:
    """解析招募说明书 PDF 的「可供分配金额测算结果」段落，返回同上结构。"""
    return _parse_prospectus_text(_find_predict_section(extract_text(pdf_path)))
