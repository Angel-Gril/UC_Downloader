# -*- coding: utf-8 -*-
"""ucdl —— UC 网盘公开分享协议客户端。

对外只暴露四件事：解析分享、遍历内容、取签名直链、下载校验。
"""

from .api import DownloadTarget, ShareClient  # noqa: F401
from .config import __version__  # noqa: F401
from .download import Downloader, md5_expected, safe_name  # noqa: F401
from .session import ApiError, GuestSession  # noqa: F401
from .share import Entry, ShareRef, parse_pwd_id  # noqa: F401

__all__ = [
    "ShareClient", "DownloadTarget", "GuestSession", "ApiError",
    "ShareRef", "Entry", "parse_pwd_id", "Downloader", "md5_expected",
    "safe_name", "__version__",
]
