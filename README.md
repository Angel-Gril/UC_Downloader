# ucdl — UC 网盘公开分享协议客户端

> 一个**不登录**也能把 `drive.uc.cn/s/<pwd_id>` 公开分享完整取到本地的小型客户端，
> 附带一份把鉴权链讲透的协议分析。

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](#)
[![Tests](https://img.shields.io/badge/tests-16%20passed-brightgreen.svg)](#测试)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 它解决了什么

UC 网盘的分享页在浏览器里点"下载"只会弹出"打开 APP"，看起来必须登录。
但把链路拆开看，真正的限制只有一处，而且这道门是可以正面走过去的：

```
① 移动 UA 取 SSR 页面        →  内联 stoken（桌面 UA 只有登录壳）
② sharepage/detail（免登录）  →  目录树 + 每个文件的 share_fid_token
③ file/download（免登录）     →  签名直链 + Set-Cookie: __pugs
④ CDN GET 直链 + __pugs       →  200，原始字节
```

关键发现：CDN 的 OSS 回调（`auth-cdn.uc.cn/outer/oss/checkplay`）判定的是
**"这次请求是否来自刚签发过直链的会话"**，而不是"属于哪个账号"。
游客护照 `__pugs` 单独一个 cookie 即可通过，实测返回完整原文件。

完整推导见 [docs/01-protocol-analysis.md](docs/01-protocol-analysis.md)。

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

# 列一层
python -m ucdl ls    "https://drive.uc.cn/s/abcdef123456?public=1"

# 递归列全树（可导出 JSON）
python -m ucdl tree  "https://drive.uc.cn/s/abcdef123456?public=1" -o tree.json

# 全量下载（保持目录结构，逐文件 MD5 校验，已存在自动跳过）
python -m ucdl get   "https://drive.uc.cn/s/abcdef123456?public=1" --all -o downloads

# 只下某几个
python -m ucdl get   "…" --match "*.rar"  -o downloads
python -m ucdl get   "…" --fid  d1795b0df0b148cf86183b98879a509f -o downloads

# 看压缩包内部清单（不解包）
python -m ucdl arc   "…" --name "2甘雨.zip"

# 取单个文件直链（自己用 curl 接）
python -m ucdl link  "…" --fid <fid>
```

有提取码的分享加 `--passcode xxxx`。

### 输出示例

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

```
ucdl/
├── config.py   端点表 / UA / 常量（端点均由前端 bundle 静态提取）
├── session.py  GuestSession：游客会话、__pugs 读取、统一错误判定
├── share.py    ShareRef：SSR 解析 stoken；Entry：目录项模型
├── api.py      ShareClient：list_dir / walk / links / archive_tree / preview
├─ download.py 分块并发、断链重取、md5 双编码归一
├── verify.py   尺寸 / MD5 / zip CRC / rar 魔数验收
└── cli.py      info | ls | tree | get | link | arc | md5
```

三个设计决定，都来自踩过的坑：

| 决定 | 原因 |
|---|---|
| `__pugs` **取链后**才读 | 它由 `file/download` 下发；先读会拿到空值，表现为全量 403 |
| 直链当**不透明字符串** | 任何 query 重排/重编码都会 `SignatureDoesNotMatch` |
| md5 **归一成 hex** 再比 | zip 给 base64、rar 给裸 hex，直接比较会误杀一半文件 |
| API 层**自动重试 4 次** | 网关偶发 `RemoteDisconnected`，不重试会打断整批下载 |
| 单文件失败**只跳过该文件** | 批量任务里一个坏链不该让前 14 个白下 |

### 吞吐参考

单连接约 0.1–0.5 MB/s；大文件（>80 MB）用 `--jobs 6~8` + 4 MB 分块最稳。
单流大文件容易被 CDN 中途 `RemoteDisconnected`，分块 + 指数退避后可跑满 404 MB 不断线。

---

## 测试

```bash
python -m unittest discover -s tests -v
# Ran 16 tests ... OK (skipped=4)
```

12 条离线单测（不触网）+ 4 条集成测试（需 `UCDL_SHARE` 环境变量，默认跳过）。

离线覆盖：md5 双编码归一、Windows 文件名安全化（非法字符/尾点/保留名）、pwd_id 解析。

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

---

## 说明

本项目用于**协议学习与授权范围内的自建镜像/归档**，只读取公开分享（`?public=1`），
不涉及账号态数据、不绕过任何登录、不碰私有空间接口。

`docs/01` 第 8 节从服务端视角列出了这套设计可加固的地方（直链未绑定会话、
护照判定过宽、预览桶与下载桶策略割裂），供防御侧参考。

MIT License.
