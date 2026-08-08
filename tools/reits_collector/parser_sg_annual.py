"""新加坡年报（Annual Report）财务摘要解析（S-REITs，含 3 月财年）。

多策略提取核心财务指标，缺失字段 → None 不抛错：
1. 「Selected Statement of Total Return and Distribution Data」五年摘要表
   （行标签 + 5 年数字序列，取最新列）——C38U 标准格式；
2. 通用全文扫描：行标签**前后**双向取数（A17U 数字在标签前取首个）、
   双列「FY2025 FY2024」表取第一列、财年 token 升/降序判列序；
3. 叙述式 DPU/NAV 兜底（"Distribution per Unit of 5.23 cents" 等）。

字段与标签：
- revenue_wan: Gross Revenue
- npi_wan: Net Property Income
- distributable_wan: Distributable Income
  （S$ million → ×100 万元；S$ billion → ×100000；$'000 → ×0.1）
- dpu_cents: Distribution Per Unit (¢)
- nav_per_unit: Net Asset Value Per Unit (S$)
- occupancy: Committed Occupancy {pct}%（label 前/后均可）
- fy: FY ended 31 December 2025 → "2025"；3 月财年封面「Annual Report 2024/25」→ "2024/25"
- currency: "SGD"
- period: "annual"
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
    "revenue_wan": r"Gross\s+Revenue(?!\s+by\b)",
    "npi_wan": r"Net\s+Property\s+Income",
    "distributable_wan": r"Distributable\s+Income",
    "nav_per_unit": r"Net\s+Asset\s+Value\s*(?:\(NAV\))?\s+Per\s+Unit",
    "dpu_cents": r"Distribution\s+Per\s+Unit",
}

# 财年兜底：封面「Annual Report 2025 / 2024/25 / FY2025」→ "2025"/"2024/25"
#（优先 Annual Report，其次 FY；含斜线形态保留）
_COVER_AR_FY_RE = re.compile(
    r"(?:A\s*N\s*N\s*U\s*A\s*L|Annual)\s*(?:R\s*E\s*P\s*O\s*R\s*T|Report)\s*(20\d{2}(?:/20\d{2}|/\d{2})?)",
    re.IGNORECASE,
)
_COVER_FY_TOKEN_RE = re.compile(r"FY\s*(20\d{2}(?:/20\d{2}|/\d{2})?)", re.IGNORECASE)

# 叙述式 DPU：多种措辞，逐个尝试（[^;] 允许 PDF 提取的换行）
# 1) "Distribution per Unit of 5.23 cents."（K71U 吉宝）
_DPU_OF_RE = re.compile(
    r"Distribution\s+per\s+Unit\s+of\s+([\d.]+)\s+cents", re.IGNORECASE
)
# 2) "Distribution Per Unit (DPU) for FY2025 stood at 15.29 Singapore cents"（C2PU）
_DPU_STOOD_RE = re.compile(
    r"Distribution\s+Per\s+Unit[^;]{0,50}?stood\s+at\s+([\d.]+)\s+(?:Singapore\s+)?cents",
    re.IGNORECASE,
)
# 3) "7.87 S Cents ... Distribution per Unit"（CY6U，值在 label 前）
_DPU_PRECEDING_RE = re.compile(
    r"([\d.]+)\s+S\s*Cents[^;]{0,30}?Distribution\s+per\s+Unit", re.IGNORECASE
)
# 4) "DPU rose 6.4% YoY to 11.58 cents"（含小数点点）
_DPU_TO_RE = re.compile(r"DPU[^;]{0,60}?to\s+([\d.]+)\s*cents", re.IGNORECASE)
# 5) "DPU: 5.95 cents" / "Core DPU 21.440 cents"（BUOU/9A4U）
_DPU_COLON_RE = re.compile(
    r"\bDPU\s*[:：]?\s*(?:of\s+)?([\d.]+)\s+(?:Singapore\s+)?cents", re.IGNORECASE
)
_DPU_NARRATIVE_RES = (
    _DPU_OF_RE,
    _DPU_STOOD_RE,
    _DPU_PRECEDING_RE,
    _DPU_TO_RE,
    _DPU_COLON_RE,
)


def _extract_narrative_dpu(text):
    """叙述式 DPU；跳过「since IPO/cumulative」累计口径、季度/半年 DPU。"""
    for pat in _DPU_NARRATIVE_RES:
        for m in pat.finditer(text):
            head = text[max(0, m.start() - 50): m.start()]
            tail = text[m.end(): m.end() + 40]
            if re.search(r"since\s+(?:IPO|listing)|cumulative", tail, re.IGNORECASE):
                continue
            if re.search(
                r"\b(?:Declared|Q[1-4]|quarter|interim|half[\s-]?year|1H|2H)\b",
                head + " " + tail,
                re.IGNORECASE,
            ):
                continue
            return round(float(m.group(1)), 2)
    return None


# 叙述式 NAV：「Net asset value per Unit increased 0.9% to S$2.14.」
# /「Net Asset Value (NAV) increased to S$2.56 per unit」（C2PU）
_NAV_NARRATIVE_RE = re.compile(
    r"(?:(?:Net\s+asset\s+value)|NAV)\s*(?:\(NAV\))?\s*(?:per\s+Unit)?[^;]{0,60}?(?:to|was|stood\s+at)\s+(?:US\$|S\$|€|A\$)?\s*([\d]+(?:\.\d+)?)",
    re.IGNORECASE,
)
# 出租率：label 在值前（Committed occupancy stood at 96.9%）或值在 label 前
#（96.9% 0.2 ppts YoY Committed Occupancy）。label 后至 % 之间不允许出现数字，
# 避免跨到下一个指标（Committed Occupancy Portfolio Performance S$27.4b 5.2%）。
_OCCUPANCY_AFTER_RE = re.compile(
    r"Committed\s+Occupancy[^%\d]{0,15}?([\d.]+)\s*%", re.IGNORECASE
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


# ---- 通用全文扫描（新格式：数字在标签前 / 双列 FY2025 FY2024 / 年 token 序） ----

# 财年 token：2021 / 2025/26 / 2025/2026 / 24/25 / FY2025
_YEAR_TOKEN_RE = re.compile(
    r"(?:FY\s*)?(20\d\d(?:/\d\d)?|\d\d/\d\d|20\d\d/\d{4})"
)
# 脚注（如 "1,2"、"2,3,4"）与千分位（"441,362"）区分
_FOOTNOTE_NUM_RE = re.compile(r"\d(?:,\d)+")
_THOUSANDS_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_CURRENCY_PREFIX_RE = re.compile(r"(?:S\$|A\$|RMB|SGD|\$)")
# 单位词（非括号形式，如 "S$ Million"）→ 跳过后定位数字
_UNIT_WORD_RE = re.compile(
    r"(?:S\$|A\$|\$)?\s*(?:million|billion)\b", re.IGNORECASE
)


def _year_end(year):
    """财年 token → 结束年份整数："2025"→2025、"2024/25"→2025、"2025/26"→2026。"""
    if "/" in year:
        return int(year.split("/")[-1])
    return int(year)


def _strip_noise(rest):
    """跳过标签后的噪声：(单位)、脚注、财年 token、币种前缀、冒号 → (rest, 跳过的财年)。

    用于标签后双向取数时定位「数字序列起始」，同时记录财年 token 判断列序。
    """
    years = []
    just_paren = False
    while rest:
        rest = rest.lstrip()
        if not rest:
            break
        if rest[0] == "(":
            j = rest.find(")")
            rest = rest[j + 1:] if j >= 0 else rest[1:]
            just_paren = True
            continue
        if rest[0] in ":：":
            rest = rest[1:]
            continue
        m = _UNIT_WORD_RE.match(rest)
        if m:
            rest = rest[m.end():]
            just_paren = False
            continue
        m = _YEAR_TOKEN_RE.match(rest)
        if m:
            years.append(m.group(1))
            rest = rest[m.end():]
            continue
        m = _NUM_RE.match(rest)
        if m:
            tok = m.group(0)
            if _FOOTNOTE_NUM_RE.fullmatch(tok) and not _THOUSANDS_NUM_RE.fullmatch(tok):
                rest = rest[m.end():]
                just_paren = False
                continue
            if "," not in tok and "." not in tok:
                if just_paren and len(tok) == 1:
                    rest = rest[m.end():]
                    just_paren = False
                    continue
                after = rest[m.end():].lstrip()
                if after and (after[0] == "(" or after[0].isalpha() or after[0] == "%"):
                    rest = rest[m.end():]
                    just_paren = False
                    continue
                if after and after[0].isdigit():
                    nxt = _NUM_RE.match(after)
                    if nxt and ("," in nxt.group(0) or "." in nxt.group(0)):
                        rest = rest[m.end():]
                        just_paren = False
                        continue
            break
        m = _CURRENCY_PREFIX_RE.match(rest)
        if m:
            rest = rest[m.end():]
            just_paren = False
            continue
        break
    return rest, years


def _window_year_order(text, m):
    """标签邻窗（±450 字符）内财年 token 序列 → "asc"/"desc"/None。

    丢弃孤立年份（与任何相邻年份间隔 > 3 年，如公司成立年），去除连续重复。
    """
    window = text[max(0, m.start() - 450): m.end() + 450]
    years = []
    for mt in _YEAR_TOKEN_RE.finditer(window):
        tok = mt.group(1)
        if "/" not in tok:
            y = int(tok)
            if not 1990 <= y <= 2100:
                continue
            years.append(y)
        else:
            years.append(_year_end(tok))
    kept = []
    for i, y in enumerate(years):
        if any(y2 != y and abs(y2 - y) <= 3 for j, y2 in enumerate(years) if j != i):
            kept.append(y)
    dedup = []
    for y in kept:
        if not dedup or y != dedup[-1]:
            dedup.append(y)
    if len(dedup) >= 2:
        if dedup[0] < dedup[1]:
            return "asc"
        if dedup[0] > dedup[1]:
            return "desc"
    return None


def _take_position(text, m, lead_years):
    """决定取序列哪个位置代表最新财年："first"/"last"/None。

    - 标签后紧跟财年 token：升序（2021..2025）→ 最后；降序/单 token → 第一。
    - 无领先 token：依邻窗财年序；仍无信号 → None（由 run 形状兜底）。
    """
    if lead_years:
        ends = [_year_end(y) for y in lead_years]
        if len(ends) >= 2:
            if ends[0] < ends[1]:
                return "last"
            if ends[0] > ends[1]:
                return "first"
            return None
        return "first"
    order = _window_year_order(text, m)
    if order == "desc":
        return "first"
    if order == "asc":
        return "last"
    return None


def _inconsistent(vals):
    """多值序列 max/min > 50 → 视为跨行混合（含他行数值），拒绝。"""
    lo, hi = min(vals), max(vals)
    return hi > 50 * lo if lo > 0 else hi > 50


def _row_value_at(text, m):
    """单个标签出现处的取值：先标签后、再标签前；返回最新财年值或 None。"""
    rest = text[m.end(): m.end() + 400]
    # 标签后紧跟年份括号（"Gross Revenue (2025)"）或年份 token（"Gross Revenue FY2025"）
    # → 地理/物业等明细表头，跳过（真实财务行标签后先单位括号后数字）
    if re.match(
        r"\s*(?:\(\s*(?:20)?\d{2}(?:/\d{2})?\s*\)|(?:FY\s*)?(?:20\d\d|\d\d/\d\d)\b)",
        rest,
    ):
        return None
    rest, lead_years = _strip_noise(rest)
    run = _RUN_RE.match(rest)
    if run:
        vals = [float(n.replace(",", "")) for n in _NUM_RE.findall(run.group(0))]
        if vals:
            vals = [v for v in vals if not _yearlike(v)]
            if not vals:
                return None
            if len(vals) >= 4:
                median = sorted(vals[:-1])[len(vals[:-1]) // 2]
                if abs(vals[-1]) < 0.2 * median:
                    vals = vals[:-1]
                if not vals:
                    return None
                if _inconsistent(vals):
                    return None
            if len(vals) == 4 and vals[:2] == vals[2:]:
                pos = "first"
            elif len(vals) == 3:
                hi = max(abs(v) for v in vals[:2])
                if abs(vals[2]) < 0.5 * hi or abs(vals[2]) > 2 * hi:
                    pos = "first"
                else:
                    pos = _take_position(text, m, lead_years)
                if pos is None:
                    pos = "last"
            else:
                pos = _take_position(text, m, lead_years)
                if pos is None:
                    pos = "first" if len(vals) <= 2 else "last"
            return vals[0] if pos == "first" else vals[-1]
    before = text[max(0, m.start() - 400): m.start()].rstrip()
    runs = list(re.finditer(rf"{_NUM}(?:\s+{_NUM})*", before))
    if runs and runs[-1].end() == len(before):
        bvals = [float(n.replace(",", "")) for n in _NUM_RE.findall(runs[-1].group(0))]
        if len(bvals) >= 2 and max(bvals) >= 50:
            return bvals[0]
    return None


def _row_latest_pair(text, label_re, validate=None):
    """全文扫描标签各出现处，返回 (最新财年值, 该处单位换算倍率)；无 → (None, 100)。

    validate(raw, scale) 可过滤不合常理的值（如年份当作 DPU），命中则继续找下一处。
    """
    for m in re.finditer(label_re, text, re.IGNORECASE):
        value = _row_value_at(text, m)
        if value is None:
            continue
        window = text[max(0, m.start() - 200): m.end() + 200]
        scale = _row_scale(window)
        if validate is not None and not validate(value, scale):
            continue
        return value, scale
    return None, 100


def _row_scale(window):
    """邻窗单位 → 换算倍率（million=100、billion=100000、$'000=0.1）。"""
    if re.search(r"\$\s*'\s*000|\$\s*’\s*000", window, re.IGNORECASE):
        return 0.1
    if re.search(
        r"billion|\$[\d.,]*\s*b\b|\$\s*\(?\s*b\b", window, re.IGNORECASE
    ):
        return 100000
    if re.search(
        r"million|\$[\d.,]*\s*m\b|\$\s*\(?\s*m\b", window, re.IGNORECASE
    ):
        return 100
    return 100


