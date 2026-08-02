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
TRAFFIC_HEADER_RE = re.compile(r"日均(?:收费|自然)车流量（辆次）")
REVENUE_HEADER_RE = re.compile(r"(?:路费|通行费)收入（人民币，万元，含增值税）?")
VALUE_TOKEN_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
BARE_YEAR_RE = re.compile(r"20\d{2}$")
LABEL_TOKENS = {
    "当月",
    "环比",
    "同比",
    "变动",
    "变化",
    "累计",
    "月份",
    "项目",
    "本月",
    "本期",
    "本年",
    "当年",
    "本年累计",
    "当年累计",
    "月",
    "年",
}
NOTE_MARKERS = ("备注", "注：")
PERIOD_ANCHOR = r"主要(?:运营|经营)数据"
ARABIC_PERIOD_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
CN_DIGITS = "〇零一二三四五六七八九十"
CN_PERIOD_RE = re.compile(rf"([{CN_DIGITS}]{{4}})年([{CN_DIGITS}]+)月")
LABEL_CHARS = set("当月环比同比变动累计年")
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
NAME_NUMBER_RE = re.compile(r"^(.*?)(-?\d[\d,]*(?:\.\d+)?%?)$")


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


def _is_label_token(token: str) -> bool:
    """判断文本流 token 是否为表头标签碎片（当月/环比/变动/2026年/2026年累 等）。"""
    s = token.strip()
    if not s:
        return True
    if s in LABEL_TOKENS:
        return True
    if re.fullmatch(r"20\d{2}年(?:累?计?)?", s):
        return True
    if BARE_YEAR_RE.match(s):
        return True
    return all(ch in LABEL_CHARS for ch in s)


def _is_label_fragment(s: str) -> bool:
    """判断是否为纯表头标签碎片（如 年/月/当/累 等单个表头用字）。"""
    return bool(s) and all(ch in LABEL_CHARS for ch in s)


def _is_data_value(token: str) -> bool:
    """是否为真实数据数值（排除被当作表头标签的裸年份，如 2026/2024）。"""
    return bool(VALUE_TOKEN_RE.fullmatch(token)) and not re.fullmatch(r"20\d{2}", token)


MONTH_INT_RE = re.compile(r"\d{1,2}")


def _is_month_int(token: str) -> bool:
    """裸整数月份名片段（如 6/12）判断；20xx 年份仍按年份处理，不算月份。"""
    return bool(MONTH_INT_RE.fullmatch(token)) and not BARE_YEAR_RE.match(token)


def _split_name_number(token: str):
    """拆分“名称+数值”黏连的 token（如 6月45237 → (“6月”, “45237”)）。

    若 token 尾部是数值则拆分，否则返回 (None, None)。
    """
    m = NAME_NUMBER_RE.match(token)
    if m and m.group(1):
        return m.group(1), m.group(2)
    return None, None


NAME_ENUM_RE = re.compile(r"[（(][一二三四五六七八九十]{1,3}[）)]")
NAME_FRAGMENT_RE = re.compile(
    r"(?<![\u4e00-\u9fa5])([\u4e00-\u9fa5]{1,8}(?:高速|公路|大桥|隧道))(?![一-龥])"
)


def _extract_name_fragment(text: str):
    """从文本中提取含 高速/公路/大桥/隧道 且去空白后长度 ≤ 12 的名称片段。

    仅接受以中文连续片段且关键词位于边界处的候选（避免误取正文长句），
    并剔除“（一）”等章节编号前缀（如「（一）杭徽高速2026…」→「杭徽高速」）。
    """
    cleaned = NAME_ENUM_RE.sub("", text)
    for m in NAME_FRAGMENT_RE.finditer(cleaned):
        fragment = m.group(1)
        if len(fragment) <= 12:
            return fragment
    return None


def _fallback_project_name(blocks, header_page: int, data_start_y: float):
    """全块范围检索含 高速/公路/大桥/隧道 的名称片段作为项目名兜底。

    用于项目名未直接出现在数据行（如浙商沪杭甬 508001 公告把项目名放在表头
    上方标题「（一）杭徽高速…主要经营数据」，或单独一行、跨块换行包绕）的格式。
    跳过备注区，避免正文中的「杭徽全程」等片段误入。
    """
    for pno, block in reversed(blocks):
        text = block[4]
        note_idx = _find_note_start(text, 0)
        if note_idx != len(text):
            text = text[:note_idx]
        fragment = _extract_name_fragment(text)
        if fragment:
            return fragment
    return None


