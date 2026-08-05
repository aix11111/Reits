"""REITs 季度报告生态环保类运营指标解析（Phase 6c：处理量）。

生态环保类资产（污水处理/垃圾焚烧/供水水利）季报
「4.1.3 报告期及上年同期重要不动产项目运营指标」表格披露三项运营指标：

- 处理量/供水量（污水处理量、生活垃圾处理量、供应原水量，单位 万吨 或
  万立方米）
- 产能利用率（%）
- 服务费单价（元/吨，从「注：…单价为X 元/吨」提取）

多项目表（如污水处理厂按项目分列）取第一个项目的值（简化，如实标注不
合并）。PDF 表格单元格会跨行断字（如「污水处 理量」「产能利用 率」
「万 吨」「元/ 吨」），解析时把全部空白折叠为单个空格，用「字间可含
空白」的标签正则定位，取值锚定单位单元格之后。无处理量字段（非环保类，
或环保类未披露 4.1.3 表）→ 返回 None，供批量脚本跳过。
"""

import re
from pathlib import Path

import fitz

NUMBER = r"-?\d[\d,]*(?:\.\d+)?"

# 运营指标 → 标签变体（按序取第一个匹配；具体口径在前，避免「处理量」泛标签
# 先行命中「污水处理量/生活垃圾处理量」等）
ENV_METRICS = {
    "volume_wan_ton": (
        "污水处理量",
        "生活垃圾处理量",
        "供应原水量",
        "供水量",
        "处理量",
    ),
    "capacity_utilization_pct": (
        "生活垃圾处理产能利用率",
        "产能利用率",
        "处理产能利用率",
    ),
}

# 表格行取值正则（(正则, 倍率)）：单位列（紧邻本期值之前）→ 数值 × 倍率。
# 处理量/供水量单位 万吨 或 万立方米（断行容忍「万 吨」「万立方 米」）×1；
# 产能利用率单位 %（断行容忍「%」前留白）×1。数值锚定单位单元格之后。
ENV_TABLE_PATTERNS = {
    "volume_wan_ton": (
        (r"万\s*吨\s*(" + NUMBER + r")", 1),
        (r"万\s*立\s*方\s*米\s*(" + NUMBER + r")", 1),
    ),
    "capacity_utilization_pct": ((r"%\s*(" + NUMBER + r")", 1),),
}

ENV_KEYS = tuple(ENV_METRICS) + ("unit_price_yuan",)

# 标签后取值窗口长度（说明列 + 单位列 + 本期值），按最长的说明列留余量
_WINDOW = 300

# 4.1.3 节标题（「重要不动产项目运营指标」为主，旧报告为「重要资产项目运营
# 指标」）；取最后一次出现（跳过目录页里的节号引用）。
_SECTION_413_RE = re.compile(
    r"4\.1\.3\s*报告期(?:及|和)上年同期重要(?:不动产|资产)项目运营指标"
)
# 4.1.3 节之后的下一个节标题（4.1.4 起或 4.2）→ 截断扫描范围
_NEXT_SECTION_RE = re.compile(r"4\.1\.[4-9]|4\.2(?:\D|$)")

# 服务费单价：注「…含税单价为1.2980 元/吨」→ 数值（元/吨，断行容忍「元/ 吨」）
_UNIT_PRICE_RE = re.compile(
    r"单价\s*为\s*(" + NUMBER + r")\s*元\s*[/／]\s*吨"
)


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


def _env_section(text: str) -> str | None:
    """定位 4.1.3 节文本：标题起到下一个节标题（4.1.4/4.2）前为止。

    无 4.1.3 节标题（非环保类，或环保类旧报告无该表）→ None。
    """
    m = None
    for cand in _SECTION_413_RE.finditer(text):
        m = cand
    if m is None:
        return None
    start = m.end()
    nxt = _NEXT_SECTION_RE.search(text, start)
    end = nxt.start() if nxt is not None else len(text)
    return text[start:end]


def _scan_value(text: str, labels: tuple[str, ...], patterns: tuple[tuple[str, int], ...]):
    """沿标签每一处出现，取首个命中取值正则的数值×倍率；全部未命中返回 None。"""
    for label in labels:
        for m in re.finditer(_label_pattern(label), text):
            seg = text[m.end() : m.end() + _WINDOW]
            for pat, scale in patterns:
                num = re.search(pat, seg)
                if num is not None:
                    return _to_number(num.group(1)) * scale
    return None


def parse_env_ops_text(text: str) -> dict | None:
    """解析季报全文，返回三项生态环保运营指标；无处理量字段时返回 None。

    返回 {volume_wan_ton, capacity_utilization_pct, unit_price_yuan}，
    缺失的字段如实为 None。以 4.1.3 节「处理量/供水量」为环保类资产判定门：
    无 4.1.3 表或无处理量字段（非环保类）→ None。
    """
    flat = _normalize(text)
    section = _env_section(flat)
    if section is None:
        return None
    result = {}
    for key, labels in ENV_METRICS.items():
        result[key] = _scan_value(section, labels, ENV_TABLE_PATTERNS[key])
    price = _UNIT_PRICE_RE.search(section)
    result["unit_price_yuan"] = (
        _to_number(price.group(1)) if price is not None else None
    )
    if result["volume_wan_ton"] is None:
        return None
    return result


def extract_text(pdf_path: Path) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串（与 parser_quarterly 一致）。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def parse_env_ops(pdf_path: Path) -> dict | None:
    """解析生态环保类季报 PDF，返回 parse_env_ops_text 同构的字典（或 None）。"""
    return parse_env_ops_text(extract_text(pdf_path))
