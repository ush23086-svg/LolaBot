import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.handlers import common
from app.middlewares.stats import StatsMiddleware
from app.services.ai_provider import build_ai_provider
from app.services.meta_engine import CodmunityClient
from app.services.stats_service import StatsService, send_daily_reports

logger = logging.getLogger(__name__)

async def main() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    stats_service = StatsService(settings.database_url)
    try:
        await asyncio.to_thread(stats_service.init_db)
    except Exception:
        logger.exception("Failed to initialize stats database")

    dp["ai_provider"] = build_ai_provider(settings)
    dp["codmunity_client"] = CodmunityClient(timeout=settings.codmunity_timeout)
    dp["stats_service"] = stats_service
    dp.message.middleware(StatsMiddleware(stats_service))
    dp.include_router(common.router)

    await bot.delete_webhook(drop_pending_updates=True)
    if stats_service.enabled:
        asyncio.create_task(send_daily_reports(bot, stats_service))
    await dp.start_polling(bot)
