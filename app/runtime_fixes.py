from __future__ import annotations

import asyncio
import re
from contextvars import ContextVar, Token
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.services.ai_provider import AIProvider, GeneratedImage
from app.services.stats_service import StatsService

_CURRENT_CHAT_ID: ContextVar[int | None] = ContextVar("lola_current_chat_id", default=None)
_CURRENT_USER_ID: ContextVar[int | None] = ContextVar("lola_current_user_id", default=None)

_GENERIC_HELP_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bsizga qanday yordam bera olaman\b",
        r"\bsizga qanday yordam beray\b",
        r"\byana qanday yordam kerak\b",
        r"\byana nimada yordam ber(?:ay|ishim mumkin)\b",
        r"\byana savol(?:ingiz)? bo['‘’]?lsa\b",
        r"\bbemalol so['‘’]?ra(?:ng|vering)\b",
        r"\byana biror narsa kerak bo['‘’]?lsa\b",
        r"\bчем я могу помочь\b",
        r"\bмогу ли я (?:ещ[её] )?чем-то помочь\b",
        r"\bесли понадобится помощь\b",
        r"\bhow can i help\b",
        r"\banything else i can help (?:you )?with\b",
        r"\blet me know if you need anything else\b",
    )
)


def _is_allowed_chat(chat_type: str, chat_id: int, main_group_id: int | None) -> bool:
    if chat_type == "private":
        return True
    if main_group_id is None:
        return False
    return int(chat_id) == int(main_group_id)


def _is_generic_help_segment(value: str) -> bool:
    normalized = value.strip(" \t\n\r-—,.;:!?🙂😊😁😄😂🤝")
    return bool(normalized and any(pattern.search(normalized) for pattern in _GENERIC_HELP_PATTERNS))


def strip_generic_help_ending(text: str) -> str:
    answer = (text or "").strip()
    if not answer:
        return answer

    lines = answer.splitlines()
    while lines and _is_generic_help_segment(lines[-1]):
        lines.pop()
    answer = "\n".join(lines).strip()

    if answer:
        parts = re.split(r"(?<=[.!?])\s+", answer)
        while parts and _is_generic_help_segment(parts[-1]):
            parts.pop()
        answer = " ".join(part for part in parts if part).strip()

    return answer or "Tushundim 🙂"


class AllowedChatMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        settings = data.get("settings")
        main_group_id = getattr(settings, "main_group_id", None)
        if not _is_allowed_chat(event.chat.type, event.chat.id, main_group_id):
            return None

        chat_token: Token = _CURRENT_CHAT_ID.set(int(event.chat.id))
        user_id = event.from_user.id if event.from_user else None
        user_token: Token = _CURRENT_USER_ID.set(user_id)
        try:
            return await handler(event, data)
        finally:
            _CURRENT_USER_ID.reset(user_token)
            _CURRENT_CHAT_ID.reset(chat_token)


class ContextAwareAIProvider(AIProvider):
    def __init__(self, base: AIProvider, stats_service: StatsService) -> None:
        self.base = base
        self.stats_service = stats_service

    async def ask_ai(self, text: str, user_name: str, reply_context: str = "") -> str:
        context = reply_context.strip()
        memory = await self._recent_memory()
        if memory:
            memory_context = (
                "Oxirgi suhbat konteksti (faqat davomiylik uchun; userning yangi xabari ustun): "
                f"{memory}"
            )
            context = f"{memory_context}\n{context}" if context else memory_context

        answer = await self.base.ask_ai(text=text, user_name=user_name, reply_context=context)
        return strip_generic_help_ending(answer)

    async def analyze_image(
        self,
        image_base64: str | list[str],
        user_name: str,
        caption: str = "",
        reply_context: str = "",
    ) -> str:
        return await self.base.analyze_image(
            image_base64=image_base64,
            user_name=user_name,
            caption=caption,
            reply_context=reply_context,
        )

    async def generate_image(self, prompt: str, user_name: str) -> GeneratedImage:
        return await self.base.generate_image(prompt=prompt, user_name=user_name)

    async def keys_status(self) -> list[str]:
        return await self.base.keys_status()

    async def vision_status(self) -> list[str]:
        return await self.base.vision_status()

    async def _recent_memory(self) -> str | None:
        chat_id = _CURRENT_CHAT_ID.get()
        user_id = _CURRENT_USER_ID.get()
        if chat_id is None or user_id is None or not self.stats_service.enabled:
            return None
        try:
            return await asyncio.to_thread(self.stats_service.get_memory, chat_id, user_id)
        except Exception:
            return None


class SafeStatsService(StatsService):
    def record_payment(
        self,
        user_id: int,
        user_name: str,
        username: str | None,
        plan: str,
        stars: int,
        payload: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        duration_days: int,
    ):
        if not self.enabled:
            return None

        charge_key = telegram_payment_charge_id or provider_payment_charge_id
        with self._connect() as conn:
            with conn.cursor() as cur:
                if charge_key:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", (charge_key,))
                    if telegram_payment_charge_id:
                        cur.execute(
                            "SELECT 1 FROM payments WHERE telegram_payment_charge_id = %s LIMIT 1;",
                            (telegram_payment_charge_id,),
                        )
                    else:
                        cur.execute(
                            "SELECT 1 FROM payments WHERE provider_payment_charge_id = %s LIMIT 1;",
                            (provider_payment_charge_id,),
                        )
                    if cur.fetchone() is not None:
                        cur.execute(
                            "SELECT premium_until FROM users WHERE user_id = %s;",
                            (user_id,),
                        )
                        row = cur.fetchone()
                        return row["premium_until"] if row else None

                cur.execute(
                    """
                    INSERT INTO users (user_id, user_name, username, premium_until)
                    VALUES (%s, %s, %s, NOW() + (%s * INTERVAL '1 day'))
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        user_name = EXCLUDED.user_name,
                        username = EXCLUDED.username,
                        premium_until = GREATEST(COALESCE(users.premium_until, NOW()), NOW())
                            + (%s * INTERVAL '1 day'),
                        updated_at = NOW()
                    RETURNING premium_until;
                    """,
                    (user_id, user_name, username, duration_days, duration_days),
                )
                premium_until = cur.fetchone()["premium_until"]
                cur.execute(
                    """
                    INSERT INTO payments (
                        user_id,
                        user_name,
                        username,
                        plan,
                        stars,
                        currency,
                        payload,
                        telegram_payment_charge_id,
                        provider_payment_charge_id
                    )
                    VALUES (%s, %s, %s, %s, %s, 'XTR', %s, %s, %s);
                    """,
                    (
                        user_id,
                        user_name,
                        username,
                        plan,
                        stars,
                        payload,
                        telegram_payment_charge_id,
                        provider_payment_charge_id,
                    ),
                )
            conn.commit()

        return premium_until
