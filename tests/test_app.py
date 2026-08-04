"""app.py 看板的 AppTest 冒烟测试。

通过 streamlit.testing.v1.AppTest 直接运行看板脚本，验证：
- 应用可无异常运行；
- 三个页签存在：经营数据 / 行情走势 / 分析规则；
- 分析规则页签正常渲染（可供分配对标与背离检测表格）。

网络行情通过 monkeypatch 让 akshare 调用失败，走 market_data 的降级路径，
避免冒烟测试触发真实网络请求。
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.market_data as md

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

TAB_LABELS = ["📈 经营数据", "📉 行情走势", "📐 分析规则"]


@pytest.fixture
def no_network(monkeypatch):
    """让 akshare 调用抛出异常，行情模块降级为空数据。"""

    def boom(*args, **kwargs):
        raise ConnectionError("test: network down")

    monkeypatch.setattr(md.ak, "reits_realtime_em", boom)
    monkeypatch.setattr(md.ak, "reits_hist_em", boom)


def test_app_runs_with_three_tabs(no_network):
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
