"""新加坡年报（Annual Report）财务摘要解析。

定位英文国际标准披露（S-REITs）年报的「Selected Statement of Total Return and
Distribution Data」五年财务摘要表（行标签 + 5 年数字序列，取最新列），
提取财年与核心财务指标；缺失字段 → None 不抛错。

字段与标签：
- revenue_wan: Gross Revenue
- npi_wan: Net Property Income
- distributable_wan: Distributable Income
  （S$ million → ×100 万元；S$ billion → ×100000）
- dpu_cents: Distribution Per Unit (¢)，叙述式「DPU rose 6.4% YoY to 11.58 cents」兜底
- nav_per_unit: Net Asset Value Per Unit (S$)，叙述式「to S$2.14」兜底
- occupancy: Committed Occupancy {pct}%（label 前/后均可）
- fy: FY ended 31 December 2025 → "2025"
- currency: "SGD"
- period: "annual"

财年：S-REITs 均为 12 月 31 日（自然年）结束，取年份。
"""

import re
from pathlib import Path

import fitz

SUMMARY_MARKER_RE = re.compile(
    r"Selected\s+Statement\s+of\s+Total\s+Return\s+and\s+Distribution\s+Data",
    re.IGNORECASE,
)

_NUM = r"\d[\d,]*(?:\.\d+)?"
_NUM_RE = re.compile(_NUM)
_RUN_RE = re.compile(rf"{_NUM}(?:\s+{_NUM})*")

# 财年：for the financial year ended 31 December 2025 / as at 31 December 2025
_FY_RE = re.compile(r"(?:ended|as at)\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})", re.IGNORECASE)
_FY_SHORT_RE = re.compile(r"FY\s*(\d{4})", re.IGNORECASE)

# 五年摘要表行标签 → 提取字段（\s+ 容忍 PDF 提取的断行/多空格）
_LABEL_PATTERNS = {
    "revenue_wan": r"Gross\s+Revenue",
    "npi_wan": r"Net\s+Property\s+Income",
    "distributable_wan": r"Distributable\s+Income",
    "nav_per_unit": r"Net\s+Asset\s+Value\s+Per\s+Unit",
    "dpu_cents": r"Distribution\s+Per\s+Unit",
}

# 叙述式 DPU：「DPU rose 6.4% YoY to 11.58 cents」（含小数点点）
_DPU_NARRATIVE_RE = re.compile(
    r"DPU[^;\n]{0,60}?to\s+([\d.]+)\s*cents", re.IGNORECASE
)
# 叙述式 NAV：「Net asset value per Unit increased 0.9% to S$2.14.」
_NAV_NARRATIVE_RE = re.compile(
    r"Net asset value per Unit[^;\n]{0,60}?to\s+S?\$?\s*([\d]+(?:\.\d+)?)", re.IGNORECASE
)
# 出租率：label 在值前（Committed occupancy stood at 96.9%）或值在 label 前
#（96.9% 0.2 ppts YoY Committed Occupancy）。label 后至 % 之间不允许出现数字，
# 避免跨到下一个指标（Committed Occupancy Portfolio Performance S$27.4b 5.2%）。
_OCCUPANCY_AFTER_RE = re.compile(
    r"Committed\s+Occupancy[^%\d]{0,40}?([\d.]+)\s*%", re.IGNORECASE
)
_OCCUPANCY_BEFORE_RE = re.compile(
    r"([\d.]+)\s*%\s*[\d.]+\s*ppts\s+YoY\s+Committed\s+Occupancy", re.IGNORECASE
)

# 五年摘要表金额单位：S$ million → ×100；S$ billion → ×100000
_SCALE_RE = re.compile(
    r"S\$\s*\(?\s*(million|billion|m|b)\s*\)?", re.IGNORECASE
)


