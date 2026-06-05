from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.services.stats_service import StatsService

logger = logging.getLogger(__name__)


class StatsMiddleware(BaseMiddleware):
    def __init__(self, stats_service: StatsService) -> None:
        self.stats_service = stats_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            await self._count_group_message(event, data)
        return await handler(event, data)

    async def _count_group_message(self, message: Message, data: dict[str, Any]) -> None:
        if message.chat.type == "private":
            return

        user = message.from_user
        if not user or user.is_bot:
            return

        if not self.stats_service.enabled:
            return

        user_name = user.full_name or user.username or "Noma'lum"
        try:
            await asyncio.to_thread(
                self.stats_service.add_message_stat,
                message.chat.id,
                user.id,
                user_name,
            )
        except Exception:
            logger.exception("Failed to count message for chat %s", message.chat.id)
