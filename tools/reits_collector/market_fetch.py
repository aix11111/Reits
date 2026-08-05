"""全市场 REITs 季度核心财务采集（M2 数据层）。

逐基金（market_funds.json 全部基金）拉取季度报告公告（2021-01-01 至今，
标题过滤「季度报告」且不含「提示性」「摘要」）→ 下载 PDF 到
data/_cache/quarterly_market/（已存在跳过）→ parser_quarterly 解析 →
跳过已存在 (code, period)（读 data/market_quarterly.json 现有）→ 新行
追加并写回 {"quarters": [...]}（period 升序）。

沪市（508xxx）列表失败 time.sleep(90) 重试 3 次，沪市基金间 15s 间隔；
深市（180xxx）走 cninfo（先检索 orgId）。单只基金失败只记录到 errors，
不影响其余基金。
"""

import json
import re
import time
from datetime import date
from pathlib import Path

from tools.reits_collector import (
    cninfo,
    parser_annual,
    parser_ops_energy,
    parser_ops_rental,
    parser_quarterly,
    sse,
)

ROW_KEYS = (
    "code",
    "period",
    "revenue_wan",
    "net_profit_wan",
    "distributable_wan",
    "unit_distributable",
    "ebitda_wan",
)

CNINFO_PDF_BASE = "https://static.cninfo.com.cn/"

# 数据文件与 PDF 缓存目录：测试中由测试替身替换。
MARKET_QUARTERLY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "market_quarterly.json"
)
CACHE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "_cache" / "quarterly_market"
)
MARKET_SHARES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "market_shares.json"
)
MARKET_COMPLETION_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "market_completion.json"
)
ANNUAL_CACHE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "_cache" / "annual_market"
)

COMPLETION_ROW_KEYS = (
    "year",
    "predicted_wan",
    "actual_wan",
    "completion_pct",
    "nav_unit_price",
    "nav_wan",
)

# 租赁类运营指标（Task 5）：仅有出租率类指标的资产类型
RENTAL_ASSET_TYPES = {"产业园", "保障房", "消费", "仓储物流"}

RENTAL_OPS_ROW_KEYS = (
    "code",
    "period",
    "occupancy_pct",
    "avg_rent_yuan",
    "collection_pct",
    "remaining_lease_days",
    "rent_unit",
)

MARKET_OPS_RENTAL_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "market_ops_rental.json"
)

# 能源类运营指标（Phase 6）：仅有发电量类指标的资产类型
ENERGY_ASSET_TYPES = {"能源"}

ENERGY_OPS_ROW_KEYS = (
    "code",
    "period",
    "generation_wan_kwh",
    "utilization_hours",
    "grid_wan_kwh",
    "electricity_revenue_wan",
    "price_yuan_kwh",
    "ops_until_year",
)

MARKET_OPS_ENERGY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "market_ops_energy.json"
)

REPORT_FUND_NAME_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z]+?)(?:封闭式基础设施证券投资基金)"
)
NAME_CORE_SUFFIX_RE = re.compile(r"(REITs?|基础设施|证券投资基金|基金)$")
CODE_PREFIX_RE = re.compile(r"^(508|180)\d{3}")

# 报告标题基金全名 → market_funds 简称的最长公共子序列匹配下限：
# 实测真实季报全名与简称的相似度 ≥ 0.5，低于 0.4 视为无法匹配。
MATCH_RATIO_THRESHOLD = 0.4


def _quarterly_title_filter(title: str) -> bool:
    """季度报告标题过滤：含「季度报告」，排除「提示性」「摘要」。"""
    return (
        "季度报告" in title
        and "提示性" not in title
        and "摘要" not in title
    )


def _sse_list_with_retry(code, date_from, date_to, attempts=3, delay=90):
    """沪市列表失败 time.sleep(delay) 重试 attempts 次（限流防护）；
    仍失败抛最后一次异常。"""
    last_exc = None
    for attempt in range(attempts):
        try:
            return sse.list_announcements(code, date_from, date_to)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last_exc


def _list_for(code: str, date_from: str, date_to: str) -> list:
    """深市走 cninfo（先检索 orgId），沪市走 sse。"""
    if code.startswith("180"):
        org_id = cninfo.search_org_id(code)
        return cninfo.list_announcements(code, org_id, date_from, date_to)
    return _sse_list_with_retry(code, date_from, date_to)


