"""全市场 REITs 清单（data/market_funds.json）的加载与数据校验测试。

清单为全市场公募 REITs（86+ 只，2026-08 口径），字段：
code/name/asset_type/listed_date/manager/exchange/source。
asset_type 枚举：高速/产业园/仓储物流/能源/生态环保/保障房/消费/商业不动产。
本测试做纯数据校验（不涉及网络），并验证 market_funds.load_market_funds
加载函数：文件缺失/损坏 → 空 DataFrame。
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.reits_collector import market_funds

ASSET_TYPES = {
    "高速",
    "产业园",
    "仓储物流",
    "能源",
    "生态环保",
    "保障房",
    "消费",
    "商业不动产",
}

MARKET_FUNDS_PATH = Path(__file__).resolve().parents[1] / "data" / "market_funds.json"


def _load_data():
    """读取市场清单原始 dict（供 schema/数值断言直接使用）。"""
    return json.loads(MARKET_FUNDS_PATH.read_text(encoding="utf-8"))


def test_funds_schema_required_fields_and_unique_code():
    data = _load_data()
    funds = data["funds"]
    assert isinstance(funds, list) and len(funds) >= 80
    codes = []
    for fund in funds:
        assert isinstance(fund, dict)
        for key in ("code", "name", "asset_type", "listed_date", "manager", "exchange"):
            assert key in fund, f"{fund.get('code')} 缺少字段 {key}"
            assert fund[key], f"{fund.get('code')} 的 {key} 为空"
        assert isinstance(fund["code"], str) and len(fund["code"]) == 6
        assert fund["code"].isdigit()
        codes.append(fund["code"])
    assert len(codes) == len(set(codes)), "基金代码重复"


def test_asset_type_enum_valid():
    data = _load_data()
    for fund in data["funds"]:
        assert fund["asset_type"] in ASSET_TYPES, (
            f"{fund['code']} 资产类型 {fund['asset_type']} 不在枚举内"
        )


def test_exchange_and_source_valid():
    data = _load_data()
    for fund in data["funds"]:
        assert fund["exchange"] in {"SSE", "SZSE"}
        assert fund["source"], f"{fund['code']} 缺少来源"


def test_listed_date_format():
    import datetime

    data = _load_data()
    for fund in data["funds"]:
        try:
            datetime.date.fromisoformat(fund["listed_date"])
        except ValueError as exc:
            raise AssertionError(
                f"{fund['code']} 上市日期 {fund['listed_date']} 格式非法"
            ) from exc


def test_meta_count_matches_funds():
    data = _load_data()
    assert data["meta"]["count"] == len(data["funds"])
    assert data["meta"]["count"] >= 80


def test_all_asset_types_represented():
    data = _load_data()
    types = {fund["asset_type"] for fund in data["funds"]}
    assert types == ASSET_TYPES


def test_funds_cover_known_fourteen():
    """原 14 只高速资产应全部在清单内且类型为高速。"""
    data = _load_data()
    known = [
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
    by_code = {fund["code"]: fund for fund in data["funds"]}
    for code in known:
        assert code in by_code, f"原高速资产 {code} 不在清单内"
        assert by_code[code]["asset_type"] == "高速", f"{code} 类型应为高速"


def test_load_market_funds_returns_dataframe():
    df = market_funds.load_market_funds(MARKET_FUNDS_PATH)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == market_funds.FUND_COLS
    assert len(df) >= 80
    assert df["code"].is_unique
    assert df["code"].str.match(r"\d{6}").all()


def test_load_market_funds_missing_file_returns_empty(tmp_path):
    df = market_funds.load_market_funds(tmp_path / "missing.json")
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == market_funds.FUND_COLS


def test_load_market_funds_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    df = market_funds.load_market_funds(path)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_load_market_funds_bad_structure_returns_empty(tmp_path):
    path = tmp_path / "bad_struct.json"
    path.write_text('{"funds": "oops"}', encoding="utf-8")
    df = market_funds.load_market_funds(path)
    assert isinstance(df, pd.DataFrame)
    assert df.empty
