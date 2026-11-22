# -*- coding: utf-8 -*-
"""会话层：游客身份 + 统一 API 封装。

设计要点（均来自实测）：
1. `pc-api.uc.cn` 的分享类接口**不需要登录**，也不校验 Referer / x-clouddrive-st。
2. 首次调用 `/file/download` 时，服务端通过 Set-Cookie 下发游客护照 `__pugs`。
   该 cookie 必须在**取链之后**读取，否则会漏掉——这是最容易踩的坑。
3. 下发给 CDN 的直链只认 `__pugs`（实测单独发它也返回 200 全量字节）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from . import config


class ApiError(RuntimeError):
    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload or {}


class GuestSession:
    """一个不带账号的 UC 网盘会话。"""

    def __init__(self, ua: str = config.UA_DESKTOP, timeout: int = config.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": ua})

    # ---------- 底层 ----------

    def _check(self, resp: requests.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            raise ApiError(f"非 JSON 响应 HTTP {resp.status_code}: {resp.text[:200]}")
        # 业务层用 status/code 双轨表达（200/0 为成功）
        if data.get("status") != 200 or data.get("code") not in (0, None):
            raise ApiError(
                f"{data.get('message') or 'api error'} "
                f"(status={data.get('status')}, code={data.get('code')})",
                data,
            )
        return data.get("data") or {}

    def get(self, path: str, params: Dict[str, Any], **kw) -> Dict[str, Any]:
        p = dict(config.COMMON)
        p.update(params)
        r = self._request("GET", config.API_BASE + path, params=p, **kw)
        return self._check(r)

    def post(self, path: str, body: Dict[str, Any], **kw) -> Dict[str, Any]:
        p = dict(config.COMMON)
        timeout = kw.pop("timeout", self.timeout)
        r = self._request("POST", config.API_BASE + path, params=p, json=body, timeout=timeout, **kw)
        return self._check(r)

    def _request(self, method: str, url: str, retry: int = 4, **kw) -> requests.Response:
        """传输层重试：CDN/网关偶发 RemoteDisconnected，不能让它打断整批任务。"""
        last: Optional[Exception] = None
        for attempt in range(retry):
            try:
                r = self.http.request(method, url, timeout=kw.pop("timeout", self.timeout), **kw)
                if r.status_code < 500:
                    return r
                last = ApiError(f"HTTP {r.status_code}")
            except requests.RequestException as e:
                last = e
            time.sleep(0.6 * (attempt + 1))
        raise ApiError(f"请求失败 {method} {url.split('?')[0]}: {last}")

    # ---------- 游客护照 ----------

    @property
    def guest_passport(self) -> Optional[str]:
        return self.http.cookies.get(config.GUEST_COOKIE)

    def cdn_cookies(self) -> str:
        """回传给 CDN 的 Cookie 头。__pugs 缺失时应重新取链。"""
        jar = self.http.cookies.get_dict()
        return "; ".join(f"{k}={v}" for k, v in jar.items() if v)

    def fetch_html(self, url: str, ua: str = config.UA_MOBILE, retry: int = 3) -> str:
        """取 SSR 页面。移动 UA 才会返回含 stoken 的真内容。"""
        last: Optional[Exception] = None
        for i in range(retry):
            try:
                r = requests.get(url, headers={"User-Agent": ua}, timeout=self.timeout)
                r.encoding = r.encoding or "utf-8"
                if r.status_code == 200:
                    return r.text
                last = ApiError(f"HTTP {r.status_code} on {url}")
            except requests.RequestException as e:
                last = e
            time.sleep(0.6 * (i + 1))
        raise ApiError(f"取页面失败: {last}")
