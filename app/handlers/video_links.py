from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message

from app.services.video_links import SUPPORTED_LINK_PATTERN, extract_supported_url
from app.services.video_queue import VideoQueueService

logger = logging.getLogger(__name__)


def build_router(allowed_chat_ids: set[int]) -> Router:
    """Build a narrow router that only sees supported links in allowed groups."""

    router = Router(name="automatic_video_links")
    allowed_ids = frozenset(int(chat_id) for chat_id in allowed_chat_ids)

    @router.message(
        F.chat.type.in_({"group", "supergroup"}),
        F.chat.id.in_(allowed_ids),
        F.text.regexp(SUPPORTED_LINK_PATTERN),
    )
    async def queue_video_link(message: Message, video_queue: VideoQueueService) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        extracted = extract_supported_url(message.text)
        if extracted is None:
            return

        url, source = extracted
        try:
            job_id = await asyncio.to_thread(
                video_queue.enqueue,
                chat_id=message.chat.id,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                user_id=message.from_user.id if message.from_user else None,
                url=url,
                source=source,
            )
        except Exception:
            # Fail silently in Telegram: the original link stays visible and the
            # normal Lola conversation remains isolated from worker failures.
            logger.exception(
                "Failed to queue automatic video chat_id=%s message_id=%s source=%s",
                message.chat.id,
                message.message_id,
                source,
            )
            return

        logger.info(
            "Automatic video queued job_id=%s chat_id=%s message_id=%s source=%s",
            job_id,
            message.chat.id,
            message.message_id,
            source,
        )

    return router
