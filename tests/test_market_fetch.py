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

from tools.reits_collector import cninfo, market_fetch, parser_quarterly, sse

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
