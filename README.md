# 抖音评论智能分析平台（对接版）

基于 `需求文档.md` 实现，已对接你现有项目：

- `E:\douyin\DouYin_Spider`（视频搜索/作者视频抓取）
- `E:\dy_analyze`（评论抓取）

并新增 `hfl/chinese-roberta-wwm-ext` 三分类微调链路。

## 1. 启动

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

打开：`http://127.0.0.1:8000/`

## 1.1 代码改动后自检（建议每次都跑）

```bash
.\.venv\Scripts\python scripts\post_change_check.py
```

该脚本会执行：

- `python -m compileall app`
- `import app.main` 启动级导入检查

## 2. 配置 `.env`

最少需要：

- `DY_COOKIE`：抖音 cookie
- `DY_VERIFY_FP`：`s_v_web_id` / `verifyFp`
- `DOUYIN_SPIDER_PATH=E:\douyin\DouYin_Spider`
- `DY_ANALYZE_PATH=E:\dy_analyze`

可选：

- `DY_SEARCH_TEMPLATE_URL`（如果你想走 keyword 脚本模板逻辑）
- `DEEPSEEK_API_KEY`

## 3. 与旧项目联动采集

### 3.1 按关键词/博主同步视频+评论

`POST /api/sync/from-existing`

示例：

```json
{
  "keyword": "AI",
  "video_limit": 5,
  "comment_limit": 300,
  "reply_limit": 30,
  "crawl_comments_for_found_videos": false
}
```

或：

```json
{
  "author_name": "某博主",
  "video_limit": 5,
  "comment_limit": 300,
  "reply_limit": 30,
  "crawl_comments_for_found_videos": false
}
```

说明：

- 默认只同步视频元数据，不抓取这些视频的评论。
- 只有 `comment_video_id` 会触发抓评。
- 如确需对搜索到的视频逐个抓评，显式设置 `crawl_comments_for_found_videos=true`。

### 3.2 仅抓某个视频评论

```json
{
  "comment_video_id": "7499999999999990001",
  "comment_limit": 500,
  "reply_limit": 50
}
```

## 4. 分析流程

1. `POST /api/analyze` 传 `video_id`
2. `GET /api/dashboard/{video_id}` 看板数据
3. `POST /api/export` 导出 CSV/JSON/Excel/Markdown

## 5. RoBERTa 三分类微调（hfl/chinese-roberta-wwm-ext）

### 5.1 生成训练集（弱标注/人工标注）

`POST /api/sentiment/build-trainset`

示例：

```json
{
  "video_id": "7499999999999990001",
  "sample_size": 3000,
  "strategy": "hybrid",
  "output_csv": "./datasets/sentiment_train.csv",
  "manual_csv": "./datasets/manual_labels.csv"
}
```

`manual_csv` 格式：

- 列：`text,label`
- `label` 取值：`Negative/Neutral/Positive`

### 5.2 启动微调

`POST /api/sentiment/finetune`

query 参数：

- `train_csv`
- `output_dir`（默认 `./models/roberta_sentiment_3cls`）
- `epochs`
- `batch_size`
- `learning_rate`

也可直接命令行：

```bash
python scripts/finetune_roberta_3cls.py --train-csv ./datasets/sentiment_train.csv --output-dir ./models/roberta_sentiment_3cls --base-model hfl/chinese-roberta-wwm-ext --epochs 3 --batch-size 16 --learning-rate 2e-5 --max-length 256
```

### 5.3 热加载新模型

`POST /api/sentiment/reload`

服务会优先加载：

- `SENTIMENT_MODEL_DIR`（微调输出目录）
- 若不存在则回退 `hfl/chinese-roberta-wwm-ext`
- 若仍失败再回退规则模型

### 5.4 批量推理测试

`POST /api/sentiment/predict`

```json
{
  "texts": ["这个视频太实用了", "有点夸张，不太真实"]
}
```

## 6. 主要新增文件

- `app/services/douyin_bridge.py`
- `app/services/training_data.py`
- `app/services/sentiment_model.py`
- `scripts/finetune_roberta_3cls.py`
- `app/routers/api.py`

## 7. 注意

- 你当前 `E:\dy_analyze` 评论抓取依赖 `cookie.txt` / `DOUYIN_COOKIE`，请先确保那边可单独运行。
- 微调质量依赖标注质量；`weak_label` 只能用于冷启动，建议尽快补人工标注集。
