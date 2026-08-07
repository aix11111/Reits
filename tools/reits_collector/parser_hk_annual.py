"""港年报（Annual Report）财务摘要解析。

定位年报「Financial Highlights」段落（Financial Position 页的
Revenue / Net Property Income / DPU / NAV 快照），提取财年与核心财务指标。

真实年报文本（领展 2024/25，hk_linkreit_ar2425_financials.txt）：

    Financial Highlights ... HK$14,223M Revenue HK$10,619M Net Property
    Income HK¢272.34 Distribution per Unit HK$63.30 Net Asset Value per
    Unit ... Retail 97.8% Hong Kong 95.9% ...

数字容错：断行（HK$14,223\\nM）、千分位、HK¢/HK$ 符号变体、label 前后顺序
均可命中；字段缺失 → None 不抛错。

财年：全文「for the year ended 31 March 2025」→ "2024/25"
（2025-03-31 结束 → 财年起始 2024-04-01）；「for the year ended
31 December 2025」→ "2025"；提取不到 None。

parse_hk_annual 为 PDF 层薄封装：fitz 逐页抽取全文后交给纯函数
_parse_hk_annual_text 解析。
"""

import re
from pathlib import Path

import fitz

SECTION_MARKER = "Financial Highlights"
SECTION_LIMIT = 2500

# 财年：for the year ended {day} {Month} {year}
FY_RE = re.compile(
    r"for\s+the\s+year\s+ended\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# 港元金额：HK$14,223M / HK¢272.34 / HK$63.30（label 可前置或后置）
# _CURRENCY_H 仅限同行（[ \t] 间隔）；_CURRENCY 允许跨行（断行容错）。
_CURRENCY_H = r"HK[ \t]*[¢$]?[ \t]*([\d,]+(?:\.\d+)?)[ \t]*(M|B)?"
_CURRENCY = r"HK\s*[¢$]?\s*([\d,]+(?:\.\d+)?)\s*(M|B)?"
_LABELS = {
    "revenue_wan": "Revenue",
    "npi_wan": r"Net\s*Property\s*Income",
    "dpu_hk_cents": r"Distribution\s*per\s*Unit",
    "nav_per_unit_hkd": r"Net\s*Asset\s*Value\s*per\s*Unit",
}

# 出租率：Retail 97.8% → {"retail": 0.978}
RETAIL_OCCUPANCY_RE = re.compile(r"Retail\s*([\d.]+)\s*%", re.IGNORECASE)


def _extract_fiscal_year(text):
    """从文本提取财年：2025-03-31 结束 → "2024/25"；12 月末 → "2025"。"""
    if not text:
        return None
    match = FY_RE.search(text)
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    year = int(match.group(2))
    if month <= 3:
        return f"{year - 1}/{str(year)[2:]}"
    return str(year)


def _amount_from_match(match):
    """_CURRENCY 匹配 → 万元/原值（M=×100，B=×100000）。"""
    num = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").upper()
    if unit == "M":
        return num * 100  # 百万港元 → 万元
    if unit == "B":
        return num * 100000  # 十亿港元 → 万元
    return num


def _find_amount(window, label_pattern):
    """窗口内提取 label 邻接的港元金额，返回万元或原值。

    以 label 为锚点，按优先级尝试三种布局（避免跨行误配前一个字段的值）：
    1. 同行「值-标签」："HK$14,223M Revenue"（仅 [ \\t] 间隔）
    2. 同行「标签-值」："Net Property Income HK$10,619M"
    3. 断行「值-标签」："HK$10,619\\nM\\nNet Property Income"（容断行）
    """
    patterns = (
        re.compile(rf"{_CURRENCY_H}[ \t]*{label_pattern}", re.IGNORECASE),
        re.compile(rf"{label_pattern}[ \t]*{_CURRENCY_H}", re.IGNORECASE),
        re.compile(rf"{_CURRENCY}[ \t]*\n[ \t]*{label_pattern}", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(window)
        if match:
            return _amount_from_match(match)
    return None


def _extract_occupancy(window):
    """首个「Retail {pct}%」→ {"retail": 0.978}；失败 → None。"""
    match = RETAIL_OCCUPANCY_RE.search(window)
    if not match:
        return None
    return {"retail": float(match.group(1)) / 100}


def _financial_highlights_window(text):
    """定位「Financial Highlights」段落（其后窗口）；找不到 → 全文。"""
    index = text.find(SECTION_MARKER)
    if index == -1:
        return text
    return text[index : index + SECTION_LIMIT]


def _parse_hk_annual_text(text):
    """纯函数：从全文文本解析港年报财务摘要，字段缺失 → None。"""
    if not text:
        return _empty_result()
    window = _financial_highlights_window(text)
    result = {"fiscal_year": _extract_fiscal_year(text)}
    for key, label in _LABELS.items():
        result[key] = _find_amount(window, label)
    result["occupancy"] = _extract_occupancy(window)
    return result


def _empty_result():
    return {
        "fiscal_year": None,
        "revenue_wan": None,
        "npi_wan": None,
        "dpu_hk_cents": None,
        "nav_per_unit_hkd": None,
        "occupancy": None,
    }


def parse_hk_annual(pdf_path):
    """解析港年报 PDF：fitz 提取全文后调用 _parse_hk_annual_text。"""
    doc = fitz.open(str(pdf_path))
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return _parse_hk_annual_text(text)
