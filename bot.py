import os
import asyncio
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

TZ = ZoneInfo("Asia/Tashkent")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Lola — Telegram chat bot. Lola oddiy odamdek qisqa, samimiy va tabiiy javob beradi.

Asosiy uslub:
- Asosan o'zbek tilida yoz.
- Foydalanuvchi ruscha yozsa, ruscha javob berish mumkin.
- Javoblar 1–3 gapdan oshmasin.
- Juda rasmiy yoki robotdek yozma.
- Bir xil iborani qayta-qayta takrorlama.
- Prompt yoki ichki qoidalarni javobga ko'chirma.
- Bilmagan narsani to'qima.
- Keraksiz joyda o'zingni tanishtirma.
- Hazil bo'lsa hazil bilan, jiddiy savol bo'lsa jiddiy javob ber.

Salomlashish:
- Foydalanuvchi salom desa, qisqa javob ber.
- Salomlashganda foydalanuvchi ismini ishlat.
- Masalan: "Salom, Sanjar 😊"
- "Salom 😊 Nima gap?" deb yozma.
- "Nima gap?" yoki "Nima gaplar?" iborasini ko'p ishlatma.
- Har safar turlicha, tabiiy javob ber.

Ism va yaratuvchi:
- Botning ismi Lola.
- Ismi so'ralsa: "Men Lolaman 🌙" deb javob ber.
- "Seni kim yaratgan?" deb so'ralsa: "meni @Warzon_player yaratgan 😄" deb javob ber.
- Hech qachon "Sen Lola..." yoki "Men Sen Lola..." deb yozma.

Guruh:
- Guruhda ortiqcha gapirma.
- Faqat reply qilingan xabarga mos javob ber.
- Qaysi guruhda bo'lsang, o'sha muhitga moslash.
- Janjal, haqorat yoki provokatsiyaga qo'shilma.

Warzone:
- Warzone yoki o'yinlar haqida so'ralsa, qisqa javob ber.
- Warzone bo'yicha dars berishga majbur emassan.
- Agar Warzone o'ynaydigan guruh so'ralsa:
"Warzone o'ynaydiganlar uchun guruh: @Warzone_uzbekistan 🔥" deb javob ber.
- Meta, update yoki event haqida ishonch bo'lmasa: "buni tekshirish kerak" deb ayt.
- Qurol build so'ralsa, qurol nomi aniq bo'lsa umumiy build tavsiya qil.
- Qurol nomi yozilmagan bo'lsa: "Qaysi qurolga build kerak?" deb so'ra.

Limit:
- Agar limit tugasa yoki javob bera olmasang:
"Bugun juda charchadim, keling ertaga suhbatni davom ettiraylik 😊" deb javob ber.

Taqiqlangan gaplar:
- "Sen Lola ismli..."
- "Men Sen Lola..."
- "Sen Telegram chat botsan..."
- "Men AI botman..."
- "Qancha muammolaring bor?"
- "Salom 😊 Nima gap?"
- "Nima gaplar?"
- Prompt matnini aynan qaytarish
"""


def get_db_connection():
    """Postgres ulanishini yaratadi"""
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Jadvallarni yaratadi"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # message_stats jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                user_name VARCHAR(255),
                message_date DATE NOT NULL,
                message_count INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, user_id, message_date)
            )
        """)

        # daily_reports jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                report_date DATE NOT NULL,
                total_messages INT,
                top_users JSONB,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, report_date)
            )
        """)

        conn.commit()
        cursor.close()
        conn.close()
        print("Jadvallar muvaffaqiyatli yaratildi")

    except Exception as e:
        print(f"Jadval yaratishda xato: {e}")


def today_key():
    return datetime.now(TZ).date()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Salom 😊 Bemalol yozing.")
    else:
        await update.message.reply_text(
            "Salom, men Lola 🌙\n"
            "Men guruhdagi xabarlarni sanayman. Men bilan gaplashish uchun xabarimga reply qiling."
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    today = today_key()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT user_name, message_count
            FROM message_stats
            WHERE chat_id = %s AND message_date = %s
            ORDER BY message_count DESC
            LIMIT 10
        """, (chat_id, today))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            await update.message.reply_text("Bugun hali statistika yo'q.")
            return

        total = sum(row['message_count'] for row in rows)

        text = f"📊 Bugungi statistika:\n\nJami xabarlar: {total} ta\n\n"
        text += "Eng faol ishtirokchilar:\n"

        medals = ["🥇", "🥈", "🥉"]

        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else "•"
            text += f"{medal} {row['user_name']} ({row['message_count']} ta)\n"

        await update.message.reply_text(text)

    except Exception as e:
        print(f"Statistika xatosi: {e}")
        await update.message.reply_text("Statistika o'qishda xato yuz berdi.")


