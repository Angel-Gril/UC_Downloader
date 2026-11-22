# -*- coding: utf-8 -*-
"""分享内容读写：目录遍历、取直链、压缩包预览。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

from . import config
from .session import ApiError, GuestSession
from .share import Entry, ShareRef

PAGE_SIZE = 100
SORT = "file_type:asc,file_name:asc"


@dataclass
class DownloadTarget:
    fid: str
    name: str
    size: int
    url: str
    md5: str = ""
    range_size: int = 0
    raw: Dict[str, Any] = None  # type: ignore[assignment]


class ShareClient:
    def __init__(self, ref: ShareRef, session: Optional[GuestSession] = None):
        self.ref = ref
        self.s = session or GuestSession()

    # ---------- 目录 ----------

    def list_dir(self, pdir_fid: str = "0", page: int = 1, size: int = PAGE_SIZE) -> Dict[str, Any]:
        params = {
            "pwd_id": self.ref.pwd_id,
            "stoken": self.ref.stoken,
            "pdir_fid": pdir_fid,
            "force": 0,
            "_page": page,
            "_size": size,
            "_fetch_banner": 1 if pdir_fid == "0" else 0,
            "_fetch_share": 1 if pdir_fid == "0" else 0,
            "_fetch_total": 1,
            "_sort": SORT,
        }
        return self.s.get(config.ENDPOINTS["share_detail"], params)

    def children(self, pdir_fid: str = "0") -> List[Entry]:
        """分页拉完一个目录的全部子项。"""
        out: List[Entry] = []
        page = 1
        while True:
            data = self.list_dir(pdir_fid, page)
            items = data.get("list") or []
            out.extend(Entry.from_api(i) for i in items)
            total = (data.get("metadata") or {}).get("_total", len(out))
            if not items or page * PAGE_SIZE >= total:
                return out
            page += 1

    def walk(self, pdir_fid: Optional[str] = None, sleep: float = 0.15) -> Iterator[Entry]:
        """深度优先遍历整棵分享树，产出带相对路径的条目。"""

        def rec(fid: str, prefix: str, depth: int) -> Iterator[Entry]:
            for e in self.children(fid):
                e.path = f"{prefix}/{e.name}" if prefix else e.name
                yield e
                if e.is_dir:
                    if sleep:
                        time.sleep(sleep)
                    yield from rec(e.fid, e.path, depth + 1)

        root = pdir_fid or self.ref.first_fid or "0"
        # 根目录本身是分享的入口文件夹时，从它内部开始
        yield from rec(root, "", 0)

    # ---------- 单文件 ----------

    def file_info(self, fid: str) -> Dict[str, Any]:
        return self.s.get(
            config.ENDPOINTS["file_info"],
            {"pwd_id": self.ref.pwd_id, "stoken": self.ref.stoken, "fid": fid},
        )

    # ---------- 直链 ----------

    def links(self, fids: List[str]) -> List[DownloadTarget]:
        """取签名直链。

        关键副作用：本次调用会让服务端 Set-Cookie: __pugs（游客护照）。
        因此把链接下发给 CDN 之前，必须读一次 client.s.guest_passport。
        """
        if not fids:
            return []
        data = self.s.post(
            config.ENDPOINTS["file_download"],
            {"fids": fids, "pwd_id": self.ref.pwd_id, "stoken": self.ref.stoken},
        )
        # 兼容两种返回形态：{"data":[...]} 或 [ ... ]
        rows = data if isinstance(data, list) else (data.get("list") or [])
        out: List[DownloadTarget] = []
        for d in rows:
            url = d.get("download_url")
            if not url:
                continue
            out.append(
                DownloadTarget(
                    fid=d.get("fid", ""),
                    name=d.get("file_name", ""),
                    size=int(d.get("size") or 0),
                    url=url,
                    md5=d.get("md5") or "",
                    range_size=int(d.get("range_size") or 0),
                    raw=d,
                )
            )
        return out

    def link_one(self, fid: str) -> DownloadTarget:
        got = self.links([fid])
        if not got:
            raise ApiError(f"未取得直链 fid={fid}")
        return got[0]

    # ---------- 压缩包 / 预览 ----------

    def archive_tree(self, fid: str, fid_token: str, page: int = 1, size: int = 50) -> Dict[str, Any]:
        """读取 zip/rar 内部条目（需 fid_token，服务端开启 sec_archive_preview 才行）。"""
        return self.s.post(
            config.ENDPOINTS["archive_tree"],
            {
                "pwd_id": self.ref.pwd_id,
                "stoken": self.ref.stoken,
                "fid": fid,
                "fid_token": fid_token,
                "_page": page,
                "_size": size,
            },
            timeout=60,
        )

    def preview(self, fid: str, fid_token: str) -> Dict[str, Any]:
        """图片/文档预览元信息。返回的 preview_url 是**缩略图**，不是原文件。"""
        return self.s.get(
            config.ENDPOINTS["preview"],
            {
                "pwd_id": self.ref.pwd_id,
                "stoken": self.ref.stoken,
                "fid_list": fid,
                "fid_token_list": fid_token,
            },
        )
