from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.handlers import common
from app.services.ai_provider import build_ai_provider
from app.services.meta_engine import CodmunityClient


async def main() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp["ai_provider"] = build_ai_provider(settings)
    dp["codmunity_client"] = CodmunityClient(timeout=settings.codmunity_timeout)
    dp.include_router(common.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
