# -*- coding: utf-8 -*-
"""分享对象模型与 stoken 获取。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config
from .session import ApiError, GuestSession

PWD_ID_RE = re.compile(r"(?:drive\.uc\.cn|drive\.quark\.cn|pan\.uc\.cn)/s/([0-9a-zA-Z]+)")
INITIAL_PROPS_RE = re.compile(r"window\.__INITIAL_PROPS__\s*=\s*(\{.*?\})\s*</script>", re.S)


def parse_pwd_id(text: str) -> str:
    """从分享链接或裸 pwd_id 中取出 pwd_id。"""
    text = text.strip()
    m = PWD_ID_RE.search(text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9a-zA-Z]{8,32}", text):
        return text
    raise ValueError(f"无法解析分享标识: {text!r}")


@dataclass
class ShareRef:
    """一个分享的访问凭据集合。"""

    pwd_id: str
    stoken: str
    share_id: str = ""
    title: str = ""
    passcode: str = ""
    first_fid: str = ""
    file_num: int = 0
    all_file_num: int = 0
    size: int = 0
    url_type: int = 1
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ssr(cls, pwd_id: str, session: GuestSession) -> "ShareRef":
        """方案 A（首选）：从移动端 SSR 页面内联的 __INITIAL_PROPS__ 取 stoken。

        桌面 UA 只会拿到一个 2KB 的 SPA 壳；移动 UA 才直出完整初始状态。
        """
        html = session.fetch_html(config.SHARE_PAGE.format(pwd_id=pwd_id))
        m = INITIAL_PROPS_RE.search(html)
        if not m:
            raise ApiError("SSR 页面未找到 __INITIAL_PROPS__（可能分享已失效或页面改版）")
        props = json.loads(m.group(1))
        data = props.get("initialData") or {}
        st = (data.get("stokenDetail") or {}).get("stoken")
        share = ((data.get("shareDetail") or {}).get("share")) or {}
        if not st:
            raise ApiError("初始状态中无 stoken")
        return cls(
            pwd_id=pwd_id,
            stoken=st,
            share_id=share.get("share_id", ""),
            title=share.get("title", ""),
            passcode=share.get("passcode", "") or "",
            first_fid=share.get("first_fid", ""),
            file_num=share.get("file_num", 0) or 0,
            all_file_num=share.get("all_file_num", 0) or 0,
            size=share.get("size", 0) or 0,
            url_type=share.get("url_type", 1) or 1,
            raw=share,
        )

    @classmethod
    def from_token_api(cls, pwd_id: str, passcode: str, session: GuestSession) -> "ShareRef":
        """方案 B（兜底）：/share/sharepage/token。

        实测该接口对部分分享直接返回 15000 inner error，仅作兼容保留。
        """
        data = session.post(
            config.ENDPOINTS["share_token"], {"pwd_id": pwd_id, "passcode": passcode}
        )
        st = data.get("stoken") or (data.get("data") or {}).get("stoken")
        if not st:
            raise ApiError("token 接口未返回 stoken")
        return cls(pwd_id=pwd_id, stoken=st, passcode=passcode, raw=data)

    @classmethod
    def resolve(cls, target: str, session: GuestSession, passcode: str = "") -> "ShareRef":
        pwd_id = parse_pwd_id(target)
        try:
            ref = cls.from_ssr(pwd_id, session)
        except (ApiError, ValueError, KeyError):
            ref = cls.from_token_api(pwd_id, passcode, session)
        if passcode:
            ref.passcode = passcode
        return ref


@dataclass
class Entry:
    """目录项 / 文件项。"""

    fid: str
    name: str
    is_dir: bool
    size: int
    fid_token: str = ""
    path: str = ""
    fmt: str = ""
    obj_category: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, d: Dict[str, Any], parent: str = "") -> "Entry":
        name = d.get("file_name") or ""
        return cls(
            fid=d.get("fid", ""),
            name=name,
            is_dir=bool(d.get("dir")),
            size=int(d.get("size") or 0),
            fid_token=d.get("share_fid_token") or "",
            path=(parent.rstrip("/") + "/" + name) if parent else name,
            fmt=d.get("format_type") or "",
            obj_category=d.get("obj_category") or "",
            raw=d,
        )


def iter_entries(entries: List[Entry]) -> List[Entry]:
    return [e for e in entries if not e.is_dir]
