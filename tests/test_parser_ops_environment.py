"""tools.reits_collector.parser_ops_environment 模块（生态环保类运营指标解析）的单元测试。

使用真实季报 PDF（data/_cache/quarterly_market/508006_20260721_1ULD.pdf，
富国首创水务 2026Q2，4.1.3 节重要不动产项目运营指标，多项目表）做全链路断言：
- 处理量（污水处理量，第一项目合肥十五里河）2,277.81 万吨、
  产能利用率 83.44%、服务费单价 1.2980 元/吨（注：…含税单价为1.2980 元/吨）；
- 标签断行（「污水处 理量」「产能利用 率」「万 吨」「元/ 吨」）可解析；
- 标签变体（生活垃圾处理量/生活垃圾处理产能利用率、供应原水量）可解析；
- 无处理量字段（非环保类）→ 返回 None。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_ops_environment

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REAL_PDF = DATA_DIR / "_cache" / "quarterly_market" / "508006_20260721_1ULD.pdf"

ENV_KEYS = (
    "volume_wan_ton",
    "capacity_utilization_pct",
    "unit_price_yuan",
)


def test_parse_env_ops_real_pdf():
    """真实环保季报 PDF：4.1.3 节第一项目 处理量/产能利用率/服务费单价 正确解析。"""
    result = parser_ops_environment.parse_env_ops(REAL_PDF)

    assert result is not None
    assert set(result) == set(ENV_KEYS)
    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] == pytest.approx(83.44)
    assert result["unit_price_yuan"] == pytest.approx(1.298)


def test_parse_env_ops_broken_line_labels():
    """标签断行（PDF 表格单元格换行）：解析结果与连续标签一致。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "不动产项目名称：1 合肥十五里河首创水务有限责任公司\n"
        "1\n污水处\n理量\n万\n吨\n2,277.81\n"
        "2\n产能利用\n率\n%\n83.44\n"
        "注：报告期内协议约定污水处理服务费含税单价为1.2980 元/\n吨\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] == pytest.approx(83.44)
    assert result["unit_price_yuan"] == pytest.approx(1.298)


def test_parse_env_ops_label_variants_waste():
    """标签变体（垃圾焚烧 180801 口径）：生活垃圾处理量/生活垃圾处理产能利用率。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n生活垃圾处理量\n万吨\n25.99\n"
        "2\n生活垃圾处理产能利用率\n%\n25.99\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(25.99)
    assert result["capacity_utilization_pct"] == pytest.approx(25.99)
    assert result["unit_price_yuan"] is None


def test_parse_env_ops_label_variants_water_supply():
    """标签变体（水利供水 180701 口径）：供应原水量（万立方米）+ 无产能利用率。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "不动产项目名称：绍兴市汤浦水库工程\n"
        "1\n供应原水量\n万立方米\n5,360.59\n"
        "2\n原水价格\n元/立方米\n0.66\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(5360.59)
    assert result["capacity_utilization_pct"] is None
    assert result["unit_price_yuan"] is None


def test_parse_env_ops_thousand_separators():
    """千分位数值（如 2,277.81）正常转数字。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n污水处理量\n万吨\n2,277.81\n"
        "2\n产能利用率\n%\n83.44\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] == pytest.approx(83.44)


def test_parse_env_ops_skips_412_aggregate_table():
    """仅 4.1.3 节取值：4.1.2 整体运营指标（污水处理量 5,917.39 / 利用率 96.34）
    不会污染 4.1.3 第一项目取值。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "1\n污水处理量\n万吨\n5,917.39\n"
        "2\n产能利用率\n%\n96.34\n"
        "注：报告期内平均单价（污水处理收入/污水处理量）为1.3243 元/吨\n"
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "不动产项目名称：1 合肥十五里河首创水务有限责任公司\n"
        "1\n污水处理量\n万吨\n2,277.81\n"
        "2\n产能利用率\n%\n83.44\n"
        "注：报告期内协议约定污水处理服务费含税单价为1.2980 元/吨\n"
        "4.1.4 其他运营情况说明\n"
        "报告期内未发现重大问题。\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] == pytest.approx(83.44)
    assert result["unit_price_yuan"] == pytest.approx(1.298)


def test_parse_env_ops_multi_project_takes_first():
    """多项目表：取第一个项目（合肥）的值，后续项目（深圳）不合并不污染。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "不动产项目名称：1 合肥十五里河首创水务有限责任公司\n"
        "1\n污水处理量\n万吨\n2,277.81\n"
        "2\n产能利用率\n%\n83.44\n"
        "注：报告期内协议约定污水处理服务费含税单价为1.2980 元/吨\n"
        "不动产项目名称：2 深圳首创水务有限责任公司\n"
        "1\n污水处理量\n万吨\n3,639.57\n"
        "2\n产能利用率\n%\n105.17\n"
        "注：报告期内协议约定污水处理服务费含税单价为1.3713 元/吨\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] == pytest.approx(83.44)
    assert result["unit_price_yuan"] == pytest.approx(1.298)


def test_parse_env_ops_no_volume_returns_none():
    """无处理量字段（非环保类，如高速/能源季报）→ 返回 None。"""
    text = (
        "某高速公路封闭式基础设施证券投资基金2026年第2季度报告\n"
        "3.1 主要财务指标\n"
        "1.本期收入\n30,650,710.62\n"
        "2.本期净利润\n-11,644,536.88\n"
    )
    assert parser_ops_environment.parse_env_ops_text(text) is None


def test_parse_env_ops_no_413_table_returns_none():
    """环保类但无 4.1.3 运营指标表（旧报告叙述段披露）→ 无处理量行 → None。"""
    text = (
        "某环保封闭式基础设施证券投资基金2021年第3季度报告\n"
        "4.1 对报告期内基础设施项目运营情况的整体说明\n"
        "报告期内，项目处理生活垃圾27.5 万吨，实现上网电量7,588.24 万千瓦时。\n"
    )
    assert parser_ops_environment.parse_env_ops_text(text) is None


def test_parse_env_ops_partial_fields_are_none():
    """有处理量但其余字段缺失 → 缺失字段如实为 None，仍返回 dict。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n污水处理量\n万吨\n2,277.81\n"
    )
    result = parser_ops_environment.parse_env_ops_text(text)

    assert result is not None
    assert result["volume_wan_ton"] == pytest.approx(2277.81)
    assert result["capacity_utilization_pct"] is None
    assert result["unit_price_yuan"] is None


def test_market_env_ops_row_schema_from_real_pdf():
    """批量行结构：code/period 由调用方补充，运营指标三字段为数值。"""
    result = parser_ops_environment.parse_env_ops(REAL_PDF)
    row = {"code": "508006", "period": "2026Q2", **result}

    assert row["code"] == "508006"
    assert row["period"] == "2026Q2"
    for key in ENV_KEYS:
        assert isinstance(row[key], (int, float))
