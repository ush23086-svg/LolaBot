import unittest

from app.config import OPENROUTER_DEFAULT_VISION_MODEL, Settings, _clean_models


class ModelConfigVisionTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
