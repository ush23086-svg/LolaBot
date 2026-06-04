import os
import re
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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

# ==================== KONFIGURATSIYA ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# 3 TA GEMINI KEY
GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
]
GEMINI_KEYS = [key for key in GEMINI_KEYS if key]  # Bo'sh bo'lganlarni olib tashla

TZ = ZoneInfo("Asia/Tashkent")
VIDEO_FILENAME = "SaveVid_Net_AQNKnUIQh4au0ukBFQeeBEE9GNtzkOFvNFXUDTipfHHr9qwI5m8RUCHhFxyUIY.mp4"
VIDEO_SONG_FILENAME = "video_2026-05-31_21-36-53.mp4"

CODMUNITY_BASE = "https://codmunity.gg"
CODMUNITY_URLS = {
    "warzone": f"{CODMUNITY_BASE}/warzone",
    "mw3": f"{CODMUNITY_BASE}/mw3",
}

CODE_RE = re.compile(r"^[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){1,}$")
LOADOUT_TYPES = {"long range", "close range", "sniper"}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ==================== QATTIQ SYSTEM PROMPT (TO'QIMAYDI) ====================
SYSTEM_PROMPT = """
Sen Lola. QATTIQ QOIDALAR:

1. Agar bilmasang, "Buni bilmayman" deb javob ber. HECH QACHON O'ZINDAN TO'QIMA.
2. 1-2 jumla bilan javob ber. Uzoq gapirma.
3. Savolga faqat aniq javob ber. Keraksiz tushuntirish qo'shma.
4. Emoji faqat bitta ishlat.

TIL:
- O'zbekcha so'ralsa — o'zbekcha
- Ruscha so'ralsa — ruscha

TAQIQLAR:
- "Odatda", "ehtimol", "taxminan" kabi so'zlarni ishlatma
- Bilmasang, "Bilmayman" de

Endi ishla.
"""

# ==================== GEMINI (3 TA KEY, QISQA, TO'QIMAYDI) ====================
async def ask_gemini(user_text: str) -> str:
    """3 ta key bilan ishlaydi, bilmasa bilmayman deydi"""
    if not GEMINI_KEYS:
        return "Gemini kaliti topilmadi."

    for i, api_key in enumerate(GEMINI_KEYS, 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{SYSTEM_PROMPT}\n\nFoydalanuvchi: {user_text}",
                config={
                    "max_output_tokens": 100,
                    "temperature": 0.3,
                }
            )
            
            if response and response.text:
                answer = response.text.strip()
                # Agar javob ma'nosiz yoki uzun bo'lsa
                if len(answer) < 2 or len(answer) > 300:
                    continue
                # To'qima so'zlar bo'lsa rad et
                bad_words = ["odatda", "ehtimol", "taxminan", "maybe", "probably"]
                if any(word in answer.lower() for word in bad_words):
                    continue
                return answer
                
        except Exception as e:
            error_msg = str(e).lower()
            logging.warning(f"Gemini key {i} xatosi: {error_msg[:50]}")
            if "429" in error_msg or "quota" in error_msg:
                continue
            if "resource_exhausted" in error_msg:
                continue
            continue
    
    return "Buni bilmayman. 😊"

# ==================== DATABASE ====================
def db_connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS message_stats (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    user_name TEXT NOT NULL,
                    day DATE NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(chat_id, user_id, day)
                );
            """)
        conn.commit()

def add_message_stat(chat_id: int, user_id: int, user_name: str):
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO message_stats (chat_id, user_id, user_name, day, count)
                    VALUES (%s, %s, %s, %s, 1)
                    ON CONFLICT (chat_id, user_id, day)
                    DO UPDATE SET count = message_stats.count + 1;
                """, (chat_id, user_id, user_name, datetime.now(TZ).date()))
            conn.commit()
    except Exception as e:
        logging.error(f"DB xatosi: {e}")

