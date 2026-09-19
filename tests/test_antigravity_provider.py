import tempfile
import unittest
from unittest.mock import AsyncMock

from app.config import Settings
from app.services.ai_provider import AIProvider, GeneratedImage, build_ai_provider
from app.services.antigravity_provider import AntigravityProvider, _decode_media_item


class StubProvider(AIProvider):
    def __init__(self) -> None:
        self.chat_calls = []
        self.vision_calls = 0

    async def ask_ai(self, text: str, user_name: str, reply_context: str = "") -> str:
        self.chat_calls.append((text, user_name, reply_context))
        return "fallback answer"

    async def analyze_image(
        self,
        image_base64: str | list[str],
        user_name: str,
        caption: str = "",
        reply_context: str = "",
    ) -> str:
        self.vision_calls += 1
        return "vision fallback"

    async def generate_image(self, prompt: str, user_name: str) -> GeneratedImage:
        return GeneratedImage(error="image fallback")

    async def keys_status(self) -> list[str]:
        return ["KEY_1: fallback"]

    async def vision_status(self) -> list[str]:
        return ["vision fallback"]


class AntigravityProviderTest(unittest.IsolatedAsyncioTestCase):
    def make_provider(self) -> tuple[AntigravityProvider, StubProvider]:
        fallback = StubProvider()
        provider = AntigravityProvider(
            command="/home/lola/.local/bin/agy",
            model="gemini-3.8-flash-high",
            reasoning_model=None,
            timeout_seconds=60,
            workdir="/tmp/lola-antigravity-test",
            home="/home/lola",
            fallback=fallback,
        )
        return provider, fallback

    async def test_antigravity_answer_is_primary(self):
        provider, fallback = self.make_provider()
        provider._run = AsyncMock(return_value="Antigravity javobi")

        answer = await provider.ask_ai("Salom", "Tester")

        self.assertEqual(answer, "Antigravity javobi")
        self.assertEqual(fallback.chat_calls, [])

    async def test_openrouter_fallback_when_antigravity_fails(self):
        provider, fallback = self.make_provider()
        provider._run = AsyncMock(return_value=None)

        answer = await provider.ask_ai("Salom", "Tester", "oldingi kontekst")

        self.assertEqual(answer, "fallback answer")
        self.assertEqual(
            fallback.chat_calls,
            [("Salom", "Tester", "oldingi kontekst")],
        )

    async def test_antigravity_vision_is_primary(self):
        provider, fallback = self.make_provider()
        provider._run = AsyncMock(return_value="Rasmda test yozuvi bor")

        answer = await provider.analyze_image("aW1hZ2U=", "Tester", caption="Nima bor?")

        self.assertEqual(answer, "Rasmda test yozuvi bor")
        self.assertEqual(fallback.vision_calls, 0)
        prompt = provider._run.await_args.args[0]
        self.assertIn("Media fayllari:", prompt)
        self.assertIn("Nima bor?", prompt)

    async def test_antigravity_vision_falls_back_if_media_run_fails(self):
        provider, fallback = self.make_provider()
        provider._run = AsyncMock(return_value=None)

        answer = await provider.analyze_image("aW1hZ2U=", "Tester")

        self.assertEqual(answer, "vision fallback")
        self.assertEqual(fallback.vision_calls, 1)

    def test_decode_media_data_url(self):
        decoded = _decode_media_item("data:image/png;base64,aW1hZ2U=")

        self.assertIsNotNone(decoded)
        data, suffix = decoded
        self.assertEqual(data, b"image")
        self.assertEqual(suffix, ".png")

    def test_build_provider_can_select_antigravity(self):
        settings = Settings(
            TELEGRAM_BOT_TOKEN="test-token",
            AI_PROVIDER="antigravity",
            ANTIGRAVITY_COMMAND="/home/lola/.local/bin/agy",
            ANTIGRAVITY_HOME="/home/lola",
        )

        provider = build_ai_provider(settings)

        self.assertIsInstance(provider, AntigravityProvider)


if __name__ == "__main__":
    unittest.main()
