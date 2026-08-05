"""app.py 看板的 AppTest 冒烟测试。

通过 streamlit.testing.v1.AppTest 直接运行看板脚本，验证：
- 应用可无异常运行；
- 四个页签存在：经营数据 / 行情走势 / 分析规则 / 估值对标；
- 分析规则页签正常渲染（可供分配对标与背离检测表格）；
- 估值对标页签渲染收益率排名 / NAV 折溢价 / 风险提示，快照缺失时降级不崩溃。

网络行情通过 monkeypatch 让 akshare 调用失败，走 market_data 的降级路径，
避免冒烟测试触发真实网络请求。
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.market_data as md

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

DATA_PATH = Path(__file__).resolve().parents[1] / "data"

TAB_LABELS = ["📈 经营数据", "📉 行情走势", "📐 分析规则", "📊 估值对标"]


@pytest.fixture
def no_network(monkeypatch):
    """让 akshare 调用抛出异常，行情模块降级为空数据。"""

    def boom(*args, **kwargs):
        raise ConnectionError("test: network down")

    monkeypatch.setattr(md.ak, "reits_realtime_em", boom)
    monkeypatch.setattr(md.ak, "reits_hist_em", boom)


def test_app_runs_with_four_tabs(no_network):
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    assert [tab.label for tab in at.tabs] == TAB_LABELS


def test_analysis_rules_tab_renders_benchmark_and_divergence(no_network):
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception

    rules_tab = at.tabs[2]
    subheaders = [s.value for s in rules_tab.subheader]
    assert "分析规则引擎" in subheaders
    # 有可供分配对标 / 背离检测的展示内容
    assert len(rules_tab.dataframe) >= 1


def test_analysis_rules_tab_degrades_gracefully_when_data_empty(no_network, monkeypatch):
    """月度/季度数据为空时，分析规则页签以 info 提示降级、不崩溃。"""

    import pandas as pd

    import src.data_loader as dl

    def empty_load(path):
        return {
            "static": pd.DataFrame(
                {
                    "code": ["180201"],
                    "name": ["测试REIT"],
                    "asset": ["高速"],
                    "region": ["广东"],
                    "mileage_km": [100],
                    "listing_date": ["2021-01-01"],
                    "issue_scale_yi": [10],
                    "concession_years_left": [20],
                    "asset_type": ["特许经营权"],
                }
            ),
            "monthly": pd.DataFrame(
                columns=[
                    "period",
                    "code",
                    "name",
                    "toll_revenue_wan",
                    "daily_traffic",
                    "toll_revenue_yoy",
                    "traffic_yoy",
                    "source",
                ]
            ),
            "quarterly": pd.DataFrame(
                columns=[
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
            ),
        }

    monkeypatch.setattr(dl, "load_all", empty_load)

    import streamlit as st
    st.cache_data.clear()

    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    rules_tab = at.tabs[2]
    infos = [i.value for i in rules_tab.info]
    assert any("暂无月度数据" in v for v in infos)
    assert any("暂无季度数据" in v for v in infos)


def test_analysis_rules_tab_renders_completion_section(no_network):
    """分析规则页签渲染「可供分配完成度」第 5 节标题。"""
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    rules_tab = at.tabs[2]
    marks = [m.value for m in rules_tab.markdown]
    assert any("可供分配完成度" in m for m in marks)


def test_status_wall_renders_color_dots(no_network):
    """签名元素 1：状态墙用真实 annual_completion.json 渲染 14 只基金色点。

    完成度有记录的基金为三态色（达标绿/警告橙/风险红），无记录基金为灰。
    期望「有状态」数量按数据文件去重基金代码实时计算，避免硬编码漂移。
    """
    import json
    import streamlit as st

    completion_file = (
        Path(__file__).resolve().parents[1] / "data" / "annual_completion.json"
    )
    expected_status = len(
        {
            str(row["code"])
            for row in json.loads(completion_file.read_text(encoding="utf-8"))[
                "completion"
            ]
        }
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    wall = next(m.value for m in at.markdown if "reit-status-wall" in m.value)
    assert wall.count("reit-dot") == 14
    colored = sum(
        wall.count(c) for c in ("#10B981", "#FBBF24", "#F87171")
    )
    assert colored == expected_status
    assert "暂无完成度数据" in wall


def test_operations_tab_renders_terminal_kpi_cards(no_network):
    """签名元素 2：经营数据页签以 JetBrains Mono 终端读数 HTML 卡片渲染 4 个 KPI。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert cards[0].count("reit-kpi-card") == 4
    assert "JetBrains Mono" in cards[0]


