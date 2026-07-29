from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

SUPPORTED_HOSTS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be"),
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "x": ("x.com", "twitter.com"),
}

# The handler uses this only as a fast pre-filter. The URL is still parsed and
# checked against the exact host allow-list below before it enters the queue.
SUPPORTED_LINK_PATTERN = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?(?:youtube\.com|youtu\.be|instagram\.com|instagr\.am|"
    r"tiktok\.com|x\.com|twitter\.com)(?:/[^\s<>]*)?",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?;:)]}\"'»”"


def _host_matches(host: str, allowed: str) -> bool:
    return host == allowed or host.endswith(f".{allowed}")


def classify_supported_url(raw_url: str) -> tuple[str, str] | None:
    """Return a normalized URL and source name when the host is supported."""

    candidate = (raw_url or "").strip().rstrip(TRAILING_PUNCTUATION)
    if not candidate:
        return None

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.username or parsed.password:
        return None

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None

    source = next(
        (
            name
            for name, hosts in SUPPORTED_HOSTS.items()
            if any(_host_matches(host, allowed) for allowed in hosts)
        ),
        None,
    )
    if source is None:
        return None

    # Fragments are not required for downloading and can contain tracking data.
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return normalized, source


def extract_supported_url(text: str | None) -> tuple[str, str] | None:
    """Extract the first supported social/video URL from a Telegram message."""

    for match in URL_PATTERN.finditer(text or ""):
        result = classify_supported_url(match.group(0))
        if result is not None:
            return result
    return None


def parse_chat_ids(raw: str | None) -> set[int]:
    """Parse the explicit comma/space separated video chat allow-list."""

    values: set[int] = set()
    if raw:
        for part in re.split(r"[,;\s]+", raw.strip()):
            if not part:
                continue
            try:
                values.add(int(part))
            except ValueError:
                continue

    return values
