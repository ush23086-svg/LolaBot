import time
import unittest
from types import SimpleNamespace

from app.handlers.common import (
    CHAT_DATA,
    _safe_loadout_error,
    _should_handle_meta_list,
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
    MetaEngineError,
    MetaWeapon,
    check_loadout_answer,
    find_selected_weapon,
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


class MetaSelectionTest(unittest.TestCase):
    def setUp(self):
        CHAT_DATA.clear()
        self.weapons = [
            MetaWeapon("Maddox RFB", "Long Range", "", url="https://wzstats.gg/best-loadouts/maddox-rfb", source="WZStatsGG"),
            MetaWeapon("Carbon 57", "Close Range", "", url="https://wzstats.gg/best-loadouts/carbon-57", source="WZStatsGG"),
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
            "Hozirgi meta:\n"
            "1. Maddox RFB - Long Range\n"
            "2. Carbon 57 - Close Range\n"
        )
        parsed = _reply_meta_weapons(fake_message(reply_text=text))
        self.assertEqual(parsed[1]["name"], "Carbon 57")
        self.assertEqual(parsed[1]["url"], "https://wzstats.gg/best-loadouts/carbon-57")

    def test_meta_context_is_user_scoped_and_expires(self):
        first_user = fake_message(chat_id=100, user_id=1)
        second_user = fake_message(chat_id=100, user_id=2)

        _save_meta_context(first_user, "br_ranked", self.weapons)
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["name"], "Carbon 57")
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["source_json"]["mode"], "BR Ranked")
        self.assertEqual(_meta_weapons_from_context(first_user)[1]["source_json"]["weapon"], "Carbon 57")
        self.assertEqual(_meta_weapons_from_context(second_user), [])

        context = _meta_contexts(first_user)[(100, 1)]
        context["expires_at"] = time.monotonic() - 1
        self.assertEqual(_meta_weapons_from_context(first_user), [])

    def test_checker_rejects_fake_attachment(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "BR Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": "S05-9CQNY-PB31",
            "attachments": ["Kuhn Ported Comp"],
        }
        answer = (
            "Manba: WZStatsGG\n"
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
            "mode": "BR Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": None,
            "attachments": [],
        }
        ok, reason = check_loadout_answer(source_json, "Manba: WZStatsGG\nCarbon 57 - Close Range\n\nAttachments:\n- Fake Barrel")
        self.assertFalse(ok)
        self.assertEqual(reason, "unexpected attachments")

    def test_checker_rejects_changed_code(self):
        source_json = {
            "source": "WZStatsGG",
            "mode": "BR Ranked",
            "weapon": "Carbon 57",
            "role": "Close Range",
            "code": "S05-9CQNY-PB31",
            "attachments": [],
        }
        ok, reason = check_loadout_answer(source_json, "Manba: WZStatsGG\nCarbon 57 - Close Range\nCode: WRONG")
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
        self.assertTrue(_should_handle_meta_list("BR Ranked uchun qurol ber", requested_game("BR Ranked uchun qurol ber")))
        self.assertTrue(_should_handle_meta_list("Ranked", requested_game("Ranked")))


if __name__ == "__main__":
    unittest.main()
