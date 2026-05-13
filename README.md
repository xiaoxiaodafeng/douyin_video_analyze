# douyin_video_analyze

基于 FastAPI 的抖音视频与评论分析项目，提供网页控制台和 API，支持：

- 按视频 ID、博主名称、抖音号（`unique_id`）查询视频
- 查询候选博主并拉取该博主视频列表
- 抓取评论（一级/二级）并异步查看进度
- 评论情感分析、关键词提取、舆情预警
- 视频语音转写（ASR）与视频内容复盘（可接 DeepSeek / Qwen VL）
- 结果看板与导出（CSV / JSON / Excel / Markdown）

## 1. 项目结构

```text
app/
  main.py                 # FastAPI 入口
  routers/api.py          # 全部接口
  services/               # 评论分析、外部桥接、ASR/VL 能力
web/
  index.html              # 前端页面
scripts/
  post_change_check.py    # 变更后自检脚本
datasets/                 # 训练/语料数据
```

## 2. 环境要求

- Python 3.10+（建议 3.10/3.11）
- Windows 环境（当前默认路径配置为 Windows）
- 可访问你本地已存在的两个外部项目（可选但推荐）：
  - `DOUYIN_SPIDER_PATH`（视频/博主检索能力）
  - `DY_ANALYZE_PATH`（评论抓取能力）

## 3. 快速启动

```powershell
cd E:\dy_comments
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`（至少填下面几项）：

- `DY_COOKIE=...`
- `DY_VERIFY_FP=...`
- `DOUYIN_SPIDER_PATH=E:\douyin\DouYin_Spider`
- `DY_ANALYZE_PATH=E:\dy_analyze`

启动服务：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问：

- 首页：`http://127.0.0.1:8000/api/`
- 健康检查：`http://127.0.0.1:8000/api/health`

## 4. 前端使用流程（当前版本）

页面入口：`web/index.html`（由 `/api/` 提供）

推荐操作顺序：

1. 输入 `博主名称` 或 `抖音号`，点击“查询候选博主”
2. 在候选下拉框选中目标博主
3. 点击“查询视频”，在视频表格中点击目标行自动带入 `视频ID`
4. 设置评论抓取数量后点击“开始分析”
5. 查看看板、评论摘要、视频转写、视频复盘
6. 需要时点击“导出结果”

说明：

- `查询视频` 若 `视频ID/博主名称/抖音号` 全空，会弹窗提示，不会继续请求
- 目前看板图表仅保留：
  - 情感占比
  - 关键词 Top20

## 5. 关键环境变量

参考 `.env.example`，常用如下：

- 基础：
  - `DATABASE_URL`（默认 `sqlite:///./dy_comments.db`）
- 抖音联动：
  - `DOUYIN_SPIDER_PATH`
  - `DY_ANALYZE_PATH`
  - `DY_COOKIE`
  - `DY_VERIFY_FP`
  - `DY_SEARCH_TEMPLATE_URL`（可选）
- 大模型：
  - `DEEPSEEK_API_KEY`（可选）
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_CHAT_MODEL`
  - `QWEN_VL_API_KEY` / `QWEN_VL_BASE_URL`（可选）
- 情感模型：
  - `SENTIMENT_MODEL_DIR`
  - `SENTIMENT_BASE_MODEL`
- 视频 ASR/VL：
  - `ASR_PYTHON_EXE`
  - `ASR_MODEL_DIR`
  - `ASR_FFMPEG_EXE`
  - `ASR_CACHE_DIR`
  - `VISUAL_PYTHON_EXE`

## 6. API 概览（按当前代码）

核心接口：

- `GET /api/health`
- `POST /api/authors/candidates` 查询候选博主（支持 `author_name`/`douyin_id`）
- `POST /api/authors/videos` 按 `author_sec_uid` 拉取视频
- `POST /api/search` 搜视频（支持 `video_id` 直查、作者、抖音号等）
- `POST /api/comments/crawl/start` 异步评论抓取
- `GET /api/comments/crawl/status/{task_id}` 查询抓取进度
- `POST /api/analyze` 评论分析
- `POST /api/analyze/video-content` 视频内容分析
- `GET /api/dashboard/{video_id}` 看板数据
- `POST /api/export` 导出分析结果

扩展接口：

- `POST /api/sync/from-existing` 与外部项目联动同步
- `POST /api/comments/crawl` 同步模式抓评
- `POST /api/video-assets/import-mp4` 导入本地 mp4
- `GET /api/video-assets/status/{video_id}` 资产状态
- `GET /api/video-assets/frame` 关键帧文件
- `POST /api/sentiment/build-trainset`
- `POST /api/sentiment/finetune`
- `POST /api/sentiment/reload`
- `POST /api/sentiment/predict`

## 7. 自检

代码修改后建议执行：

```powershell
.\.venv\Scripts\python scripts\post_change_check.py
```

当前脚本会执行：

- `python -m compileall app`
- `import app.main` 导入检查

## 8. 安全与上传建议

- 不要提交 `.env`（含 Cookie / API Key）
- 不要提交 `*.db`、`models/`、`outputs/`
- 本仓库已通过 `.gitignore` 默认忽略上述敏感/运行产物

如果你怀疑密钥泄露，请立即轮换：

- 更换抖音 Cookie
- 重置模型服务 API Key