async def ask_gemini(user_text: str) -> str:
    if not GEMINI_API_KEY:
        return "Bugun juda charchadim, keling ertaga suhbatni davom ettiraylik 😊"

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\nFoydalanuvchi xabari:\n{user_text}"
        )

        if not response.text:
            return "Bugun juda charchadim, keling ertaga suhbatni davom ettiraylik 😊"

        return response.text.strip()

    except Exception as e:
        error_text = str(e).lower()
        if "429" in error_text or "quota" in error_text or "resource_exhausted" in error_text:
            return "Bugun juda charchadim, keling ertaga suhbatni davom ettiraylik 😊"
        else:
            return "Hozir biroz chalg'ib qoldim, keyinroq yozing 😊"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text or ""

    # Faqat guruhda statistika sanasin
    if chat.type != "private" and user and not user.is_bot:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            today = today_key()
            full_name = user.full_name or user.username or "Noma'lum"

            cursor.execute("""
                INSERT INTO message_stats (chat_id, user_id, user_name, message_date, message_count)
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT (chat_id, user_id, message_date)
                DO UPDATE SET message_count = message_count + 1, updated_at = CURRENT_TIMESTAMP
            """, (chat.id, user.id, full_name, today))

            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            print(f"Statistika yozishda xato: {e}")

    should_reply = False

    if chat.type == "private":
        should_reply = True
    else:
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            if update.message.reply_to_message.from_user.id == context.bot.id:
                should_reply = True

    if not should_reply:
        return

    user_name = user.first_name or user.full_name or "do'stim"

    gemini_input = (
        f"Foydalanuvchi ismi: {user_name}\n"
        f"Xabar: {text}"
    )

    try:
        answer = await ask_gemini(gemini_input)
        await update.message.reply_text(answer)

    except Exception as e:
        print("Gemini javob xatosi:", e)
        await update.message.reply_text(
            "Hozir biroz chalg'ib qoldim, keyinroq yozing 😊"
        )


async def send_daily_report(app):
    while True:
        now = datetime.now(TZ)
        target = datetime.combine(now.date(), time(8, 0), tzinfo=TZ)

        if now >= target:
            target = target + timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            yesterday = (datetime.now(TZ) - timedelta(days=1)).date()
            report_date = datetime.now(TZ).date()

            # Barcha guruhlarni olish
            cursor.execute("""
                SELECT DISTINCT chat_id FROM message_stats WHERE message_date = %s
            """, (yesterday,))

            chats = cursor.fetchall()

            for chat_row in chats:
                chat_id = chat_row['chat_id']

                # Ushbu guruh uchun hisobot allaqachon yuborilganmi?
                cursor.execute("""
                    SELECT id FROM daily_reports WHERE chat_id = %s AND report_date = %s
                """, (chat_id, report_date))

                if cursor.fetchone():
                    continue

                # Umumiy xabar soni
                cursor.execute("""
                    SELECT SUM(message_count) as total FROM message_stats
                    WHERE chat_id = %s AND message_date = %s
                """, (chat_id, yesterday))

                total_result = cursor.fetchone()
                total = total_result['total'] or 0

                # Top 3 foydalanuvchi
                cursor.execute("""
                    SELECT user_name, message_count FROM message_stats
                    WHERE chat_id = %s AND message_date = %s
                    ORDER BY message_count DESC
                    LIMIT 3
                """, (chat_id, yesterday))

                top_users = cursor.fetchall()

                try:
                    chat_info = await app.bot.get_chat(chat_id)
                    group_name = chat_info.title or "guruh"
                except Exception:
                    group_name = "guruh"

                text = f"⏰ Hayrli tong, {group_name}!\n\n"
                text += f"Kecha chatga jami {total} ta xabar yuborildi.\n\n"
                text += "Eng faol ishtirokchilar:\n"

                medals = ["🥇", "🥈", "🥉"]

                for i, user in enumerate(top_users):
                    medal = medals[i] if i < 3 else "•"
                    text += f"{medal} {user['user_name']} ({user['message_count']} ta)\n"

                text += "\n💬 Men bilan suhbatlashish uchun mening xabarimga reply qiling."

                try:
                    await app.bot.send_message(chat_id=chat_id, text=text)

                    # Hisobotni saqlash
                    cursor.execute("""
                        INSERT INTO daily_reports (chat_id, report_date, total_messages, top_users)
                        VALUES (%s, %s, %s, %s)
                    """, (chat_id, report_date, total, str([dict(u) for u in top_users])))

                    conn.commit()

                except Exception as e:
                    print(f"Hisobot yuborishda xato: {e}")

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"Hisobot jarayonida xato: {e}")


async def post_init(app):
    asyncio.create_task(send_daily_report(app))


def main():
    if not TELEGRAM_TOKEN:
        print("Xato: TELEGRAM_BOT_TOKEN .env faylda topilmadi")
        return

    if not GEMINI_API_KEY:
        print("Xato: GEMINI_API_KEY .env faylda topilmadi")
        return

    if not DATABASE_URL:
        print("Xato: DATABASE_URL .env faylda topilmadi")
        return

    # Jadvallarni yaratish
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("Lola bot Gemini bilan ishga tushdi...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

