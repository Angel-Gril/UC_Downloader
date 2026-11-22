# ucdl — UC 网盘公开分享协议客户端 & 直链解析器

> 把 `drive.uc.cn/s/<pwd_id>` 公开分享解析成**外部下载器可直接使用**的下载描述，
> 顺带提供一份把鉴权链讲透的协议分析。全程不登录。

[![CI](https://github.com/Angel-Gril/UC_Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Angel-Gril/UC_Downloader/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](#)
[![Tests](https://img.shields.io/badge/tests-27%20passed-brightgreen.svg)](#测试)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 定位：它是解析器，不是"下载脚本"

这个区别值得先说清楚，因为它决定了整个架构。

**UC 的直链不是自足的**。`file/download` 返回的 `dl-*.pds.uc.cn` URL 只证明"有权取这个对象"，
真正放行的是 CDN 回调里比对的会话票据 `__pugs`。
所以：

| 产物 | 能不能直接用 |
|---|---|
| 只有 URL | ❌ 403 `require login [auth not found]` |
| **URL + `Cookie: __pugs=…` + UA** | ✅ 200，原文件 |

因此本项目对外交付的最小单元是 **(url, headers) 二元组**，不是 url。
拿到这份描述后，你**不需要再运行本项目**——丢给 aria2 / curl / IDM / wget 都行：

```bash
# 解析 → 生成 aria2 输入文件 → aria2 自己下（本项目退出舞台）
python -m ucdl resolve "<share>" --all --format aria2 --write aria2.txt
aria2c -i aria2.txt -x8 -s8 -j4

# IDM 不吃自定义 header，所以走 /pipe 代理（先起服务）
python -m ucdl serve --port 8080 &
python -m ucdl resolve "<share>" --all --format idm --pipe-base http://127.0.0.1:8080 --write idm.bat
```

| 客户端 | 能否设 header | 接法 |
|---|---|---|
| aria2 / curl / wget / 自写脚本 | ✅ | 直接用 `(url, headers)` |
| **IDM / 浏览器 / 播放器** | ❌ | 用 `/pipe` 的代理 URL（凭证留在服务端） |

三种用法，按需要选：

| 你要什么 | 用哪个 |
|---|---|
| 只要链接和头，自己下 | `ucdl link` / `ucdl resolve --format json\|curl\|aria2` |
| 让别的进程通过 HTTP 拿解析结果 | `ucdl serve` → `/parse` `/resolve` `/pipe` |
| 不想折腾，本项目帮你下完并校验 | `ucdl get --all`（内置传输层，分块并发 + MD5） |

## 协议链路

```
① 移动 UA 取 SSR 页面        →  内联 stoken（桌面 UA 只有登录壳）
② sharepage/detail（免登录）  →  目录树 + 每个文件的 share_fid_token
③ file/download（免登录）     →  签名直链 + Set-Cookie: __pugs
④ 交付 (url, headers)         →  aria2 / curl / 外部任意客户端
   或 内置传输层分块并发下载
```

关键发现：CDN 的 OSS 回调（`auth-cdn.uc.cn/outer/oss/checkplay`）判定的是
**"这次请求是否来自刚签发过直链的会话"**，而不是"属于哪个账号"。
游客护照 `__pugs` 单独一个 cookie 即可通过，实测返回完整原文件。

完整推导见 [docs/01-protocol-analysis.md](docs/01-protocol-analysis.md)，
解析层设计见 [docs/05-resolver.md](docs/05-resolver.md)。

---

## 安装

```bash
git clone https://github.com/Angel-Gril/UC_Downloader.git
cd UC_Downloader
pip install -r requirements.txt          # 仅依赖 requests
```

Python ≥ 3.9。解压归档需要系统里有 7-Zip（可选，本项目核心不依赖）。

---

## 用法

```bash
# 看分享元信息（标题 / stoken / 规模 / 是否有提取码）
python -m ucdl info  "https://drive.uc.cn/s/abcdef123456?public=1"

# 列一层 / 递归列全树
python -m ucdl ls    "…"
python -m ucdl tree  "…" -o tree.json

# ── 解析（本项目的核心，产物给外部下载器用）─────────────────
python -m ucdl link    "…" --fid <fid> --format json     # 单文件 → {url, headers}
python -m ucdl link    "…" --fid <fid> --format curl     # 直接给人类复制
python -m ucdl resolve "…" --all --format aria2 --write aria2.txt
python -m ucdl resolve "…" --match "*.rar" --format json --write links.json

# ── HTTP 解析服务（给别的进程/脚本调）───────────────────────
python -m ucdl serve --port 8080
#   GET /parse?share=<url>&path=<相对路径>   → {url, headers, expires_in}
#   GET /resolve?share=<url>&all=1           → 全量
#   GET /pipe?share=<url>&fid=<fid>          → 反向代理字节流（受 Range）

# ── 内置传输层（不想自己下就用这个）─────────────────────────
python -m ucdl get   "…" --all -o downloads              # 分块并发 + MD5 校验
python -m ucdl get   "…" --match "*.rar" -o downloads

# 看压缩包内部清单（不解包）
python -m ucdl arc   "…" --name "2甘雨.zip"
```

有提取码的分享加 `--passcode xxxx`。

### 输出示例：解析产物

```console
$ python -m ucdl link "…" --fid d1795b0d… --format json
{
 "fid": "d1795b0df0b148cf86183b98879a509f",
 "path": "4k高清图和原视频/2甘雨.zip",
 "name": "2甘雨.zip",
 "size": 2559057,
 "md5": "mHPehrEb2pU4W5saR3DLsQ==",
 "url": "https://dl-uf-zb.pds.uc.cn/I4IZwhGR/…",
 "headers": {
  "Cookie": "__pugs=…",
  "User-Agent": "Mozilla/5.0 …",
  "Referer": "https://drive.uc.cn/"
 },
 "expires_in": 10800
}
```

这份 JSON 拿到另一个干净进程里直接可用——已实测：新解释器仅凭 `url + headers`
取回 2,559,057 B，MD5 与官方字段一致。

### 输出示例：内置下载

```
$ python -m ucdl get "…" --match "菲伦..zip" -o out
待载 1 个文件 / 230.57KB
  ok 菲伦..zip  0.23MB  0.08MB/s

状态            实际/应为                   说明                文件
OK                236101/236101      3 entries         菲伦..zip
通过 1/1  字节 236,101/236,101
```

### 作为库用

```python
from ucdl import ShareRef, ShareClient, GuestSession, Downloader

s   = GuestSession()
ref = ShareRef.resolve("https://drive.uc.cn/s/abcdef123456?public=1", s)
cli = ShareClient(ref, s)

for e in cli.walk():                     # 递归遍历
    if e.is_dir:
        continue
    tgt = cli.link_one(e.fid)            # 取直链（同时产生 __pugs）
    Downloader(cli).save(tgt, f"out/{e.name}")
```

---

## 架构

分成三层，**解析层可以脱离传输层独立使用**——这是本项目与"下载脚本"的分界线。

```
① 协议层  session.py / share.py / api.py     stoken → fid_token → 直链
② 解析层  resolve.py                         直链 + __pugs → (url, headers) 可交付产物
                                              └→ txt / json / curl / wget / ps1 / aria2 / idm / list
③ 传输层  download.py / verify.py            可选：分块并发下载 + 校验
          server.py                          可选：以 HTTP 暴露 ①②
```

```
ucdl/
├── config.py    端点表 / UA / 常量（端点均由前端 bundle 静态提取）
├── session.py   GuestSession：游客会话、__pugs 读取、传输重试、统一错误判定
├── share.py     ShareRef：SSR 解析 stoken；Entry：目录项模型
├── api.py       ShareClient：list_dir / walk / links / archive_tree / preview
├── resolve.py   ★ 解析层：Resolved 模型 + 8 种外部格式渲染
├── download.py  传输层：分块并发、断链重取、md5 双编码归一
├── verify.py    验收：尺寸 / MD5 / zip CRC / rar 魔数
├── server.py    ★ HTTP 解析服务：/list /parse /resolve /pipe
└── cli.py       info | ls | tree | link | resolve | serve | get | arc | md5
```

设计决定，都来自踩过的坑：

| 决定 | 原因 |
|---|---|
| 交付 **(url, headers) 二元组** | 裸 URL 必 403，CDN 只认 `__pugs`；导出时把它一起打包 |
| `__pugs` **取链后**才读 | 它由 `file/download` 下发；先读会拿到空值，表现为全量 403 |
| 直链当**不透明字符串** | 任何 query 重排/重编码都会 `SignatureDoesNotMatch` |
| md5 **归一成 hex** 再比 | zip 给 base64、rar 给裸 hex，直接比较会误杀一半文件 |
| API 层**自动重试 4 次** | 网关偶发 `RemoteDisconnected`，不重试会打断整批下载 |
| 单文件失败**只跳过该文件** | 批量任务里一个坏链不该让前 14 个白下 |
| 解析层**不依赖 download.py** | 用户可以只拿链接、用自己的下载器，本层零耦合 |

### 吞吐参考

单连接约 0.1–0.5 MB/s；大文件（>80 MB）用 `--jobs 6~8` + 4 MB 分块最稳。
单流大文件容易被 CDN 中途 `RemoteDisconnected`，分块 + 指数退避后可跑满 404 MB 不断线。

---

## 测试

```bash
python -m unittest discover -s tests -v
# Ran 27 tests ... OK (skipped=4)
```

23 条离线单测（不触网）+ 4 条集成测试（需 `UCDL_SHARE` 环境变量，默认跳过）。

离线覆盖：md5 双编码归一、Windows 文件名安全化（非法字符/尾点/保留名）、pwd_id 解析、
解析层 8 种输出格式（JSON 结构 / aria2 保留相对路径 / curl 断点续传参数 / 过期时间推导，
以及 IDM 走 pipe、子目录并入 `/p`、share 查询串必须完整转义）。

```bash
# 想跑集成测试：
set UCDL_SHARE=https://drive.uc.cn/s/<pwd_id>?public=1
python -m unittest tests.test_integration -v
```

### 端到端验证

对同一公开分享（32 文件 / 423,929,789 B）全量下载：

| 校验项 | 结果 |
|---|---|
| 文件数 | 32 / 32 |
| 总字节 | 423,929,789 / 423,929,789 |
| 逐文件 MD5（对官方 `md5` 字段） | 32 / 32 一致 |
| zip CRC | 通过 |
| rar 魔数 (RAR5) | 通过 |
| **与另一套独立实现交叉对拍** | **32 / 32 字节级一致** |

下载后再解包：48 张 jpg + 12 个 mp4，条目名与字节数逐条核对，0 不符。

交叉对拍脚本：

```bash
python tools/crosscheck.py     # 比对两棵输出树的相对路径 / 大小 / MD5
```

---

## 已知限制

- **`stoken` 是会话级票据**，会随请求变化，不能缓存复用。
- **直链有效期约 1 小时**，超时后需重取；`Downloader` 已自动处理。
- **`sharepage/token` 接口不稳定**（常返回 `15000 inner error`），SSR 解析是主路径。
- **`preview` / `archive/preview_tree` 返回的是缩略图**，不能替代原文件下载。
- **游客配额**：响应 `metadata.guest_time` 提示游客有时限/配额，大批量任务建议控制并发。
- 未实现转存（`sharepage/save`）等**需要账号**的能力，本项目的边界就是"公开分享读取"。

---

## 文档

| 文件 | 内容 |
|---|---|
| [docs/01-protocol-analysis.md](docs/01-protocol-analysis.md) | 完整链路推导：SSR 注入、fid_token、直链签发、CDN 回调、两个格式坑 |
| [docs/02-auth-chain.md](docs/02-auth-chain.md) | 三道关卡、最小凭证矩阵、失败码速查、为何签名字段不可裁剪 |
| [docs/03-api-reference.md](docs/03-api-reference.md) | 端点速查：参数、响应、注意事项 |
| [docs/04-implementation-notes.md](docs/04-implementation-notes.md) | 5 个实现坑：凭证时机 / md5 双编码 / 签名不可编辑 / 单点隔离 / 预览冒充下载 |
| [docs/05-resolver.md](docs/05-resolver.md) | 解析层设计：(url,headers) 契约、8 种格式、HTTP 服务 |

---

## 说明

本项目用于**协议学习与授权范围内的自建镜像/归档**，只读取公开分享（`?public=1`），
不涉及账号态数据、不绕过任何登录、不碰私有空间接口。

`docs/01` 第 8 节从服务端视角列出了这套设计可加固的地方（直链未绑定会话、
护照判定过宽、预览桶与下载桶策略割裂），供防御侧参考。

MIT License.
