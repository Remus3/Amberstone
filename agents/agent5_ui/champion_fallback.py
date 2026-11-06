"""Round 45 - champion fallback for when live-client (:2999) is dead.

When the local live-client API is unreachable, the legacy RC pipeline
can't populate ``champion`` / ``game_time`` / ``kda`` / ``items_*``
in ``coaching_data.json``. The dashboard header becomes an empty stub.

This module gives the Phase 3 supervisor a best-effort way to *guess*
the user's current champion through three progressively-weaker signals:

  1. LCU champ-select session (only live during lobby / champ select)
  2. Most recent non-TFT row in ``data/match_history.db`` (last game)
  3. Most recent user-input / note task payload mentioning a champion

Returns whichever fires first. Never raises. If all three fail, returns
``None`` and the dashboard stays with its dash placeholder.

Called by the ``/api/locked-champion`` supervisor endpoint every few
seconds; cached briefly to avoid hammering LCU + SQLite.

Trust boundaries (s144 true-audit, RM-1966..RM-1973): the LCU session, the
match_history.db rows and the queue log (fed by /api/input free text) are all
read as untrusted shapes. A junk entry is skipped, never raised past its
probe, and every name handed to the pill is a DDragon-resolved champion, a
one-line champion of a non-TFT match_db game, or the honest
``champion#<id>`` placeholder for a locked id DDragon does not know yet.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("agent5.champion_fallback")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MATCH_DB_PATH = _PROJECT_ROOT / "data" / "match_history.db"
# Must match agents.agent1_lead.scheduler.QUEUE_LOG (path literal, not an
# import, to keep this module free of the scheduler import chain).
_QUEUE_LOG_PATH = _PROJECT_ROOT / "agents" / "state" / "task_queue.jsonl"
_QUEUE_TAIL_BYTES = 64 * 1024
_DDRAGON_CHAMPS_PATH = _PROJECT_ROOT / "data" / "meta" / "ddragon_champions.json"
# Longest champion display name is 14 chars ("Nunu & Willump"); a TFT comp
# label ("Flora Fatalis 2 / Lunar 3 / Executioner 2") runs past 40.
_MAX_NAME_LEN = 32

# DDragon champion ids - the offline floor of the free-text scanner. At
# runtime _champion_lookup() unions this with every id and display name in
# data/meta/ddragon_champions.json, so a champion newer than this list still
# matches once DDragon is refreshed.
_KNOWN_CHAMPIONS: frozenset[str] = frozenset({
    "Aatrox", "Ahri", "Akali", "Akshan", "Alistar", "Ambessa", "Amumu",
    "Anivia", "Annie", "Aphelios", "Ashe", "AurelionSol", "Aurora", "Azir",
    "Bard", "Belveth",
    "Blitzcrank", "Brand", "Braum", "Briar", "Caitlyn", "Camille",
    "Cassiopeia", "Chogath", "Corki", "Darius", "Diana", "Draven",
    "DrMundo", "Ekko", "Elise", "Evelynn", "Ezreal", "Fiddlesticks",
    "Fiora", "Fizz", "Galio", "Gangplank", "Garen", "Gnar", "Gragas",
    "Graves", "Gwen", "Hecarim", "Heimerdinger", "Hwei", "Illaoi",
    "Irelia", "Ivern", "Janna", "JarvanIV", "Jax", "Jayce", "Jhin",
    "Jinx", "Kaisa", "Kalista", "Karma", "Karthus", "Kassadin",
    "Katarina", "Kayle", "Kayn", "Kennen", "Khazix", "Kindred",
    "Kled", "KogMaw", "KSante", "Leblanc", "LeeSin", "Leona", "Lillia",
    "Lissandra", "Locke", "Lucian", "Lulu", "Lux", "Malphite", "Malzahar",
    "Maokai", "MasterYi", "Mel", "Milio", "MissFortune", "MonkeyKing",
    "Mordekaiser", "Morgana", "Naafiri", "Nami", "Nasus", "Nautilus",
    "Neeko", "Nidalee", "Nilah", "Nocturne", "Nunu", "Olaf", "Orianna",
    "Ornn", "Pantheon", "Poppy", "Pyke", "Qiyana", "Quinn", "Rakan",
    "Rammus", "RekSai", "Rell", "Renata", "Renekton", "Rengar",
    "Riven", "Rumble", "Ryze", "Samira", "Sejuani", "Senna", "Seraphine",
    "Sett", "Shaco", "Shen", "Shyvana", "Singed", "Sion", "Sivir",
    "Skarner", "Smolder", "Sona", "Soraka", "Swain", "Sylas", "Syndra",
    "TahmKench", "Taliyah", "Talon", "Taric", "Teemo", "Thresh",
    "Tristana", "Trundle", "Tryndamere", "TwistedFate", "Twitch",
    "Udyr", "Urgot", "Varus", "Vayne", "Veigar", "Velkoz", "Vex",
    "Vi", "Viego", "Viktor", "Vladimir", "Volibear", "Warwick",
    "Xayah", "Xerath", "XinZhao", "Yasuo", "Yone", "Yorick", "Yuumi",
    "Yunara", "Zaahen", "Zac", "Zed", "Zeri", "Ziggs", "Zilean", "Zoe",
    "Zyra",
})

# Display names whose letters-only form is not their id's (the rest - "Lee
# Sin", "Kai'Sa", "Dr. Mundo" - already normalize onto the id).
_DISPLAY_ALIASES: dict[str, str] = {
    "Wukong": "MonkeyKing",
    "Nunu & Willump": "Nunu",
    "Renata Glasc": "Renata",
}

# Cache so the endpoint can be polled every 15s without hammering LCU.
# "ts" is the wall-clock fetch time reported to the caller; "mono" is the
# monotonic stamp the TTL runs on, so a wall-clock step (NTP, DST, a manual
# change) can neither pin a stale entry nor expire a fresh one.
_CACHE: dict[str, Any] = {"champion": None, "source": None, "ts": 0.0, "mono": None}
CACHE_TTL_SEC = 10

_LOOKUP_CACHE: dict[str, str] | None = None
_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _norm(name: str) -> str:
    """Letters-only lower-case form: "Kai'Sa" / "KaiSa" / "kaisa" -> "kaisa"."""
    return "".join(ch for ch in name.lower() if "a" <= ch <= "z")


def _champion_lookup() -> dict[str, str]:
    """Normalized name -> DDragon id, from the static list plus every id and
    display name DDragon carries. Cached once DDragon has been read; while it
    is unreadable the static floor is rebuilt per call (about 175 entries)."""
    global _LOOKUP_CACHE
    if _LOOKUP_CACHE is not None:
        return _LOOKUP_CACHE
    out = {_norm(c): c for c in _KNOWN_CHAMPIONS}
    for display, cid in _DISPLAY_ALIASES.items():
        out[_norm(display)] = cid
    try:
        raw = json.loads(_DDRAGON_CHAMPS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as e:
        logger.debug("ddragon champion list unreadable: %s", e)
        return out
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return out
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        if not isinstance(cid, str) or not _norm(cid):
            continue
        out.setdefault(_norm(cid), cid)
        name = entry.get("name")
        if isinstance(name, str) and _norm(name):
            out.setdefault(_norm(name), cid)
    _LOOKUP_CACHE = out
    return out


def _clean_name(value: object) -> str | None:
    """A champion name fit for the pill: a str that is one printable line of
    1 to _MAX_NAME_LEN chars after strip, holding at least one letter (the
    TEXT-affinity champion column stores a written 42 as the text "42").
    Anything else is None."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > _MAX_NAME_LEN or not name.isprintable():
        return None
    if not any(ch.isalpha() for ch in name):
        return None
    return name


