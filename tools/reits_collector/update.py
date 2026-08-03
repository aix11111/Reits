"""增量数据更新管线。

流程：读取模板月度/季度数据 → 逐基金（14 只 REIT）按市场拉公告
（深市 180xxx 走 cninfo，沪市 508xxx 走 sse）→ 按标题过滤
（月度含「运营数据」，季度含「季度报告」且不含「提示性」）→ 下载
PDF 到临时目录（已存在跳过）→ 解析 → 跳过已存在 (code, period) →
新行追加回模板对应 Sheet（period 升序 + code）。

单只基金失败只记录到 errors，不影响其余基金。
"""

import argparse
import numbers
import shutil
import tempfile
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from src import data_loader
from tools.reits_collector import cninfo, parser_generic, parser_quarterly, sse

FUND_CODES = [
    "180201",
    "180202",
    "180203",
    "508001",
    "508018",
    "508008",
    "508066",
    "508009",
    "508007",
    "508033",
    "508086",
    "508069",
    "508036",
    "508020",
]

MONTHLY_SOURCE = "月度运营公告（自动采集）"
QUARTERLY_SOURCE = "季度报告（自动采集）"
CNINFO_PDF_BASE = "https://static.cninfo.com.cn/"
DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "REITsMonitor_数据模板_v1.xlsx"
)

# PDF 下载临时目录：由 main() 创建并在结束后清理；测试中由测试替身替换。
PDF_DIR = None


def _period_date_from(period: str, kind: str) -> str:
    """最新报告期 → 查询起始日。

    月度 YYYY-MM → 次月 1 日；季度 YYYYQq → 下一季度首日。
    """
    if kind == "monthly":
        year, month = period.split("-")
        month = int(month)
        if month == 12:
            return f"{int(year) + 1}-01-01"
        return f"{year}-{month + 1:02d}-01"
    year, quarter = period[:4], int(period[5])
    month = quarter * 3 + 1
    if month > 12:
        return f"{int(year) + 1}-01-01"
    return f"{year}-{month:02d}-01"


def _date_from(code: str, last_period: dict, kind: str) -> str:
    """逐基金查询起始日：无数据从 2023-01-01 起；否则从该基金最新报告期之后起。"""
    last = last_period.get(code)
    if last is None:
        return "2023-01-01"
    return _period_date_from(last, kind)


def _list_for(code: str, date_from: str, date_to: str) -> list:
    """深市走 cninfo（先检索 orgId），沪市走 sse。"""
    if code.startswith("180"):
        org_id = cninfo.search_org_id(code)
        return cninfo.list_announcements(code, org_id, date_from, date_to)
    return sse.list_announcements(code, date_from, date_to)


def _download(url_path: str, dest: Path, code: str) -> None:
    """按市场拼接完整 URL 并下载；cninfo 用静态域名前缀，sse 由接口补全。"""
    if code.startswith("180"):
        cninfo.download_pdf(CNINFO_PDF_BASE + url_path, dest)
    else:
        sse.download_pdf(url_path, dest)


def _announcement_rows(df, kind, errors, title_filter, parse_fn, source):
    """通用抓取管线：逐基金拉公告→过滤→下载→解析→去重→组装新行。"""
    if errors is None:
        errors = []
    existing = set()
    code_to_name = {}
    last_period = {}
    for _, record in df.iterrows():
        code = str(record["code"])
        period = str(record["period"])
        existing.add((code, period))
        code_to_name[code] = str(record["name"])
        if period > last_period.get(code, ""):
            last_period[code] = period
    date_to = date.today().isoformat()

    rows = []
    for code in FUND_CODES:
        try:
            announcements = _list_for(code, _date_from(code, last_period, kind), date_to)
        except Exception as exc:
            errors.append(f"{code}：{exc}")
            continue
        for item in announcements:
            try:
                title = item.get("announcementTitle") or item.get("title") or ""
                if not title_filter(title):
                    continue
                url_path = item.get("adjunctUrl") or item.get("url") or ""
                if not url_path:
                    continue
                dest = PDF_DIR / Path(url_path).name
                if not dest.exists():
                    _download(url_path, dest, code)
                parsed = parse_fn(dest)
                period = parsed.get("period")
                if period is None or (code, period) in existing:
                    continue
                rows.append(
                    dict(
                        parsed,
                        code=code,
                        name=code_to_name.get(code, code),
                        source=source,
                    )
                )
                existing.add((code, period))
            except Exception as exc:
                errors.append(f"{code}：{exc}")
    return rows


