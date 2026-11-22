# -*- coding: utf-8 -*-
"""下载层：分块并发 + 断链重取 + 双编码 MD5 校验。"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, Tuple

import requests

from . import config
from .api import DownloadTarget, ShareClient
from .session import ApiError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """Windows 下安全化文件名：去非法字符、尾点尾空格、保留名。"""
    out = _ILLEGAL.sub("_", name).rstrip(" .")
    stem = out.split(".")[0].upper()
    if stem in _RESERVED:
        out = "_" + out
    return out or "_"


def safe_rel(path: str) -> str:
    return os.sep.join(safe_name(p) for p in path.split("/") if p not in ("", "."))


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_file(path: str, bufsize: int = 1024 * 1024) -> str:
    """流式计算，避免把上百 MB 读进内存。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_expected(exp: str) -> str:
    """服务端 md5 字段有双编码：zip 给 base64，rar 给裸 hex。统一成 hex。"""
    exp = (exp or "").strip()
    if not exp:
        return ""
    if len(exp) == 32 and all(c in "0123456789abcdefABCDEF" for c in exp):
        return exp.lower()
    try:
        raw = base64.b64decode(exp, validate=True)
    except Exception:
        return ""
    return raw.hex() if len(raw) == 16 else ""


class Downloader:
    def __init__(self, client: ShareClient, jobs: int = config.DEFAULT_JOBS,
                 chunk: int = config.DEFAULT_CHUNK, retries: int = 6,
                 log: Callable[[str], None] = print):
        self.c = client
        self.jobs = max(1, jobs)
        self.chunk = max(256 * 1024, chunk)
        self.retries = retries
        self.log = log
        self._cookie = ""

    # ---------- 传输 ----------

    def _refresh_cookie(self) -> str:
        """__pugs 由 file/download 下发，取链后刷新一次即可。"""
        self._cookie = self.c.s.cdn_cookies()
        return self._cookie

    def _fetch(self, url: str, start: int, end: int) -> bytes:
        last = ""
        for attempt in range(self.retries):
            try:
                r = requests.get(
                    url,
                    headers={
                        "User-Agent": config.UA_DESKTOP,
                        "Cookie": self._cookie,
                        "Referer": "https://drive.uc.cn/",
                        "Range": f"bytes={start}-{end}",
                    },
                    timeout=240,
                )
                if r.status_code in (200, 206):
                    return r.content
                last = f"HTTP {r.status_code}"
                if r.status_code in (401, 403):
                    break  # 链接过期或护照失效，交给上层重取
            except requests.RequestException as e:
                last = repr(e)[:80]
            time.sleep(0.8 * (attempt + 1))
        raise ApiError(f"分块失败 {start}-{end}: {last}")

    def _fetch_all(self, target: DownloadTarget) -> bytes:
        size = target.size
        ranges: List[Tuple[int, int]] = [
            (s, min(s + self.chunk - 1, size - 1)) for s in range(0, size, self.chunk)
        ]
        with ThreadPoolExecutor(max_workers=self.jobs) as ex:
            parts = list(ex.map(lambda rg: self._fetch(target.url, *rg), ranges))
        data = b"".join(parts)
        if len(data) != size:
            raise ApiError(f"长度不符: {len(data)} != {size}")
        return data

    # ---------- 对外 ----------

    def fetch_blob(self, target: DownloadTarget) -> bytes:
        try:
            return self._fetch_all(target)
        except ApiError:
            # 直链带 Expires（约 1h）且绑定护照，过期后重取一次
            self.log(f"  重取直链: {target.name}")
            fresh = self.c.link_one(target.fid)
            target = fresh
            self._refresh_cookie()
            return self._fetch_all(target)

    def save(self, target: DownloadTarget, dest_path: str, expect_md5: str = "") -> Tuple[bool, str]:
        size_ok = (os.path.exists(dest_path) and os.path.getsize(dest_path) == target.size)
        if size_ok:
            exp = md5_expected(expect_md5 or target.md5)
            if not exp:
                return True, "skip"
            if md5_file(dest_path) == exp:
                return True, "skip"
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        self._refresh_cookie()
        t0 = time.time()
        data = self.fetch_blob(target)
        exp = md5_expected(expect_md5 or target.md5)
        got = md5_hex(data)
        if exp and got != exp:
            return False, f"md5 不符 expect={exp} got={got}"
        tmp = dest_path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest_path)
        dt = max(time.time() - t0, 0.01)
        self.log(f"  ok {target.name}  {target.size/1048576:.2f}MB  "
                 f"{target.size/1048576/dt:.2f}MB/s")
        return True, "ok"
