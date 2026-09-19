import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.reminder_service import parse_reminder_request

TZ = ZoneInfo("Asia/Tashkent")


class ReminderParserTest(unittest.TestCase):
    def test_tomorrow_medicine_reminder(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)

        reminder = parse_reminder_request(
            "Ertaga 10:00 da dori ichishni eslat",
            now=now,
        )

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.remind_at, datetime(2026, 9, 20, 10, 0, tzinfo=TZ))
        self.assertEqual(reminder.task, "dori ichishni")
        self.assertEqual(reminder.reminder_text, "Doringni ich 💊")
        self.assertEqual(reminder.day_label, "ertaga")

    def test_supports_soat_and_single_hour(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)

        reminder = parse_reminder_request(
            "Menga ertaga soat 9 da hujjatlarni olishni eslat",
            now=now,
        )

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.remind_at.hour, 9)
        self.assertEqual(reminder.remind_at.minute, 0)
        self.assertEqual(reminder.task, "hujjatlarni olishni")

    def test_past_today_time_is_not_scheduled(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)

        reminder = parse_reminder_request(
            "Bugun 10:00 da dori ichishni eslat",
            now=now,
        )

        self.assertIsNone(reminder)

    def test_non_reminder_is_ignored(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)
        self.assertIsNone(parse_reminder_request("Ertaga 10:00 da uchrashuv bor", now=now))


if __name__ == "__main__":
    unittest.main()
