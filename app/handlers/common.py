import asyncio
import base64
import logging
import random
import re
import time
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.config import Settings
from app.services.ai_provider import AIProvider
from app.services.meta_engine import (
    CHECKER_FAIL_MESSAGE,
    CodmunityClient,
    LOADOUT_NOT_FOUND_MESSAGE,
    MetaEngineError,
    MetaWeapon,
    find_selected_weapon,
    format_meta_list,
    format_weapon_loadout,
    is_loadout_request,
    is_meta_request,
    meta_mode_label,
    normalize_text,
    requested_game,
)
from app.services.stats_service import StatsService, format_stats, today_key

router = Router()
logger = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096
CHAT_DATA: dict[int, dict] = {}
META_CONTEXT_TTL_SECONDS = 15 * 60

VIDEO_FILENAME = "SaveVid_Net_AQNKnUIQh4au0ukBFQeeBEE9GNtzkOFvNFXUDTipfHHr9qwI5m8RUCHhFxyUIY.mp4"
VIDEO_SONG2_FILENAME = "video_2026-05-31_21-36-53.mp4"
PREMIUM_PLANS = {
    "test": {
        "title": "Lola Premium - 1 kun test",
        "description": "1 kun premium kirish.",
        "label": "1 kun test",
        "stars": 29,
        "days": 1,
    },
    "month": {
        "title": "Lola Premium - 1 oy",
        "description": "30 kun premium kirish.",
        "label": "1 oy premium",
        "stars": 250,
        "days": 30,
    },
}

GREETING_RE = re.compile(
    r"^\s*(salom|assalomu alaykum|assalom|hello|hi|privet|привет)\s*[!.?]*\s*$",
    re.IGNORECASE,
)
LOLA_PRESENCE_RE = re.compile(
    r"^\s*lola\s*(?:\?|bormisan\??|shu yerdamisan\??|qayerdasan\??|eshityapsanmi\??)\s*$",
    re.IGNORECASE,
)
PRESENCE_REPLIES = ["Xa, shu yerdaman 🙂", "Eshitaman.", "Shu yerdaman."]
MEMORY_RE = re.compile(
    r"(kecha|oldin|avval).*(nima|gaplash|yozish)|nimani gaplashdik",
    re.IGNORECASE,
)
META_LIST_LINE_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.+?)(?:\s+-\s+(.+?))?(?:\s+-\s+(\d+(?:\.\d+)?%))?\s*$")
META_SELECTION_WORDS = {
    "birinchi": 1,
    "ikkinchi": 2,
    "uchinchi": 3,
    "tortinchi": 4,
    "to'rtinchi": 4,
    "beshinchi": 5,
}
META_EXPLANATION_MARKERS = (
    "nimafarqibor",
    "farqinima",
    "qandayfarq",
    "tushuntir",
    "qaysibirinima",
    "nima",
)
META_ACTION_MARKERS = (
    "meta",
    "loadout",
    "qurol",
    "weapon",
    "gun",
    "build",
    "klass",
    "class",
    "ber",
)


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


def _user_meta_key(message: Message) -> tuple[int, int]:
    user_id = message.from_user.id if message.from_user else 0
    return (message.chat.id, user_id)


def _meta_contexts(message: Message) -> dict:
    data = _chat_data(message)
    return data.setdefault("meta_contexts", {})


def _meta_context(message: Message) -> dict | None:
    context = _meta_contexts(message).get(_user_meta_key(message))
    if not context:
        return None

    if context.get("expires_at", 0) < time.monotonic():
        _meta_contexts(message).pop(_user_meta_key(message), None)
        return None

    return context


def _save_meta_context(message: Message, game: str, weapons: list[MetaWeapon]) -> None:
    if not message.from_user:
        return

    source = weapons[0].source if weapons else ""
    mode = _mode_label(game)
    weapon_dicts = []
    for weapon in weapons:
        item = weapon.to_dict()
        item["source_json"] = weapon.to_source_json(mode=mode)
        weapon_dicts.append(item)

    _meta_contexts(message)[_user_meta_key(message)] = {
        "mode": mode,
        "source": source,
        "weapons": weapon_dicts,
        "expires_at": time.monotonic() + META_CONTEXT_TTL_SECONDS,
    }


