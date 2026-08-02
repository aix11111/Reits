"""tools.reits_collector.sse 模块（上交所 REITs 公告接口封装）的单元测试。

通过 monkeypatch 替换 requests.post / requests.get，
避免发起真实网络请求。覆盖公告列表（含自动翻页）与 PDF 下载路径。
"""

import requests
import pytest

from tools.reits_collector import sse

QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
PDF_BASE_URL = "https://www.sse.com.cn"
REFERER = "https://www.sse.com.cn/disclosure/fund/reits/"


class FakeResponse:
    """伪造 requests 响应：携带 json / status_code / content。"""

    def __init__(self, json_data=None, status_code=200, content=b"pdf-bytes"):
        self._json_data = json_data
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._json_data


def make_item(title="公告标题", sse_date="2026-07-21"):
    return {
        "title": title,
        "sseDate": sse_date,
        "url": "/disclosure/fund/announcement/c/new/2026-07-21/508001_20260721_JR6B.pdf",
        "fundExtAbbr": "华安张江光大园",
        "bulletinType": "公告",
        "securityCode": "508001",
    }


def test_list_announcements_returns_items_with_required_keys(monkeypatch):
    sent = {}
    item = make_item()

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["data"] = kwargs.get("data")
        sent["headers"] = kwargs.get("headers")
        return FakeResponse(
            json_data={
                "success": "true",
                "pageHelp": {"total": 1, "pageCount": 1, "pageNo": 1, "data": [item]},
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    items = sse.list_announcements("508001", "2026-07-01", "2026-07-31")

    assert items == [item]
    assert sent["url"] == QUERY_URL
    assert sent["headers"].get("Referer") == REFERER
    assert sent["headers"].get("User-Agent")
    payload = sent["data"] or {}
    assert payload.get("sqlId") == "REITS_BULLETIN"
    assert payload.get("fundCode") == "508001"
    assert payload.get("startDate") == "2026-07-01"
    assert payload.get("endDate") == "2026-07-31"
    assert payload.get("pageHelp.pageSize") == 25
    assert payload.get("pageHelp.pageNo") == 1
    assert payload.get("isPagination") == "true"


def test_list_announcements_accepts_custom_page_size(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent["data"] = kwargs.get("data")
        return FakeResponse(
            json_data={
                "success": "true",
                "pageHelp": {"total": 0, "pageCount": 0, "pageNo": 1, "data": []},
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    sse.list_announcements("508001", "2026-07-01", "2026-07-31", page_size=50)

    payload = sent["data"] or {}
    assert payload.get("pageHelp.pageSize") == 50


def test_list_announcements_auto_paginates_all_pages(monkeypatch):
    requested_pages = []

    def fake_post(url, **kwargs):
        page_no = int(kwargs["data"]["pageHelp.pageNo"])
        requested_pages.append(page_no)
        pages = {
            1: [make_item("第一条"), make_item("第二条")],
            2: [make_item("第三条")],
        }
        return FakeResponse(
            json_data={
                "success": "true",
                "pageHelp": {
                    "total": 3,
                    "pageCount": 2,
                    "pageNo": page_no,
                    "data": pages.get(page_no, []),
                },
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    items = sse.list_announcements("508001", "2026-07-01", "2026-07-31")

    assert [i["title"] for i in items] == ["第一条", "第二条", "第三条"]
    assert requested_pages == [1, 2]


def test_list_announcements_raises_on_api_error(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(json_data={"success": "false", "msg": "查询失败"})

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(RuntimeError) as excinfo:
        sse.list_announcements("508001", "2026-07-01", "2026-07-31")
    assert "查询失败" in str(excinfo.value)


def test_list_announcements_raises_on_network_error(monkeypatch):
    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("无法连接上交所")

    monkeypatch.setattr(requests, "post", boom)

    with pytest.raises(RuntimeError) as excinfo:
        sse.list_announcements("508001", "2026-07-01", "2026-07-31")
    assert "无法连接上交所" in str(excinfo.value)


def test_download_pdf_writes_bytes_to_dest(monkeypatch, tmp_path):
    sent = {}

    def fake_get(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs.get("headers")
        return FakeResponse(status_code=200, content=b"%PDF-1.7 test")

    monkeypatch.setattr(requests, "get", fake_get)

    url_path = "/disclosure/fund/announcement/c/new/2026-07-21/508001.pdf"
    dest = tmp_path / "ann.pdf"
    result = sse.download_pdf(url_path, dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF-1.7 test"
    assert sent["url"] == PDF_BASE_URL + url_path
    assert sent["headers"].get("Referer") == REFERER
    assert sent["headers"].get("User-Agent")


def test_download_pdf_raises_on_non_200(monkeypatch, tmp_path):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=404, content=b"not found"),
    )

    with pytest.raises(RuntimeError):
        sse.download_pdf("/disclosure/fund/announcement/c/new/a.pdf", tmp_path / "a.pdf")


def test_download_pdf_raises_on_empty_content(monkeypatch, tmp_path):
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kwargs: FakeResponse(status_code=200, content=b""),
    )

    with pytest.raises(RuntimeError):
        sse.download_pdf("/disclosure/fund/announcement/c/new/a.pdf", tmp_path / "a.pdf")


def test_download_pdf_raises_on_network_error(monkeypatch, tmp_path):
    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("连接失败")

    monkeypatch.setattr(requests, "get", boom)

    with pytest.raises(RuntimeError) as excinfo:
        sse.download_pdf("/disclosure/fund/announcement/c/new/a.pdf", tmp_path / "a.pdf")
    assert "连接失败" in str(excinfo.value)
