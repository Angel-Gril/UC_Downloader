# -*- coding: utf-8 -*-
"""对拍：比对两棵已下载目录树（相对路径 / 大小 / MD5）。

用法：
    python tools/crosscheck.py <树A> <树B>
    # 省略参数时使用项目内约定路径
"""

from __future__ import annotations

import hashlib
import os
import sys


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index(root: str) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[os.path.relpath(p, root)] = (os.path.getsize(p), md5(p))
    return out


def main(a: str, b: str) -> int:
    if not os.path.isdir(a) or not os.path.isdir(b):
        print("路径不存在：", a, "|", b)
        return 1
    ia, ib = index(a), index(b)
    print(f"A {len(ia)} 个 / B {len(ib)} 个")
    same = diff = only_a = only_b = 0
    for k in sorted(set(ia) | set(ib)):
        if k not in ib:
            only_a += 1
            print("  仅 A:", k)
        elif k not in ia:
            only_b += 1
            print("  仅 B:", k)
        elif ia[k] == ib[k]:
            same += 1
        else:
            diff += 1
            print("  不一致:", k, ia[k], ib[k])
    print(f"\n一致 {same} / 不一致 {diff} / 仅A {only_a} / 仅B {only_b}")
    return 0 if diff == 0 and only_a == 0 and only_b == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) == 3:
        raise SystemExit(main(sys.argv[1], sys.argv[2]))
    if len(sys.argv) == 1:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        raise SystemExit(main(os.path.join(here, "downloads"),
                              os.path.join(here, "downloads.ref")))
    print(__doc__)
    raise SystemExit(1)
