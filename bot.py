import os
import asyncio
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from google import genai

# =========================
# CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY_1")

TZ = ZoneInfo("Asia/Tashkent")

logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """
Sen Lola ismli AI yordamchisan.
Qisqa, oddiy va tabiiy javob ber.
"""

# =========================
# DATABASE
# =========================

def db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

def init_db():
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                user_id BIGINT,
                user_name TEXT,
                day DATE,
                count INTEGER DEFAULT 0,
                UNIQUE(chat_id, user_id, day)
            )
            """)

        conn.commit()

# =========================
# GEMINI
# =========================

async def ask_gemini(text: str):

    try:
        client = genai.Client(api_key=GEMINI_KEY)

        response = client.models.generate_content(
            model="gemini-1.5-pro",
            contents=[
                {
                    "role": "user",
                    "parts": [SYSTEM_PROMPT]
                },
                {
                    "role": "user",
                    "parts": [text]
                }
            ]
        )

        return response.text.strip()

    except Exception as e:
        print(e)
        return "Keyinroq yoz 😊"

# =========================
# STATS
# =========================

def add_stat(chat_id, user_id, user_name):

    today = datetime.now(TZ).date()

    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            INSERT INTO message_stats
            (chat_id, user_id, user_name, day, count)

            VALUES (%s,%s,%s,%s,1)

            ON CONFLICT (chat_id, user_id, day)

            DO UPDATE SET
            count = message_stats.count + 1
            """, (
                chat_id,
                user_id,
                user_name,
                today
            ))

        conn.commit()

def get_stats(chat_id):

    today = datetime.now(TZ).date()

    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            SELECT user_name, count
            FROM message_stats
            WHERE chat_id=%s AND day=%s
            ORDER BY count DESC
            """, (chat_id, today))

            return cur.fetchall()

# =========================
# COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Salom 😊"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    rows = get_stats(update.effective_chat.id)

    if not rows:
        await update.message.reply_text(
            "Statistika yo'q."
        )
        return

    text = "📊 Bugungi statistika:\n\n"

    for i, row in enumerate(rows[:10], start=1):

        text += f"{i}. {row['user_name']} — {row['count']} ta\n"

    await update.message.reply_text(text)

# =========================
# MESSAGE
# =========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    text = update.message.text or ""

    # statistika
    if chat.type != "private":

        add_stat(
            chat.id,
            user.id,
            user.full_name
        )

        # faqat reply
        if not update.message.reply_to_message:
            return

        if update.message.reply_to_message.from_user.id != context.bot.id:
            return

    answer = await ask_gemini(text)

    await update.message.reply_text(answer)

# =========================
# DAILY REPORT
# =========================

async def daily_report(app):

    while True:

        now = datetime.now(TZ)

        target = datetime.combine(
            now.date(),
            time(8, 0),
            tzinfo=TZ
        )

        if now >= target:
            target += timedelta(days=1)

        await asyncio.sleep(
            (target - now).total_seconds()
        )

        print("Daily report ishladi")

# =========================
# INIT
# =========================

async def post_init(app):

    init_db()

    asyncio.create_task(
        daily_report(app)
    )

# =========================
# MAIN
# =========================

def main():

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("stats", stats)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Lola ishga tushdi...")

    app.run_polling()

if __name__ == "__main__":
    main()
