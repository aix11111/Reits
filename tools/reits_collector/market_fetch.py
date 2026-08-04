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
import time
from datetime import date
from pathlib import Path

from tools.reits_collector import cninfo, parser_quarterly, sse

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
