"""s213: serve DDragon item + rune description JSON from project-root
data/meta/ so the dashboard's lol_descriptions.js lib can build
tooltip lookups client-side.

The dashboard's existing /data/ static route only serves web/data/.
The DDragon dictionary files live at data/meta/ddragon_items.json +
data/meta/ddragon_runes.json (project root) - these are version-pinned
to whatever patch the daemon_slayer pipeline is on.

GET /api/dictionary/items -> ddragon_items.json (item.json from DDragon)
GET /api/dictionary/runes -> ddragon_runes.json (runesReforged.json)

Both responses are unchanged from disk so the client can use them
verbatim. Long-lived Cache-Control since DDragon dumps don't change
between patch refreshes (operator triggers a regen explicitly). Because
that cache is long and immutable (and the clients fetch with
cache:"force-cache"), a file is served only when it parses as a strict
JSON object or array: a truncated or half-written mirror, a NaN /
Infinity token (which JSON.parse refuses) or a non-UTF-8 byte is a
no-store 500, never a day-long cached broken dictionary (S144-T-593).

Every field the champion-tags and augments routes derive from these
files is type-checked: they are third-party snapshots (DDragon,
CommunityDragon), and augment icon URLs are interpolated into an <img
src> attribute by web/js/panels/last_match.js, so an icon path is
reduced to a lower-case [a-z0-9_.-] segment path or dropped. One bad
row never loses the whole map. Failure log lines name the exception
type only.
"""
from __future__ import annotations

import json as _json
import logging
import math
import re
from pathlib import Path

from core import champion_info_overrides as _cio

log = logging.getLogger("rc.web_dashboard")

# Expected read / decode failures of a dictionary file. Anything else is a
# programming error and propagates to the dispatcher's fixed 500.
_READ_ERRORS = (OSError, ValueError, RecursionError)


def _refuse_constant(token: str):
    raise ValueError(f"non-strict JSON constant {token}")


def _read_json(path: Path, *, strict: bool = False):
    """Parse ``path`` as UTF-8 JSON (a leading BOM is dropped, as fetch's
    .json() does). ``strict`` refuses NaN / Infinity tokens."""
    text = path.read_bytes().decode("utf-8-sig")
    if strict:
        return _json.loads(text, parse_constant=_refuse_constant)
    return _json.loads(text)


def _text(value) -> str:
    """A str field passes through; anything else (None, number, bool,
    container, NaN) reads as the empty string the client already treats
    as absent."""
    return value if isinstance(value, str) else ""