_MONEY_KEYS = ("revenue_wan", "npi_wan", "distributable_wan")


def _dpu_validate(value, scale):
    """DPU 合理性：0<值≤100¢/Unit，且非年份整数。"""
    if value <= 0 or value > 100:
        return False
    if value == int(value) and 1990 <= value <= 2100:
        return False
    return True


def _nav_validate(value, scale):
    """NAV 合理性：0<值≤100 S$/Unit，且非年份整数。"""
    if value <= 0 or value > 100:
        return False
    if value == int(value) and 1990 <= value <= 2100:
        return False
    return True


def _yearlike(value):
    """值是否为「年份」整数（如 2025.0），拒绝把年份当指标。"""
    return value == int(value) and 1990 <= value <= 2100


def _money_validate(value, scale):
    """金额合理性（万元口径）：0<值×倍率<S$50b；非年份整数；S$m 口径下值≥50
    （避免地理/物业表小数值，如地址门牌号）。"""
    if _yearlike(value):
        return False
    if scale == 100 and value < 50:
        return False
    scaled = value * scale
    return 0 < scaled < 5_000_000


def _extract_generic(text):
    """全文扫描各标签出现处，尽力提取最新财年值（金额 ×单位倍率）；缺失 → None。"""
    validators = {
        "revenue_wan": _money_validate,
        "npi_wan": _money_validate,
        "distributable_wan": _money_validate,
        "nav_per_unit": _nav_validate,
        "dpu_cents": _dpu_validate,
    }
    result = {}
    for key, pat in _LABEL_PATTERNS.items():
        value, scale = _row_latest_pair(text, pat, validators[key])
        if value is None:
            result[key] = None
        elif key in _MONEY_KEYS:
            result[key] = round(value * scale, 2)
        else:
            result[key] = value
    if result["nav_per_unit"] is None:
        value, _ = _row_latest_pair(text, r"NAV\s+per\s+Unit", _nav_validate)
        result["nav_per_unit"] = value
    return result