def _ro_uri(db_path: PurePath) -> str:
    """Percent-encoded read-only sqlite URI for ``db_path``.

    An f-string "file:{path}" let a '#' end the path (sqlite reads the rest
    as a fragment) and a '%xx' decode into a different file. Not as_uri(): a
    UNC path becomes file://host/share, which sqlite rejects as a URI
    authority; file:////host/share opens. Same shape as the dashboard
    reader's _ro_uri (dashboard/_context.py).
    """
    quoted = quote(db_path.as_posix(), safe="/:")
    if not quoted.startswith("/"):
        quoted = "/" + quoted
    return f"file://{quoted}?mode=ro"


def _champion_id(value: object) -> int | None:
    """A positive int champion id, else None (a bool is not an id)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _try_lcu_champ_select() -> str | None:
    """Best-effort LCU champ-select read. Returns the local player's locked
    (else hovered) champion name, or None on any failure or no pick.

    The id resolves through the local DDragon list
    (core.archetype_picks.champion_name_by_key) with no second LCU call. The
    pre-audit inventory lookup was keyed by the FIRST teammate's summonerId,
    not the local player's, and its miss shipped "champion#<id>" for every
    pick. An id DDragon does not know yet (a champion newer than the local
    data) keeps that placeholder: it is honest, and falling through to the
    last game's champion would show the wrong one while a pick is live.
    """
    try:
        from lcu.lcu_client import LcuClient
    except Exception as e:       # noqa: BLE001
        logger.debug("LcuClient import failed: %s", e)
        return None
    try:
        c = LcuClient()
        if not c.connect():
            return None
        sess = c._request("GET", "/lol-champ-select/v1/session")
    except Exception as e:       # noqa: BLE001
        logger.debug("champ-select probe failed: %s", e)
        return None
    if not isinstance(sess, dict):
        return None
    local_cell = sess.get("localPlayerCellId")
    # None == None would match a teammate with no cellId, and True == 1
    # would match cell 1: only a real int cell names the local player.
    if isinstance(local_cell, bool) or not isinstance(local_cell, int):
        return None
    team = sess.get("myTeam")
    if not isinstance(team, list):
        return None
    for member in team:
        if not isinstance(member, dict):
            continue
        cell = member.get("cellId")
        if isinstance(cell, bool) or not isinstance(cell, int) or cell != local_cell:
            continue
        cid = (_champion_id(member.get("championId"))
               or _champion_id(member.get("championPickIntent")))
        if cid is None:
            return None
        try:
            from core.archetype_picks import champion_name_by_key
            name = _clean_name(champion_name_by_key(cid))
        except Exception as e:   # noqa: BLE001 - fail-soft resolver
            logger.debug("champion id resolve failed: %s", e)
            name = None
        return name or f"champion#{cid}"
    return None


def _try_match_db_last() -> str | None:
    """Champion of the most recent non-TFT game in match_history.db -
    useful after a match ends or between games when LCU is idle.

    TFT rows are skipped: core/match_db.py stores a TFT game's comp label
    ("Flora Fatalis 2 / Lunar 3 / Executioner 2") in ``champion``. A row
    whose champion is not one printable line of text (a BLOB, a number, a
    newline, an over-long string) is passed over for the next newest.
    """
    if not _MATCH_DB_PATH.is_file():
        return None
    try:
        conn = sqlite3.connect(_ro_uri(_MATCH_DB_PATH), uri=True)
    except sqlite3.Error as e:
        logger.debug("match_db open failed: %s", e)
        return None
    try:
        rows = conn.execute(
            "SELECT champion FROM matches "
            "WHERE typeof(champion) = 'text' AND trim(champion) != '' "
            "AND upper(coalesce(mode, '')) NOT LIKE 'TFT%' "
            "ORDER BY timestamp DESC, id DESC LIMIT 20"
        ).fetchall()
    except sqlite3.Error as e:
        logger.debug("match_db probe failed: %s", e)
        return None
    finally:
        conn.close()
    for (champion,) in rows:
        name = _clean_name(champion)
        if name:
            return name
    return None


def _note_champion(text: str) -> str | None:
    """First champion named in ``text``, as its DDragon id.

    A candidate starts at a Capitalized word (so "my karma is bad" never
    reads as Karma). The two-word join is tried first, so "Lee Sin",
    "Kai'Sa", "Dr. Mundo" and "Miss Fortune" match, then the single word
    ("Jinx", "Vi", "JINX").
    """
    lookup = _champion_lookup()
    words = _TOKEN_RE.findall(text)
    for i, word in enumerate(words):
        if not word[0].isupper():
            continue
        if i + 1 < len(words):
            hit = lookup.get(_norm(word + words[i + 1]))
            if hit:
                return hit
        hit = lookup.get(_norm(word))
        if hit:
            return hit
    return None


def _try_recent_user_note() -> str | None:
    """Walk the newest queue-log entries looking for a champion name in any
    user_text payload. The user typing 'playing Jinx' counts. A line that is
    not a JSON object, or whose task / payload / user_text has the wrong
    shape, is skipped - it never costs the older lines their read."""
    if not _QUEUE_LOG_PATH.is_file():
        return None
    try:
        with _QUEUE_LOG_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _QUEUE_TAIL_BYTES))
            raw = f.read()
    except OSError:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if size > _QUEUE_TAIL_BYTES and lines:
        lines = lines[1:]  # first line is likely truncated mid-record
    # Walk newest-first.
    for line in reversed(lines[-200:]):
        try:
            rec = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(rec, dict):
            continue
        task = rec.get("task")
        payload = task.get("payload") if isinstance(task, dict) else None
        text = payload.get("user_text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text:
            continue
        hit = _note_champion(text)
        if hit:
            return hit
    return None


def current_champion(force_fresh: bool = False) -> dict:
    """Return ``{champion, source, fetched_at_epoch}``.

    ``source`` is one of: ``"lcu"`` / ``"match_db"`` / ``"user_note"`` (each
    with a ``" (cache)"`` suffix on a cache hit) / ``"none"``. Never raises.
    """
    now_wall = time.time()
    now_mono = time.monotonic()
    if not force_fresh:
        snap = dict(_CACHE)
        mono = snap.get("mono")
        if (isinstance(mono, (int, float)) and not isinstance(mono, bool)
                and 0.0 <= now_mono - mono < CACHE_TTL_SEC):
            champion = snap.get("champion")
            source = snap.get("source")
            if not isinstance(source, str) or not source:
                source = "fallback"
            return {
                "champion": champion,
                "source": f"{source} (cache)" if champion else "none",
                "fetched_at_epoch": snap.get("ts"),
            }

    champion: str | None = None
    source = "none"
    for name, probe in (
        ("lcu", _try_lcu_champ_select),
        ("match_db", _try_match_db_last),
        ("user_note", _try_recent_user_note),
    ):
        try:
            got = probe()
        except Exception as e:  # noqa: BLE001
            logger.warning("%s probe raised: %s", name, e)
            continue
        if got:
            champion, source = got, name
            break

    _CACHE.update({"champion": champion, "source": source,
                   "ts": now_wall, "mono": now_mono})
    return {
        "champion": champion,
        "source": source,
        "fetched_at_epoch": now_wall,
    }
