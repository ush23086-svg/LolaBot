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
        self.assertEqual(reminder.reminder_text, "Doringni ich")
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

    def test_two_weeks_without_time_keeps_message_time(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)

        reminder = parse_reminder_request(
            "2 haftadan keyin admin bolalarni kechirishi kerakligini eslat",
            now=now,
        )

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.remind_at, datetime(2026, 10, 3, 11, 35, tzinfo=TZ))
        self.assertEqual(reminder.day_label, "2 haftadan keyin")
        self.assertEqual(reminder.task, "admin bolalarni kechirishi kerakligini")

    def test_relative_reminder_can_override_clock_time(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)

        reminder = parse_reminder_request(
            "3 kundan keyin soat 9 da hujjatlarni olishni eslat",
            now=now,
        )

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder.remind_at, datetime(2026, 9, 22, 9, 0, tzinfo=TZ))
        self.assertEqual(reminder.task, "hujjatlarni olishni")

    def test_month_and_year_reminders(self):
        now = datetime(2026, 1, 31, 8, 15, tzinfo=TZ)

        month_reminder = parse_reminder_request(
            "1 oydan keyin abonent to'lovini eslat",
            now=now,
        )
        year_reminder = parse_reminder_request(
            "1 yildan keyin shu testni eslat",
            now=now,
        )

        self.assertIsNotNone(month_reminder)
        self.assertEqual(month_reminder.remind_at, datetime(2026, 2, 28, 8, 15, tzinfo=TZ))
        self.assertIsNotNone(year_reminder)
        self.assertEqual(year_reminder.remind_at, datetime(2027, 1, 31, 8, 15, tzinfo=TZ))

    def test_non_reminder_is_ignored(self):
        now = datetime(2026, 9, 19, 11, 35, tzinfo=TZ)
        self.assertIsNone(parse_reminder_request("Ertaga 10:00 da uchrashuv bor", now=now))


if __name__ == "__main__":
    unittest.main()
