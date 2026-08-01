"""src.market_data 模块（akshare 行情封装）的单元测试。

通过 monkeypatch 替换 md.ak.reits_realtime_em / md.ak.reits_hist_em，
避免真实调用 akshare 网络接口。
"""

import pandas as pd
import pytest

import src.market_data as md

QUOTES_COLS = ["code", "name", "price", "pct_change", "volume", "amount"]
HIST_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _quotes_chinese_df():
    """模拟 reits_realtime_em 返回的中文列名 DataFrame。"""
    return pd.DataFrame(
        {
            "代码": ["180201", "180202"],
            "名称": ["平安广州广河REIT", "华夏越秀高速REIT"],
            "最新价": [7.05, 6.42],
            "涨跌幅": [1.22, -0.78],
            "成交量": [3200000, 1800000],
            "成交额": [22560000.0, 11556000.0],
        }
    )


def _hist_chinese_df():
    """模拟 reits_hist_em 返回的中文列名 DataFrame。"""
    return pd.DataFrame(
        {
            "日期": ["2024-01-02", "2024-01-03"],
            "今开": [7.0, 7.05],
            "最高": [7.1, 7.12],
            "最低": [6.95, 7.0],
            "最新价": [7.05, 7.08],
            "成交量": [3000000, 3500000],
            "成交额": [21150000.0, 24780000.0],
        }
    )


def _quotes_empty():
    """预期异常时的空表：六列齐全，无数据行。"""
    return pd.DataFrame(columns=QUOTES_COLS)


def _hist_empty():
    """预期异常时的空表：七列齐全，无数据行。"""
    return pd.DataFrame(columns=HIST_COLS)


def test_get_realtime_quotes_normalizes_columns_and_values(monkeypatch):
    monkeypatch.setattr(md.ak, "reits_realtime_em", lambda: _quotes_chinese_df())

    df = md.get_realtime_quotes()

    assert list(df.columns) == QUOTES_COLS
    assert df["code"].tolist() == ["180201", "180202"]
    assert df["name"].tolist() == ["平安广州广河REIT", "华夏越秀高速REIT"]
    assert df["price"].tolist() == pytest.approx([7.05, 6.42])
    assert df["pct_change"].tolist() == pytest.approx([1.22, -0.78])
    assert df["volume"].tolist() == pytest.approx([3200000, 1800000])
    assert df["amount"].tolist() == pytest.approx([22560000.0, 11556000.0])


def test_get_realtime_quotes_returns_empty_with_columns_on_error(monkeypatch, capsys):
    def boom():
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(md.ak, "reits_realtime_em", boom)

    df = md.get_realtime_quotes()

    assert df.empty
    assert list(df.columns) == QUOTES_COLS
    assert "网络连接失败" in capsys.readouterr().out


def test_get_hist_normalizes_columns_and_values_and_converts_date(monkeypatch):
    monkeypatch.setattr(md.ak, "reits_hist_em", lambda symbol: _hist_chinese_df())

    df = md.get_hist("180201")

    assert list(df.columns) == HIST_COLS
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert df["date"].tolist() == pd.to_datetime(["2024-01-02", "2024-01-03"]).tolist()
    assert df["open"].tolist() == pytest.approx([7.0, 7.05])
    assert df["high"].tolist() == pytest.approx([7.1, 7.12])
    assert df["low"].tolist() == pytest.approx([6.95, 7.0])
    assert df["close"].tolist() == pytest.approx([7.05, 7.08])
    assert df["volume"].tolist() == pytest.approx([3000000, 3500000])
    assert df["amount"].tolist() == pytest.approx([21150000.0, 24780000.0])


def test_get_hist_returns_empty_with_columns_on_error(monkeypatch, capsys):
    def boom(symbol):
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(md.ak, "reits_hist_em", boom)

    df = md.get_hist("180201")

    assert df.empty
    assert list(df.columns) == HIST_COLS
    assert "网络连接失败" in capsys.readouterr().out


def test_error_returns_independent_copies(monkeypatch):
    """异常时多次调用应各自返回独立副本，互不影响。"""

    def boom():
        raise ConnectionError("网络连接失败")

    monkeypatch.setattr(md.ak, "reits_realtime_em", boom)

    first = md.get_realtime_quotes()
    second = md.get_realtime_quotes()

    assert first is not second
    assert list(first.columns) == QUOTES_COLS
    assert list(second.columns) == QUOTES_COLS
