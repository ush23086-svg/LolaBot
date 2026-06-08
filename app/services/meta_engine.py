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
RANKED_META_URL = f"{BASE_URL}/warzoneranked"
WZSTATS_BASE_URL = "https://wzstats.gg"
WZSTATS_WARZONE_META_URL = f"{WZSTATS_BASE_URL}/"
WZSTATS_MW3_META_URL = f"{WZSTATS_BASE_URL}/mw3/meta"
WZSTATS_RANKED_META_URL = f"{WZSTATS_BASE_URL}/warzone/meta/ranked"
META_NOT_FOUND_MESSAGE = "Meta manbalaridan aniq ma'lumot topilmadi, keyinroq qayta urinib ko'ring."

CODE_RE = re.compile(r"^[A-Z]\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+){1,3}$")
PICK_RE = re.compile(r"^\d+(?:\.\d+)?%\s*Pick$", re.IGNORECASE)
PICK_VALUE_RE = re.compile(r"^\d+(?:\.\d+)?%$", re.IGNORECASE)
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
    source: str = "CODMunity"
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
            "source": self.source,
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
            source=data.get("source", "CODMunity"),
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
        return self._get_meta_with_fallback(
            codmunity_url=WARZONE_META_URL,
            wzstats_url=WZSTATS_WARZONE_META_URL,
            game="warzone",
            limit=limit,
        )

    def get_mw3_meta(self, limit: int = 6) -> list[MetaWeapon]:
        return self._get_meta_with_fallback(
            codmunity_url=MW3_META_URL,
            wzstats_url=WZSTATS_MW3_META_URL,
            game="mw3",
            limit=limit,
        )

    def get_ranked_meta(self, limit: int = 6) -> list[MetaWeapon]:
        return self._get_meta_with_fallback(
            codmunity_url=RANKED_META_URL,
            wzstats_url=WZSTATS_RANKED_META_URL,
            game="ranked",
            limit=limit,
        )

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

    def _get_meta_with_fallback(
        self,
        codmunity_url: str,
        wzstats_url: str,
        game: str,
        limit: int,
    ) -> list[MetaWeapon]:
        try:
            return self._get_codmunity_meta(codmunity_url, game=game, limit=limit)
        except MetaEngineError as exc:
            logger.warning("CODMunity %s meta failed, trying WZStatsGG: %s", game, exc)

        try:
            return self._get_wzstats_meta(wzstats_url, game=game, limit=limit)
        except MetaEngineError as exc:
            logger.warning("WZStatsGG %s meta failed: %s", game, exc)
            raise MetaEngineError(META_NOT_FOUND_MESSAGE) from exc

    def _get_codmunity_meta(self, url: str, game: str, limit: int) -> list[MetaWeapon]:
        soup = self._fetch_soup(url)
        links = _weapon_links(soup)
        lines = _visible_lines(soup)
        weapons = _parse_meta_lines(lines, links=links, game=game, limit=limit)
        heading_found = _has_absolute_meta_heading(lines, game)

        logger.info(
            "CODMunity %s meta parse: visible_lines=%s weapon_links=%s parsed_weapons=%s heading_found=%s",
            game,
            len(lines),
            len(links),
            len(weapons),
            heading_found,
        )

        if not heading_found:
            raise MetaEngineError(META_NOT_FOUND_MESSAGE)

        if not weapons:
            raise MetaEngineError(META_NOT_FOUND_MESSAGE)

        return weapons

    def _get_wzstats_meta(self, url: str, game: str, limit: int) -> list[MetaWeapon]:
        soup = self._fetch_soup(url)
        weapons = _parse_wzstats_meta(soup, game=game, limit=limit)
        logger.info("WZStatsGG %s meta parse: parsed_weapons=%s", game, len(weapons))
        if not weapons:
            raise MetaEngineError(META_NOT_FOUND_MESSAGE)
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


def get_ranked_meta(limit: int = 6, timeout: int = 15) -> list[dict]:
    return [weapon.to_dict() for weapon in CodmunityClient(timeout).get_ranked_meta(limit)]


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
    source = weapons[0].source if weapons else "CODMunity"
    lines = [f"Manba: {source}", "Hozirgi meta:"]
    for index, weapon in enumerate(weapons, start=1):
        pick = f" - {weapon.pick}" if weapon.pick else ""
        lines.append(f"{index}. {weapon.name} - {weapon.type}{pick}")
    lines.append("\nKeragini tanlang: masalan, \"2 ni ber\" yoki \"Kogot-7\".")
    return "\n".join(lines)


def format_weapon_loadout(weapon: MetaWeapon) -> str:
    lines = [f"Manba: {weapon.source}", f"{weapon.name} - {weapon.type}"]
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
    return "meta" in query or any(key in query for key in ("warzoneloadout", "mw3loadout", "rankedloadout"))


