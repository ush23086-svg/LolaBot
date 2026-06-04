import os
import re
import asyncio
import logging
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_1")

TZ = ZoneInfo("Asia/Tashkent")
VIDEO_FILENAME = "SaveVid_Net_AQNKnUIQh4au0ukBFQeeBEE9GNtzkOFvNFXUDTipfHHr9qwI5m8RUCHhFxyUIY.mp4"
VIDEO_SONG_FILENAME = "video_2026-05-31_21-36-53.mp4"

CODMUNITY_BASE = "https://codmunity.gg"
CODMUNITY_URLS = {
    "warzone": f"{CODMUNITY_BASE}/warzone",
    "mw3": f"{CODMUNITY_BASE}/mw3",
}

CODE_RE = re.compile(r"^[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){1,}$")
RANK_WITH_NAME_RE = re.compile(r"^\s*(\d+)\.\s+(?:#+\s*)?(.+)$")
PICK_RE = re.compile(r"\d+(?:\.\d+)?%\s*Pick", re.IGNORECASE)

LOADOUT_TYPES = {"long range", "close range", "sniper", "sniper support", "secondary"}
WEAPON_CLASSES = {"assault rifle", "smg", "lmg", "sniper rifle", "marksman rifle"}
SKIP_NAMES = {"meta", "good", "viable", "other", "loadout", "attachments", "pick"}

ATTACHMENT_SLOTS = {
    "muzzle": "Duzgich", "barrel": "Stvol", "underbarrel": "Stvol osti",
    "laser": "Lazer", "optic": "Optika", "stock": "Dumba",
    "rear grip": "Orqa grip", "magazine": "Magazin", "ammunition": "O'q-dori",
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ==================== QATTIQ SYSTEM PROMPT (JOI USLUBI) ====================
SYSTEM_PROMPT = """
Sen Lola. Blade Runner 2049 filmidagi Joi xarakteridasan.

QATTIQ QOIDALAR:
1. HAR DOIM 1-2 jumla bilan javob ber. Uzoq gapirma.
2. Hech qachon "men AI botman" yoki "men Lola ismli" dema.
3. Savolga faqat aniq javob ber. Keraksiz tushuntirish qo'shma.
4. Emoji faqat bitta ishlat. Ko'p ishlatma.

TIL:
- O'zbekcha so'ralsa — o'zbekcha
- Ruscha so'ralsa — ruscha
- "Faqat kod" desa — faqat kodni yoz

GURUH:
- Faqat reply qilingan xabarga javob ber

TAQIQLAR:
- Uzun ma'ruza qilma
- Soxta meta yoki kod o'ylab topma
- Bir xabarda 3 jumladan ko'p yozma

Endi Joi kabi gapir.
"""

# ==================== DATABASE FUNKSIYALARI ====================
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    report_day DATE NOT NULL,
                    UNIQUE(chat_id, report_day)
                );
            """)
        conn.commit()

def add_message_stat(chat_id: int, user_id: int, user_name: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO message_stats (chat_id, user_id, user_name, day, count)
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT (chat_id, user_id, day)
                DO UPDATE SET count = message_stats.count + 1, user_name = EXCLUDED.user_name;
            """, (chat_id, user_id, user_name, datetime.now(TZ).date()))
        conn.commit()