def _row_last(text, label_re):
    """标签后紧邻数字序列的最后一个值（五年摘要表最新列）。

    跳过「label (S$) 2.06 ...」的单位括号；数字序列需连续（首个 token 即数字），
    避开叙述句中值在 label 之后的「increased ... to S$X」结构（交由叙述式兜底）。
    """
    for m in re.finditer(label_re, text, re.IGNORECASE):
        rest = text[m.end(): m.end() + 300]
        unit = re.match(r"\s*(?:\([^)]*\))?\s*", rest)
        rest = rest[unit.end():]
        run = _RUN_RE.match(rest)
        if not run:
            continue
        vals = [float(n.replace(",", "")) for n in _NUM_RE.findall(run.group(0))]
        if vals:
            return vals[-1]
    return None


def _section_scale(section):
    """摘要表段金额单位 → 换算倍率（million=100、billion=100000）。"""
    m = _SCALE_RE.search(section)
    if m and m.group(1).lower() in ("billion", "b"):
        return 100000
    return 100


def _scale_wan(value, scale):
    if value is None:
        return None
    return round(value * scale, 2)


def _extract_summary_table(text):
    """五年摘要表（Selected Statement of Total Return and Distribution Data）
    优先：行标签 + 数字序列取最新列；NAV/DPU 取全局首个标签行。"""
    idx = SUMMARY_MARKER_RE.search(text)
    if idx is None:
        return None
    section = text[idx.start(): idx.start() + 6000]
    scale = _section_scale(section)
    result = {
        "revenue_wan": _scale_wan(
            _row_last(section, _LABEL_PATTERNS["revenue_wan"]), scale
        ),
        "npi_wan": _scale_wan(
            _row_last(section, _LABEL_PATTERNS["npi_wan"]), scale
        ),
        "distributable_wan": _scale_wan(
            _row_last(section, _LABEL_PATTERNS["distributable_wan"]), scale
        ),
        "nav_per_unit": _row_last(text, _LABEL_PATTERNS["nav_per_unit"]),
        "dpu_cents": _row_last(text, _LABEL_PATTERNS["dpu_cents"]),
    }
    if result["revenue_wan"] is None and result["npi_wan"] is None:
        return None
    return result


def _extract_fiscal_year(text):
    """FY ended 31 December 2025 → "2025"（S-REITs 均为自然年结束）。"""
    for m in _FY_RE.finditer(text):
        return m.group(2)
    m = _FY_SHORT_RE.search(text)
    if m:
        return m.group(1)
    return None


def _extract_occupancy(text):
    m = _OCCUPANCY_AFTER_RE.search(text)
    if not m:
        m = _OCCUPANCY_BEFORE_RE.search(text)
    if not m:
        return None
    return round(float(m.group(1)) / 100, 4)


def _empty_result():
    return {
        "period": "annual",
        "fy": None,
        "currency": "SGD",
        "revenue_wan": None,
        "npi_wan": None,
        "distributable_wan": None,
        "dpu_cents": None,
        "nav_per_unit": None,
        "occupancy": None,
    }


def _parse_sg_annual_text(text):
    """纯函数：从全文文本解析新加坡年报财务摘要，字段缺失 → None。"""
    result = _empty_result()
    if not text:
        return result
    result["fy"] = _extract_fiscal_year(text)
    result["occupancy"] = _extract_occupancy(text)

    summary = _extract_summary_table(text)
    if summary:
        for key in (
            "revenue_wan",
            "npi_wan",
            "distributable_wan",
            "nav_per_unit",
            "dpu_cents",
        ):
            result[key] = summary[key]

    if result["dpu_cents"] is None:
        m = _DPU_NARRATIVE_RE.search(text)
        if m:
            result["dpu_cents"] = round(float(m.group(1)), 2)
    if result["nav_per_unit"] is None:
        m = _NAV_NARRATIVE_RE.search(text)
        if m:
            result["nav_per_unit"] = round(float(m.group(1)), 4)
    return result


def parse_sg_annual(pdf_path):
    """解析新加坡年报 PDF：fitz 提取全文后调用 _parse_sg_annual_text。"""
    doc = fitz.open(str(pdf_path))
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return _parse_sg_annual_text(text)
