"""tools.reits_collector.update 模块（增量数据更新管线）的单元测试。

通过 monkeypatch 替换 cninfo / sse / parser_generic / parser_quarterly
的列表、下载与解析函数，全程不发起真实网络请求。覆盖：
- 已存在 period 跳过、新 period 追加（月度 + 季度）
- 深市走 cninfo、沪市走 sse 的分支路由
- 单基金网络失败 → 收集到 errors 不崩溃
- update_template 写回模板后 load 验证行数增加
- 空增量（无新公告）→ 摘要全 0
"""

import pandas as pd
import pytest
from openpyxl import Workbook

from src import data_loader
from tools.reits_collector import cninfo, parser_generic, parser_quarterly, sse, update

MONTHLY_NUMERIC_KEYS = [
    "daily_traffic",
    "traffic_mom",
    "traffic_yoy",
    "traffic_cum",
    "traffic_cum_yoy",
    "toll_revenue_wan",
    "revenue_mom",
    "revenue_yoy",
    "revenue_cum",
    "revenue_cum_yoy",
]

SH_CODES = [
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
SZ_CODES = ["180201", "180202", "180203"]


def _monthly_parse_result(period):
    """构造 parse_pdf 风格的解析结果：period + project_name + 10 个数值字段。"""
    result = {"period": period, "project_name": "某高速"}
    for i, key in enumerate(MONTHLY_NUMERIC_KEYS):
        result[key] = 1000 + i
    return result


def _monthly_df(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "period",
            "code",
            "name",
            "toll_revenue_wan",
            "daily_traffic",
            "toll_revenue_yoy",
            "traffic_yoy",
            "source",
        ],
    )


def _quarterly_df(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "period",
            "code",
            "name",
            "total_revenue_wan",
            "total_cost_wan",
            "net_profit_wan",
            "distributable_wan",
            "ebitda_wan",
            "nav_wan",
            "source",
        ],
    )


def _patch_downloads(monkeypatch, tmp_path):
    """PDF 目录指向 tmp_path；两个市场的 download_pdf 均为写假 PDF 字节。"""
    monkeypatch.setattr(update, "PDF_DIR", tmp_path)

    def fake_download(url, dest):
        dest.write_bytes(b"%PDF-fake")
        return dest

    monkeypatch.setattr(cninfo, "download_pdf", fake_download)
    monkeypatch.setattr(sse, "download_pdf", fake_download)


def _cninfo_item(title, filename):
    return {
        "announcementTitle": title,
        "adjunctUrl": f"finalpage/2026-07-15/{filename}",
        "announcementTime": 1752566400000,
    }


def _sse_item(title, filename):
    return {
        "title": title,
        "url": f"/disclosure/fund/announcement/{filename}",
        "sseDate": "2026-07-15",
    }


# ---------------------------------------------------------------------------
# fetch_new_monthly
# ---------------------------------------------------------------------------


