from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://codmunity.gg"
WARZONE_META_URL = f"{BASE_URL}/warzone"
MW3_META_URL = f"{BASE_URL}/mw3"

CODE_RE = re.compile(r"^[A-Z]\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+){1,3}$")
PICK_RE = re.compile(r"^\d+(?:\.\d+)?%\s*Pick$", re.IGNORECASE)
NUMBER_RE = re.compile(r"(\d{1,2})")

ORDINALS = {
    "birinchi": 1,
    "1chi": 1,
    "1-chisi": 1,
    "ikkinchi": 2,
    "2chi": 2,
    "2-chisi": 2,
    "uchinchi": 3,
    "3chi": 3,
    "3-chisi": 3,
    "tortinchi": 4,
    "to'rtinchi": 4,
    "4chi": 4,
    "beshinchi": 5,
    "5chi": 5,
}

WEAPON_CLASSES = {
    "Assault Rifle",
    "SMG",
    "LMG",
    "Sniper Rifle",
    "Marksman Rifle",
    "Shotgun",
    "Pistol",
    "Battle Rifle",
    "Melee",
}

PLAYSTYLE_TYPES = {
    "Long Range",
    "Close Range",
    "Sniper",
    "Sniper Support",
    "Secondary",
    "Semi Auto",
    "Versatile",
    "Small Map",
    "Mid Range",
}

ATTACHMENT_SLOTS = {
    "Optic",
    "Muzzle",
    "Barrel",
    "Magazine",
    "Stock",
    "Rear Grip",
    "Underbarrel",
    "Laser",
    "Fire Mods",
    "Ammunition",
    "Comb",
    "Bolt",
    "Conversion Kit",
}


class MetaEngineError(RuntimeError):
    pass


@dataclass
class Attachment:
    slot: str
    name: str


