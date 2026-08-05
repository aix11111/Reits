"""REITs 年报可供分配完成度解析（Phase 3 可供分配完成度）。

监管要求 REITs 年报披露「实际可供分配金额与招募说明书测算的差异」，
对应年报「3.3.3 本期可供分配金额与招募说明书中刊载的可供分配金额测算
报告的差异情况说明」段落。

深市（180201 2022 年报）：
「预测本基金2022 年度可供分配金额626,287,596.94 元，报告期内本基金实现
可供分配金额476,911,864.89 元，完成招募说明书预测的76.15%。」

沪市（508018 2022 年报）以「偏离度」表述、无年份：
「本报告期内，本基金实现可供分配金额为250,597,919.87 元，相较招募说明书
中披露的可供分配金额同期目标数（……为290,818,170.72 元），偏离度
为-13.83%。」→ completion_pct = round(100 + 偏离度, 2) = 86.17。

另一深市措辞（508008 2022 年报）：「预测的2022 年度可供分配金额为
427,054,548.82 元，本报告期实现可供分配金额为390,321,619.58 元，完成
《招募说明书》预测值的91.40%。」与深市共用宽松正则（年份「预测本基金」/
「预测的」、金额「为」可选、完成率「预测/预测值」及「的」可选）。

深市 180202 2022 年报（格式 D）：「本报告期内，本基金实现可供分配金额为
137,426,821.43 元，相较招募说明书中披露的2022 年可供分配金额（153,838,106.00
元），偏离度为-10.67%。」走沪市「偏离度」分支（括号内无「为」的预测金额），
年份从「披露的{YYYY} 年」提取，completion_pct = round(100 + (-10.67), 2) = 89.33。

深市 180203 2024 年报（格式 E）：「本报告期，本基金实现可供分配金额为
235,347,428.99 元，相较招募说明书中披露的可供分配同期目标数235,299,621.65 元，
完成招募说明书预测的100.02%。」预测金额取「同期目标数{X} 元」备选，段落无
年份 → year=None（调用方/页眉标题兜底）。

508066 2023 年报（格式 F）：混合单位——预测「22,512.32 万元」、实际
「227,778,602.49 元」；508009 2023 偏离度双万元（预测「同期目标数88,871.81 万元」
无括号）；508007 2023（格式 G）：「实际可供分配金额{X} 元，与招募说明书中刊载的
{YYYY} 年度可供分配预测金额{Y} 元相比，实际金额约为预测金额的{Z}%」；508086 2025
偏离度但预测「同期目标数600,017,286.71 元」无括号。所有金额正则统一捕获单位
（元|万元），经 _to_wan 换算为万元。

extract_text 用 pymupdf 逐页抽取 PDF 全文（与 parser_generic 一致）；
parse_annual_completion 定位「刊载的可供分配金额测算报告」段落（其后
窗口）后交给纯函数 _parse_completion_text 解析，找不到段落抛 ValueError。
年份：深市从段落「预测本基金{YYYY} 年度」/「预测的{YYYY} 年度」提取；沪市
「偏离度」段落从「披露的{YYYY} 年」提取（180202 格式），180203 格式段落无
年份可由调用方经 year 参数传入，未传时从全文「{YYYY} 年年度报告」/「{YYYY}
年度报告」标题兜底，仍找不到 → year=None。
金额统一 元→万元 除以 10000。
"""

import re
from pathlib import Path

import fitz

SECTION_MARKER = "刊载的可供分配金额测算报告"
SECTION_LIMIT = 800

NAV_PRICE_LABEL = "期末基金份额净值"
NAV_ASSET_LABEL = "期末基金净资产"

SHARES_LABEL = "报告期末基金份额总额"
SHARES_LABEL_PAT = re.compile(r"报告\s*期\s*末\s*基\s*金\s*份\s*额\s*总\s*额")

