# UC 网盘分享协议分析（免登录链路）

> 目标：把一个 `https://drive.uc.cn/s/<pwd_id>` 公开分享完整落到本地，全程不携带任何账号凭证。
> 本文记录的是**链路结构与判定逻辑**，所有结论都来自对分享页前端产物与 `pc-api.uc.cn` 响应的静态/动态观测。

---

## 0. 一句话结论

UC 网盘把「列目录」和「发直链」做成了免登录接口，真正的闸门后移到 CDN 的 **OSS 回调鉴权**上；
而这道闸门只校验一个由服务端自己下发的**游客护照 cookie `__pugs`**，不校验账号归属。
于是链路变成：

```
移动UA 取 SSR 页 → 内联 stoken
        ↓
sharepage/detail  (免登录, 分页) → 每条目带 share_fid_token
        ↓
file/download     (免登录, {fids,pwd_id,stoken}) → 签名直链 + Set-Cookie: __pugs
        ↓
CDN GET  直链 + Cookie: __pugs=…  → 200 全量原始字节
```

---

## 1. 第一层：分享标识与 stoken

### 1.1 桌面页是登录壳，移动页才是真页面

同一 URL，仅 UA 不同：

| UA | 响应长度 | 内容 |
|---|---|---|
| Chrome/Windows | 2,227 B | SPA 壳，`<div id="ice-container">`，无数据 |
| iPhone Safari | 15,165 B | SSR 直出，`window.__INITIAL_PROPS__ = {...}` |

桌面端靠 XHR 二次取数（且强制登录态），移动端为了首屏速度把初始状态内联进 HTML。
**这是整条免登录链路的入口。**

### 1.2 从 SSR 状态里取什么

```json
{
  "initialData": {
    "stokenDetail": { "stoken": "dGhpcy1pcy1hLWZha2Utc3Rva2VuLWZvci1kb2NzLW9ubHk=" },
    "shareDetail": {
      "share": { "pwd_id": "abcdef123456", "share_id": "18c22aba…", "passcode": "",
                 "first_fid": "60c091b9…", "file_num": 1, "all_file_num": 35,
                 "size": 423929789 }
    }
  }
}
```

要点：

- `stoken` 是**会话级**的，同一分享多次请求会拿到不同值（实测 44 字符 base64），
  只用于本会话后续调用，不可跨会话复用。
- `passcode` 为空表示无提取码；有码的分享需要在 `token` 接口带上 `passcode`。
- `first_fid` 是首层文件夹 fid，遍历起点。
- `all_file_num` / `size` 是**递归**统计，可用来做下载进度分母。

### 1.3 兜底的 token 接口

`POST /1/clouddrive/share/sharepage/token`
body `{"pwd_id": "...", "passcode": ""}`

实测对多数分享返回 `{"status":500,"code":15000,"message":"inner error"}`，
属于服务端内部异常（缺参数或该分享类型不走此接口）。**仅作兼容分支保留**，主路径用 SSR。

---

## 2. 第二层：目录遍历与 `share_fid_token`

`GET /1/clouddrive/share/sharepage/detail`

| 参数 | 说明 |
|---|---|
| `pwd_id` / `stoken` | 1.x 取得 |
| `pdir_fid` | 目录 fid；`0` 表示分享根，也可用 `first_fid` |
| `_page` / `_size` | 分页；`_size` 上限 100 |
| `_fetch_total` | 1 时返回 `metadata._total`，用于翻页终止判定 |
| `_fetch_share` / `_fetch_banner` | 仅首层置 1，用于回带分享元信息 |
| `_sort` | `file_type:asc,file_name:asc` |

每个条目除常规字段外，还带 **`share_fid_token`**（32 hex）。
它是文件级的**持有证明（possession proof）**：

- 不带它调 `archive/preview_tree` → `403 41020 "转存文件token校验异常"`
- 带上它 → `200`，正常返回压缩包内部清单

也就是说：**目录接口同时承担了"发牌"职责**——没有先在 detail 里看到这个文件，就拿不到它的 token。
这解释了为什么"猜到 fid 也下不动"。

遍历策略：深度优先 + 每层 0.15s 间隔；`_total` 与实条数不一致时以 `_total` 为准继续翻页。

---

## 3. 第三层：直链签发 —— 免登录的核心

