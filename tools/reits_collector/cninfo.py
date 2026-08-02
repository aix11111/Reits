"""巨潮资讯（cninfo）接口封装：机构检索、公告列表查询与公告 PDF 下载。

全部接口通过 requests 发起 HTTP 请求；网络异常、无结果或下载失败
统一抛出 RuntimeError 并附带原因，便于上层捕获与提示。
"""

from pathlib import Path

import requests

BASE_URL = "http://www.cninfo.com.cn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "http://www.cninfo.com.cn/",
}


def search_org_id(code: str) -> str:
    """按证券代码检索机构 orgId，返回列表第一项的 orgId。"""
    url = f"{BASE_URL}/new/information/topSearch/query"
    try:
        resp = requests.post(url, data={"keyWord": code}, headers=HEADERS, timeout=30)
        rows = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"查询机构 orgId 失败：{exc}") from exc

    if not rows or not rows[0].get("orgId"):
        raise RuntimeError(f"未找到代码 {code} 对应的机构")
    return rows[0]["orgId"]


def list_announcements(
    code: str,
    org_id: str,
    date_from: str,
    date_to: str,
    page_size: int = 100,
) -> list[dict]:
    """按代码、机构与日期区间查询公告列表，返回公告 dict 列表。

    每项含 announcementTitle / adjunctUrl / announcementTime（毫秒）。
    """
    url = f"{BASE_URL}/new/hisAnnouncement/query"
    params = {
        "stock": f"{code},{org_id}",
        "seDate": f"{date_from}~{date_to}",
        "pageNum": 1,
        "pageSize": page_size,
        "tabName": "fulltext",
    }
    try:
        resp = requests.post(url, params=params, headers=HEADERS, timeout=30)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"查询公告列表失败：{exc}") from exc

    return data.get("announcements", [])


def download_pdf(url: str, dest: Path) -> Path:
    """下载公告 PDF 并写入 dest，返回 dest 路径。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
    except requests.RequestException as exc:
        raise RuntimeError(f"下载公告失败：{exc}") from exc

    if resp.status_code != 200 or not resp.content:
        raise RuntimeError(f"下载公告失败：HTTP {resp.status_code} 或内容为空")

    dest.write_bytes(resp.content)
    return dest
