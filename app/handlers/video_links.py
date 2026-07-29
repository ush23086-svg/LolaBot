from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import Message

from app.services.video_links import extract_supported_url
from app.services.video_queue import VideoQueueService

logger = logging.getLogger(__name__)


class SupportedVideoLinkFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict[str, str]:
        extracted = extract_supported_url(message.text)
        if extracted is None:
            return False
        url, source = extracted
        return {"video_url": url, "video_source": source}


def build_router(allowed_chat_ids: set[int]) -> Router:
    """Build a narrow router that only sees supported links in allowed groups."""

    router = Router(name="automatic_video_links")
    allowed_ids = frozenset(int(chat_id) for chat_id in allowed_chat_ids)

    @router.message(
        F.chat.type.in_({"group", "supergroup"}),
        F.chat.id.in_(allowed_ids),
        SupportedVideoLinkFilter(),
    )
    async def queue_video_link(
        message: Message,
        video_queue: VideoQueueService,
        video_url: str,
        video_source: str,
    ) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        try:
            job_id = await asyncio.to_thread(
                video_queue.enqueue,
                chat_id=message.chat.id,
                message_id=message.message_id,
                message_thread_id=message.message_thread_id,
                user_id=message.from_user.id if message.from_user else None,
                url=video_url,
                source=video_source,
            )
        except Exception:
            # Fail silently in Telegram: the original link stays visible and the
            # normal Lola conversation remains isolated from worker failures.
            logger.exception(
                "Failed to queue automatic video chat_id=%s message_id=%s source=%s",
                message.chat.id,
                message.message_id,
                video_source,
            )
            return

        logger.info(
            "Automatic video queued job_id=%s chat_id=%s message_id=%s source=%s",
            job_id,
            message.chat.id,
            message.message_id,
            video_source,
        )

    return router
