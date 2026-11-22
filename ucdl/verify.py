# -*- coding: utf-8 -*-
"""下载后验收：尺寸、MD5、zip CRC、rar 魔数。"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from typing import Optional

from .download import md5_expected, md5_file

RAR_MAGIC = b"Rar!\x1a\x07"
ZIP_MAGIC = b"PK\x03\x04"


@dataclass
class CheckResult:
    path: str
    size: int
    expect_size: int
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def sniff(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(ZIP_MAGIC):
        return "zip"
    if head.startswith(RAR_MAGIC):
        return "rar"
    return ""


def check_file(path: str, expect_size: int, expect_md5: str = "") -> CheckResult:
    if not os.path.exists(path):
        return CheckResult(path, 0, expect_size, "MISSING")
    size = os.path.getsize(path)
    if size != expect_size:
        return CheckResult(path, size, expect_size, "SIZE-MISMATCH")
    exp = md5_expected(expect_md5)
    if exp:
        with open(path, "rb") as f:
            if md5_file(path) != exp:
                return CheckResult(path, size, expect_size, "MD5-MISMATCH")
    kind = sniff(path)
    try:
        if kind == "zip":
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
                if bad:
                    return CheckResult(path, size, expect_size, "ZIP-CRC", str(bad))
                return CheckResult(path, size, expect_size, "OK", f"{len(z.namelist())} entries")
        if kind == "rar":
            with open(path, "rb") as f:
                head = f.read(8)
            ver = "RAR5" if head[6:7] == b"\x01" else "RAR4"
            return CheckResult(path, size, expect_size, "OK", ver)
    except Exception as e:  # noqa: BLE001
        return CheckResult(path, size, expect_size, "VERIFY-ERROR", repr(e)[:80])
    return CheckResult(path, size, expect_size, "OK", "raw")


def format_table(results) -> str:
    lines = [f"{'状态':<14}{'实际/应为':<24}{'说明':<18}文件"]
    for r in sorted(results, key=lambda x: x.status):
        name = os.path.basename(r.path)
        lines.append(f"{r.status:<14}{r.size:>10}/{r.expect_size:<12}{r.detail:<18}{name}")
    ok = sum(1 for r in results if r.ok)
    lines.append("")
    lines.append(f"通过 {ok}/{len(results)}  "
                 f"字节 {sum(r.size for r in results):,}/{sum(r.expect_size for r in results):,}")
    return "\n".join(lines)

