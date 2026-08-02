"""巨潮资讯（cninfo）接口封装：机构检索、公告列表查询与公告 PDF 下载。

全部接口通过 requests 发起 HTTP 请求；网络异常、无结果或下载失败
统一抛出 RuntimeError 并附带原因，便于上层捕获与提示。
"""

from pathlib import Path

import requests

MAX_PAGES = 50

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
    巨潮单页上限 30 条：pageSize 超过 30 时服务端分页失效
    （pageNum 被忽略，每页都返回第一页内容），故 page_size 内部 clamp 到 30。
    翻页终止采用自适应：逐页拉取直到某页返回空列表或条数不足一页
    （不足一页说明已到最后一页），不依赖 totalpages 字段——该字段向下取整，
    在末页不满时会漏拉。最多翻 MAX_PAGES 页以防响应异常时死循环。
    """
    effective_page_size = min(page_size, 30)
    url = f"{BASE_URL}/new/hisAnnouncement/query"
    base_params = {
        "stock": f"{code},{org_id}",
        "seDate": f"{date_from}~{date_to}",
        "pageSize": effective_page_size,
        "tabName": "fulltext",
    }
    items: list[dict] = []
    total_pages_hint = 1
    page_num = 1
    while page_num <= MAX_PAGES:
        params = dict(base_params, pageNum=page_num)
        try:
            resp = requests.post(url, params=params, headers=HEADERS, timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"查询公告列表失败：{exc}") from exc

        if page_num == 1:
            total_pages_hint = int(data.get("totalpages") or 1)
        announcements = data.get("announcements", [])
        if not announcements:
            break
        items.extend(announcements)
        if len(announcements) < effective_page_size and page_num >= total_pages_hint:
            break
        page_num += 1

    return items


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
