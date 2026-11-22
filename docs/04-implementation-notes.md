# 实现踩坑记录

三条 bug 都是"接口全 200、结果全不对"的类型，比 403 更难查。记在这里，省后来人时间。

---

## 坑 1：`__pugs` 读取时机（症状：全量 403）

**错误写法**

```python
cookie = session.cdn_cookies()          # 此时 jar 里只有站点 cookie
target = client.link_one(fid)           # 这一步才 Set-Cookie: __pugs
requests.get(target.url, headers={"Cookie": cookie})
```

现象：`file/download` 返回 200 且拿到直链，但每个分块都
`range 0-4194303 failed`，错误信息里是 `require login [auth not found]`。

**根因**：`__pugs` 只在 `file/download` 响应里下发。
在选择"先拼 cookie 再取链"的实现里，cookie 是空串。

**修正**：取链后刷新一次。

```python
target = client.link_one(fid)
cookie = client.s.cdn_cookies()        # ← 必须在取链之后
```

**教训**：把"产生凭证的调用"和"读取凭证"的顺序写成注释钉在代码里，
否则下一次重构很容易换回来。

---

## 坑 2：md5 双编码（症状：一半文件被误判损坏）

第一版：

```python
if base64.b64encode(hashlib.md5(data).digest()) == target.md5:
    write(data)
else:
    print("md5 mismatch")   # rar 全中
```

现象：8 个 `.zip` 全通过，8 个 `.rar` 全部 `FAIL-md5`，且**重下两次字节完全一致**——
说明文件没问题，是校验逻辑错了。

**根因**：服务端 `md5` 字段编码取决于归档类型：

| 类型 | 形态 | 长度 |
|---|---|---|
| zip | base64(16B) | 24 |
| rar | 裸 hex | 32 |

`b3f0168cca8130eb0c0ca98982201cf9` 与 `s/AWjMqBMOsMDKmJgiAc+Q==` 是同一个值。

**修正**：统一归一成 hex 再比；无法解析就返回空串（跳过校验，而不是误杀）。

```python
def md5_expected(exp: str) -> str:
    if len(exp) == 32 and all(c in HEX, exp):   # 裸 hex
        return exp.lower()
    raw = base64.b64decode(exp)                 # base64 -> hex
    return raw.hex() if len(raw) == 16 else ""
```

---

## 坑 3：把直链交给 `params=`（症状：`SignatureDoesNotMatch`）

想"清理掉 callback 参数再请求"，于是把 query 拆成 dict 重新拼：

```python
p = urlparse(url)
qs = parse_qsl(p.query)
requests.get(urlunsplit(p._replace(query=urlencode(qs))))   # 403 SignatureDoesNotMatch
```

**根因**：OSS 预签名对「路径 + 完整查询串」做摘要。
`urlencode` 会改变 `+`/`%2B` 的表示、参数顺序、空值保留策略，
哪怕语义相同、字节不同，签名即失配。删 `callback` 同样会失配（已实测三种裁剪全 403）。

**修正**：把 `download_url` 当**不透明字符串**，原样交给 `requests.get(url)`，
需要额外参数（如 `Range`）只放 header。

```python
requests.get(target.url, headers={"Cookie": ck, "Range": "bytes=0-4194303"})
```

---

## 坑 4：瞬时断连打断整批（症状：第 15 个文件时进程带栈退出）

41 个文件跑到第 15 个，`file/download` 撞上 `RemoteDisconnected`，
`requests` 直接抛 `ConnectionError` 冒到顶层，前 14 个已下完但整批失败退出。

**修正**两处：

1. 传输层统一重试（4 次退避），5xx 与连接异常都算可重试；
2. 单文件异常只记失败、继续下一个，最终汇总。

```python
try:
    good, status = dl.save(tgt, dest, expect_md5=tgt.md5)
except Exception as err:
    print(f"  [fail] {e.name}: {err}")
    good = False
```

**教训**：批量任务里，"一个失败"和"整批失败"必须被区分开。

---

## 坑 5：预览链冒充下载链（症状：图片只有 62 KB）

`archive/preview_tree` 返回的 `preview_url` **不需要 cookie** 就能 200，
很容易误以为"绕过成功"。

| 来源 | 大小 | 类型 |
|---|---|---|
| `preview_url` | 62,874 B | WebP 缩略图 |
| `file/download` | 988,773 B | 原始 JPEG |

两套桶（`thumb-c-*` vs `dl-*`）策略完全不同：缩略图桶匿名开放，
下载桶走回调鉴权。预览链只能用来**枚举结构**。

---

## 小结

| 症状 | 真实原因 |
|---|---|
| 接口 200 但字节 403 | 凭证读取时机错了 |
| 半数文件 md5 不符 | 同一 digest 两种编码 |
| 签名失配 | 把签名 URL 当可编辑对象 |
| 整批中断 | 单点异常没有隔离 |
| 图很小 | 预览桶 ≠ 下载桶 |