def _download(url_path: str, dest: Path, code: str) -> None:
    """按市场拼接完整 URL 并下载；cninfo 用静态域名前缀，sse 由接口补全。"""
    if code.startswith("180"):
        cninfo.download_pdf(CNINFO_PDF_BASE + url_path, dest)
    else:
        sse.download_pdf(url_path, dest)


def _load_existing_quarters() -> list:
    """读 data/market_quarterly.json 现有 quarters；文件缺失/损坏按空处理。"""
    try:
        data = json.loads(MARKET_QUARTERLY_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    quarters = data.get("quarters") if isinstance(data, dict) else None
    return quarters if isinstance(quarters, list) else []


def _write_quarters(quarters: list) -> None:
    """合并后的全部 quarter 行写回 market_quarterly.json，period 升序 + code。"""
    quarters = sorted(
        quarters, key=lambda q: (str(q.get("period") or ""), str(q.get("code") or ""))
    )
    data = {"quarters": quarters}
    MARKET_QUARTERLY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def fetch_market_quarterly(market_funds: list[dict], errors=None) -> list[dict]:
    """逐基金抓取全市场季度核心财务，返回新行 dict 列表并写回。

    market_funds：data/market_funds.json 的 funds 列表（含 code/exchange）。
    行字段：code/period/revenue_wan/net_profit_wan/distributable_wan/
    unit_distributable/ebitda_wan（缺失为 None）。已存在 (code, period)
    整条跳过（不下载不解析）；已存在 PDF 跳过下载但仍解析。
    """
    if errors is None:
        errors = []
    existing = _load_existing_quarters()
    existing_pairs = {(str(q.get("code")), str(q.get("period"))) for q in existing}
    date_from = "2021-01-01"
    date_to = date.today().isoformat()

    rows = []
    for idx, fund in enumerate(market_funds):
        code = str(fund.get("code") or "").strip()
        if not code:
            errors.append("基金代码缺失")
            continue
        is_sh = not code.startswith("180")
        try:
            announcements = _list_for(code, date_from, date_to)
        except Exception as exc:
            errors.append(f"{code}：{exc}")
            continue
        if is_sh and idx != len(market_funds) - 1:
            time.sleep(15)
        for item in announcements:
            try:
                title = item.get("announcementTitle") or item.get("title") or ""
                if not _quarterly_title_filter(title):
                    continue
                url_path = item.get("adjunctUrl") or item.get("url") or ""
                if not url_path:
                    continue
                period_hint = parser_quarterly._parse_period(title)
                if period_hint and (code, period_hint) in existing_pairs:
                    continue
                dest = CACHE_DIR / Path(url_path).name
                if not dest.exists():
                    _download(url_path, dest, code)
                parsed = parser_quarterly.parse_quarterly_report(dest)
                period = parsed.get("period")
                if period is None or (code, str(period)) in existing_pairs:
                    continue
                row = {"code": code}
                for key in ROW_KEYS:
                    if key != "code":
                        row[key] = parsed.get(key)
                rows.append(row)
                existing_pairs.add((code, str(period)))
            except Exception as exc:
                errors.append(f"{code}：{exc}")

    if rows:
        _write_quarters(list(existing) + rows)
    return rows


def _fund_name_core(name: str) -> str:
    """基金简称 → 匹配核心：去掉 REIT/基础设施/基金 等后缀。

    如「中航首钢绿能REIT」→「中航首钢绿能」、「招商基金蛇口租赁住房REIT」
    →「招商基金蛇口租赁住房」。
    """
    return NAME_CORE_SUFFIX_RE.sub("", name)


def _lcs_ratio(a: str, b: str) -> float:
    """最长公共子序列长度 / 较长字符串长度（0.0~1.0）。"""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0.0
    dp = [0] * (n + 1)
    for i in range(1, m + 1):
        prev = 0
        for j in range(1, n + 1):
            tmp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j - 1])
            prev = tmp
    return dp[n] / max(m, n)