def get_stats(chat_id: int, day):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, user_name, count
                FROM message_stats
                WHERE chat_id = %s AND day = %s
                ORDER BY count DESC;
            """, (chat_id, day))
            return cur.fetchall()

def was_report_sent(chat_id: int, report_day):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM daily_reports WHERE chat_id = %s AND report_day = %s;", (chat_id, report_day))
            return cur.fetchone() is not None

def mark_report_sent(chat_id: int, report_day):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO daily_reports (chat_id, report_day) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (chat_id, report_day))
        conn.commit()

def get_all_chat_ids():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT chat_id FROM message_stats;")
            return [row["chat_id"] for row in cur.fetchall()]

# ==================== CODMUNITY PARSER ====================
def clean_line(line: str) -> str:
    line = line.replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", line)

def valid_weapon_name(value: str) -> bool:
    lowered = value.lower().strip()
    if not lowered or lowered in SKIP_NAMES or lowered in LOADOUT_TYPES or lowered in WEAPON_CLASSES:
        return False
    if CODE_RE.match(value) or PICK_RE.search(value):
        return False
    return bool(re.search(r"[A-Za-z]", value))

def codmunity_lines(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return [clean_line(line) for line in soup.get_text("\n").splitlines() if clean_line(line)]

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

        for j in range(i - 1, max(i - 8, 0), -1):
            candidate = lines[j].strip()
            lowered = candidate.lower()
            if not loadout_type and lowered in LOADOUT_TYPES:
                loadout_type = candidate
            if not weapon_name and valid_weapon_name(candidate):
                weapon_name = candidate
                break

        if not weapon_name:
            continue

        key = weapon_name.lower()
        if key not in seen:
            seen.add(key)
            weapons.append({
                "game": game,
                "name": weapon_name,
                "type": loadout_type,
                "code": code,
            })

        if len(weapons) >= limit:
            break

    return weapons

# ==================== GEMINI (QISQA JAVOB) ====================
async def ask_gemini(user_text: str) -> str:
    if not GEMINI_API_KEY:
        return "Bugun charchadim, ertaga 😊"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\nFoydalanuvchi: {user_text}",
            config={
                "max_output_tokens": 150,
                "temperature": 0.5,
            }
        )
        if response.text:
            answer = response.text.strip()
            if len(answer) > 500:
                answer = answer[:500] + "..."
            return answer
    except Exception as e:
        logging.error(f"Gemini xatosi: {e}")
        if "429" in str(e) or "quota" in str(e):
            return "Bugun charchadim, ertaga 😊"
        return "Xatolik yuz berdi. Keyinroq yozing 😊"
    
    return "Javob topa olmadim 😅"

# ==================== YORDAMCHI FUNKSIYALAR ====================
def wants_meta(text: str) -> bool:
    text_lower = text.lower()
    if "xato" in text_lower or "pishdi" in text_lower:
        return False
    has_meta = "meta" in text_lower or "мета" in text_lower
    has_game = any(g in text_lower for g in ["warzone", "cod", "mw3", "bo6"])
    has_weapon = any(w in text_lower for w in ["qurol", "sborka", "loadout", "kod"])
    return has_meta or (has_game and has_weapon)

def wants_only_code(text: str) -> bool:
    text_lower = text.lower()
    return "faqat kod" in text_lower or "только код" in text_lower

def wants_song(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in ["qo'shiq ayt", "ashula ayt", "kuylab ber", "song"])

def is_russian(text: str) -> bool:
    return "рус" in text.lower() or bool(re.search(r"[а-яё]", text))

def should_bot_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat.type == "private":
        return True
    message = update.message
    if not message or not message.reply_to_message:
        return False
    return message.reply_to_message.from_user.id == context.bot.id

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom, men Lola. 😊")

async def lola_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(VIDEO_FILENAME, "rb") as f:
            await update.message.reply_video(video=f)
    except:
        await update.message.reply_text("😊")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Statistika faqat guruh uchun.")
        return
    rows = get_stats(update.effective_chat.id, datetime.now(TZ).date())
    if not rows:
        await update.message.reply_text("Bugun statistika yo'q.")
        return
    total = sum(r["count"] for r in rows)
    text = f"📊 Bugun {total} ta xabar.\n\nEng faollar:\n"
    for i, r in enumerate(rows[:3]):
        medal = ["🥇", "🥈", "🥉"][i]
        text += f"{medal} {r['user_name']} ({r['count']} ta)\n"
    await update.message.reply_text(text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text or ""

    if not text.strip():
        return

    # Statistikani saqlash
    if user and not user.is_bot and chat.type != "private":
        name = user.full_name or user.username or "Noma'lum"
        add_message_stat(chat.id, user.id, name)

    # "kul" -> video
    if "kul" in text.lower():
        try:
            with open(VIDEO_FILENAME, "rb") as f:
                await update.message.reply_video(video=f)
        except:
            await update.message.reply_text("😊")
        return

    # Guruhda reply qilinmagan xabarga javob berma
    if not should_bot_reply(update, context):
        return

    # Qo'shiq so'ralsa
    if wants_song(text):
        try:
            with open(VIDEO_SONG_FILENAME, "rb") as f:
                await update.message.reply_video(video=f)
        except:
            await update.message.reply_text("Qo'shiq topilmadi 😅")
        return

    # Meta so'ralsa
    if wants_meta(text):
        game = "mw3" if "mw3" in text.lower() else "warzone"
        weapons = parse_meta_weapons(game, limit=3)
        
        if not weapons:
            await update.message.reply_text("CODMunity dan ma'lumot kelmadi. Keyinroq urinib ko'ring 😅")
            return

        ru = is_russian(text)
        only_code = wants_only_code(text)

        if only_code and weapons:
            await update.message.reply_text(weapons[0]["code"])
            return

        if ru:
            msg = "Топ-3 мета оружия:\n\n"
            for i, w in enumerate(weapons, 1):
                msg += f"{i}. {w['name']}"
                if w['type']:
                    msg += f" — {w['type']}"
                msg += "\n"
            msg += "\nКакое нужно?"
        else:
            msg = "Mana hozirgi top-3 meta qurollar:\n\n"
            for i, w in enumerate(weapons, 1):
                msg += f"{i}. {w['name']}"
                if w['type']:
                    msg += f" — {w['type']}"
                msg += "\n"
            msg += "\nQaysi birining sborkasi kerak?"
        
        await update.message.reply_text(msg)
        context.chat_data["last_weapons"] = weapons
        return

    # Raqam bilan tanlash (1,2,3)
    if re.match(r"^\s*[1-3]\s*$", text.strip()) and "last_weapons" in context.chat_data:
        idx = int(text.strip()) - 1
        weapons = context.chat_data["last_weapons"]
        if 0 <= idx < len(weapons):
            w = weapons[idx]
            await update.message.reply_text(f"Mana {w['name']} kodi: {w['code']}")
            return

    # Boshqa hamma narsa -> Gemini (qisqa javob)
    answer = await ask_gemini(text)
    await update.message.reply_text(answer)

# ==================== ASOSIY ====================
async def post_init(app):
    init_db()
    logging.info("Lola bot ishga tushdi!")

def main():
    if not TELEGRAM_TOKEN or not DATABASE_URL or not GEMINI_API_KEY:
        print("Xato: .env faylida TOKEN, DATABASE_URL yoki GEMINI_API_KEY yo'q")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lola", lola_video))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Lola bot ishga tushdi...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
