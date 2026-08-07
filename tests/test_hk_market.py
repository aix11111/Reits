"""tools.reits_collector.hk_market 模块（港股行情快照）的单元测试。

通过 monkeypatch 替换 akshare stock_hk_daily（新浪源），避免真实网络请求。
覆盖最新收盘提取、单只失败跳过、全失败返回 {}、快照合并去重、文件缺失容错。
"""

import json
from datetime import date

import pandas as pd
import pytest

from tools.reits_collector import hk_market as hm


def _daily_df():
    """模拟 stock_hk_daily 返回的日线 DataFrame（close 列，最后一行=最新收盘）。"""
    return pd.DataFrame(
        {
            "date": ["2026-08-04", "2026-08-05", "2026-08-06"],
            "open": [39.06, 39.02, 38.60],
            "high": [39.14, 39.24, 38.96],
            "low": [38.88, 38.64, 38.28],
            "close": [39.02, 39.06, 38.78],
            "volume": [8936780.0, 9137848.0, 7254426.0],
            "amount": [348574373.0, 356224923.0, 280698267.0],
        }
    )


def test_snapshot_path_matches_spec():
    assert hm.SNAPSHOT_PATH.name == "hk_market_snapshot.json"


def test_fetch_hk_prices_extracts_latest_close_and_date(monkeypatch):
    monkeypatch.setattr(hm.ak, "stock_hk_daily", lambda symbol: _daily_df())

    result = hm.fetch_hk_prices(["00823"])

    assert result == {"00823": {"price": 38.78, "date": "2026-08-06"}}


def test_fetch_hk_prices_skips_single_failure_and_records_error(monkeypatch):
    def fake(symbol):
        if symbol == "00823":
            return _daily_df()
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(hm.ak, "stock_hk_daily", fake)
    errors = []

    result = hm.fetch_hk_prices(["00823", "00012"], errors=errors)

    assert result == {"00823": {"price": 38.78, "date": "2026-08-06"}}
    assert len(errors) == 1
    assert "00012" in errors[0]


def test_fetch_hk_prices_returns_empty_when_all_fail(monkeypatch):
    def boom(symbol):
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(hm.ak, "stock_hk_daily", boom)
    errors = []

    result = hm.fetch_hk_prices(["00823", "00012"], errors=errors)

    assert result == {}
    assert len(errors) == 2


def test_update_hk_snapshot_appends_new_entry(monkeypatch, tmp_path):
    snapshot = tmp_path / "hk_market_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshots": [
                    {"date": "2026-08-05", "code": "00823", "price": 39.06},
                ],
                "latest": {"00823": 39.06},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hm, "SNAPSHOT_PATH", snapshot)

    result = hm.update_hk_snapshot({"00823": {"price": 38.78, "date": "2026-08-06"}})

    assert result["latest"] == {"00823": 38.78}
    snapshots = result["snapshots"]
    assert len(snapshots) == 2
    assert snapshots[-1] == {"date": "2026-08-06", "code": "00823", "price": 38.78}


def test_update_hk_snapshot_dedupes_same_date_and_code(monkeypatch, tmp_path):
    snapshot = tmp_path / "hk_market_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshots": [
                    {"date": "2026-08-06", "code": "00823", "price": 39.0},
                ],
                "latest": {"00823": 39.0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hm, "SNAPSHOT_PATH", snapshot)

    result = hm.update_hk_snapshot({"00823": {"price": 38.78, "date": "2026-08-06"}})

    assert len(result["snapshots"]) == 1
    assert result["snapshots"][0] == {
        "date": "2026-08-06",
        "code": "00823",
        "price": 38.78,
    }
    assert result["latest"] == {"00823": 38.78}


def test_update_hk_snapshot_missing_file_starts_empty(monkeypatch, tmp_path):
    snapshot = tmp_path / "hk_market_snapshot.json"
    monkeypatch.setattr(hm, "SNAPSHOT_PATH", snapshot)

    result = hm.update_hk_snapshot({"00823": {"price": 38.78, "date": "2026-08-06"}})

    assert result["snapshots"] == [
        {"date": "2026-08-06", "code": "00823", "price": 38.78}
    ]
    assert result["latest"] == {"00823": 38.78}
    assert snapshot.exists()


def test_update_hk_snapshot_uses_today_when_no_date(monkeypatch, tmp_path):
    snapshot = tmp_path / "hk_market_snapshot.json"
    monkeypatch.setattr(hm, "SNAPSHOT_PATH", snapshot)

    result = hm.update_hk_snapshot({"00823": {"price": 38.78}})

    assert result["snapshots"][0]["date"] == date.today().isoformat()
    assert result["snapshots"][0]["code"] == "00823"
    assert result["snapshots"][0]["price"] == 38.78
