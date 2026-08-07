"""tools.reits_collector.sg_market 模块（新加坡雅虎行情快照）的单元测试。

通过 monkeypatch 替换 requests.get，避免真实网络请求。
覆盖：雅虎 chart JSON → 最新价格提取、单只失败跳过并记录、全失败返回 {}、
快照合并去重、文件缺失容错、默认用当天日期。
"""

import json
from datetime import date

import pytest

from tools.reits_collector import sg_market as sm


class _FakeResponse:
    def __init__(self, payload=None, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error
        return None

    def json(self):
        return self._payload


def _chart_payload(price=2.46, meta_time=1783353600):
    """模拟雅虎 chart API v8 响应（result[0].meta 含最新价与时间戳）。"""
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "SGD",
                        "regularMarketPrice": price,
                        "regularMarketTime": meta_time,
                    },
                    "timestamp": [meta_time],
                    "indicators": {"quote": [{"close": [price]}]},
                }
            ],
            "error": None,
        }
    }


def _expected_date(meta_time):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(meta_time, tz=timezone.utc).date().isoformat()


def test_snapshot_path_matches_spec():
    assert sm.SNAPSHOT_PATH.name == "sg_market_snapshot.json"


def test_fetch_sg_prices_extracts_price_and_date(monkeypatch):
    def fake_get(url, timeout, headers=None):
        assert url.endswith("C38U.SI")
        return _FakeResponse(payload=_chart_payload(price=2.46))

    monkeypatch.setattr(sm.requests, "get", fake_get)

    result = sm.fetch_sg_prices(["C38U"])

    assert result == {"C38U": {"price": 2.46, "date": _expected_date(1783353600)}}


def test_fetch_sg_prices_skips_single_failure_and_records_error(monkeypatch):
    def fake_get(url, timeout, headers=None):
        if url.endswith("C38U.SI"):
            return _FakeResponse(payload=_chart_payload(price=2.46))
        return _FakeResponse(status_error=ConnectionError("网络连接失败"))

    monkeypatch.setattr(sm.requests, "get", fake_get)
    errors = []

    result = sm.fetch_sg_prices(["C38U", "A17U"], errors=errors)

    assert result == {"C38U": {"price": 2.46, "date": _expected_date(1783353600)}}
    assert len(errors) == 1
    assert "A17U" in errors[0]


def test_fetch_sg_prices_returns_empty_when_all_fail(monkeypatch):
    def fake_get(url, timeout, headers=None):
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(sm.requests, "get", fake_get)
    errors = []

    result = sm.fetch_sg_prices(["C38U", "A17U"], errors=errors)

    assert result == {}
    assert len(errors) == 2


def test_fetch_sg_prices_skips_missing_chart_result(monkeypatch):
    def fake_get(url, timeout, headers=None):
        return _FakeResponse(payload={"chart": {"result": None, "error": None}})

    monkeypatch.setattr(sm.requests, "get", fake_get)
    errors = []

    result = sm.fetch_sg_prices(["C38U"], errors=errors)

    assert result == {}
    assert len(errors) == 1


def test_update_sg_snapshot_appends_new_entry(monkeypatch, tmp_path):
    snapshot = tmp_path / "sg_market_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshots": [
                    {"date": "2026-08-06", "code": "C38U", "price": 2.44},
                ],
                "latest": {"C38U": 2.44},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sm, "SNAPSHOT_PATH", snapshot)

    result = sm.update_sg_snapshot(
        {"C38U": {"price": 2.46, "date": "2026-08-07"}}
    )

    assert result["latest"] == {"C38U": 2.46}
    snapshots = result["snapshots"]
    assert len(snapshots) == 2
    assert snapshots[-1] == {"date": "2026-08-07", "code": "C38U", "price": 2.46}


def test_update_sg_snapshot_dedupes_same_date_and_code(monkeypatch, tmp_path):
    snapshot = tmp_path / "sg_market_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshots": [
                    {"date": "2026-08-07", "code": "C38U", "price": 2.40},
                ],
                "latest": {"C38U": 2.40},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sm, "SNAPSHOT_PATH", snapshot)

    result = sm.update_sg_snapshot(
        {"C38U": {"price": 2.46, "date": "2026-08-07"}}
    )

    assert len(result["snapshots"]) == 1
    assert result["snapshots"][0] == {
        "date": "2026-08-07",
        "code": "C38U",
        "price": 2.46,
    }
    assert result["latest"] == {"C38U": 2.46}


def test_update_sg_snapshot_missing_file_starts_empty(monkeypatch, tmp_path):
    snapshot = tmp_path / "sg_market_snapshot.json"
    monkeypatch.setattr(sm, "SNAPSHOT_PATH", snapshot)

    result = sm.update_sg_snapshot(
        {"C38U": {"price": 2.46, "date": "2026-08-07"}}
    )

    assert result["snapshots"] == [
        {"date": "2026-08-07", "code": "C38U", "price": 2.46}
    ]
    assert result["latest"] == {"C38U": 2.46}
    assert snapshot.exists()


def test_update_sg_snapshot_uses_today_when_no_date(monkeypatch, tmp_path):
    snapshot = tmp_path / "sg_market_snapshot.json"
    monkeypatch.setattr(sm, "SNAPSHOT_PATH", snapshot)

    result = sm.update_sg_snapshot({"C38U": {"price": 2.46}})

    assert result["snapshots"][0]["date"] == date.today().isoformat()
    assert result["snapshots"][0]["code"] == "C38U"
    assert result["snapshots"][0]["price"] == 2.46
