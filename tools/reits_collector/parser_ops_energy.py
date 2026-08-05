"""REITs 季度报告能源类运营指标解析（Phase 6：发电量/结算电价/运营年限）。

能源类资产（能源/生态环保电力项目）季报「4.1.3 报告期及上年同期重要不
动产项目运营指标」表格披露五项运营指标：

- 发电量（万千瓦时）
- 等效利用小时数（小时）
- 结算电量 / 上网电量（万千瓦时）
- 结算电费（元，→ 万元）
- 结算电价（元/千瓦时）

同时 4.1 节「其他运营情况的说明」披露不动产项目运营年限
（如「不动产项目运营年限预计至2037 年」）→ ops_until_year，供能源类
基金剩余年限 IRR 计算使用。

PDF 表格单元格会跨行断字（如「等效利用小 时数」「结算电 价」），且不同
管理人对标签表述略有差异（「结算电量」vs「上网电量」、「结算电价」vs
「平均结算电价」）。解析时把全部空白折叠为单个空格，用「字间可含空白」
的标签正则定位，取值锚定单位单元格之后（避免公式列中的数字污染，如
「售电收入/结算电量*(1+增值税税率)」）。

单位口径：发电量/结算电量为 万千瓦时（×1）或 亿千瓦时（×10000 折算）两种
披露口径；等效利用小时为 小时；结算电费接受 元（除以 10000 折算万元）或
万元（如实取）两种披露口径；结算电价为 元/千瓦时（含税注记容忍）。无发电
量字段（非能源类，或能源类未披露 4.1.3 表）→ 返回 None，供批量脚本跳过。
"""

import re
from pathlib import Path

import fitz

NUMBER = r"-?\d[\d,]*(?:\.\d+)?"

# 运营指标 → 标签变体（按序取第一个匹配）
ENERGY_METRICS = {
    "generation_wan_kwh": ("发电量",),
    "utilization_hours": ("等效利用小时数", "利用小时数", "等效利用小时"),
    "grid_wan_kwh": ("结算电量", "上网电量"),
    "electricity_revenue_wan": ("结算电费",),
    "price_yuan_kwh": ("结算电价", "平均结算电价", "结算均价"),
}

# 表格行取值正则（(正则, 倍率)）：单位列（紧邻本期值之前）→ 数值 × 倍率。
# 发电量/结算电量单位 万千瓦时（×1，断行容忍「万千瓦 时」）或 亿千瓦时
# （×10000 折算万千瓦时）；等效利用小时单位 小时（×1）；结算电费单位
# 元 或 万元（断行容忍「万 元」，按单位决定是否折算）；结算电价单位
# 元/千瓦时（单位后可选括号注记如「（含税）」「(含税)」）。数值锚定单位
# 单元格之后，且不允许跨长句扫描（避免叙述段「0.5 元/千瓦时…」之后偶发
# 的年份/序号数字污染取值）。
_NOTE = r"\s*(?:[（(][^（）()]*[）)])?\s*"

ENERGY_TABLE_PATTERNS = {
    "generation_wan_kwh": (
        (r"万千瓦\s*时\s*(" + NUMBER + r")", 1),
        (r"亿千瓦\s*时\s*(" + NUMBER + r")", 10000),
    ),
    "utilization_hours": ((r"小时\s*(" + NUMBER + r")", 1),),
    "grid_wan_kwh": (
        (r"万千瓦\s*时\s*(" + NUMBER + r")", 1),
        (r"亿千瓦\s*时\s*(" + NUMBER + r")", 10000),
    ),
    "electricity_revenue_wan": (),
    "price_yuan_kwh": ((r"元[\s/／]*千\s*瓦\s*时" + _NOTE + r"(" + NUMBER + r")", 1),),
}

ENERGY_KEYS = tuple(ENERGY_METRICS)

# 标签后取值窗口长度（公式列 + 单位列 + 本期值），按电价公式留余量
_WINDOW = 300

# 4.1 节「不动产项目运营年限预计至 {YYYY} 年」→ 运营到期年份
_OPS_UNTIL_YEAR_RE = re.compile(r"运营年限预计至\s*(\d{4})\s*年")


def _normalize(text: str) -> str:
    """全部空白折叠为单个空格：保留 token 边界（数值不粘连），
    同时让断行标签在字间留白处可被空白通配的正则匹配。"""
    return re.sub(r"\s+", " ", text)


def _label_pattern(label: str) -> str:
    """标签 → 字间可含任意空白的正则（PDF 表格断字容忍）。"""
    return r"\s*".join(re.escape(ch) for ch in label)


def _to_number(raw: str):
    """数值字符串 → 数字：去除千分位逗号。"""
    normalized = raw.replace(",", "")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _scan_value(
    text: str, labels: tuple[str, ...], patterns: tuple[tuple[str, int], ...]
):
    """沿标签每一处出现，取首个命中取值正则的数值×倍率；全部未命中返回 None。"""
    for label in labels:
        for m in re.finditer(_label_pattern(label), text):
            seg = text[m.end() : m.end() + _WINDOW]
            for pat, scale in patterns:
                num = re.search(pat, seg)
                if num is not None:
                    return _to_number(num.group(1)) * scale
    return None


def _scan_revenue(text: str, labels: tuple[str, ...]):
    """结算电费取值：单位「亿元」×10000 折算万元、「万元」如实取、
    「元」除以 10000 折算万元（断行容忍「亿 元」「万 元」）。

    公式列/描述列可能含数字（如「售电收入/结算电量」），锚定单位单元格
    之后取数；描述列在前、单位单元格紧邻本期值之前。
    """
    for label in labels:
        for m in re.finditer(_label_pattern(label), text):
            seg = text[m.end() : m.end() + _WINDOW]
            num = re.search(r"(亿\s*元|万\s*元|元)\s*(" + NUMBER + r")", seg)
            if num is not None:
                value = _to_number(num.group(2))
                if "亿" in num.group(1):
                    return value * 10000.0
                if "万" in num.group(1):
                    return value
                return value / 10000.0
    return None


def parse_energy_ops_text(text: str) -> dict | None:
    """解析季报全文，返回六项能源运营指标；无发电量字段时返回 None。

    返回 {generation_wan_kwh, utilization_hours, grid_wan_kwh,
    electricity_revenue_wan, price_yuan_kwh, ops_until_year}，
    缺失的字段如实为 None。以「发电量」为能源类资产判定门：无发电量字段
    （非能源类，或能源类未披露 4.1.3 运营指标表）→ None。
    """
    flat = _normalize(text)
    result = {}
    for key, labels in ENERGY_METRICS.items():
        if key == "electricity_revenue_wan":
            result[key] = _scan_revenue(flat, labels)
        else:
            result[key] = _scan_value(flat, labels, ENERGY_TABLE_PATTERNS[key])
    match = _OPS_UNTIL_YEAR_RE.search(flat)
    result["ops_until_year"] = int(match.group(1)) if match is not None else None
    if result["generation_wan_kwh"] is None:
        return None
    return result


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串（与 parser_quarterly 一致）。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def parse_energy_ops(pdf_path: Path) -> dict | None:
    """解析能源类季报 PDF，返回 parse_energy_ops_text 同构的字典（或 None）。"""
    return parse_energy_ops_text(extract_text(pdf_path))
