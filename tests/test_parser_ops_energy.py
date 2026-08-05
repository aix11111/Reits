"""tools.reits_collector.parser_ops_energy 模块（能源类运营指标解析）的单元测试。

使用真实季报 PDF（data/_cache/quarterly_market/1225431331.PDF，
鹏华深圳能源 2026Q2，4.1.3 节重要不动产项目运营指标）做全链路断言：
- 发电量 61,620.34 万千瓦时、等效利用小时 527 小时、
  结算电量(上网) 60,688.10 万千瓦时、结算电费 307,686,738.41 元 → 万元
  30,768.67、结算电价 0.57 元/千瓦时；
- 4.1 节「不动产项目运营年限预计至 2037 年」→ ops_until_year=2037；
- 标签断行（「等效利用小 时数」「结算电 价」）与标签变体
  （「上网电量」「平均结算电价」）均可解析；
- 结算电费单位「万元」口径时不除以 10000、如实取；
- 无发电量字段（非能源类，或能源类无 4.1.3 表）→ 返回 None。
"""

from pathlib import Path

import pytest

from tools.reits_collector import parser_ops_energy

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REAL_PDF = DATA_DIR / "_cache" / "quarterly_market" / "1225431331.PDF"

ENERGY_KEYS = (
    "generation_wan_kwh",
    "utilization_hours",
    "grid_wan_kwh",
    "electricity_revenue_wan",
    "price_yuan_kwh",
    "ops_until_year",
)


def test_parse_energy_ops_real_pdf():
    """真实能源季报 PDF：4.1.3 节五字段 + 4.1 节运营年限正确解析。"""
    result = parser_ops_energy.parse_energy_ops(REAL_PDF)

    assert result is not None
    assert set(result) == set(ENERGY_KEYS)
    assert result["generation_wan_kwh"] == pytest.approx(61620.34)
    assert result["utilization_hours"] == pytest.approx(527.0)
    assert result["grid_wan_kwh"] == pytest.approx(60688.10)
    assert result["electricity_revenue_wan"] == pytest.approx(30768.67, abs=0.01)
    assert result["price_yuan_kwh"] == pytest.approx(0.57)
    assert result["ops_until_year"] == 2037


def test_parse_energy_ops_broken_line_labels():
    """标签断行（PDF 表格单元格换行）：解析结果与连续标签一致。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发\n电量\n万千瓦时\n61,620.34\n"
        "2\n等效利用小\n时数\n小时\n527.00\n"
        "3\n结\n算电量\n万千瓦时\n60,688.10\n"
        "4\n结算电\n费\n元\n307,686,738.41\n"
        "5\n结算电\n价\n元/千瓦时(含税)\n0.57\n"
        "不动产项目运营年限预计至2037 年\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["generation_wan_kwh"] == pytest.approx(61620.34)
    assert result["utilization_hours"] == pytest.approx(527.0)
    assert result["grid_wan_kwh"] == pytest.approx(60688.10)
    assert result["electricity_revenue_wan"] == pytest.approx(30768.67, abs=0.01)
    assert result["price_yuan_kwh"] == pytest.approx(0.57)
    assert result["ops_until_year"] == 2037


def test_parse_energy_ops_label_variants():
    """标签变体：「上网电量」「平均结算电价」「利用小时数」也能解析。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n10,000.00\n"
        "2\n利用小时数\n小时\n500.00\n"
        "3\n上网电量\n万千瓦时\n9,800.00\n"
        "4\n结算电费\n元\n100,000,000.00\n"
        "5\n平均结算电价\n元/千瓦时（含税）\n0.50\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["generation_wan_kwh"] == pytest.approx(10000.0)
    assert result["utilization_hours"] == pytest.approx(500.0)
    assert result["grid_wan_kwh"] == pytest.approx(9800.0)
    assert result["electricity_revenue_wan"] == pytest.approx(10000.0)
    assert result["price_yuan_kwh"] == pytest.approx(0.50)
    assert result["ops_until_year"] is None


def test_parse_energy_ops_revenue_in_wan_unit():
    """结算电费单位「万元」口径：值如实取，不再除以 10000。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n10,000.00\n"
        "2\n等效利用小时数\n小时\n500.00\n"
        "3\n结算电量\n万千瓦时\n9,800.00\n"
        "4\n结算电费\n万元\n30,768.67\n"
        "5\n结算电价\n元/千瓦时\n0.50\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["electricity_revenue_wan"] == pytest.approx(30768.67)


def test_parse_energy_ops_revenue_broken_wan_unit():
    """结算电费单位断行成「万 元」（PDF 单元格换行）：仍按万元口径如实取。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n10,000.00\n"
        "2\n等效利用小时数\n小时\n500.00\n"
        "3\n结算电量\n万千瓦时\n9,800.00\n"
        "4\n结算电费\n人民币万\n元\n30,768.67\n"
        "5\n平均结算电价\n元/千瓦时\n0.50\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["electricity_revenue_wan"] == pytest.approx(30768.67)


