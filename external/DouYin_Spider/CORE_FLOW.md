# DouYin_Spider 核心流程与逻辑

## 1. 总体架构

项目分成四层：

1. 入口调度层：`main.py`
2. 认证与签名层：`utils/common_util.py`、`builder/auth.py`、`builder/params.py`、`utils/dy_util.py`
3. API 抓取层：`dy_apis/douyin_api.py`
4. 数据处理与落盘层：`utils/data_util.py`

---

## 2. 运行主链路（从启动到落盘）

### Step 1: 初始化

在 `main.py` 中启动后，先执行：

- `init()`（`utils/common_util.py`）
  - 读取 `.env` 里的 `DY_COOKIES`、`DY_LIVE_COOKIES`
  - 构建 `DouyinAuth` 对象
  - 创建输出目录：
    - `datas/media_datas`
    - `datas/excel_datas`

### Step 2: 选择抓取模式

`Data_Spider` 提供三类主入口：

1. `spider_some_work`：抓指定作品链接
2. `spider_user_all_work`：抓某个用户全部作品
3. `spider_some_search_work`：按关键词抓搜索结果

### Step 3: 组装请求参数与签名

请求前会拼接一组关键参数：

- `webid`：由 `with_web_id()` 生成
- `msToken`：来自 cookie 或随机生成
- `verifyFp / fp`：通常来自 `s_v_web_id`
- `a_bogus`：由 `with_a_bogus()` 计算

其中 `a_bogus` 是通过 JS 算法算出来的，入口在：

- `utils/dy_util.py` -> `generate_a_bogus()`
- 依赖脚本：`static/dy_ab.js`

### Step 4: 调用 Douyin Web API

核心 API 在 `dy_apis/douyin_api.py`，典型包括：

- 用户主页信息：`get_user_info()`
- 用户作品分页：`get_user_work_info()`
- 用户作品全量：`get_user_all_work_info()`（循环 `max_cursor` 直到 `has_more != 1`）
- 作品详情：`get_work_info()`
- 搜索：`search_general_work()`、`search_some_general_work()`

### Step 5: 统一字段与保存

API 返回后会统一进入：

- `handle_work_info()`：标准化字段（作者、统计、视频地址、话题、发布时间等）
- `download_work()`：按作品类型下载媒体
- `save_to_xlsx()`：导出 Excel

---

## 3. 分页逻辑（用户作品）

`get_user_all_work_info()` 的核心循环逻辑：

1. 初始 `max_cursor = "0"`
2. 调 `get_user_work_info(auth, user_url, max_cursor)`
3. 追加 `aweme_list`
4. 更新 `max_cursor = res_json["max_cursor"]`
5. 若 `has_more != 1` 则结束

这是全量抓取的关键。

---

## 4. 为什么必须要 Cookie

项目很多接口依赖登录态和风控参数，至少要保证：

- `sessionid / sid_tt / uid_tt`（登录态）
- `s_v_web_id`（指纹参数）
- `msToken`（请求参数）

缺失时常见现象：

- `status_code` 非 0
- 返回空 body
- 命中 `anonymous` 风控

---

## 5. MP4 与 MP3 链路（你当前在用）

你当前的媒体处理链路是：

1. 先从作品列表提取每条视频 URL（`play_url` / `download_url`）
2. 保存为 `datas/user_xxx_mp4_data.json`
3. 用 `download_mp4_to_mp3.py`：
   - 下载 MP4
   - 调 `ffmpeg` 转 MP3
   - 输出转换报告 `datas/mp3_convert_report.json`

---

## 6. 你最常改的几个位置

如果你想做定制，优先改这里：

1. `main.py`：改抓取入口与参数
2. `dy_apis/douyin_api.py`：加/改接口
3. `utils/data_util.py`：改字段映射与存储格式
4. `download_mp4_to_mp3.py`：改下载与转码策略

---

## 7. 一句话总结

这个项目本质是：**用登录态 + 参数签名绕过 Web 风控，调用 Douyin Web API 拉取数据，再标准化并导出媒体/Excel**。
