# 代码逻辑说明

## 总体流程

入口文件是 `douyin_crawler_server.js`。运行时传入视频 ID：

```powershell
node .\douyin_crawler_server.js 7626423682646326117 --limit=500 --reply-limit=50
```

脚本会按下面顺序执行：

1. 读取命令行参数。
2. 从 `cookie.txt` 或环境变量 `DOUYIN_COOKIE` 读取 Cookie。
3. 从 `api.txt` 读取接口模板。
4. 抓取一级评论。
5. 对有回复数的一级评论继续抓取二级评论。
6. 精简评论字段。
7. 写入 `outputs/douyin_comments_视频ID.json`。

## 核心文件

### `douyin_crawler_server.js`

主抓取脚本，负责参数解析、读取配置、构造请求、分页抓取、字段精简和写入 JSON。

### `reverse_a_bogus/pure_a_bogus.js`

纯算法 `a_bogus` 的统一入口。当前主脚本用它给一级评论接口重新签名，不再依赖 `bdm_sign_vm.js`、`bdm_live.js` 或 Chrome。

### `reverse_a_bogus/core/`

纯算法签名的拆分模块目录。`payload.js` 负责组包，`finalize.js` 负责最终混淆加密，`sign.js` 负责生成签名并写回 URL，其他文件负责 SM3、Base64、RC4-like、字节转换和校验等小步骤。

### `reverse_a_bogus/legacy_vm/`

旧 VM 签名方案和原始签名 JS 参考目录，包含 `bdm_sign_vm.js`、`bdm_live.js`、`bdm.js`。这些文件现在不参与主抓取流程，只用于后续继续逆向或对比纯算法结果。

### `api.txt`

保存两个接口模板：

- 第 1 行：二级评论接口 `/aweme/v1/web/comment/list/reply/`
- 第 2 行：一级评论接口 `/aweme/v1/web/comment/list/`

脚本会替换里面的视频 ID、评论 ID、分页 `cursor` 和 `count`。

## 一级评论抓取逻辑

对应函数：`crawlTopComments`

流程：

1. 读取 `api.txt` 第 2 行作为一级评论接口模板。
2. 替换 `aweme_id` 为命令行传入的视频 ID。
3. 替换 `cursor` 和 `count`。
4. 删除旧的 `a_bogus`、`timestamp`、`x-secsdk-web-signature`。
5. 调用 `reverse_a_bogus/pure_a_bogus.js` 重新生成 `a_bogus`。
6. 请求接口并读取 `comments`。
7. 保存评论数据和该评论的二级评论数量。
8. 根据接口返回的 `cursor` 和 `has_more` 继续翻页。

## 二级评论抓取逻辑

对应函数：`crawlReplies`

流程：

1. 读取 `api.txt` 第 1 行作为二级评论接口模板。
2. 替换 `item_id` 为视频 ID。
3. 替换 `comment_id` 为一级评论 ID。
4. 替换 `cursor` 和 `count`。
5. 保留模板中的可用 `a_bogus`。
6. 请求接口并读取二级评论。
7. 根据 `cursor` 和 `has_more` 继续翻页。

这里没有用纯算法重新签二级评论。原因是接口级验证发现：一级评论用纯算法签名可以稳定返回 JSON，但二级评论用当前纯算法签名会触发 `x-vc-bdturing-parameters`。目前稳定方案是复用 `api.txt` 第一行中抓包得到的二级评论模板签名。

## 字段精简逻辑

对应函数：`simplifyComment`

最终只保留这些字段：

- `cid`：评论 ID。
- `text`：评论内容。
- `user_id`：评论人 ID。
- `user_sec_uid`：评论人 sec_uid。
- `user_unique_id`：评论人抖音号，如果接口返回了就保留。
- `user_name`：评论人昵称。
- `ip_label`：IP 属地。
- `digg_count`：点赞数。

空值字段会自动删除。

## 输出 JSON 结构

最终输出是一级评论数组。二级评论会写在对应一级评论下面：

```json
[
  {
    "cid": "一级评论ID",
    "text": "一级评论内容",
    "user_name": "昵称",
    "ip_label": "广东",
    "digg_count": 12,
    "replies": [
      {
        "cid": "二级评论ID",
        "text": "二级评论内容",
        "user_name": "昵称",
        "ip_label": "北京",
        "digg_count": 0
      }
    ]
  }
]
```

没有二级评论的一级评论不会写 `replies` 字段。
