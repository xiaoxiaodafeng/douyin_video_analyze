from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VideoCreate(BaseModel):
    video_id: str
    title: str
    desc: str = ""
    author_name: str
    author_id: str = ""
    duration: int = 0
    digg_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    share_count: int = 0
    create_time: Optional[datetime] = None
    music_name: str = ""
    video_url: str = ""


class VideoOut(VideoCreate):
    id: int

    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    comment_id: str
    video_id: str
    user_name: str = ""
    content: str
    digg_count: int = 0
    reply_count: int = 0
    create_time: Optional[datetime] = None
    ip_label: str = ""


class CommentOut(CommentCreate):
    id: int

    class Config:
        from_attributes = True




class AuthorCandidateRequest(BaseModel):
    author_name: Optional[str] = None
    douyin_id: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class AuthorVideoRequest(BaseModel):
    author_sec_uid: str
    author_name: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=10000)
    page: int = Field(default=1, ge=1, le=100000)
    sort_by: str = Field(default="create_time", pattern="^(digg_count|comment_count|create_time)$")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    fetch_all: bool = False

class SearchRequest(BaseModel):
    video_id: Optional[str] = None
    author_name: Optional[str] = None
    douyin_id: Optional[str] = None
    author_sec_uid: Optional[str] = None
    author_id: Optional[str] = None
    keyword: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=200)
    remote_fallback: bool = True


class IngestRequest(BaseModel):
    videos: list[VideoCreate] = Field(default_factory=list)
    comments: list[CommentCreate] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    video_id: str
    force_reanalyze: bool = False


class VideoInsightRequest(BaseModel):
    video_id: str


class VideoAssetImportRequest(BaseModel):
    video_id: str
    mp4_path: str
    overwrite: bool = True


class CrawlCommentsRequest(BaseModel):
    video_id: str
    comment_limit: int = Field(default=200, ge=1, le=5000)
    reply_limit: int = Field(default=50, ge=0, le=500)


class CrawlTaskStatus(BaseModel):
    task_id: str
    status: str
    stage: str = ""
    video_id: str = ""
    top_count: int = 0
    top_target: int = 0
    reply_count: int = 0
    reply_done: int = 0
    reply_total: int = 0
    comments_synced: int = 0
    message: str = ""
    error: str = ""


class AnalysisResultItem(BaseModel):
    comment_id: str
    sentiment: str
    keywords: list[str]
    topic: str
    summary: str
    suggestion: str


class ExportRequest(BaseModel):
    video_id: str
    format: str = Field(pattern="^(csv|json|excel|markdown)$")


class SyncRequest(BaseModel):
    keyword: Optional[str] = None
    author_name: Optional[str] = None
    douyin_id: Optional[str] = None
    video_url: Optional[str] = None
    comment_video_id: Optional[str] = None
    crawl_comments_for_found_videos: bool = False
    video_limit: int = Field(default=10, ge=1, le=200)
    comment_limit: int = Field(default=200, ge=1, le=5000)
    reply_limit: int = Field(default=50, ge=0, le=500)


class BuildTrainsetRequest(BaseModel):
    video_id: Optional[str] = None
    sample_size: int = Field(default=1000, ge=50, le=200000)
    strategy: str = Field(default="weak_label", pattern="^(weak_label|manual_only|hybrid)$")
    output_csv: str = "./datasets/sentiment_train.csv"
    manual_csv: Optional[str] = None


class PredictBatchRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)