def _extract_narrative_nav(text):
    m = _NAV_NARRATIVE_RE.search(text)
    if m:
        return round(float(m.group(1)), 4)
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
    """财年：封面「Annual Report 2025 / 2024/25 / FY2025」优先（前 5 页约 30k 字符）；
    再 FY ended/as at 31 December 2025 → "2025"；兜底 FYxxxx 取最大年份。"""
    # 封面大字常为「R E P O R T 2 0 2 5」字母/数字间空格——紧凑化数字串
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    cover = text[:30000]
    m = _COVER_AR_FY_RE.search(cover)
    if m:
        return m.group(1)
    m = _COVER_FY_TOKEN_RE.search(cover)
    if m:
        return m.group(1)
    for m in _FY_RE.finditer(text):
        return m.group(2)
    matches = list(_FY_SHORT_RE.finditer(text))
    if matches:
        return str(max(int(m.group(1)) for m in matches))
    return None


def _extract_occupancy(text):
    m = _OCCUPANCY_BEFORE_RE.search(text)
    if not m:
        m = _OCCUPANCY_AFTER_RE.search(text)
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
    """纯函数：从全文文本解析新加坡年报财务摘要，字段缺失 → None。

    优先级：五年摘要表（C38U 标准格式）> 通用全文扫描（标签前后双向取数、
    双列 FY2025 FY2024、财年 token 列序）> 叙述式 DPU/NAV。
    """
    result = _empty_result()
    if not text:
        return result
    result["fy"] = _extract_fiscal_year(text)
    result["occupancy"] = _extract_occupancy(text)
    # 币种：按符号出现次数判断（US$ > S$ → USD；€ → EUR；A$ → AUD；默认 SGD）
    usd_n = len(re.findall(r"US\$", text))
    sgd_n = len(re.findall(r"(?<!U)S\$", text))
    eur_n = len(re.findall(r"€", text))
    aud_n = len(re.findall(r"A\$", text))
    if eur_n > sgd_n and eur_n > usd_n:
        result["currency"] = "EUR"
    elif aud_n > sgd_n and aud_n > usd_n:
        result["currency"] = "AUD"
    elif usd_n > sgd_n:
        result["currency"] = "USD"
    else:
        result["currency"] = "SGD"

    summary = _extract_summary_table(text)
    generic = _extract_generic(text)

    for key in ("revenue_wan", "npi_wan", "distributable_wan"):
        if summary is not None and summary.get(key) is not None:
            result[key] = summary[key]
        elif generic.get(key) is not None:
            result[key] = generic[key]

    # DPU/NAV：五年摘要表 > 通用扫描（表格值权威）> 叙述式兜底（避免叙述误引
    # 中期/总额，如 T82U 半年 DPU 3.15、M44U 上年 9.003）
    for key, narrative_fn in (
        ("dpu_cents", _extract_narrative_dpu),
        ("nav_per_unit", _extract_narrative_nav),
    ):
        if summary is not None and summary.get(key) is not None:
            result[key] = summary[key]
        elif generic.get(key) is not None:
            result[key] = generic[key]
        if result[key] is None:
            result[key] = narrative_fn(text)

    # 量级防护：表格式提取可能抓到总资产/总负债/股数等（如 UD1U 46,328 被当
    # million → 4632800 万）——超出 S-REIT 合理量级拒绝置 None
    for key in ("revenue_wan", "npi_wan", "distributable_wan"):
        if result[key] is not None and result[key] > 3_000_000:
            result[key] = None
    # NAV/Unit 合理范围：S-REIT（SGD/USD/GBP 计价）NAV 均在 0.1-8（CICT 2.14 为
    # 最大梯队；误配常见 11-31 来自每股收益/总净资产）；DPU 上限 500 美分
    if result["nav_per_unit"] is not None and not (0.1 <= result["nav_per_unit"] <= 8):
        result["nav_per_unit"] = None
    if result["dpu_cents"] is not None and result["dpu_cents"] > 500:
        result["dpu_cents"] = None
    return result


def parse_sg_annual(pdf_path):
    """解析新加坡年报 PDF：fitz 提取全文后调用 _parse_sg_annual_text。
    输出字段与 data/sg_annual.json schema 一致（fy → fiscal_year）。"""
    doc = fitz.open(str(pdf_path))
    try:
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    result = _parse_sg_annual_text(text)
    if "fy" in result:
        result["fiscal_year"] = result.pop("fy")
    return result
