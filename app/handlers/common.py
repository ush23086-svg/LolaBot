import base64
import logging

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

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

router = Router()
logger = logging.getLogger(__name__)
TELEGRAM_TEXT_LIMIT = 4096
CHAT_DATA: dict[int, dict] = {}


def _user_label(message: Message) -> str:
    user = message.from_user
    if not user:
        return "foydalanuvchi"
    return user.full_name or user.username or "foydalanuvchi"


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


async def _send_answer(message: Message, text: str, status: Message | None = None) -> None:
    parts = _chunks(text)
    if not parts:
        return

    if status:
        await status.edit_text(parts[0])
    else:
        await message.answer(parts[0])

    for part in parts[1:]:
        await message.answer(part)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Salom, men Lolaman. Warzone yoki MW3 meta kerak bo'lsa yozing. AI keyin ulansa, skrinlarni ham tahlil qilaman."
    )


@router.message(F.photo)
async def photo_handler(message: Message, bot: Bot, ai_provider: AIProvider) -> None:
    if not await _should_answer(message, bot):
        return

    status = await message.answer("Rasmni ko'rib chiqyapman...")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buffer = await bot.download_file(file.file_path)

        if buffer is None:
            await status.edit_text("Rasmni yuklab olishda muammo bo'ldi. Qayta yuborib ko'ring.")
            return

        image_base64 = base64.b64encode(buffer.read()).decode("ascii")
        caption = message.caption or ""
        answer = await ai_provider.analyze_image(
            image_base64=image_base64,
            user_name=_user_label(message),
            caption=caption,
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
    if not await _should_answer(message, bot):
        return

    text = message.text or ""
    if not text.strip():
        await message.answer("Aniqroq yozing.")
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
        )
        await _send_answer(message, answer)
    except Exception:
        logger.exception("Text handling failed")
        await message.answer("Hozir javob berishda muammo bo'ldi. Birozdan keyin urinib ko'ring.")


async def _handle_meta_request(
    message: Message,
    text: str,
    chat_data: dict,
    codmunity_client: CodmunityClient,
) -> None:
    status = await message.answer("CODMunity'dan meta ma'lumotni olyapman...")

    try:
        game = requested_game(text)
        weapons = (
            codmunity_client.get_mw3_meta()
            if game == "mw3"
            else codmunity_client.get_warzone_meta()
        )
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
    status = await message.answer("CODMunity'dan loadoutni ochyapman...")

    try:
        weapon = codmunity_client.get_weapon_loadout(selected_weapon)
        await status.edit_text(format_weapon_loadout(weapon))
    except MetaEngineError as exc:
        await status.edit_text(str(exc))
    except Exception:
        logger.exception("Selected weapon handling failed")
        await status.edit_text("CODMunity'dan ma'lumot olishda muammo bo'ldi")
