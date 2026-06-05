from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from aiogram import Bot
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")


class StatsService:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def init_db(self) -> None:
        if not self.enabled:
            logger.warning("DATABASE_URL is not set; group stats are disabled")
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS message_stats (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        user_name TEXT NOT NULL,
                        day DATE NOT NULL,
                        count INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(chat_id, user_id, day)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_reports (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        report_day DATE NOT NULL,
                        UNIQUE(chat_id, report_day)
                    );
                    """
                )
            conn.commit()

    def add_message_stat(self, chat_id: int, user_id: int, user_name: str) -> None:
        if not self.enabled:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO message_stats (chat_id, user_id, user_name, day, count)
                    VALUES (%s, %s, %s, %s, 1)
                    ON CONFLICT (chat_id, user_id, day)
                    DO UPDATE SET
                        count = message_stats.count + 1,
                        user_name = EXCLUDED.user_name;
                    """,
                    (chat_id, user_id, user_name, today_key()),
                )
            conn.commit()

    def get_stats(self, chat_id: int, day) -> list[dict]:
        if not self.enabled:
            return []

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, user_name, count
                    FROM message_stats
                    WHERE chat_id = %s AND day = %s
                    ORDER BY count DESC;
                    """,
                    (chat_id, day),
                )
                return list(cur.fetchall())

    def get_stats_range(self, chat_id: int, start_day, end_day) -> list[dict]:
        if not self.enabled:
            return []

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, user_name, SUM(count) AS count
                    FROM message_stats
                    WHERE chat_id = %s AND day >= %s AND day <= %s
                    GROUP BY user_id, user_name
                    ORDER BY count DESC;
                    """,
                    (chat_id, start_day, end_day),
                )
                return list(cur.fetchall())

    def get_all_chat_ids(self) -> list[int]:
        if not self.enabled:
            return []

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT chat_id FROM message_stats;")
                return [row["chat_id"] for row in cur.fetchall()]

    def was_report_sent(self, chat_id: int, report_day) -> bool:
        if not self.enabled:
            return True

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM daily_reports
                    WHERE chat_id = %s AND report_day = %s;
                    """,
                    (chat_id, report_day),
                )
                return cur.fetchone() is not None

    def mark_report_sent(self, chat_id: int, report_day) -> None:
        if not self.enabled:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO daily_reports (chat_id, report_day)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id, report_day) DO NOTHING;
                    """,
                    (chat_id, report_day),
                )
            conn.commit()

    def _connect(self):
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)


def today_key():
    return datetime.now(TZ).date()


def yesterday_key():
    return (datetime.now(TZ) - timedelta(days=1)).date()


def format_stats(title: str, total: int, rows: list[dict]) -> str:
    text = f"{title}:\n\nJami xabarlar: {total} ta\n\nEng faol ishtirokchilar:\n"
    medals = ["1.", "2.", "3."]
    for index, row in enumerate(rows[:3]):
        text += f"{medals[index]} {row['user_name']} ({row['count']} ta)\n"
    return text


async def send_daily_reports(bot: Bot, stats_service: StatsService) -> None:
    while True:
        now = datetime.now(TZ)
        target = datetime.combine(now.date(), time(8, 0), tzinfo=TZ)
        if now >= target:
            target += timedelta(days=1)

        await asyncio.sleep((target - now).total_seconds())

        try:
            chat_ids = await asyncio.to_thread(stats_service.get_all_chat_ids)
        except Exception:
            logger.exception("Failed to get chat ids for daily report")
            continue

        report_day = today_key()
        stat_day = yesterday_key()

        for chat_id in chat_ids:
            try:
                already_sent = await asyncio.to_thread(
                    stats_service.was_report_sent,
                    chat_id,
                    report_day,
                )
                if already_sent:
                    continue

                rows = await asyncio.to_thread(stats_service.get_stats, chat_id, stat_day)
                if not rows:
                    continue

                total = sum(int(row["count"]) for row in rows)
                chat_info = await bot.get_chat(int(chat_id))
                group_name = chat_info.title or "guruh"
                text = format_stats(f"Hayrli tong, {group_name}. Kechagi statistika", total, rows)
                text += "\nMen bilan gaplashish uchun xabarimga reply qiling."

                await bot.send_message(chat_id=int(chat_id), text=text)
                await asyncio.to_thread(stats_service.mark_report_sent, chat_id, report_day)
            except Exception:
                logger.exception("Failed to send daily report for chat %s", chat_id)