def test_fetch_new_monthly_skips_existing_period_and_appends_new(
    monkeypatch, tmp_path
):
    """已存在 (code, period) 跳过、新 period 追加；非「运营数据」公告被过滤；
    已存在的 PDF 跳过下载但仍解析。"""
    _patch_downloads(monkeypatch, tmp_path)
    monthly_df = _monthly_df(
        [["2026-06", "180201", "平安广州广河REIT", 8000, 120000, 1.0, 2.0, "公告"]]
    )
    # 2026-07 的 PDF 已存在 → 应跳过下载
    (tmp_path / "180201_202607.pdf").write_bytes(b"%PDF-exists")

    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(sse, "list_announcements", lambda *a, **k: [])

    def fake_cninfo_list(code, org_id, date_from, date_to, page_size=100):
        if code != "180201":
            return []
        return [
            _cninfo_item("关于2026年6月主要运营数据的公告", "180201_202606.pdf"),
            _cninfo_item("关于2026年7月主要运营数据的公告", "180201_202607.pdf"),
            _cninfo_item("关于召开基金份额持有人大会的公告", "other.pdf"),
        ]

    monkeypatch.setattr(cninfo, "list_announcements", fake_cninfo_list)

    downloaded = []
    real_download = cninfo.download_pdf

    def recording_download(url, dest):
        downloaded.append(dest.name)
        return real_download(url, dest)

    monkeypatch.setattr(cninfo, "download_pdf", recording_download)

    parsed = {
        "180201_202606.pdf": _monthly_parse_result("2026-06"),
        "180201_202607.pdf": _monthly_parse_result("2026-07"),
    }
    parse_calls = []

    def fake_parse(path):
        parse_calls.append(path.name)
        return parsed[path.name]

    monkeypatch.setattr(parser_generic, "parse_pdf", fake_parse)

    rows = update.fetch_new_monthly(monthly_df)

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "180201"
    assert row["name"] == "平安广州广河REIT"
    assert row["period"] == "2026-07"
    for key in MONTHLY_NUMERIC_KEYS:
        assert key in row

    # 已存在 period 的公告仍下载解析（用于判定 period）；已存在 PDF 跳过下载；
    # 非「运营数据」公告既不下载也不解析
    assert downloaded == ["180201_202606.pdf"]
    assert sorted(parse_calls) == ["180201_202606.pdf", "180201_202607.pdf"]


def test_fetch_new_monthly_routes_sz_to_cninfo_and_sh_to_sse(
    monkeypatch, tmp_path
):
    """深市 3 只走 cninfo（含 search_org_id），沪市 11 只走 sse；
    日期范围从最新 period 次月 1 日开始。"""
    _patch_downloads(monkeypatch, tmp_path)
    monthly_df = _monthly_df(
        [["2026-06", "180201", "平安广州广河REIT", 8000, 120000, 1.0, 2.0, "公告"]]
    )

    org_calls = []
    monkeypatch.setattr(
        cninfo, "search_org_id", lambda code: org_calls.append(code) or f"org-{code}"
    )
    cninfo_calls = []
    sse_calls = []

    def fake_cninfo_list(code, org_id, date_from, date_to, page_size=100):
        cninfo_calls.append({"code": code, "from": date_from})
        return []

    def fake_sse_list(code, date_from, date_to, page_size=25):
        sse_calls.append({"code": code, "from": date_from})
        return []

    monkeypatch.setattr(cninfo, "list_announcements", fake_cninfo_list)
    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)

    rows = update.fetch_new_monthly(monthly_df)

    assert rows == []
    assert sorted(org_calls) == SZ_CODES
    assert sorted(c["code"] for c in cninfo_calls) == SZ_CODES
    assert sorted(c["code"] for c in sse_calls) == sorted(SH_CODES)
    assert all(c["from"] == "2026-07-01" for c in cninfo_calls + sse_calls)


def test_fetch_new_monthly_collects_errors_and_continues(monkeypatch, tmp_path):
    """单基金网络失败 → 错误收集到 errors，其余基金正常返回，不崩溃。"""
    _patch_downloads(monkeypatch, tmp_path)
    monthly_df = _monthly_df(
        [["2026-06", "180201", "平安广州广河REIT", 8000, 120000, 1.0, 2.0, "公告"]]
    )
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(sse, "list_announcements", lambda *a, **k: [])

    def fake_cninfo_list(code, org_id, date_from, date_to, page_size=100):
        if code == "180202":
            raise RuntimeError("网络超时")
        if code == "180201":
            return [_cninfo_item("关于2026年7月主要运营数据的公告", "180201_202607.pdf")]
        return []

    monkeypatch.setattr(cninfo, "list_announcements", fake_cninfo_list)
    monkeypatch.setattr(
        parser_generic, "parse_pdf", lambda path: _monthly_parse_result("2026-07")
    )

    errors = []
    rows = update.fetch_new_monthly(monthly_df, errors=errors)

    assert len(rows) == 1
    assert rows[0]["code"] == "180201"
    assert len(errors) == 1
    assert "180202" in errors[0]


