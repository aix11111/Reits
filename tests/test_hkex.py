"""tools.reits_collector.hkex 模块（港交所 HKEX 年报直链下载封装）的单元测试。

通过 monkeypatch 替换 requests.get，避免发起真实网络请求。
覆盖成功写文件、异常传播（非 200 / 网络失败 / 写失败），
以及 data/hk_funds.json 清单可加载且含领展条目。
"""

import json
from pathlib import Path

import pytest
import requests

from tools.reits_collector import hkex

ANNUAL_URL = "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0616/2025061600521.pdf"
HK_FUNDS_PATH = Path(__file__).resolve().parents[1] / "data" / "hk_funds.json"


class FakeResponse:
    """伪造 requests 响应：携带 status_code / content / iter_content。"""

    def __init__(self, status_code=200, content=b"%PDF-1.4 hkex"):
        self.status_code = status_code
        self.content = content

    def iter_content(self, chunk_size=8192):
        yield self.content


def test_hkex_ua_matches_spec():
    assert hkex.HKEX_UA == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def test_download_annual_report_writes_pdf_to_dest(monkeypatch, tmp_path):
    sent = {}

    def fake_get(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs.get("headers")
        sent["timeout"] = kwargs.get("timeout")
        return FakeResponse(status_code=200, content=b"%PDF-1.4 hkex")

    monkeypatch.setattr(requests, "get", fake_get)

    dest = tmp_path / "ann.pdf"
    result = hkex.download_annual_report(ANNUAL_URL, dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF-1.4 hkex"
    assert sent["url"] == ANNUAL_URL
    assert sent["headers"].get("User-Agent") == hkex.HKEX_UA
    assert sent["timeout"] == 60


def test_download_annual_report_raises_on_non_200(monkeypatch, tmp_path):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=404, content=b"not found"),
    )

    with pytest.raises(RuntimeError):
        hkex.download_annual_report(ANNUAL_URL, tmp_path / "a.pdf")


def test_download_annual_report_raises_on_network_error(monkeypatch, tmp_path):
    def boom(url, **kwargs):
        raise requests.exceptions.Timeout("连接超时")

    monkeypatch.setattr(requests, "get", boom)

    with pytest.raises(RuntimeError) as excinfo:
        hkex.download_annual_report(ANNUAL_URL, tmp_path / "a.pdf")
    assert "连接超时" in str(excinfo.value)


def test_download_annual_report_raises_on_write_error(monkeypatch, tmp_path):
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError):
        hkex.download_annual_report(ANNUAL_URL, tmp_path / "no_dir" / "a.pdf")


def test_hk_funds_json_loads_with_link_reit():
    data = json.loads(HK_FUNDS_PATH.read_text(encoding="utf-8"))
    funds = data["funds"]
    assert isinstance(funds, list) and len(funds) >= 1

    link = next(f for f in funds if f["code"] == "00823")
    assert link["name"] == "领展房产基金"
    assert link["name_en"] == "Link REIT"
    assert link["market"] == "HK"
    assert link["annual_url"] == ANNUAL_URL
    assert link["fiscal_year_end"] == "0331"
