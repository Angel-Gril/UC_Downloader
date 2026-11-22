"""示例：把一个公开分享整树镜像到本地，带清单与校验报告。

用法：
    python examples/mirror.py "https://drive.uc.cn/s/<pwd_id>?public=1" ./mirror
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ucdl import Downloader, ShareClient, ShareRef, GuestSession  # noqa: E402
from ucdl.download import safe_rel  # noqa: E402
from ucdl.verify import check_file, format_table  # noqa: E402


def main(share: str, out: str) -> int:
    sess = GuestSession()
    ref = ShareRef.resolve(share, sess)
    client = ShareClient(ref, sess)
    print(f"《{ref.title}》 {ref.all_file_num} 项 / {ref.size/1048576:.2f} MB")

    files = [e for e in client.walk() if not e.is_dir]
    dl = Downloader(client, jobs=6, log=lambda m: print(m, flush=True))

    results, manifest = [], []
    for i, e in enumerate(files, 1):
        dest = os.path.join(os.path.abspath(out), safe_rel(e.path))
        print(f"[{i}/{len(files)}] {e.name}", flush=True)
        tgt = client.link_one(e.fid)
        good, status = dl.save(tgt, dest, expect_md5=tgt.md5)
        res = check_file(dest, e.size, tgt.md5)
        results.append(res)
        manifest.append({
            "path": e.path, "fid": e.fid, "size": e.size,
            "md5_expected": tgt.md5, "ok": good and res.ok, "status": status,
        })

    report = os.path.join(os.path.abspath(out), "manifest.json")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    json.dump({"share": share, "title": ref.title, "files": manifest},
              open(report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print()
    print(format_table(results))
    print(f"\n清单: {report}")
    return 0 if all(r.ok for r in results) else 2


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
