# 抖音评论抓取工具

这是一个本地 Node.js 抖音评论抓取脚本。输入视频 ID 后，可以抓取一级评论和二级评论，并输出为嵌套 JSON。

## 隐私说明

`cookie.txt` 不会上传到 GitHub。使用前请复制示例文件，并填入你自己的抖音 Cookie：

```powershell
Copy-Item .\cookie.example.txt .\cookie.txt
```

也可以用环境变量 `DOUYIN_COOKIE` 传入 Cookie。

## 快速使用

```powershell
node .\douyin_crawler_server.js 7626423682646326117 --limit=500 --reply-limit=50
```

默认输出位置：

```text
outputs/douyin_comments_7626423682646326117.json
```

## 参数说明

- `--limit=500`：最多抓取多少条一级评论。
- `--reply-limit=50`：每条一级评论下最多抓取多少条二级评论。
- `--page-size=20`：每次请求的分页数量。
- `--output=xxx.json`：自定义输出文件路径。
- `--ua="..."`：自定义请求使用的 User-Agent，一般不用传。

## 当前签名策略

- 一级评论接口使用 `reverse_a_bogus/pure_a_bogus.js` 纯算法生成 `a_bogus`，不再依赖打开 Chrome，也不再调用 `bdm_sign_vm.js`。
- 二级评论接口暂时复用 `api.txt` 第一行里已验证可用的模板签名。接口级验证发现，二级评论直接用当前纯算法重新生成 `a_bogus` 会触发 BDTuring。

所以主命令仍然是：

```powershell
node .\douyin_crawler_server.js 视频ID --limit=500 --reply-limit=50
```

## 文件说明

- `douyin_crawler_server.js`：主入口，平时只运行这个文件。
- `reverse_a_bogus/pure_a_bogus.js`：一级评论接口使用的纯算法 `a_bogus` 生成器。
- `reverse_a_bogus/core/`：纯算法签名的拆分模块，包含 payload、加密、编码、SM3 等逻辑。
- `reverse_a_bogus/validate_comments_api.js`：接口级验证脚本，用来验证一级评论和二级评论接口返回状态。
- `reverse_a_bogus/legacy_vm/`：旧 VM 签名方案和原始签名 JS 参考，不参与当前主流程。
- `api.txt`：接口模板文件，第 1 行是二级评论接口，第 2 行是一级评论接口。
- `cookie.example.txt`：Cookie 示例文件。
- `cookie.txt`：你自己的真实 Cookie，本地使用，不要上传。
- `outputs/`：抓取结果输出目录。
- `CODE_LOGIC.md`：代码逻辑说明。

## 输出结构

每条一级评论是一个对象。如果它下面有二级评论，会多一个 `replies` 数组；没有二级评论就不会写这个字段。

```json
[
  {
    "cid": "一级评论ID",
    "text": "一级评论内容",
    "user_id": "评论人ID",
    "user_name": "评论人昵称",
    "ip_label": "IP属地",
    "digg_count": 10,
    "replies": [
      {
        "cid": "二级评论ID",
        "text": "二级评论内容",
        "user_name": "评论人昵称",
        "ip_label": "IP属地",
        "digg_count": 0
      }
    ]
  }
]
```

## 注意事项

- `cookie.txt` 过期后需要重新更新。
- 不要把自己的 `cookie.txt` 上传到公开仓库。
- `api.txt` 第一行的二级评论模板很关键，不要清空。
- 如果二级评论突然无法抓取，优先重新从浏览器抓一条二级评论接口 URL 更新到 `api.txt` 第一行。
