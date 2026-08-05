"""REITs 季度报告租赁类运营指标解析（M5：产业园/保租房出租率）。

租赁类资产（产业园/保障房/消费/仓储物流）季报「4.1.2 报告期以及上年
同期不动产项目整体运营指标」/「4.1.3 …重要不动产项目运营指标」表格披露
四项运营指标：

- 期末出租率（%）
- 平均租金单价（元/平/天 或 元/平方米/月）
- 期末剩余租期（天）
- 期末租金收缴率（%）

结果附 rent_unit 字段标注平均租金的单位口径：
- "yuan_per_sqm_day"（元/平/天，产业园等常见）
- "yuan_per_sqm_month"（元/平方米/月，消费类常见）
- None（无法识别时间维度，如仅「元/平方米」）

PDF 表格单元格会跨行断字（如「期末租金收缴/率」「期末剩余租/期」），
且不同管理人对标签表述略有差异（「出租率」vs「期末出租率」、「平均合同
单价」vs「平均租金单价」）。解析时把全部空白折叠为单个空格（保 token
边界、避免相邻单元格数值粘连），用「字间可含空白」的标签正则定位。

取值优先级：
1. 表格行（单位列紧邻本期值之前，如「% 88.12」「元/平/天 5.44」）——
   锚定单位取数可避免公式列中的数字污染（如收缴率公式「=1-截至6月30日
   …」、出租率公式「×100%」）；
2. 旧报告无 4.1.2 表格时退化为叙述段（数值在前、% 在后，如「整体出租率
   为82.31%」），仅对出租率/收缴率开放。

单位口径：出租率/收缴率为 %；租金接受各管理人披露口径（元/…/天 或
元/…/月，如 元/平/天、元/平方米/月，值按披露数字如实取，单位随取值正则
的匹配串识别出 rent_unit）；剩余租期为天（年口径不折算、如实 None）。无
出租率字段（非租赁类资产，如高速/能源）→ 返回 None，供批量脚本跳过。
"""

import re
from pathlib import Path

import fitz

NUMBER = r"-?\d[\d,]*(?:\.\d+)?"

# 运营指标 → 标签变体（按序取第一个匹配）
RENTAL_METRICS = {
    "occupancy_pct": ("期末出租率", "出租率"),
    "avg_rent_yuan": ("平均租金单价", "平均合同单价", "平均含税月租金", "平均月末租金", "租金单价"),
    "collection_pct": ("期末租金收缴率", "租金收缴率", "收缴率"),
    "remaining_lease_days": ("期末剩余租期", "加权平均剩余租期", "租约剩余期限", "剩余租期"),
}

# 表格行取值正则：单位列（紧邻本期值之前）→ 数值。
# 出租率/收缴率为 %；租金接受各管理人披露口径（元/…/天 或 元/…/月，如
# 元/平/天、元/平方米/月）；剩余租期为 天（年口径不折算、如实 None）。
# 单位后可选注记（括号或逗号引导的短说明，如「（不含增值税）」「，含税」
# 「（取整）」），允许出现在单位与本期值之间。
_NOTE = r"(?:(?:（[^（）]*）|，[^\d，]*)\s*)?"

RENTAL_TABLE_PATTERNS = {
    "occupancy_pct": (r"%\s*(" + NUMBER + r")",),
    # 元/…/天、元/…/月 或仅元/面积（如「元/平方米」，时间维度隐含在
    # 标签中）；面积单位「平方米/平米/平方/平」本身可能断行拆分；段间允许
    # 空格与斜杠任意混排，且「面积/时间」或「时间/面积」两种段序都可能出现
    # （如「元/平方米 /月」「元/月/平方米」）；单位后可选括号注记
    "avg_rent_yuan": (
        r"元[\s/／]*(?:㎡|平\s*方?\s*米?)(?:[\s/／]*(?:天|月))?\s*"
        + _NOTE
        + r"(" + NUMBER + r")",
        r"元[\s/／]*(?:天|月)[\s/／]*(?:㎡|平\s*方?\s*米?)\s*"
        + _NOTE
        + r"(" + NUMBER + r")",
    ),
    "collection_pct": (r"%\s*(" + NUMBER + r")",),
    "remaining_lease_days": (r"天\s*" + _NOTE + r"(" + NUMBER + r")",),
}

