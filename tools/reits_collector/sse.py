"""上交所（SSE）REITs 公告接口封装：公告列表查询与公告 PDF 下载。

上交所公告接口通过证券代码直接查询，无需机构检索；
网络异常、接口错误或下载失败统一抛出 RuntimeError 并附带原因，
便于上层捕获与提示。
"""

from pathlib import Path

import requests

QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
PDF_BASE_URL = "https://www.sse.com.cn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.sse.com.cn/disclosure/fund/reits/",
}


def list_announcements(
    code: str,
    date_from: str,
    date_to: str,
    page_size: int = 25,
) -> list[dict]:
    """按证券代码与日期区间查询公告列表，自动翻页拉取全部，返回公告 dict 列表。

    每项含 title / sseDate / url / fundExtAbbr / bulletinType / securityCode。
    """
    items: list[dict] = []
    page_no = 1
    while True:
        data = {
            "isPagination": "true",
            "pageHelp.pageSize": page_size,
            "pageHelp.pageNo": page_no,
            "pageHelp.beginPage": 1,
            "pageHelp.cacheSize": 1,
            "pageHelp.endPage": 1,
            "sqlId": "REITS_BULLETIN",
            "fundCode": code,
            "startDate": date_from,
            "endDate": date_to,
            "order": "sseDate|desc,securityCode|asc,id|asc",
        }
        try:
            resp = requests.post(QUERY_URL, data=data, headers=HEADERS, timeout=30)
            result = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"查询公告列表失败：{exc}") from exc

        # 真实接口：正常响应无 success 字段（仅错误响应带 success=false）
        if result.get("success") == "false":
            msg = result.get("msg") or "接口返回错误"
            raise RuntimeError(f"查询公告列表失败：{msg}")

        page_help = result.get("pageHelp") or {}
        items.extend(page_help.get("data") or [])
        page_count = page_help.get("pageCount") or 0

        if page_no >= page_count or page_count == 0:
            break
        page_no += 1

    return items


def download_pdf(url_path: str, dest: Path) -> Path:
    """下载公告 PDF 并写入 dest，返回 dest 路径。

    url_path 为接口返回的相对路径，内部拼接 PDF_BASE_URL 前缀。
    """
    url = f"{PDF_BASE_URL}{url_path}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
    except requests.RequestException as exc:
        raise RuntimeError(f"下载公告失败：{exc}") from exc

    if resp.status_code != 200 or not resp.content:
        raise RuntimeError(f"下载公告失败：HTTP {resp.status_code} 或内容为空")

    dest.write_bytes(resp.content)
    return dest
