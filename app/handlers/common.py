import asyncio
import base64
import logging
import random
import re
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from app.services.ai_provider import AIProvider
from app.services.meta_engine import (
    CodmunityClient,
    MetaEngineError,
    MetaWeapon,
    find_selected_weapon,
    format_meta_list,
    format_weapon_loadout,
    is_meta_request,
    requested_game,
)
from app.services.stats_service import StatsService, format_stats, today_key

router = Router()
logger = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096
CHAT_DATA: dict[int, dict] = {}

VIDEO_FILENAME = "SaveVid_Net_AQNKnUIQh4au0ukBFQeeBEE9GNtzkOFvNFXUDTipfHHr9qwI5m8RUCHhFxyUIY.mp4"
VIDEO_SONG2_FILENAME = "video_2026-05-31_21-36-53.mp4"

GREETING_RE = re.compile(
    r"^\s*(salom|assalomu alaykum|assalom|hello|hi|privet|привет)\s*[!.?]*\s*$",
    re.IGNORECASE,
)
LOLA_PRESENCE_RE = re.compile(
    r"^\s*lola\s*(?:\?|bormisan\??|shu yerdamisan\??|qayerdasan\??|eshityapsanmi\??)\s*$",
    re.IGNORECASE,
)
PRESENCE_REPLIES = ["Xa, shu yerdaman 🙂", "Eshitaman.", "Shu yerdaman."]


def _user_label(message: Message) -> str:
    user = message.from_user
    if not user:
        return "foydalanuvchi"
    return user.full_name or user.username or "foydalanuvchi"


def _user_display_name(message: Message) -> str:
    user = message.from_user
    if not user:
        return ""

    return (user.full_name or user.username or "").strip().lstrip("@")


def _greeting_for(message: Message) -> str:
    name = _user_display_name(message)
    if not name:
        return "Salom 😊"
    return f"Salom, {name} 😊"


async def _should_answer(message: Message, bot: Bot) -> bool:
    if message.chat.type == "private":
        return True

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return False

    me = await bot.me()
    return message.reply_to_message.from_user.id == me.id


