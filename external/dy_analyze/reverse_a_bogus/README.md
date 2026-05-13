# reverse_a_bogus

这个目录集中放 `a_bogus` 逆向相关代码。当前主抓取脚本只依赖 `pure_a_bogus.js` 的纯算法签名；旧 VM 方案只作为参考留在 `legacy_vm/`。

## 文件说明

- `pure_a_bogus.js`：统一入口和命令行入口，负责汇总导出 `core/` 里的算法模块。
- `core/sign.js`：签名入口，负责生成 `a_bogus` 并写回 URL。
- `core/payload.js`：构造核心 payload，是当前算法里最关键的组包逻辑。
- `core/finalize.js`：负责 payload 扩展、最终加密和编码。
- `core/query_stages.js`：负责 query + 固定盐的 SM3 摘要。
- `core/url_helpers.js`：负责清理旧签名参数和提取 query。
- `core/base64_custom.js`：自定义 Base64 字母表和编码逻辑。
- `core/rc4_like.js`：RC4-like 加密逻辑。
- `core/mask.js`：字节扩展混淆和 pair mask 编码。
- `core/bytes.js`：字符串和字节数组转换、小端字节转换。
- `core/fingerprint.js`：版本号和屏幕指纹构造。
- `core/checksum.js`：哨兵字节选择和 XOR 校验。
- `core/constants.js`：固定 UA、Base64 字母表、密钥、默认版本等常量。
- `core/sm3.js`：SM3 摘要算法实现。
- `validate_comments_api.js`：接口级验证脚本，用纯算法请求一级评论和二级评论，并写出验证结果。
- `api_validation_result.json`：最近一次接口验证结果。
- `legacy_vm/`：旧 VM 签名方案和原始签名 JS 参考，不参与当前主流程。

## 使用方式

单独生成签名：

```powershell
node .\reverse_a_bogus\pure_a_bogus.js "https://www.douyin.com/aweme/v1/web/comment/list/?device_platform=webapp&aid=6383&aweme_id=7626423682646326117"
```

输出：

```json
{
  "aBogus": "...",
  "signedUrl": "..."
}
```

代码调用：

```js
const { signUrl } = require("./reverse_a_bogus/pure_a_bogus");

const { signedUrl, aBogus } = signUrl(unsignedUrl);
```

## 完整算法流程

入口函数是 `signUrl(rawUrl, options)`。

整体链路：

```text
原始 URL
  -> 删除旧签名参数
  -> 计算 query / UA / 固定盐摘要
  -> 组装 96 字节 payload
  -> payload 扩展混淆
  -> RC4-like 加密
  -> 自定义 Base64 编码
  -> 得到 a_bogus
  -> 写回 URL
```

### 1. 清理 URL

对应文件：`core/url_helpers.js`

对应函数：`stripKnownSignatureParams`

生成签名前会删除这些旧参数：

- `a_bogus`
- `timestamp`
- `x-secsdk-web-signature`

这样可以保证签名输入只包含真实业务参数，避免旧签名影响新签名。

### 2. 构造签名 query

对应文件：`core/url_helpers.js`

对应函数：`buildVmQuery`

清理后的 URL 会取出 query 部分，不带开头的 `?`。例如：

```text
device_platform=webapp&aid=6383&aweme_id=7626423682646326117&cursor=0&count=20
```

这个 query 是后面 SM3 摘要的核心输入。

### 3. 计算 query 摘要

对应文件：`core/query_stages.js`

对应函数：`computeConfirmedStages`

当前还原出的固定盐是：

```text
dhzx
```

计算过程：

```text
queryInput = query + "dhzx"
queryHash = sm3(queryInput)
queryHash2 = sm3(queryHash)

fixedHash = sm3("dhzx")
fixedHash2 = sm3(fixedHash)
```

后面 payload 会从 `queryHash2`、`fixedHash2` 中抽取部分字节。

### 4. 计算 UA 摘要

对应文件：`core/payload.js`

对应逻辑在：`buildPayload96`

User-Agent 不直接放入 payload，而是先经过一层 RC4-like 加密和自定义 Base64：

```text
uaCipher = rc4ReverseBox(userAgent, "\x00\x81\x0e")
uaBase64 = encodeBySelector(uaCipher, "s3")
uaHash = sm3(uaBase64)
```

这里的 `s3` 对应 `INTERMEDIATE_BASE64_ALPHABET` 字母表。payload 后续会从 `uaHash` 中抽取部分字节。

### 5. 构造环境指纹

对应文件：`core/fingerprint.js`

对应函数：`buildScreenFingerprint`

默认指纹内容由屏幕和平台信息拼成：

```text
innerWidth|innerHeight|outerWidth|outerHeight|availWidth|availHeight|width|height|platform
```

默认值大致是 Windows Chrome 环境：

```text
1904|959|160|28|1920|1032|1920|1080|Win32
```

随后通过 `stringToVmBytes` 转成字节，写入 payload 尾部。

### 6. 构造时间字段

对应文件：`core/payload.js`

对应逻辑在：`buildPayload96`

核心时间值：