def test_parse_energy_ops_price_rejects_long_narrative_skip():
    """结算电价仅叙述段披露（数值在单位前、单位后跟长说明）→ 不跨长句
    误取后续年份/序号数字，price 如实为 None。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n10,000.00\n"
        "4\n结算电费\n元\n100,000,000.00\n"
        "本报告期平均结算电价为0.50 元/千瓦时(含税)，上年同期为0.48 元/"
        "千瓦时(含税)，同比上涨4.17%。据《2026 年电力交易方案》…\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["generation_wan_kwh"] == pytest.approx(10000.0)
    assert result["price_yuan_kwh"] is None


def test_parse_energy_ops_thousand_separators():
    """千分位数值（如 61,620.34）正常转数字。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n61,620.34\n"
        "2\n等效利用小时数\n小时\n527.00\n"
        "3\n结算电量\n万千瓦时\n60,688.10\n"
        "4\n结算电费\n元\n307,686,738.41\n"
        "5\n结算电价\n元/千瓦时\n0.57\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result["generation_wan_kwh"] == pytest.approx(61620.34)
    assert result["grid_wan_kwh"] == pytest.approx(60688.10)
    assert result["electricity_revenue_wan"] == pytest.approx(30768.67, abs=0.01)


def test_parse_energy_ops_billion_kwh_unit():
    """发电量/结算电量单位「亿千瓦时」→ 折算万千瓦时（×10000）。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "1\n发电量\n亿千瓦时\n5.22\n"
        "2\n等效利用小时数\n小时\n700.00\n"
        "3\n结算电量\n亿千瓦时\n5.10\n"
        "4\n结算电费\n元\n400,000,000.00\n"
        "5\n结算电价\n元/千瓦时\n0.80\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["generation_wan_kwh"] == pytest.approx(52200.0)
    assert result["grid_wan_kwh"] == pytest.approx(51000.0)


def test_parse_energy_ops_revenue_billion_yuan_unit():
    """结算电费单位「亿元」→ 折算万元（×10000），不断行与断行「亿 元」均可。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n10,000.00\n"
        "2\n等效利用小时数\n小时\n500.00\n"
        "3\n结算电量\n万千瓦时\n9,800.00\n"
        "4\n结算电费\n亿元\n0.20\n"
        "5\n结算均价\n元/千瓦时\n0.80\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["electricity_revenue_wan"] == pytest.approx(2000.0)


def test_parse_energy_ops_label_variants_aggregate():
    """标签变体：「等效利用小时」（无数后缀）「结算均价」（光伏/水电口径）。"""
    text = (
        "4.1.2 报告期以及上年同期不动产项目整体运营指标\n"
        "1\n发电量\n亿千瓦时\n5.22\n"
        "2\n等效利用小时\n小时\n700.00\n"
        "3\n结算电量\n亿千瓦时\n5.10\n"
        "4\n结算电费\n亿元\n0.84\n"
        "5\n结算均价\n元/千瓦时\n0.79\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["utilization_hours"] == pytest.approx(700.0)
    assert result["electricity_revenue_wan"] == pytest.approx(8400.0)
    assert result["price_yuan_kwh"] == pytest.approx(0.79)


def test_parse_energy_ops_no_generation_returns_none():
    """无发电量字段（非能源类，如高速/生态环保季报）→ 返回 None。"""
    text = (
        "某高速公路封闭式基础设施证券投资基金2026年第2季度报告\n"
        "3.1 主要财务指标\n"
        "1.本期收入\n30,650,710.62\n"
        "2.本期净利润\n-11,644,536.88\n"
    )
    assert parser_ops_energy.parse_energy_ops_text(text) is None


def test_parse_energy_ops_no_table_returns_none():
    """能源类但无 4.1.3 运营指标表（叙述段披露）→ 无发电量行 → None。"""
    text = (
        "某新能源封闭式基础设施证券投资基金2026年第2季度报告\n"
        "4.1 报告期内不动产项目的运营情况\n"
        "报告期内，发电量为 6,547.91 万千瓦时，上网电量 6,426.65 万千瓦时，"
        "结算电费 3,752.07 万元。\n"
    )
    assert parser_ops_energy.parse_energy_ops_text(text) is None


def test_parse_energy_ops_partial_fields_are_none():
    """有发电量但其余字段缺失 → 缺失字段如实为 None，仍返回 dict。"""
    text = (
        "4.1.3 报告期及上年同期重要不动产项目运营指标\n"
        "1\n发电量\n万千瓦时\n61,620.34\n"
    )
    result = parser_ops_energy.parse_energy_ops_text(text)

    assert result is not None
    assert result["generation_wan_kwh"] == pytest.approx(61620.34)
    assert result["utilization_hours"] is None
    assert result["grid_wan_kwh"] is None
    assert result["electricity_revenue_wan"] is None
    assert result["price_yuan_kwh"] is None
    assert result["ops_until_year"] is None


def test_market_ops_energy_row_schema_from_real_pdf():
    """批量行结构：code/period 由调用方补充，运营指标字段为数值。"""
    result = parser_ops_energy.parse_energy_ops(REAL_PDF)
    row = {"code": "180401", "period": "2026Q2", **result}

    assert row["code"] == "180401"
    assert row["period"] == "2026Q2"
    for key in ENERGY_KEYS:
        if key == "ops_until_year":
            assert isinstance(row[key], int)
        else:
            assert isinstance(row[key], (int, float))