def _meta_weapons_from_context(message: Message) -> list[dict]:
    context = _meta_context(message)
    if not context:
        return []
    return list(context.get("weapons", []))


def _reply_meta_weapons(message: Message) -> list[dict]:
    reply = message.reply_to_message
    if not reply:
        return []

    text = reply.text or reply.caption or ""
    if "Hozirgi meta:" not in text:
        return []

    source = "CODMunity"
    mode = "Warzone"
    weapons: list[dict] = []
    for line in text.splitlines():
        clean_line = line.strip()
        if clean_line.startswith("Manba:"):
            source = clean_line.partition(":")[2].strip() or source
            continue
        if clean_line.startswith("Mode:"):
            mode = clean_line.partition(":")[2].strip() or mode
            continue

        match = META_LIST_LINE_RE.match(clean_line)
        if not match:
            continue

        _, name, role, pick = match.groups()
        weapon = MetaWeapon(
            name=name.strip(),
            type=(role or "Meta").strip(),
            pick=(pick or "").strip(),
            url=_inferred_loadout_url(name, source),
            game=mode,
            source=source,
        )
        item = weapon.to_dict()
        item["source_json"] = weapon.to_source_json(mode=mode)
        weapons.append(item)

    return weapons


def _inferred_loadout_url(name: str, source: str) -> str | None:
    if not source.startswith("WZStatsGG"):
        return None

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"https://wzstats.gg/best-loadouts/{slug}" if slug else None


def _mode_label(game: str) -> str:
    return meta_mode_label(game)


def _selection_index_from_text(text: str) -> int | None:
    query = normalize_text(text)
    for word, number in META_SELECTION_WORDS.items():
        if normalize_text(word) in query:
            return number - 1

    match = re.match(r"^(\d{1,2})(.*)$", query)
    if match:
        suffix = match.group(2)
        if suffix in {"", "ni", "niber", "ber", "chi", "chisi", "nchi", "inchi", "och", "ochibber", "taxlabber"}:
            return int(match.group(1)) - 1

    return None


def _selection_is_out_of_range(text: str, weapons: list[dict]) -> bool:
    index = _selection_index_from_text(text)
    return index is not None and not (0 <= index < len(weapons))


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
    return normalized in {"kul", "lolakul", "bittakul", "lolabittakul", "kulchi"}


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


async def _check_usage_limit(message: Message, stats_service: StatsService) -> bool:
    user = message.from_user
    if not user or user.is_bot:
        return True

    try:
        allowed, count, limit = await asyncio.to_thread(
            stats_service.use_bot_quota,
            message.chat.id,
            user.id,
            message.chat.type,
        )
    except Exception:
        logger.exception("Failed to check bot quota for chat %s", message.chat.id)
        return True

    if allowed:
        return True

    if message.chat.type == "private":
        await message.reply(
            f"Bugungi bepul limit tugadi ({limit} ta). Davom etish uchun /premium kerak."
        )
    else:
        await message.reply(
            f"Bugungi bepul limit tugadi ({limit} ta). Premium olish uchun private chatda /premium yozing."
        )
    logger.info(
        "Bot quota exceeded chat=%s user=%s count=%s limit=%s",
        message.chat.id,
        user.id,
        count,
        limit,
    )
    return False


def _premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 kun test - 29 Stars",
                    callback_data="premium:test",
                )
            ],
            [
                InlineKeyboardButton(
                    text="1 oy premium - 250 Stars",
                    callback_data="premium:month",
                )
            ],
        ]
    )


async def _send_premium_invoice(message: Message, plan_key: str) -> None:
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await message.reply("Tarif topilmadi.")
        return

    await message.answer_invoice(
        title=plan["title"],
        description=plan["description"],
        payload=f"premium:{plan_key}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
        reply_to_message_id=message.message_id,
    )


def _is_owner(message: Message, settings: Settings) -> bool:
    return bool(
        settings.owner_id
        and message.from_user
        and message.from_user.id == settings.owner_id
    )


def _format_dt(value) -> str:
    if not value:
        return "yo'q"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _target_user_from_admin_command(message: Message) -> tuple[int | None, str | None, str | None]:
    parts = (message.text or "").split()
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user
        return user.id, user.full_name or user.username or str(user.id), user.username

    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        return int(parts[1]), None, None

    return None, None, None


