import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.handlers.common import _should_answer_text
from app.services.video_links import (
    classify_supported_url,
    extract_supported_url,
    parse_chat_ids,
)


class VideoLinksTest(unittest.TestCase):
    def test_extracts_supported_link_from_text(self) -> None:
        result = extract_supported_url(
            "mana video https://www.instagram.com/reel/ABC123/?utm_source=test"
        )
        self.assertIsNotNone(result)
        assert result is not None
        url, source = result
        self.assertEqual(source, "instagram")
        self.assertTrue(url.startswith("https://www.instagram.com/reel/ABC123/"))

    def test_supports_short_and_mobile_hosts(self) -> None:
        self.assertEqual(classify_supported_url("https://youtu.be/abc")[1], "youtube")
        self.assertEqual(classify_supported_url("https://vm.tiktok.com/abc")[1], "tiktok")
        self.assertEqual(classify_supported_url("https://mobile.twitter.com/a/status/1")[1], "x")

    def test_rejects_lookalike_and_credentials(self) -> None:
        self.assertIsNone(classify_supported_url("https://youtube.com.evil.example/video"))
        self.assertIsNone(classify_supported_url("https://user:pass@youtube.com/video"))
        self.assertIsNone(classify_supported_url("ftp://youtube.com/video"))

    def test_strips_trailing_message_punctuation(self) -> None:
        result = classify_supported_url("https://x.com/test/status/123).")
        self.assertEqual(result, ("https://x.com/test/status/123", "x"))

    def test_chat_id_allow_list_falls_back_to_main_group(self) -> None:
        self.assertEqual(parse_chat_ids(None, -100123), {-100123})
        self.assertEqual(
            parse_chat_ids("-1001, -1002 invalid; -1001", -1009),
            {-1001, -1002},
        )


class VideoDiscussionRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_plain_reply_to_bot_video_is_not_an_ai_prompt(self) -> None:
        bot = SimpleNamespace(
            me=AsyncMock(
                return_value=SimpleNamespace(id=42, username="lola_bot")
            )
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(type="supergroup", id=-1001),
            text="zo'r video ekan",
            reply_to_message=SimpleNamespace(
                from_user=SimpleNamespace(id=42),
                video=object(),
            ),
        )

        self.assertFalse(await _should_answer_text(message, bot))

    async def test_explicit_mention_under_bot_video_still_works(self) -> None:
        bot = SimpleNamespace(
            me=AsyncMock(
                return_value=SimpleNamespace(id=42, username="lola_bot")
            )
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(type="supergroup", id=-1001),
            text="@lola_bot shu haqida ayt",
            reply_to_message=SimpleNamespace(
                from_user=SimpleNamespace(id=42),
                video=object(),
            ),
        )

        self.assertTrue(await _should_answer_text(message, bot))


if __name__ == "__main__":
    unittest.main()
