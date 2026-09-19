import unittest

from app.runtime_fixes import (
    ContextAwareAIProvider,
    _CURRENT_CHAT_ID,
    _CURRENT_CHAT_TYPE,
    _CURRENT_USER_ID,
    strip_generic_help_ending,
)
from app.services.ai_provider import AIProvider, GeneratedImage


class FakeProvider(AIProvider):
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.reply_context = ""

    async def ask_ai(self, text: str, user_name: str, reply_context: str = "") -> str:
        self.reply_context = reply_context
        return self.answer

    async def analyze_image(self, image_base64, user_name, caption="", reply_context="") -> str:
        return "vision"

    async def generate_image(self, prompt: str, user_name: str) -> GeneratedImage:
        return GeneratedImage(error="disabled")

    async def keys_status(self) -> list[str]:
        return ["ok"]

    async def vision_status(self) -> list[str]:
        return ["ok"]


class FakeStatsService:
    enabled = True

    def __init__(self) -> None:
        self.last_query = ""

    def get_memory(self, chat_id: int, user_id: int) -> str | None:
        return f"memory:{chat_id}:{user_id}"

    def get_memory_context(self, chat_id: int, user_id: int, query: str = "") -> str | None:
        self.last_query = query
        return f"memory:{chat_id}:{user_id}:{query}"


class RuntimeFixesTest(unittest.IsolatedAsyncioTestCase):
    def test_strips_generic_help_tail(self):
        self.assertEqual(
            strip_generic_help_ending("Mana javob. Sizga qanday yordam bera olaman?"),
            "Mana javob.",
        )
        self.assertEqual(
            strip_generic_help_ending("Mana javob. Sizga qanday yordam berolaman?"),
            "Mana javob.",
        )
        self.assertEqual(
            strip_generic_help_ending("Tushunarli. Sizga qanday yordam berishim mumkin?"),
            "Tushunarli.",
        )
        self.assertEqual(
            strip_generic_help_ending("Готово. Чем я могу помочь?"),
            "Готово.",
        )
        self.assertEqual(
            strip_generic_help_ending("Mana javob, sizga qanday yordam bera olaman?"),
            "Mana javob",
        )
        self.assertEqual(
            strip_generic_help_ending("Tayyor. Yana savolingiz bo‘lsa, bemalol so‘rang."),
            "Tayyor.",
        )

    def test_generic_only_reply_becomes_neutral(self):
        self.assertEqual(strip_generic_help_ending("Sizga qanday yordam beray?"), "Tushundim 🙂")

    async def test_group_member_gets_siz_style_context(self):
        base = FakeProvider("Mayli.")
        stats = FakeStatsService()
        provider = ContextAwareAIProvider(base, stats, owner_id=999)
        chat_token = _CURRENT_CHAT_ID.set(-1001)
        user_token = _CURRENT_USER_ID.set(77)
        type_token = _CURRENT_CHAT_TYPE.set("supergroup")
        try:
            await provider.ask_ai("salom", "Tester")
        finally:
            _CURRENT_CHAT_TYPE.reset(type_token)
            _CURRENT_USER_ID.reset(user_token)
            _CURRENT_CHAT_ID.reset(chat_token)

        self.assertIn("hurmat bilan 'siz'", base.reply_context)

    async def test_owner_can_keep_natural_sen_style_in_group(self):
        base = FakeProvider("Mayli.")
        stats = FakeStatsService()
        provider = ContextAwareAIProvider(base, stats, owner_id=77)
        chat_token = _CURRENT_CHAT_ID.set(-1001)
        user_token = _CURRENT_USER_ID.set(77)
        type_token = _CURRENT_CHAT_TYPE.set("supergroup")
        try:
            await provider.ask_ai("salom", "Tester")
        finally:
            _CURRENT_CHAT_TYPE.reset(type_token)
            _CURRENT_USER_ID.reset(user_token)
            _CURRENT_CHAT_ID.reset(chat_token)

        self.assertIn("bot owneri", base.reply_context)

    async def test_recent_memory_is_injected_and_tail_is_removed(self):
        base = FakeProvider("Davom etamiz. Yana nimada yordam beray?")
        stats = FakeStatsService()
        provider = ContextAwareAIProvider(base, stats)
        chat_token = _CURRENT_CHAT_ID.set(-1001)
        user_token = _CURRENT_USER_ID.set(77)
        try:
            answer = await provider.ask_ai("davom et", "Tester", "reply context")
        finally:
            _CURRENT_USER_ID.reset(user_token)
            _CURRENT_CHAT_ID.reset(chat_token)

        self.assertEqual(answer, "Davom etamiz.")
        self.assertIn("memory:-1001:77:davom et", base.reply_context)
        self.assertIn("reply context", base.reply_context)
        self.assertEqual(stats.last_query, "davom et")


if __name__ == "__main__":
    unittest.main()
