"""港年报（Annual Report）财务摘要解析。

定位年报「Financial Highlights」/「主要財務數據」摘要段（优先）或全文，
提取财年与核心财务指标，兼容英文（领展）与中文（阳光/泓富/顺丰等）报告。

字段与标签：
- revenue_wan: Revenue / 收益 / 總收益
- npi_wan: Net Property Income / 物業收入淨額
- dpu_hk_cents: Distribution per Unit / DPU / 每基金單位分派
  （含叙述式「每基金單位分派總額為0.1156港元」「每基金單位全年分派」）
- nav_per_unit_hkd: Net Asset Value per Unit / 每基金單位資產淨值
- occupancy: Retail {pct}%

数字换算 _to_wan：
- 百萬港元 / HK$X M → ×100（万元）；億港元 → ×10000；HK$X B → ×100000
- 完整港元值（如 408,500,000 港元）→ ÷10000
- DPU：港仙/HK¢ 直取；港元/港幣 每单位 → ×100（港仙）
- NAV：每单位港元/港幣 直取

财年：
- 英文「for the year ended 31 March 2025」→ "2024/25"；「31 December 2025」→ "2025"
- 中文「截至2025年12月31日止年度」→ "2025"
- 中文数字「截至二零二五年十二月三十一日止全年度」→ "2025"

字段缺失 → None 不抛错。
"""

import re
from pathlib import Path

import fitz

SECTION_MARKERS = ("Financial Highlights", "主要財務數據")
SECTION_LIMIT = 2500