def _chunks(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _chat_data(message: Message) -> dict:
    return CHAT_DATA.setdefault(message.chat.id, {})


def _reply_context(message: Message) -> str:
    reply = message.reply_to_message
    if not reply:
        return ""

    text = reply.text or reply.caption or ""
    if not text.strip():
        return ""

    sender = reply.from_user.full_name if reply.from_user else "oldingi xabar"
    return f"Reply qilingan xabar ({sender}): {text.strip()}"


def _wants_joke_video(text: str) -> bool:
    normalized = re.sub(r"[^a-zа-яё]+", "", text.lower())
    return normalized in {"kul", "lolakul", "kulchi"}


def _wants_song_video(text: str) -> bool:
    value = text.lower()
    return any(
        phrase in value
        for phrase in (
            "qo'shiq ayt",
            "qoshiq ayt",
            "ashula ayt",
            "kuylab ber",
            "qo'shiq tashla",
            "qoshiq tashla",
            "song ayt",
        )
    )


async def _send_answer(message: Message, text: str, status: Message | None = None) -> None:
    parts = _chunks(text)
    if not parts:
        return

    if status:
        await status.edit_text(parts[0])
    else:
        await message.reply(parts[0])

    for part in parts[1:]:
        await message.reply(part)


async def _send_video_reply(message: Message, filename: str) -> None:
    try:
        await message.reply_video(FSInputFile(filename))
    except Exception:
        logger.exception("Failed to send video %s", filename)
        await message.reply("Videoni yubora olmadim.")


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.reply("Salom 😊 Bemalol yozing.")


@router.message(Command("stats"))
async def stats_handler(message: Message, stats_service: StatsService) -> None:
    if message.chat.type == "private":
        await message.reply("Statistika faqat guruhlar uchun ishlaydi.")
        return

    rows = await asyncio.to_thread(stats_service.get_stats, message.chat.id, today_key())
    if not rows:
        await message.reply("Bugun hali statistika yo'q.")
        return

    total = sum(int(row["count"]) for row in rows)
    await message.reply(format_stats("Bugungi statistika", total, rows))


@router.message(Command("week"))
async def week_handler(message: Message, stats_service: StatsService) -> None:
    if message.chat.type == "private":
        await message.reply("Haftalik statistika faqat guruhlar uchun ishlaydi.")
        return

    today = today_key()
    start_day = today - timedelta(days=today.weekday())
    rows = await asyncio.to_thread(stats_service.get_stats_range, message.chat.id, start_day, today)
    if not rows:
        await message.reply("Bu hafta hali statistika yo'q.")
        return

    total = sum(int(row["count"]) for row in rows)
    await message.reply(format_stats("Haftalik statistika", total, rows))


@router.message(Command("month"))
async def month_handler(message: Message, stats_service: StatsService) -> None:
    if message.chat.type == "private":
        await message.reply("Oylik statistika faqat guruhlar uchun ishlaydi.")
        return

    today = today_key()
    start_day = today.replace(day=1)
    rows = await asyncio.to_thread(stats_service.get_stats_range, message.chat.id, start_day, today)
    if not rows:
        await message.reply("Bu oy hali statistika yo'q.")
        return

    total = sum(int(row["count"]) for row in rows)
    await message.reply(format_stats("Oylik statistika", total, rows))


@router.message(F.photo)
async def photo_handler(message: Message, bot: Bot, ai_provider: AIProvider) -> None:
    if not await _should_answer(message, bot):
        return

    status = await message.reply("Rasmni ko'rib chiqyapman...")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buffer = await bot.download_file(file.file_path)

        if buffer is None:
            await status.edit_text("Rasmni yuklab olishda muammo bo'ldi. Qayta yuborib ko'ring.")
            return

        image_base64 = base64.b64encode(buffer.read()).decode("ascii")
        answer = await ai_provider.analyze_image(
            image_base64=image_base64,
            user_name=_user_label(message),
            caption=message.caption or "",
            reply_context=_reply_context(message),
        )
        await _send_answer(message, answer, status=status)
    except Exception:
        logger.exception("Photo handling failed")
        await status.edit_text("Rasmni tahlil qilishda xatolik bo'ldi. Keyinroq qayta urinib ko'ring.")


@router.message(F.text)
async def text_handler(
    message: Message,
    bot: Bot,
    ai_provider: AIProvider,
    codmunity_client: CodmunityClient,
) -> None:
    text = message.text or ""
    if not text.strip():
        await message.reply("Aniqroq yozing.")
        return

    if _wants_joke_video(text):
        await _send_video_reply(message, VIDEO_FILENAME)
        return

    if _wants_song_video(text):
        await _send_video_reply(message, VIDEO_SONG2_FILENAME)
        return

    if not await _should_answer(message, bot):
        return

    if GREETING_RE.match(text):
        await message.reply(_greeting_for(message))
        return

    if LOLA_PRESENCE_RE.match(text):
        await message.reply(random.choice(PRESENCE_REPLIES))
        return

    chat_data = _chat_data(message)
    last_meta = chat_data.get("last_meta_weapons", [])
    selected_weapon = find_selected_weapon(text, last_meta)

    if selected_weapon:
        await _handle_selected_weapon(message, selected_weapon, codmunity_client)
        return

    if is_meta_request(text):
        await _handle_meta_request(message, text, chat_data, codmunity_client)
        return

    try:
        answer = await ai_provider.ask_ai(
            text=text,
            user_name=_user_label(message),
            reply_context=_reply_context(message),
        )
        await _send_answer(message, answer)
    except Exception:
        logger.exception("Text handling failed")
        await message.reply("Hozir javob berishda muammo bo'ldi. Birozdan keyin urinib ko'ring.")


async def _handle_meta_request(
    message: Message,
    text: str,
    chat_data: dict,
    codmunity_client: CodmunityClient,
) -> None:
    status = await message.reply("CODMunity'dan meta ma'lumotni olyapman...")

    try:
        game = requested_game(text)
        weapons = codmunity_client.get_mw3_meta() if game == "mw3" else codmunity_client.get_warzone_meta()
        chat_data["last_meta_weapons"] = [weapon.to_dict() for weapon in weapons]
        await status.edit_text(format_meta_list(weapons))
    except MetaEngineError as exc:
        await status.edit_text(str(exc))
    except Exception:
        logger.exception("Meta request failed")
        await status.edit_text("CODMunity'dan ma'lumot olishda muammo bo'ldi")


async def _handle_selected_weapon(
    message: Message,
    selected_weapon: MetaWeapon,
    codmunity_client: CodmunityClient,
) -> None:
    status = await message.reply("CODMunity'dan loadoutni ochyapman...")

    try:
        weapon = codmunity_client.get_weapon_loadout(selected_weapon)
        await status.edit_text(format_weapon_loadout(weapon))
    except MetaEngineError as exc:
        await status.edit_text(str(exc))
    except Exception:
        logger.exception("Selected weapon handling failed")
        await status.edit_text("CODMunity'dan ma'lumot olishda muammo bo'ldi")
