from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _has_legacy_bigint_pk(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cur.fetchone():
        return False
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = cur.fetchall()
    id_col = next((c for c in cols if c[1] == "id"), None)
    return bool(id_col and str(id_col[2]).upper() == "BIGINT")


def _rebuild_core_tables_with_integer_pk(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE video_info__new (
            id INTEGER NOT NULL PRIMARY KEY,
            video_id VARCHAR(64) NOT NULL,
            title VARCHAR(255) NOT NULL,
            "desc" TEXT NOT NULL,
            author_name VARCHAR(128) NOT NULL,
            author_id VARCHAR(64) NOT NULL,
            duration INTEGER NOT NULL,
            digg_count INTEGER NOT NULL,
            comment_count INTEGER NOT NULL,
            collect_count INTEGER NOT NULL,
            share_count INTEGER NOT NULL,
            create_time DATETIME,
            music_name VARCHAR(255) NOT NULL,
            video_url VARCHAR(512) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        );

        INSERT INTO video_info__new (
            id, video_id, title, "desc", author_name, author_id, duration, digg_count,
            comment_count, collect_count, share_count, create_time, music_name, video_url, created_at
        )
        SELECT
            id, video_id, title, "desc", author_name, author_id, duration, digg_count,
            comment_count, collect_count, share_count, create_time, music_name, video_url, created_at
        FROM video_info;

        DROP TABLE video_info;
        ALTER TABLE video_info__new RENAME TO video_info;
        CREATE UNIQUE INDEX ix_video_info_video_id ON video_info (video_id);
        CREATE INDEX ix_video_info_author_name ON video_info (author_name);

        CREATE TABLE comment_info__new (
            id INTEGER NOT NULL PRIMARY KEY,
            comment_id VARCHAR(64) NOT NULL,
            video_id VARCHAR(64) NOT NULL,
            user_name VARCHAR(128) NOT NULL,
            content TEXT NOT NULL,
            digg_count INTEGER NOT NULL,
            reply_count INTEGER NOT NULL,
            create_time DATETIME,
            ip_label VARCHAR(64) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            FOREIGN KEY(video_id) REFERENCES video_info (video_id)
        );

        INSERT INTO comment_info__new (
            id, comment_id, video_id, user_name, content, digg_count, reply_count, create_time, ip_label, created_at
        )
        SELECT
            id, comment_id, video_id, user_name, content, digg_count, reply_count, create_time, ip_label, created_at
        FROM comment_info;

        DROP TABLE comment_info;
        ALTER TABLE comment_info__new RENAME TO comment_info;
        CREATE UNIQUE INDEX ix_comment_info_comment_id ON comment_info (comment_id);
        CREATE INDEX ix_comment_info_video_id ON comment_info (video_id);

        CREATE TABLE analysis_result__new (
            id INTEGER NOT NULL PRIMARY KEY,
            comment_id VARCHAR(64) NOT NULL,
            sentiment VARCHAR(16) NOT NULL,
            keywords TEXT NOT NULL,
            topic VARCHAR(128) NOT NULL,
            summary TEXT NOT NULL,
            suggestion TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            FOREIGN KEY(comment_id) REFERENCES comment_info (comment_id)
        );

        INSERT INTO analysis_result__new (
            id, comment_id, sentiment, keywords, topic, summary, suggestion, created_at
        )
        SELECT
            id, comment_id, sentiment, keywords, topic, summary, suggestion, created_at
        FROM analysis_result;

        DROP TABLE analysis_result;
        ALTER TABLE analysis_result__new RENAME TO analysis_result;
        CREATE INDEX ix_analysis_result_comment_id ON analysis_result (comment_id);
        CREATE INDEX ix_analysis_result_sentiment ON analysis_result (sentiment);
        """
    )


def migrate_legacy_sqlite_schema() -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        return

    db_file = Path(db_path)
    if not db_file.is_absolute():
        db_file = (Path.cwd() / db_file).resolve()
    if not db_file.exists():
        return

    conn = sqlite3.connect(str(db_file))
    try:
        cur = conn.cursor()
        has_legacy = any(
            _has_legacy_bigint_pk(cur, table_name)
            for table_name in ("video_info", "comment_info", "analysis_result")
        )
        if not has_legacy:
            return

        backup_name = f"{db_file.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_file = db_file.with_name(backup_name)
        shutil.copy2(db_file, backup_file)

        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN IMMEDIATE")
        _rebuild_core_tables_with_integer_pk(cur)
        conn.commit()
        cur.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
