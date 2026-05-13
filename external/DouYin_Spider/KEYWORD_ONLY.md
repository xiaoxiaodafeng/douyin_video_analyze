# Keyword 列表批量抓取（按 `keyword.txt`）

本说明对应脚本：

- `keyword_file_first_blogger_videos.py`

脚本逻辑：

1. 读取 `datas/key/keyword.txt`（每行一个关键词）
2. 每个关键词取搜索结果第一个博主
3. 获取该博主 `sec_uid`
4. 抓取该博主详情页全部视频数据（含 `play_url` / `download_url`）
5. 导出 JSON

## 启动命令

```powershell
cd e:\douyin\DouYin_Spider
python .\keyword_file_first_blogger_videos.py --keyword-file .\datas\key\keyword.txt --save-each
```

## 输出文件

目录：

- `datas/keyword_batch`

文件：

1. `keywords_merged_<timestamp>.json`（所有关键词合并结果）
2. `keyword_<关键词>.json`（每个关键词一个文件，使用 `--save-each` 时生成）

## keyword.txt 格式

示例：

```txt
AI音乐人Tenno
小旭 AI Studio
```

支持：

- 空行自动跳过
- 以 `#` 开头的行视为注释
