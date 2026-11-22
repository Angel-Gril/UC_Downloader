# -*- coding: utf-8 -*-
"""离线单测：解析层输出格式（不触网）"""

import json
import unittest

from ucdl.resolve import (  # noqa: E402
    Resolved, pipe_url, render, to_aria2, to_curl, to_idm, to_list,
    to_powershell, to_wget,
)


def sample(**kw):
    base = dict(
        fid="f1", path="往期充电专属/第一期.rar", name="第一期.rar", size=487834,
        md5="s/AWjMqBMOsMDKmJgiAc+Q==", url="https://dl-uf-zb.pds.uc.cn/a/b?Expires=100",
        headers={"Cookie": "__pugs=abc", "User-Agent": "UA/1", "Referer": "https://drive.uc.cn/"},
        expires_at=0, range_size=262144,
    )
    base.update(kw)
    return Resolved(**base)


class TestFormats(unittest.TestCase):
    def test_json_shape(self):
        d = json.loads(render([sample()], "json"))[0]
        for k in ("fid", "path", "size", "md5", "url", "headers", "expires_in"):
            self.assertIn(k, d)
        self.assertEqual(set(d["headers"]), {"Cookie", "User-Agent", "Referer"})

    def test_aria2_keeps_relative_path(self):
        block = to_aria2(sample(), out_dir="downloads")
        self.assertTrue(block.startswith("https://"))
        self.assertIn("  header=Cookie: __pugs=abc", block)
        self.assertIn("  dir=downloads", block)
        # 保留分享内相对路径，避免同名文件互相覆盖
        self.assertIn("  out=往期充电专属/第一期.rar", block)

    def test_curl_has_headers_and_resume(self):
        cmd = to_curl(sample())
        self.assertIn("curl -L -C -", cmd)
        self.assertIn("Cookie: __pugs=abc", cmd)

    def test_wget_and_ps(self):
        self.assertIn("wget -c", to_wget(sample()))
        self.assertIn("Invoke-WebRequest", to_powershell(sample()))

    def test_expires_in_derived(self):
        import time
        future = int(time.time()) + 600
        r = sample(expires_at=future)
        self.assertTrue(560 <= r.expires_in <= 600)
        self.assertEqual(sample(expires_at=0).expires_in, 0)

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            render([sample()], "nope")


class TestPipePath(unittest.TestCase):
    """IDM 这类客户端不能设 header，必须走 /pipe 代理。"""

    SHARE = "https://drive.uc.cn/s/abc?public=1"

    def test_pipe_url_shape(self):
        u = pipe_url(sample(), "http://127.0.0.1:8080", self.SHARE)
        self.assertTrue(u.startswith("http://127.0.0.1:8080/pipe?"))
        self.assertIn("fid=f1", u)
        # share 必须被完整转义，否则 ?public=1 会把查询串截断
        self.assertIn("%3Fpublic%3D1", u)

    def test_idm_uses_pipe_and_basename(self):
        cmd = to_idm(sample(), "http://127.0.0.1:8080", self.SHARE, out_dir=r"D:\dl")
        self.assertIn("IDMan.exe", cmd)
        self.assertIn("/pipe?", cmd)
        self.assertIn('/f "第一期.rar"', cmd)
        self.assertIn(r'/p "D:\dl\往期充电专属"', cmd)
        self.assertTrue(cmd.rstrip().endswith("/a"))

    def test_idm_requires_share(self):
        with self.assertRaises(ValueError):
            render([sample()], "idm")

    def test_list_defaults_to_pipe(self):
        line = render([sample()], "list", share=self.SHARE).strip()
        self.assertIn("/pipe?", line)
        # 没有 share 时退回裸直链（并非常规用法）
        self.assertEqual(to_list(sample()), "https://dl-uf-zb.pds.uc.cn/a/b?Expires=100")

    def test_aria2_still_uses_native_headers(self):
        # aria2 支持逐任务 header，不需要走 pipe
        block = to_aria2(sample())
        self.assertIn("header=Cookie:", block)
        self.assertNotIn("/pipe?", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