def _match_fund_code(full_name: str, funds: list[dict]) -> str | None:
    """报告标题中的基金全名 → market_funds 中唯一最相似的 code。

    基金改名后报告仍沿用旧全名（如「中航首钢生物质」→ 简称「中航首钢绿能
    REIT」），用最长公共子序列相似度匹配。要求最高分唯一且 ≥ 阈值，否则
    返回 None（避免误匹配）。
    """
    best_score, best_code = -1.0, None
    runner_up = -1.0
    for fund in funds:
        core = _fund_name_core(str(fund.get("name") or ""))
        if not core:
            continue
        score = _lcs_ratio(full_name, core)
        if score > best_score:
            runner_up, best_score, best_code = best_score, score, fund.get("code")
        elif score > runner_up:
            runner_up = score
    if best_code is None or best_score < MATCH_RATIO_THRESHOLD:
        return None
    if best_score - runner_up < 1e-4:
        return None
    return str(best_code)


def _report_fund_name(text: str) -> str | None:
    """从报告文本标题提取基金全名（「…封闭式基础设施证券投资基金」之前的部分）。"""
    flat = re.sub(r"\s+", "", text)
    match = REPORT_FUND_NAME_RE.search(flat)
    if match is None:
        return None
    return match.group(1)


def _code_from_filename(filename: str) -> str | None:
    """文件名以基金代码开头（沪市 sse 公告命名 508xxx_…）→ 直接取 code。"""
    match = CODE_PREFIX_RE.match(filename)
    if match is None:
        return None
    return match.group(0)


