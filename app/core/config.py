from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Dy Comments Analyze"
    database_url: str = "sqlite:///./dy_comments.db"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    qwen_vl_api_key: str = ""
    qwen_vl_base_url: str = ""
    qwen_vl_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    qwen_vl_max_frames: int = 6

    topic_cluster_count: int = 4
    sensitive_keywords: str = "诈骗,造假,维权,投诉,翻车,虚假宣传,退货,封号,违法"

    # Existing project integration
    douyin_spider_path: str = r"E:\douyin\DouYin_Spider"
    dy_analyze_path: str = r"E:\dy_analyze"
    dy_cookie: str = ""
    dy_verify_fp: str = ""
    dy_search_template_url: str = ""
    dy_uifid: str = ""

    sync_video_limit_per_keyword: int = 10
    sync_comment_limit: int = 500
    sync_reply_limit: int = 50

    # Sentiment model runtime
    sentiment_model_dir: str = "./models/roberta_sentiment_3cls"
    sentiment_base_model: str = "hfl/chinese-roberta-wwm-ext"
    sentiment_max_length: int = 256

    # Local ASR / video analysis runtime
    asr_python_exe: str = r"D:\miniconda\envs\dy_asr_test\python.exe"
    asr_model_dir: str = r"E:\asr_models\iic\SenseVoiceSmall"
    asr_ffmpeg_exe: str = r"D:\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
    asr_cache_dir: str = "./outputs/asr_cache"
    visual_python_exe: str = r"D:\miniconda\python.exe"


settings = Settings()
