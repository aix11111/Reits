"""REITs 季度报告 PDF 解析。

extract_text 用 pymupdf 逐页抽取 PDF 全文（与 parser_generic 一致）；
parse_quarterly_report 面向沪深两市统一的季度报告模板：

- 「3.1 主要财务指标」表格给出 本期收入 / 本期净利润 / 本期现金流分派率(%)；
- 「3.3.1 本报告期的可供分配金额」表格给出 期间(本期/本年累计) 行的
  可供分配金额 与 单位可供分配金额；
- EBITDA 出现在财务分析节（位置可能为 3.x 或 4.x），取当期值；
- total_cost_wan 取「4.2.1 不动产项目公司整体财务情况」表的「营业成本/费用」
  行（部分管理人标签为「营业成本」「总成本」，容忍断行与千分位）。

报告期支持三种写法：标题「2026年第2季度报告」、正文
「报告期(2026年04月01日-2026年06月30日)」、中文数字年份
「二〇二六年第二季度报告」。金额类字段统一 元→万元 除以 10000。

与月度公告解析器不同：不同管理人披露详略不同，任一核心字段缺失时
对应值为 None（不抛异常）。
"""

import re
from pathlib import Path

import fitz

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

OLD_DISTRIBUTABLE_LABEL_RE = re.compile(r"本期可供分配金额(?!\S)")

NEW_DISTRIBUTABLE_TITLE_RE = re.compile(r"本报告期(?:及近三年)?的可供分配金额")

# 4.2.1 表「营业成本/费用」行：按标签优先级依次匹配，要求标签后（允许空白/
# 断行）紧跟数值，避免把叙述句（「营业成本及主要费用分析」「营业成本-管理人
# 报酬」等分项指标、日期中的年份）误当成成本值。
_COST_FEE_RE = re.compile(
    r"营业成本\s*/\s*费\s*用\s*[:：]?\s*(-?[\d,]+(?:\.\d+)?)"
)
_COST_STANDALONE_RE = re.compile(
    r"营业成本(?!/)(?!及)(?!-)(?!合)(?!计)(?!费)\s*[:：]?\s*(-?[\d,]+(?:\.\d+)?)"
)
_TOTAL_COST_RE = re.compile(r"总成本\s*[:：]?\s*(-?[\d,]+(?:\.\d+)?)")

_COST_PATTERNS = (_COST_FEE_RE, _COST_STANDALONE_RE, _TOTAL_COST_RE)

TITLE_PERIOD_RE = re.compile(r"(\d{4})\s*年第\s*([1-4一二三四])\s*季度")
CN_YEAR_PERIOD_RE = re.compile(
    r"([〇零一二三四五六七八九]{4})\s*年第\s*([1-4一二三四])\s*季度"
)
BODY_PERIOD_RE = re.compile(
    r"报告期[（(]?[起自至]?[\s]*(\d{4})\s*年\s*(\d{1,2})\s*月\s*\d{1,2}\s*日"
)

NOTE_MARKERS = ("注：", "注:", "备注")
WINDOW_CUTS = ("注：", "注:", "备注", "年化")

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
QUARTER_CN = {"一": 1, "二": 2, "三": 3, "四": 4}


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def _to_number(raw: str):
    """将抽取出的原始数值字符串转为数值，去除千分位逗号与百分号。"""
    normalized = raw.replace(",", "").rstrip("%")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _cn_digits_to_int(s: str) -> int:
    """按每位一数字的中文数字串（如“二〇二六”）转整数。"""
    value = 0
    for ch in s:
        if ch not in CN_DIGIT_VALUE:
            raise ValueError(f"无法识别中文数字：{s}")
        value = value * 10 + CN_DIGIT_VALUE[ch]
    return value


def _quarter_num(q: str) -> int:
    """季度序号：阿拉伯数字或中文数字（1-4/一-四）。"""
    if q.isdigit():
        return int(q)
    return QUARTER_CN[q]


def _quarter_from_month(month: int) -> int:
    return (month - 1) // 3 + 1


def _parse_period(text: str):
    """从标题/正文提取报告期，如「2026Q2」。

    优先级：标题「2026年第2季度报告」→ 中文数字年份标题 → 正文
    「报告期(2026年04月01日-2026年06月30日)」；均未匹配时返回 None。
    """
    m = TITLE_PERIOD_RE.search(text)
    if m:
        return f"{int(m.group(1))}Q{_quarter_num(m.group(2))}"
    m = CN_YEAR_PERIOD_RE.search(text)
    if m:
        return f"{_cn_digits_to_int(m.group(1))}Q{_quarter_num(m.group(2))}"
    m = BODY_PERIOD_RE.search(text)
    if m:
        return f"{int(m.group(1))}Q{_quarter_from_month(int(m.group(2)))}"
    return None


def _window_after(text: str, label: str, limit: int = 120) -> str:
    """返回标签之后、到下一个标签/注记边界为止的文本窗口。"""
    idx = text.find(label)
    if idx == -1:
        return ""
    start = idx + len(label)
    end = start + limit
    for marker in WINDOW_CUTS:
        pos = text.find(marker, start)
        if pos != -1:
            end = min(end, pos)
    return text[start:end]


def _value_after(text: str, label: str, limit: int = 120):
    """取标签后窗口内第一个数值；标签不存在或无数值时返回 None。"""
    m = NUMBER_RE.search(_window_after(text, label, limit))
    if m is None:
        return None
    return _to_number(m.group(0))