def _days_from_admin_command(message: Message, default: int = 30) -> int:
    parts = (message.text or "").split()
    if message.reply_to_message and len(parts) > 1 and parts[1].isdigit():
        return max(1, int(parts[1]))

    for part in parts[2:]:
        if part.isdigit():
            return max(1, int(part))
    return default


def _is_direct_meta_scope(text: str, game_choice: str | None) -> bool:
    if not game_choice:
        return False

    query = normalize_text(text)
    return query in {
        "ranked",
        "rank",
        "warzone",
        "mw3",
        "resurgence",
        "rezurgence",
        "br",
        "battleroyale",
    }


def _is_meta_explanation_question(text: str) -> bool:
    query = normalize_text(text)
    if not ("ranked" in query or "resurgence" in query):
        return False
    return any(marker in query for marker in META_EXPLANATION_MARKERS)


def _is_ranked_mode_explanation(text: str) -> bool:
    query = normalize_text(text)
    return "ranked" in query and any(marker in query for marker in META_EXPLANATION_MARKERS)


def _is_meta_weapon_request(text: str, game_choice: str | None) -> bool:
    if not game_choice or _is_meta_explanation_question(text):
        return False
    query = normalize_text(text)
    return any(marker in query for marker in META_ACTION_MARKERS)


def _should_handle_meta_list(text: str, game_choice: str | None) -> bool:
    if _is_meta_explanation_question(text):
        return False
    return (
        _is_meta_weapon_request(text, game_choice)
        or _is_direct_meta_scope(text, game_choice)
        or is_meta_request(text)
    )


def _safe_loadout_error(exc: MetaEngineError) -> str:
    text = str(exc)
    if text in {LOADOUT_NOT_FOUND_MESSAGE, CHECKER_FAIL_MESSAGE}:
        return CHECKER_FAIL_MESSAGE
    return text


def _memory_summary(user_text: str, answer: str) -> str:
    return f"Oxirgi mavzu: user '{user_text[:300]}'; Lola '{answer[:500]}'".replace("\n", " ")[:1000]


async def _save_memory(message: Message, stats_service: StatsService, user_text: str, answer: str) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    try:
        await asyncio.to_thread(
            stats_service.update_memory,
            message.chat.id,
            user.id,
            _memory_summary(user_text, answer),
        )
    except Exception:
        logger.exception("Failed to update memory for chat %s", message.chat.id)


async def _send_memory_reply(message: Message, stats_service: StatsService) -> bool:
    text = message.text or ""
    if not MEMORY_RE.search(text):
        return False

    user = message.from_user
    if not user:
        return False

    try:
        memory = await asyncio.to_thread(stats_service.get_memory, message.chat.id, user.id)
    except Exception:
        logger.exception("Failed to read memory for chat %s", message.chat.id)
        memory = None

    await message.reply(memory or "Hozircha oldingi suhbatni eslab qolmaganman.")
    return True


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


@router.message(Command("premium"))
async def premium_handler(message: Message) -> None:
    if message.chat.type != "private":
        await message.reply("Premium olish uchun menga private chatda /premium yozing.")
        return

    await message.reply(
        "Premium tariflar:\n\n"
        "1 kun test - 29 Stars\n"
        "1 oy premium - 250 Stars",
        reply_markup=_premium_keyboard(),
    )


@router.message(Command("premium_test"))
async def premium_test_handler(message: Message) -> None:
    if message.chat.type != "private":
        await message.reply("Premium olish uchun private chatda /premium_test yozing.")
        return

    await _send_premium_invoice(message, "test")


@router.message(Command("premium_month"))
async def premium_month_handler(message: Message) -> None:
    if message.chat.type != "private":
        await message.reply("Premium olish uchun private chatda /premium_month yozing.")
        return

    await _send_premium_invoice(message, "month")


