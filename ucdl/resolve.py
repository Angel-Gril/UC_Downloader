# -*- coding: utf-8 -*-
"""解析层：把「分享内的一个文件」解析成**可在本程序之外直接使用**的下载描述。

关键认知：UC 的直链不是自足的。
    URL 只证明"有权取这个对象"，真正放行的是 CDN 回调里的 __pugs 会话票据。
    所以对外交付的最小单元是 (url, headers) 二元组，而不是 url。

因此本模块的产物可以喂给 aria2 / curl / IDM / 任何 HTTP 客户端，
不需要再运行本项目做传输。
"""

from __future__ import annotations

import json
import time
import urllib.parse as up
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from . import config
from .api import ShareClient
from .share import Entry


@dataclass
class Resolved:
    """一个可直接下载的目标：链接 + 必需请求头 + 元信息。"""

    fid: str
    path: str
    name: str
    size: int
    md5: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    expires_at: int = 0        # 直链过期时刻（unix 秒），0 表示未解析出
    range_size: int = 0

    @property
    def expires_in(self) -> int:
        return max(0, self.expires_at - int(time.time())) if self.expires_at else 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["expires_in"] = self.expires_in
        return d


def _expires_from_url(url: str) -> int:
    try:
        qs = dict(up.parse_qsl(up.urlsplit(url).query, keep_blank_values=True))
        return int(qs.get("Expires", 0))
    except (ValueError, TypeError):
        return 0


def resolve_entry(client: ShareClient, entry: Entry) -> Resolved:
    """解析单个条目。调用会让会话取得 __pugs，随后把 cookie 一并打包进 headers。"""
    tgt = client.link_one(entry.fid)
    # 必须在 link_one 之后读取：__pugs 是那次响应下发的
    cookie = client.s.cdn_cookies()
    headers = {
        "Cookie": cookie,
        "User-Agent": config.UA_DESKTOP,
        "Referer": "https://drive.uc.cn/",
    }
    return Resolved(
        fid=entry.fid,
        path=entry.path or entry.name,
        name=entry.name,
        size=tgt.size or entry.size,
        md5=tgt.md5,
        url=tgt.url,
        headers=headers,
        expires_at=_expires_from_url(tgt.url),
        range_size=tgt.range_size,
    )


# ---------- 输出格式 ----------


def to_text(r: Resolved) -> str:
    lines = [r.url]
    lines += [f"{k}: {v}" for k, v in r.headers.items()]
    return "\n".join(lines)


def to_curl(r: Resolved) -> str:
    parts = ["curl", "-L", "-C", "-", "-o", _shell_quote(r.name)]
    for k, v in r.headers.items():
        parts += ["-H", _shell_quote(f"{k}: {v}")]
    parts.append(_shell_quote(r.url))
    return " ".join(parts)


def _shell_quote(s: str) -> str:
    if not s:
        return "''"
    if all(c.isalnum() or c in "-._/:=" for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def to_aria2(r: Resolved, out_dir: str = "") -> str:
    """aria2 输入文件单条：URI 行 + 缩进选项行。"""
    lines = [r.url]
    for k, v in r.headers.items():
        lines.append(f"  header={k}: {v}")
    if out_dir:
        lines.append(f"  dir={out_dir}")
    out_name = r.path.replace("\\", "/") or r.name   # 保留分享内相对路径，避免同名覆盖
    lines.append(f"  out={out_name}")
    return "\n".join(lines)


def to_powershell(r: Resolved) -> str:
    h = "; ".join(f"'{k}'='{v.replace(chr(39), chr(39) * 2)}'" for k, v in r.headers.items())
    return (f"$h=@{{{h}}}; Invoke-WebRequest -Uri '{r.url}' -Headers $h "
            f"-OutFile '{r.name}'")


def pipe_url(r: Resolved, pipe_base: str, share: str) -> str:
    """把目标转换成 /pipe 代理 URL：凭证留在服务端，客户端只需一个普通 URL。"""
    q = up.urlencode({"share": share, "fid": r.fid}, quote_via=up.quote)
    return f"{pipe_base.rstrip('/')}/pipe?{q}"


def to_idm(r: Resolved, pipe_base: str = "http://127.0.0.1:8080",
           share: str = "", out_dir: str = "") -> str:
    """IDM 不支持逐任务自定义 header，只能喂普通 URL —— 因此走 /pipe。"""
    base = pipe_base or "http://127.0.0.1:8080"
    url = pipe_url(r, base, share) if share else r.url
    # /f 只接受文件名；分享内的子目录并到 /p
    sub = r.path.replace("\\", "/").rsplit("/", 1)[0] if "/" in r.path else ""
    target_dir = out_dir
    if sub:
        target_dir = (out_dir.rstrip("\\/") + "\\" + sub.replace("/", "\\")) if out_dir else sub.replace("/", "\\")
    parts = ['IDMan.exe', '/d', _win_quote(url), '/f', f'"{r.name}"']
    if target_dir:
        parts += ['/p', f'"{target_dir}"']
    parts.append('/a')
    return " ".join(parts)


def to_list(r: Resolved, pipe_base: str = "", share: str = "") -> str:
    """纯 URL 列表（每行一条），供 IDM / 浏览器「从剪贴板批量添加」。

    有 share 时默认给 /pipe 代理 URL —— 裸直链缺 cookie，粘进 IDM 同样 403。
    """
    if share:
        return pipe_url(r, pipe_base or "http://127.0.0.1:8080", share)
    return r.url


def _win_quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"' if (not s or any(c in s for c in ' &()[]{}^=;!\'+,')) else s


def to_wget(r: Resolved) -> str:
    hs = " ".join(f"--header={_shell_quote(f'{k}: {v}')}" for k, v in r.headers.items())
    return f"wget -c {hs} -O {_shell_quote(r.name)} {_shell_quote(r.url)}"


FORMATTERS = {
    "txt": to_text,
    "json": lambda r: json.dumps(r.to_dict(), ensure_ascii=False, indent=1),
    "curl": to_curl,
    "wget": to_wget,
    "ps": to_powershell,
    "aria2": to_aria2,
    "idm": to_idm,
    "list": to_list,
}


def render(items: List[Resolved], fmt: str = "json", out_dir: str = "",
           pipe_base: str = "", share: str = "") -> str:
    """渲染解析产物。

    pipe_base 非空时，产出走 /pipe 代理 URL —— 用于 IDM 这类无法自定义 header 的客户端。
    """
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps([r.to_dict() for r in items], ensure_ascii=False, indent=1)
    if fmt == "aria2":
        return "\n".join(to_aria2(r, out_dir) for r in items) + "\n"
    if fmt == "idm":
        if not share:
            raise ValueError("idm 格式需要分享地址（/pipe 代理需要 share 参数）")
        return "\n".join(to_idm(r, pipe_base or "http://127.0.0.1:8080", share, out_dir)
                         for r in items)
    if fmt == "list":
        return "\n".join(to_list(r, pipe_base, share) for r in items)
    fn = FORMATTERS.get(fmt)
    if not fn:
        raise ValueError(f"不支持的格式: {fmt}（可选 {', '.join(sorted(FORMATTERS))}）")
    sep = "\n\n" if len(items) > 1 else ""
    return sep.join(fn(r) for r in items)
