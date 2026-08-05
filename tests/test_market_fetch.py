"""tools.reits_collector.market_fetch 模块（全市场季度核心财务采集）的单元测试。

通过 monkeypatch 替换 cninfo / sse / parser_quarterly 的列表、下载与解析函数，
全程不发起真实网络请求。覆盖：
- 已存在 (code, period) 跳过、新 period 追加（period 升序写回）
- 「季度报告」过滤（排除「提示性」「摘要」）、已存在 PDF 跳过下载
- 深市走 cninfo（search_org_id）、沪市走 sse 的分支路由
- 单基金列表失败 → 收集到 errors 不崩溃、其余基金正常
- 沪市列表失败 time.sleep(90) 重试 3 次、沪市基金间 15s 间隔
- 缺失字段如实为 None
"""

import json
from datetime import date
from pathlib import Path

import pytest

from tools.reits_collector import cninfo, market_fetch, parser_annual, parser_quarterly, sse

ROW_KEYS = (
    "code",
    "period",
    "revenue_wan",
    "net_profit_wan",
    "distributable_wan",
    "unit_distributable",
    "ebitda_wan",
)


def _sse_item(title, filename):
    return {
        "title": title,
        "url": f"/disclosure/fund/announcement/{filename}",
        "sseDate": "2026-07-15",
    }


def _cninfo_item(title, filename):
    return {
        "announcementTitle": title,
        "adjunctUrl": f"finalpage/2026-07-15/{filename}",
        "announcementTime": 1752566400000,
    }


