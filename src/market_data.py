"""akshare 行情封装模块。

提供 REITs 全市场实时行情与单只 REIT 历史日线的获取函数，
统一将 akshare 中文列名规范化为英文列名，并对网络异常做容错处理：
akshare 调用失败时打印警告并返回列齐全的空 DataFrame。
"""

from concurrent.futures import ThreadPoolExecutor

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

# 单次行情请求的超时秒数
_REQUEST_TIMEOUT = 5


def _call_with_timeout(fn, timeout=_REQUEST_TIMEOUT):
    """在线程池中执行 fn，超时或异常时返回降级值 None。

    正常返回 fn() 的结果；超时或异常时打印警告并返回 None，
    由调用方决定降级为空表。
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except Exception as e:
        print(f"[market_data] 调用失败或超时（>{timeout}s）: {e}")
        return None
    finally:
        executor.shutdown(wait=False)


def get_realtime_quotes():
    """获取全市场 REITs 实时行情。

    返回 DataFrame，列为 code, name, price, pct_change, volume, amount。
    akshare 异常时打印警告并返回列齐全的空 DataFrame。
    """
    df = _call_with_timeout(lambda: ak.reits_realtime_em())
    if df is None:
        return EMPTY_QUOTES.copy()
    return df.rename(columns=_QUOTES_MAP)[QUOTES_COLS]


def get_hist(symbol):
    """获取单只 REIT 历史日线。

    返回 DataFrame，列为 date(datetime64), open, high, low, close, volume, amount。
    日期列统一转为 datetime64；akshare 异常时打印警告并返回列齐全的空 DataFrame。
    """
    df = _call_with_timeout(lambda: ak.reits_hist_em(symbol=symbol))
    if df is None:
        return EMPTY_HIST.copy()
    df = df.rename(columns=_HIST_MAP)[HIST_COLS]
    df["date"] = pd.to_datetime(df["date"])
    return df
