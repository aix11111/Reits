"""新加坡（S-REITs）行情快照封装。

通过雅虎 finance chart API（query1.finance.yahoo.com/v8/finance/chart/{CODE}.SI）
抓取新加坡 REIT 最新收盘价，按 date+code 去重合并写入 data/sg_market_snapshot.json：
    {"snapshots": [{"date": "YYYY-MM-DD", "code": "C38U", "price": 2.46}],
     "latest": {"C38U": 2.46}}

单只请求 5s 超时，失败跳过并记录；全部失败返回 {}。
"""

import json
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

import requests

# 快照数据文件（相对项目根 data/）
SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "sg_market_snapshot.json"
)

# 单次行情请求的超时秒数
_REQUEST_TIMEOUT = 5

# 雅虎 chart API（后缀 .SI 为新加坡交易所代码）
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{code}.SI"

# 浏览器 UA，避免雅虎 429 限流
_YAHOO_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _chart_price(payload):
    """解析雅虎 chart API v8 响应 → (price, date)；无行情数据 → (None, None)。

    取 result[0].meta.regularMarketPrice 为最新价、regularMarketTime 为日期；
    若 meta 无价则回退 indicators.quote[0].close 最后一项。
    """
    chart = (payload or {}).get("chart") or {}
    result = chart.get("result") or []
    if not result:
        return None, None
    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    timestamp = meta.get("regularMarketTime")
    if price is None:
        quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        closes = [c for c in closes if c is not None]
        if not closes:
            return None, None
        price = closes[-1]
        ts_list = result[0].get("timestamp") or []
        if ts_list:
            timestamp = ts_list[-1]
    date = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        if timestamp
        else _date.today().isoformat()
    )
    return float(price), date


def fetch_sg_prices(codes, errors=None):
    """抓取多只新加坡 REIT 最新收盘价。

    对每个 code 调雅虎 chart API（{code}.SI），解析 meta.regularMarketPrice
    → {code: {"price": float, "date": "YYYY-MM-DD"}}。
    单只失败 → errors 记录 code 并跳过；全部失败 → 返回 {}。
    """
    prices = {}
    for code in codes:
        try:
            resp = requests.get(
                _CHART_URL.format(code=code),
                headers={"User-Agent": _YAHOO_UA},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            price, date = _chart_price(resp.json())
        except Exception as e:
            if errors is not None:
                errors.append(f"{code}: 获取行情失败: {e}")
            continue
        if price is None:
            if errors is not None:
                errors.append(f"{code}: 行情数据缺失")
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


def update_sg_snapshot(prices):
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
