"""港交所（HKEX）年报直链下载封装。

通过 HKEXNews 直链下载年报 PDF：requests + UA，流式写入 dest。
网络失败 / 写入失败统一抛出 RuntimeError 并附带原因，便于上层捕获与提示。
"""

from pathlib import Path

import requests

HKEX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def download_annual_report(url: str, dest: Path) -> Path:
    """下载 HKEX 年报 PDF 并流式写入 dest，返回 dest 路径。"""
    try:
        resp = requests.get(url, headers={"User-Agent": HKEX_UA}, timeout=60)
        if resp.status_code != 200 or not resp.content:
            raise RuntimeError(f"下载年报失败：HTTP {resp.status_code} 或内容为空")
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise RuntimeError(f"下载年报失败：{exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"写入年报失败：{exc}") from exc
    return dest
