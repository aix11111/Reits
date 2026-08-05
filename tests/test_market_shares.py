"""全市场份额与年报净值/完成度数据文件（Task 3）的纯数据校验测试。

data/market_shares.json：{"shares": {code: 报告期末基金份额总额}}，
每基金取最新季报（本地解析季度报告缓存，见 market_fetch.fetch_market_shares）。
data/market_completion.json：{"completion": [同 annual_completion 结构]}，
每基金逐年年报可供分配完成度 + 净值（见 market_fetch.fetch_market_annual）。

本测试做纯数据校验（不涉及网络），与 test_market_funds.py 同模式。
抽样核对与公开信息一致的值（180201=7 亿份、508000 从季报解析、180202=3 亿份）。
"""

import json
from pathlib import Path

import pytest

MARKET_SHARES_PATH = Path(__file__).resolve().parents[1] / "data" / "market_shares.json"
MARKET_FUNDS_PATH = Path(__file__).resolve().parents[1] / "data" / "market_funds.json"
MARKET_COMPLETION_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "market_completion.json"
)

COMPLETION_REQUIRED = {
    "code",
    "name",
    "year",
    "predicted_wan",
    "actual_wan",
    "completion_pct",
    "nav_unit_price",
    "nav_wan",
}

SHARES_SAMPLES = {
    "180201": 700000000.0,
    "180202": 300000000.0,
    "508000": 960326121.0,
}


def _load_market_funds():
    return json.loads(MARKET_FUNDS_PATH.read_text(encoding="utf-8"))["funds"]


def test_market_shares_schema_valid():
    data = json.loads(MARKET_SHARES_PATH.read_text(encoding="utf-8"))
    shares = data["shares"]
    assert isinstance(shares, dict) and len(shares) >= 80
    for code, value in shares.items():
        assert isinstance(code, str) and len(code) == 6 and code.isdigit()
        assert isinstance(value, (int, float)) and value > 0


def test_market_shares_codes_subset_of_market_funds():
    funds = _load_market_funds()
    fund_codes = {fund["code"] for fund in funds}
    shares = json.loads(MARKET_SHARES_PATH.read_text(encoding="utf-8"))["shares"]

    assert set(shares).issubset(fund_codes)


def test_market_shares_samples_match_known_values():
    """抽样核对：180201=7 亿份、180202=3 亿份、508000 从季报解析的份额。"""
    shares = json.loads(MARKET_SHARES_PATH.read_text(encoding="utf-8"))["shares"]

    for code, expected in SHARES_SAMPLES.items():
        assert shares.get(code) == pytest.approx(expected), f"{code} 份额不符"


def test_market_completion_schema_valid():
    data = json.loads(MARKET_COMPLETION_PATH.read_text(encoding="utf-8"))
    completion = data["completion"]
    assert isinstance(completion, list) and len(completion) > 0
    pairs = []
    with_completion = 0
    for row in completion:
        assert COMPLETION_REQUIRED.issubset(row.keys()), f"{row.get('code')} 缺字段"
        assert row["year"] is not None
        assert isinstance(row["year"], int)
        assert isinstance(row["code"], str) and row["code"].isdigit()
        if row["completion_pct"] is not None:
            assert row["predicted_wan"] is not None and row["actual_wan"] is not None
            with_completion += 1
        pairs.append((row["code"], row["year"]))
    assert len(pairs) == len(set(pairs)), "(code, year) 重复"
    assert with_completion > 0, "应有已完成度数据行"
