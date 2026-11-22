# -*- coding: utf-8 -*-
"""集成测试：真连外网，默认跳过。

运行方式：
    set UCDL_SHARE=https://drive.uc.cn/s/<pwd_id>?public=1
    python -m unittest tests.test_integration -v
可选：
    set UCDL_SAMPLE=某个文件名    # 只验证该文件，默认挑最小的文件
"""

import os
import unittest

from ucdl import Downloader, ShareClient, ShareRef, GuestSession
from ucdl.download import md5_expected
from ucdl.verify import check_file

SHARE = os.environ.get("UCDL_SHARE", "")
SAMPLE = os.environ.get("UCDL_SAMPLE", "")


@unittest.skipUnless(SHARE, "未设置 UCDL_SHARE，跳过集成测试")
class TestLiveShare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = GuestSession()
        cls.ref = ShareRef.resolve(SHARE, cls.s)
        cls.c = ShareClient(cls.ref, cls.s)
        cls.files = [e for e in cls.c.walk() if not e.is_dir]

    def test_stoken(self):
        self.assertTrue(self.ref.stoken)
        self.assertEqual(self.ref.pwd_id, ShareRef.resolve(SHARE, GuestSession()).pwd_id)

    def test_tree(self):
        self.assertGreater(len(self.files), 0)
        self.assertTrue(all(e.fid and e.fid_token for e in self.files))

    def test_guest_passport_after_link(self):
        tgt = self.c.link_one(self.files[0].fid)
        self.assertTrue(tgt.url.startswith("https://"))
        self.assertTrue(self.s.guest_passport, "file/download 应下发 __pugs")

    def test_download_smallest(self):
        target = next((f for f in self.files if SAMPLE and SAMPLE in f.name),
                      min(self.files, key=lambda x: x.size))
        tgt = self.c.link_one(target.fid)
        dst = os.path.join(os.environ.get("TEMP", "."), "ucdl_it_" + target.name)
        good, status = Downloader(self.c).save(tgt, dst, expect_md5=tgt.md5)
        self.assertTrue(good, status)
        res = check_file(dst, target.size, tgt.md5)
        self.assertTrue(res.ok, res.status)
        if md5_expected(tgt.md5):
            self.assertEqual(len(md5_expected(tgt.md5)), 32)


if __name__ == "__main__":
    unittest.main(verbosity=2)
