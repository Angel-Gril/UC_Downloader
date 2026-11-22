# -*- coding: utf-8 -*-
"""全局常量与端点表。

所有端点均来自对分享页前端 bundle（cloud-drive-web / shareh5）的静态提取，
未使用任何私有 SDK。
"""

from __future__ import annotations

APP_NAME = "ucdl"
__version__ = "0.1.0"

# pc-api 前缀：桌面端与 H5 共用同一套 clouddrive v1 接口
API_BASE = "https://pc-api.uc.cn"

# 分享页（H5 SSR 会内联 stoken）
SHARE_PAGE = "https://drive.uc.cn/s/{pwd_id}?public=1"

# 通用业务参数：pr=产品线，fr=端
COMMON = {"pr": "UCBrowser", "fr": "pc"}

ENDPOINTS = {
    "share_token": "/1/clouddrive/share/sharepage/token",       # POST {pwd_id,passcode}
    "share_detail": "/1/clouddrive/share/sharepage/detail",     # GET  列目录
    "share_v2_detail": "/1/clouddrive/share/sharepage/v2/detail",
    "file_info": "/1/clouddrive/share/sharepage/file/info",     # GET 单文件元信息(免登录)
    "file_download": "/1/clouddrive/file/download",             # POST {fids,pwd_id,stoken} -> 签名直链
    "preview": "/1/clouddrive/share/sharepage/preview",         # GET 需 fid_list+fid_token_list
    "video_preview": "/1/clouddrive/share/sharepage/video_preview",
    "archive_tree": "/1/clouddrive/share/sharepage/archive/preview_tree",  # POST 压缩包内条目
    "report": "/1/clouddrive/share/sharepage/report",
}

# 桌面/移动 UA 差异会决定返回「登录壳」还是「SSR 真页面」，移动 UA 必须
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

# 游客护照 cookie 名：由 pc-api 在 file/download 时下发，CDN 回调只认它
GUEST_COOKIE = "__pugs"

DEFAULT_CHUNK = 4 * 1024 * 1024
DEFAULT_JOBS = 6
DEFAULT_TIMEOUT = 30
