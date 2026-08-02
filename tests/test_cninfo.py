"""tools.reits_collector.cninfo 模块（巨潮资讯接口封装）的单元测试。

通过 monkeypatch 替换 requests.post / requests.get，
避免发起真实网络请求。覆盖三个接口的正常路径与网络异常路径。
"""

import requests
import pytest

from tools.reits_collector import cninfo

TOP_SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
HIS_ANNOUNCEMENT_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
REFERER = "http://www.cninfo.com.cn/"


class FakeResponse:
    """伪造 requests 响应：携带 json / status_code / content。"""

    def __init__(self, json_data=None, status_code=200, content=b"pdf-bytes"):
        self._json_data = json_data
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._json_data


def test_search_org_id_returns_first_org_id(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["data"] = kwargs.get("data")
        sent["params"] = kwargs.get("params")
        return FakeResponse(
            json_data=[{"code": "180201", "orgId": "gssz0180201"}]
        )

    monkeypatch.setattr(requests, "post", fake_post)

    org_id = cninfo.search_org_id("180201")

    assert org_id == "gssz0180201"
    assert sent["url"] == TOP_SEARCH_URL
    payload = sent["data"] or sent["params"] or {}
    assert payload.get("keyWord") == "180201"


def test_search_org_id_raises_when_no_result(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kwargs: FakeResponse(json_data=[]),
    )

    with pytest.raises(RuntimeError):
        cninfo.search_org_id("180201")


def test_search_org_id_raises_on_network_error(monkeypatch):
    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("无法连接巨潮资讯")

    monkeypatch.setattr(requests, "post", boom)

    with pytest.raises(RuntimeError) as excinfo:
        cninfo.search_org_id("180201")
    assert "无法连接巨潮资讯" in str(excinfo.value)


def test_list_announcements_returns_items_with_required_keys(monkeypatch):
    sent = {}
    item = {
        "announcementTitle": "关于二〇二六年六月主要运营数据的公告",
        "adjunctUrl": "/new/details/1.html",
        "announcementTime": 1780000000000,
    }

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["data"] = kwargs.get("data")
        sent["params"] = kwargs.get("params")
        sent["headers"] = kwargs.get("headers")
        return FakeResponse(json_data={"announcements": [item]})

    monkeypatch.setattr(requests, "post", fake_post)

    items = cninfo.list_announcements(
        "180201", "gssz0180201", "2026-06-01", "2026-06-30"
    )

    assert items == [item]
    assert sent["url"] == HIS_ANNOUNCEMENT_URL
    payload = sent["data"] or sent["params"] or {}
    assert payload.get("stock") == "180201,gssz0180201"
    assert payload.get("seDate") == "2026-06-01~2026-06-30"
    assert payload.get("pageNum") == 1
    assert payload.get("pageSize") == 100
    assert payload.get("tabName") == "fulltext"
    assert sent["headers"].get("Referer") == REFERER
    assert sent["headers"].get("User-Agent")


def test_list_announcements_accepts_custom_page_size(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent["params"] = kwargs.get("params")
        sent["data"] = kwargs.get("data")
        return FakeResponse(json_data={"announcements": []})

    monkeypatch.setattr(requests, "post", fake_post)

    cninfo.list_announcements(
        "180201", "gssz0180201", "2026-06-01", "2026-06-30", page_size=50
    )

    payload = sent["data"] or sent["params"] or {}
    assert payload.get("pageSize") == 50


def test_list_announcements_paginates_over_pages(monkeypatch):
    """跨多页公告应逐页拉取并合并，而非只取第一页。"""
    sent_pages = []

    def fake_post(url, **kwargs):
        payload = kwargs.get("data") or kwargs.get("params") or {}
        page_num = payload.get("pageNum")
        sent_pages.append(page_num)
        if page_num == 1:
            return FakeResponse(
                json_data={
                    "totalAnnouncement": 3,
                    "totalpages": 2,
                    "announcements": [
                        {
                            "announcementTitle": "公告一",
                            "adjunctUrl": "/new/details/1.html",
                            "announcementTime": 1780000000000,
                        },
                        {
                            "announcementTitle": "公告二",
                            "adjunctUrl": "/new/details/2.html",
                            "announcementTime": 1780000001000,
                        },
                    ],
                }
            )
        return FakeResponse(
            json_data={
                "announcements": [
                    {
                        "announcementTitle": "公告三",
                        "adjunctUrl": "/new/details/3.html",
                        "announcementTime": 1780000002000,
                    }
                ]
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    items = cninfo.list_announcements(
        "180201", "gssz0180201", "2026-06-01", "2026-06-30"
    )

    assert [item["announcementTitle"] for item in items] == [
        "公告一",
        "公告二",
        "公告三",
    ]
    assert sent_pages == [1, 2]


def test_list_announcements_raises_on_network_error(monkeypatch):
    def boom(url, **kwargs):
        raise requests.exceptions.Timeout("请求超时")

    monkeypatch.setattr(requests, "post", boom)

    with pytest.raises(RuntimeError) as excinfo:
        cninfo.list_announcements(
            "180201", "gssz0180201", "2026-06-01", "2026-06-30"
        )
    assert "请求超时" in str(excinfo.value)


def test_download_pdf_writes_bytes_to_dest(monkeypatch, tmp_path):
    sent = {}

    def fake_get(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs.get("headers")
        return FakeResponse(status_code=200, content=b"%PDF-1.4 test")

    monkeypatch.setattr(requests, "get", fake_get)

    dest = tmp_path / "ann.pdf"
    result = cninfo.download_pdf("http://www.cninfo.com.cn/new/ann.pdf", dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF-1.4 test"
    assert sent["url"] == "http://www.cninfo.com.cn/new/ann.pdf"
    assert sent["headers"].get("Referer") == REFERER
    assert sent["headers"].get("User-Agent")


def test_download_pdf_raises_on_non_200(monkeypatch, tmp_path):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=404, content=b"not found"),
    )

    with pytest.raises(RuntimeError):
        cninfo.download_pdf("http://www.cninfo.com.cn/new/ann.pdf", tmp_path / "a.pdf")


def test_download_pdf_raises_on_empty_content(monkeypatch, tmp_path):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=200, content=b""),
    )

    with pytest.raises(RuntimeError):
        cninfo.download_pdf("http://www.cninfo.com.cn/new/ann.pdf", tmp_path / "a.pdf")


def test_download_pdf_raises_on_network_error(monkeypatch, tmp_path):
    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("连接失败")

    monkeypatch.setattr(requests, "get", boom)

    with pytest.raises(RuntimeError) as excinfo:
        cninfo.download_pdf("http://www.cninfo.com.cn/new/ann.pdf", tmp_path / "a.pdf")
    assert "连接失败" in str(excinfo.value)