def _patch_network(monkeypatch, tmp_path):
    """缓存目录指向 tmp_path/cache；下载写假 PDF 字节并记录目标文件名。"""
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    monkeypatch.setattr(market_fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(market_fetch.time, "sleep", lambda s: None)
    downloaded = []
    real_download = cninfo.download_pdf

    def recording_download(url, dest):
        downloaded.append(dest.name)
        dest.write_bytes(b"%PDF-fake")
        return dest

    monkeypatch.setattr(cninfo, "download_pdf", recording_download)
    monkeypatch.setattr(sse, "download_pdf", recording_download)
    return cache, downloaded


def _parse_for(period):
    return {
        "period": period,
        "revenue_wan": 3065.07,
        "net_profit_wan": -1164.45,
        "cash_distribution_rate": 1.14,
        "distributable_wan": 2369.54,
        "unit_distributable": 0.0247,
        "ebitda_wan": 2440.59,
    }


def test_fetch_market_quarterly_skips_existing_and_appends_new(
    monkeypatch, tmp_path
):
    """已存在 (code, period) 整条跳过（不下载不解析）；新 period 追加；
    写回 market_quarterly.json（旧行保留 + 新行，period 升序）。"""
    mq_path = tmp_path / "market_quarterly.json"
    mq_path.write_text(
        json.dumps(
            {
                "quarters": [
                    {
                        "code": "508000",
                        "period": "2026Q2",
                        "revenue_wan": 3065.07,
                        "net_profit_wan": -1164.45,
                        "distributable_wan": 2369.54,
                        "unit_distributable": 0.0247,
                        "ebitda_wan": None,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_fetch, "MARKET_QUARTERLY_PATH", mq_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        assert date_from == "2021-01-01"
        if code != "508000":
            return []
        return [
            _sse_item("华安张江产业园REIT 2026年第2季度报告", "508000_2026Q2.pdf"),
            _sse_item("华安张江产业园REIT 2026年第1季度报告", "508000_2026Q1.pdf"),
            _sse_item("华安张江产业园REIT 2026年第2季度报告披露提示性公告", "notice.pdf"),
        ]

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    parsed = {
        "508000_2026Q1.pdf": _parse_for("2026Q1"),
        "508000_2026Q2.pdf": _parse_for("2026Q2"),
    }
    parse_calls = []

    def fake_parse(path):
        parse_calls.append(path.name)
        return parsed[path.name]

    monkeypatch.setattr(parser_quarterly, "parse_quarterly_report", fake_parse)

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
    ]
    rows = market_fetch.fetch_market_quarterly(funds)

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "508000"
    assert row["period"] == "2026Q1"
    assert row["revenue_wan"] == pytest.approx(3065.07)
    assert row["net_profit_wan"] == pytest.approx(-1164.45)
    assert row["distributable_wan"] == pytest.approx(2369.54)
    assert row["unit_distributable"] == pytest.approx(0.0247)
    assert row["ebitda_wan"] == pytest.approx(2440.59)

    # 已存在 Q2 整条跳过（不下载不解析）；提示性公告被过滤
    assert downloaded == ["508000_2026Q1.pdf"]
    assert parse_calls == ["508000_2026Q1.pdf"]

    # 写回：旧行保留 + 新行，period 升序
    written = json.loads(mq_path.read_text(encoding="utf-8"))
    periods = [q["period"] for q in written["quarters"]]
    assert periods == ["2026Q1", "2026Q2"]
    assert written["quarters"][0]["code"] == "508000"


def test_fetch_market_quarterly_routes_sz_cninfo_and_sh_sse(
    monkeypatch, tmp_path
):
    """深市走 cninfo（含 search_org_id），沪市走 sse；
    已存在 PDF 跳过下载但仍解析。"""
    mq_path = tmp_path / "market_quarterly.json"
    mq_path.write_text(json.dumps({"quarters": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_QUARTERLY_PATH", mq_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    # 已存在 PDF → 跳过下载
    (cache / "180201_2026Q2.pdf").write_bytes(b"%PDF-exists")

    org_calls = []
    monkeypatch.setattr(
        cninfo, "search_org_id", lambda code: org_calls.append(code) or f"org-{code}"
    )
    cninfo_calls = []
    sse_calls = []

    def fake_cninfo_list(code, org_id, date_from, date_to, page_size=100):
        cninfo_calls.append(code)
        if code != "180201":
            return []
        return [
            _cninfo_item("平安广州广河REIT 2026年第2季度报告", "180201_2026Q2.pdf"),
            _cninfo_item("平安广州广河REIT 2026年第2季度报告摘要", "180201_2026Q2_sum.pdf"),
        ]

    def fake_sse_list(code, date_from, date_to, page_size=25):
        sse_calls.append(code)
        return []

    monkeypatch.setattr(cninfo, "list_announcements", fake_cninfo_list)
    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_quarterly,
        "parse_quarterly_report",
        lambda path: _parse_for("2026Q2"),
    )

    funds = [
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
        {"code": "508001", "name": "浙商沪杭甬REIT", "exchange": "SSE"},
    ]
    rows = market_fetch.fetch_market_quarterly(funds)

    assert org_calls == ["180201"]
    assert cninfo_calls == ["180201"]
    assert sse_calls == ["508001"]
    # 已存在 PDF 跳过下载；「摘要」公告既不下载也不解析
    assert downloaded == []
    assert len(rows) == 1
    assert rows[0]["code"] == "180201"
    assert rows[0]["period"] == "2026Q2"


def test_fetch_market_quarterly_collects_errors_and_continues(
    monkeypatch, tmp_path
):
    """单基金列表失败 → 错误收集到 errors，其余基金正常返回，不崩溃。"""
    mq_path = tmp_path / "market_quarterly.json"
    mq_path.write_text(json.dumps({"quarters": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_QUARTERLY_PATH", mq_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        if code == "508008":
            raise RuntimeError("接口限流")
        if code == "508000":
            return [_sse_item("华安张江产业园REIT 2026年第1季度报告", "508000_2026Q1.pdf")]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_quarterly,
        "parse_quarterly_report",
        lambda path: _parse_for("2026Q1"),
    )

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
        {"code": "508008", "name": "国金中国铁建REIT", "exchange": "SSE"},
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
    ]
    errors = []
    rows = market_fetch.fetch_market_quarterly(funds, errors=errors)

    assert len(rows) == 1
    assert rows[0]["code"] == "508000"
    assert len(errors) == 1
    assert "508008" in errors[0]


def test_fetch_market_quarterly_sh_retries_list_failure_and_15s_interval(
    monkeypatch, tmp_path
):
    """沪市列表失败 → time.sleep(90) 重试 3 次后成功；沪市基金间 15s 间隔。"""
    mq_path = tmp_path / "market_quarterly.json"
    mq_path.write_text(json.dumps({"quarters": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_QUARTERLY_PATH", mq_path)
    cache, _ = _patch_network(monkeypatch, tmp_path)
    sleeps = []
    monkeypatch.setattr(market_fetch.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    calls = {}

    def fake_sse_list(code, date_from, date_to, page_size=25):
        calls[code] = calls.get(code, 0) + 1
        if code == "508018":
            if calls[code] < 3:
                raise RuntimeError("接口限流")
            return [_sse_item("华夏中国交建REIT 2026年第1季度报告", "508018_2026Q1.pdf")]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_quarterly,
        "parse_quarterly_report",
        lambda path: _parse_for("2026Q1"),
    )

    funds = [
        {"code": "508001", "name": "浙商沪杭甬REIT", "exchange": "SSE"},
        {"code": "508018", "name": "华夏中国交建REIT", "exchange": "SSE"},
        {"code": "508008", "name": "国金中国铁建REIT", "exchange": "SSE"},
    ]
    rows = market_fetch.fetch_market_quarterly(funds)

    assert len(rows) == 1
    assert rows[0]["code"] == "508018"
    assert calls["508018"] == 3
    # 3 次尝试间 2 次 90s 等待；3 只沪市基金间 2 次 15s 间隔
    assert sleeps.count(90) == 2
    assert sleeps.count(15) == 2


# ---- fetch_market_shares（Task 3a：全市场份额，本地解析季度报告缓存） ----


def _quarterly_report_text(fund_name, period, shares_segment):
    """构造季度报告文本：标题含基金全名 + 报告期 + 基金概况节份额行。"""
    return (
        f"{fund_name}封闭式基础设施证券投资基金\n{period}\n\n"
        f"基金基本信息\n报告期末基金份额总额\n{shares_segment}\n基金合同存续期\n35 年\n"
    )


def _patch_shares_cache(monkeypatch, tmp_path, files):
    """CACHE_DIR 指向 tmp 目录并写入假 PDF 文件；
    extract_text 按文件名返回构造文本。"""
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    texts = {}
    for name, content in files.items():
        (cache / name).write_bytes(b"%PDF-fake")
        texts[name] = content
    monkeypatch.setattr(market_fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(
        parser_annual, "extract_text", lambda path: texts[Path(path).name]
    )
    return cache


def test_fetch_market_shares_picks_latest_period_and_matches_name(
    monkeypatch, tmp_path
):
    """沪市按文件名前缀取 code 且取最新报告期份额；深市数字文件名
    按报告标题基金全名匹配 market_funds code；无文件的基金进 missing。"""
    shares_path = tmp_path / "market_shares.json"
    monkeypatch.setattr(market_fetch, "MARKET_SHARES_PATH", shares_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "508000_2026Q1.pdf": _quarterly_report_text(
                "华安张江产业园", "2026年第1季度报告", "800,000,000.00 份"
            ),
            "508000_2026Q2.pdf": _quarterly_report_text(
                "华安张江产业园", "2026年第2季度报告", "960,326,121.00 份"
            ),
            "1234567890.PDF": _quarterly_report_text(
                "平安广州交投广河高速公路", "2026年第2季度报告", "700,000,000.00 份"
            ),
        },
    )

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT"},
        {"code": "180201", "name": "平安广州广河REIT"},
        {"code": "508030", "name": "中航中核汇能新能源REIT"},
    ]
    result = market_fetch.fetch_market_shares(funds)

    assert result["shares"]["508000"] == 960326121.0
    assert result["shares"]["180201"] == 700000000.0
    assert "508000" not in result["missing"]
    assert "180201" not in result["missing"]
    assert result["missing"] == ["508030"]

    written = json.loads(shares_path.read_text(encoding="utf-8"))
    assert written == {"shares": result["shares"]}


def test_fetch_market_shares_unit_in_label_variant(monkeypatch, tmp_path):
    """季报 label 自带「（单位：份）」且数值无「份」后缀（508006 格式）
    也能解析份额。"""
    shares_path = tmp_path / "market_shares.json"
    monkeypatch.setattr(market_fetch, "MARKET_SHARES_PATH", shares_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "508006_2026Q2.pdf": _quarterly_report_text(
                "华泰江苏交控",
                "2026年第2季度报告",
                "（单位：份）\n500,000,000.00",
            )
        },
    )

    result = market_fetch.fetch_market_shares(
        [{"code": "508006", "name": "华泰江苏交控REIT"}]
    )

    assert result["shares"]["508006"] == 500000000.0
    assert result["missing"] == []


def test_fetch_market_shares_numeric_file_matches_szse_only(monkeypatch, tmp_path):
    """数字文件名（cninfo 深市公告）名称匹配限定深市基金：
    「华夏华润商业资产」与沪市 508077 华润有巢并列时仍唯一匹配 180601。"""
    shares_path = tmp_path / "market_shares.json"
    monkeypatch.setattr(market_fetch, "MARKET_SHARES_PATH", shares_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "1211111111.PDF": _quarterly_report_text(
                "华夏华润商业资产", "2026年第2季度报告", "700,000,000.00 份"
            )
        },
    )

    errors = []
    result = market_fetch.fetch_market_shares(
        [
            {"code": "508077", "name": "华夏基金华润有巢REIT"},
            {"code": "180601", "name": "华夏华润消费REIT"},
        ],
        errors=errors,
    )

    assert result["shares"]["180601"] == 700000000.0
    assert "508077" in result["missing"]
    assert errors == []


def test_fetch_market_shares_unmatched_file_records_error(monkeypatch, tmp_path):
    """数字文件名且标题基金全名无法唯一匹配 → 记录 errors 不崩溃。"""
    shares_path = tmp_path / "market_shares.json"
    monkeypatch.setattr(market_fetch, "MARKET_SHARES_PATH", shares_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "9999999999.PDF": "某未知封闭式基础设施证券投资基金\n2026年第2季度报告\n",
        },
    )

    errors = []
    result = market_fetch.fetch_market_shares(
        [{"code": "180201", "name": "平安广州广河REIT"}], errors=errors
    )

    assert result["shares"] == {}
    assert result["missing"] == ["180201"]
    assert len(errors) == 1
    assert "9999999999.PDF" in errors[0]


# ---- fetch_market_annual（Task 3b：全市场年报净值/完成度） ----


def _annual_parse_result(year):
    return {
        "year": year,
        "predicted_wan": 60000.0,
        "actual_wan": 59000.0,
        "completion_pct": 98.33,
        "nav_unit_price": 3.4567,
        "nav_wan": 345000.0,
    }


def _patch_annual_cache(monkeypatch, tmp_path):
    """ANNUAL_CACHE_DIR 指向 tmp 子目录；下载写假 PDF 并记录目标文件名。"""
    annual_cache = tmp_path / "annual_cache"
    annual_cache.mkdir(exist_ok=True)
    monkeypatch.setattr(market_fetch, "ANNUAL_CACHE_DIR", annual_cache)
    return annual_cache


def test_fetch_market_annual_skips_existing_and_appends_new(monkeypatch, tmp_path):
    """已存在 (code, year) 整条跳过（不下载不解析）；新 year 追加；
    摘要/提示性公告过滤；写回 market_completion.json（旧行保留 + 新行）。"""
    mc_path = tmp_path / "market_completion.json"
    mc_path.write_text(
        json.dumps(
            {
                "completion": [
                    {
                        "code": "508000",
                        "name": "华安张江产业园REIT",
                        "year": 2024,
                        "predicted_wan": 60000.0,
                        "actual_wan": 59000.0,
                        "completion_pct": 98.33,
                        "nav_unit_price": 3.4,
                        "nav_wan": 340000.0,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_fetch, "MARKET_COMPLETION_PATH", mc_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    _patch_annual_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        assert date_from == "2021-01-01"
        if code != "508000":
            return []
        return [
            _sse_item("华安张江产业园REIT 2024年年度报告", "508000_2024.pdf"),
            _sse_item("华安张江产业园REIT 2025年年度报告", "508000_2025.pdf"),
            _sse_item("华安张江产业园REIT 2025年年度报告摘要", "508000_2025_sum.pdf"),
            _sse_item("关于华安张江产业园REIT 2025年年度报告的提示性公告", "508000_notice.pdf"),
        ]

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    parsed = {
        "508000_2024.pdf": _annual_parse_result(2024),
        "508000_2025.pdf": _annual_parse_result(2025),
    }
    parse_calls = []

    def fake_parse(path):
        parse_calls.append(path.name)
        return parsed[path.name]

    monkeypatch.setattr(parser_annual, "parse_annual_completion", fake_parse)

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
    ]
    rows = market_fetch.fetch_market_annual(funds)

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "508000"
    assert row["name"] == "华安张江产业园REIT"
    assert row["year"] == 2025
    assert row["predicted_wan"] == pytest.approx(60000.0)
    assert row["actual_wan"] == pytest.approx(59000.0)
    assert row["completion_pct"] == pytest.approx(98.33)
    assert row["nav_unit_price"] == 3.4567
    assert row["nav_wan"] == 345000.0

    # 已存在 2024 整条跳过；摘要/提示性公告不下载不解析
    assert downloaded == ["508000_2025.pdf"]
    assert parse_calls == ["508000_2025.pdf"]

    written = json.loads(mc_path.read_text(encoding="utf-8"))
    years = [r["year"] for r in written["completion"]]
    assert years == [2024, 2025]


def test_fetch_market_annual_parses_existing_pdf_without_download(
    monkeypatch, tmp_path
):
    """已存在 PDF 跳过下载但仍解析。"""
    mc_path = tmp_path / "market_completion.json"
    mc_path.write_text(json.dumps({"completion": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_COMPLETION_PATH", mc_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    annual_cache = _patch_annual_cache(monkeypatch, tmp_path)
    (annual_cache / "508000_2025.pdf").write_bytes(b"%PDF-exists")
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        if code != "508000":
            return []
        return [_sse_item("华安张江产业园REIT 2025年年度报告", "508000_2025.pdf")]

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_annual, "parse_annual_completion", lambda path: _annual_parse_result(2025)
    )

    rows = market_fetch.fetch_market_annual(
        [{"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"}]
    )

    assert downloaded == []
    assert len(rows) == 1
    assert rows[0]["year"] == 2025


def test_fetch_market_annual_collects_errors_and_continues(monkeypatch, tmp_path):
    """单基金列表失败 → errors 记录，其余基金正常。"""
    mc_path = tmp_path / "market_completion.json"
    mc_path.write_text(json.dumps({"completion": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_COMPLETION_PATH", mc_path)
    cache, _ = _patch_network(monkeypatch, tmp_path)
    _patch_annual_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        if code == "508008":
            raise RuntimeError("接口限流")
        if code == "508000":
            return [_sse_item("华安张江产业园REIT 2025年年度报告", "508000_2025.pdf")]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_annual, "parse_annual_completion", lambda path: _annual_parse_result(2025)
    )

    errors = []
    rows = market_fetch.fetch_market_annual(
        [
            {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
            {"code": "508008", "name": "国金中国铁建REIT", "exchange": "SSE"},
            {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
        ],
        errors=errors,
    )

    assert len(rows) == 1
    assert rows[0]["code"] == "508000"
    assert len(errors) == 1
    assert "508008" in errors[0]


def test_fetch_market_annual_sh_retries_and_15s_interval(monkeypatch, tmp_path):
    """沪市列表失败 → time.sleep(90) 重试 3 次后成功；沪市基金间 15s 间隔；
    深市走 cninfo。"""
    mc_path = tmp_path / "market_completion.json"
    mc_path.write_text(json.dumps({"completion": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_COMPLETION_PATH", mc_path)
    cache, _ = _patch_network(monkeypatch, tmp_path)
    _patch_annual_cache(monkeypatch, tmp_path)
    sleeps = []
    monkeypatch.setattr(market_fetch.time, "sleep", lambda s: sleeps.append(s))
    org_calls = []
    monkeypatch.setattr(
        cninfo, "search_org_id", lambda code: org_calls.append(code) or f"org-{code}"
    )
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    calls = {}

    def fake_sse_list(code, date_from, date_to, page_size=25):
        calls[code] = calls.get(code, 0) + 1
        if code == "508018":
            if calls[code] < 3:
                raise RuntimeError("接口限流")
            return [_sse_item("华夏中国交建REIT 2025年年度报告", "508018_2025.pdf")]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_annual, "parse_annual_completion", lambda path: _annual_parse_result(2025)
    )

    funds = [
        {"code": "508001", "name": "浙商沪杭甬REIT", "exchange": "SSE"},
        {"code": "508018", "name": "华夏中国交建REIT", "exchange": "SSE"},
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
    ]
    rows = market_fetch.fetch_market_annual(funds)

    assert len(rows) == 1
    assert rows[0]["code"] == "508018"
    assert calls["508018"] == 3
    assert org_calls == ["180201"]
    assert sleeps.count(90) == 2
    assert sleeps.count(15) == 2


def test_fetch_market_annual_skip_year_none_and_parse_failure(monkeypatch, tmp_path):
    """解析结果 year 缺失 → 行丢弃；单条解析失败 → errors 不崩溃。"""
    mc_path = tmp_path / "market_completion.json"
    mc_path.write_text(json.dumps({"completion": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_COMPLETION_PATH", mc_path)
    cache, _ = _patch_network(monkeypatch, tmp_path)
    _patch_annual_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    def fake_sse_list(code, date_from, date_to, page_size=25):
        if code == "508000":
            return [
                _sse_item("华安张江产业园REIT 2025年年度报告", "a.pdf"),
                _sse_item("华安张江产业园REIT 2024年年度报告", "b.pdf"),
            ]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)

    def fake_parse(path):
        if path.name == "a.pdf":
            return _annual_parse_result(None)
        raise ValueError("未找到「刊载的可供分配金额测算报告」段落")

    monkeypatch.setattr(parser_annual, "parse_annual_completion", fake_parse)

    errors = []
    rows = market_fetch.fetch_market_annual(
        [
            {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
            {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
        ],
        errors=errors,
    )

    assert rows == []
    assert len(errors) == 1
    assert "508000" in errors[0]
    assert "未找到" in errors[0]


def test_match_fund_code_handles_rename_and_ambiguity():
    """报告旧名（基金改名）靠最长公共子序列唯一匹配新简称；
    无唯一匹配返回 None。"""
    funds = [
        {"code": "180801", "name": "中航首钢绿能REIT"},
        {"code": "180501", "name": "红土创新深圳安居REIT"},
        {"code": "180102", "name": "华夏合肥高新REIT"},
    ]

    assert market_fetch._match_fund_code("中航首钢生物质", funds) == "180801"
    assert market_fetch._match_fund_code("红土创新深圳人才安居保障性租赁住房", funds) == "180501"
    # 两个候选得分并列 → 无唯一匹配
    tied = [
        {"code": "180102", "name": "华夏合肥高新REIT"},
        {"code": "180107", "name": "华夏合肥高新REIT"},
    ]
    assert market_fetch._match_fund_code("华夏合肥高新创新产业园", tied) is None


# ---- fetch_market_ops_rental（Task 5：租赁类出租率运营指标） ----


def _rental_report_text(period_title, occupancy="88.12"):
    """构造租赁类季报文本：标题含基金全名 + 报告期 + 4.1.2 运营指标表。"""
    return (
        f"华安张江产业园封闭式基础设施证券投资基金\n{period_title}\n\n"
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "3\n期末出租率\n%\n"
        f"{occupancy}\n"
        "4\n平均租金单价\n元/平/天\n5.44\n"
        "5\n期末剩余租期\n天\n554.00\n"
        "6\n期末租金收缴率\n%\n100.00\n"
    )


def test_fetch_market_ops_rental_filters_rental_types_and_writes_ops(
    monkeypatch, tmp_path
):
    """仅产业园/保障房/消费/仓储物流类基金入库；非租赁类跳过；
    解析为 None 的行丢弃；沪市按文件名前缀、深市按名称匹配 code；
    写回 market_ops_rental.json {"ops": [...]}。"""
    ops_path = tmp_path / "market_ops_rental.json"
    monkeypatch.setattr(market_fetch, "MARKET_OPS_RENTAL_PATH", ops_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "508000_2026Q2.pdf": _rental_report_text("2026年第2季度报告"),
            "508000_2026Q1.pdf": _rental_report_text("2026年第1季度报告", "91.50"),
            "508001_2026Q2.pdf": _rental_report_text("2026年第2季度报告"),
            "1211111111.PDF": (
                "博时蛇口产园封闭式基础设施证券投资基金\n"
                "2026年第2季度报告\n\n"
                "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
                "3\n期末出租率\n%\n95.00\n"
            ),
            "508000_2027Q1.pdf": "华安张江产业园2027年第1季度报告\n3.1 主要财务指标\n",
        },
    )

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT", "asset_type": "产业园"},
        {"code": "508001", "name": "浙商沪杭甬REIT", "asset_type": "高速"},
        {"code": "180101", "name": "博时蛇口产园REIT", "asset_type": "产业园"},
    ]
    rows = market_fetch.fetch_market_ops_rental(funds)

    # 508001（高速）跳过；508000_2027Q1 无出租率字段 → None 行丢弃
    assert [r["code"] for r in rows] == ["180101", "508000", "508000"]
    assert [r["period"] for r in rows] == ["2026Q2", "2026Q1", "2026Q2"]

    by_key = {f"{r['code']} {r['period']}": r for r in rows}
    assert by_key["508000 2026Q2"]["occupancy_pct"] == pytest.approx(88.12)
    assert by_key["508000 2026Q2"]["avg_rent_yuan"] == pytest.approx(5.44)
    assert by_key["508000 2026Q2"]["collection_pct"] == pytest.approx(100.0)
    assert by_key["508000 2026Q2"]["remaining_lease_days"] == pytest.approx(554.0)
    assert by_key["180101 2026Q2"]["occupancy_pct"] == pytest.approx(95.0)
    assert by_key["180101 2026Q2"]["collection_pct"] is None

    written = json.loads(ops_path.read_text(encoding="utf-8"))
    assert written == {"ops": rows}


# ---- fetch_market_ops_energy（Phase 6：能源类发电量运营指标） ----


def _energy_report_text(period_title, generation="61620.34"):
    """构造能源类季报文本：标题含基金全名 + 报告期 + 4.1.3 运营指标表。"""
    return (
        f"鹏华深圳能源封闭式基础设施证券投资基金\n{period_title}\n\n"
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n"
        f"{generation}\n"
        "2\n等效利用小时数\n小时\n527.00\n"
        "3\n结算电量\n万千瓦时\n60,688.10\n"
        "4\n结算电费\n元\n307,686,738.41\n"
        "5\n结算电价\n元/千瓦时(含税)\n0.57\n"
        "不动产项目运营年限预计至2037 年\n"
    )


def test_fetch_market_ops_energy_filters_energy_types_and_writes_ops(
    monkeypatch, tmp_path
):
    """仅能源类基金入库；非能源类跳过；解析为 None 的行丢弃；
    沪市按文件名前缀取 code、深市数字文件名按名称匹配 code；(code, period)
    去重；写回 market_ops_energy.json {"ops": [...]}。"""
    ops_path = tmp_path / "market_ops_energy.json"
    monkeypatch.setattr(market_fetch, "MARKET_OPS_ENERGY_PATH", ops_path)
    _patch_shares_cache(
        monkeypatch,
        tmp_path,
        {
            "180401_2026Q2.pdf": _energy_report_text("2026年第2季度报告"),
            "508015_2026Q2.pdf": _energy_report_text("2026年第2季度报告", "1000.00"),
            "1225431331.PDF": _energy_report_text("2026年第2季度报告"),
            "508001_2026Q2.pdf": "浙商沪杭甬REIT\n2026年第2季度报告\n3.1 主要财务指标\n",
            "508015_2027Q1.pdf": "中信建投明阳智能新能源REIT\n2027年第1季度报告\n",
        },
    )

    funds = [
        {"code": "180401", "name": "鹏华深圳能源REIT", "asset_type": "能源"},
        {"code": "508015", "name": "中信建投明阳智能新能源REIT", "asset_type": "能源"},
        {"code": "508001", "name": "浙商沪杭甬REIT", "asset_type": "高速"},
    ]
    rows = market_fetch.fetch_market_ops_energy(funds)

    # 508001（高速）跳过；508015_2027Q1 无发电量字段 → None 行丢弃；
    # 1225431331.PDF 与 180401_2026Q2.pdf 同 (code, period) → 去重
    assert [r["code"] for r in rows] == ["180401", "508015"]
    assert [r["period"] for r in rows] == ["2026Q2", "2026Q2"]

    by_code = {r["code"]: r for r in rows}
    assert by_code["180401"]["generation_wan_kwh"] == pytest.approx(61620.34)
    assert by_code["180401"]["utilization_hours"] == pytest.approx(527.0)
    assert by_code["180401"]["grid_wan_kwh"] == pytest.approx(60688.10)
    assert by_code["180401"]["electricity_revenue_wan"] == pytest.approx(
        30768.67, abs=0.01
    )
    assert by_code["180401"]["price_yuan_kwh"] == pytest.approx(0.57)
    assert by_code["180401"]["ops_until_year"] == 2037
    assert by_code["508015"]["generation_wan_kwh"] == pytest.approx(1000.0)

    written = json.loads(ops_path.read_text(encoding="utf-8"))
    assert written == {"ops": rows}


def test_fetch_market_quarterly_missing_fields_are_none(monkeypatch, tmp_path):
    """解析结果缺失字段如实为 None；period 缺失行丢弃。"""
    mq_path = tmp_path / "market_quarterly.json"
    mq_path.write_text(json.dumps({"quarters": []}), encoding="utf-8")
    monkeypatch.setattr(market_fetch, "MARKET_QUARTERLY_PATH", mq_path)
    cache, downloaded = _patch_network(monkeypatch, tmp_path)
    monkeypatch.setattr(cninfo, "search_org_id", lambda code: f"org-{code}")
    monkeypatch.setattr(cninfo, "list_announcements", lambda *a, **k: [])

    parsed = {
        "a.pdf": {
            "period": "2026Q1",
            "revenue_wan": 3065.07,
            "net_profit_wan": None,
            "distributable_wan": None,
            "unit_distributable": None,
            "ebitda_wan": None,
        },
        "b.pdf": {
            "period": None,
            "revenue_wan": 111.0,
            "net_profit_wan": None,
            "distributable_wan": None,
            "unit_distributable": None,
            "ebitda_wan": None,
        },
    }

    def fake_sse_list(code, date_from, date_to, page_size=25):
        if code == "508000":
            return [
                _sse_item("华安张江产业园REIT 2026年第1季度报告", "a.pdf"),
                _sse_item("某基金 2026年第1季度报告", "b.pdf"),
            ]
        return []

    monkeypatch.setattr(sse, "list_announcements", fake_sse_list)
    monkeypatch.setattr(
        parser_quarterly, "parse_quarterly_report", lambda path: parsed[path.name]
    )

    funds = [
        {"code": "508000", "name": "华安张江产业园REIT", "exchange": "SSE"},
        {"code": "180201", "name": "平安广州广河REIT", "exchange": "SZSE"},
    ]
    rows = market_fetch.fetch_market_quarterly(funds)

    assert len(rows) == 1
    row = rows[0]
    assert row["revenue_wan"] == pytest.approx(3065.07)
    assert row["net_profit_wan"] is None
    assert row["distributable_wan"] is None
    assert row["unit_distributable"] is None
    assert row["ebitda_wan"] is None
    assert set(rows[0].keys()) == set(ROW_KEYS)