`POST /1/clouddrive/file/download`
body `{"fids": ["<fid>"], "pwd_id": "<pwd_id>", "stoken": "<stoken>"}`

返回（节选）：

```json
{"status":200,"code":0,"data":[{
  "fid":"d1795b0d…","file_name":"2甘雨.zip","size":2559057,
  "md5":"mHPehrEb2pU4W5saR3DLsQ==","range_size":262144,
  "download_url":"https://dl-uf-zb.pds.uc.cn/I4IZwhGR/…?Expires=…&Signature=…"
}]}
```

四个关键字段：

| 字段 | 作用 |
|---|---|
| `download_url` | OSS 预签名直链，`response-content-disposition=attachment` 已带好文件名 |
| `md5` | 客户端校验用，**编码不统一**（见 §6.1） |
| `range_size` | 分块粒度（262144），配合 `Range` 头可多线程 |
| `metadata.guest_time` | 游客配额/时限提示 |

同一个响应还会 **`Set-Cookie: __pugs=…`**。这就是下一节的主语。

### 3.1 直链的参数结构

```
Expires=…                 有效期（约 1 小时）
OSSAccessKeyId / Signature 预签名三元组
x-oss-traffic-limit       限速（字节/秒）
response-content-disposition  attachment; filename=…
callback-var              自定义授权上下文（x:token / x:ud / x:sp / x:ttl / x:ork / x:au）
callback                  回调地址 + 回调体模板
ud / dfi                  用户维度、下载文件标识
```

`callback-var` 里 `x:ud` 形如 `4-N-5-0-7-N-3-N-0-26-N-N-N-N-N`，是**用户/权限维度编码**；
`x:sp` 在预览与下载里同为 `100`，说明它不是"权限等级"，而是"空间/场景"标识。

---

## 4. CDN 闸门：OSS 回调鉴权

直链拿到并不等于能下。直接 `GET` 会得到：

```xml
<Error>
  <Code>RequestDeniedByCallback</Code>
  <Message>Callback deny this request reason: require login [auth not found]</Message>
  <HostId>dl-uf-zb.pds.uc.cn</HostId>
  <EC>0007-00000209</EC>
</Error>
```

机制：OSS 收到 GET 后，按 `callback` 参数把请求上下文（host / size / range / **referer** /
**cookie** / method / **clientIp** / `x:ulrp`）POST 到 `https://auth-cdn.uc.cn/outer/oss/checkplay`，
由业务侧返回 allow/deny。`callbackStage: before-execute` 表示这是**授权前置**，不是传输后回调。

### 4.1 第一反应：能不能把 `callback` 摘掉？

不行。OSS 预签名把**整个查询串**纳入签名计算，
删掉 `callback` / `callback-var` 任意一个都直接 `SignatureDoesNotMatch`；
三个变体（删 callback、删 callback-var、全删）实测全部 403。
**签名字段不可裁剪**，这条路封死。

### 4.2 真正的钥匙：`__pugs` 游客护照

把 `file/download` 那次会话的 cookie 一并回传，立刻：

| 携带 cookie | 结果 |
|---|---|
| 无 | `403 require login [auth not found]` |
| 仅站点 `ctoken` + `UDRIVE_TRANSFER_SESS` | `403 require login [auth miss]` |
| **仅 `__pugs`** | **200，2,559,057 B 全量** |
| `__pugs` + 站点 cookie | 200 全量 |

两个细节值得记：

1. **`auth not found` 与 `auth miss` 是两码事**：前者表示根本没看到 auth 字段，
   后者表示看到了但不匹配。仅带站点 cookie 会得到 `auth miss`，说明服务端确实在**比对**，
   而不是简单地"有 cookie 就放行"。
2. **`__pugs` 只在 `file/download` 响应里下发**，`detail` 阶段拿不到。
   如果先读 cookie 再取链，就会漏掉它——这是实现里最容易踩的坑（本项目第一版正是栽在这里，
   表现为 32 个文件全部 `range failed`）。

### 4.3 这意味着什么

CDN 侧的判定是：**"这次求是否来自一个刚签发过直链的会话"**，
而不是"这个请求属于哪个账号"。游客护照与其说是身份，不如说是**短时关联票据**。
因此免登录下载不是漏洞利用，而是这套设计的自然结果：
服务端刻意让 `detail`/`download` 开放，再用 CDN 回调把"谁能真拿到字节"收敛到会话维度。

