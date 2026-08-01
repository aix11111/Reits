"""akshare 行情封装模块。

提供 REITs 全市场实时行情与单只 REIT 历史日线的获取函数，
统一将 akshare 中文列名规范化为英文列名，并对网络异常做容错处理：
akshare 调用失败时打印警告并返回列齐全的空 DataFrame。
"""

import akshare as ak
import pandas as pd

# 实时行情输出列（与 reits_realtime_em 的中文表头对应）
QUOTES_COLS = ["code", "name", "price", "pct_change", "volume", "amount"]

# 历史日线输出列（与 reits_hist_em 的中文表头对应）
HIST_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]

# 列名映射：中文表头 → 英文列名
_QUOTES_MAP = {
    "代码": "code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "pct_change",
    "成交量": "volume",
    "成交额": "amount",
}

_HIST_MAP = {
    "日期": "date",
    "今开": "open",
    "最高": "high",
    "最低": "low",
    "最新价": "close",
    "成交量": "volume",
    "成交额": "amount",
}

# 模块级常量空表：异常时返回的副本，保证列齐全
EMPTY_QUOTES = pd.DataFrame(columns=QUOTES_COLS)
EMPTY_HIST = pd.DataFrame(columns=HIST_COLS)


def get_realtime_quotes():
    """获取全市场 REITs 实时行情。

    返回 DataFrame，列为 code, name, price, pct_change, volume, amount。
    akshare 异常时打印警告并返回列齐全的空 DataFrame。
    """
    try:
        df = ak.reits_realtime_em()
        return df.rename(columns=_QUOTES_MAP)[QUOTES_COLS]
    except Exception as e:
        print(f"[market_data] get_realtime_quotes 失败: {e}")
        return EMPTY_QUOTES.copy()


def get_hist(symbol):
    """获取单只 REIT 历史日线。

    返回 DataFrame，列为 date(datetime64), open, high, low, close, volume, amount。
    日期列统一转为 datetime64；akshare 异常时打印警告并返回列齐全的空 DataFrame。
    """
    try:
        df = ak.reits_hist_em(symbol=symbol)
        df = df.rename(columns=_HIST_MAP)[HIST_COLS]
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        print(f"[market_data] get_hist 失败: {e}")
        return EMPTY_HIST.copy()