@dataclass
class MetaWeapon:
    name: str
    type: str
    pick: str
    code: str | None = None
    category: str | None = None
    url: str | None = None
    game: str = "warzone"
    attachments: list[Attachment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "pick": self.pick,
            "code": self.code,
            "category": self.category,
            "url": self.url,
            "game": self.game,
            "attachments": [attachment.__dict__ for attachment in self.attachments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetaWeapon":
        return cls(
            name=data["name"],
            type=data["type"],
            pick=data["pick"],
            code=data.get("code"),
            category=data.get("category"),
            url=data.get("url"),
            game=data.get("game", "warzone"),
            attachments=[
                Attachment(slot=item["slot"], name=item["name"])
                for item in data.get("attachments", [])
            ],
        )


class CodmunityClient:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        try:
            import requests
        except ImportError as exc:
            raise MetaEngineError(
                "CODMunity'dan ma'lumot olish uchun requests kutubxonasi o'rnatilishi kerak"
            ) from exc

        self.requests = requests
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; LolaBot/1.0)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def get_warzone_meta(self, limit: int = 6) -> list[MetaWeapon]:
        return self._get_meta(WARZONE_META_URL, game="warzone", limit=limit)

    def get_mw3_meta(self, limit: int = 6) -> list[MetaWeapon]:
        return self._get_meta(MW3_META_URL, game="mw3", limit=limit)

    def get_weapon_loadout(self, weapon: MetaWeapon) -> MetaWeapon:
        if not weapon.url:
            raise MetaEngineError("CODMunity'dan ma'lumot olishda muammo bo'ldi")

        soup = self._fetch_soup(weapon.url)
        lines = _visible_lines(soup)
        code, attachments = _parse_loadout_details(lines, weapon)

        if not code and not attachments:
            raise MetaEngineError("CODMunity'dan ma'lumot olishda muammo bo'ldi")

        weapon.code = code or weapon.code
        weapon.attachments = attachments
        return weapon

    def _get_meta(self, url: str, game: str, limit: int) -> list[MetaWeapon]:
        soup = self._fetch_soup(url)
        links = _weapon_links(soup)
        lines = _visible_lines(soup)
        weapons = _parse_meta_lines(lines, links=links, game=game, limit=limit)

        if not weapons:
            raise MetaEngineError("CODMunity'dan ma'lumot olishda muammo bo'ldi")

        return weapons

    def _fetch_soup(self, url: str) -> Any:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise MetaEngineError(
                "CODMunity HTML parser uchun beautifulsoup4 kutubxonasi o'rnatilishi kerak"
            ) from exc

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except self.requests.RequestException as exc:
            logger.warning("CODMunity request failed: %s", exc)
            raise MetaEngineError("CODMunity'dan ma'lumot olishda muammo bo'ldi") from exc

        return BeautifulSoup(response.text, "html.parser")


def get_warzone_meta(limit: int = 6, timeout: int = 15) -> list[dict]:
    return [weapon.to_dict() for weapon in CodmunityClient(timeout).get_warzone_meta(limit)]


def get_mw3_meta(limit: int = 6, timeout: int = 15) -> list[dict]:
    return [weapon.to_dict() for weapon in CodmunityClient(timeout).get_mw3_meta(limit)]


def find_selected_weapon(text: str, weapons: Iterable[dict | MetaWeapon]) -> MetaWeapon | None:
    weapon_list = [
        item if isinstance(item, MetaWeapon) else MetaWeapon.from_dict(item)
        for item in weapons
    ]
    query = normalize_text(text)

    selected_index = _selection_index(query)
    if selected_index is not None and 0 <= selected_index < len(weapon_list):
        return weapon_list[selected_index]

    for weapon in weapon_list:
        aliases = {
            normalize_text(weapon.name),
            normalize_text(weapon.name.replace("-", " ")),
            normalize_text(weapon.name.replace(".", "")),
        }
        aliases.update(
            normalize_text(part)
            for part in re.split(r"[\s\-.]+", weapon.name)
            if len(normalize_text(part)) >= 4
        )
        if weapon.code:
            aliases.add(normalize_text(weapon.code))

        if any(alias and (alias in query or query in alias) for alias in aliases):
            return weapon

    return None


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("o'", "o").replace("g'", "g")
    return re.sub(r"[^a-z0-9]+", "", value)


def format_meta_list(weapons: list[MetaWeapon]) -> str:
    lines = ["CODMunity bo'yicha hozirgi meta:"]
    for index, weapon in enumerate(weapons, start=1):
        pick = f" - {weapon.pick}" if weapon.pick else ""
        lines.append(f"{index}. {weapon.name} - {weapon.type}{pick}")
    lines.append("\nKeragini tanlang: masalan, \"2 ni ber\" yoki \"Kogot-7\".")
    return "\n".join(lines)


def format_weapon_loadout(weapon: MetaWeapon) -> str:
    lines = [f"{weapon.name} - {weapon.type}"]
    if weapon.pick:
        lines.append(f"Pick rate: {weapon.pick}")
    if weapon.code:
        lines.append(f"Code: {weapon.code}")
    if weapon.attachments:
        lines.append("\nAttachments:")
        for attachment in weapon.attachments:
            lines.append(f"- {attachment.slot}: {attachment.name}")
    if not weapon.code and not weapon.attachments:
        raise MetaEngineError("CODMunity'dan ma'lumot olishda muammo bo'ldi")
    return "\n".join(lines)


def is_meta_request(text: str) -> bool:
    query = normalize_text(text)
    return "meta" in query or any(key in query for key in ("warzoneloadout", "mw3loadout"))


def requested_game(text: str) -> str:
    query = normalize_text(text)
    if "mw3" in query:
        return "mw3"
    return "warzone"


def _visible_lines(soup: Any) -> list[str]:
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    return [
        _clean_line(line)
        for line in soup.get_text("\n").splitlines()
        if _clean_line(line)
    ]


def _weapon_links(soup: Any) -> dict[str, str]:
    links: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/weapon/" not in href:
            continue
        name = anchor.get_text(" ", strip=True)
        clean_name = _clean_weapon_name(name)
        if clean_name:
            links.setdefault(normalize_text(clean_name), urljoin(BASE_URL, href))
    return links


def _parse_meta_lines(
    lines: list[str],
    links: dict[str, str],
    game: str,
    limit: int,
) -> list[MetaWeapon]:
    weapons: list[MetaWeapon] = []
    in_ranking = False
    rank_re = re.compile(r"^\d+\.\s+(.+)$")
    rank_only_re = re.compile(r"^\d+\.$")
    seen: set[tuple[str, str]] = set()

    for index, line in enumerate(lines):
        clean_line = _clean_line(line)
        if _is_absolute_meta_heading(clean_line, game):
            in_ranking = True
            continue

        if in_ranking and _is_meta_contenders_heading(clean_line):
            break

        if not in_ranking:
            continue

        match = rank_re.match(clean_line)
        if match:
            name = _clean_weapon_name(match.group(1))
            window_start = index + 1
        elif rank_only_re.match(clean_line) and index + 1 < len(lines):
            name = _clean_weapon_name(lines[index + 1])
            window_start = index + 2
        else:
            continue

        if not name or name in {"Warzone Meta", "MW3 Meta", "MW4 Meta"}:
            continue

        window_end = _find_next_rank_index(lines, window_start, rank_re, rank_only_re)
        window = [_clean_line(item) for item in lines[window_start:window_end]]
        category = _first_match(window, WEAPON_CLASSES)
        playstyle = _first_match(window, PLAYSTYLE_TYPES) or "Meta"
        pick = _first_pattern(window, PICK_RE)
        code = _first_pattern(window, CODE_RE)

        seen_key = (normalize_text(name), normalize_text(playstyle))
        if seen_key in seen:
            continue
        seen.add(seen_key)

        url = links.get(normalize_text(name))
        weapons.append(
            MetaWeapon(
                name=name,
                type=playstyle,
                pick=pick.replace(" Pick", "") if pick else "",
                code=code,
                category=category,
                url=url,
                game=game,
            )
        )

        if len(weapons) >= limit:
            break

    return weapons


def _parse_loadout_details(lines: list[str], weapon: MetaWeapon) -> tuple[str | None, list[Attachment]]:
    code = None
    attachments: list[Attachment] = []
    start_index = _find_best_loadout_index(lines, weapon)

    if start_index is None:
        return None, []

    end_index = _find_next_boundary(lines, start_index + 1)
    block = lines[start_index:end_index]

    for line in block:
        if line.startswith("Code:"):
            value = line.replace("Code:", "", 1).strip()
            if CODE_RE.match(value):
                code = value

    try:
        attachments_index = block.index("Attachments")
    except ValueError:
        return code, []

    attachment_lines = block[attachments_index + 1 :]
    for index in range(0, len(attachment_lines) - 1, 2):
        name = attachment_lines[index]
        slot = attachment_lines[index + 1]
        if slot in ATTACHMENT_SLOTS:
            attachments.append(Attachment(slot=slot, name=name))
        if len(attachments) >= 8:
            break

    return code, attachments


def _find_best_loadout_index(lines: list[str], weapon: MetaWeapon) -> int | None:
    wanted_type = normalize_text(weapon.type)
    wanted_name = normalize_text(weapon.name)

    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if "best" in normalized and "loadout" in normalized and wanted_name in normalized:
            if wanted_type in normalized or not wanted_type:
                return index

    for index, line in enumerate(lines):
        if line == weapon.type:
            return index

    return None


def _find_next_boundary(lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines)):
        line = lines[index]
        if line.startswith(("Time To Kill", "Key Stats", "Exclusive loadouts", "##")):
            return index
        if index > start_index + 80:
            return index
    return len(lines)


