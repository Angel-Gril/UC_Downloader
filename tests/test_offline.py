# -*- coding: utf-8 -*-
"""离线单测：不触网，覆盖编码/路径/解析这三处最容易出错的逻辑。"""

import unittest

from ucdl.download import md5_expected, safe_name, safe_rel
from ucdl.share import parse_pwd_id


class TestMd5Norm(unittest.TestCase):
    def test_hex_passthrough(self):
        # .rar 形态：服务端直接给裸 hex
        self.assertEqual(
            md5_expected("b3f0168cca8130eb0c0ca98982201cf9"),
            "b3f0168cca8130eb0c0ca98982201cf9",
        )

    def test_base64_decoded(self):
        # .zip 形态：base64(16 字节 digest)
        self.assertEqual(
            md5_expected("mHPehrEb2pU4W5saR3DLsQ=="),
            "9873de86b11bda95385b9b1a4770cbb1",
        )

    def test_same_digest_two_encodings(self):
        self.assertEqual(
            md5_expected("s/AWjMqBMOsMDKmJgiAc+Q=="),
            md5_expected("b3f0168cca8130eb0c0ca98982201cf9"),
        )

    def test_empty_and_garbage(self):
        self.assertEqual(md5_expected(""), "")
        self.assertEqual(md5_expected("not-a-digest"), "")


class TestSafeName(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(safe_name('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")

    def test_trailing_dot_and_space(self):
        self.assertEqual(safe_name("4k高清图和原视频."), "4k高清图和原视频")
        self.assertEqual(safe_name("name. "), "name")

    def test_reserved(self):
        self.assertTrue(safe_name("CON").startswith("_"))
        self.assertTrue(safe_name("lpt1.txt").startswith("_"))

    def test_cjk_kept(self):
        self.assertEqual(safe_name("兔兔的福利包.rar"), "兔兔的福利包.rar")

    def test_rel(self):
        self.assertEqual(safe_rel("兔兔的福利包./a/b.zip"),
                         "兔兔的福利包\\a\\b.zip".replace("\\", __import__("os").sep))


class TestPwdId(unittest.TestCase):
    def test_from_url(self):
        self.assertEqual(parse_pwd_id("https://drive.uc.cn/s/abcdef123456?public=1"),
                         "abcdef123456")

    def test_from_bare(self):
        self.assertEqual(parse_pwd_id(" abcdef123456 "), "abcdef123456")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_pwd_id("https://example.com/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