def requested_game(text: str) -> str | None:
    query = normalize_text(text)
    if "mw3" in query:
        return "mw3"
    if "ranked" in query or "rank" in query:
        return "ranked"
    if "warzone" in query or "warzoneloadout" in query:
        return "warzone"
    return None


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
        name = anchor.get_text(" ", strip=True) or _weapon_name_from_href(href)
        clean_name = _clean_weapon_name(name)
        if clean_name:
            url = urljoin(BASE_URL, href)
            links.setdefault(normalize_text(clean_name), url)
            slug_name = _clean_weapon_name(_weapon_name_from_href(href))
            if slug_name:
                links.setdefault(normalize_text(slug_name), url)
    return links


def _parse_wzstats_meta(soup: Any, game: str, limit: int) -> list[MetaWeapon]:
    weapons: list[MetaWeapon] = []
    seen: set[str] = set()

    for container in soup.select(".loadout-container"):
        anchor = container.select_one("a.sr-only[href]")
        if not anchor:
            continue

        href = anchor.get("href", "")
        if "/best-loadouts/" not in href:
            continue

        name = _wzstats_weapon_name(container, anchor)
        normalized = normalize_text(name)
        if not name or normalized in seen:
            continue

        tags = [_clean_line(tag.get_text(" ", strip=True)) for tag in container.select(".loadout-tag")]
        category = _wzstats_category(tags)
        playstyle = _wzstats_playstyle(tags) or "Meta"

        seen.add(normalized)
        weapons.append(
            MetaWeapon(
                name=name,
                type=playstyle,
                pick="",
                category=category,
                url=urljoin(WZSTATS_BASE_URL, href),
                game=game,
                source="WZStatsGG",
            )
        )
        if len(weapons) >= limit:
            break

    return weapons


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
        elif _is_weapon_candidate(clean_line):
            name = _clean_weapon_name(clean_line)
            window_start = index + 1
        else:
            continue

        if not name or name in {"Warzone Meta", "MW3 Meta", "MW4 Meta"}:
            continue

        window_end = _find_next_weapon_block_index(lines, window_start, rank_re, rank_only_re)
        window = [_clean_line(item) for item in lines[window_start:window_end]]
        category = _first_match(window, WEAPON_CLASSES)
        playstyle = _first_match(window, PLAYSTYLE_TYPES) or "Meta"
        pick = _first_pick(window)
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
                pick=pick,
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
            continue
        if code is None and CODE_RE.match(line):
            code = line

    try:
        attachments_index = block.index("Attachments")
    except ValueError:
        return code, _parse_attachment_pairs(block)

    attachment_lines = block[attachments_index + 1 :]
    for index in range(0, len(attachment_lines) - 1, 2):
        name = attachment_lines[index]
        slot = attachment_lines[index + 1]
        if slot in ATTACHMENT_SLOTS:
            attachments.append(Attachment(slot=slot, name=name))
        if len(attachments) >= 8:
            break

    return code, attachments


def _parse_attachment_pairs(lines: list[str]) -> list[Attachment]:
    attachments: list[Attachment] = []
    for index in range(0, len(lines) - 1):
        name = lines[index]
        slot = lines[index + 1]
        if slot not in ATTACHMENT_SLOTS or not _looks_like_attachment_name(name):
            continue
        attachments.append(Attachment(slot=slot, name=_format_attachment_name(name)))
        if len(attachments) >= 5:
            break
    return attachments


def _looks_like_attachment_name(value: str) -> bool:
    if not value or value in ATTACHMENT_SLOTS:
        return False
    if value in {"Recommended", "Not Unlocked?", "Armory", "Code"}:
        return False
    if value.startswith(("Level ", "Best ", "Loadout", "Warzone", "Black Ops")):
        return False
    return any(ch.isdigit() for ch in value) or value.isupper()


def _format_attachment_name(value: str) -> str:
    if value.isupper():
        return value.title()
    return value


def _find_best_loadout_index(lines: list[str], weapon: MetaWeapon) -> int | None:
    wanted_type = normalize_text(weapon.type)
    wanted_name = normalize_text(weapon.name)

    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if "best" in normalized and "loadoutfor" in normalized and wanted_name in normalized:
            return index

    for index in range(0, len(lines) - 3):
        if (
            normalize_text(lines[index]) == "best"
            and wanted_name in normalize_text(lines[index + 1])
            and normalize_text(lines[index + 2]) == "loadoutfor"
            and (wanted_type in normalize_text(lines[index + 3]) or not wanted_type)
        ):
            return max(0, index - 1)

    for index in range(0, len(lines) - 3):
        if (
            normalize_text(lines[index]) == "best"
            and wanted_name in normalize_text(lines[index + 1])
            and normalize_text(lines[index + 2]) == "loadoutfor"
        ):
            return max(0, index - 1)

    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if "best" in normalized and "loadout" in normalized and wanted_name in normalized:
            if wanted_type in normalized or not wanted_type:
                return index

    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if "best" in normalized and "loadout" in normalized and wanted_name in normalized:
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


