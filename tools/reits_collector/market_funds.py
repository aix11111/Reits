"""全市场 REITs 清单加载模块。

读取 data/market_funds.json（{"funds": [...], "meta": {...}}），
返回标准化列的 DataFrame；文件缺失或损坏返回空 DataFrame（不抛错），
供看板全市场视图降级使用。
"""

import json
from pathlib import Path

import pandas as pd

FUND_COLS = [
    "code",
    "name",
    "asset_type",
    "listed_date",
    "manager",
    "exchange",
    "source",
]

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "market_funds.json"


def load_market_funds(path=None):
    """读取全市场 REITs 清单，返回 DataFrame。

    文件缺失、内容损坏或结构异常返回空 DataFrame（列齐全，无数据行）。
    """
    path = Path(path) if path is not None else DEFAULT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return pd.DataFrame(columns=FUND_COLS)
    funds = data.get("funds") if isinstance(data, dict) else None
    if not isinstance(funds, list):
        return pd.DataFrame(columns=FUND_COLS)
    df = pd.DataFrame(funds, columns=FUND_COLS)
    df["code"] = df["code"].astype(str)
    return df
