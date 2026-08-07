"""港股行情快照封装。

通过 akshare stock_hk_daily（新浪源）抓取港股最新收盘价，
并按 date+code 去重合并写入 data/hk_market_snapshot.json：
    {"snapshots": [{"date": "YYYY-MM-DD", "code": "00823", "price": 38.78}],
     "latest": {"00823": 38.78}}

akshare 慢接口统一走 _call_with_timeout（5s 超时）包装，单只失败跳过并记录。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date as _date
from pathlib import Path

import akshare as ak
import pandas as pd

# 快照数据文件（相对项目根 data/）
SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "hk_market_snapshot.json"
)

# 单次行情请求的超时秒数
_REQUEST_TIMEOUT = 5


def _call_with_timeout(fn, timeout=_REQUEST_TIMEOUT):
    """在线程池中执行 fn，超时或异常时返回降级值 None。

    正常返回 fn() 的结果；超时或异常时打印警告并返回 None，
    由调用方决定跳过该只。
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except Exception as e:
        print(f"[hk_market] 调用失败或超时（>{timeout}s）: {e}")
        return None
    finally:
        executor.shutdown(wait=False)


def _latest_close(df):
    """取日线 DataFrame 最后一行（最新）的收盘价与日期。"""
    row = df.iloc[-1]
    price = float(row["close"])
    date = str(row["date"])[:10]
    return price, date


def fetch_hk_prices(codes, errors=None):
    """抓取多只港股最新收盘价。

    对每个 code 调 akshare stock_hk_daily(symbol=code)（新浪源），
    取最后一行（最新）收盘价 → {code: {"price": float, "date": "YYYY-MM-DD"}}。
    单只失败 → errors 记录 code 并跳过；全部失败 → 返回 {}。
    """
    prices = {}
    for code in codes:
        df = _call_with_timeout(lambda: ak.stock_hk_daily(symbol=code))
        if df is None or df.empty:
            if errors is not None:
                errors.append(f"{code}: 获取行情失败或超时")
            continue
        try:
            price, date = _latest_close(df)
        except Exception as e:
            if errors is not None:
                errors.append(f"{code}: 解析行情失败: {e}")
            continue
        prices[code] = {"price": price, "date": date}
    return prices


def _load_snapshot():
    """读取快照文件；缺失/损坏时按空结构返回。"""
    if not SNAPSHOT_PATH.exists():
        return {"snapshots": [], "latest": {}}
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"snapshots": [], "latest": {}}
    return {
        "snapshots": data.get("snapshots", []) or [],
        "latest": data.get("latest", {}) or {},
    }


def update_hk_snapshot(prices):
    """合并写入快照文件，返回写入后的新结构。

    prices: {code: {"price": float, "date": "YYYY-MM-DD"}}。
    按 date+code 去重（已存在则覆盖价格不重复追加），latest 逐码覆盖。
    date 缺省用当天日期。
    """
    data = _load_snapshot()

    for code, item in prices.items():
        date = item.get("date") or _date.today().isoformat()
        price = item["price"]
        for snap in data["snapshots"]:
            if snap.get("date") == date and snap.get("code") == code:
                snap["price"] = price
                break
        else:
            data["snapshots"].append(
                {"date": date, "code": code, "price": price}
            )
        data["latest"][code] = price

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data