def fetch_new_monthly(monthly_df, errors=None):
    """抓取月度运营公告，返回新行 dict 列表（含 code/name/period/source）。"""
    return _announcement_rows(
        monthly_df,
        "monthly",
        errors,
        title_filter=lambda title: "运营数据" in title,
        parse_fn=parser_generic.parse_pdf,
        source=MONTHLY_SOURCE,
    )


def fetch_new_quarterly(quarterly_df, errors=None):
    """抓取季度报告，返回新行 dict 列表（含 code/name/period/source）。"""
    return _announcement_rows(
        quarterly_df,
        "quarterly",
        errors,
        title_filter=lambda title: "季度报告" in title and "提示性" not in title,
        parse_fn=parser_quarterly.parse_quarterly_report,
        source=QUARTERLY_SOURCE,
    )


def _to_native(value):
    """DataFrame 取值 → openpyxl 可写类型；NaN → None。"""
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    return value


def _monthly_row_values(row):
    return [
        row.get("period"),
        row.get("code"),
        row.get("name"),
        row.get("toll_revenue_wan"),
        row.get("daily_traffic"),
        row.get("toll_revenue_yoy", row.get("revenue_yoy")),
        row.get("traffic_yoy"),
        row.get("source") or MONTHLY_SOURCE,
    ]


def _quarterly_row_values(row):
    return [
        row.get("period"),
        row.get("code"),
        row.get("name"),
        row.get("total_revenue_wan", row.get("revenue_wan")),
        row.get("total_cost_wan"),
        row.get("net_profit_wan"),
        row.get("distributable_wan"),
        row.get("ebitda_wan"),
        row.get("nav_wan"),
        row.get("source") or QUARTERLY_SOURCE,
    ]


def _rewrite_sheet(wb, sheet_name, old_df, new_rows, row_values_fn):
    """删掉数据行（行 2~max_row），重写 旧+新 合并行，period 升序 + code。"""
    ws = wb[sheet_name]
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    all_rows = []
    for _, record in old_df.iterrows():
        all_rows.append(
            row_values_fn({col: _to_native(record[col]) for col in old_df.columns})
        )
    for record in new_rows:
        all_rows.append(row_values_fn({k: _to_native(v) for k, v in record.items()}))
    all_rows.sort(key=lambda values: (str(values[0]), str(values[1])))
    for values in all_rows:
        ws.append(values)


def update_template(template_path):
    """读取模板 → 抓取增量 → 重写月度/季度 Sheet，返回摘要 dict。"""
    errors = []
    monthly_df = data_loader.load_monthly(template_path)
    quarterly_df = data_loader.load_quarterly(template_path)
    monthly_new = fetch_new_monthly(monthly_df, errors=errors)
    quarterly_new = fetch_new_quarterly(quarterly_df, errors=errors)

    wb = load_workbook(template_path)
    _rewrite_sheet(wb, "月度数据", monthly_df, monthly_new, _monthly_row_values)
    _rewrite_sheet(wb, "季度数据", quarterly_df, quarterly_new, _quarterly_row_values)
    wb.save(template_path)

    return {
        "monthly_added": len(monthly_new),
        "quarterly_added": len(quarterly_new),
        "errors": errors,
    }


def main(argv=None):
    """CLI：增量更新模板并打印摘要；PDF 临时目录用完清理。"""
    parser = argparse.ArgumentParser(description="增量更新 REITs 模板 Excel")
    parser.add_argument(
        "template",
        nargs="?",
        default=str(DEFAULT_TEMPLATE),
        help="模板 xlsx 路径（默认 data/REITsMonitor_数据模板_v1.xlsx）",
    )
    args = parser.parse_args(argv)

    global PDF_DIR
    PDF_DIR = Path(tempfile.mkdtemp(prefix="reits_pdf_"))
    try:
        summary = update_template(args.template)
    finally:
        shutil.rmtree(PDF_DIR, ignore_errors=True)

    print(
        f"月度新增 {summary['monthly_added']} 行，"
        f"季度新增 {summary['quarterly_added']} 行"
    )
    for err in summary["errors"]:
        print(f"  [错误] {err}")
    return summary


if __name__ == "__main__":
    main()