def _find_next_rank_index(
    lines: list[str],
    start_index: int,
    rank_re: re.Pattern[str],
    rank_only_re: re.Pattern[str],
) -> int:
    fallback_end = min(len(lines), start_index + 12)
    for index in range(start_index, len(lines)):
        line = _clean_line(lines[index])
        if _is_meta_contenders_heading(line):
            return index
        if rank_re.match(line) or rank_only_re.match(line):
            return index
        if index >= fallback_end:
            return fallback_end
    return len(lines)


def _selection_index(query: str) -> int | None:
    for word, number in ORDINALS.items():
        if normalize_text(word) in query:
            return number - 1

    match = NUMBER_RE.search(query)
    if match:
        number = int(match.group(1))
        if number > 0:
            return number - 1

    return None


def _clean_weapon_name(value: str) -> str:
    value = _clean_line(value)
    value = re.sub(r"^\d+\.\s*", "", value).strip()
    value = re.sub(r"^#+\s*", "", value).strip()
    value = re.sub(r"\s+(SMG|LMG|Assault Rifle|Sniper Rifle|Marksman Rifle|Shotgun)$", "", value)
    return value.strip()


def _clean_line(value: str) -> str:
    value = value.strip().replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"^#+\s*", "", value).strip()


def _is_absolute_meta_heading(line: str, game: str) -> bool:
    normalized = normalize_text(line)
    game_aliases = {"warzone"} if game == "warzone" else {"mw3", "mw4"}
    return normalized.endswith("absolutemeta") and any(alias in normalized for alias in game_aliases)


def _is_meta_contenders_heading(line: str) -> bool:
    normalized = normalize_text(line)
    return normalized.endswith("metacontenders")


def _first_match(lines: list[str], values: set[str]) -> str | None:
    for line in lines:
        if line in values:
            return line
    return None


def _first_pattern(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        if pattern.match(line):
            return line
    return None