YEAR_RE = re.compile(
    r"(?:预测\s*本\s*基\s*金|预\s*测\s*的?|预\s*计)\s*(\d{4})\s*年度"
)
PREDICTED_RE = re.compile(
    r"(?:"
    r"(?<!实现)可供\s*分\s*配\s*金\s*额\s*(?:测\s*算\s*报\s*告)?\s*(?:为|数){0,2}\s*"
    r"(?P<predicted>\d[\d,]*(?:\.\d+)?)\s*(?P<predicted_unit>万元|元)"
    r"|同期目标[数值]\s*(?P<target>\d[\d,]*(?:\.\d+)?)\s*(?P<target_unit>万元|元)"
    r")"
)
# 实际金额：「实现」后可带「全年累计/的/全年」等词（鹏华/嘉实等管理人）。
ACTUAL_RE = re.compile(
    r"(?:实现|实际)\s*(?:全年累计|全年|的|本年度)?\s*可\s*供\s*分\s*配\s*金\s*额\s*为?\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
# 完成率：「完成」后可接「率/达/约为」且无「预测」字样（完成率为96%/
# 目标完成率达111.10%/完成率约为97%）。
COMPLETION_RE = re.compile(
    r"完成[^%\d]{0,14}(?:预测值?)?\s*的?\s*(\d+(?:\.\d+)?)\s*%"
)

SH_ACTUAL_RE = re.compile(
    r"(?:实现|实际)\s*(?:全年累计|全年|的|本年度)?\s*可\s*供\s*分\s*配\s*金\s*额\s*为?\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
SH_PREDICTED_RE = re.compile(
    r"(?:"
    r"[（(][^（）()]{0,200}?(\d[\d,]*(?:\.\d+)?)\s*(万元|元)\s*[）)]"
    r"|同期目标数\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
    r"|披露的\s*(\d{4})\s*年\s*可\s*供\s*分\s*配\s*金\s*额\s*预\s*测\s*数\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
    r"|预测的\s*(\d{4})\s*年\s*[^（()（）]{0,12}?\s*可\s*供\s*分\s*配\s*金\s*额\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
    r")"
)
SH_YEAR_RE = re.compile(r"披露的\s*(\d{4})\s*年")
DEVIATION_RE = re.compile(r"偏离度\s*为?\s*([-+]?\d+(?:\.\d+)?)\s*%")

G_ACTUAL_RE = re.compile(
    r"实际\s*可供\s*分配\s*金额\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
G_PREDICTED_RE = re.compile(
    r"(\d{4})\s*年\s*度\s*可\s*供\s*分\s*配\s*预\s*测\s*金\s*额\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
G_COMPLETION_RE = re.compile(r"约为预测金额的\s*(\d+(?:\.\d+)?)\s*%")

# 产业园「差异情况说明」格式（508000 等）：「本期可供分配金额为{X} 元，…
# 测算报告{YYYY} 年可供分配金额为{Y} 元」，不直接给出完成率 → 推导；
# 2025 起为表格格式「本期实现金额（万元）…可供分配金额|11,268.57|-|-」。
# 博时/招商蛇口另用「项目可供分配现金流{X} 元，较可供分配金额测算报告{Y} 元，
# 完成《招募说明书》预测的{Z}%」措辞。
DIFF_ACTUAL_RE = re.compile(
    r"本期\s*(?:实现)?\s*可\s*供\s*分\s*配\s*金\s*额\s*为?\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
DIFF_PREDICTED_RE = re.compile(
    r"(\d{4})\s*年\s*(?:度)?\s*可\s*供\s*分\s*配\s*(?:发\s*行\s*预\s*测\s*|预\s*测\s*)?\s*金\s*额\s*为?\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
CASHFLOW_ACTUAL_RE = re.compile(
    r"可\s*供\s*分\s*配\s*现\s*金\s*流\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
CASHFLOW_PREDICTED_RE = re.compile(
    r"较\s*可\s*供\s*分\s*配\s*金\s*额\s*测\s*算\s*报\s*告\s*(\d[\d,]*(?:\.\d+)?)\s*(万元|元)"
)
DIFF_TABLE_RE = re.compile(
    r"可\s*供\s*分\s*配\s*金\s*额\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(\d[\d,]*(?:\.\d+)?)?\s*(\d[\d,]*(?:\.\d+)?)?"
)
TABLE_HEADER_RE = re.compile(r"本\s*期\s*实\s*现\s*金\s*额|本\s*期\s*实\s*现\s*金")

# 无完成度数据：段落仅「无」「不涉及」（华夏越秀/中金交控 2023/2024 等）、
# 「招募说明书未披露{YYYY} 年可供分配金额」「未披露本期可供分配金额预测数」
# 「未预测{YYYY} 年可供分配金额」→ 金额字段为 None，不抛错。
NODISCLOSURE_RE = re.compile(
    r"招募说明书\s*未\s*披\s*露\s*(?:本期|\s*(\d{4})\s*年)\s*"
    r"可\s*供\s*分\s*配\s*金\s*额(?:\s*预\s*测\s*数?)?"
)
NOTPREDICTED_RE = re.compile(
    r"未\s*预\s*测\s*(\d{4})\s*年\s*可\s*供\s*分\s*配\s*金\s*额"
)
NOVALUE_COMPARE_RE = re.compile(
    r"无\s*与\s*预\s*测\s*值\s*的\s*比\s*较|未\s*提\s*供\s*(\d{4})\s*年\s*度\s*预\s*测\s*值"
)
AMOUNT_HINT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*[亿]?\s*(?:万)?元")

# 费用节边界（折叠后）：完成度段落之后的费用叙述含大量金额，判定无数据时
# 需只检查完成度段落本身，排除费用节的金额污染。
FEE_SECTION_CUTS = (
    "3.4报告期内基金及资产支持证券费用",
    "3.4报告期内基金费用",
    "3.4报告期内不动产基金费用",
    "3.4报告期内",
)


def _completion_portion(text: str) -> str:
    """返回完成度段落正文（截止到费用节「3.4…」之前），用于无数据判定。"""
    for cut in FEE_SECTION_CUTS:
        idx = text.find(cut)
        if idx != -1:
            return text[:idx]
    return text

# 净值叙述/表格格式（508000 2023+）：「基金份额净值人民币2.9780 元」或
# 「基金份额净值 |2.7614 |2.9656」——无「期末」前缀也解析。
NAV_NARRATIVE_RE = re.compile(
    r"基金份额净值\s*人民币?\s*(\d[\d,]*(?:\.\d+)?)\s*元?"
)

REPORT_YEAR_RE = re.compile(r"(\d{4})\s*年\s*年度报告")
REPORT_YEAR_SHORT_RE = re.compile(r"(\d{4})\s*年度报告")


def extract_text(pdf_path: str) -> str:
    """逐页抽取 PDF 文本并拼接为单个字符串。"""
    pages = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n".join(pages)


def _to_number(raw: str):
    """将抽取出的原始数值字符串转为数值，去除千分位逗号。"""
    normalized = raw.replace(",", "")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _to_wan(raw: str, unit: str) -> float:
    """按捕获单位将数值换算为万元：万元原值、元除以 10000。"""
    value = _to_number(raw)
    if unit == "元":
        return value / 10000.0
    return float(value)


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _extract_nav_value(text: str, label: str) -> float | None:
    """返回 label 后的第一个数值；早期年报无净值披露时返回 None。

    按行取 label 后的首个数字：完整数值行含小数点即停止；值跨行（数字被
    换行截断，如 508001「3,438,945,95\\n5.16」）时上一行无小数点、续接下一行
    数字直到出现小数点，绝不与相邻年份数值合并。千分位逗号由 _to_number
    去除。
    """
    idx = text.find(label)
    if idx == -1:
        return None
    tail = text[idx + len(label) : idx + len(label) + 200]
    parts = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _NUM_RE.match(line)
        if match is None:
            break
        parts.append(match.group(0))
        if "." in parts[-1]:
            break
    if not parts:
        return None
    return _to_number("".join(parts))


def _extract_nav_price(text: str) -> float | None:
    """提取期末单位净值（元/份）。

    优先「期末基金份额净值」表格标签（值可跨行）；缺失时回退到
    「基金份额净值人民币{X} 元」叙述格式（508000 2023+）与无「期末」
    前缀的表格格式。
    """
    value = _extract_nav_value(text, NAV_PRICE_LABEL)
    if value is not None:
        return value
    narrative = NAV_NARRATIVE_RE.search(text)
    if narrative is not None:
        return _to_number(narrative.group(1))
    return _extract_nav_value(text, "基金份额净值")


def _extract_nav_fields(text: str) -> dict:
    """从全文提取净值字段：nav_unit_price（元/份）、nav_wan（万元）。

    早期年报无净值披露 → 字段为 None 不抛错。nav_wan 为「期末基金净资产」元值
    除以 10000 并保留两位。
    """
    nav_unit_price = _extract_nav_price(text)
    nav_wan = _extract_nav_value(text, NAV_ASSET_LABEL)
    if nav_wan is not None:
        nav_wan = round(nav_wan / 10000.0, 2)
    return {"nav_unit_price": nav_unit_price, "nav_wan": nav_wan}


def _find_completion_section(text: str, limit: int = SECTION_LIMIT) -> str:
    """返回「刊载的可供分配金额测算报告」标记后的段落窗口；找不到抛 ValueError。"""
    idx = text.find(SECTION_MARKER)
    if idx == -1:
        raise ValueError("未找到「刊载的可供分配金额测算报告」段落")
    return text[idx : idx + limit]


def _parse_shanghai_completion(text: str, year) -> dict:
    """解析沪市「偏离度」格式段落，返回 {year, predicted_wan, actual_wan, completion_pct}。

    实际金额取「实现可供分配金额为{X} 元」，预测金额取括号内「{X} 元)」
    （「为」可省略，如「（153,838,106.00 元）」或「（…为290,818,170.72 元）」），
    completion_pct = round(100 + 偏离度, 2)；year 由调用方传入，为 None 时从
    「披露的{YYYY} 年」（180202 格式）提取，找不到保持 None。
    """
    actual_match = SH_ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实现可供分配金额")

    predicted_match = SH_PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")

    deviation_match = DEVIATION_RE.search(text)
    if deviation_match is None:
        raise ValueError("未找到偏离度")

    if predicted_match.group(1) is not None:
        predicted_raw = predicted_match.group(1)
        predicted_unit = predicted_match.group(2)
    elif predicted_match.group(3) is not None:
        predicted_raw = predicted_match.group(3)
        predicted_unit = predicted_match.group(4)
    else:
        # 「披露的{YYYY} 年可供分配金额预测数{X} 元」/「预测的{YYYY} 年…可供分配金额{X}」
        predicted_raw = (
            predicted_match.group(6)
            if predicted_match.group(6) is not None
            else predicted_match.group(9)
        )
        predicted_unit = (
            predicted_match.group(7)
            if predicted_match.group(7) is not None
            else predicted_match.group(10)
        )
        if year is None:
            hint = (
                predicted_match.group(5)
                if predicted_match.group(5) is not None
                else predicted_match.group(8)
            )
            if hint is not None:
                year = int(hint)

    if year is None:
        year_match = SH_YEAR_RE.search(text)
        if year_match is not None:
            year = int(year_match.group(1))

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_raw, predicted_unit),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": round(100 + _to_number(deviation_match.group(1)), 2),
    }


def _parse_g_completion(text: str, year) -> dict:
    """解析「约为预测金额的」格式段落（508007），返回同构字典。

    实际金额取「实际可供分配金额{X} 元」，预测金额取「{YYYY} 年度可供分配
    预测金额{Y} 元」，完成率取「约为预测金额的{Z}%」，年份从预测正则提取。
    """
    actual_match = G_ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实际可供分配金额")

    predicted_match = G_PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")

    completion_match = G_COMPLETION_RE.search(text)
    if completion_match is None:
        raise ValueError("未找到完成率")

    if year is None:
        year = int(predicted_match.group(1))

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_match.group(2), predicted_match.group(3)),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": _to_number(completion_match.group(1)),
    }


def _parse_no_data_completion(text: str, year=None) -> dict:
    """段落无完成度数据（「无」「不涉及」「未披露…预测数」「未预测{YYYY} 年」），
    返回年份 + 金额字段全 None。"""
    disclosure = NODISCLOSURE_RE.search(text)
    if disclosure is not None and disclosure.group(1) is not None:
        year = int(disclosure.group(1))
    notpredicted = NOTPREDICTED_RE.search(text)
    if notpredicted is not None:
        year = int(notpredicted.group(1))
    return {
        "year": year,
        "predicted_wan": None,
        "actual_wan": None,
        "completion_pct": None,
    }


def _parse_difference_completion(text: str, year=None, raw_text: str | None = None) -> dict:
    """解析产业园「差异情况说明」格式，返回 {year, predicted_wan, actual_wan,
    completion_pct}。

    叙述格式（508000 2021-2024）：「本期可供分配金额为{X} 元，…测算报告{YYYY} 年
    可供分配金额为{Y} 元」，报告不直接给出完成率 → completion_pct = 推导值；
    博时/招商蛇口现金流格式：「项目可供分配现金流{X} 元，较可供分配金额测算报告
    {Y} 元，完成《招募说明书》预测的{Z}%」→ 完成率取 Z；2025 表格格式
    「可供分配金额|实际|预测|完成度」→ 三项照实解析（万元原值，预测缺失为 None）。
    """
    result = {
        "year": year,
        "predicted_wan": None,
        "actual_wan": None,
        "completion_pct": None,
    }
    actual_match = DIFF_ACTUAL_RE.search(text)
    predicted_match = DIFF_PREDICTED_RE.search(text)
    if actual_match is not None:
        result["actual_wan"] = _to_wan(actual_match.group(1), actual_match.group(2))
    if predicted_match is not None:
        result["predicted_wan"] = _to_wan(predicted_match.group(2), predicted_match.group(3))
        # 段落「{YYYY} 年可供分配金额」的年份即报告年，优先于标题推断。
        result["year"] = int(predicted_match.group(1))

    if result["actual_wan"] is None or result["predicted_wan"] is None:
        # 表格数字在原始文本中以空白分隔，折叠后相邻数字会粘连
        # （如 8,052.61 6,489.62 → 8,052.616,489.62）→ 用原始文本匹配。
        table_match = DIFF_TABLE_RE.search(raw_text if raw_text is not None else text)
        if table_match is not None:
            if result["actual_wan"] is None:
                result["actual_wan"] = float(_to_number(table_match.group(1)))
            if result["predicted_wan"] is None and table_match.group(2) is not None:
                result["predicted_wan"] = float(_to_number(table_match.group(2)))
            if table_match.group(3) is not None:
                result["completion_pct"] = _to_number(table_match.group(3))
        else:
            cash_actual = CASHFLOW_ACTUAL_RE.search(text)
            cash_predicted = CASHFLOW_PREDICTED_RE.search(text)
            if result["actual_wan"] is None and cash_actual is not None:
                result["actual_wan"] = _to_wan(
                    cash_actual.group(1), cash_actual.group(2)
                )
            if result["predicted_wan"] is None and cash_predicted is not None:
                result["predicted_wan"] = _to_wan(
                    cash_predicted.group(1), cash_predicted.group(2)
                )
            completion_match = COMPLETION_RE.search(text)
            if completion_match is not None:
                result["completion_pct"] = _to_number(completion_match.group(1))

    if (
        result["completion_pct"] is None
        and result["actual_wan"] is not None
        and result["predicted_wan"] is not None
        and result["predicted_wan"] > 0
    ):
        result["completion_pct"] = round(
            result["actual_wan"] / result["predicted_wan"] * 100, 2
        )
    return result


def _parse_completion_text(text: str, year=None) -> dict:
    """解析年报可供分配完成度段落，返回 {year, predicted_wan, actual_wan, completion_pct}。

    空文本/None 返回空结构 {}；找不到段落/年份/金额/完成率时抛 ValueError。
    深市格式（含「预测本基金{YYYY} 年度」）：完成率为百分比原值（如 76.15）。
    沪市格式（含「偏离度」，无年份）：completion_pct = round(100 + 偏离度, 2)，
    year 取传入参数（可为 None）。
    预测金额 元→万元，实际金额 元→万元。
    """
    if not text:
        return {}

    # 折叠空白：抽取文本的换行可落在标签/数值任意两字符之间，折叠后
    # 所有带 \s* 的正则与「数字元」相邻捕获都稳定。表格数字需保留原始
    # 空白分隔，故 raw_text 一并传给差异格式处理器。
    raw_text = text
    text = re.sub(r"\s+", "", text)

    if SECTION_MARKER not in text:
        raise ValueError("未找到「刊载的可供分配金额测算报告」段落")

    if (
        NODISCLOSURE_RE.search(text)
        or NOTPREDICTED_RE.search(text)
        or NOVALUE_COMPARE_RE.search(text)
    ):
        return _parse_no_data_completion(text, year)

    # 差异情况说明/2025 表格优先：表格段后常附「偏离度」叙述（508092 等），
    # 若不先走表格分支会误入沪市偏离度分支。
    if (
        DIFF_ACTUAL_RE.search(text)
        or CASHFLOW_ACTUAL_RE.search(text)
        or TABLE_HEADER_RE.search(text)
    ):
        return _parse_difference_completion(text, year, raw_text=raw_text)

    if "偏离度" in text:
        return _parse_shanghai_completion(text, year)

    if "约为预测金额的" in text:
        return _parse_g_completion(text, year)

    if not AMOUNT_HINT_RE.search(_completion_portion(text)):
        # 完成度段落无任何金额披露（仅「无」「不涉及」或差异原因叙述）→ 无完成度数据。
        return _parse_no_data_completion(text, year)

    if year is None:
        year_match = YEAR_RE.search(text)
        if year_match is not None:
            year = int(year_match.group(1))
        elif "年度" in text:
            raise ValueError("未找到预测年份")

    predicted_match = PREDICTED_RE.search(text)
    if predicted_match is None:
        raise ValueError("未找到预测可供分配金额")
    predicted_raw = predicted_match.group("predicted") or predicted_match.group("target")
    predicted_unit = predicted_match.group("predicted_unit") or predicted_match.group(
        "target_unit"
    )

    actual_match = ACTUAL_RE.search(text)
    if actual_match is None:
        raise ValueError("未找到实现可供分配金额")

    completion_match = COMPLETION_RE.search(text)
    if completion_match is None:
        raise ValueError("未找到完成率")

    return {
        "year": year,
        "predicted_wan": _to_wan(predicted_raw, predicted_unit),
        "actual_wan": _to_wan(actual_match.group(1), actual_match.group(2)),
        "completion_pct": _to_number(completion_match.group(1)),
    }


def _find_report_year(text: str):
    """从全文「{YYYY} 年年度报告」或「{YYYY} 年度报告」标题提取年份；找不到返回 None。"""
    match = REPORT_YEAR_RE.search(text)
    if match is not None:
        return int(match.group(1))
    match = REPORT_YEAR_SHORT_RE.search(text)
    if match is not None:
        return int(match.group(1))
    return None


def _extract_fund_shares(text: str) -> float | None:
    """返回「报告期末基金份额总额」后的份额数值（份）；找不到返回 None。

    label 本身可能跨行（如「报告期末基金份额\\n总额」），用容空白正则定位；
    数字可含千分位逗号、值跨行（数字被换行截断，如 700,000,00\\n0.00）——
    将 label 后窗口内全部空白折叠后再以「数字+份」正则匹配，避免与相邻
    字段数值合并。部分季报 label 自带「（单位：份）」且数值不带「份」后缀
    （如 508006「报告期末基金份额总额（单位：份）500,000,000.00」）——
    无「数字+份」时回退到窗口内首个数值（label 后的首个数字即份额）。
    """
    match = SHARES_LABEL_PAT.search(text)
    if match is None:
        return None
    tail = text[match.end() : match.end() + 200]
    collapsed = re.sub(r"\s+", "", tail)
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*份", collapsed)
    if match is None:
        match = re.search(r"(\d[\d,]*(?:\.\d+)?)", collapsed)
    if match is None:
        return None
    return float(_to_number(match.group(1)))


def parse_fund_shares(pdf_path: str) -> float | None:
    """解析年报 PDF 的「报告期末基金份额总额」（份）；找不到返回 None。"""
    return _extract_fund_shares(extract_text(pdf_path))


def build_fund_shares_snapshot(annual_dir: str, fund_codes) -> tuple[dict, list]:
    """遍历年报缓存目录，每基金取报告年份最新的一条份额值。

    文件名 {code}_annual_{公告年}.pdf；公告年≠报告年，报告年从 PDF 标题
    「{YYYY} 年年度报告」解析（_find_report_year）。返回 (shares, missing)：
    shares 为 {code: 份额}；missing 为无年报文件或无法解析份额的基金代码。
    """
    shares = {}
    missing = []
    by_code = {}
    for f in sorted(Path(annual_dir).glob("*.pdf")):
        code = f.name.split("_")[0]
        if code not in fund_codes:
            continue
        try:
            text = extract_text(f)
        except Exception:
            continue
        year = _find_report_year(text)
        if year is None:
            continue
        value = _extract_fund_shares(text)
        if value is None:
            continue
        cur = by_code.get(code)
        if cur is None or year > cur[0]:
            by_code[code] = (year, value)
    for code in fund_codes:
        if code in by_code:
            shares[code] = by_code[code][1]
        else:
            missing.append(code)
    return shares, missing


def parse_annual_completion(pdf_path: str, year=None) -> dict:
    """解析年报 PDF 的「可供分配完成度」段落，返回 _parse_completion_text 同构字典。

    year 可选：沪市段落无年份时传入；为 None 时从全文页眉标题
    「{YYYY} 年年度报告」/「{YYYY} 年度报告」兜底，找不到 → year=None。
    返回字典额外含 nav_unit_price（元/份）、nav_wan（万元）两个净值字段
    （早期年报无净值披露 → None）。
    """
    text = extract_text(pdf_path)
    if year is None:
        year = _find_report_year(text)
    result = _parse_completion_text(_find_completion_section(text), year)
    result.update(_extract_nav_fields(text))
    return result
