from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")

_TIME_RE = re.compile(
    r"\b(?:soat\s*)?(?P<hour>[01]?\d|2[0-3])(?:[:.](?P<minute>[0-5]\d))?\s*(?:da|ga)?\b",
    re.IGNORECASE,
)
_DAY_RE = re.compile(r"\b(?P<day>bugun|ertaga)\b", re.IGNORECASE)
_RELATIVE_RE = re.compile(
    r"\b(?P<count>\d+)\s*(?P<unit>kun|kunda|kundan|hafta|haftada|haftadan|oy|oyda|oydan|yil|yilda|yildan)\s*(?:keyin)?\b",
    re.IGNORECASE,
)
_REMIND_RE = re.compile(
    r"\beslat(?:ib\s+qo['‘’]?y)?(?:gin|ing)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReminderRequest:
    remind_at: datetime
    task: str
    reminder_text: str
    day_label: str


def parse_reminder_request(text: str, now: datetime | None = None) -> ReminderRequest | None:
    raw = (text or "").strip()
    if not raw or not _REMIND_RE.search(raw):
        return None

    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)

    day_match = _DAY_RE.search(raw)
    relative_match = _RELATIVE_RE.search(raw)
    time_match = _TIME_RE.search(raw)

    if relative_match:
        count = int(relative_match.group("count"))
        unit = relative_match.group("unit").lower()
        remind_at = _add_relative(now, count, unit)
        day_label = _relative_label(count, unit)
        if time_match:
            remind_at = remind_at.replace(
                hour=int(time_match.group("hour")),
                minute=int(time_match.group("minute") or 0),
                second=0,
                microsecond=0,
            )
    elif day_match and time_match:
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        day_label = day_match.group("day").lower()
        target_date = now.date() + (timedelta(days=1) if day_label == "ertaga" else timedelta())
        remind_at = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=TZ,
        )
    else:
        return None

    if remind_at <= now:
        return None

    task = _extract_task(raw)
    if not task:
        task = "eslatma"

    return ReminderRequest(
        remind_at=remind_at,
        task=task,
        reminder_text=_reminder_text(task),
        day_label=day_label,
    )


def _add_relative(now: datetime, count: int, unit: str) -> datetime:
    if count <= 0:
        return now

    if unit.startswith("kun"):
        return now + timedelta(days=count)
    if unit.startswith("hafta"):
        return now + timedelta(weeks=count)
    if unit.startswith("oy"):
        month_index = (now.month - 1) + count
        year = now.year + month_index // 12
        month = month_index % 12 + 1
        day = min(now.day, calendar.monthrange(year, month)[1])
        return now.replace(year=year, month=month, day=day)
    if unit.startswith("yil"):
        year = now.year + count
        day = min(now.day, calendar.monthrange(year, now.month)[1])
        return now.replace(year=year, day=day)
    return now


def _relative_label(count: int, unit: str) -> str:
    if unit.startswith("kun"):
        base = "kun"
    elif unit.startswith("hafta"):
        base = "hafta"
    elif unit.startswith("oy"):
        base = "oy"
    else:
        base = "yil"
    return f"{count} {base}dan keyin"


def _extract_task(text: str) -> str:
    task = _DAY_RE.sub(" ", text, count=1)
    task = _RELATIVE_RE.sub(" ", task, count=1)
    task = _TIME_RE.sub(" ", task, count=1)
    task = re.sub(r"\b(?:menga|meni)\b", " ", task, flags=re.IGNORECASE)
    task = _REMIND_RE.sub(" ", task)
    task = re.sub(r"\s+", " ", task).strip(" ,.!?-")
    return task


def _reminder_text(task: str) -> str:
    lowered = task.lower().replace("‘", "'").replace("’", "'")
    if "dori" in lowered and "ich" in lowered:
        return "Doringni ich"
    return f"Eslatma: {task}"
