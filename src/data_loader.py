"""数据加载模块。

从 REITsMonitor 模板 Excel 中读取静态信息、月度数据与季度数据，
并将中文表头统一转换为英文列名。
"""

import json
import os
from pathlib import Path

import pandas as pd


# 静态信息表列名映射：中文表头 → 英文列名。
# 注意：部分表头含换行符与中文括号，键必须与 Excel 原始表头完全一致。
STATIC_COLS = {
    "基金代码": "code",
    "基金简称": "name",
    "底层资产": "asset",
    "区域": "region",
    "里程(km)": "mileage_km",
    "上市日期": "listing_date",
    "发行规模(亿元)": "issue_scale_yi",
    "特许经营剩余年限\n(截至2026)": "concession_years_left",
    "资产类型": "asset_type",
}

# 月度数据表列名映射
MONTHLY_COLS = {
    "报告期": "period",
    "基金代码": "code",
    "基金简称": "name",
    "通行费收入(万元)": "toll_revenue_wan",
    "日均自然车流量(辆/日)": "daily_traffic",
    "通行费收入同比(%)": "toll_revenue_yoy",
    "车流量同比(%)": "traffic_yoy",
    "数据来源/备注": "source",
}

# 季度数据表列名映射
QUARTERLY_COLS = {
    "报告期": "period",
    "基金代码": "code",
    "基金简称": "name",
    "营业总收入(万元)": "total_revenue_wan",
    "营业成本(万元)": "total_cost_wan",
    "净利润(万元)": "net_profit_wan",
    "可供分配金额(万元)": "distributable_wan",
    "EBITDA(万元)": "ebitda_wan",
    "基金净资产-NAV(万元)": "nav_wan",
    "数据来源/备注": "source",
}

# 各表的输出列顺序，严格按规范顺序
_STATIC_ORDER = [
    "code",
    "name",
    "asset",
    "region",
    "mileage_km",
    "listing_date",
    "issue_scale_yi",
    "concession_years_left",
    "asset_type",
]

_MONTHLY_ORDER = [
    "period",
    "code",
    "name",
    "toll_revenue_wan",
    "daily_traffic",
    "toll_revenue_yoy",
    "traffic_yoy",
    "source",
]

_QUARTERLY_ORDER = [
    "period",
    "code",
    "name",
    "total_revenue_wan",
    "total_cost_wan",
    "net_profit_wan",
    "distributable_wan",
    "ebitda_wan",
    "nav_wan",
    "source",
]


def _ensure_file_exists(path):
    """文件不存在时抛出 FileNotFoundError，错误信息携带传入路径。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")


def _to_string(series):
    """将数值型代码统一转为字符串，避免丢失前导零或被读成数字。"""
    if series.dtype.kind in "iuf":
        series = series.map(lambda v: str(int(v)) if float(v).is_integer() else str(v))
    return series.astype(str)


_PERIOD_PATTERN = r"\d{4}-\d{2}|\d{4}Q[1-4]"


def _read_sheet(path, sheet_name, col_map, order):
    """读取指定工作表，将中文表头映射为英文列名并按指定顺序输出。"""
    _ensure_file_exists(path)
    df = pd.read_excel(path, sheet_name=sheet_name)
    df = df.rename(columns=col_map)
    if "period" in df.columns:
        # 月度/季度：仅保留报告期列非空且符合报告期格式的行，过滤说明行
        df = df[
            df["period"].notna()
            & df["period"].astype(str).str.fullmatch(_PERIOD_PATTERN, na=False)
        ]
    elif "code" in df.columns:
        # 静态信息：仅保留基金代码为 6 位数字的行，过滤说明行
        df = df[df["code"].astype(str).str.fullmatch(r"\d{6}", na=False)]
    if "code" in df.columns:
        df["code"] = _to_string(df["code"])
    return df[order]


def load_static(path):
    """读取静态信息表，返回标准化列名的 DataFrame。"""
    return _read_sheet(path, "静态信息", STATIC_COLS, _STATIC_ORDER)


def load_monthly(path):
    """读取月度数据表，返回标准化列名的 DataFrame。"""
    return _read_sheet(path, "月度数据", MONTHLY_COLS, _MONTHLY_ORDER)


def load_quarterly(path):
    """读取季度数据表，返回标准化列名的 DataFrame。"""
    return _read_sheet(path, "季度数据", QUARTERLY_COLS, _QUARTERLY_ORDER)


def load_all(path):
    """读取全部三个工作表，返回 {"static": ..., "monthly": ..., "quarterly": ...}。"""
    _ensure_file_exists(path)
    return {
        "static": load_static(path),
        "monthly": load_monthly(path),
        "quarterly": load_quarterly(path),
    }


def _load_json_dict(path):
    """读取 JSON 文件为 dict；文件缺失或内容损坏时返回空 dict（不抛错）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_market_snapshot(path):
    """读取市场快照 JSON（{"snapshots": [...], "latest": {...}}）。

    文件缺失或损坏返回空 dict，看板侧据此降级。
    """
    return _load_json_dict(path)


def load_fund_shares(path):
    """读取基金份额 JSON（{"shares": {code: 份}}）。

    文件缺失或损坏返回空 dict，市值计算侧据此降级。
    """
    return _load_json_dict(path)