def fetch_market_shares(market_funds, errors=None) -> dict:
    """逐基金从季度报告 PDF 缓存取最新季报的「报告期末基金份额总额」。

    遍历 CACHE_DIR（季度报告缓存）每个 PDF：沪市文件名以代码开头直接取 code；
    深市数字文件名按报告标题基金全名与 market_funds 简称唯一匹配 code。
    每基金取报告期最新的一条份额，写回 data/market_shares.json
    {"shares": {code: 份额}}，返回 {"shares": ..., "missing": [...]}。
    无季报缓存的基金（如新上市）如实进 missing，不编造。
    """
    if errors is None:
        errors = []
    # 无代码前缀的文件名来自 cninfo 公告（adjunctUrl 数字文件名），
    # 仅深市（180xxx）基金走 cninfo → 名称匹配限定深市基金，避免与
    # 沪市基金同名候选并列（如「华夏华润商业资产」vs 508077 华润有巢）。
    szse_funds = [
        f for f in market_funds if str(f.get("code") or "").startswith("180")
    ]
    best = {}
    pdf_paths = [
        p for p in Path(CACHE_DIR).iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    for path in sorted(pdf_paths, key=lambda p: p.name):
        try:
            text = parser_annual.extract_text(path)
        except Exception as exc:
            errors.append(f"{path.name}：{exc}")
            continue
        period = parser_quarterly._parse_period(text)
        code = _code_from_filename(path.name)
        if code is None:
            full_name = _report_fund_name(text)
            if full_name is None:
                errors.append(f"{path.name}：无法识别基金全名")
                continue
            code = _match_fund_code(full_name, szse_funds)
            if code is None:
                errors.append(f"{path.name}：无法唯一匹配基金代码")
                continue
        shares = parser_annual._extract_fund_shares(text)
        if shares is None:
            continue
        current = best.get(code)
        if current is None or (period or "") > (current[0] or ""):
            best[code] = (period, shares)

    shares_map = {}
    missing = []
    for fund in market_funds:
        code = str(fund.get("code") or "").strip()
        if code in best:
            shares_map[code] = best[code][1]
        else:
            missing.append(code)

    MARKET_SHARES_PATH.write_text(
        json.dumps({"shares": shares_map}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return {"shares": shares_map, "missing": missing}


def fetch_market_ops_rental(market_funds, errors=None) -> list[dict]:
    """逐基金从季度报告 PDF 缓存取租赁类运营指标（出租率等）。

    仅处理 market_funds 中产业园/保障房/消费/仓储物流类基金：遍历 CACHE_DIR
    季度报告缓存每个 PDF，沪市文件名以代码开头直接取 code，深市数字文件名
    按报告标题基金全名与深市基金简称唯一匹配 code；非租赁类或解析为 None
    （无出租率字段）的行跳过。写回 data/market_ops_rental.json
    {"ops": [code/period/occupancy_pct/avg_rent_yuan/collection_pct/
    remaining_lease_days]}（保留全部期，(code, period) 去重，升序），返回全部行。
    """
    if errors is None:
        errors = []
    rental_codes = {
        str(f.get("code") or "").strip()
        for f in market_funds
        if str(f.get("asset_type") or "") in RENTAL_ASSET_TYPES
    }
    # 数字文件名来自 cninfo 公告（adjunctUrl），仅深市（180xxx）走名称匹配
    szse_funds = [
        f for f in market_funds if str(f.get("code") or "").startswith("180")
    ]
    rows = []
    seen_pairs = set()
    pdf_paths = [
        p for p in Path(CACHE_DIR).iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    for path in sorted(pdf_paths, key=lambda p: p.name):
        code = _code_from_filename(path.name)
        text = None
        if code is None:
            try:
                text = parser_annual.extract_text(path)
            except Exception as exc:
                errors.append(f"{path.name}：{exc}")
                continue
            full_name = _report_fund_name(text)
            if full_name is None:
                errors.append(f"{path.name}：无法识别基金全名")
                continue
            code = _match_fund_code(full_name, szse_funds)
            if code is None:
                errors.append(f"{path.name}：无法唯一匹配基金代码")
                continue
        if code not in rental_codes:
            continue
        if text is None:
            try:
                text = parser_annual.extract_text(path)
            except Exception as exc:
                errors.append(f"{path.name}：{exc}")
                continue
        period = parser_quarterly._parse_period(text)
        if period is None:
            continue
        pair = (code, period)
        if pair in seen_pairs:
            continue
        parsed = parser_ops_rental.parse_rental_ops_text(text)
        if parsed is None:
            continue
        seen_pairs.add(pair)
        rows.append({"code": code, "period": period, **parsed})

    rows.sort(key=lambda r: (str(r["code"]), str(r["period"])))
    MARKET_OPS_RENTAL_PATH.write_text(
        json.dumps({"ops": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return rows


def fetch_market_ops_energy(market_funds, errors=None) -> list[dict]:
    """逐基金从季度报告 PDF 缓存取能源类运营指标（发电量等）。

    仅处理 market_funds 中能源类基金：遍历 CACHE_DIR 季度报告缓存每个 PDF，
    沪市文件名以代码开头直接取 code，深市数字文件名按报告标题基金全名与
    深市基金简称唯一匹配 code；非能源类或解析为 None（无发电量字段）的行
    跳过。写回 data/market_ops_energy.json
    {"ops": [code/period/generation_wan_kwh/utilization_hours/grid_wan_kwh/
    electricity_revenue_wan/price_yuan_kwh/ops_until_year]}（保留全部期，
    (code, period) 去重，升序），返回全部行。
    """
    if errors is None:
        errors = []
    energy_codes = {
        str(f.get("code") or "").strip()
        for f in market_funds
        if str(f.get("asset_type") or "") in ENERGY_ASSET_TYPES
    }
    # 数字文件名来自 cninfo 公告（adjunctUrl），仅深市（180xxx）走名称匹配
    szse_funds = [
        f for f in market_funds if str(f.get("code") or "").startswith("180")
    ]
    rows = []
    seen_pairs = set()
    pdf_paths = [
        p for p in Path(CACHE_DIR).iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    for path in sorted(pdf_paths, key=lambda p: p.name):
        code = _code_from_filename(path.name)
        text = None
        if code is None:
            try:
                text = parser_annual.extract_text(path)
            except Exception as exc:
                errors.append(f"{path.name}：{exc}")
                continue
            full_name = _report_fund_name(text)
            if full_name is None:
                errors.append(f"{path.name}：无法识别基金全名")
                continue
            code = _match_fund_code(full_name, szse_funds)
            if code is None:
                errors.append(f"{path.name}：无法唯一匹配基金代码")
                continue
        if code not in energy_codes:
            continue
        if text is None:
            try:
                text = parser_annual.extract_text(path)
            except Exception as exc:
                errors.append(f"{path.name}：{exc}")
                continue
        period = parser_quarterly._parse_period(text)
        if period is None:
            continue
        pair = (code, period)
        if pair in seen_pairs:
            continue
        parsed = parser_ops_energy.parse_energy_ops_text(text)
        if parsed is None:
            continue
        seen_pairs.add(pair)
        rows.append({"code": code, "period": period, **parsed})

    rows.sort(key=lambda r: (str(r["code"]), str(r["period"])))
    MARKET_OPS_ENERGY_PATH.write_text(
        json.dumps({"ops": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return rows


def _annual_title_filter(title: str) -> bool:
    """年报标题过滤：含「年度报告」，排除「摘要」「提示性」。"""
    return (
        "年度报告" in title
        and "摘要" not in title
        and "提示性" not in title
    )


def _annual_year_hint(title: str) -> int | None:
    """从公告标题「{YYYY} 年年度报告」提取报告年份（跳过下载/解析前判断用）。"""
    match = re.search(r"(\d{4})\s*年\s*年度报告", title)
    if match is None:
        return None
    return int(match.group(1))


def _load_existing_completion() -> list:
    """读 data/market_completion.json 现有 completion 行；缺失/损坏按空处理。"""
    try:
        data = json.loads(MARKET_COMPLETION_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    completion = data.get("completion") if isinstance(data, dict) else None
    return completion if isinstance(completion, list) else []


def _write_completion(completion: list) -> None:
    """合并后的全部完成度行写回 market_completion.json，year 升序 + code。"""
    completion = sorted(
        completion,
        key=lambda r: (str(int(r.get("year") or -1)), str(r.get("code") or "")),
    )
    MARKET_COMPLETION_PATH.write_text(
        json.dumps({"completion": completion}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def fetch_market_annual(market_funds, errors=None) -> list[dict]:
    """逐基金抓取全市场年报净值与可供分配完成度，返回新行并写回。

    逐基金拉年度报告公告（标题含「年度报告」且不含「摘要」「提示性」）→
    PDF 缓存 data/_cache/annual_market/（已存在跳过下载但仍解析）→
    parser_annual.parse_annual_completion → 行 {code, name, year,
    predicted_wan, actual_wan, completion_pct, nav_unit_price, nav_wan}。
    已存在 (code, year) 整条跳过；沪市 15s 基金间间隔 + 列表失败 90s×3 重试；
    深市走 cninfo。单基金失败只记录 errors，不影响其余。
    """
    if errors is None:
        errors = []
    existing = _load_existing_completion()
    existing_pairs = {
        (str(r.get("code")), str(int(r["year"])))
        for r in existing
        if r.get("year") is not None
    }
    names = {
        str(fund.get("code") or ""): str(fund.get("name") or "")
        for fund in market_funds
    }
    date_from = "2021-01-01"
    date_to = date.today().isoformat()

    rows = []
    for idx, fund in enumerate(market_funds):
        code = str(fund.get("code") or "").strip()
        if not code:
            errors.append("基金代码缺失")
            continue
        is_sh = not code.startswith("180")
        try:
            announcements = _list_for(code, date_from, date_to)
        except Exception as exc:
            errors.append(f"{code}：{exc}")
            continue
        if is_sh and idx != len(market_funds) - 1:
            time.sleep(15)
        for item in announcements:
            try:
                title = item.get("announcementTitle") or item.get("title") or ""
                if not _annual_title_filter(title):
                    continue
                year_hint = _annual_year_hint(title)
                if year_hint is not None and (code, str(year_hint)) in existing_pairs:
                    continue
                url_path = item.get("adjunctUrl") or item.get("url") or ""
                if not url_path:
                    continue
                dest = ANNUAL_CACHE_DIR / Path(url_path).name
                if not dest.exists():
                    _download(url_path, dest, code)
                parsed = parser_annual.parse_annual_completion(dest)
                year = parsed.get("year")
                if year is None or (code, str(int(year))) in existing_pairs:
                    continue
                row = {"code": code, "name": names.get(code, code)}
                for key in COMPLETION_ROW_KEYS:
                    row[key] = parsed.get(key)
                rows.append(row)
                existing_pairs.add((code, str(int(year))))
            except Exception as exc:
                errors.append(f"{code}：{exc}")

    if rows:
        _write_completion(list(existing) + rows)
    return rows