def get_stats(chat_id: int, day):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_name, count
                FROM message_stats
                WHERE chat_id = %s AND day = %s
                ORDER BY count DESC
                LIMIT 5;
            """, (chat_id, day))
            return cur.fetchall()

# ==================== CODMUNITY PARSER ====================
def clean_line(line: str) -> str:
    line = line.replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", line)

def codmunity_lines(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return [clean_line(line) for line in soup.get_text("\n").splitlines() if clean_line(line)]
    except Exception as e:
        logging.error(f"CODMunity xatosi: {e}")
        return []

def parse_meta_weapons(game: str, limit: int = 3):
    lines = codmunity_lines(CODMUNITY_URLS[game])
    weapons = []
    seen = set()

    for i, line in enumerate(lines):
        if not CODE_RE.match(line):
            continue
        
        code = line
        weapon_name = ""
        loadout_type = ""
        
        for j in range(i - 1, max(i - 10, 0), -1):
            candidate = lines[j].strip()
            lowered = candidate.lower()
            if not loadout_type and lowered in LOADOUT_TYPES:
                loadout_type = candidate
            if not weapon_name and len(candidate) > 2 and not CODE_RE.match(candidate):
                if not any(skip in lowered for skip in ["meta", "good", "viable", "pick"]):
                    weapon_name = candidate
                    break
        
        if weapon_name and weapon_name not in seen:
            seen.add(weapon_name)
            weapons.append({
                "name": weapon_name,
                "type": loadout_type,
                "code": code,
            })
        
        if len(weapons) >= limit:
            break
    
    return weapons

# ==================== HANDLERLAR ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom, men Lola! 😊")

async def lola_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(VIDEO_FILENAME, "rb") as f:
            await update.message.reply_video(video=f)
    except:
        await update.message.reply_text("😊")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("Statistika faqat guruhlar uchun.")
        return
    
    rows = get_stats(chat.id, datetime.now(TZ).date())
    if not rows:
        await update.message.reply_text("Bugun hali statistika yo'q.")
        return
    
    total = sum(row["count"] for row in rows)
    text = f"📊 Bugungi statistika ({total} ta xabar):\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows[:3]):
        text += f"{medals[i]} {row['user_name']}: {row['count']} ta\n"
    await update.message.reply_text(text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text or ""
    
    if not text.strip():
        return
    
    # Guruhda faqat reply qilingan xabarga javob ber
    if chat.type != "private":
        reply_to = update.message.reply_to_message
        if not reply_to or reply_to.from_user.id != context.bot.id:
            return
        if user and not user.is_bot:
            name = user.full_name or user.username or "Noma'lum"
            add_message_stat(chat.id, user.id, name)
    
    # "kul" -> video
    if text.lower().strip() == "kul":
        try:
            with open(VIDEO_FILENAME, "rb") as f:
                await update.message.reply_video(video=f)
        except:
            await update.message.reply_text("😄")
        return
    
    # Qo'shiq so'rash
    if any(w in text.lower() for w in ["qo'shiq", "ashula", "kuyla", "song"]):
        try:
            with open(VIDEO_SONG_FILENAME, "rb") as f:
                await update.message.reply_video(video=f)
        except:
            await update.message.reply_text("🎵")
        return
    
    # CODMunity meta so'rash
    if "meta ber" in text.lower() or ("meta" in text.lower() and "warzone" in text.lower()):
        game = "warzone"
        if "mw3" in text.lower():
            game = "mw3"
        
        weapons = parse_meta_weapons(game, limit=3)
        
        if weapons:
            msg = "🎯 CODMunity dan meta qurollar:\n\n"
            for i, w in enumerate(weapons, 1):
                msg += f"{i}. {w['name']}"
                if w['type']:
                    msg += f" ({w['type']})"
                msg += f"\n   Kod: {w['code']}\n\n"
            await update.message.reply_text(msg)
            context.chat_data["last_weapons"] = weapons
        else:
            await update.message.reply_text("CODMunity dan ma'lumot kelmadi. Keyinroq urinib ko'ring. 😅")
        return
    
    # Kod so'rash (1, 2, 3)
    if text.strip() in ["1", "2", "3"] and "last_weapons" in context.chat_data:
        idx = int(text.strip()) - 1
        weapons = context.chat_data["last_weapons"]
        if 0 <= idx < len(weapons):
            await update.message.reply_text(weapons[idx]["code"])
            return
    
    # Gemini ga yubor (to'qimaydi, bilmasa bilmayman deydi)
    answer = await ask_gemini(text)
    await update.message.reply_text(answer)

# ==================== ASOSIY ====================
async def post_init(app):
    init_db()
    logging.info("✅ Lola bot ishga tushdi! (3 ta Gemini key bilan)")

def main():
    if not TELEGRAM_TOKEN:
        print("❌ Xato: TELEGRAM_BOT_TOKEN topilmadi")
        return
    if not DATABASE_URL:
        print("❌ Xato: DATABASE_URL topilmadi")
        return
    if not GEMINI_KEYS:
        print("❌ Xato: Hech qanday Gemini API KEY topilmadi")
        return
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lola", lola_video))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"✅ Lola bot ishga tushdi! ({len(GEMINI_KEYS)} ta Gemini key bilan)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
