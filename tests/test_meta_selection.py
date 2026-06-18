import asyncio
import time
import unittest
from types import SimpleNamespace

from app.handlers.common import (
    CHAT_DATA,
    LOLA_WAKEUP_REPLIES,
    UNSUPPORTED_MEDIA_REPLY,
    _is_unsupported_gif_or_video,
    _is_supported_image_message,
    _is_exact_lola_wakeup,
    _lola_wakeup_reply,
    _safe_loadout_error,
    _should_handle_meta_list,
    _should_answer_media,
    _should_answer_unsupported_media,
    _should_answer_text,
    _user_label,
    _meta_contexts,
    _meta_weapons_from_context,
    _reply_meta_weapons,
    _save_meta_context,
    _selection_index_from_text,
    _selection_is_out_of_range,
)
from app.services.meta_engine import (
    CHECKER_FAIL_MESSAGE,
    LOADOUT_NOT_FOUND_MESSAGE,
    META_NOT_FOUND_MESSAGE,
    CodmunityClient,
    MetaEngineError,
    MetaWeapon,
    _codmunity_mode_matches,
    _codmunity_page_mode,
    _is_absolute_meta_heading,
    check_loadout_answer,
    find_selected_weapon,
    format_meta_list,
    format_source_loadout,
    requested_game,
)


def fake_message(chat_id=100, user_id=200, reply_text=None):
    reply = None
    if reply_text is not None:
        reply = SimpleNamespace(text=reply_text, caption=None)
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=user_id),
        reply_to_message=reply,
    )


class FakeBot:
    async def me(self):
        return SimpleNamespace(id=999, username="LolaBot")


def fake_media_message(
    chat_type="group",
    chat_id=100,
    caption="",
    reply_from_user_id=None,
    *,
    photo=True,
    document_mime_type=None,
    animation=False,
    video=False,
    sticker=False,
):
    reply = None
    if reply_from_user_id is not None:
        reply = SimpleNamespace(from_user=SimpleNamespace(id=reply_from_user_id))
    document = None
    if document_mime_type is not None:
        document = SimpleNamespace(file_id="document", mime_type=document_mime_type)
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        caption=caption,
        photo=[SimpleNamespace(file_id="photo")] if photo else [],
        document=document,
        animation=SimpleNamespace(file_id="animation", mime_type="image/gif") if animation else None,
        video=SimpleNamespace(file_id="video", mime_type="video/mp4") if video else None,
        sticker=SimpleNamespace(file_id="sticker") if sticker else None,
        reply_to_message=reply,
    )


def fake_text_message(chat_type="group", chat_id=100, text="", reply_from_user_id=None):
    reply = None
    if reply_from_user_id is not None:
        reply = SimpleNamespace(from_user=SimpleNamespace(id=reply_from_user_id))
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        text=text,
        reply_to_message=reply,
    )


def fake_user_message(user_id=1, first_name=None, username=None, full_name=None):
    return SimpleNamespace(
        from_user=SimpleNamespace(
            id=user_id,
            first_name=first_name,
            username=username,
            full_name=full_name,
        )
    )