# 叙述段取值正则（旧报告无表格时兜底，仅出租率/收缴率）：
# 数值在前、% 在后，如「整体出租率为82.31%」「租金收缴率为98.67%」。
RENTAL_NARRATIVE_PATTERNS = {
    "occupancy_pct": (r"(" + NUMBER + r")\s*%",),
    "collection_pct": (r"(" + NUMBER + r")\s*%",),
}

RENTAL_KEYS = tuple(RENTAL_METRICS) + ("rent_unit",)

# 平均租金单位 → rent_unit 枚举（时间维度「天/月」；无时间维度 → None）
RENT_UNIT_BY_SYMBOL = {
    "天": "yuan_per_sqm_day",
    "月": "yuan_per_sqm_month",
}

# 标签后取值窗口长度（公式列 + 单位列 + 本期值），按最长的租金公式留余量
_WINDOW = 300


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


def _scan_value(text: str, labels: tuple[str, ...], patterns: tuple[str, ...]):
    """沿标签每一处出现，取首个命中取值正则的数值；全部未命中返回 None。"""
    for label in labels:
        for m in re.finditer(_label_pattern(label), text):
            seg = text[m.end() : m.end() + _WINDOW]
            for pat in patterns:
                num = re.search(pat, seg)
                if num is not None:
                    return _to_number(num.group(1))
    return None


def _rent_unit_from_match(match_str: str) -> str | None:
    """租金取值正则整段匹配串 → rent_unit 枚举。

    匹配串形如「元/平/天 5.44」「元/平方 米/月 444.53」「元/平方米 46.05」，
    按其中出现的时间维度字符（天/月）判定；两者皆无 → None。
    """
    for symbol, unit in RENT_UNIT_BY_SYMBOL.items():
        if symbol in match_str:
            return unit
    return None


def _scan_rent(text: str, labels: tuple[str, ...]) -> tuple:
    """平均租金专用扫描：返回 (数值, rent_unit)；未命中 (None, None)。

    单位随取值正则的整段匹配串识别（单位单元格紧邻本期值之前，匹配串中
    必然含时间维度「天/月」或二者皆无）。
    """
    for label in labels:
        for m in re.finditer(_label_pattern(label), text):
            seg = text[m.end() : m.end() + _WINDOW]
            for pat in RENTAL_TABLE_PATTERNS["avg_rent_yuan"]:
                num = re.search(pat, seg)
                if num is not None:
                    value = _to_number(num.group(1))
                    return value, _rent_unit_from_match(num.group(0))
    return None, None


def _value_after_any(text: str, labels: tuple[str, ...], key: str):
    """表格行取值优先；无表格行时（旧报告）回退叙述段取值。

    返回 (数值, rent_unit)：仅 avg_rent 携带单位（随取值正则匹配串识别），
    其余字段单位为 None。
    """
    if key == "avg_rent_yuan":
        value, unit = _scan_rent(text, labels)
        return value, unit
    value = _scan_value(text, labels, RENTAL_TABLE_PATTERNS[key])
    if value is not None:
        return value, None
    narrative = RENTAL_NARRATIVE_PATTERNS.get(key)
    if narrative is not None:
        return _scan_value(text, labels, narrative), None
    return None, None


def parse_rental_ops_text(text: str) -> dict | None:
    """解析季报全文，返回运营指标；无出租率字段时返回 None。

    返回 {occupancy_pct, avg_rent_yuan, collection_pct, remaining_lease_days,
    rent_unit}，缺失/单位不符的字段如实为 None（rent_unit 取值：
    "yuan_per_sqm_day" / "yuan_per_sqm_month" / None）。以「期末出租率」为
    租赁类资产判定门：无出租率字段（非租赁类资产）→ None。
    """
    flat = _normalize(text)
    result = {}
    for key, labels in RENTAL_METRICS.items():
        result[key], unit = _value_after_any(flat, labels, key)
        if key == "avg_rent_yuan":
            result["rent_unit"] = unit
    if result["occupancy_pct"] is None:
        return None
    return result


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串（与 parser_quarterly 一致）。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def parse_rental_ops(pdf_path: Path) -> dict | None:
    """解析租赁类季报 PDF，返回 parse_rental_ops_text 同构的字典（或 None）。"""
    return parse_rental_ops_text(extract_text(pdf_path))