# ---------------------------------------------------------------------------
# fetch_new_quarterly
# ---------------------------------------------------------------------------


def test_fetch_new_quarterly_filters_advisory_and_dedups(monkeypatch, tmp_path):
    """过滤「季度报告」并排除提示性公告；已存在 (code, period) 跳过；
    沪市走 sse，日期范围从最新季度末次日开始。"""
    _patch_downloads(monkeypatch, tmp_path)
    quarterly_df = _quarterly_df(
        [["2026Q2", "508001", "浙商沪杭甬REIT", 17000, None, 4000, 14000, 7000, None, "季报"]]
    )

    sse_calls = []

    def fake_sse_list(code, date_from, date_to, page_size=25):
        sse_calls.append({"code": code, "from": date_from})
        if code != "508001":
            return []
        return [
            _sse_item("浙商沪杭甬REIT 2026年第2季度报告", "q2.pdf"),
            _sse_item("浙商沪杭甬REIT 2026年第3季度报告", "q3.pdf"),
            _sse_item("关于2026年第3季度报告披露的提示性公告", "notice.pdf"),
            _sse_item("浙商沪杭甬REIT 2026年中期报告", "interim.pdf"),
        ]

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    downloaded = []
    real_download = sse.download_pdf

    def recording_download(url, dest):
        downloaded.append(dest.name)
        return real_download(url, dest)

    monkeypatch.setattr(sse, "download_pdf", recording_download)

    parsed = {
        "q2.pdf": {
            "period": "2026Q2",
            "revenue_wan": 17000.0,
            "net_profit_wan": 4000.0,
            "cash_distribution_rate": 1.2,
            "distributable_wan": 14000.0,
            "unit_distributable": 0.14,
            "ebitda_wan": 7000.0,
        },
        "q3.pdf": {
            "period": "2026Q3",
            "revenue_wan": 18000.0,
            "net_profit_wan": 4100.0,
            "cash_distribution_rate": 1.3,
            "distributable_wan": 14500.0,
            "unit_distributable": 0.145,
            "ebitda_wan": 7100.0,
        },
    }
    monkeypatch.setattr(
        parser_quarterly, "parse_quarterly_report", lambda path: parsed[path.name]
    )

    rows = update.fetch_new_quarterly(quarterly_df)

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "508001"
    assert row["name"] == "浙商沪杭甬REIT"
    assert row["period"] == "2026Q3"
    assert row["revenue_wan"] == 18000.0
    assert row["distributable_wan"] == 14500.0

    # 提示性公告与中期报告既不下载也不解析
    assert sorted(downloaded) == ["q2.pdf", "q3.pdf"]
    assert all(c["from"] == "2026-07-01" for c in sse_calls)


# ---------------------------------------------------------------------------
# update_template
# ---------------------------------------------------------------------------

STATIC_HEADERS = [
    "基金代码",
    "基金简称",
    "底层资产",
    "区域",
    "里程(km)",
    "上市日期",
    "发行规模(亿元)",
    "特许经营剩余年限\n(截至2026)",
    "资产类型",
]

MONTHLY_HEADERS = [
    "报告期",
    "基金代码",
    "基金简称",
    "通行费收入(万元)",
    "日均自然车流量(辆/日)",
    "通行费收入同比(%)",
    "车流量同比(%)",
    "数据来源/备注",
]

QUARTERLY_HEADERS = [
    "报告期",
    "基金代码",
    "基金简称",
    "营业总收入(万元)",
    "营业成本(万元)",
    "净利润(万元)",
    "可供分配金额(万元)",
    "EBITDA(万元)",
    "基金净资产-NAV(万元)",
    "数据来源/备注",
]