---

## 5. 压缩包：预览能看，别当下载用

`POST /1/clouddrive/share/sharepage/archive/preview_tree`
body `{"pwd_id","stoken","fid","fid_token","_page","_size"}`

返回包内条目：

```json
{"data":{"finish":true,"total_file_count":4,"file_list":[
  {"file_name":"mmexport…jpg","size":988773,"format_type":"image/jpeg",
   "preview_url":"https://thumb-c-sz-cf.pds.uc.cn/…/preview?Expires=…&Signature=…"}
]}}
```

**陷阱**：这些 `preview_url` 落在 `thumb-c-*-cf` 缩略图桶，且**不需要 cookie** 就能取到——
看起来像"白嫖成功"，实际拿到的是 62,874 B 的 WebP，而原图是 988,773 B。
预览桶匿名开放 + 缩略重编码，与 `dl-*` 下载桶的回调鉴权是两套完全不同的策略。

结论：**预览链只能用来枚举结构和确认内容，取原文件必须走 `file/download`。**

---

## 6. 两个数据格式坑

### 6.1 md5 双编码

| 归档类型 | 字段形态 | 示例 |
|---|---|---|
| `.zip` | base64(16B digest) | `mHPehrEb2pU4W5saR3DLsQ==` |
| `.rar` | 裸 hex | `b3f0168cca8130eb0c0ca98982201cf9` |

两者解码后是同一个 16 字节值。第一版实现直接字符串比较，
导致 8 个 `.rar` 全部误判为"下载损坏"而被丢弃——文件其实是好的。
本项目 `md5_expected()` 统一归一成 hex 再比，并对无法解析的输入返回空串（跳过校验而非误杀）。

### 6.2 扩展名被抹掉的归档

分享里存在 `八重神子2ip`、`甘雨zip`、`花火2zip`、`申鹤.zip.` 这类文件名。
它们仍是完整 zip。识别方式：

- `PK\x03\x04` → zip
- `Rar!\x1a\x07` → rar

按魔数判型后交给 7-Zip 解包，`申鹤.zip.` 的尾点在 Windows 写入时会被自动裁掉（`申鹤.zip`）。

---

## 7. 速率与稳定性

- 单连接实测约 0.1–0.5 MB/s；`range_size=262144` 支持小块并发。
- 大文件（>80 MB）单流容易被 CDN 中途 `RemoteDisconnected`，
  分块 + 重试（8 次、指数退避）后稳定。
- 直链 `Expires` 约 1 小时；超时或 403 时**重取直链**即可，不算失败。
- 解析 `_size=100` 翻页；整棵树 35 项、2 层，实测 6 次请求可枚举完。

---

## 8. 防御视角（若要做对抗加固）

站在服务端角度，当前设计的"松"集中在三处，加固方向对应如下：

1. **直链签发未绑定会话**
   `file/download` 不给 `__pugs` 也能拿链接，等于把"发牌"和"验牌"解耦。
   合理做法是签发时即写入 `x:session` 并在 `checkplay` 里强校验，且一链一会话。

2. **游客护照的判定过宽**
   `checkplay` 只要求"存在且匹配"，未做 IP / UA / 时间窗绑定。
   实测护照单独可用，且 `clientIp` 已经在回调体里透传，却没参与判定。

3. **预览桶与下载桶策略割裂**
   缩略图桶匿名开放是合理的 CDN 优化，但同一 `obj_key` 的两套访问策略若不做审计，
   容易出现"预览可枚举 → 推断内容 → 定向取原文件"的链路放大。

---

## 9. 复现路径（本项目 CLI）

```bash
python -m ucdl info  "https://drive.uc.cn/s/<pwd_id>?public=1"   # 看 stoken / 规模
python -m ucdl tree  "https://drive.uc.cn/s/<pwd_id>?public=1" -o tree.json
python -m ucdl get   "https://drive.uc.cn/s/<pwd_id>?public=1" --all -o downloads
python -m ucdl arc   "https://drive.uc.cn/s/<pwd_id>?public=1" --name "x.zip"   # 包内清单
python -m ucdl link  "https://drive.uc.cn/s/<pwd_id>?public=1" --fid <fid>      # 单链
```

端到端实测（同一分享）：32 文件 / 423,929,789 B，逐文件 MD5 与官方一致，
zip 通过 CRC、rar 魔数与体积校验。
