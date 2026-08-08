"""美国 10-K（SEC EDGAR HTML）财务解析。

10-K 为 HTML（Inline XBRL）而非 PDF——strip_html 剥离标签后正则处理（无 fitz）。
提取：
- fiscal_year: "Years Ended December 31, 2025" → "2025"
- revenue_wan: 损益表 "Total revenues" 行（报表单位 $000 → ×0.1 万美元；in millions → ×100）
- noi_wan: "Net operating income"/"NOI"（MD&A 表行，找不到 None）
- ffo_wan: "Funds From Operations" 表 "attributable to common stockholders" 行
  （$000 → ×0.1；找不到 None——部分公司 FFO 在补充材料，如实 None）
- dpu_usd: "quarterly cash dividends of $X" → X×4；"annual dividends of $X" → X；
  "dividends declared per share $X" → X
- occupancy: 美国 10-K 常不披露 → 默认 None
- currency: "USD"
- period: "annual"

表格行提取：行标签后第一个数字（可能带 $/千分位）；(XX) 负数剔除。
"""

import re

# 损益表头部：Statements of Operations / Income（容忍字母间空格，如 "Statem ents"），
# 后随单位标注（in/amounts in/dollars in thousands|millions）与年份列
# "Year(s) Ended December 31, 2025 2024"（允许逗号分隔）。
# 词间字母空格：EDGAR Inline XBRL 常把单词拆进多个 span（"Statem ents"、"O F"），
# 故关键字母允许可选的单空格（\s?）。
_WORD = lambda w: r"\s?".join(w)
_IS_HDR_RE = re.compile(
    rf"(?:CONSOLIDATED\s+)?"
    rf"(?:{_WORD('STATEMENT')}S?\s+{_WORD('OF')}\s+(?:{_WORD('OPERATIONS')}|{_WORD('INCOME')}|{_WORD('COMPREHENSIVE')}\s+{_WORD('INCOME')})"
    rf"|{_WORD('INCOME')}\s+{_WORD('STATEMENT')}S?)"
    rf"(?=.{{0,700}}?(?:in|amounts in|dollars in)\s+(thousands|millions))"
    rf"(?=.{{0,700}}?(?:Year|Years)\s+Ended\s+December\s+31,\s*20\d\d[,\s]+20\d\d)",
    re.IGNORECASE,
)