- `now`：当前毫秒时间戳。
- `shiftedNow`：`now - 1`。
- `dayBucket`：从固定起点 `1721836800000` 开始按 14 天分桶。

时间会以小端字节写入：

```text
nowBytes = littleEndianBytes(now, 6)
shiftedNowBytes = littleEndianBytes(now - 1, 6)
```

还有一个动态文本：

```text
dynamicText = ((now + 3) & 0xff) + ","
```

它也会被转成字节追加到 payload 里。

### 7. 构造版本头

对应文件：`core/fingerprint.js`、`core/mask.js`

对应函数：`parseVersionBytes`、`encodePairMasked`

默认版本：

```text
1.0.1.19-fix.01
```

会先解析成数字数组：

```text
[1, 0, 1, 19, 1]
```

当前主要使用前两个版本字节 `[1, 0]`，经过 `encodePairMasked` 得到 `packetHeader`。

`encodePairMasked` 的作用是把 2 字节输入扩展成 4 字节，并混入随机数或指定熵：

```text
input[0], input[1] -> 4 bytes
```

### 8. 填充 payload 字段

对应文件：`core/payload.js`

对应函数：`buildPayload96`

payload 不是顺序字段直接拼接，而是先构造一批 slot：

- 时间相关 slot
- queryHash2 相关 slot
- fixedHash2 相关 slot
- uaHash 相关 slot
- aid 相关 slot
- 环境字节长度 slot
- dynamicText 长度 slot
- 校验 slot

比较关键的抽取关系：

```text
queryHash2 -> slot48, slot49, slot51
fixedHash2 -> slot52, slot53, slot55
uaHash     -> slot56, slot57, slot59
aid        -> slot71, slot72
```

`slot51`、`slot55`、`slot59` 使用 `findGuardByte`，会避开特定哨兵值。

### 9. 计算 payload 校验

对应文件：`core/checksum.js`

对应函数：`xorChecksum`

`slot87` 是一个异或校验值。它会对 header 和大量 slot 做 XOR：

```text
slot87 = xorChecksum([...packetHeader, ...selectedSlots])
```

这个字节最后会追加到 payload 末尾。

### 10. 重排 payload

对应文件：`core/payload.js`

对应逻辑在：`buildPayload96`

slot 不会按编号顺序进入 payload，而是按固定顺序重排。例如开头是：

```text
slot34, slot44, slot56, slot61, slot73, slot29, ...
```

然后追加：

```text
screenBytes
dynamicTextBytes
slot87
```

最终得到 `payload`。

### 11. payload 扩展混淆

对应文件：`core/mask.js`

对应函数：`expandMaskedTriples`

payload 每 3 字节一组扩展成 4 字节，并混入随机 mask：

```text
a, b, c -> 4 bytes
```

变换关系：

```text
out0 = (mask & 145) ^ (a & 110)
out1 = (mask & 66)  ^ (b & 189)
out2 = (mask & 44)  ^ (c & 211)
out3 = (a & 145) ^ (b & 66) ^ (c & 44)
```

如果最后不足 3 字节，则直接保留。

### 12. 最终包加密

对应文件：`core/finalize.js`

对应函数：`finalizeABogus`

先构造：

```text
packet = packetHeader + expandedPayload
```

再使用 RC4-like 算法加密：

```text
encryptedPacket = rc4ReverseBox(packet, "\xd3")
```

这里的 RC4-like 不是标准 RC4，初始化 box 时使用了反向下标逻辑。

### 13. 生成前缀

对应文件：`core/mask.js`

对应函数：`encodePairMasked`

最终字符串前面还有一个 prefix：

```text
prefixBytes = encodePairMasked([3, 82], 1)
```

然后拼接：

```text
finalBytes = prefixBytes + encryptedPacket
```

### 14. 自定义 Base64 得到 a_bogus

对应文件：`core/base64_custom.js`

对应函数：`encodeBySelector(..., "s4")`

最后使用 `s4` 字母表编码：

```text
FINAL_BASE64_ALPHABET = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
```

得到最终 `a_bogus`。

### 15. 写回 URL

对应文件：`core/sign.js`

对应函数：`signUrl`

生成完成后，把 `a_bogus` 写回 URL：

```text
url.searchParams.set("a_bogus", aBogus)
```

最终返回：

```js
{
  aBogus,
  signedUrl
}
```

## 当前验证结论

运行接口验证：

```powershell
node .\reverse_a_bogus\validate_comments_api.js
```

当前结论：

- 一级评论：纯算法 `a_bogus` 可以稳定返回 JSON。
- 二级评论：当前纯算法签名会触发 `x-vc-bdturing-parameters`，主流程暂时复用 `api.txt` 第一行的二级评论模板签名。

结果文件：

```text
reverse_a_bogus/api_validation_result.json
```

## 旧版参考

`legacy_vm/` 里是旧 VM 签名方案和原始参考脚本：

- `legacy_vm/bdm_sign_vm.js`：旧版 Node VM 签名脚本。
- `legacy_vm/bdm_live.js`：抓取到的页面签名 JS 参考。
- `legacy_vm/bdm.js`：备用页面签名 JS 参考。

这些文件现在不参与主流程，只用于继续逆向或对比纯算法结果。