def _build_template(path):
    """构造最小模板：静态 2 行、月度 1 行、季度 1 行。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "静态信息"
    ws.append(STATIC_HEADERS)
    ws.append(["180201", "平安广州广河REIT", "广河高速(广州段)", "华南", 99, "2021-06-07", 91.14, 10, "高速公路"])
    ws.append(["508001", "浙商沪杭甬REIT", "杭徽高速", "华东", 123, "2021-06-07", 43.0, 5, "高速公路"])

    ws = wb.create_sheet("月度数据")
    ws.append(MONTHLY_HEADERS)
    ws.append(["2026-06", "180201", "平安广州广河REIT", 8000, 120000, 1.0, 2.0, "月度运营公告（自动采集）"])

    ws = wb.create_sheet("季度数据")
    ws.append(QUARTERLY_HEADERS)
    ws.append(["2026Q2", "508001", "浙商沪杭甬REIT", 17000, None, 4000, 14000, 7000, None, "季度报告（自动采集）"])

    wb.save(path)


def test_update_template_appends_rows_and_reloads(tmp_path, monkeypatch):
    """主入口：新增行写回对应 Sheet，load 验证行数增加、字段映射正确、
    旧行与表头保留，摘要结构正确。"""
    path = tmp_path / "tpl.xlsx"
    _build_template(path)

    new_monthly = [
        dict(
            _monthly_parse_result("2026-07"),
            code="180201",
            name="平安广州广河REIT",
        )
    ]
    new_quarterly = [
        {
            "code": "508001",
            "name": "浙商沪杭甬REIT",
            "period": "2026Q3",
            "revenue_wan": 18000.0,
            "net_profit_wan": 4100.0,
            "cash_distribution_rate": 1.3,
            "distributable_wan": 14500.0,
            "unit_distributable": 0.145,
            "ebitda_wan": 7100.0,
        }
    ]
    monkeypatch.setattr(update, "fetch_new_monthly", lambda df, errors=None: new_monthly)
    monkeypatch.setattr(
        update, "fetch_new_quarterly", lambda df, errors=None: new_quarterly
    )

    summary = update.update_template(path)

    assert summary == {"monthly_added": 1, "quarterly_added": 1, "errors": []}

    monthly = data_loader.load_monthly(path)
    assert len(monthly) == 2
    row = monthly[(monthly["code"] == "180201") & (monthly["period"] == "2026-07")]
    assert len(row) == 1
    row = row.iloc[0]
    parsed = _monthly_parse_result("2026-07")
    assert row["toll_revenue_wan"] == parsed["toll_revenue_wan"]
    assert row["daily_traffic"] == parsed["daily_traffic"]
    assert row["toll_revenue_yoy"] == parsed["revenue_yoy"]
    assert row["traffic_yoy"] == parsed["traffic_yoy"]
    assert row["source"] == "月度运营公告（自动采集）"
    # 旧行保留
    assert len(monthly[monthly["period"] == "2026-06"]) == 1

    quarterly = data_loader.load_quarterly(path)
    assert len(quarterly) == 2
    qrow = quarterly[
        (quarterly["code"] == "508001") & (quarterly["period"] == "2026Q3")
    ]
    assert len(qrow) == 1
    qrow = qrow.iloc[0]
    assert qrow["total_revenue_wan"] == 18000.0
    assert qrow["net_profit_wan"] == 4100.0
    assert qrow["distributable_wan"] == 14500.0
    assert qrow["ebitda_wan"] == 7100.0
    assert qrow["source"] == "季度报告（自动采集）"


def test_update_template_empty_increment(tmp_path, monkeypatch):
    """空增量（无新公告）→ 摘要全 0，errors 为空，模板数据不变。"""
    path = tmp_path / "tpl.xlsx"
    _build_template(path)

    monkeypatch.setattr(update, "fetch_new_monthly", lambda df, errors=None: [])
    monkeypatch.setattr(update, "fetch_new_quarterly", lambda df, errors=None: [])

    summary = update.update_template(path)

    assert summary == {"monthly_added": 0, "quarterly_added": 0, "errors": []}
    assert len(data_loader.load_monthly(path)) == 1
    assert len(data_loader.load_quarterly(path)) == 1
