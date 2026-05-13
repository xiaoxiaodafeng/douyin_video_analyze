from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class VideoInfo(Base):
    __tablename__ = "video_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    desc: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(128), index=True)
    author_id: Mapped[str] = mapped_column(String(64), default="")
    duration: Mapped[int] = mapped_column(Integer, default=0)
    digg_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    create_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    music_name: Mapped[str] = mapped_column(String(255), default="")
    video_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    comments: Mapped[list["CommentInfo"]] = relationship("CommentInfo", back_populates="video")


class CommentInfo(Base):
    __tablename__ = "comment_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    video_id: Mapped[str] = mapped_column(String(64), ForeignKey("video_info.video_id"), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text)
    digg_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    create_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    ip_label: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    video: Mapped["VideoInfo"] = relationship("VideoInfo", back_populates="comments")
    analysis: Mapped[list["AnalysisResult"]] = relationship("AnalysisResult", back_populates="comment")


class AnalysisResult(Base):
    __tablename__ = "analysis_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(String(64), ForeignKey("comment_info.comment_id"), index=True)
    sentiment: Mapped[str] = mapped_column(String(16), index=True)
    keywords: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(String(128), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    comment: Mapped["CommentInfo"] = relationship("CommentInfo", back_populates="analysis")
