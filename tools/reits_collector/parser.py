"""广河 REIT 月度运营公告 PDF 解析。

extract_text 用 pymupdf 逐页抽取 PDF 全文；
parse_monthly_announcement 按“日均收费车流量（辆次）”与
“路费收入（人民币，万元，含增值税）”两行表头解析出当月 / 当月环比 /
当月同比 / 累计 / 累计同比共 10 个数值，并提取报告期。

解析面对 PDF 抽取文本中数值与中文标签交错、千分位逗号、百分号等
情况保持稳健；任一部分缺失时抛出 ValueError 说明缺失项。
"""

import re
from pathlib import Path

import fitz

TRAFFIC_HEADER = "日均收费车流量（辆次）"
REVENUE_HEADER = "路费收入"
DATA_ROW_LABEL = "广州段"
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
PERIOD_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月主要运营数据")


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def _parse_period(text: str) -> str:
    """从正文提取报告期，如“2026 年6 月主要运营数据” -> "2026-06"。"""
    match = PERIOD_RE.search(text)
    if not match:
        raise ValueError("未找到报告期（YYYY 年M 月）")
    year, month = match.groups()
    return f"{year}-{int(month):02d}"


def _to_number(raw: str):
    """将抽取出的原始数值字符串转为数值，去除千分位逗号与百分号。"""
    normalized = raw.replace(",", "").rstrip("%")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def parse_monthly_announcement(text: str) -> dict:
    """解析广河格式月度运营公告，返回含 11 个键的字典。"""
    if TRAFFIC_HEADER not in text:
        raise ValueError("公告缺少“日均收费车流量（辆次）”表头")
    if REVENUE_HEADER not in text:
        raise ValueError("公告缺少“路费收入（人民币，万元，含增值税）”表头")

    period = _parse_period(text)

    start = text.find(TRAFFIC_HEADER)
    end = text.find("备注", start)
    if end == -1:
        end = len(text)
    segment = text[start:end]

    label_index = segment.rfind(DATA_ROW_LABEL)
    if label_index == -1:
        raise ValueError(f"未找到数据行标签（{DATA_ROW_LABEL}）")
    data_segment = segment[label_index + len(DATA_ROW_LABEL):]

    numbers = NUMBER_RE.findall(data_segment)
    if len(numbers) < 10:
        raise ValueError(
            f"运营数据数值不足，期望 10 个，实际 {len(numbers)} 个"
        )

    traffic, revenue = numbers[:5], numbers[5:10]
    return {
        "period": period,
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
