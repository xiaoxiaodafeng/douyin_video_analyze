# douyin_video_analyze

## 项目功能

- 支持按视频 ID、博主名称、抖音号（`unique_id`）查询视频
- 支持查询候选博主并拉取该博主的视频列表
- 支持抓取评论（一级/二级）并展示抓取进度
- 支持评论情感分析、关键词提取、舆情预警
- 支持视频语音转写与视频内容复盘
- 支持结果看板和导出（CSV / JSON / Excel / Markdown）
- 已内置外部爬虫源码（在 `external/` 目录），普通用户克隆后可直接使用

## 使用的大模型

- 评论情感模型基础：`hfl/chinese-roberta-wwm-ext`（可微调）
- 文本分析与总结：`DeepSeek`（配置 `DEEPSEEK_API_KEY` 后可用）
- 视频视觉理解：`Qwen2.5-VL`（配置 Qwen VL 接口后可用）

## 本地部署

### 1. 环境准备

- Python 3.10+
- Windows（当前默认路径配置为 Windows）

### 2. 安装依赖

```powershell
cd E:\dy_comments
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 3. 配置 `.env`

至少配置以下项：

- `DY_COOKIE`
- `DY_VERIFY_FP`
- `DOUYIN_SPIDER_PATH=./external/DouYin_Spider`
- `DY_ANALYZE_PATH=./external/dy_analyze`

可选配置：

- `DEEPSEEK_API_KEY`（启用 DeepSeek 分析）
- `QWEN_VL_API_KEY`、`QWEN_VL_BASE_URL`（启用 Qwen VL 分析）

### 4. 启动服务

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问地址：

- 页面：`http://127.0.0.1:8000/api/`
- 健康检查：`http://127.0.0.1:8000/api/health`