@router.callback_query(F.data.startswith("premium:"))
async def premium_callback_handler(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    plan_key = (callback.data or "").split(":", 1)[1]
    await callback.answer()
    await _send_premium_invoice(callback.message, plan_key)


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery) -> None:
    payload = query.invoice_payload or ""
    plan_key = payload.removeprefix("premium:")
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await query.answer(ok=False, error_message="Tarif topilmadi.")
        return
    if query.total_amount != plan["stars"]:
        logger.warning(
            "Premium pre-checkout amount mismatch user=%s plan=%s expected=%s actual=%s",
            query.from_user.id if query.from_user else None,
            plan_key,
            plan["stars"],
            query.total_amount,
        )
        await query.answer(ok=False, error_message="To'lov summasi tarifga mos kelmadi.")
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, stats_service: StatsService) -> None:
    payment = message.successful_payment
    user = message.from_user
    if not payment or not user:
        return

    payload = payment.invoice_payload or ""
    plan_key = payload.removeprefix("premium:")
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await message.reply("To'lov qabul qilindi, lekin tarif topilmadi.")
        return
    if payment.total_amount != plan["stars"]:
        logger.warning(
            "Premium successful_payment amount mismatch user=%s plan=%s expected=%s actual=%s charge=%s",
            user.id,
            plan_key,
            plan["stars"],
            payment.total_amount,
            payment.telegram_payment_charge_id,
        )
        await message.reply("To'lov summasi tarifga mos kelmadi. Premium yoqilmadi.")
        return

    try:
        premium_until = await asyncio.to_thread(
            stats_service.record_payment,
            user.id,
            user.full_name or user.username or "foydalanuvchi",
            user.username,
            plan_key,
            payment.total_amount,
            payload,
            payment.telegram_payment_charge_id,
            payment.provider_payment_charge_id,
            plan["days"],
        )
    except Exception:
        logger.exception("Failed to record successful payment for user %s", user.id)
        await message.reply("To'lov qabul qilindi. Premiumni yoqishda muammo bo'ldi, egasiga yozing.")
        return

    if premium_until is None:
        logger.error("Payment accepted but DATABASE_URL is not configured")
        await message.reply("To'lov qabul qilindi. Premiumni yoqishda muammo bo'ldi, egasiga yozing.")
        return

    await message.reply(f"Premium yoqildi. Amal qilish muddati: {_format_dt(premium_until)}")


@router.message(Command("income"))
async def income_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    summary = await asyncio.to_thread(stats_service.get_income_summary)
    await message.reply(
        "Daromad:\n"
        f"To'lovlar: {summary['payments']} ta\n"
        f"Stars: {summary['stars']}"
    )


@router.message(Command("paid"))
async def paid_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    rows = await asyncio.to_thread(stats_service.get_recent_payments, 10)
    if not rows:
        await message.reply("Hali to'lov yo'q.")
        return

    lines = ["Oxirgi to'lovlar:"]
    for row in rows:
        username = f" @{row['username']}" if row.get("username") else ""
        lines.append(
            f"- {row['user_name']}{username}: {row['plan']} - {row['stars']} Stars"
        )
    await message.reply("\n".join(lines))


@router.message(Command("users"))
async def users_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    rows = await asyncio.to_thread(stats_service.get_premium_users, 20)
    if not rows:
        await message.reply("Premium userlar yo'q.")
        return

    lines = ["Premium userlar:"]
    for row in rows:
        username = f" @{row['username']}" if row.get("username") else ""
        lines.append(
            f"- {row['user_name']}{username}: {_format_dt(row['premium_until'])}"
        )
    await message.reply("\n".join(lines))


@router.message(Command("grant"))
async def grant_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    user_id, user_name, username = _target_user_from_admin_command(message)
    if not user_id:
        await message.reply("User ID yozing yoki user xabariga reply qiling: /grant 123456789 30")
        return

    days = _days_from_admin_command(message, default=30)
    premium_until = await asyncio.to_thread(
        stats_service.grant_premium,
        user_id,
        days,
        user_name,
        username,
    )
    if premium_until is None:
        await message.reply("DATABASE_URL ulanmagan.")
        return

    await message.reply(f"Premium berildi: {user_id}\nMuddat: {_format_dt(premium_until)}")


@router.message(Command("revoke"))
async def revoke_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    user_id, user_name, username = _target_user_from_admin_command(message)
    if not user_id:
        await message.reply("User ID yozing yoki user xabariga reply qiling: /revoke 123456789")
        return

    await asyncio.to_thread(stats_service.revoke_premium, user_id, user_name, username)
    await message.reply(f"Premium o'chirildi: {user_id}")


