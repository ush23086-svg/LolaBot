import unittest

from app.runtime_fixes import (
    ContextAwareAIProvider,
    _CURRENT_CHAT_ID,
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

    def get_memory(self, chat_id: int, user_id: int) -> str | None:
        return f"memory:{chat_id}:{user_id}"


class RuntimeFixesTest(unittest.IsolatedAsyncioTestCase):
    def test_strips_generic_help_tail(self):
        self.assertEqual(
            strip_generic_help_ending("Mana javob. Sizga qanday yordam bera olaman?"),
            "Mana javob.",
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

    async def test_recent_memory_is_injected_and_tail_is_removed(self):
        base = FakeProvider("Davom etamiz. Yana nimada yordam beray?")
        provider = ContextAwareAIProvider(base, FakeStatsService())
        chat_token = _CURRENT_CHAT_ID.set(-1001)
        user_token = _CURRENT_USER_ID.set(77)
        try:
            answer = await provider.ask_ai("davom et", "Tester", "reply context")
        finally:
            _CURRENT_USER_ID.reset(user_token)
            _CURRENT_CHAT_ID.reset(chat_token)

        self.assertEqual(answer, "Davom etamiz.")
        self.assertIn("memory:-1001:77", base.reply_context)
        self.assertIn("reply context", base.reply_context)


if __name__ == "__main__":
    unittest.main()
