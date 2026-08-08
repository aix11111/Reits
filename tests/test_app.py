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
    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    asset_box.select("全部").run()
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
    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    asset_box.select("全部").run()
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
    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    asset_box.select("全部").run()
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
    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
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


# ---------------------------------------------------------------------------
# Phase 6c（M6c）：生态环保类运营指标 + 经营 Tab 处理量 KPI
# ---------------------------------------------------------------------------


def test_operations_tab_env_kpi_renders_for_env_fund(no_network, monkeypatch):
    """环保类基金（有处理量数据）在经营数据页签渲染「处理量」KPI 卡；
    无处理量数据的基金不显示占位、不崩。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static = pd.DataFrame(
        {
            "code": ["508006", "508001"],
            "name": ["富国首创水务REIT", "浙商沪杭甬REIT"],
            "asset": ["生态环保", "高速"],
            "region": ["安徽", "浙江"],
            "mileage_km": [None, 100],
            "listing_date": ["2021-06-07", "2021-06-29"],
            "issue_scale_yi": [18, 43],
            "concession_years_left": [None, 20],
            "asset_type": ["生态环保", "高速"],
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

    env = pd.DataFrame(
        {
            "code": ["508006", "508006"],
            "period": ["2026Q1", "2026Q2"],
            "volume_wan_ton": [2200.0, 2277.81],
            "capacity_utilization_pct": [80.0, 83.44],
            "unit_price_yuan": [1.28, 1.298],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_ops_environment", lambda path=None: env, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("508006").run()
    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "处理量" in cards[0]
    assert "2,277.81" in cards[0]

    # 无处理量数据（高速基金）→ 不显示处理量占位、不崩
    box.select("508001").run()
    assert not at.exception
    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert all("处理量" not in c for c in cards)


def test_operations_tab_env_kpi_renders_capacity_and_price(no_network, monkeypatch):
    """环保类 KPI 卡含产能利用率与服务费单价（最新报告期 83.44% / 1.2980 元/吨）。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static = pd.DataFrame(
        {
            "code": ["508006"],
            "name": ["富国首创水务REIT"],
            "asset": ["生态环保"],
            "region": ["安徽"],
            "mileage_km": [None],
            "listing_date": ["2021-06-07"],
            "issue_scale_yi": [18],
            "concession_years_left": [None],
            "asset_type": ["生态环保"],
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

    env = pd.DataFrame(
        {
            "code": ["508006"],
            "period": ["2026Q2"],
            "volume_wan_ton": [2277.81],
            "capacity_utilization_pct": [83.44],
            "unit_price_yuan": [1.298],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_ops_environment", lambda path=None: env, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("508006").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "83.44%" in cards[0]
    assert "1.2980" in cards[0]


# ---------------------------------------------------------------------------
# Phase 5.1（M5.1）：全市场联动导航（资产类型 → 基金选择器 / 经营数据 / 状态墙）
# ---------------------------------------------------------------------------


def test_selector_default_highway_and_energy_linked(no_network, monkeypatch):
    """联动：默认「高速」→ 选择器 14 只静态高速；选「能源」→ options 含
    能源基金 180401、不含高速 180201。"""
    import streamlit as st

    _patch_market_data_with_energy(monkeypatch)
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not at.exception
    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    assert asset_box.value == "高速"
    fund_box = next(b for b in at.selectbox if b.label == "选择REIT")
    assert len(fund_box.options) == 14

    asset_box.select("能源").run()
    assert not at.exception
    fund_box = next(b for b in at.selectbox if b.label == "选择REIT")
    options = [o.split(" ")[0] for o in fund_box.options]
    assert "180401" in options
    assert "180201" not in options


def test_operations_tab_non_highway_no_quarterly_degrade(no_network, monkeypatch):
    """经营数据 Tab：非高速基金无季度数据 → st.info「该资产类型暂无数据」。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    funds = pd.DataFrame(
        {
            "code": ["180402"],
            "name": ["测试能源REIT"],
            "asset_type": ["能源"],
        }
    )
    empty_quarterly = pd.DataFrame(columns=["code", "period", "distributable_wan"])
    monkeypatch.setattr(
        dl, "load_market_funds", lambda path=None: funds, raising=False
    )
    monkeypatch.setattr(
        dl, "load_market_quarterly", lambda path=None: empty_quarterly, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    asset_box = next(b for b in at.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
    fund_box = next(b for b in at.selectbox if b.label == "选择REIT")
    fund_box.select("180402").run()

    assert not at.exception
    infos = [i.value for i in at.tabs[0].info]
    assert any("该资产类型暂无数据" in v for v in infos)


# ---------------------------------------------------------------------------
# 高速 KPI 缺数字修复：total_cost_wan 解析 + NAV 改年报净值
# ---------------------------------------------------------------------------


def _mock_quarterly_for(code, name):
    """单只基金季度数据（含 total_cost_wan；nav_wan 列留空——不再使用）。"""
    import pandas as pd

    static = pd.DataFrame(
        {
            "code": [code],
            "name": [name],
            "asset": ["高速"],
            "region": ["广东"],
            "mileage_km": [100],
            "listing_date": ["2021-01-01"],
            "issue_scale_yi": [90],
            "concession_years_left": [20],
            "asset_type": ["高速"],
        }
    )
    monthly = pd.DataFrame(
        columns=["period", "code", "name", "toll_revenue_wan", "daily_traffic"]
    )
    quarterly = pd.DataFrame(
        {
            "period": ["2026Q2"],
            "code": [code],
            "name": [name],
            "total_revenue_wan": [16539.13],
            "total_cost_wan": [23043.99],
            "net_profit_wan": [3032.10],
            "distributable_wan": [9917.02],
            "ebitda_wan": [13618.28],
            "nav_wan": [float("nan")],
            "source": ["测试"],
        }
    )
    return static, monthly, quarterly


def test_operations_tab_kpi_noi_and_yield_filled_for_180201(no_network, monkeypatch):
    """高速 180201：NOI 利润率与年化可供分配收益率不再是「—」。

    成本取自季报 4.2.1（mock quarterly total_cost_wan）；NAV 改用
    annual_completion.json 中 180201 的最新年报净值（860066.41 万）。
    """
    import json
    import streamlit as st

    import src.data_loader as dl

    static, monthly, quarterly = _mock_quarterly_for("180201", "平安广州广河REIT")
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": monthly, "quarterly": quarterly},
        raising=False,
    )

    completion = json.loads(
        (DATA_PATH / "annual_completion.json").read_text(encoding="utf-8")
    )["completion"]
    nav_180201 = next(
        r["nav_wan"] for r in completion if str(r["code"]) == "180201"
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("180201").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "NOI利润率" in cards[0]
    assert "年化可供分配收益率" in cards[0]
    assert f"{(16539.13 - 23043.99) / 16539.13:.1%}" in cards[0]
    assert f"{9917.02 * 4 / nav_180201:.1%}" in cards[0]


def test_operations_tab_yield_uses_market_completion_nav(no_network, monkeypatch):
    """NAV 不在 annual_completion.json 的基金（508069）：年化收益率用
    market_completion.json 年报净值；有值不再显示「—」。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static, monthly, quarterly = _mock_quarterly_for("508069", "华夏南京交通高速公路REIT")
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": monthly, "quarterly": quarterly},
        raising=False,
    )
    completion = pd.DataFrame(
        {
            "code": ["508069"],
            "name": ["华夏南京交通高速公路REIT"],
            "year": [2024],
            "predicted_wan": [None],
            "actual_wan": [None],
            "completion_pct": [None],
            "status": [None],
            "nav_unit_price": [5.4798],
            "nav_wan": [273988.58],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_completion", lambda path=None: completion, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("508069").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "年化可供分配收益率" in cards[0]
    assert f"{9917.02 * 4 / 273988.58:.1%}" in cards[0]


def test_operations_tab_kpi_yield_dash_when_no_nav(no_network, monkeypatch):
    """无任何年报净值来源的基金（508020）：年化可供分配收益率保留「—」、
    不抛异常；NOI 利润率有成本时仍有值。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    static, monthly, quarterly = _mock_quarterly_for("508020", "平安合肥高新REIT")
    monkeypatch.setattr(
        dl,
        "load_all",
        lambda path=None: {"static": static, "monthly": monthly, "quarterly": quarterly},
        raising=False,
    )
    monkeypatch.setattr(
        dl, "load_market_completion", lambda path=None: pd.DataFrame(), raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    box = next(b for b in at.selectbox if b.label == "选择REIT")
    box.select("508020").run()
    assert not at.exception
    cards = [m.value for m in at.tabs[0].markdown if "reit-kpi-card" in m.value]
    assert "年化可供分配收益率" in cards[0]
    assert f"{(16539.13 - 23043.99) / 16539.13:.1%}" in cards[0]


# ---------------------------------------------------------------------------
# Phase 7（M7）：资产类型联动基金选择器（全市场导航）
# ---------------------------------------------------------------------------


def _energy_fund_options(at):
    """返回侧边栏「选择REIT」下拉框当前 options（格式化后的显示文本）。"""
    return next(b for b in at.sidebar.selectbox if b.label == "选择REIT").options


def test_fund_selector_links_to_asset_type_energy(no_network):
    """资产类型选「能源」→ 基金选择器 options 变为能源基金列表（含 180401）；
    高速基金 180201 不在 options 中。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    asset_box = next(b for b in at.sidebar.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
    assert not at.exception

    options = [o.split(" ")[0] for o in _energy_fund_options(at)]
    assert "180401" in options
    assert "508015" in options
    assert "180201" not in options


def test_operations_tab_non_highway_fund_renders_quarterly_with_placeholder(
    no_network,
):
    """选中非高速基金（能源 180401）→ 经营数据 Tab 渲染季度表，
    月度区块显示「该资产类型暂无月度披露」（原月度图表位置）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    asset_box = next(b for b in at.sidebar.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
    assert not at.exception

    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    fund_box.select("180401").run()
    assert not at.exception

    ops_tab = at.tabs[0]
    subheaders = [s.value for s in ops_tab.subheader]
    assert "季度经营明细" in subheaders

    infos = [i.value for i in ops_tab.info]
    assert any("该资产类型暂无月度披露" in v for v in infos)

    marks = [m.value for m in ops_tab.markdown]
    assert all("通行费收入" not in m for m in marks)

    frames = [df.value for df in ops_tab.dataframe]
    assert any("报告期" in f.columns for f in frames)


def test_fund_selector_honest_warning_when_market_funds_missing(no_network, monkeypatch):
    """market_funds.json 缺失 → 选非高速类型出现 st.warning（含「全市场基金数据缺失」）、
    选择器无可选项（不静默回退）；选「高速」无 warning、14 只照常。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(
        dl,
        "load_market_funds",
        lambda path=None: pd.DataFrame(columns=["code", "name", "asset_type"]),
        raising=False,
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    # 高速：无 warning、14 只高速照常
    asset_box = next(b for b in at.sidebar.selectbox if b.label == "资产类型")
    asset_box.select("高速").run()
    assert not at.exception
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    assert len(fund_box.options) == 14
    assert all("全市场基金数据缺失" not in w.value for w in at.sidebar.warning)

    # 非高速类型：如实 warning + 选择器无可选项，不是静默回退
    asset_box.select("能源").run()
    assert not at.exception
    warnings = [w.value for w in at.sidebar.warning]
    assert any("全市场基金数据缺失" in v for v in warnings)
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    assert len(fund_box.options) == 0


def test_non_highway_type_without_funds_shows_info(no_network, monkeypatch):
    """market_funds 存在但该非高速类型无基金 → st.info「该资产类型暂无数据」、
    选择器无可选项；不显示「全市场基金数据缺失」warning。"""
    import pandas as pd
    import streamlit as st

    import src.data_loader as dl

    funds = pd.DataFrame(
        {
            "code": ["180201"],
            "name": ["平安广州广河REIT"],
            "asset_type": ["高速"],
        }
    )
    monkeypatch.setattr(
        dl, "load_market_funds", lambda path=None: funds, raising=False
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    asset_box = next(b for b in at.sidebar.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
    assert not at.exception

    infos = [i.value for i in at.sidebar.info]
    assert any("该资产类型暂无数据" in v for v in infos)
    assert all("全市场基金数据缺失" not in w.value for w in at.sidebar.warning)
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    assert len(fund_box.options) == 0


def test_status_wall_follows_asset_type_energy(no_network):
    """状态墙跟随资产类型：选「能源」→ 色点带渲染能源基金（含 180401）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    asset_box = next(b for b in at.sidebar.selectbox if b.label == "资产类型")
    asset_box.select("能源").run()
    assert not at.exception

    wall = next(m.value for m in at.markdown if "reit-status-wall" in m.value)
    assert "1804" in wall
    assert "180201" not in wall


# ---------------------------------------------------------------------------
# Task 5（HK）：市场维度（中国/香港）+ 香港视图
# ---------------------------------------------------------------------------


def _select_hk(at):
    """把侧边栏「市场」下拉切到「香港」并重跑。"""
    box = next(b for b in at.sidebar.selectbox if b.label == "市场")
    box.select("香港").run()


def test_title_contains_multi_market(no_network):
    """标题升级：st.title 含「多市场」。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception
    assert "多市场" in at.title[0].value


def test_hk_market_fund_selector_lists_hk_funds(no_network):
    """市场选香港 → 基金选择器 options = HK 清单（含 00823 领展）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_hk(at)
    assert not at.exception
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    options = [o.split(" ")[0] for o in fund_box.options]
    assert "00823" in options


def test_hk_operations_tab_renders_hk_kpis(no_network):
    """市场选香港 → 经营数据 Tab 渲染 HK 指标 KPI 卡（含 DPU / NPI 文案）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "DPU" in cards[0]
    assert "NPI" in cards[0]


def test_hk_operations_tab_lists_annual_and_interim(no_network):
    """经营数据 Tab：00823 领展财务摘要表显示年度+中期两行并标注报告类型，
    KPI 卡显示最新报告（interim 2025H1 优先）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    fund_box.select("00823").run()
    assert not at.exception

    ops_tab = at.tabs[0]
    frames = [df.value for df in ops_tab.dataframe]
    summary = next(f for f in frames if "报告类型" in f.columns)
    assert len(summary) == 2
    assert set(summary["报告类型"]) == {"年度", "中期"}
    assert "2025H1" in summary["财务年"].values

    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert "2025H1" in cards[0]


def _hk_annual_by_code():
    """读 data/hk_annual.json 为 {code: annual rec}（估值对标仅用年报口径）。"""
    annual = json.loads((DATA_PATH / "hk_annual.json").read_text(encoding="utf-8"))[
        "annual"
    ]
    result = {}
    for r in annual:
        if r.get("period", "annual") == "annual":
            result[str(r["code"])] = r
    return result


def test_hk_valuation_tab_renders_yield_ranking(no_network):
    """市场选香港 → 估值 Tab 渲染「分派收益率」排名表（多行）。

    排名表含全量基金；有效收益率（DPU 与市价均非空）行数 = 实跑数据；
    领展 00823 收益率 = hk_distribution_yield(253.61, 38.78) ≈ 6.5%，非「—」。
    """
    import streamlit as st

    from src.valuation import hk_distribution_yield

    funds = json.loads((DATA_PATH / "hk_funds.json").read_text(encoding="utf-8"))[
        "funds"
    ]
    snapshot = json.loads(
        (DATA_PATH / "hk_market_snapshot.json").read_text(encoding="utf-8")
    )["latest"]
    annual_by_code = _hk_annual_by_code()
    valid_codes = [
        code
        for code in annual_by_code
        if annual_by_code[code].get("dpu_hk_cents") is not None
        and snapshot.get(code) is not None
    ]

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派收益率" in f.columns)
    assert len(rank) == len(funds)
    valid_rows = rank[rank["分派收益率"] != "—"]
    assert len(valid_rows) == len(valid_codes)

    link = valid_rows[valid_rows["基金代码"] == "00823"]
    assert link["分派收益率"].iloc[0] == f"{hk_distribution_yield(253.61, 38.78):.1%}"

    # 财年标注列存在
    assert "财年" in rank.columns

    # 横向条形图渲染（青绿主色 + 中位数虚线）
    assert len(val_tab.get("plotly_chart")) >= 1


def test_hk_valuation_tab_premium_table_semantic(no_network):
    """估值 Tab P/NAV 折溢价表：全量基金、00823 折价、NAV 缺失显示「—」。"""
    import streamlit as st

    from src.valuation import hk_nav_premium

    funds = json.loads((DATA_PATH / "hk_funds.json").read_text(encoding="utf-8"))[
        "funds"
    ]
    annual_by_code = _hk_annual_by_code()

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    premium = next(f for f in frames if "折溢价" in f.columns)
    assert len(premium) == len(funds)

    link = premium[premium["基金代码"] == "00823"]
    assert link["折溢价"].iloc[0] == pytest.approx(hk_nav_premium(38.78, 57.75))

    missing_nav = {
        code for code, rec in annual_by_code.items() if rec.get("nav_per_unit_hkd") is None
    }
    missing_rows = premium[premium["基金代码"].isin(missing_nav)]
    assert not missing_rows.empty
    assert missing_rows["折溢价"].isna().all()
    assert missing_rows["单位NAV(港元)"].isna().all()


def test_hk_valuation_tab_degrades_when_yield_data_insufficient(
    no_network, monkeypatch
):
    """有效分派收益率少于 3 只 → st.info「香港分派数据不足」。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(
        dl,
        "load_hk_annual",
        lambda path=None: {
            "00405": [
                {"period": "annual", "fiscal_year": "2025", "dpu_hk_cents": 3.33}
            ],
            "00823": [
                {
                    "period": "annual",
                    "fiscal_year": "2025/26",
                    "dpu_hk_cents": 253.61,
                }
            ],
            "01426": [
                {"period": "annual", "fiscal_year": "2025", "dpu_hk_cents": None}
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        dl,
        "load_hk_snapshot",
        lambda path=None: {"00405": 0.68, "00823": 38.78, "01426": 1.18},
        raising=False,
    )

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    infos = [i.value for i in at.tabs[3].info]
    assert any("香港分派数据不足" in v for v in infos)


def test_hk_valuation_tab_degrades_when_snapshot_missing(no_network, monkeypatch):
    """行情快照缺失 → 估值 Tab st.info「香港数据缺失」，不崩。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(dl, "load_hk_snapshot", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    infos = [i.value for i in at.tabs[3].info]
    assert any("香港数据缺失" in v for v in infos)


def test_hk_market_tab_shows_price_snapshot(no_network):
    """市场选香港 → 行情 Tab 显示港股价格快照（选中 00823 领展，最新价 38.78）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    fund_box.select("00823").run()
    assert not at.exception

    mkt_tab = at.tabs[1]
    marks = [m.value for m in mkt_tab.markdown]
    assert any("00823" in m and "38.78" in m for m in marks)


def test_hk_rules_tab_shows_placeholder(no_network):
    """市场选香港 → 分析规则 Tab 显示「香港模块分析规则建设中」（不崩）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    rules_tab = at.tabs[2]
    infos = [i.value for i in rules_tab.info]
    assert any("香港模块分析规则建设中" in v for v in infos)


def test_hk_status_wall_renders_gray_dots(no_network):
    """市场选香港 → 状态墙渲染香港基金灰点（全量，含 00823 后四位 0823）。"""
    import json
    import streamlit as st

    funds_file = DATA_PATH / "hk_funds.json"
    expected = len(json.loads(funds_file.read_text(encoding="utf-8"))["funds"])

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_hk(at)
    assert not at.exception

    wall = next(m.value for m in at.markdown if "reit-status-wall" in m.value)
    assert wall.count("reit-dot") == expected
    assert "#4B5563" in wall
    assert "0823" in wall


def test_hk_mode_degrades_when_json_missing(no_network, monkeypatch):
    """hk_funds/hk_annual/hk_market_snapshot 缺失 → 对应 Tab st.info「香港数据缺失」不崩。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(dl, "load_hk_funds", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_hk_annual", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_hk_snapshot", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_hk(at)
    assert not at.exception
    infos = [i.value for i in at.tabs[0].info]
    assert any("香港数据缺失" in v for v in infos)


# ---------------------------------------------------------------------------
# Task SG：市场维度（中国/香港/新加坡）+ 新加坡视图（CICT）
# ---------------------------------------------------------------------------


def _select_sg(at):
    """把侧边栏「市场」下拉切到「新加坡」并重跑。"""
    box = next(b for b in at.sidebar.selectbox if b.label == "市场")
    box.select("新加坡").run()


def _sg_annual_by_code():
    """读 data/sg_annual.json 为 {code: annual rec}（估值对标仅用年报口径）。"""
    annual = json.loads((DATA_PATH / "sg_annual.json").read_text(encoding="utf-8"))[
        "annual"
    ]
    result = {}
    for r in annual:
        if r.get("period", "annual") == "annual":
            result[str(r["code"])] = r
    return result


def test_market_options_include_singapore(no_network):
    """侧边栏「市场」含新加坡/美国；默认仍为中国（零变化）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception
    box = next(b for b in at.sidebar.selectbox if b.label == "市场")
    assert box.options == ["中国", "香港", "新加坡", "美国"]
    assert box.value == "中国"


def test_sg_market_fund_selector_lists_sg_funds(no_network):
    """市场选新加坡 → 基金选择器 options = SG 清单（含 C38U）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_sg(at)
    assert not at.exception
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    options = [o.split(" ")[0] for o in fund_box.options]
    assert "C38U" in options


def test_sg_operations_tab_renders_sg_kpis(no_network):
    """市场选新加坡 → 经营数据 Tab 渲染 SG 指标 KPI 卡（含 Revenue / SGD 币种标注）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_sg(at)
    assert not at.exception

    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "Revenue" in cards[0]
    assert "Distributable Income" in cards[0]
    assert "SGD" in cards[0]


def test_sg_valuation_tab_renders_yield_ranking(no_network):
    """市场选新加坡 → 估值 Tab 渲染「分派收益率」排名表，C38U 收益率按实跑数据≈4.7%。"""
    import streamlit as st

    from src.valuation import hk_distribution_yield

    snapshot = json.loads(
        (DATA_PATH / "sg_market_snapshot.json").read_text(encoding="utf-8")
    )["latest"]
    annual_by_code = _sg_annual_by_code()
    dpu = annual_by_code["C38U"]["dpu_cents"]
    price = snapshot["C38U"]
    expected_yield = f"{hk_distribution_yield(dpu, price):.1%}"

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_sg(at)
    assert not at.exception

    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "分派收益率" in f.columns)
    c38u = rank[rank["基金代码"] == "C38U"]
    assert c38u["分派收益率"].iloc[0] == expected_yield
    assert "财年" in rank.columns


def test_sg_valuation_tab_renders_pnav_and_npi_margin(no_network):
    """估值 Tab：P/NAV 折溢价表 + NPI 利润率排名表（C38U 折溢价 ≈ +15%）。"""
    import streamlit as st

    from src.valuation import hk_nav_premium

    snapshot = json.loads(
        (DATA_PATH / "sg_market_snapshot.json").read_text(encoding="utf-8")
    )["latest"]
    annual_by_code = _sg_annual_by_code()
    rec = annual_by_code["C38U"]
    price = snapshot["C38U"]

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_sg(at)
    assert not at.exception

    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]

    premium = next(f for f in frames if "折溢价" in f.columns)
    c38u_prem = premium[premium["基金代码"] == "C38U"]
    assert c38u_prem["折溢价"].iloc[0] == pytest.approx(
        hk_nav_premium(price, rec["nav_per_unit"])
    )

    npi = next(f for f in frames if "NPI利润率" in f.columns)
    c38u_npi = npi[npi["基金代码"] == "C38U"]
    assert c38u_npi["NPI利润率"].iloc[0] == f"{rec['npi_wan'] / rec['revenue_wan']:.1%}"


def test_sg_mode_degrades_when_json_missing(no_network, monkeypatch):
    """sg_funds/sg_annual/sg_market_snapshot 缺失 → 各 Tab st.info「新加坡数据缺失」不崩。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(dl, "load_sg_funds", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_sg_annual", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_sg_snapshot", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_sg(at)
    assert not at.exception
    infos = [i.value for i in at.tabs[0].info]
    assert any("新加坡数据缺失" in v for v in infos)


# ---------------------------------------------------------------------------
# Task US：市场维度（中国/香港/新加坡/美国）+ 美国视图（20 只美股 REITs）
# ---------------------------------------------------------------------------


def _select_us(at):
    """把侧边栏「市场」下拉切到「美国」并重跑。"""
    box = next(b for b in at.sidebar.selectbox if b.label == "市场")
    box.select("美国").run()


def test_market_options_include_us(no_network):
    """侧边栏「市场」含美国；默认仍为中国（零变化）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception
    box = next(b for b in at.sidebar.selectbox if b.label == "市场")
    assert box.options == ["中国", "香港", "新加坡", "美国"]
    assert box.value == "中国"


def test_us_market_fund_selector_lists_us_funds(no_network):
    """市场选美国 → 基金选择器 options = US 清单（含 PLD Prologis）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_us(at)
    assert not at.exception
    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    options = [o.split(" ")[0] for o in fund_box.options]
    assert "PLD" in options
    assert "PLD Prologis" in fund_box.options


def test_us_operations_tab_renders_us_kpis(no_network):
    """市场选美国 → 经营数据 Tab 渲染 US 指标 KPI 卡（FY/Revenue/NOI/FFO/
    每股股息/出租率，USD 币种标注）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_us(at)
    assert not at.exception

    ops_tab = at.tabs[0]
    cards = [m.value for m in ops_tab.markdown if "reit-kpi-card" in m.value]
    assert len(cards) == 1
    assert "FY" in cards[0]
    assert "Revenue" in cards[0]
    assert "NOI" in cards[0]
    assert "FFO" in cards[0]
    assert "每股股息" in cards[0]
    assert "出租率" in cards[0]
    assert "USD" in cards[0]


def test_us_operations_tab_lists_annual_summary(no_network):
    """经营数据 Tab：选中 PLD → 财务摘要表渲染 Prologis 记录（每股股息 USD 列）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_us(at)
    assert not at.exception

    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    fund_box.select("PLD").run()
    assert not at.exception

    ops_tab = at.tabs[0]
    subheaders = [s.value for s in ops_tab.subheader]
    assert any("Prologis" in s for s in subheaders)
    frames = [df.value for df in ops_tab.dataframe]
    summary = next(f for f in frames if "每股股息(USD)" in f.columns)
    assert len(summary) == 1
    assert summary["财务年"].iloc[0] == "2025"


def test_us_valuation_tab_renders_yield_ranking(no_network):
    """市场选美国 → 估值 Tab 渲染「股息率」排名表。

    排名表含全量基金；PLD 股息率 = 4.04/140.16 ≈ 2.9%（按实跑数据）；
    P/FFO 列 ffo 有值的 3 只显示、其余「—」；横向条形图渲染。
    """
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_us(at)
    assert not at.exception

    val_tab = at.tabs[3]
    frames = [df.value for df in val_tab.dataframe]
    rank = next(f for f in frames if "股息率" in f.columns)
    assert len(rank) == 20
    assert "财年" in rank.columns
    assert "P/FFO" in rank.columns

    pld = rank[rank["基金代码"] == "PLD"]
    assert pld["股息率"].iloc[0] == "2.9%"

    with_ffo = rank[rank["P/FFO"] != "—"]
    assert set(with_ffo["基金代码"]) == {"ESS", "EXR", "WELL"}

    assert len(val_tab.get("plotly_chart")) >= 1


def test_us_market_tab_shows_price_snapshot(no_network):
    """市场选美国 → 行情 Tab 显示美股价格快照（选中 PLD 最新价 140.16）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_us(at)
    assert not at.exception

    fund_box = next(b for b in at.sidebar.selectbox if b.label == "选择REIT")
    fund_box.select("PLD").run()
    assert not at.exception

    mkt_tab = at.tabs[1]
    marks = [m.value for m in mkt_tab.markdown]
    assert any("PLD" in m and "140.16" in m for m in marks)


def test_us_rules_tab_shows_placeholder(no_network):
    """市场选美国 → 分析规则 Tab 显示「美国模块分析规则建设中」（不崩）。"""
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _select_us(at)
    assert not at.exception

    rules_tab = at.tabs[2]
    infos = [i.value for i in rules_tab.info]
    assert any("美国模块分析规则建设中" in v for v in infos)


def test_us_mode_degrades_when_json_missing(no_network, monkeypatch):
    """us_funds/us_annual/us_market_snapshot 缺失 → 各 Tab st.info「美国数据缺失」不崩。"""
    import streamlit as st

    import src.data_loader as dl

    monkeypatch.setattr(dl, "load_us_funds", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_us_annual", lambda path=None: {}, raising=False)
    monkeypatch.setattr(dl, "load_us_snapshot", lambda path=None: {}, raising=False)

    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception

    _select_us(at)
    assert not at.exception
    infos = [i.value for i in at.tabs[0].info]
    assert any("美国数据缺失" in v for v in infos)
