"""通用 REITs 月度运营公告 PDF 解析。

extract_text 用 pymupdf 逐页抽取 PDF 全文（与 parser.py 一致）；
parse_generic_monthly 面向不同基金管理人的月度运营公告，其数据表格结构
统一：「日均收费车流量（辆次）」与「路费收入（人民币，万元，含增值税）」
两个表头各带 5 个数值（当月 / 当月环比 / 当月同比 / 累计 / 累计同比）。

与广河专用 parser 不同，本解析器不依赖固定项目名，而是锚定「主要运营数据」
附近的报告期（兼容阿拉伯数字与中文数字年份写法），并在两个表头之后的
区域内跳过表头标签、识别项目名、收集 10 个数值；备注区域被截断，避免
其中出现的车流量等数字混入表格数值。任何缺失或无法识别时抛出 ValueError
并说明原因。
"""

import re
from pathlib import Path

import fitz

TRAFFIC_HEADER = "日均收费车流量（辆次）"
REVENUE_HEADER = "路费收入（人民币，万元，含增值税）"
NOTE_MARKERS = ("备注", "注：")
PERIOD_ANCHOR = "主要运营数据"
ARABIC_PERIOD_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
CN_DIGITS = "〇零一二三四五六七八九十"
CN_PERIOD_RE = re.compile(rf"([{CN_DIGITS}]{{4}})年([{CN_DIGITS}]+)月")
LABEL_CHARS = set("当月环比同比变动累计年")
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


CN_DIGIT_VALUE = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _cn_digits_to_int(s: str) -> int:
    """按每位一数字的中文数字串（如“二〇二六”）转整数。"""
    value = 0
    for ch in s:
        if ch not in CN_DIGIT_VALUE:
            raise ValueError(f"无法识别中文数字：{s}")
        value = value * 10 + CN_DIGIT_VALUE[ch]
    return value


def _cn_num_to_int(s: str) -> int:
    """中文数字（含“十”，如六月/十月/十一）转整数。"""
    if "十" in s:
        tens, _, units = s.partition("十")
        tens_value = _cn_digits_to_int(tens) if tens else 1
        units_value = _cn_digits_to_int(units) if units else 0
        return tens_value * 10 + units_value
    return _cn_digits_to_int(s)


def _parse_period(text: str) -> str:
    """锚定「主要运营数据」附近提取报告期，如 2026-06。

    正文/标题中的「2026 年6 月」「二〇二六年六月」「二零二六年六月」均可识别；
    取最靠近锚点的匹配，避免误取「公告送出日期」等无关日期。
    """
    for match in re.finditer(PERIOD_ANCHOR, text):
        window = text[max(0, match.start() - 80):match.start()]
        candidates = []
        for m in ARABIC_PERIOD_RE.finditer(window):
            candidates.append((m.start(), int(m.group(1)), int(m.group(2))))
        for m in CN_PERIOD_RE.finditer(window):
            candidates.append(
                (m.start(), _cn_digits_to_int(m.group(1)), _cn_num_to_int(m.group(2)))
            )
        if candidates:
            _, year, month = max(candidates, key=lambda item: item[0])
            if 1 <= month <= 12:
                return f"{year}-{month:02d}"
    raise ValueError("未找到报告期（如 2026 年6 月 或 二〇二六年六月）")


def _is_label_line(line: str) -> bool:
    """判断一行是否为表头标签（当月/环比/同比/累计/变动/2026年 等碎片）。"""
    s = "".join(line.split())
    if not s:
        return True
    if s == "项目":
        return True
    if s.isdigit():
        return True
    rest = re.sub(r"^\d+", "", s)
    if not rest:
        return True
    return all(ch in LABEL_CHARS for ch in rest)


def _has_number(line: str) -> bool:
    """判断一行中是否含数值 token。"""
    return bool(NUMBER_RE.search(line))


def _to_number(raw: str):
    """将抽取出的原始数值字符串转为数值，去除千分位逗号与百分号。"""
    normalized = raw.replace(",", "").rstrip("%")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _find_note_start(text: str, start: int) -> int:
    """在 start 之后找备注/注起始位置；找不到则返回全文末尾。"""
    candidates = [text.find(marker, start) for marker in NOTE_MARKERS]
    found = [idx for idx in candidates if idx != -1]
    return min(found) if found else len(text)


def parse_generic_monthly(text: str) -> dict:
    """解析通用格式月度运营公告，返回含 11 个键的字典。"""
    if TRAFFIC_HEADER not in text:
        raise ValueError("公告缺少“日均收费车流量（辆次）”表头")
    if REVENUE_HEADER not in text:
        raise ValueError("公告缺少“路费收入（人民币，万元，含增值税）”表头")

    period = _parse_period(text)

    traffic_index = text.find(TRAFFIC_HEADER)
    revenue_index = text.find(REVENUE_HEADER)
    segment_start = max(
        traffic_index + len(TRAFFIC_HEADER), revenue_index + len(REVENUE_HEADER)
    )
    segment_end = _find_note_start(text, segment_start)
    segment = text[segment_start:segment_end]

    lines = segment.splitlines()

    index = 0
    while index < len(lines) and _is_label_line(lines[index]):
        index += 1
    if index >= len(lines):
        raise ValueError("表头之后未找到任何数据行")

    project_parts = []
    while index < len(lines) and not _has_number(lines[index]):
        project_parts.append("".join(lines[index].split()))
        index += 1
    if index < len(lines):
        first = NUMBER_RE.search(lines[index])
        prefix = "".join(lines[index][:first.start()].split())
        if prefix:
            project_parts.append(prefix)
    project_name = "".join(project_parts)
    if not project_name:
        raise ValueError("未找到数据行项目名")

    value_text = "\n".join(lines[index:])
    numbers = NUMBER_RE.findall(value_text)
    if len(numbers) < 10:
        raise ValueError(
            f"运营数据数值不足，期望 10 个，实际 {len(numbers)} 个"
        )

    traffic, revenue = numbers[:5], numbers[5:10]
    return {
        "period": period,
        "project_name": project_name,
        "daily_traffic": _to_number(traffic[0]),
        "traffic_mom": _to_number(traffic[1]),
        "traffic_yoy": _to_number(traffic[2]),
        "traffic_cum": _to_number(traffic[3]),
        "traffic_cum_yoy": _to_number(traffic[4]),
        "toll_revenue_wan": _to_number(revenue[0]),
        "revenue_mom": _to_number(revenue[1]),
        "revenue_yoy": _to_number(revenue[2]),
        "revenue_cum": _to_number(revenue[3]),
        "revenue_cum_yoy": _to_number(revenue[4]),
    }