def _rating(value) -> int:
    """A DDragon info rating (0-10 scale). A finite non-bool real is
    truncated like int() and clamped to 0..10; anything else is 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float):
        if not math.isfinite(value):
            return 0
        value = int(value)
    return max(0, min(10, value))

_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_items.json"
_RUNES_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_runes.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"


_DICT_CACHE_CONTROL = "public, max-age=86400, immutable"
# champion-tags layers curated damage-profile overrides (core.champion_info_
# overrides) on top of the patch data, so - unlike the immutable raw items/runes
# dumps - it must be revalidatable: a short, NON-immutable cache lets a curated
# edit or a DDragon refresh show up on a normal reload without a hard refresh
# (honoring champion_tags.js's cache:"default" revalidation intent).
_CHAMPION_TAGS_CACHE_CONTROL = "public, max-age=300"


def _serve_file(h, path: Path) -> None:
    if not path.is_file():
        h._send(404, b'{"error":"dictionary file missing"}', "application/json")
        return
    try:
        body = path.read_bytes()
        parsed = _json.loads(body.decode("utf-8-sig"),
                             parse_constant=_refuse_constant)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("dictionary root is not a JSON container")
    except _READ_ERRORS as exc:
        log.warning("dictionary serve %s: %s", path.name, type(exc).__name__)
        h._send(500, b'{"error":"dictionary_read_failed"}', "application/json")
        return
    h._send(200, body, "application/json; charset=utf-8",
            cache_control=_DICT_CACHE_CONTROL)


def _serve_items(h) -> None: _serve_file(h, _ITEMS_PATH)
def _serve_runes(h) -> None: _serve_file(h, _RUNES_PATH)


# s213 v2: compact champion-tag map for the enemies panel's 2-piece
# identifier (e.g., Thresh -> ["CC", "TANK"]). Built from DDragon's
# info.attack/magic/defense + tags array + our hardcoded CC and burst
# sets. The frontend uses this to render comp-aware tags + a role
# confidence percentage on each enemy cell.
_HARD_CC_NAMES = frozenset({
    "Blitzcrank", "Thresh", "Pyke", "Nautilus", "Skarner",
    "Morgana", "Lillia", "Neeko", "Lulu", "Ivern", "Zyra", "Cassiopeia",
    "Leona", "Annie", "Veigar", "Pantheon", "Sett", "Taric",
    "TwistedFate", "Twisted Fate", "Vex", "Zilean",
    "Ashe", "Sejuani", "Maokai", "Galio", "Amumu", "Sion", "Volibear",
    "Wukong", "MonkeyKing", "Alistar", "Braum", "Rakan", "Rell",
    "Jarvan IV", "JarvanIV", "Diana", "Malzahar", "Warwick", "Urgot",
})
_BURST_NAMES = frozenset({
    "Rengar", "Zed", "Talon", "Kha'Zix", "KhaZix", "Pantheon", "Kindred",
    "Master Yi", "MasterYi", "Yi", "Camille", "Riven", "Yone", "Yasuo",
    "Veigar", "Annie", "LeBlanc", "Syndra", "Lux", "Brand", "Akali",
    "Fizz", "Kassadin", "Diana", "Katarina", "Ekko", "Ahri", "Vex",
    "Hwei", "Naafiri",
})


def _damage_profile_tag(name, tags_raw, attack, magic) -> str:
    """tag1: the enemy cell's damage-profile chip (CC / BURST / AD / AP).

    The hardcoded CC + BURST override sets win first; otherwise DDragon's
    info.attack vs info.magic ratings decide AD vs AP. Guard: when BOTH ratings
    are zero the champ's DDragon info block is missing (e.g. Seraphine, whose
    zeroed block made the 0>=0 tie default to AD - operator-reported 2026-06-30);
    fall back to the role tags there - a Marksman is AD, anything else
    (mage / support / enchanter) is AP. Valid-info champs are UNCHANGED, so a
    hybrid like Azir (Mage+Marksman, magic>attack) still resolves AP.
    Junk never raises: a non-str name reads "", a non-sequence tags value
    reads empty (a str is NOT split per character), and each rating goes
    through _rating (finite real clamped to 0..10, else 0)."""
    name = _text(name)
    if not isinstance(tags_raw, (list, tuple)):
        tags_raw = ()
    attack = _rating(attack)
    magic = _rating(magic)
    if (name in _HARD_CC_NAMES
            or name.replace("'", "") in _HARD_CC_NAMES
            or name.replace(" ", "") in _HARD_CC_NAMES):
        return "CC"
    if (name in _BURST_NAMES
            or name.replace("'", "") in _BURST_NAMES
            or name.replace(" ", "") in _BURST_NAMES):
        return "BURST"
    if attack == 0 and magic == 0:
        return "AD" if "Marksman" in tags_raw else "AP"
    return "AD" if attack >= magic else "AP"


def _serve_champion_tags(h) -> None:
    if not _CHAMPS_PATH.is_file():
        h._send(404, b'{"error":"ddragon_champions.json missing"}', "application/json")
        return
    try:
        raw = _read_json(_CHAMPS_PATH)
        if not isinstance(raw, dict):
            raise ValueError("champions root is not an object")
        data = raw.get("data", raw)
        if not isinstance(data, dict):
            raise ValueError("champions data is not an object")
    except _READ_ERRORS as exc:
        log.warning("dictionary champion-tags: %s", type(exc).__name__)
        h._send(500, b'{"error":"champion_tags_failed"}', "application/json")
        return
    out: dict = {}
    for entry in data.values():
        tags_entry = _champion_tag_entry(entry)
        if tags_entry is None:
            continue
        name = entry["name"].strip()
        # s213 v3 fix: store under display name + DDragon slug +
        # spelling variants so the dashboard's CHAMPS lookups
        # ("Kaisa" without apostrophe but with lowercase s) match
        # the display name "Kai'Sa".
        out[name] = tags_entry
        out[name.replace("'", "")] = tags_entry
        out[name.replace(" ", "")] = tags_entry
        out[name.replace("'", "").replace(" ", "")] = tags_entry
        slug = _text(entry.get("id")).strip()
        if slug:
            out[slug] = tags_entry
    h._send(200, _json.dumps(out, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
            cache_control=_CHAMPION_TAGS_CACHE_CONTROL)


def _champion_tag_entry(entry) -> dict | None:
    """One DDragon champion row -> its tag entry, or None when the row has
    no usable name. Every field is type-checked so one junk row is skipped
    or neutralised instead of losing the whole map: a non-str / blank name
    skips the row, a non-list tags value reads empty (a str is never split
    per character) and non-str tag elements are dropped, and each rating
    goes through _rating."""
    if not isinstance(entry, dict):
        return None
    name = _text(entry.get("name")).strip()
    if not name:
        return None
    # Overlay the curated damage-profile override for champs DDragon
    # leaves zeroed (Seraphine/Akshan/Rell/Vex all-zero, Qiyana attack=0)
    # so the AD/AP chip is not driven by missing info - see
    # core.champion_info_overrides.
    info = _cio.merged_info(name, entry.get("info") or {})
    tags_field = entry.get("tags")
    tags_raw = ([t for t in tags_field if isinstance(t, str)]
                if isinstance(tags_field, (list, tuple)) else [])
    attack = _rating(info.get("attack"))
    magic = _rating(info.get("magic"))
    defense = _rating(info.get("defense"))
    # 2-piece identifier:
    #  - tag 0 = damage profile or special signal (CC / BURST / AD / AP)
    #  - tag 1 = archetype (TANK / BRUISER / ASSASSIN / SUPPORT / MAGE / ADC)
    tag1 = _damage_profile_tag(name, tags_raw, attack, magic)
    if "Tank" in tags_raw:
        tag2 = "TANK"
    elif "Fighter" in tags_raw:
        tag2 = "BRUISER"
    elif "Assassin" in tags_raw:
        tag2 = "ASSASSIN"
    elif "Support" in tags_raw:
        tag2 = "SUPPORT"
    elif "Marksman" in tags_raw:
        tag2 = "ADC"
    elif "Mage" in tags_raw:
        tag2 = "MAGE"
    else:
        tag2 = "FLEX"
    return {
        "tags":    [tag1, tag2],
        "attack":  attack,
        "magic":   magic,
        "defense": defense,
        "primary": tags_raw[0] if tags_raw else "",
    }


# s-PGR-S2: per-player augment icons for the Post Game Review roster
# (ARAM Mayhem / Arena). The augment id -> {name, rarity, icon} table
# is the patch-versioned cherry_augments.json snapshot that
# core.augment_external_source already builds + consumes; the stored
# `icon` is the raw LCU virtual path, so we transform it here to the
# CommunityDragon raw mirror (same base as that module's
# CHERRY_AUGMENTS_URL) so the client just gets a fetchable URL.
_DS_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_CDRAGON_GAMEDATA_BASE = (
    "https://raw.communitydragon.org/latest/plugins/"
    "rcp-be-lol-game-data/global/default/"
)


# data/daemon_slayer/<patch>/ directory names are DDragon versions
# (major.minor.build). current.txt is joined onto the data dir, so anything
# else (a "..", an absolute path, a second line) reads as no patch.
_PATCH_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,4}")
# A lowered CDragon asset path: "/"-separated segments of [a-z0-9_.-]. The
# result is interpolated into an <img src="..."> attribute client-side, so no
# quote, space, "?", "#", backslash or non-ASCII byte may survive, and a "."
# or ".." segment would walk off the plugin root.
_ICON_SEGMENT_RE = re.compile(r"[a-z0-9_.\-]+")


def _current_ds_patch() -> str:
    try:
        text = (_DS_DATA_DIR / "current.txt").read_bytes().decode("utf-8-sig")
    except (OSError, ValueError):
        return ""
    patch = text.strip()
    return patch if _PATCH_RE.fullmatch(patch) else ""


def _cdragon_icon_url(icon_path) -> str:
    """LCU virtual asset path -> CommunityDragon raw mirror URL.

    cherry_augments.json stores
    `/lol-game-data/assets/ASSETS/UX/Cherry/Augments/Icons/X_small.png`;
    CommunityDragon serves it under the rcp-be-lol-game-data plugin
    root, lowercased. Empty in -> empty out (client hides the img), and
    so is a non-str value or a path that is not a plain segment path
    (see _ICON_SEGMENT_RE)."""
    p = _text(icon_path).strip()
    if not p:
        return ""
    low = p.lstrip("/").lower()
    marker = "lol-game-data/"
    low = low.removeprefix(marker)
    segments = low.split("/")
    for seg in segments:
        if seg in (".", "..") or not _ICON_SEGMENT_RE.fullmatch(seg):
            return ""
    return _CDRAGON_GAMEDATA_BASE + low


def _serve_augments(h) -> None:
    """Compact id -> {name, icon_url, rarity} for roster augment icons.
    Built from the current-patch cherry_augments.json. Long-lived
    client cache - only changes on an operator-triggered patch refresh."""
    patch = _current_ds_patch()
    src = (_DS_DATA_DIR / patch / "cherry_augments.json") if patch else None
    if src is None or not src.is_file():
        h._send(404, b'{"error":"cherry_augments.json missing"}', "application/json")
        return
    try:
        raw = _read_json(src)
        if not isinstance(raw, dict):
            raise ValueError("augments root is not an object")
        augs = raw.get("augments")
        if augs is None:
            augs = {}
        if not isinstance(augs, dict):
            raise ValueError("augments table is not an object")
    except _READ_ERRORS as exc:
        log.warning("dictionary augments: %s", type(exc).__name__)
        h._send(500, b'{"error":"augments_read_failed"}', "application/json")
        return
    out: dict = {}
    for aid, row in augs.items():
        if not isinstance(row, dict):
            continue
        # Every field is str or "": a number / container / NaN never
        # reaches the client (a NaN used to emit a bare NaN token that
        # JSON.parse refuses, losing every roster icon).
        out[str(aid)] = {
            "name":     _text(row.get("name")),
            "rarity":   _text(row.get("rarity")),
            "icon_url": _cdragon_icon_url(row.get("icon")),
        }
    body = _json.dumps({"patch": patch, "augments": out},
                       allow_nan=False).encode("utf-8")
    h._send(200, body, "application/json; charset=utf-8",
            cache_control=_DICT_CACHE_CONTROL)


def _equals(p: str):
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/dictionary/items"),         _serve_items),
    (_equals("/api/dictionary/runes"),         _serve_runes),
    (_equals("/api/dictionary/champion-tags"), _serve_champion_tags),
    (_equals("/api/dictionary/augments"),      _serve_augments),
]
POST_ROUTES: list = []
