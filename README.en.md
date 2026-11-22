# ucdl — UC Drive public-share protocol client & direct-link resolver

> Parse a `drive.uc.cn/s/<pwd_id>` public share into a **download descriptor any external
> client can consume**, plus a deep write-up of the auth chain. No account required.

[中文文档](README.md) · [Protocol analysis](docs/01-protocol-analysis.md) · [Resolver design](docs/05-resolver.md)

---

## Why "link + headers", not just a link

UC's presigned URL is **not self-sufficient**:

```bash
$ curl -O "https://dl-uf-zb.pds.uc.cn/…?Signature=…"
403 RequestDeniedByCallback
    Callback deny this request reason: require login [auth not found]
```

The signature is valid. What's missing is `__pugs`, a guest-passport cookie issued by
`file/download` and verified by the CDN's `before-execute` callback
(`auth-cdn.uc.cn/outer/oss/checkplay`).

So the smallest deliverable unit is a **(url, headers) pair**:

| Artifact | Usable? |
|---|---|
| URL only | ❌ 403 |
| **URL + `Cookie: __pugs=…` + UA** | ✅ full original bytes |

## Pipeline

```
① mobile UA  → SSR page   → inlined stoken   (desktop UA gets a 2 KB login shell)
② sharepage/detail (no auth) → tree + per-file share_fid_token
③ file/download    (no auth) → presigned URL + Set-Cookie: __pugs
④ hand (url, headers) to aria2 / curl / IDM  — or use the built-in transfer layer
```

## Install

```bash
git clone https://github.com/Angel-Gril/UC_Downloader.git
cd UC_Downloader
pip install -r requirements.txt     # requests only
```

Python ≥ 3.9.

## Usage

```bash
# metadata / tree
python -m ucdl info "https://drive.uc.cn/s/<pwd_id>?public=1"
python -m ucdl tree "…" -o tree.json

# ── resolve: the point of this project ──────────────────────
python -m ucdl link    "…" --fid <fid> --format json     # {url, headers, expires_in}
python -m ucdl link    "…" --fid <fid> --format curl
python -m ucdl resolve "…" --all --format aria2 --write aria2.txt

# ── HTTP resolver ───────────────────────────────────────────
python -m ucdl serve --port 8080
#   /list      /parse      /resolve      /pipe   (Range passthrough)

# ── built-in transfer layer (optional) ──────────────────────
python -m ucdl get "…" --all -o downloads     # chunked parallel + MD5 verify
```

Then hand the artifact to your downloader:

```bash
python -m ucdl resolve "<share>" --all --format aria2 --write aria2.txt
aria2c -i aria2.txt -x8 -s8 -j4
```

## Layout

```
ucdl/
├── session.py   guest session, __pugs retrieval, transport retries
├── share.py     SSR stoken parsing, entry model
├── api.py       list_dir / walk / links / archive_tree / preview
├── resolve.py   Resolved model + 8 renderers (incl. aria2/idm/list)
├── download.py  chunked parallel download, link refresh, md5 normalization
├── verify.py    size / MD5 / zip CRC / rar magic
├── server.py    HTTP resolver: /list /parse /resolve /pipe
└── cli.py       info | ls | tree | link | resolve | serve | get | arc | md5
```

## Verified

Against a 32-file / 423,929,789 B public share, anonymous:

| Check | Result |
|---|---|
| Files / bytes | 32 / 32 · 423,929,789 exact |
| Per-file MD5 vs server field | 32 / 32 |
| zip CRC · rar magic | pass |
| Cross-check vs an independent implementation | 32 / 32 byte-identical |
| Unit tests | 27 (23 offline, 4 integration skipped) |

The exported artifact was replayed in a **fresh interpreter with no session state**:
`200`, 2,559,057 B, MD5 matched.

## Limits

- `stoken` is session-scoped and rotates; never cache it.
- Presigned URLs expire (~1 h). Re-resolve instead of reusing.
- `preview` / `archive/preview_tree` return **thumbnails**, never originals.
- `/pipe` is an unauthenticated download proxy — keep it on `127.0.0.1`.
- Out of scope by design: anything requiring an account (`sharepage/save`, personal space).

MIT License.
