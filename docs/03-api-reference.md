# API 速查（pc-api.uc.cn · clouddrive v1）

公共查询参数：`pr=UCBrowser&fr=pc`（产品线 / 端）。
以下端点均**不需要账号**，除特别标注。

---

## 1. 分享页（HTML）

```
GET https://drive.uc.cn/s/<pwd_id>?public=1
UA: 必须移动端（iPhone Safari / UC Mobile）
```

返回 15 KB SSR HTML，内联：

```html
<script>window.__INITIAL_PROPS__ = { "initialData": { "shareDetail": {...},
        "stokenDetail": { "stoken": "..." } } }</script>
```

桌面 UA 只得到 2 KB SPA 壳。

---

## 2. 分享 token（兜底）

```
POST /1/clouddrive/share/sharepage/token
{"pwd_id": "abcdef123456", "passcode": ""}
```

- 成功：`data.stoken`
- 实测常返回 `500 / 15000 inner error`，主链路不依赖它

---

## 3. 列目录

```
GET /1/clouddrive/share/sharepage/detail
pwd_id, stoken, pdir_fid, force=0, _page, _size,
_fetch_banner, _fetch_share, _fetch_total, _sort=file_type:asc,file_name:asc
```

响应要点：

```json
{"status":200,"code":0,"data":{
  "list":[{ "fid":"…","file_name":"…","dir":false,"size":2559057,
            "share_fid_token":"784d75840063ee21bd155ad2423d8f26",
            "obj_category":"archive","sec_archive_preview":true }],
  "metadata":{ "_total":24, "_page":1, "_size":50 } }}
```

- `pdir_fid=0` 等价于分享根；也可传 `first_fid`
- `metadata._total` 用于翻页终止
- 条目里的 `share_fid_token` 是 L2 凭证，务必保留

---

## 4. 单文件元信息

```
GET /1/clouddrive/share/sharepage/file/info
pwd_id, stoken, fid
```

比 detail 多出 `obj_category`、`sec_archive_preview`、`last_play_info` 等，
可用于判断"这个文件是否支持在线解包/播放"。

---

## 5. 取直链 ★

```
POST /1/clouddrive/file/download
{"fids": ["<fid>", …], "pwd_id": "<pwd_id>", "stoken": "<stoken>"}
```

响应：

```json
{"status":200,"code":0,"data":[{
  "fid":"…","file_name":"2甘雨.zip","size":2559057,"obj_key":"898f0d9a…",
  "md5":"mHPehrEb2pU4W5saR3DLsQ==",
  "range_size":262144,
  "download_url":"https://dl-uf-zb.pds.uc.cn/<a>/<b>/<c>/<d>?Expires=…&Signature=…"
}],"metadata":{"svip_time":1,"normal_time":1,"dms":true,"guest_time":7}}
```

- **副作用**：响应 `Set-Cookie: __pugs=…`（L3 凭证，必须取链后再读）
- `md5` 编码不统一：zip → base64，rar → hex
- `download_url` 有效期约 1 小时；`range_size` 给分块粒度
- 支持一次传多个 `fids`（批量取链）

---

## 6. 图片/文档预览

```
GET /1/clouddrive/share/sharepage/preview
pwd_id, stoken, fid_list=<fid>, fid_token_list=<share_fid_token>
```

- 缺 `fid_token_list` → `14001 Bad Parameter`
- 返回 `preview_url` / `quick_preview_url`
- ⚠️ 这些是**缩略图桶**（`thumb-c-*-cf.pds.uc.cn`）的 WebP，非原文件

---

## 7. 视频预览

```
GET /1/clouddrive/share/sharepage/video_preview
（参数同 preview）
```

用于在线播放，返回转码/切片信息。取原视频仍应走 `file/download`。

---

## 8. 压缩包内部清单 ★

```
POST /1/clouddrive/share/sharepage/archive/preview_tree
{"pwd_id":"…","stoken":"…","fid":"…","fid_token":"…","_page":1,"_size":50}
```

缺 `fid_token` → `403 / 41020 转存文件token校验异常`。

响应

```json
{"data":{"finish":true,"archive_id":"…_arc","total_file_count":4,
  "file_list":[{"file_name":"…jpg","size":988773,"path":"…jpg","path_no":1,
                "format_type":"image/jpeg","preview_url":"https://thumb-c-…/preview?…"}],
  "total_file_size":2617958},
 "metadata":{"_q_gap":500,"tq_gap":500}}
```

- `finish:false` 时按 `metadata.tq_gap` 毫秒重试
- `preview_url` 是缩略图，**不能当原文件**

---

## 9. CDN 直链（非 pc-api）

```
GET https://dl-uf-zb.pds.uc.cn/<path>?Expires=…&OSSAccessKeyId=…&Signature=…&callback=…&callback-var=…
Cookie: __pugs=<guest passport>
Range:  bytes=0-4194303          # 可选，配合 range_size
```

- 无 `__pugs` → `RequestDeniedByCallback` / `require login [auth not found]`
- 改动任何 query 参数（含删除 `callback`）→ `SignatureDoesNotMatch`
- 支持 `Range`，返回 206 + 精确分片

---

## 10. 压缩包条目命名异常

部分归档文件名被去掉/改写扩展名（`八重神子2ip`、`甘雨zip`、`申鹤.zip.`）。
判型按魔数：

| 魔数 | 类型 |
|---|---|
| `50 4B 03 04` | zip |
| `52 61 72 21 1A 07` | rar |

---

## 附：本项目未使用的接口

`sharepage/save`（转存，需登录）、`file/*`（个人空间，需登录，`/config` 直接 `401 require login [guest]`）、
`upload/*`、`offline/*`、`doc/weboffice/*`。这些属于账号态能力，与"公开分享下载"无关。