@router.message(Command("check"))
async def check_handler(message: Message, stats_service: StatsService, settings: Settings) -> None:
    if message.chat.type != "private" or not _is_owner(message, settings):
        return

    user_id = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip().isdigit():
        user_id = int(parts[1].strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
    elif message.from_user:
        user_id = message.from_user.id

    if not user_id:
        await message.reply("User ID topilmadi.")
        return

    row = await asyncio.to_thread(stats_service.get_user_status, user_id)
    if not row:
        await message.reply(f"{user_id}: bazada topilmadi.")
        return

    username = f" @{row['username']}" if row.get("username") else ""
    await message.reply(
        f"{row['user_name']}{username}\n"
        f"ID: {row['user_id']}\n"
        f"Premium: {_format_dt(row['premium_until'])}"
    )


@router.message(Command("keys_status"))
async def keys_status_handler(
    message: Message,
    ai_provider: AIProvider,
    settings: Settings,
) -> None:
    if not _is_owner(message, settings):
        return
    if message.chat.type != "private":
        return

    rows = await ai_provider.keys_status()
    await message.reply("\n".join(rows))


@router.message(Command("vision_status"))
async def vision_status_handler(
    message: Message,
    ai_provider: AIProvider,
    settings: Settings,
) -> None:
    if not _is_owner(message, settings):
        return
    if message.chat.type != "private":
        return

    rows = await ai_provider.vision_status()
    await message.reply("\n".join(rows))


@router.message(Command("image"))
async def image_command_handler(
    message: Message,
    ai_provider: AIProvider,
    stats_service: StatsService,
) -> None:
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.reply("Rasm uchun prompt yozing: /image quyosh botayotgan shahar")
        return
    if not await _check_usage_limit(message, stats_service):
        return

    status = await message.reply("Rasm yaratyapman...")
    try:
        result = await ai_provider.generate_image(prompt=prompt, user_name=_user_label(message))
        if result.data:
            await message.reply_photo(
                BufferedInputFile(result.data, filename="lola_image.png"),
                caption="Tayyor.",
            )
            try:
                await status.delete()
            except Exception:
                logger.debug("Failed to delete image generation status message")
            return

        await status.edit_text(result.error or "Rasm yaratishda muammo bo'ldi.")
    except Exception:
        logger.exception("Image generation failed")
        await status.edit_text("Rasm yaratishda muammo bo'ldi. Keyinroq urinib ko'ring.")


@router.message(F.photo)
async def photo_handler(
    message: Message,
    bot: Bot,
    ai_provider: AIProvider,
    stats_service: StatsService,
) -> None:
    if not await _should_answer(message, bot):
        return
    if not await _check_usage_limit(message, stats_service):
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
        await _save_memory(message, stats_service, message.caption or "[rasm]", answer)
    except Exception:
        logger.exception("Photo handling failed")
        await status.edit_text("Rasmni tahlil qilishda xatolik bo'ldi. Keyinroq qayta urinib ko'ring.")


@router.message(F.text)
async def text_handler(
    message: Message,
    bot: Bot,
    ai_provider: AIProvider,
    codmunity_client: CodmunityClient,
    stats_service: StatsService,
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
    if not await _check_usage_limit(message, stats_service):
        return

    if await _send_memory_reply(message, stats_service):
        return

    if GREETING_RE.match(text):
        await message.reply(_greeting_for(message))
        return

    if LOLA_PRESENCE_RE.match(text):
        await message.reply(random.choice(PRESENCE_REPLIES))
        return

    chat_data = _chat_data(message)
    last_meta = _meta_weapons_from_context(message) or _reply_meta_weapons(message)
    selected_weapon = find_selected_weapon(text, last_meta)
    game_choice = requested_game(text)
    is_explanation = _is_meta_explanation_question(text)

    if not is_explanation and chat_data.get("awaiting_meta_game") and game_choice:
        await _handle_meta_request(message, text, chat_data, codmunity_client)
        await _save_memory(message, stats_service, text, "Meta ro'yxati so'raldi.")
        return

    if _is_ranked_mode_explanation(text):
        await message.reply("Hozir BR Ranked yo'q, faqat Resurgence Ranked bor.")
        await _save_memory(message, stats_service, text, "Ranked farqi tushuntirildi.")
        return

    if _should_handle_meta_list(text, game_choice):
        await _handle_meta_request(message, text, chat_data, codmunity_client)
        await _save_memory(message, stats_service, text, "Meta turi so'raldi.")
        return

    if selected_weapon:
        logger.info(
            "selected weapon from context chat=%s user=%s weapon=%s source=%s",
            message.chat.id,
            message.from_user.id if message.from_user else None,
            selected_weapon.name,
            selected_weapon.source,
        )
        await _handle_selected_weapon(message, selected_weapon, codmunity_client)
        await _save_memory(message, stats_service, text, "Loadout ochildi.")
        return

    if last_meta and _selection_is_out_of_range(text, last_meta):
        await message.reply("Ro'yxatda bunaqa raqam yo'q")
        return

    if is_loadout_request(text):
        await _handle_named_loadout_request(message, text, codmunity_client)
        await _save_memory(message, stats_service, text, "Top meta bo'lmagan qurol loadouti so'raldi.")
        return

    try:
        answer = await ai_provider.ask_ai(
            text=text,
            user_name=_user_label(message),
            reply_context=_reply_context(message),
        )
        await _send_answer(message, answer)
        await _save_memory(message, stats_service, text, answer)
    except Exception:
        logger.exception("Text handling failed")
        await message.reply("AI modeli vaqtincha band yoki limitga tushgan. Keyinroq urinib ko'ring.")


async def _handle_meta_request(
    message: Message,
    text: str,
    chat_data: dict,
    codmunity_client: CodmunityClient,
) -> None:
    game = requested_game(text)
    if game is None:
        chat_data["awaiting_meta_game"] = True
        await message.reply("Qaysi meta kerak: Warzone, Ranked yoki MW3?")
        return

    chat_data.pop("awaiting_meta_game", None)
    chat_data.pop("awaiting_ranked_type", None)
    if game == "ranked_unavailable":
        await message.reply("Hozir BR Ranked yo'q, faqat Resurgence Ranked bor.")
        game = "resurgence_ranked"

    status = await message.reply("CODMunity'dan meta ma'lumotni olyapman...")

    try:
        if game == "mw3":
            weapons = codmunity_client.get_mw3_meta()
        elif game == "resurgence_ranked":
            weapons = codmunity_client.get_resurgence_ranked_meta()
        elif game == "resurgence":
            weapons = codmunity_client.get_resurgence_meta()
        elif game == "battle_royale":
            weapons = codmunity_client.get_battle_royale_meta()
        else:
            weapons = codmunity_client.get_warzone_meta()
        _save_meta_context(message, game, weapons)
        await status.edit_text(format_meta_list(weapons))
    except MetaEngineError as exc:
        await status.edit_text(str(exc))
    except Exception:
        logger.exception("Meta request failed")
        await status.edit_text("CODMunity'dan ma'lumot olishda muammo bo'ldi")


async def _handle_named_loadout_request(
    message: Message,
    text: str,
    codmunity_client: CodmunityClient,
) -> None:
    status = await message.reply("Bu hozir top meta emas, lekin loadout beraman.")

    try:
        weapon = codmunity_client.get_named_weapon_loadout(text)
        await status.edit_text(
            "Bu hozir top meta emas, lekin loadout beraman.\n\n"
            f"{format_weapon_loadout(weapon)}"
        )
    except MetaEngineError as exc:
        await status.edit_text(_safe_loadout_error(exc))
    except Exception:
        logger.exception("Named loadout handling failed")
        await status.edit_text("Aniq ma'lumot topolmadim.")


async def _handle_selected_weapon(
    message: Message,
    selected_weapon: MetaWeapon,
    codmunity_client: CodmunityClient,
) -> None:
    if not selected_weapon.url and (selected_weapon.code or selected_weapon.attachments):
        await message.reply(format_weapon_loadout(selected_weapon))
        return

    status = await message.reply("CODMunity'dan loadoutni ochyapman...")

    try:
        weapon = codmunity_client.get_weapon_loadout(selected_weapon)
        await status.edit_text(format_weapon_loadout(weapon))
    except MetaEngineError as exc:
        await status.edit_text(_safe_loadout_error(exc))
    except Exception:
        logger.exception("Selected weapon handling failed")
        await status.edit_text("CODMunity'dan ma'lumot olishda muammo bo'ldi")