def load_market_funds(path):
    """读取全市场基金清单 JSON（{"funds": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / name / asset_type（其余字段按 JSON 原样保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("funds") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(columns=["code", "name", "asset_type"])
    return pd.DataFrame(rows)


def load_market_quarterly(path):
    """读取全市场季度财务 JSON（{"quarters": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / period / distributable_wan（其余字段按 JSON 原样保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("quarters") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(columns=["code", "period", "distributable_wan"])
    return pd.DataFrame(rows)


def load_market_completion(path):
    """读取全市场年报完成度 JSON（{"completion": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / name / year / completion_pct / nav_unit_price（其余字段保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("completion") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(
            columns=["code", "name", "year", "completion_pct", "nav_unit_price"]
        )
    return pd.DataFrame(rows)


def load_market_shares(path):
    """读取全市场份额 JSON（{"shares": {code: 份}}），缺失/损坏返回空 dict。

    返回内部 shares 映射（code → 份）。
    """
    data = _load_json_dict(path)
    shares = data.get("shares") if isinstance(data, dict) else None
    return shares if isinstance(shares, dict) else {}


def load_market_ops_rental(path):
    """读取全市场租赁类运营指标 JSON（{"ops": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / period / occupancy_pct / avg_rent_yuan / collection_pct /
    remaining_lease_days（其余字段按 JSON 原样保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("ops") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(
            columns=[
                "code",
                "period",
                "occupancy_pct",
                "avg_rent_yuan",
                "collection_pct",
                "remaining_lease_days",
            ]
        )
    return pd.DataFrame(rows)


def load_market_ops_environment(path):
    """读取全市场生态环保类运营指标 JSON（{"ops": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / period / volume_wan_ton / capacity_utilization_pct /
    unit_price_yuan（其余字段按 JSON 原样保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("ops") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(
            columns=[
                "code",
                "period",
                "volume_wan_ton",
                "capacity_utilization_pct",
                "unit_price_yuan",
            ]
        )
    return pd.DataFrame(rows)


def load_market_ops_energy(path):
    """读取全市场能源类运营指标 JSON（{"ops": [...]}），缺失/损坏返回空 DataFrame。

    返回列：code / period / generation_wan_kwh / utilization_hours /
    grid_wan_kwh / electricity_revenue_wan / price_yuan_kwh / ops_until_year
    （其余字段按 JSON 原样保留）。
    """
    data = _load_json_dict(path)
    rows = data.get("ops") if isinstance(data, dict) else None
    if not rows:
        return pd.DataFrame(
            columns=[
                "code",
                "period",
                "generation_wan_kwh",
                "utilization_hours",
                "grid_wan_kwh",
                "electricity_revenue_wan",
                "price_yuan_kwh",
                "ops_until_year",
            ]
        )
    return pd.DataFrame(rows)


def load_hk_funds(path):
    """读取香港基金清单 JSON（{"funds": [...]}），缺失/损坏返回空 dict。

    返回 {code: 基金简称} 映射（code 统一转为字符串）。
    """
    data = _load_json_dict(path)
    funds = data.get("funds") if isinstance(data, dict) else None
    if not funds:
        return {}
    return {str(f.get("code")): f.get("name", "") for f in funds}


def load_hk_annual(path):
    """读取香港年报/中期数据 JSON（{"annual": [...]}），缺失/损坏返回空 dict。

    返回 {code: [记录...]}（含 annual + interim，按 JSON 出现顺序；
    年报在前、中期在后，每条含 period 字段）。"""
    data = _load_json_dict(path)
    annual = data.get("annual") if isinstance(data, dict) else None
    if not annual:
        return {}
    grouped = {}
    for rec in annual:
        code = str(rec.get("code"))
        grouped.setdefault(code, []).append(rec)
    return grouped


def load_hk_snapshot(path):
    """读取香港行情快照 JSON（{"latest": {code: price}}），缺失/损坏返回空 dict。

    返回 latest 映射（code → price）。
    """
    data = _load_json_dict(path)
    latest = data.get("latest") if isinstance(data, dict) else None
    return latest if isinstance(latest, dict) else {}


def load_sg_funds(path):
    """读取新加坡基金清单 JSON（{"funds": [...]}），缺失/损坏返回空 dict。

    返回 {code: 基金简称} 映射（code 统一转为字符串）。
    """
    data = _load_json_dict(path)
    funds = data.get("funds") if isinstance(data, dict) else None
    if not funds:
        return {}
    return {str(f.get("code")): f.get("name", "") for f in funds}


def load_sg_annual(path):
    """读取新加坡年报/中期数据 JSON（{"annual": [...]}），缺失/损坏返回空 dict。

    返回 {code: [记录...]}（含 annual + interim，按 JSON 出现顺序；
    每条含 period 字段）。"""
    data = _load_json_dict(path)
    annual = data.get("annual") if isinstance(data, dict) else None
    if not annual:
        return {}
    grouped = {}
    for rec in annual:
        code = str(rec.get("code"))
        grouped.setdefault(code, []).append(rec)
    return grouped


def load_sg_snapshot(path):
    """读取新加坡行情快照 JSON（{"latest": {code: price}}），缺失/损坏返回空 dict。

    返回 latest 映射（code → price）。
    """
    data = _load_json_dict(path)
    latest = data.get("latest") if isinstance(data, dict) else None
    return latest if isinstance(latest, dict) else {}
