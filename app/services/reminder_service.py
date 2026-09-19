from __future__ import annotations

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

    day_match = _DAY_RE.search(raw)
    time_match = _TIME_RE.search(raw)
    if not day_match or not time_match:
        return None

    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)

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


def _extract_task(text: str) -> str:
    task = _DAY_RE.sub(" ", text, count=1)
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
