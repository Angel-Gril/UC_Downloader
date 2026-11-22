# 鉴权链拆解：三道关卡与最小凭证

一条分享下载请求要穿过三层判定。三层之间**不是递进加强，而是职责分裂**：
前两层在业务 API 侧、面向"结构与指针"，第三层在 CDN 侧、面向"字节"。

```
┌─────────────────────────────────────────────────────────────────┐
│ L1  stoken          会话级分享票据   ← SSR 内联 / token 接口     │
│     作用：证明"我知道这个分享"                                    │
│     缺失：detail 返回 403 / 空列表                               │
├─────────────────────────────────────────────────────────────────┤
│ L2  share_fid_token 文件级持有证明   ← detail 顺手发牌            │
│     作用：证明"我看得到这个具体文件"                              │
│     缺失：41020 "转存文件token校验异常"                          │
├─────────────────────────────────────────────────────────────────┤
│ L3  __pugs          游客护照 cookie  ← file/download 下发        │
│     作用：让 CDN 回调确认"这次求来自刚签过链的会话"               │
│     缺失：RequestDeniedByCallback "require login [auth not found]"│
└─────────────────────────────────────────────────────────────────┘
```

---

## L1：`stoken`

| 项 | 值 |
|---|---|
| 来源 | `window.__INITIAL_PROPS__.initialData.stokenDetail.stoken` |
| 形态 | 44 字符 base64（含 `=`） |
| 生命周期 | 会话级；同一分享反复取会**变化** |
| 传递 | query 参数 `stoken` + header `x-clouddrive-st: <stoken>` |
| 是否必需 | 是（query 必需；header 实测对 `file/download` 非必需） |

同一分享两次解析的结果（间隔数分钟）：

```
dGhpcy1pcy1hLWZha2Utc3Rva2VuLWZvci1kb2NzLW9ubHk=
YW5vdGhlci1zZXNzaW9uLXRva2VuLXZhbHVlLWhlcmU=            ← 另一个会话
```

所以**不要把 stoken 写死进代码或配置文件**，它本质是一次性票据。

---

## L2：`share_fid_token`

`detail` 返回的每个条目都带 `share_fid_token`（32 hex，如 `784d75840063ee21bd155ad2423d8f26`）。

对比实验（同一 zip `fid`）：

| 请求 | 结果 |
|---|---|
| `archive/preview_tree` + `fid`，无 token | `403 / 41020 / 转存文件token校验异常[... token校验异常]` |
| 同上 + `fid_token=784d…` | `200 / finish:true / 4 条目` |

结论：该 token 是**文件级 capability**，由目录接口在"你确实看到了这一项"时签发。
这同时解释了：

- 为什么伪造 / 猜 `fid` 无效——没有配套 token；
- 为什么 `preview` 接口要求 `fid_list` **和** `fid_token_list` 两个参数同时在场。

---

## L3：`__pugs`

### 下发时机

只在 `POST /1/clouddrive/file/download` 的响应头里出现。
`detail` / `file_info` / `archive_tree` 均不下发。

```
POST /1/clouddrive/file/download?pr=UCBrowser&fr=pc
→ 200 OK
   Set-Cookie: __pugs=fd135580…AAR78LfF7sXwxhiE9OWR1V5u…   (184 字节)
```

### 判定矩阵（对 CDN 直链发 `GET`）

| 携带内容 | 状态 | 返回 |
|---|---|---|
| 无 cookie | 403 | `require login [auth not found]` |
| 仅 `ctoken` + `UDRIVE_TRANSFER_SESS`（站点访客） | 403 | `require login [auth miss]` |
| **仅 `__pugs`** | **200** | 全量 2,559,057 B |
| `__pugs` + 站点 cookie | 200 | 全量 |
| `x-clouddrive-pus: <__pugs>` 走 header 而非 cookie | 403 | `auth not found` |

两个高价值观察：

1. `auth not found` → `auth miss` 的变化证明服务端在**做值比对**，而不是"存在即通过"。
2. 鉴权信息**只从 cookie 读取**；换成同名 header 无效。回调体模板里写死了
   `${httpHeader.cookie}`，这决定了投递通道。

### 最小可用凭证

```
Cookie: __pugs=<取自同一次 file/download 会话的值>
```

不需要 `ctoken`、不需要 `UDRIVE_TRANSFER_SESS`、不需要 `Referer`、
不需要 `x-clouddrive-st`。这条结论直接决定了客户端实现：

```python
tgt = client.link_one(fid)        # ① 取链（此调用产生 __pugs）
cookie = client.s.cdn_cookies()   # ② 取链之后再读 cookie
requests.get(tgt.url, headers={"Cookie": cookie, "Range": "bytes=0-…"})  # ③
```

顺序颠倒（先读 cookie 再取链）就会出现"接口全通、字节全 403"的诡异现象。

---

## 为什么不能靠裁剪 URL 绕过 L3

OSS 预签名把**整个 query string** 纳入签名。对同一条直链做三种裁剪：

| 变体 | 结果 |
|---|---|
| 删 `callback` | `SignatureDoesNotMatch` |
| 删 `callback-var` | `SignatureDoesNotMatch` |
| 两者都删 | `SignatureDoesNotMatch` |

`Expires` / `Signature` / `OSSAccessKeyId` 保持原样也无济于事——
签名是对"路径 + 完整查询串"的摘要，任何字段缺失都会改变待签串。
**结论：签名字段不可裁剪，L3 无法通过参数手术绕过，只能正面满足。**

---

## 失败码速查

| 现象 | status/code | 根因 |
|---|---|---|
| `require login [guest]` | 401 / 31001 | 调了需要账号的接口（如 `/config`、`/file` 列表） |
| `inner error` | 500 / 15000 | 参数不全或接口不适用（如 `sharepage/token`） |
| `transfet token校验异常` | 403 / 41020 | 缺 `fid_token` |
| `require login [auth not found]` | OSS 403 | 没带 `__pugs` |
| `require login [auth miss]` | OSS 403 | 带了 cookie 但不是服务端认的那个值 |
| `SignatureDoesNotMatch` | OSS 403 | 直链被改动（裁剪 / 重排 / 重新编码） |

> 最后一行有个实践含义：**直链必须原样使用**。用 `requests` 的 `params=` 重新拼装，
> 很容易因为 `+`/`%2B`、参数顺序、空值保留策略的差异导致签名失配。
> 本项目一律把 `download_url` 当不透明字符串直接传给 `requests.get(url)`。
