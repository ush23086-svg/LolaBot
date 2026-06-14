import time
import unittest
from types import SimpleNamespace

from app.handlers.common import (
    CHAT_DATA,
    _meta_contexts,
    _meta_weapons_from_context,
    _reply_meta_weapons,
    _save_meta_context,
    _selection_index_from_text,
    _selection_is_out_of_range,
)
from app.services.meta_engine import MetaWeapon, find_selected_weapon


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
        self.assertEqual(_meta_weapons_from_context(second_user), [])

        context = _meta_contexts(first_user)[(100, 1)]
        context["expires_at"] = time.monotonic() - 1
        self.assertEqual(_meta_weapons_from_context(first_user), [])


if __name__ == "__main__":
    unittest.main()
