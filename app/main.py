import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import OPENROUTER_DEFAULT_REASONING_MODEL, get_settings
from app.handlers import common, video_links
from app.middlewares.stats import StatsMiddleware
from app.runtime_fixes import ContextAwareAIProvider, LolaContextMiddleware, SafeStatsService
from app.services.ai_provider import build_ai_provider
from app.services.meta_engine import CodmunityClient
from app.services.stats_service import send_daily_reports
from app.services.video_queue import VideoQueueService

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.reasoning_model:
        settings.reasoning_model = OPENROUTER_DEFAULT_REASONING_MODEL

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    stats_service = SafeStatsService(settings.database_url, main_group_id=settings.main_group_id)
    try:
        await asyncio.to_thread(stats_service.init_db)
    except Exception:
        logger.exception("Failed to initialize stats database")

    base_ai_provider = build_ai_provider(settings)
    dp["ai_provider"] = ContextAwareAIProvider(base_ai_provider, stats_service)
    dp["codmunity_client"] = CodmunityClient(timeout=settings.codmunity_timeout)
    dp["stats_service"] = stats_service
    dp["settings"] = settings
    dp.message.middleware(LolaContextMiddleware())
    dp.message.middleware(StatsMiddleware(stats_service))

    # Automatic video links are fail-closed and isolated from Lola's AI path.
    # The router is not installed until the feature, database and chat allow-list
    # are all ready, so an incomplete setup cannot swallow normal conversations.
    if settings.video_links_enabled:
        video_queue = VideoQueueService(settings.database_url)
        allowed_chat_ids = settings.video_link_chat_ids
        if not video_queue.enabled:
            logger.error("VIDEO_LINKS_ENABLED is true but DATABASE_URL is missing")
        elif not allowed_chat_ids:
            logger.error(
                "VIDEO_LINKS_ENABLED is true but VIDEO_LINKS_CHAT_IDS is empty"
            )
        else:
            try:
                await asyncio.to_thread(video_queue.init_db)
            except Exception:
                logger.exception("Failed to initialize automatic video queue; feature stays disabled")
            else:
                dp["video_queue"] = video_queue
                dp.include_router(video_links.build_router(allowed_chat_ids))
                logger.info("Automatic video links enabled for chat ids: %s", sorted(allowed_chat_ids))

    dp.include_router(common.router)

    await bot.delete_webhook(drop_pending_updates=True)
    if stats_service.enabled:
        asyncio.create_task(send_daily_reports(bot, stats_service))
    await dp.start_polling(bot)