def test_valuation_tab_renders_ranking_premium_and_risk(no_network):
    """估值对标页签：有市值快照时渲染收益率排名 / NAV 折溢价 / 风险提示区。"""
    import streamlit as st

    snapshot_file = DATA_PATH / "market_snapshot.json"
    expected_rows = len(
        json.loads(snapshot_file.read_text(encoding="utf-8"))["latest"]
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    val_tab = at.tabs[3]

    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)
    assert len(rank) == expected_rows

    premium = next(f for f in frames if "折溢价" in f.columns)
    assert not premium.empty

    warnings = [w.value for w in val_tab.warning]
    infos = [i.value for i in val_tab.info]
    assert warnings or any("暂无风险" in v for v in infos)


def test_valuation_tab_degrades_when_snapshot_missing(no_network, monkeypatch):
    """估值对标页签：市值快照缺失时降级为 st.info，不抛异常。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(dl, "load_market_snapshot", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    val_tab = at.tabs[3]
    infos = [i.value for i in val_tab.info]
    assert any("市值数据缺失" in v for v in infos)


# ---------------------------------------------------------------------------
# Task 5（M5）：租赁类基金经营数据 Tab 出租率 KPI
# ---------------------------------------------------------------------------


def test_operations_tab_rental_kpi_renders_for_rental_fund(no_network, monkeypatch):
    """租赁类基金（有出租率数据）在经营数据页签渲染「出租率」KPI 卡；
    其余 Tab 不崩；无出租率数据的基金不显示占位。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static = pd.DataFrame(
        {
            "code": ["180201", "508000"],
            "name": ["平安广州广河REIT", "华安张江产业园REIT"],
            "asset": ["高速", "产业园"],
            "region": ["广东", "上海"],
            "mileage_km": [100, None],
            "listing_date": ["2021-01-01", "2021-06-21"],
            "issue_scale_yi": [90, 15],
            "concession_years_left": [20, None],
            "asset_type": ["高速", "产业园"],
        }
    )
    empty = pd.DataFrame(
        columns=["period", "code", "name", "toll_revenue_wan", "daily_traffic"]
    )
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": empty, "quarterly": empty},
        raising=False,
    )

    rental = pd.DataFrame(
        {
            "code": ["508000", "508000"],
            "period": ["2026Q1", "2026Q2"],
            "occupancy_pct": [93.03, 88.12],
            "avg_rent_yuan": [5.48, 5.44],
            "collection_pct": [98.56, 100.0],
            "remaining_lease_days": [684.0, 554.0],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_ops_rental", lambda path=None: rental, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("508000").run()

    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "出租率" in cards[0]
    assert "88.12%" in cards[0]

    # 无出租率数据（高速基金）→ 不显示出租率占位、不崩
    box.select("180201").run()
    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert all("出租率" not in c for c in cards)


def test_operations_tab_rental_kpi_shows_rent_unit(no_network, monkeypatch):
    """出租率 KPI 卡平均租金按 rent_unit 标注单位：消费类「元/㎡/月」、
    产业园「元/㎡/天」；rent_unit 缺失时保持原「元/平/天」。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static = pd.DataFrame(
        {
            "code": ["180601", "508000"],
            "name": ["华夏华润消费REIT", "华安张江产业园REIT"],
            "asset": ["消费", "产业园"],
            "region": ["山东", "上海"],
            "mileage_km": [None, None],
            "listing_date": ["2024-03-14", "2021-06-21"],
            "issue_scale_yi": [30, 15],
            "concession_years_left": [None, None],
            "asset_type": ["消费", "产业园"],
        }
    )
    empty = pd.DataFrame(
        columns=["period", "code", "name", "toll_revenue_wan", "daily_traffic"]
    )
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": empty, "quarterly": empty},
        raising=False,
    )

    rental = pd.DataFrame(
        {
            "code": ["180601", "508000"],
            "period": ["2026Q2", "2026Q2"],
            "occupancy_pct": [99.08, 88.12],
            "avg_rent_yuan": [444.53, 5.44],
            "collection_pct": [100.0, 100.0],
            "remaining_lease_days": [None, 554.0],
            "rent_unit": ["yuan_per_sqm_month", "yuan_per_sqm_day"],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_ops_rental", lambda path=None: rental, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("180601").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "元/㎡/月" in cards[0]

    box.select("508000").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "元/㎡/天" in cards[0]


# ---------------------------------------------------------------------------
# Task 4（M4）：看板全市场视图
# ---------------------------------------------------------------------------


def _patch_market_data(monkeypatch):
    """把 data_loader 的市场 JSON 加载替换为全市场 fixture（2 产业园 + 1 高速）。"""
    import pandas as pd

    import src.data_loader as dl

    funds = pd.DataFrame(
        {
            "code": ["180101", "508000", "508001"],
            "name": ["博时蛇口产园REIT", "华安张江产业园REIT", "浙商沪杭甬REIT"],
            "asset_type": ["产业园", "产业园", "高速"],
        }
    )
    quarterly = pd.DataFrame(
        {
            "code": ["180101", "508000", "508001"],
            "period": ["2026Q1", "2026Q1", "2026Q1"],
            "distributable_wan": [2500.0, 3000.0, 4000.0],
        }
    )
    completion = pd.DataFrame(
        {
            "code": ["180101", "508000", "508001"],
            "name": ["博时蛇口产园REIT", "华安张江产业园REIT", "浙商沪杭甬REIT"],
            "year": [2025, 2025, 2025],
            "completion_pct": [95.0, 100.0, 90.0],
            "nav_unit_price": [2.5, 3.0, 6.0],
        }
    )
    shares = {"180101": 1000000000.0, "508000": 1000000000.0, "508001": 2000000000.0}
    snapshot = {
        "latest": {
            "180101": {"price": 2.6, "market_cap_wan": 260000.0},
            "508000": {"price": 3.1, "market_cap_wan": 310000.0},
            "508001": {"price": 6.5, "market_cap_wan": 1300000.0},
        },
        "snapshots": [],
    }
    monkeypatch.setattr(dl, "load_market_funds", lambda path=None: funds, raising=False)
    monkeypatch.setattr(
        dl, "load_market_quarterly", lambda path=None: quarterly, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_completion", lambda path=None: completion, raising=False
    )
    monkeypatch.setattr(dl, "load_market_shares", lambda path=None: shares, raising=False)
    monkeypatch.setattr(
        dl, "load_market_snapshot", lambda path=None: snapshot, raising=False
    )


def test_valuation_tab_full_market_rank_all_types(no_network, monkeypatch):
    """资产类型「全部」→ 估值排名表含全市场基金（含产业园 180101 / 508000）。"""
    import streamlit as st

    _patch_market_data(monkeypatch)
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)
    codes = set(rank["基金代码"])
    assert "180101" in codes
    assert "508000" in codes
    assert "508001" in codes


def test_valuation_tab_asset_type_filter_park(no_network, monkeypatch):
    """资产类型「产业园」→ 排名表仅产业园基金。"""
    import streamlit as st

    _patch_market_data(monkeypatch)
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "资产类型")
    box.select("产业园").run()

    assert not at.exception
    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)
    assert set(rank["基金代码"]) == {"180101", "508000"}
    assert (rank["资产类型"] == "产业园").all()


def test_valuation_tab_property_irr_not_applicable(no_network, monkeypatch):
    """产权类（产业园）基金特许经营 IRR 列显示「不适用（产权类）」。"""
    import streamlit as st

    _patch_market_data(monkeypatch)
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)
    park = rank[rank["基金代码"] == "180101"]
    assert park["特许经营IRR"].iloc[0] == "不适用（产权类）"


def test_valuation_tab_degraded_when_market_json_missing(no_network, monkeypatch):
    """market_*.json 缺失 → 估值 Tab 回退现有快照视图，其余 Tab 不回归。"""
    import pandas as pd

    import streamlit as st

    import src.data_loader as dl

    empty_funds = pd.DataFrame(columns=["code", "name", "asset_type"])
    empty_quarterly = pd.DataFrame(columns=["code", "period", "distributable_wan"])
    empty_completion = pd.DataFrame(
        columns=["code", "name", "year", "completion_pct", "nav_unit_price"]
    )
    monkeypatch.setattr(
        dl, "load_market_funds", lambda path=None: empty_funds, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_quarterly", lambda path=None: empty_quarterly, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_completion", lambda path=None: empty_completion, raising=False
    )
    monkeypatch.setattr(dl, "load_market_shares", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    assert [tab.label for tab in at.tabs] == TAB_LABELS
    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)
    assert not rank.empty


# ---------------------------------------------------------------------------
# Phase 6（M6）：能源类运营指标 + 能源 IRR
# ---------------------------------------------------------------------------


def _patch_market_data_with_energy(monkeypatch):
    """全市场 fixture：能源 180401（有 ops_until_year）+ 高速 508001。"""
    import pandas as pd

    import src.data_loader as dl

    funds = pd.DataFrame(
        {
            "code": ["180401", "508001"],
            "name": ["鹏华深圳能源REIT", "浙商沪杭甬REIT"],
            "asset_type": ["能源", "高速"],
        }
    )
    quarterly = pd.DataFrame(
        {
            "code": ["180401", "508001"],
            "period": ["2026Q1", "2026Q1"],
            "distributable_wan": [12500.0, 4000.0],
        }
    )
    completion = pd.DataFrame(
        {
            "code": ["180401", "508001"],
            "name": ["鹏华深圳能源REIT", "浙商沪杭甬REIT"],
            "year": [2025, 2025],
            "completion_pct": [100.0, 90.0],
            "nav_unit_price": [5.0, 6.0],
        }
    )
    shares = {"180401": 1_000_000_000.0, "508001": 2_000_000_000.0}
    snapshot = {
        "latest": {
            "180401": {"price": 5.0, "market_cap_wan": 500000.0},
            "508001": {"price": 6.5, "market_cap_wan": 1300000.0},
        },
        "snapshots": [],
    }
    energy = pd.DataFrame(
        {
            "code": ["180401"],
            "period": ["2026Q1"],
            "generation_wan_kwh": [61620.34],
            "utilization_hours": [527.0],
            "grid_wan_kwh": [60688.10],
            "electricity_revenue_wan": [30768.67],
            "price_yuan_kwh": [0.57],
            "ops_until_year": [2037],
        }
    )
    monkeypatch.setattr(dl, "load_market_funds", lambda path=None: funds, raising=False)
    monkeypatch.setattr(
        dl, "load_market_quarterly", lambda path=None: quarterly, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_completion", lambda path=None: completion, raising=False
    )
    monkeypatch.setattr(dl, "load_market_shares", lambda path=None: shares, raising=False)
    monkeypatch.setattr(
        dl, "load_market_snapshot", lambda path=None: snapshot, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_ops_energy", lambda path=None: energy, raising=False
    )


def test_valuation_tab_energy_irr_computed_from_ops_until_year(
    no_network, monkeypatch
):
    """能源类基金（有 ops_until_year）估值 IRR 列显示百分比而非「—」：
    years_left = ops_until_year − 2026（180401 → 2037−2026=11）。"""
    import streamlit as st

    _patch_market_data_with_energy(monkeypatch)
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派率收益率" in f.columns)

    energy_row = rank[rank["基金代码"] == "180401"]
    irr_label = energy_row["特许经营IRR"].iloc[0]
    assert isinstance(irr_label, str)
    assert irr_label != "—"
    assert irr_label != "不适用（产权类）"
    assert irr_label.endswith("%")


def test_operations_tab_energy_kpi_renders_for_energy_fund(no_network, monkeypatch):
    """能源类基金（有发电量数据）在经营数据页签渲染「发电量」KPI 卡；
    无发电量数据的基金不显示占位、不崩。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static = pd.DataFrame(
        {
            "code": ["180401", "508001"],
            "name": ["鹏华深圳能源REIT", "浙商沪杭甬REIT"],
            "asset": ["能源", "高速"],
            "region": ["广东", "浙江"],
            "mileage_km": [None, 100],
            "listing_date": ["2022-07-26", "2021-06-29"],
            "issue_scale_yi": [36, 43],
            "concession_years_left": [None, 20],
            "asset_type": ["能源", "高速"],
        }
    )
    empty = pd.DataFrame(
        columns=["period", "code", "name", "toll_revenue_wan", "daily_traffic"]
    )
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": empty, "quarterly": empty},
        raising=False,
    )

    energy = pd.DataFrame(
        {
            "code": ["180401", "180401"],
            "period": ["2026Q1", "2026Q2"],
            "generation_wan_kwh": [60000.0, 61620.34],
            "utilization_hours": [500.0, 527.0],
            "grid_wan_kwh": [59000.0, 60688.10],
            "electricity_revenue_wan": [30000.0, 30768.67],
            "price_yuan_kwh": [0.55, 0.57],
            "ops_until_year": [2037, 2037],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_ops_energy", lambda path=None: energy, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("180401").run()
    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "发电量" in cards[0]
    assert "61,620.34" in cards[0]

    # 无发电量数据（高速基金）→ 不显示发电量占位、不崩
    box.select("508001").run()
    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert all("发电量" not in c for c in cards)
