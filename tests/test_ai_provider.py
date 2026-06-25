import unittest

from app.services import ai_provider as provider_module
from app.config import (
    OPENROUTER_DEFAULT_FALLBACK_MODEL,
    OPENROUTER_DEFAULT_REASONING_MODEL,
    OPENROUTER_DEFAULT_VISION_MODEL,
    Settings,
    _clean_models,
)
from app.services.ai_provider import OpenRouterProvider
from app.services.ai_provider import MEDIA_ANALYSIS_PHRASES
from app.services.ai_provider import MEDIA_REACTION_MAX_CHARS
from app.services.ai_provider import _sanitize_user_name_leak
from app.services.ai_provider import _strip_markdown_emphasis


class FakeResponse:
    def __init__(self, status, data, headers=None):
        self.status = status
        self._data = data
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self._data

    async def text(self):
        return str(self._data)


class FakeSession:
    responses = []
    attempts = []

    def __init__(self, headers=None, timeout=None):
        self.headers = headers or {}
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        FakeSession.attempts.append(
            {
                "authorization": self.headers.get("Authorization", ""),
                "model": json.get("model"),
                "content": json.get("messages", [{}])[-1].get("content"),
            }
        )
        if not FakeSession.responses:
            raise AssertionError("No fake response queued")
        response = FakeSession.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class OpenRouterProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_session = provider_module.aiohttp.ClientSession
        provider_module.aiohttp.ClientSession = FakeSession
        FakeSession.responses = []
        FakeSession.attempts = []

    def tearDown(self):
        provider_module.aiohttp.ClientSession = self.original_session

    async def test_429_rotates_to_next_key(self):
        FakeSession.responses = [
            FakeResponse(429, {"error": "free-models-per-day"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1"), (3, "secret-key-3")],
            models=["free-model"],
            vision_models=[],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.ask_ai("hi", "Tester")

        self.assertEqual(answer, "ok")
        self.assertEqual(len(FakeSession.attempts), 2)
        self.assertEqual(FakeSession.attempts[0]["authorization"], "Bearer secret-key-1")
        self.assertEqual(FakeSession.attempts[1]["authorization"], "Bearer secret-key-3")

    async def test_chat_uses_preferred_key_order(self):
        FakeSession.responses = [
            FakeResponse(429, {"error": "rate limit"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(429, {"error": "rate limit"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[
                (1, "secret-key-1"),
                (2, "secret-key-2"),
                (3, "secret-key-3"),
                (4, "secret-key-4"),
                (5, "secret-key-5"),
            ],
            models=["chat-model"],
            vision_models=[],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.ask_ai("hi", "Tester")

        self.assertEqual(answer, "ok")
        self.assertEqual(
            [attempt["authorization"] for attempt in FakeSession.attempts],
            ["Bearer secret-key-1", "Bearer secret-key-3", "Bearer secret-key-2"],
        )

    async def test_chat_429_still_tries_fallback_model_on_same_key(self):
        FakeSession.responses = [
            FakeResponse(429, {"error": "rate limit"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(200, {"choices": [{"message": {"content": "fallback ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1"), (3, "secret-key-3")],
            models=["chat-model", "fallback-model"],
            vision_models=[],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.ask_ai("hi", "Tester")

        self.assertEqual(answer, "fallback ok")
        self.assertEqual(
            [attempt["model"] for attempt in FakeSession.attempts],
            ["chat-model", "fallback-model"],
        )
        self.assertEqual(
            [attempt["authorization"] for attempt in FakeSession.attempts],
            ["Bearer secret-key-1", "Bearer secret-key-1"],
        )

    async def test_reasoning_request_uses_reasoning_model(self):
        FakeSession.responses = [
            FakeResponse(200, {"choices": [{"message": {"content": "4"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1")],
            models=["chat-model", "fallback-model"],
            vision_models=[],
            image_models=[],
            reasoning_models=["reasoning-model", "fallback-model"],
            app_name="Lola",
        )

        answer = await provider.ask_ai("2+2 nechchi?", "Tester")

        self.assertEqual(answer, "4")
        self.assertEqual(FakeSession.attempts[0]["model"], "reasoning-model")

    async def test_vision_falls_back_to_second_model_before_next_key(self):
        FakeSession.responses = [
            TimeoutError("slow vision model"),
            FakeResponse(200, {"choices": [{"message": {"content": "vision ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1"), (3, "secret-key-3")],
            models=["chat-model"],
            vision_models=["vision-model-1", "vision-model-2"],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.analyze_image("aW1hZ2U=", "Tester")

        self.assertEqual(answer, "vision ok")
        self.assertEqual(
            [attempt["model"] for attempt in FakeSession.attempts],
            ["vision-model-1", "vision-model-2"],
        )

    async def test_vision_accepts_multiple_frame_data_urls(self):
        FakeSession.responses = [
            FakeResponse(200, {"choices": [{"message": {"content": "frame ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1")],
            models=["chat-model"],
            vision_models=["vision-model"],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.analyze_image(
            [
                "data:image/jpeg;base64,Zmlyc3Q=",
                "data:image/jpeg;base64,c2Vjb25k",
            ],
            "Tester",
        )

        self.assertEqual(answer, "frame ok")
        content = FakeSession.attempts[0]["content"]
        self.assertEqual([item["type"] for item in content].count("image_url"), 2)
        self.assertIn("framelarini", content[0]["text"])

    async def test_media_reaction_removes_analysis_style_and_stays_short(self):
        long_tail = " ".join(["yana"] * 80)
        FakeSession.responses = [
            FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Stickerda bu yerda rasmda captiondagi hazil "
                                    "deyotgandek ko'rinmoqda, rosa troll vibe 😂. "
                                    f"{long_tail}"
                                )
                            }
                        }
                    ]
                },
            ),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1")],
            models=["chat-model"],
            vision_models=["vision-model"],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.analyze_image(
            ["data:image/webp;base64,c3RpY2tlcg=="],
            "Tester",
        )

        lowered = answer.lower()
        for phrase in MEDIA_ANALYSIS_PHRASES:
            self.assertNotIn(phrase, lowered)
        for phrase in ("bu yerda", "captionda"):
            self.assertNotIn(phrase, lowered)
        self.assertLessEqual(len(answer), MEDIA_REACTION_MAX_CHARS)

    async def test_vision_string_uses_static_image_prompt(self):
        FakeSession.responses = [
            FakeResponse(200, {"choices": [{"message": {"content": "static ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1")],
            models=["chat-model"],
            vision_models=["vision-model"],
            image_models=[],
            app_name="Lola",
        )

        answer = await provider.analyze_image("aW1hZ2U=", "Tester")

        self.assertEqual(answer, "static ok")
        content = FakeSession.attempts[0]["content"]
        self.assertIn("Rasmni caption bilan birga tushun", content[0]["text"])
        self.assertNotIn("framelarini", content[0]["text"])

    async def test_keys_status_masks_real_keys(self):
        FakeSession.responses = [
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            FakeResponse(429, {"error": "rate limit"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            FakeResponse(429, {"error": "rate limit"}, {"X-RateLimit-Remaining": "0"}),
            FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=["secret-key-1", "secret-key-2"],
            models=["chat-model", "fallback-model"],
            vision_models=["vision-model"],
            image_models=[],
            app_name="Lola",
        )

        rows = await provider.keys_status()
        text = "\n".join(rows)

        self.assertIn("KEY_1:", text)
        self.assertIn("- chat model: OK", text)
        self.assertIn("- vision model: 429 rate limit", text)
        self.assertIn("- fallback model: OK", text)
        self.assertIn("KEY_2:", text)
        self.assertNotIn("secret-key", text)
        self.assertEqual(
            [attempt["model"] for attempt in FakeSession.attempts],
            [
                "chat-model",
                "vision-model",
                "fallback-model",
                "chat-model",
                "vision-model",
                "fallback-model",
            ],
        )

    async def test_vision_status_uses_image_payload(self):
        FakeSession.responses = [
            FakeResponse(200, {"choices": [{"message": {"content": "red"}}]}),
            FakeResponse(200, {"choices": [{"message": {"content": "not sure"}}]}),
        ]
        provider = OpenRouterProvider(
            api_keys=[(1, "secret-key-1")],
            models=["chat-model"],
            vision_models=["vision-model-1", "vision-model-2"],
            image_models=[],
            app_name="Lola",
        )

        rows = await provider.vision_status()
        text = "\n".join(rows)

        self.assertIn("KEY_1:", text)
        self.assertIn("- vision model: OK", text)
        self.assertIn("- vision model 2: image-not-understood", text)
        self.assertNotIn("secret-key", text)
        self.assertEqual([attempt["model"] for attempt in FakeSession.attempts], ["vision-model-1", "vision-model-2"])
        self.assertIsInstance(FakeSession.attempts[0]["content"], list)


class ModelConfigTest(unittest.TestCase):
    def test_bad_railway_model_names_are_normalized(self):
        models = _clean_models(["google/gemma-3-27b-it:free", "gemini-1.5-flash"])

        self.assertEqual(
            models,
            [OPENROUTER_DEFAULT_FALLBACK_MODEL, OPENROUTER_DEFAULT_REASONING_MODEL],
        )

    def test_legacy_free_vision_model_is_normalized(self):
        models = _clean_models(["nex-agi/nex-n2-pro:free"])

        self.assertEqual(models, [OPENROUTER_DEFAULT_VISION_MODEL])

    def test_openrouter_vision_models_supports_comma_separated_fallbacks(self):
        settings = Settings(
            TELEGRAM_BOT_TOKEN="token",
            VISION_MODEL="primary-vision",
            OPENROUTER_VISION_MODELS="fallback-one, fallback-two\nfallback-three",
        )

        self.assertEqual(
            settings.openrouter_vision_models,
            ["primary-vision", "fallback-one", "fallback-two", "fallback-three"],
        )

    def test_numbered_vision_models_are_not_ignored_by_default_vision_model(self):
        settings = Settings(
            TELEGRAM_BOT_TOKEN="token",
            OPENROUTER_VISION_MODEL_1="fallback-one",
            OPENROUTER_VISION_MODEL_2="fallback-two",
        )

        self.assertEqual(
            settings.openrouter_vision_models,
            [OPENROUTER_DEFAULT_VISION_MODEL, "fallback-one", "fallback-two"],
        )

    def test_sanitize_wrong_name_salutation(self):
        self.assertEqual(
            _sanitize_user_name_leak("Shaxboz, tushunarli.", "iKO"),
            "iKO, tushunarli.",
        )
        self.assertEqual(
            _sanitize_user_name_leak("Shaxboz, tushunarli.", "Shaxboz"),
            "Shaxboz, tushunarli.",
        )
        self.assertEqual(
            _sanitize_user_name_leak("iKO, bo'ldi.", "Sanjar"),
            "Sanjar, bo'ldi.",
        )
        self.assertEqual(
            _sanitize_user_name_leak("Jasur, ko'rdim.", ""),
            "ko'rdim.",
        )

    def test_strip_markdown_emphasis_from_image_answer(self):
        self.assertEqual(
            _strip_markdown_emphasis("Bu **game screenshot** ko'rinadi ***"),
            "Bu game screenshot ko'rinadi ",
        )


if __name__ == "__main__":
    unittest.main()