# 营业收入行：行标签 + 紧邻数字（$000/百万，无小数点即整数；带小数点即百万小数）
_REV_PATTERNS = [
    re.compile(r"(Total\s+operating\s+[Rr]evenue[s]?)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"(Total\s+[Rr]evenue[s]?)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"(Net\s+[Rr]evenue[s]?)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"(Total\s+income\s+from\s+real\s+estate)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"(Rental\s+and\s+other\s+property\s+[Rr]evenue[s]?)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"(Rental\s+income)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
    re.compile(r"([Rr]evenue[s]?)\s*\$?\s*([\d,]+(?:\.\d+)?)"),
]

# 营业收入段结束标签（费用段开头）
_EXPENSE_START_RE = re.compile(
    r"(?:Expenses?:|OPERATING\s+EXPENSES?|Operating\s+expenses?:|Costs?\s+and\s+operating\s+expenses?:)", re.IGNORECASE
)

_NUM_RUN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# 营业收入行后应紧跟费用段标签（确认取到的是损益表 total revenue 行而非
# MD&A 明细/合并平台汇总表）
_EXPENSE_AFTER_RE = re.compile(
    r"(?:Expenses?|OPERATING\s+EXPENSES?|Operating\s+expenses?|Costs?\s+and\s+operating\s+expenses?)",
    re.IGNORECASE,
)

_FY_RE = re.compile(
    r"(?:Year|Years)\s+Ended\s+December\s+31,\s*(20\d\d)", re.IGNORECASE
)

# 股息：季度 ×4 > 年度 > dividends declared per share
_DPU_QUARTERLY_RE = re.compile(
    r"quarterly\s+cash\s+dividends?\s+of\s+\$([\d.]+)", re.IGNORECASE
)
_DPU_ANNUAL_RE = re.compile(
    r"(?:annual|annualized)\s+dividends?\s+of\s+\$([\d.]+)", re.IGNORECASE
)
_DPU_DECLARED_RE = re.compile(
    r"dividends?\s+declared\s+per\s+share\s+\$([\d.]+)", re.IGNORECASE
)

# NOI：MD&A 表行 "Net operating income $ X" / "Net operating income 3,312,375"
#（排除 "(cash basis)" 叙述行；[^0-9.] 禁止跨句/定义段取数；max 过滤规避 per-sq-ft 小值）
_NOI_RE = re.compile(
    r"Net\s+operating\s+income(?!\s*\(?cash\s+basis)[^0-9.]{0,40}?(?:\$)?\s*(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

# FFO：表 "Funds From Operations ... attributable to common stockholders/unitholders $ X"
_FFO_RE = re.compile(
    r"Funds?\s+[Ff]rom\s+[Oo]perations[^.]{0,200}?"
    r"attributable\s+to\s+common\s+(?:stockholders?|shareholders?|unitholders?|stockholders\s+and\s+unitholders?)"
    r"[^0-9]{0,60}?\$\s*(\d[\d,]*(?:\.\d+)?)"
)

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _yearlike(value):
    """值是否为「年份」整数（如 2025.0），拒绝把年份当指标。"""
    return value == int(value) and 1990 <= value <= 2100


def strip_html(html):
    """剥离 HTML 标签并规范化实体/空白。

    - 剥离 <[^>]+>；
    - &#160;/&nbsp; → 空格；&#8217; → '；
    - &#8203;（零宽空格）→ 移除（EDGAR Inline XBRL 常见，干扰年份/数字 token）；
    - 压缩空白（含换行/多空格）。
    """
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&#160;", " ").replace("&nbsp;", " ")
    txt = txt.replace("&#8217;", "'")
    txt = txt.replace("&#8203;", "")
    txt = txt.replace("&#8220;", '"').replace("&#8221;", '"')
    txt = re.sub(r"&#\d+;", lambda m: chr(int(m.group()[2:-1])) if int(m.group()[2:-1]) >= 32 else " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def _scale_multiplier(scale):
    """损益表单位 → 万元换算倍率（in millions → ×100；其余 $000 → ×0.1）。"""
    return 100 if scale == "millions" else 0.1


def _extract_income_statement(text):
    """定位损益表：(头部位置, 单位倍率)。无 → None。"""
    for m in _IS_HDR_RE.finditer(text):
        scale = m.group(1).lower()
        return m.end(), _scale_multiplier(scale)
    return None


def _row_number(text, patterns):
    """行标签后第一个数字（可能带 $/千分位）；(XX) 负数剔除。"""
    for pat in patterns:
        m = pat.search(text)
        if m:
            raw = m.group(m.re.groups)
            return float(raw.replace(",", ""))
    return None


def _extract_revenue(text):
    """损益表营业收入（万元）。取全文中唯一/最大的损益表 total revenue 行。

    优先行标签模式（Total revenues / Net revenues / Total operating revenues...）；
    无标签行时兜底取损益表收入段（"Revenues:" 到首个费用段标签）末行的首个数值
    （部分公司收入合计无标签，如 ESS "1,887,345 1,774,450 1,669,395 Expenses:"）。
    """
    best = None
    for m in _IS_HDR_RE.finditer(text):
        scale = m.group(1).lower()
        mult = _scale_multiplier(scale)
        seg = text[m.end(): m.end() + 4000]
        found = None
        for pat in _REV_PATTERNS:
            for rm in pat.finditer(seg):
                v = float(rm.group(2).replace(",", ""))
                if v <= 0:
                    continue
                if _EXPENSE_AFTER_RE.search(seg[rm.end(): rm.end() + 150]):
                    found = v * mult
                    break
            if found:
                break
        if found is None:
            # 兜底：收入段（"Revenues:"/"REVENUE:" 后到费用标签前）末行 = 合计
            start = None
            for label in (r"[Rr]evenue[s]?:", r"REVENUE:"):
                lm = re.search(label, seg)
                if lm:
                    start = lm.end()
                    break
            if start is not None:
                tail = seg[start: start + 1200]
                end = _EXPENSE_START_RE.search(tail)
                if end:
                    tail = tail[: end.start()]
                nums = [float(n.replace(",", "")) for n in _NUM_RUN_RE.findall(tail)]
                nums = [n for n in nums if n > 0 and not _yearlike(n)]
                if len(nums) >= 3:
                    found = nums[-3] * mult
                elif nums:
                    found = nums[0] * mult
        if found and (best is None or found > best):
            best = found
    return round(best, 1) if best else None


def _extract_fiscal_year(text):
    """损益表头年份："Years Ended December 31, 2025" → "2025"。"""
    for m in _IS_HDR_RE.finditer(text):
        seg = text[m.start(): m.start() + 3000]
        fym = _FY_RE.search(seg)
        if fym:
            return fym.group(1)
    return None


def _extract_dpu(text):
    """每股股息：季度 ×4 > 年度 > dividends declared per share。"""
    m = _DPU_QUARTERLY_RE.search(text)
    if m:
        return round(float(m.group(1)) * 4, 4)
    m = _DPU_ANNUAL_RE.search(text)
    if m:
        return round(float(m.group(1)), 4)
    m = _DPU_DECLARED_RE.search(text)
    if m:
        return round(float(m.group(1)), 4)
    return None


def _extract_noi(text):
    """净营运收入（NOI，MD&A 表行，$000 → ×0.1）。找不到 → None。

    取所有 "Net operating income $ X" 中出现次数最多且最大表值
    （规避叙述 "NOI of $1.98 billion" 与 per-sq-ft 小值——取最大值 + 排除
    "(cash basis)"/"(loss)" 与小值）。
    """
    candidates = []
    for m in _NOI_RE.finditer(text):
        head = text[max(0, m.start() - 60): m.start()]
        v = float(m.group(1).replace(",", ""))
        if v < 1000:
            continue
        if re.search(r"cash\s+basis|\(loss\)|per\s+(?:sq|square)|NOI\s+per", head + text[m.start():m.end()], re.IGNORECASE):
            continue
        candidates.append(v)
    if not candidates:
        return None
    return round(max(candidates) * 0.1, 1)


def _extract_ffo(text):
    """FFO（attributable to common stockholders 行，$000 → ×0.1）。找不到 → None。

    取最大值（表行总额，规避 per-share 小值如 "$2.68"）。
    """
    candidates = []
    for m in _FFO_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if v >= 1000:
            candidates.append(v)
    if not candidates:
        return None
    return round(max(candidates) * 0.1, 1)


def parse_us_10k(html):
    """解析美国 10-K HTML，字段缺失 → None。"""
    text = strip_html(html)
    result = {
        "fiscal_year": _extract_fiscal_year(text),
        "period": "annual",
        "currency": "USD",
        "revenue_wan": _extract_revenue(text),
        "noi_wan": _extract_noi(text),
        "ffo_wan": _extract_ffo(text),
        "dpu_usd": _extract_dpu(text),
        "occupancy": None,
    }
    return result