# 财年（英文）：for the year ended {day} {Month} {year}
_FY_RE = re.compile(
    r"for\s+the\s+year\s+ended\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
# 财年（中文）：截至{年}年{月}月[{日}]止[全]年度（年月日可为中文数字）
_CN_FY_RE = re.compile(
    r"截至\s*(?P<yr>[\d零一二三四五六七八九〇○兩]{4})\s*年\s*"
    r"(?P<mo>\d{1,2}|[一二三四五六七八九十]{1,3})\s*月\s*"
    r"(?:\d{1,2}|[一二三四五六七八九十]{1,5})?\s*日?\s*止\s*(?:全)?年度"
)
# 中期报告期（英文）：for the six months ended 30 September 2025
_H1_EN_FY_RE = re.compile(
    r"for\s+the\s+(?:six\s+months|half[- ]year)\s+ended\s+\d{1,2}\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
# 中期报告期（中文）：截至2025年6月30日止六個月（年月日可为中文数字）
_H1_CN_FY_RE = re.compile(
    r"截至\s*(?P<yr>[\d零一二三四五六七八九〇○兩]{4})\s*年\s*"
    r"(?P<mo>\d{1,2}|[一二三四五六七八九十]{1,3})\s*月\s*"
    r"(?:\d{1,2}|[一二三四五六七八九十]{1,5})?\s*日?\s*止\s*六個月"
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

_CN_DIGIT = {
    "〇": 0,
    "○": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_DIGIT_CHARS = "〇○零一二三四五六七八九兩"

# 金额：HK$14,223M / HK¢272.34 / 港幣778.1百萬元 / 408,500,000 港元 /
# 61.708 億港元 / 18.2港仙 / 0.1156港元 / 港幣7.09 / 人民幣0.0043元
# （label 可前置或后置）
_AMOUNT_RE = re.compile(
    r"(?:"
    r"HK[ \t]*(?P<cur>[¢$])[ \t]*"
    r"|"
    r"(?P<cn>港[幣]?)[ \t]*"
    r")?"
    r"(?P<num>[\d,]+(?:\.\d+)?)"
    r"\s*(?P<scale>M\b|B\b|百萬|億)?"
    r"\s*(?P<unit>港元|港仙|元)?"
)

# 叙述式中文数额：「至人民幣二十二億零九百萬元」→ 220900 万元
_CN_AMT_CHARS = "零〇一二三四五六七八九兩十百千萬億"
_CN_NARRATIVE_RE = re.compile(
    rf"至\s*人民幣\s*([{_CN_AMT_CHARS}]+)元"
)

_LABELS = {
    "revenue_wan": (r"Revenue", r"收\s*益\s*(?!率)", r"總\s*收\s*益\s*(?!率)"),
    "npi_wan": (r"Net\s*Property\s*Income", r"物\s*業\s*收\s*入\s*淨\s*額"),
    "dpu_hk_cents": (
        r"Distribution\s*per\s*Unit",
        r"DPU",
        r"每\s*基\s*金\s*單\s*位\s*(?:全年)?\s*分\s*派",
    ),
    "nav_per_unit_hkd": (
        r"Net\s*Asset\s*Value\s*per\s*Unit",
        r"每\s*基\s*金\s*單\s*位\s*資\s*產\s*淨\s*值",
    ),
}

# 叙述式联合句：「收益及物業收入淨額分別放緩至408,500,000港元及305,200,000港元」
_JOINT_REV_NPI_RE = re.compile(
    r"收益及物業收入淨額[^\d]*"
    r"(?P<rev>[\d,]+(?:\.\d+)?)\s*港元[^\d]*(?:及|、)[^\d]*"
    r"(?P<npi>[\d,]+(?:\.\d+)?)\s*港元"
)

# DPU 优先命中的上下文（叙述式全年总额）
_DPU_PREFER = ("總額", "全年")

# 叙述式 FY2025 收益及物業收入淨額（置富 MD&A）：
# 「錄得總收益1,682.4百萬港元」+「物業收入淨額按年減少5.2%至1,188.1百萬港元」
_FY_REVENUE_NARRATIVE_RE = re.compile(
    r"總收益\s*([\d,]+(?:\.\d+)?)\s*百萬\s*港元"
)
_FY_NPI_NARRATIVE_RE = re.compile(
    r"物業收入淨額[^。]{0,20}至\s*([\d,]+(?:\.\d+)?)\s*百萬\s*港元"
)
# 叙述式联合句（FY2025）：「錄得收益1,682.4百萬港元及物業收入淨額1,188.1百萬港元」
_FY_REV_NPI_JOINT_RE = re.compile(
    r"收益\s*([\d,]+(?:\.\d+)?)\s*百萬\s*港元\s*及\s*物業收入淨額\s*([\d,]+(?:\.\d+)?)\s*百萬\s*港元"
)
# 叙述式全年 DPU：「全年每基金單位分派按年下跌1.0%至35.22港仙」
_FY_DPU_NARRATIVE_RE = re.compile(
    r"全年\s*每\s*基\s*金\s*單\s*位\s*分\s*派[^。]{0,40}至\s*([\d.]+)\s*港仙"
)
# 叙述式中期 DPU：「中期每基金單位分派按年上升1.0%至18.41港仙」
_H1_DPU_NARRATIVE_RE = re.compile(
    r"中期\s*每\s*基\s*金\s*單\s*位\s*分\s*派[^。]{0,40}(?:至|為)\s*([\d.]+)\s*港仙"
)
# 叙述式通用 DPU（亿/百万均可）：「每基金單位分派由去年同期134.89港仙下降5.9%至126.88港仙」
_GEN_DPU_NARRATIVE_RE = re.compile(
    r"每\s*基\s*金\s*單\s*位\s*分\s*派[^。]{0,40}(?:至|為)\s*([\d.]+)\s*港仙"
)
# 叙述式（亿港元，领展 MD&A）：「收益由2024/2025上半年71.53億港元減少1.8%至70.23億港元」
_YI_REVENUE_NARRATIVE_RE = re.compile(
    r"收益[^。]{0,30}至\s*([\d,]+(?:\.\d+)?)\s*億港元"
)
_YI_NPI_NARRATIVE_RE = re.compile(
    r"物業收入淨額[^。]{0,30}至\s*([\d,]+(?:\.\d+)?)\s*億港元"
)

# 摘要表段标（表現摘要/Performance Summary）：标签顺序-数字顺序对齐
_SUMMARY_MARKERS = ("表現摘要", "Performance Summary")

# 出租率：Retail 97.8% → {"retail": 0.978}
RETAIL_OCCUPANCY_RE = re.compile(r"Retail\s*([\d.]+)\s*%", re.IGNORECASE)

# per-unit 裸数字（每基金單位資產淨值，值不带单位，如「3.1737」）：
# 非「,」/数字开头的含小数数值，且后不接 百万/亿/M/B/百分比/货币单位（总额或比率）
_PER_UNIT_BARE_RE = re.compile(
    r"(?<![\d,])(\d+\.\d+)"
    r"(?!\s*(?:百萬|億|M\b|B\b|%|個百分點|港元|港幣|人民幣|元))"
)


def _cn_to_int(s):
    """中文数字/阿拉伯数字 → int：二零二五 → 2025；12 → 12。"""
    if s.isdigit():
        return int(s)
    total = 0
    for ch in s:
        if ch == "十":
            total = total + 10 if total else 10
        elif ch in _CN_DIGIT:
            total = total * 10 + _CN_DIGIT[ch]
    return total


def _cn_number(s):
    """中文数字串（不含亿/万）→ int：二千八百 → 2800；二十二 → 22。"""
    num = 0
    unit = 0
    for ch in s:
        if ch in _CN_DIGIT:
            unit = _CN_DIGIT[ch]
        elif ch == "十":
            num += 10 if unit == 0 else unit * 10
            unit = 0
        elif ch == "百":
            num += unit * 100
            unit = 0
        elif ch == "千":
            num += unit * 1000
            unit = 0
    return num + unit


def _cn_wan(s):
    """中文数额（含亿/万）→ 万元：二十二億零九百萬元 → 220900。"""
    if "億" in s:
        yi_s, _, rest = s.partition("億")
        yi = _cn_number(yi_s) if yi_s.strip() else 0
        wan_s, _, _ = rest.partition("萬")
        wan = _cn_number(wan_s) if wan_s.strip() else 0
        return yi * 10000 + wan
    wan_s, _, _ = s.partition("萬")
    return _cn_number(wan_s) if wan_s.strip() else 0


def _cn_month_num(s):
    """月份：12 / 十二 → 12。"""
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + _CN_DIGIT[s[1:]]
    return _CN_DIGIT[s]


def _extract_fiscal_year(text, period="annual"):
    """从文本提取财年（取出现最多的财年，同年并列取最晚）：
    3 月末结束 → "2024/25"；12 月末 → "2025"。
    中期（period="interim"）：截至2025年6月30日止六個月 → "2025H1"（一律结束年+H1）。
    频率优先避免里程碑/附注中的往年或展望年份干扰。"""
    if not text:
        return None
    counts = {}
    if period == "interim":
        for match in _H1_EN_FY_RE.finditer(text):
            month = MONTHS.get(match.group(1).lower())
            if month is None:
                continue
            key = (int(match.group(2)), month)
            counts[key] = counts.get(key, 0) + 1
        for match in _H1_CN_FY_RE.finditer(text):
            key = (_cn_to_int(match.group("yr")), _cn_month_num(match.group("mo")))
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return None
        year, month = max(counts, key=lambda k: (counts[k], k))
        return f"{year}H1"
    for match in _FY_RE.finditer(text):
        month = MONTHS.get(match.group(1).lower())
        if month is None:
            continue
        key = (int(match.group(2)), month)
        counts[key] = counts.get(key, 0) + 1
    for match in _CN_FY_RE.finditer(text):
        key = (_cn_to_int(match.group("yr")), _cn_month_num(match.group("mo")))
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    year, month = max(counts, key=lambda k: (counts[k], k))
    if month <= 3:
        return f"{year - 1}/{str(year)[2:]}"
    return str(year)


def _is_valid_amount(m):
    """仅接受带货币语境（HK/港币前缀或 百万/亿/港元/港仙/M/B 后缀）的金额，
    拒绝「2024」「26.33」这类裸数字。"""
    return bool(
        m.group("cur") or m.group("cn") or m.group("scale") or m.group("unit")
    )


def _interpret_amount(m, field):
    """_AMOUNT_RE 匹配 → 按字段换算。"""
    num = float(m.group("num").replace(",", ""))
    scale = m.group("scale") or ""
    unit = m.group("unit") or ""
    cur = m.group("cur") or ""
    if field == "dpu_hk_cents":
        if unit == "港仙" or cur == "¢":
            return round(num, 2)  # 港仙直取
        return round(num * 100, 2)  # 每单位港元 → 港仙
    if field == "nav_per_unit_hkd":
        return round(num, 2)  # 每单位港元直取
    # revenue / npi → 万元
    if scale in ("M", "百萬"):
        return round(num * 100, 2)  # 百万港元 → 万元
    if scale == "B":
        return round(num * 100000, 2)  # 十亿港元 → 万元
    if scale == "億":
        return round(num * 10000, 2)  # 亿港元 → 万元
    if unit in ("港元", "元"):
        return round(num / 10000, 2)  # 完整港元/元 → 万元
    return round(num, 2)


def _line_range(window, pos):
    """pos 所在行的 [start, end)。"""
    start = window.rfind("\n", 0, pos) + 1
    end = window.find("\n", pos)
    if end == -1:
        end = len(window)
    return start, end


def _adjacent(gap):
    """label 与金额之间仅允许少量无数字文本（脚注/量词），视为字段自有值。"""
    return (
        len(gap) <= 12
        and not re.search(r"\d", gap)
        and not re.search(f"[{_CN_DIGIT_CHARS}]", gap)
    )


def _nearest_amount(window, lm, field, cjk):
    """label 匹配 lm 邻域内最近的合法金额 → 换算值；无 → None。

    布局优先级：英文年报常为「值-标签」（Revenue HK$14,223M），中文为
    「标签-值」（收益 港幣778.1百萬元）。同行紧邻命中 > 跨行（本标签前一
    值）> 同行非紧邻，避免误配相邻字段的值。
    """
    ls, le = _line_range(window, lm.start())
    before_same = []
    for hm in _AMOUNT_RE.finditer(window[ls: lm.start()]):
        if _is_valid_amount(hm):
            gap = window[ls + hm.end(): lm.start()]
            before_same.append((_adjacent(gap), lm.start() - (ls + hm.end()), hm))
    after_same = []
    for tm in _AMOUNT_RE.finditer(window[lm.end(): le]):
        if _is_valid_amount(tm):
            gap = window[lm.end(): lm.end() + tm.start()]
            after_same.append((_adjacent(gap), tm.start(), tm))
    before_cross = []
    hstart = max(0, lm.start() - 200)
    for hm in _AMOUNT_RE.finditer(window[hstart: ls]):
        if _is_valid_amount(hm):
            before_cross.append((lm.start() - (hstart + hm.end()), hm))
    after_cross = []
    for tm in _AMOUNT_RE.finditer(window[le: lm.end() + 200]):
        if _is_valid_amount(tm):
            after_cross.append(((le + tm.start()) - lm.end(), tm))

    def _cls(adj, side, is_cross):
        if adj:
            # 同行紧邻 > 跨行；英文「值-标签」优先，中文「标签-值」优先
            if cjk:
                return 0 if side == "after" else 1
            return 0 if side == "before" else 1
        if is_cross:
            if cjk:
                return 2 if side == "after" else 3
            return 2 if side == "before" else 3
        if cjk:
            return 4 if side == "after" else 5
        return 4 if side == "before" else 5

    cands = []
    for adj, dist, m in before_same:
        cands.append((_cls(adj, "before", False), dist, m))
    for adj, dist, m in after_same:
        cands.append((_cls(adj, "after", False), dist, m))
    for dist, m in before_cross:
        cands.append((_cls(False, "before", True), dist, m))
    for dist, m in after_cross:
        cands.append((_cls(False, "after", True), dist, m))
    if field in ("revenue_wan", "npi_wan"):
        m = _CN_NARRATIVE_RE.search(window[lm.end(): lm.end() + 120])
        if m:
            try:
                value = _cn_wan(m.group(1))
            except (ValueError, TypeError):
                value = None
            if value:
                return round(value, 2)
    if field == "nav_per_unit_hkd":
        # 排除总额：應佔資產淨值后「人民幣百萬元/百萬港元」等 scale 值不可当 per-unit
        cands = [
            c
            for c in cands
            if c[2].group("scale") not in ("百萬", "M", "B", "億")
        ]
        if not cands and cjk:
            # per-unit 裸数字：标签后直接数字（「（人民幣元）」列头，值不带单位）
            m = _PER_UNIT_BARE_RE.search(window[lm.end() : lm.end() + 200])
            if m:
                return round(float(m.group(1)), 4)
        if not cands:
            return None
    if not cands:
        return None
    if field == "dpu_hk_cents":
        cents = [
            c
            for c in cands
            if c[2].group("unit") == "港仙" or c[2].group("cur") == "¢"
        ]
        if cents:
            cands = cents
    elif field in ("revenue_wan", "npi_wan"):
        cands = [
            c
            for c in cands
            if c[2].group("unit") != "港仙" and c[2].group("cur") != "¢"
        ]
        if not cands:
            return None
    cands.sort(key=lambda x: (x[0], x[1]))
    return _interpret_amount(cands[0][2], field)


def _find_amount(window, labels, field, prefer=()):
    """按标签在窗口内提取金额；prefer 关键词（如「總額」）优先于首个匹配。"""
    for label in labels:
        cjk = bool(re.search(r"[\u4e00-\u9fff]", label))
        hits = []
        for lm in re.finditer(label, window, re.IGNORECASE):
            value = _nearest_amount(window, lm, field, cjk)
            if value is None or value == 0:
                continue
            if field == "dpu_hk_cents" and value > 10000:
                # 每单位 DPU 港仙不会上万：排除误配的总额（物业估值/收入）
                continue
            ctx = window[lm.end(): lm.end() + 25]
            score = 1 if any(k in ctx for k in prefer) else 0
            hits.append((score, value))
        if hits:
            hits.sort(key=lambda x: -x[0])
            return hits[0][1]
    return None


def _extract_joint_rev_npi(window):
    """叙述式联合句：「收益及物業收入淨額…A港元及B港元」→ (revenue, npi) 万元。"""
    match = _JOINT_REV_NPI_RE.search(window)
    if not match:
        return None
    return (
        float(match.group("rev").replace(",", "")) / 10000,
        float(match.group("npi").replace(",", "")) / 10000,
    )


def _extract_occupancy(window):
    """首个「Retail {pct}%」→ {"retail": 0.978}；失败 → None。"""
    match = RETAIL_OCCUPANCY_RE.search(window)
    if not match:
        return None
    return {"retail": float(match.group(1)) / 100}


def _financial_highlights_window(text):
    """定位「Financial Highlights」/「主要財務數據」摘要段（其后窗口）；
    找不到 → 全文。"""
    best = None
    for marker in SECTION_MARKERS:
        index = text.find(marker)
        if index != -1 and (best is None or index < best):
            best = index
    if best is None:
        return text
    return text[best : best + SECTION_LIMIT]


def _extract_fy_narrative_rev_npi(text, period="annual"):
    """叙述式 FY2025 收益及物業收入淨額（置富 MD&A 财务回顧）：
    「錄得總收益1,682.4百萬港元」及「物業收入淨額按年減少5.2%至1,188.1百萬港元」。
    优先取联合句「收益A百萬港元及物業收入淨額B百萬港元」，否则分别取两句。
    中期（period="interim"）额外支持亿港元叙述式（领展 MD&A）。"""
    joint = _FY_REV_NPI_JOINT_RE.search(text)
    if joint:
        rev = float(joint.group(1).replace(",", ""))
        npi = float(joint.group(2).replace(",", ""))
        return (round(rev * 100, 2), round(npi * 100, 2))
    rev_m = _FY_REVENUE_NARRATIVE_RE.search(text)
    npi_m = _FY_NPI_NARRATIVE_RE.search(text)
    if rev_m and npi_m:
        rev = float(rev_m.group(1).replace(",", ""))
        npi = float(npi_m.group(1).replace(",", ""))
        return (round(rev * 100, 2), round(npi * 100, 2))
    if period == "interim":
        yi_rev = _YI_REVENUE_NARRATIVE_RE.search(text)
        yi_npi = _YI_NPI_NARRATIVE_RE.search(text)
        if yi_rev and yi_npi:
            rev = float(yi_rev.group(1).replace(",", ""))
            npi = float(yi_npi.group(1).replace(",", ""))
            return (round(rev * 10000, 2), round(npi * 10000, 2))
    return None


def _extract_summary_table(text):
    """摘要表（表現摘要 / Performance Summary）「标签顺序-数字顺序」对齐。

    摘要表内当年（非「2024年：」上年列）金额按出现顺序配给标签：
    收益/物業收入淨額取当年 亿/百万 级金额（按序），DPU 取港仙，NAV 取每单位港元。

    年报目录（TOC）可能先于正文出现「表現摘要」段标（其后仅有章节页码），
    须逐段尝试，取首个确实含金额序列（>=2 个 亿/百万 级金额）的摘要表。
    """
    occurrences = []
    for marker in _SUMMARY_MARKERS:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1:
                break
            occurrences.append(idx)
            start = idx + 1
    for idx in sorted(occurrences):
        result = _summary_table_at(text, idx)
        if result is not None:
            return result
    return None


def _summary_table_at(text, idx):
    section = text[idx : idx + SECTION_LIMIT]
    # 摘要表范围截止到页脚/下一节（年报页脚「年報」）
    for stop in ("年報", "年度報告", "Annual Report", "Performance Review"):
        si = section.find(stop)
        if si != -1:
            section = section[:si]
            break
    scale_vals = []  # (num, scale, pos) 当年 亿/百万级金额
    hkcent_vals = []  # 当年 港仙/¢
    hkd_vals = []  # 当年 每单位 港元
    bare_vals = []  # 当年裸数字（非 个百分點/百分比 差）
    for m in _AMOUNT_RE.finditer(section):
        pre = section[max(0, m.start() - 10) : m.start()]
        if "2024年" in pre:
            continue
        num = float(m.group("num").replace(",", ""))
        scale = m.group("scale") or ""
        unit = m.group("unit") or ""
        cur = m.group("cur") or ""
        if scale in ("億", "百萬", "M", "B"):
            scale_vals.append((num, scale, m.start()))
        elif unit == "港仙" or cur == "¢":
            hkcent_vals.append(num)
        elif unit == "港元" and not scale:
            hkd_vals.append(num)
        elif not (m.group("cur") or m.group("cn")):
            after = section[m.end() : m.end() + 12]
            if "個百分點" in after or after.lstrip().startswith("%"):
                continue
            if num >= 1000 and num == int(num):
                continue  # 排除「2024」「2025」等年份
            bare_vals.append((num, m.start()))
    if len(scale_vals) < 2:
        return None

    def _scale_wan(num, scale):
        if scale == "億":
            return round(num * 10000, 2)
        if scale in ("百萬", "M"):
            return round(num * 100, 2)
        if scale == "B":
            return round(num * 100000, 2)
        return num

    result = {}
    result["revenue_wan"] = _scale_wan(*scale_vals[0][:2])
    result["npi_wan"] = _scale_wan(*scale_vals[1][:2])
    if hkcent_vals:
        result["dpu_hk_cents"] = round(hkcent_vals[0], 2)
    elif bare_vals:
        first_scale_pos = scale_vals[0][2]
        late_bare = [b for b in bare_vals if b[1] >= first_scale_pos]
        if late_bare:
            result["dpu_hk_cents"] = round(late_bare[-1][0], 2)
    if hkd_vals:
        result["nav_per_unit_hkd"] = round(hkd_vals[0], 2)
    return result


def _parse_hk_annual_text(text, period="annual"):
    """纯函数：从全文文本解析港年报/中期报告财务摘要，字段缺失 → None。"""
    if not text:
        return _empty_result(period)
    window = _financial_highlights_window(text)
    result = _empty_result(period)
    result["fiscal_year"] = _extract_fiscal_year(text, period=period)

    summary = _extract_summary_table(text)
    if summary:
        for key in ("revenue_wan", "npi_wan", "dpu_hk_cents", "nav_per_unit_hkd"):
            result[key] = summary.get(key)
    else:
        fy_narr = _extract_fy_narrative_rev_npi(text, period=period)
        if fy_narr:
            result["revenue_wan"], result["npi_wan"] = fy_narr
        else:
            joint = _extract_joint_rev_npi(window)
            if joint:
                result["revenue_wan"], result["npi_wan"] = joint
            else:
                result["revenue_wan"] = _find_amount(
                    window, _LABELS["revenue_wan"], "revenue_wan"
                )
                result["npi_wan"] = _find_amount(window, _LABELS["npi_wan"], "npi_wan")
        dpu_narrative_res = (
            (_H1_DPU_NARRATIVE_RE, _GEN_DPU_NARRATIVE_RE)
            if period == "interim"
            else (_FY_DPU_NARRATIVE_RE,)
        )
        dpu_m = None
        for dpu_re in dpu_narrative_res:
            dpu_m = dpu_re.search(text)
            if dpu_m is not None:
                break
        if dpu_m is not None:
            result["dpu_hk_cents"] = round(float(dpu_m.group(1)), 2)
        else:
            result["dpu_hk_cents"] = _find_amount(
                window, _LABELS["dpu_hk_cents"], "dpu_hk_cents", prefer=_DPU_PREFER
            )
        result["nav_per_unit_hkd"] = _find_amount(
            window, _LABELS["nav_per_unit_hkd"], "nav_per_unit_hkd"
        )
    result["occupancy"] = _extract_occupancy(window)
    return result


def _empty_result(period="annual"):
    return {
        "period": period,
        "fiscal_year": None,
        "revenue_wan": None,
        "npi_wan": None,
        "dpu_hk_cents": None,
        "nav_per_unit_hkd": None,
        "occupancy": None,
    }


def parse_hk_annual(pdf_path, period="annual"):
    """解析港年报/中期报告 PDF：fitz 提取全文后调用 _parse_hk_annual_text。

    period="interim" 时 fiscal_year 输出 "2025H1"（截至2025年6月30日止六個月）。
    """
    doc = fitz.open(str(pdf_path))
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return _parse_hk_annual_text(text, period=period)


def parse_hk_interim(pdf_path):
    """解析港中期报告 PDF（period="interim"，fiscal_year 为 {结束年}H1）。"""
    return parse_hk_annual(pdf_path, period="interim")