def _find_next_weapon_block_index(
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
        if _is_meta_section_heading(line):
            return index
        if rank_re.match(line) or rank_only_re.match(line):
            return index
        if _is_weapon_candidate(line) and _has_weapon_data(lines[start_index:index]):
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
    value = re.sub(r"\s+\d+(?:\.\d+)?%\s*Pick$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(SMG|LMG|Assault Rifle|Sniper Rifle|Marksman Rifle|Shotgun)$", "", value)
    return value.strip()


def _clean_line(value: str) -> str:
    value = value.strip().replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"^#+\s*", "", value).strip()


def _is_absolute_meta_heading(line: str, game: str) -> bool:
    normalized = normalize_text(line)
    if game == "warzone":
        game_aliases = {"warzone"}
    elif game == "ranked":
        game_aliases = {"ranked", "warzoneranked"}
    else:
        game_aliases = {"mw3", "mw4"}
    return normalized.endswith("absolutemeta") and any(alias in normalized for alias in game_aliases)


def _has_absolute_meta_heading(lines: list[str], game: str) -> bool:
    return any(_is_absolute_meta_heading(_clean_line(line), game) for line in lines)


def _is_meta_contenders_heading(line: str) -> bool:
    normalized = normalize_text(line)
    return normalized.endswith("metacontenders")


def _is_meta_section_heading(line: str) -> bool:
    normalized = normalize_text(line)
    return normalized in {"warzonemeta", "mw3meta", "mw4meta"}


def _is_weapon_candidate(line: str) -> bool:
    if not line:
        return False
    if line in WEAPON_CLASSES or line in PLAYSTYLE_TYPES:
        return False
    if line in {"Category", "Pick", "EaseScore", "Last Updated"}:
        return False
    if line.startswith(("The Current", "Discover the current", "Last Updated:")):
        return False
    if _is_absolute_meta_heading(line, "warzone") or _is_absolute_meta_heading(line, "mw3"):
        return False
    if _is_meta_contenders_heading(line) or _is_meta_section_heading(line):
        return False
    if PICK_RE.match(line) or PICK_VALUE_RE.match(line) or CODE_RE.match(line):
        return False
    if re.match(r"^[\d.,]+$", line):
        return False
    return bool(re.search(r"[A-Za-z]", line))


def _has_weapon_data(lines: list[str]) -> bool:
    clean_lines = [_clean_line(line) for line in lines]
    return any(
        line in WEAPON_CLASSES
        or line in PLAYSTYLE_TYPES
        or PICK_RE.match(line)
        or PICK_VALUE_RE.match(line)
        or CODE_RE.match(line)
        for line in clean_lines
    )


def _weapon_name_from_href(href: str) -> str:
    slug = href.rstrip("/").split("/")[-1]
    return " ".join(part.upper() if any(ch.isdigit() for ch in part) else part.capitalize() for part in slug.split("-"))


def _first_pick(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if PICK_RE.match(line):
            return line.replace(" Pick", "")
        if PICK_VALUE_RE.match(line):
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if next_line.lower() == "pick":
                return line
    return ""


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


def _wzstats_weapon_name(container: Any, anchor: Any) -> str:
    name_node = container.select_one(".loadout-content-name")
    if name_node:
        for child in name_node.find_all(True):
            text = _clean_line(child.get_text(" ", strip=True))
            if text and not _wzstats_ignored_name_text(text):
                return _clean_weapon_name(text)

    text = anchor.get_text(" ", strip=True)
    match = re.search(r"Get all the best (.+?) builds", text, flags=re.IGNORECASE)
    if match:
        return _clean_weapon_name(match.group(1))
    return _clean_weapon_name(_weapon_name_from_href(anchor.get("href", "")))


def _wzstats_ignored_name_text(text: str) -> bool:
    return text in {"Buff", "Nerf", "Update"} or text.startswith("#")


def _wzstats_category(tags: list[str]) -> str | None:
    for tag in tags:
        normalized = normalize_text(tag)
        if tag in WEAPON_CLASSES:
            return tag
        if normalized in {"ar", "assaultrifle"}:
            return "Assault Rifle"
        if normalized in {"br", "battlerifle"}:
            return "Battle Rifle"
        if normalized in {"marksman"}:
            return "Marksman Rifle"
        if normalized in {"sniper"}:
            return "Sniper Rifle"
        if normalized == "smg":
            return "SMG"
    return None


def _wzstats_playstyle(tags: list[str]) -> str | None:
    for tag in tags:
        clean_tag = re.sub(r"^#?\d+\s*", "", tag).strip()
        if clean_tag in PLAYSTYLE_TYPES:
            return clean_tag
    return None