def _parse_old_distributable(text: str, limit: int = 120):
    """旧格式 fallback：取「本期可供分配金额」标签后的首个数值。

    2025Q1 及以前的报告没有「3.3.1 本报告期的可供分配金额」表，而是
    「3.3.3 本期可供分配金额计算过程」表中的完整标签行
    「本期可供分配金额  <金额> [-脚注标记]」。仅当该标签独立成行时
    才匹配（用 (?!\\S) 排除「本期可供分配金额计算过程」标题）。
    返回 (可供分配金额元, None)；未匹配返回 (None, None)。
    """
    m = OLD_DISTRIBUTABLE_LABEL_RE.search(text)
    if m is None:
        return None, None
    start = m.end()
    end = start + limit
    for marker in WINDOW_CUTS:
        pos = text.find(marker, start)
        if pos != -1:
            end = min(end, pos)
    num = NUMBER_RE.search(text[start:end])
    if num is None:
        return None, None
    return _to_number(num.group(0)), None


def _parse_distributable(text: str):
    """解析「3.3.1 本报告期的可供分配金额」/「3.3.1 本报告期及近三年的可供分配金额」
    表格中“本期”行的两个数值。

    返回 (可供分配金额元, 单位可供分配金额元)；任一行缺失时返回 (None, None)。
    新版表格缺失时回退到旧格式「本期可供分配金额」计算表（单位可供分配金额为 None）。
    """
    m = NEW_DISTRIBUTABLE_TITLE_RE.search(text)
    if m is None:
        return _parse_old_distributable(text)
    start = m.start()
    end_candidates = [
        text.find("本报告期的实际分配金额", start),
        text.find("3.3.2", start),
    ]
    found = [idx for idx in end_candidates if idx != -1]
    end = min(found) if found else start + 400
    lines = text[start:end].splitlines()

    for i, line in enumerate(lines):
        if not line.strip().startswith("本期"):
            continue
        values = []
        for j in range(i, len(lines)):
            current = lines[j].strip()
            if j > i and current.startswith("本年累计"):
                break
            values.extend(_to_number(n) for n in NUMBER_RE.findall(current))
            if len(values) >= 2:
                return values[0], values[1]
        break
    return None, None


def _to_wan(value):
    """金额元 → 万元；None 原样返回。"""
    if value is None:
        return None
    return value / 10000.0


def _value_after_any(text: str, labels: tuple[str, ...], limit: int = 120):
    """取任一标签后窗口内第一个数值；全部不存在或无数值时返回 None。

    按标签顺序取第一个有数值的标签（「本期收入」优先于「营业总收入」），
    兼容不同管理人对 3.1 主要财务指标收入行的不同表述。
    """
    for label in labels:
        value = _value_after(text, label, limit)
        if value is not None:
            return value
    return None


def _parse_ebitda(text: str, limit: int = 80):
    """取财务分析表中「EBITDA」行的当期值（元）。

    EBITDA 一词可能出现在叙述句中（如「收入和EBITDA同比下降超过10%」），
    需跳过：仅在「EBITDA」标签后跟表格数字（行内首个数值）时取值。
    采用扫所有出现位置、取首个「标签后紧跟数字」的匹配。
    """
    pos = -1
    while True:
        pos = text.find("EBITDA", pos + 1)
        if pos == -1:
            return None
        window = text[pos + len("EBITDA") : pos + len("EBITDA") + limit]
        m = NUMBER_RE.search(window)
        if m is None:
            continue
        prefix = window[: m.start()]
        if prefix.strip():
            continue
        return _to_number(m.group(0))


def _parse_total_cost(text: str):
    """取「4.2.1 不动产项目公司整体财务情况」表「营业成本/费用」行当期值（元）。

    按标签优先级匹配：营业成本/费用（容忍「营业成本/费\\n用」断行与千分位）
    → 独立「营业成本」行 → 「总成本」。仅当标签后紧跟数值时取值，因此
    「营业成本及主要费用分析」标题、「营业成本-管理人报酬」分项指标与
    「占该项目总成本比例」表头均不会误匹配；无成本行返回 None。
    """
    for pattern in _COST_PATTERNS:
        m = pattern.search(text)
        if m is not None:
            return _to_number(m.group(1))
    return None


def parse_quarterly(text: str) -> dict:
    """解析季度报告全文，返回含 8 个键的字典（缺失字段为 None）。"""
    result = {"period": _parse_period(text)}
    result["revenue_wan"] = _to_wan(
        _value_after_any(text, ("本期收入", "营业总收入"))
    )
    result["total_cost_wan"] = _to_wan(_parse_total_cost(text))
    result["net_profit_wan"] = _to_wan(_value_after(text, "本期净利润"))
    result["cash_distribution_rate"] = _value_after(text, "本期现金流分派率")
    distributable, unit = _parse_distributable(text)
    result["distributable_wan"] = _to_wan(distributable)
    result["unit_distributable"] = unit
    result["ebitda_wan"] = _to_wan(_parse_ebitda(text))
    return result


def parse_quarterly_report(pdf_path: Path) -> dict:
    """解析季度报告 PDF 文件，返回 parse_quarterly 同构的字典。"""
    return parse_quarterly(extract_text(pdf_path))
