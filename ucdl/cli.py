# -*- coding: utf-8 -*-
"""命令行入口：python -m ucdl <cmd>"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from typing import Iterable, List

from . import config
from .api import ShareClient
from .download import Downloader, safe_rel
from .session import ApiError, GuestSession
from .share import Entry, ShareRef
from .verify import check_file, format_table


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.2f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n:.2f}GB"


def parse_size(s: str) -> int:
    s = s.strip().upper()
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    if s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(s)


def build_client(args) -> tuple[ShareClient, GuestSession]:
    s = GuestSession()
    ref = ShareRef.resolve(args.share, s, passcode=getattr(args, "passcode", "") or "")
    return ShareClient(ref, s), s


# ---------- 子命令 ----------


def cmd_info(args) -> int:
    client, _ = build_client(args)
    r = client.ref
    print(f"标题      : {r.title}")
    print(f"pwd_id    : {r.pwd_id}")
    print(f"share_id  : {r.share_id}")
    print(f"提取码    : {r.passcode or '(无)'}")
    print(f"stoken    : {r.stoken[:24]}…  (len={len(r.stoken)})")
    print(f"首层 fid  : {r.first_fid}")
    print(f"文件数    : {r.file_num} 项 / 全量 {r.all_file_num}")
    print(f"总大小    : {r.size:,} B ({human(r.size)})")
    if args.json:
        print(json.dumps({k: v for k, v in r.raw.items() if not isinstance(v, (dict, list))},
                         ensure_ascii=False, indent=1))
    return 0


def cmd_ls(args) -> int:
    client, _ = build_client(args)
    pdir = args.fid or client.ref.first_fid or "0"
    rows = client.children(pdir)
    for e in sorted(rows, key=lambda x: (not x.is_dir, x.name)):
        kind = "[D]" if e.is_dir else "[F]"
        size = "" if e.is_dir else f"{e.size:>12,}"
        print(f"{kind} {size}  {e.name}")
    print(f"\n共 {len(rows)} 项")
    return 0


def cmd_tree(args) -> int:
    client, _ = build_client(args)
    rows: List[Entry] = list(client.walk())
    files = [e for e in rows if not e.is_dir]
    for e in rows:
        depth = e.path.count("/")
        print("  " * depth + ("[D] " if e.is_dir else "[F] ") + e.name)
    print(f"\n目录 {len(rows)-len(files)} / 文件 {len(files)} / "
          f"{sum(e.size for e in files)/1048576:.2f} MB")
    if args.out:
        json.dump([e.__dict__ for e in rows], open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"已写出 {args.out}")
    return 0


def _select(files: Iterable[Entry], args) -> List[Entry]:
    sel = list(files)
    if getattr(args, "fid", None):
        sel = [e for e in sel if e.fid == args.fid]
    if getattr(args, "match", None):
        sel = [e for e in sel if fnmatch.fnmatch(e.name, args.match)]
    if not args.all and not args.fid and not args.match:
        print("需要 --all / --fid / --match 之一来指定下载范围", file=sys.stderr)
        return []
    return sel


def cmd_get(args) -> int:
    client, _ = build_client(args)
    files = [e for e in client.walk() if not e.is_dir]
    sel = _select(files, args)
    if not sel:
        return 1
    total = sum(e.size for e in sel)
    print(f"待载 {len(sel)} 个文件 / {human(total)}")

    out_root = os.path.abspath(args.out)
    dl = Downloader(client, jobs=args.jobs, chunk=parse_size(args.chunk),
                    log=lambda m: print(m, flush=True))
    results, ok = [], 0
    for e in sel:
        dest = os.path.join(out_root, safe_rel(e.path))
        if args.dry_run:
            print(f"  [dry] {dest}  ({human(e.size)})", flush=True)
            continue
        try:
            tgt = client.link_one(e.fid)
        except ApiError as err:
            print(f"  [link-fail] {e.name}: {err}", flush=True)
            results.append(check_file(dest, e.size))
            continue
        if tgt.size != e.size:  # 元数据与实际不一致时以服务端为准
            e.size = tgt.size
        try:
            good, status = dl.save(tgt, dest, expect_md5=tgt.md5)
        except Exception as err:  # noqa: BLE001 单个文件失败不应终止整批
            print(f"  [fail] {e.name}: {err}", flush=True)
            good, status = False, repr(err)[:80]
        ok += good
        if not good:
            print(f"  [fail] {e.name}: {status}", flush=True)
        results.append(check_file(dest, e.size, tgt.md5))
    if args.dry_run:
        return 0
    print()
    print(format_table(results))
    return 0 if ok == len(sel) else 2


def cmd_link(args) -> int:
    client, _ = build_client(args)
    entry = next((e for e in client.walk() if not e.is_dir and e.fid == args.fid), None)
    if entry is None:
        entry = type("E", (), {"fid": args.fid, "name": args.fid, "path": args.fid, "size": 0})()
    from .resolve import resolve_entry, render
    r = resolve_entry(client, entry)
    if args.format == "json":
        import json as _json
        print(_json.dumps(r.to_dict(), ensure_ascii=False, indent=1))
    else:
        print(render([r], args.format, args.out, args.pipe_base, args.share))
    print(f"\n# 直链有效期约 {r.expires_in // 60} 分钟；单独 URL 会 403，必须带 Cookie: __pugs",
          file=sys.stderr)
    return 0


def cmd_resolve(args) -> int:
    from .resolve import resolve_entry, render
    client, _ = build_client(args)
    files = [e for e in client.walk() if not e.is_dir]
    sel = _select(files, args)
    if not sel:
        return 1
    out, bad = [], 0
    for e in sel:
        try:
            out.append(resolve_entry(client, e))
            print(f"  resolved {e.path}", file=sys.stderr, flush=True)
        except ApiError as err:
            bad += 1
            print(f"  [fail] {e.path}: {err}", file=sys.stderr, flush=True)
    text = render(out, args.format, args.out, args.pipe_base, args.share)
    if args.write:
        with open(args.write, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写出 {args.write}（{len(out)} 条，失败 {bad}）", file=sys.stderr)
    else:
        print(text)
    return 0 if bad == 0 else 2


def cmd_serve(args) -> int:
    from .server import serve
    serve(args.host, args.port)
    return 0



def cmd_arc(args) -> int:
    client, _ = build_client(args)
    files = [e for e in client.walk() if not e.is_dir]
    target = None
    for e in files:
        if e.fid == args.fid or (args.name and e.name == args.name):
            target = e
            break
    if not target:
        print("未找到目标文件，请用 --fid 或 --name 指定", file=sys.stderr)
        return 1
    data = client.archive_tree(target.fid, target.fid_token,
                               page=args.page, size=args.size)
    rows = data.get("file_list") or []
    print(f"{target.name}: 共 {data.get('total_file_count', len(rows))} 条目 "
          f"(本页 {len(rows)})")
    for r in rows:
        print(f"  {r.get('size', 0):>12,}  {r.get('file_name')}")
    print("\n注意: preview_url 指向缩略图，原文件请走 file/download")
    return 0


def cmd_md5(args) -> int:
    from .download import md5_hex
    for p in args.paths:
        with open(p, "rb") as f:
            print(f"{md5_hex(f.read())}  {p}")
    return 0


# ---------- 解析器 ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ucdl",
        description="UC 网盘公开分享协议客户端（免登录，用于授权范围内的协议研究与自建镜像）",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {config.__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_share(sp):
        sp.add_argument("share", help="分享链接或 pwd_id")
        sp.add_argument("--passcode", default="", help="提取码（若有）")
        sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("info", help="解析分享元信息与 stoken")
    add_share(sp)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("ls", help="列一层目录")
    add_share(sp)
    sp.add_argument("--fid", default="")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("tree", help="递归列出整棵分享树")
    add_share(sp)
    sp.add_argument("-o", "--out", default="", help="导出 JSON")
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("get", help="下载文件")
    add_share(sp)
    sp.add_argument("-o", "--out", default="downloads")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--fid", default="")
    sp.add_argument("--match", default="")
    sp.add_argument("--jobs", type=int, default=config.DEFAULT_JOBS)
    sp.add_argument("--chunk", default="4M")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("link", help="解析单个文件的直链 + 必需请求头")
    add_share(sp)
    sp.add_argument("--fid", required=True)
    sp.add_argument("--format", default="txt",
                    choices=["txt", "json", "curl", "wget", "ps", "aria2", "idm", "list"])
    sp.add_argument("--out", default="", help="aria2/idm 格式时的落盘目录")
    sp.set_defaults(func=cmd_link)

    sp = sub.add_parser("resolve", help="批量解析成外部下载器可用的产物")
    add_share(sp)
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--fid", default="")
    sp.add_argument("--match", default="", help="文件名通配，如 *.rar")
    sp.add_argument("--format", default="json",
                    choices=["json", "txt", "curl", "wget", "ps", "aria2", "idm", "list"])
    sp.add_argument("--out", default="", help="aria2/idm 格式时的落盘目录")
    sp.add_argument("--pipe-base", default="", help="用 /pipe 代理 URL，如 http://127.0.0.1:8080")
    sp.add_argument("--write", default="", help="写入文件而不是打印")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("serve", help="启动 HTTP 解析服务")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8080)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("arc", help="读压缩包内部条目")
    add_share(sp)
    sp.add_argument("--fid", default="")
    sp.add_argument("--name", default="")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--size", type=int, default=50)
    sp.set_defaults(func=cmd_arc)

    sp = sub.add_parser("md5", help="计算本地文件 md5")
    sp.add_argument("paths", nargs="+")
    sp.set_defaults(func=cmd_md5)

    return p


def _ensure_utf8_streams() -> None:
    """Windows 默认控制台代码页（cp1252/cp936）对中文输出会抛 UnicodeEncodeError。

    `python -m ucdl --help` 在英文 Windows 上会直接崩，因此入口处统一切到 UTF-8。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: List[str] | None = None) -> int:
    _ensure_utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ApiError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
