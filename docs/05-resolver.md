# 解析层设计：为什么交付「链接 + 请求头」

## 1. 问题定义

"解析直链"这个说法隐含一个假设：拿到 URL 就能下载。
在 UC 网盘的公开分享里，这个假设**不成立**：

```bash
$ curl -O "https://dl-uf-zb.pds.uc.cn/I4IZwhGR/…?Expires=…&Signature=…"
403  RequestDeniedByCallback
     Callback deny this request reason: require login [auth not found]
```

签名是对的、没过期，URL 本身完全有效。拒绝来自 CDN 的 `before-execute` 回调
`auth-cdn.uc.cn/outer/oss/checkplay`，它只比对一件事：请求里的 `__pugs`。

所以"直链"如果只交付 URL，交付的是一个**不可用的半成品**。

## 2. 契约

解析层的输出是 `Resolved`：

```python
@dataclass
class Resolved:
    fid: str
    path: str                  # 分享内相对路径，用于落盘结构
    name: str
    size: int
    md5: str                   # 原样保留服务端字段（base64 或 hex）
    url: str                   # 直链，原样，不可改写
    headers: Dict[str, str]    # ← 关键：Cookie / User-Agent / Referer
    expires_at: int            # 从 URL 的 Expires 解析
    range_size: int            # 分块粒度提示
```

三条不变量：

1. **`url` 必须逐字节原样使用**。任何重排/重编码都会 `SignatureDoesNotMatch`。
2. **`headers` 里的 `Cookie` 含 `__pugs`**，且必须与该 `url` 出自同一次会话。
3. **`expires_at` 只减不增**。过期后重新解析，不要试图复用。

## 3. 可用性证明

导出产物后，在**全新解释器、全新会话、无任何本项目状态**下直接取字节：

```python
import json, hashlib, base64, requests
d = json.load(open("r.json", encoding="utf-8"))
r = requests.get(d["url"], headers=d["headers"], timeout=120)
print(r.status_code, len(r.content), len(r.content) == d["size"])
print(base64.b64encode(hashlib.md5(r.content).digest()).decode() == d["md5"])
```

实测输出：

```
200 2559057 True
True
```

这一步是"解析器"与"下载脚本"的分水岭：前者交付的东西**离开本程序仍然成立**。

## 4. 八种输出格式

| `--format` | 用途 | 特点 |
|---|---|---|
| `json` | 程序消费 | 完整字段，`expires_in` 为剩余秒数 |
| `txt` | 人看 | URL 一行，之后是 `Key: Value` |
| `curl` | 直接粘贴 | 已带 `-L -C -`（跟随重定向 + 断点续传）与全部 header |
| `wget` | 同上 | `wget -c` + `--header` |
| `ps` | Windows | `Invoke-WebRequest` + hashtable |
| `aria2` | 批量 | aria2 输入文件格式（逐任务 `header=`，**不需要** pipe） |
| `idm` | IDM | 走 `/pipe` 代理 URL（IDM 不支持逐任务自定义 header） |
| `list` | 剪贴板 | 纯 URL 列表，有 `share` 时同样走 `/pipe` |

### 客户端怎么接：分两类

```
能自定义 header 的客户端         不能设 header 的客户端
curl / wget / aria2 / 自写脚本   IDM / 浏览器 / 播放器 / 只认 URL 的下载框
        ↓                                ↓
  直接用 (url, headers)            用 /pipe 的代理 URL
```

`/pipe` 的存在就是为了这后一半：凭证留在服务端，对外只给一个干净 URL。
代价是流量过本机（见 §5 的边界）。

### IDM

```bash
python -m ucdl resolve "<share>" --match "*.rar" --format idm \
        --pipe-base http://127.0.0.1:8080 --out "D:\dl" --write idm.bat
# 输出（每行一条，可当批处理直接跑）
IDMan.exe /d "http://127.0.0.1:8080/pipe?share=…&fid=…" /f "第一期.rar" /p "D:\dl\往期充电专属" /a
```

要求：先 `ucdl serve`，再让 IDM 打这个本地端口。`/f` 只放文件名，分享内的子目录并进 `/p`。

实测（裸 curl 模拟 IDM，不带任何 header）：

```
http=200  bytes=487834  md5=95efe2eab342d3eccca73c6c2a66ec36  ← 与官方字段一致
```

### aria2 输入文件

```
https://dl-uf-zb.pds.uc.cn/…
  header=Cookie: __pugs=…
  header=User-Agent: Mozilla/5.0 …
  header=Referer: https://drive.uc.cn/
  dir=downloads
  out=往期充电专属/第一期.rar
```

```bash
python -m ucdl resolve "<share>" --all --format aria2 --write aria2.txt
aria2c -i aria2.txt -x8 -s8 -j4
```

`out=` 保留分享内相对路径（`往期充电专属/第一期.rar`），避免不同目录下的同名文件互相覆盖。

## 5. HTTP 服务

```bash
python -m ucdl serve --port 8080        # 默认只绑 127.0.0.1
```

| 路由 | 说明 |
|---|---|
| `GET /` | 能力索引 |
| `GET /list?share=…` | 目录树 + 总字节数（15 分钟缓存） |
| `GET /parse?share=…&fid=…` | 单条解析 → `{url, headers, expires_in}` |
| `GET /parse?share=…&path=…` | 按相对路径解析 |
| `GET /resolve?share=…&all=1` | 全量解析（逐条 try，单条失败不影响整体） |
| `GET /pipe?share=…&fid=…` | 反向代理字节流，透传 `Range` |

`/pipe` 的存在是为了**给不能自定义 header 的客户端**兜底（比如某些播放器、
只认 URL 的下载框）。它把凭证留在服务端，对外只暴露一个干净的 URL——代价是流量过本机。

实测：

```
GET /parse?path=往期充电专属/第一期.rar
→ ok=True  name=第一期.rar  size=487834  exp_in=10800s  headers=Cookie,User-Agent,Referer

GET /pipe (Range: bytes=0-65535)
→ 65536 字节，206 语义透传
```

### 边界

- 只绑 `127.0.0.1`：`/pipe` 等于一个开放的下载代理，**不要拿去公网监听**。
- 无鉴权：服务本身不含账号概念，谁连上谁就能解析。
- 分享树缓存 15 分钟，避免每次请求都重走 `walk()`。

## 6. 与传输层的关系

```
resolve.py  ──→ (url, headers) ──→ 外部下载器（本项目退出）
     │
     └────────→ download.py ──→ 内置下载（分块并发 + MD5 + 断链重取）
```

`resolve.py` 不 import `download.py`，传输层反过来依赖解析层的 `DownloadTarget`
（同一个 `file/download` 响应，两种消费方式）。这样"只想要链接"的用户完全不会
被内置下载器拖进来。
