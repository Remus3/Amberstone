"""s213: serve DDragon item + rune description JSON from project-root
data/meta/ so the dashboard's lol_descriptions.js lib can build
tooltip lookups client-side.

The dashboard's existing /data/ static route only serves web/data/.
The DDragon dictionary files live at data/meta/ddragon_items.json +
data/meta/ddragon_runes.json (project root) - these are version-pinned
to whatever patch the daemon_slayer pipeline is on (currently 16.12.1).

GET /api/dictionary/items → ddragon_items.json (item.json from DDragon)
GET /api/dictionary/runes → ddragon_runes.json (runesReforged.json)

Both responses are unchanged from disk so the client can use them
verbatim. Long-lived Cache-Control since DDragon dumps don't change
between patch refreshes (operator triggers a regen explicitly).
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("rc.web_dashboard")

_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_items.json"
_RUNES_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_runes.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"


_DICT_CACHE_CONTROL = "public, max-age=86400, immutable"


def _serve_file(h, path: Path) -> None:
    if not path.is_file():
        h._send(404, b'{"error":"dictionary file missing"}', "application/json")
        return
    try:
        h._send(200, path.read_bytes(), "application/json; charset=utf-8",
                cache_control=_DICT_CACHE_CONTROL)
    except Exception as exc:
        log.warning("dictionary serve %s: %s", path.name, exc)
        h._send(500, b'{"error":"dictionary_read_failed"}', "application/json")


def _serve_items(h) -> None: _serve_file(h, _ITEMS_PATH)
def _serve_runes(h) -> None: _serve_file(h, _RUNES_PATH)


# s213 v2: compact champion-tag map for the enemies panel's 2-piece
# identifier (e.g., Thresh → ["CC", "TANK"]). Built from DDragon's
# info.attack/magic/defense + tags array + our hardcoded CC and burst
# sets. The frontend uses this to render comp-aware tags + a role
# confidence percentage on each enemy cell.
import json as _json

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


def _serve_champion_tags(h) -> None:
    if not _CHAMPS_PATH.is_file():
        h._send(404, b'{"error":"ddragon_champions.json missing"}', "application/json")
        return
    try:
        raw = _json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        out: dict = {}
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            info = entry.get("info") or {}
            tags_raw = list(entry.get("tags") or [])
            attack = int(info.get("attack") or 0)
            magic = int(info.get("magic") or 0)
            defense = int(info.get("defense") or 0)
            is_cc = (name in _HARD_CC_NAMES
                     or name.replace("'", "") in _HARD_CC_NAMES
                     or name.replace(" ", "") in _HARD_CC_NAMES)
            is_burst = (name in _BURST_NAMES
                        or name.replace("'", "") in _BURST_NAMES
                        or name.replace(" ", "") in _BURST_NAMES)
            # 2-piece identifier:
            #  - tag 0 = damage profile or special signal (CC / BURST / AD / AP / TRUE)
            #  - tag 1 = archetype (TANK / BRUISER / ASSASSIN / SUPPORT / MAGE / ADC)
            tag1 = "CC" if is_cc else ("BURST" if is_burst else ("AD" if attack >= magic else "AP"))
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
            tags_entry = {
                "tags":    [tag1, tag2],
                "attack":  attack,
                "magic":   magic,
                "defense": defense,
                "primary": tags_raw[0] if tags_raw else "",
            }
            # s213 v3 fix: store under display name + DDragon slug +
            # spelling variants so the dashboard's CHAMPS lookups
            # ("Kaisa" without apostrophe but with lowercase s) match
            # the display name "Kai'Sa".
            slug = entry.get("id") or ""
            out[name] = tags_entry
            out[name.replace("'", "")] = tags_entry
            out[name.replace(" ", "")] = tags_entry
            out[name.replace("'", "").replace(" ", "")] = tags_entry
            if slug:
                out[slug] = tags_entry
        h._send(200, _json.dumps(out).encode("utf-8"), "application/json; charset=utf-8",
                cache_control=_DICT_CACHE_CONTROL)
    except Exception as exc:
        log.warning("dictionary champion-tags: %s", exc)
        h._send(500, b'{"error":"champion_tags_failed"}', "application/json")


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


def _current_ds_patch() -> str:
    try:
        return (_DS_DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _cdragon_icon_url(icon_path: str) -> str:
    """LCU virtual asset path -> CommunityDragon raw mirror URL.

    cherry_augments.json stores
    `/lol-game-data/assets/ASSETS/UX/Cherry/Augments/Icons/X_small.png`;
    CommunityDragon serves it under the rcp-be-lol-game-data plugin
    root, lowercased. Empty in -> empty out (client hides the img)."""
    p = (icon_path or "").strip()
    if not p:
        return ""
    low = p.lstrip("/").lower()
    marker = "lol-game-data/"
    if low.startswith(marker):
        low = low[len(marker):]
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
        raw = _json.loads(src.read_text(encoding="utf-8"))
        augs = raw.get("augments") or {}
        out: dict = {}
        for aid, row in augs.items():
            if not isinstance(row, dict):
                continue
            out[str(aid)] = {
                "name":     row.get("name") or "",
                "rarity":   row.get("rarity") or "",
                "icon_url": _cdragon_icon_url(row.get("icon") or ""),
            }
        body = _json.dumps({"patch": patch, "augments": out}).encode("utf-8")
        h._send(200, body, "application/json; charset=utf-8",
                cache_control=_DICT_CACHE_CONTROL)
    except Exception as exc:
        log.warning("dictionary augments: %s", exc)
        h._send(500, b'{"error":"augments_read_failed"}', "application/json")


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