class MetaSelectionTest(unittest.TestCase):
    def setUp(self):
        CHAT_DATA.clear()
        self.weapons = [
            MetaWeapon("Maddox RFB", "Long Range", "", url="https://wzstats.gg/best-loadouts/maddox-rfb", game="resurgence_ranked", source="WZStatsGG"),
            MetaWeapon("Carbon 57", "Close Range", "", url="https://wzstats.gg/best-loadouts/carbon-57", game="resurgence_ranked", source="WZStatsGG"),
        ]
        self.weapon_dicts = [weapon.to_dict() for weapon in self.weapons]

    def test_number_and_name_selection(self):
        cases = {
            "1": "Maddox RFB",
            "2": "Carbon 57",
            "2 ni ber": "Carbon 57",
            "2-chi": "Carbon 57",
            "ikkinchisini ber": "Carbon 57",
            "Carbon 57ni ber": "Carbon 57",
            "2. Carbon 57": "Carbon 57",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(find_selected_weapon(text, self.weapon_dicts).name, expected)

    def test_out_of_range_number(self):
        self.assertEqual(_selection_index_from_text("9 ni ber"), 8)
        self.assertTrue(_selection_is_out_of_range("9 ni ber", self.weapon_dicts))

    def test_reply_meta_list_parser(self):
        text = (
            "Manba: WZStatsGG\n"
            "Mode: Resurgence Ranked\n"
            "Hozirgi meta:\n"
            "1. Maddox RFB - Long Range\n"
            "2. Carbon 57 - Close Range\n"
        )
        parsed = _reply_meta_weapons(fake_message(reply_text=text))
        self.assertEqual(parsed[1]["name"], "Carbon 57")
        self.assertEqual(parsed[1]["url"], "https://wzstats.gg/best-loadouts/carbon-57")
        self.assertEqual(parsed[1]["source_json"]["mode"], "Resurgence Ranked")

    def test_meta_list_includes_mode(self):
        text = format_meta_list(self.weapons)
        self.assertIn("Manba: WZStatsGG", text)
        self.assertIn("Mode: Resurgence Ranked", text)
        self.assertIn("2. Carbon 57 - Close Range", text)

    def test_loadout_includes_mode(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "Resurgence Ranked",
            "weapon": "AK-27",
            "role": "Long Range",
            "code": "S05-9CQNY-PB31",
            "attachments": [],
        }
        text = format_source_loadout(source_json)
        self.assertTrue(text.startswith("Manba: WZStatsGG\nMode: Resurgence Ranked\nAK-27 - Long Range"))

    def test_meta_context_is_user_scoped_and_expires(self):
        first_user = fake_message(chat_id=100, user_id=1)
        second_user = fake_message(chat_id=100, user_id=2)

        _save_meta_context(first_user, "resurgence_ranked", self.weapons)
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["name"], "Carbon 57")
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["source_json"]["mode"], "Resurgence Ranked")
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["source_json"]["weapon"], "Carbon 57")
        self.assertEqual(_meta_weapons_from_context(second_user), [])

        context = _meta_contexts(first_user)[(100, 1)]
        context["expires_at"] = time.monotonic() - 1
        self.assertEqual(_meta_weapons_from_context(first_user), [])

    def test_checker_rejects_fake_attachment(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "Resurgence Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": "S05-9CQNY-PB31",
            "attachments": ["Kuhn Ported Comp"],
        }
        answer = (
            "Manba: WZStatsGG\n"
            "Mode: Resurgence Ranked\n"
            "Carbon 57 - Close Range\n"
            "Code: S05-9CQNY-PB31\n\n"
            "Attachments:\n"
            "- Kuhn Ported Comp\n"
            "- Fake Barrel"
        )
        ok, reason = check_loadout_answer(source_json, answer)
        self.assertFalse(ok)
        self.assertIn("unknown attachment", reason)

    def test_checker_rejects_attachments_when_source_has_none(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "Resurgence Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": None,
            "attachments": [],
        }
        ok, reason = check_loadout_answer(
            source_json,
            "Manba: WZStatsGG\nMode: Resurgence Ranked\nCarbon 57 - Close Range\n\nAttachments:\n- Fake Barrel",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "unexpected attachments")

    def test_checker_rejects_changed_code(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "Resurgence Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": "S05-9CQNY-PB31",
            "attachments": [],
        }
        ok, reason = check_loadout_answer(source_json, "Manba: WZStatsGG\nMode: Resurgence Ranked\nCarbon 57 - Close Range\nCode: WRONG")
        self.assertFalse(ok)
        self.assertEqual(reason, "code mismatch")

    def test_missing_loadout_error_is_safe(self):
        self.assertEqual(
            _safe_loadout_error(MetaEngineError(LOADOUT_NOT_FOUND_MESSAGE)),
            CHECKER_FAIL_MESSAGE,
        )

    def test_meta_intent_routing(self):
        self.assertFalse(_should_handle_meta_list(
            "BR Ranked bilan Resurgence Ranked nima farqi bor?",
            requested_game("BR Ranked bilan Resurgence Ranked nima farqi bor?"),
        ))
        self.assertFalse(_should_handle_meta_list(
            "Resurgence Ranked nima?",
            requested_game("Resurgence Ranked nima?"),
        ))
        self.assertTrue(_should_handle_meta_list("BR Ranked meta", requested_game("BR Ranked meta")))
        self.assertTrue(_should_handle_meta_list("Ranked meta", requested_game("Ranked meta")))
        self.assertEqual(requested_game("Ranked"), "resurgence_ranked")
        self.assertEqual(requested_game("BR Ranked"), "ranked_unavailable")
        self.assertTrue(_should_handle_meta_list("Ranked", requested_game("Ranked")))

    def test_group_media_allows_plain_photo_in_main_group(self):
        message = fake_media_message(chat_type="group", chat_id=100, caption="")
        settings = SimpleNamespace(main_group_id=100)

        allowed = asyncio.run(_should_answer_media(message, FakeBot(), settings))

        self.assertTrue(allowed)

    def test_main_group_media_ignores_reply_to_human(self):
        message = fake_media_message(
            chat_type="group",
            chat_id=100,
            reply_from_user_id=123,
        )
        settings = SimpleNamespace(main_group_id=100)

        allowed = asyncio.run(_should_answer_media(message, FakeBot(), settings))

        self.assertFalse(allowed)

    def test_main_group_media_allows_reply_to_bot_or_lola_caption(self):
        settings = SimpleNamespace(main_group_id=100)

        reply_allowed = asyncio.run(
            _should_answer_media(
                fake_media_message(chat_type="group", chat_id=100, reply_from_user_id=999),
                FakeBot(),
                settings,
            )
        )
        caption_allowed = asyncio.run(
            _should_answer_media(
                fake_media_message(chat_type="group", chat_id=100, caption="Lola nima bu?"),
                FakeBot(),
                settings,
            )
        )

        self.assertTrue(reply_allowed)
        self.assertTrue(caption_allowed)

    def test_user_label_uses_current_telegram_sender_only(self):
        self.assertEqual(_user_label(fake_user_message(user_id=777, first_name="Jasur")), "Jasur")
        self.assertEqual(_user_label(fake_user_message(user_id=2, first_name="Shaxboz")), "Shaxboz")
        self.assertEqual(_user_label(fake_user_message(user_id=3, username="other_user")), "other_user")
        self.assertEqual(_user_label(fake_user_message(user_id=4)), "")

    def test_user_label_does_not_mix_multiple_senders(self):
        users = [
            fake_user_message(user_id=1, first_name="Shaxboz"),
            fake_user_message(user_id=2, first_name="iKO"),
            fake_user_message(user_id=3, first_name="Sanjar"),
            fake_user_message(user_id=4, username="cod_user"),
            fake_user_message(user_id=5, first_name="Ali"),
        ]

        self.assertEqual([_user_label(user) for user in users], ["Shaxboz", "iKO", "Sanjar", "cod_user", "Ali"])

    def test_exact_lola_wakeup_is_random_reply_eligible(self):
        self.assertTrue(_is_exact_lola_wakeup("Lola"))
        self.assertTrue(_is_exact_lola_wakeup("Lola?"))
        self.assertTrue(_is_exact_lola_wakeup("Lola 😊"))
        self.assertTrue(_is_exact_lola_wakeup("Loola"))
        self.assertTrue(_is_exact_lola_wakeup("Lolaa"))
        self.assertFalse(_is_exact_lola_wakeup("Lola ishlayaptimi?"))
        self.assertGreater(len(LOLA_WAKEUP_REPLIES), 1)

    def test_lola_wakeup_replies_do_not_get_stuck(self):
        replies = [_lola_wakeup_reply() for _ in range(6)]

        self.assertGreater(len(set(replies)), 1)
        for reply in replies:
            self.assertIn(reply, LOLA_WAKEUP_REPLIES)

    def test_lola_mentioned_in_sentence_is_not_group_wakeup(self):
        message = fake_text_message(chat_type="group", text="Lola ishlayaptimi?")

        allowed = asyncio.run(_should_answer_text(message, FakeBot()))

        self.assertFalse(_is_exact_lola_wakeup(message.text))
        self.assertFalse(allowed)

    def test_reply_to_bot_continues_group_chat(self):
        message = fake_text_message(
            chat_type="group",
            text="rasm ko'rasanmi?",
            reply_from_user_id=999,
        )

        allowed = asyncio.run(_should_answer_text(message, FakeBot()))

        self.assertTrue(allowed)

    def test_private_lola_is_allowed(self):
        message = fake_text_message(chat_type="private", text="Lola")

        allowed = asyncio.run(_should_answer_text(message, FakeBot()))

        self.assertTrue(_is_exact_lola_wakeup(message.text))
        self.assertTrue(allowed)

    def test_generic_support_reply_is_not_used_for_lola_wakeup(self):
        for reply in LOLA_WAKEUP_REPLIES:
            lowered = reply.lower()
            self.assertNotIn("qanday yordam beray?", lowered)
            self.assertNotIn("nima yordam kerak?", lowered)
            self.assertNotIn("qanday yordam kerak?", lowered)

    def test_group_plain_gif_is_ignored(self):
        message = fake_media_message(
            chat_type="group",
            photo=False,
            document_mime_type="image/gif",
        )

        self.assertTrue(_is_unsupported_gif_or_video(message))
        allowed = asyncio.run(_should_answer_unsupported_media(message, FakeBot()))

        self.assertFalse(allowed)

    def test_group_addressed_gif_gets_polite_unsupported_reply_path(self):
        caption_message = fake_media_message(
            chat_type="group",
            caption="Lola",
            photo=False,
            document_mime_type="image/gif",
        )
        reply_message = fake_media_message(
            chat_type="group",
            photo=False,
            document_mime_type="image/gif",
            reply_from_user_id=999,
        )

        self.assertTrue(_is_unsupported_gif_or_video(caption_message))
        self.assertTrue(asyncio.run(_should_answer_unsupported_media(caption_message, FakeBot())))
        self.assertTrue(asyncio.run(_should_answer_unsupported_media(reply_message, FakeBot())))
        self.assertIn("GIF/video", UNSUPPORTED_MEDIA_REPLY)

    def test_animation_video_and_sticker_are_unsupported_media(self):
        self.assertTrue(_is_unsupported_gif_or_video(fake_media_message(photo=False, animation=True)))
        self.assertTrue(_is_unsupported_gif_or_video(fake_media_message(photo=False, video=True)))
        self.assertTrue(_is_unsupported_gif_or_video(fake_media_message(photo=False, sticker=True)))

    def test_supported_image_formats_go_to_vision_path(self):
        self.assertTrue(_is_supported_image_message(fake_media_message(photo=True)))
        self.assertTrue(_is_supported_image_message(fake_media_message(photo=False, document_mime_type="image/png")))
        self.assertTrue(_is_supported_image_message(fake_media_message(photo=False, document_mime_type="image/jpeg")))
        self.assertTrue(_is_supported_image_message(fake_media_message(photo=False, document_mime_type="image/webp")))
        self.assertFalse(_is_supported_image_message(fake_media_message(photo=False, document_mime_type="image/gif")))
        self.assertFalse(_is_unsupported_gif_or_video(fake_media_message(photo=False, document_mime_type="image/png")))

    def test_codmunity_success_skips_wzstats_fallback(self):
        client = object.__new__(CodmunityClient)
        codmunity_weapon = MetaWeapon("AK-27", "Long Range", "", game="resurgence_ranked", source="CODMunity")
        calls = {"wzstats": 0}

        def codmunity_meta(url, game, limit):
            return [codmunity_weapon]

        def wzstats_meta(url, game, limit):
            calls["wzstats"] += 1
            raise AssertionError("WZStats should not be called")

        client._get_codmunity_meta = codmunity_meta
        client._get_wzstats_meta = wzstats_meta

        weapons = client._get_meta_with_fallback("codmunity", "wzstats", "resurgence_ranked", 6)

        self.assertEqual(weapons[0].source, "CODMunity")
        self.assertEqual(calls["wzstats"], 0)

    def test_codmunity_fail_uses_wzstats_fallback_source(self):
        client = object.__new__(CodmunityClient)

        def codmunity_meta(url, game, limit):
            raise MetaEngineError(META_NOT_FOUND_MESSAGE)

        def wzstats_meta(url, game, limit):
            return [MetaWeapon("Carbon 57", "Close Range", "", game=game, source="WZStatsGG")]

        client._get_codmunity_meta = codmunity_meta
        client._get_wzstats_meta = wzstats_meta

        weapons = client._get_meta_with_fallback("codmunity", "wzstats", "resurgence_ranked", 6)

        self.assertEqual(weapons[0].source, "WZStatsGG fallback")

    def test_codmunity_ranked_absolute_meta_heading_is_accepted(self):
        self.assertTrue(_is_absolute_meta_heading("Absolute Meta", "resurgence_ranked"))

    def test_codmunity_page_mode_detects_resurgence_ranked(self):
        lines = ["Warzone Ranked Play Meta", "Season 4 brings Ranked to Haven's Hollow (Resurgence) map."]
        self.assertEqual(_codmunity_page_mode(lines), "resurgence_ranked")
        self.assertTrue(_codmunity_mode_matches("resurgence_ranked", "resurgence_ranked"))


if __name__ == "__main__":
    unittest.main()
