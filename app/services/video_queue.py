from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VideoJob:
    id: int
    chat_id: int
    message_id: int
    message_thread_id: int | None
    user_id: int | None
    url: str
    source: str
    attempts: int


class VideoQueueService:
    """Small PostgreSQL queue shared by Railway Lola and the PC worker."""

    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)

    def init_db(self) -> None:
        if not self.enabled:
            logger.warning("DATABASE_URL is not set; automatic video links are disabled")
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS video_jobs (
                        id BIGSERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL,
                        message_thread_id BIGINT,
                        user_id BIGINT,
                        url TEXT NOT NULL,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        leased_at TIMESTAMPTZ,
                        worker_id TEXT,
                        sent_message_id BIGINT,
                        last_error TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(chat_id, message_id)
                    );
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE video_jobs
                    ADD COLUMN IF NOT EXISTS message_thread_id BIGINT;
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_video_jobs_ready
                    ON video_jobs (status, available_at, created_at);
                    """
                )
            conn.commit()

    def enqueue(
        self,
        *,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None,
        user_id: int | None,
        url: str,
        source: str,
    ) -> int | None:
        if not self.enabled:
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_jobs (
                        chat_id,
                        message_id,
                        message_thread_id,
                        user_id,
                        url,
                        source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chat_id, message_id) DO NOTHING
                    RETURNING id;
                    """,
                    (chat_id, message_id, message_thread_id, user_id, url, source),
                )
                row = cur.fetchone()
            conn.commit()

        return int(row["id"]) if row else None

    def claim_next(
        self,
        worker_id: str,
        lease_timeout_minutes: int = 30,
        max_attempts: int = 3,
    ) -> VideoJob | None:
        if not self.enabled:
            return None

        lease_timeout_minutes = max(5, int(lease_timeout_minutes))
        max_attempts = max(1, int(max_attempts))
        with self._connect() as conn:
            with conn.cursor() as cur:
                # A worker that repeatedly dies must not bypass the retry cap
                # merely because its lease expires.
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET
                        status = 'failed',
                        leased_at = NULL,
                        worker_id = NULL,
                        last_error = COALESCE(last_error, 'lease expired at retry limit'),
                        updated_at = NOW()
                    WHERE status = 'processing'
                      AND attempts >= %s
                      AND leased_at < NOW() - (%s * INTERVAL '1 minute');
                    """,
                    (max_attempts, lease_timeout_minutes),
                )
                cur.execute(
                    """
                    WITH candidate AS (
                        SELECT id
                        FROM video_jobs
                        WHERE attempts < %s
                          AND (
                            (
                                status = 'pending'
                                AND available_at <= NOW()
                            ) OR (
                                status = 'processing'
                                AND leased_at < NOW() - (%s * INTERVAL '1 minute')
                            )
                          )
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE video_jobs AS job
                    SET
                        status = 'processing',
                        attempts = job.attempts + 1,
                        leased_at = NOW(),
                        worker_id = %s,
                        updated_at = NOW(),
                        last_error = NULL
                    FROM candidate
                    WHERE job.id = candidate.id
                    RETURNING
                        job.id,
                        job.chat_id,
                        job.message_id,
                        job.message_thread_id,
                        job.user_id,
                        job.url,
                        job.source,
                        job.attempts;
                    """,
                    (max_attempts, lease_timeout_minutes, worker_id),
                )
                row = cur.fetchone()
            conn.commit()

        if not row:
            return None
        return VideoJob(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            message_id=int(row["message_id"]),
            message_thread_id=(
                int(row["message_thread_id"])
                if row["message_thread_id"] is not None
                else None
            ),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            url=str(row["url"]),
            source=str(row["source"]),
            attempts=int(row["attempts"]),
        )

    def renew_lease(self, job_id: int, worker_id: str) -> bool:
        """Keep a long-running download/upload from being claimed twice."""

        if not self.enabled:
            return False

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET leased_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND worker_id = %s
                    RETURNING id;
                    """,
                    (job_id, worker_id),
                )
                row = cur.fetchone()
            conn.commit()
        return row is not None

    def mark_sent(self, job_id: int, sent_message_id: int, worker_id: str) -> None:
        if not self.enabled:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET
                        status = 'sent',
                        sent_message_id = %s,
                        leased_at = NULL,
                        updated_at = NOW(),
                        last_error = NULL
                    WHERE id = %s
                      AND status = 'processing'
                      AND worker_id = %s
                    RETURNING id;
                    """,
                    (sent_message_id, job_id, worker_id),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("video job lease was lost before mark_sent")

    def mark_failed(
        self,
        job_id: int,
        error: str,
        *,
        attempts: int,
        max_attempts: int = 3,
        retry_delay_seconds: int = 90,
        worker_id: str,
    ) -> None:
        if not self.enabled:
            return

        terminal = int(attempts) >= max(1, int(max_attempts))
        next_status = "failed" if terminal else "pending"
        safe_error = (error or "unknown error")[:1000]
        delay = max(10, int(retry_delay_seconds))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET
                        status = %s,
                        available_at = CASE
                            WHEN %s = 'pending' THEN NOW() + (%s * INTERVAL '1 second')
                            ELSE available_at
                        END,
                        leased_at = NULL,
                        worker_id = NULL,
                        last_error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND worker_id = %s;
                    """,
                    (next_status, next_status, delay, safe_error, job_id, worker_id),
                )
            conn.commit()

    def mark_ignored(self, job_id: int, reason: str, worker_id: str) -> None:
        if not self.enabled:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET
                        status = 'ignored',
                        leased_at = NULL,
                        worker_id = NULL,
                        last_error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND worker_id = %s;
                    """,
                    ((reason or "ignored")[:1000], job_id, worker_id),
                )
            conn.commit()