def parse_pdf(pdf_path: Path) -> dict:
    """坐标版解析月度运营公告 PDF，覆盖多表头措辞与单项目“月份”列格式。

    用 fitz 按文本块坐标定位「日均(收费|自然)车流量（辆次）」与
    「(路费|通行费)收入（人民币，万元，含增值税）」两个表头，在其下方
    按行顺序跳过标签、识别项目名、收集 10 个数值；报告期复用 _parse_period。
    """
    text = extract_text(pdf_path)

    traffic_header_block = None
    revenue_header_block = None
    traffic_header_page = None
    revenue_header_page = None
    with fitz.open(str(pdf_path)) as doc:
        for pno, page in enumerate(doc):
            for block in page.get_text("blocks"):
                bbox_text = block[4]
                if traffic_header_block is None and TRAFFIC_HEADER_RE.search(bbox_text):
                    traffic_header_block = block
                    traffic_header_page = pno
                if revenue_header_block is None and REVENUE_HEADER_RE.search(bbox_text):
                    revenue_header_block = block
                    revenue_header_page = pno
                if traffic_header_block is not None and revenue_header_block is not None:
                    break
            if traffic_header_block is not None and revenue_header_block is not None:
                break

    if traffic_header_block is None:
        raise ValueError("公告缺少“日均（收费/自然）车流量（辆次）”表头")
    if revenue_header_block is None:
        raise ValueError("公告缺少“（路费/通行费）收入（人民币，万元，含增值税）”表头")

    header_page = max(traffic_header_page, revenue_header_page)
    data_start_y = max(
        traffic_header_block[3] if traffic_header_page == header_page else 0,
        revenue_header_block[3] if revenue_header_page == header_page else 0,
    )

    project_parts = []
    numbers = []
    blocks = []
    with fitz.open(str(pdf_path)) as doc:
        for pno, page in enumerate(doc):
            if pno < header_page:
                continue
            for block in page.get_text("blocks"):
                blocks.append((pno, block))
    blocks.sort(key=lambda item: (item[0], item[1][1]))

    for pno, block in blocks:
        if pno == header_page and block[1] < data_start_y:
            continue
        block_text = block[4]
        note_idx = _find_note_start(block_text, 0)
        truncated = note_idx != len(block_text)
        if truncated:
            block_text = block_text[:note_idx]
        block_tokens = block_text.split()
        if not numbers and all(
            _is_label_token(t) for t in block_tokens if t.strip()
        ):
            continue
        pending_year = None
        for token in block_tokens:
            if not token.strip():
                continue
            if numbers:
                if (
                    token == "月"
                    and not project_parts
                    and len(numbers) == 1
                    and _is_month_int(numbers[0])
                ):
                    project_parts.append(numbers.pop())
                    project_parts.append(token)
                    continue
                if _is_data_value(token):
                    numbers.append(token)
                    if len(numbers) >= 12:
                        break
                continue
            name_part, num_part = _split_name_number(token)
            if num_part is not None:
                if name_part and _is_label_fragment(name_part):
                    if not project_parts and pending_year:
                        project_parts.append(pending_year)
                        pending_year = None
                    project_parts.append(token)
                    continue
                if not project_parts and name_part and not _is_label_token(name_part):
                    project_parts.append(name_part)
                numbers.append(num_part)
                if len(numbers) >= 12:
                    break
                continue
            if project_parts:
                if _is_data_value(token):
                    numbers.append(token)
                    if len(numbers) >= 12:
                        break
                elif token == "月" and re.search(
                    r"年\d{1,2}$", "".join(project_parts)
                ):
                    project_parts.append(token)
                elif not _is_label_token(token):
                    project_parts.append(token)
                continue
            if BARE_YEAR_RE.match(token):
                pending_year = token
                continue
            if _is_label_token(token):
                continue
            if VALUE_TOKEN_RE.fullmatch(token):
                numbers.append(token)
                if len(numbers) >= 12:
                    break
                continue
            if pending_year and ("年" in token or "月" in token):
                project_parts.append(pending_year)
            project_parts.append(token)
            pending_year = None
        if truncated or len(numbers) >= 12:
            break

    project_name = "".join(project_parts)
    if len(numbers) < 10:
        raise ValueError(
            f"运营数据数值不足，期望 10 个，实际 {len(numbers)} 个"
        )
    if not project_name:
        project_name = _fallback_project_name(blocks, header_page, data_start_y)
    if not project_name:
        raise ValueError("未找到数据行项目名")

    period = _parse_period(text)
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
