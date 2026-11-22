# -*- coding: utf-8 -*-
"""HTTP 解析服务：把「分享 → 可用直链」这层能力暴露成接口。

用途：让 aria2 / IDM / 脚本 / 另一个进程通过 HTTP 拿解析结果，
而不必把本项目当库导入或当脚本调用。

    GET /                    能力索引
    GET /list?share=<url>    分享目录树（JSON）
    GET /parse?share=<url>&fid=<fid>            单个解析
    GET /parse?share=<url>&path=<相对路径>       按路径解析
    GET /resolve?share=<url>&all=1              全量解析（JSON 数组）
    GET /pipe?share=<url>&fid=<fid>             反向代理字节流（给不能设头的客户端）

默认只监听 127.0.0.1。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse as up
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple

import requests

from . import config
from .api import ShareClient
from .resolve import Resolved, resolve_entry
from .session import ApiError, GuestSession
from .share import Entry, ShareRef

_CACHE_TTL = 900  # 分享树缓存 15 分钟
_lock = threading.Lock()
_tree_cache: Dict[str, Tuple[float, list]] = {}


def _get_share(share: str) -> ShareClient:
    sess = GuestSession()
    ref = ShareRef.resolve(share, sess)
    return ShareClient(ref, sess)


def _files(client: ShareClient) -> list:
    key = client.ref.pwd_id
    with _lock:
        hit = _tree_cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
    files = [e for e in client.walk() if not e.is_dir]
    with _lock:
        _tree_cache[key] = (time.time(), files)
    return files


def _find(files: list, fid: str = "", path: str = "") -> Optional[Entry]:
    if fid:
        return next((e for e in files if e.fid == fid), None)
    if path:
        p = path.lstrip("/")
        return next((e for e in files if e.path == p or e.name == p), None)
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = f"{config.APP_NAME}/{config.__version__}"

    def log_message(self, fmt, *args):  # 静音默认日志
        pass

    # ---------- 输出 ----------

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg: str, code: int = 400):
        self._json({"ok": False, "error": msg}, code)

    # ---------- 路由 ----------

    def do_GET(self):
        u = up.urlsplit(self.path)
        q = dict(up.parse_qsl(u.query))
        try:
            if u.path in ("/", "/index"):
                return self._json({
                    "name": config.APP_NAME, "version": config.__version__,
                    "routes": ["/list", "/parse", "/resolve", "/pipe"],
                    "note": "解析结果为 (url, headers)；单独 URL 不可用，必须带 Cookie: __pugs",
                })
            if u.path == "/list":
                return self._list(q)
            if u.path == "/parse":
                return self._parse(q)
            if u.path == "/resolve":
                return self._resolve(q)
            if u.path == "/pipe":
                return self._pipe(q)
            return self._err("not found", 404)
        except (ApiError, ValueError) as e:
            return self._err(str(e), 502)
        except BrokenPipeError:
            return
        except Exception as e:  # noqa: BLE001
            return self._err(f"{type(e).__name__}: {e}", 500)

    # ---------- 实现 ----------

    def _client(self, q) -> ShareClient:
        share = q.get("share", "")
        if not share:
            raise ValueError("缺少 share 参数")
        return _get_share(share)

    def _list(self, q):
        client = self._client(q)
        files = _files(client)
        return self._json({
            "ok": True,
            "title": client.ref.title,
            "pwd_id": client.ref.pwd_id,
            "count": len(files),
            "total_bytes": sum(e.size for e in files),
            "files": [{"fid": e.fid, "path": e.path, "size": e.size} for e in files],
        })

    def _parse(self, q):
        client = self._client(q)
        entry = _find(_files(client), q.get("fid", ""), q.get("path", ""))
        if not entry:
            return self._err("未找到该文件（用 fid 或 path 指定）", 404)
        r = resolve_entry(client, entry)
        return self._json({"ok": True, "result": r.to_dict()})

    def _resolve(self, q):
        client = self._client(q)
        files = _files(client)
        if q.get("all") not in ("1", "true", "yes"):
            entry = _find(files, q.get("fid", ""), q.get("path", ""))
            if not entry:
                return self._err("未找到该文件；批量请加 all=1", 404)
            files = [entry]
        out = []
        for e in files:
            try:
                out.append(resolve_entry(client, e).to_dict())
            except ApiError as err:
                out.append({"fid": e.fid, "path": e.path, "error": str(err)})
        return self._json({"ok": True, "count": len(out), "results": out})

    def _pipe(self, q):
        """把字节流转发出去，方便不支持自定义 header 的客户端。"""
        client = self._client(q)
        entry = _find(_files(client), q.get("fid", ""), q.get("path", ""))
        if not entry:
            return self._err("未找到该文件", 404)
        r: Resolved = resolve_entry(client, entry)
        headers = dict(r.headers)
        rng = self.headers.get("Range")
        if rng:
            headers["Range"] = rng
        upstream = requests.get(r.url, headers=headers, stream=True, timeout=240)
        if upstream.status_code not in (200, 206):
            return self._err(f"上游 {upstream.status_code}: {upstream.text[:160]}", 502)
        self.send_response(upstream.status_code)
        for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges",
                  "Content-Disposition"):
            if k in upstream.headers:
                self.send_header(k, upstream.headers[k])
        self.end_headers()
        for chunk in upstream.iter_content(1 << 16):
            self.wfile.write(chunk)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"{config.APP_NAME} resolve service -> http://{host}:{port}")
    print("  例: /parse?share=<分享链接>&path=<相对路径>")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
