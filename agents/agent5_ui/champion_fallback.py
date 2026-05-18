"""Round 45 - champion fallback for when live-client (:2999) is dead.

When Game-PC's live-client API is unreachable, the legacy RC pipeline
can't populate ``champion`` / ``game_time`` / ``kda`` / ``items_*``
in ``coaching_data.json``. The dashboard header becomes an empty stub.

This module gives the Phase 3 supervisor a best-effort way to *guess*
the user's current champion through three progressively-weaker signals:

  1. LCU champ-select session (only live during lobby / champ select)
  2. Most recent row in ``data/match_history.db`` (last completed game)
  3. Most recent user-input / note task payload mentioning a champion

Returns whichever fires first. Never raises. If all three fail, returns
``None`` and the dashboard stays with its dash placeholder.

Called by the ``/api/locked-champion`` supervisor endpoint every few
seconds; cached briefly to avoid hammering LCU + SQLite.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent5.champion_fallback")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MATCH_DB_PATH = _PROJECT_ROOT / "data" / "match_history.db"
_QUEUE_LOG_PATH = _PROJECT_ROOT / "data" / "task_queue.jsonl"

# Well-known LoL champion names - cheap filter when scanning free-text
# user input. Not exhaustive; additions go here as needed.
_KNOWN_CHAMPIONS: frozenset[str] = frozenset({
    "Aatrox", "Ahri", "Akali", "Akshan", "Alistar", "Amumu", "Anivia",
    "Annie", "Aphelios", "Ashe", "AurelionSol", "Azir", "Bard", "Belveth",
    "Blitzcrank", "Brand", "Braum", "Briar", "Caitlyn", "Camille",
    "Cassiopeia", "Chogath", "Corki", "Darius", "Diana", "Draven",
    "DrMundo", "Ekko", "Elise", "Evelynn", "Ezreal", "Fiddlesticks",
    "Fiora", "Fizz", "Galio", "Gangplank", "Garen", "Gnar", "Gragas",
    "Graves", "Gwen", "Hecarim", "Heimerdinger", "Hwei", "Illaoi",
    "Irelia", "Ivern", "Janna", "JarvanIV", "Jax", "Jayce", "Jhin",
    "Jinx", "Kaisa", "Kalista", "Karma", "Karthus", "Kassadin",
    "Katarina", "Kayle", "Kayn", "Kennen", "Khazix", "Kindred",
    "Kled", "KogMaw", "KSante", "Leblanc", "LeeSin", "Leona", "Lillia",
    "Lissandra", "Lucian", "Lulu", "Lux", "Malphite", "Malzahar",
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
    "Yunara", "Zac", "Zed", "Zeri", "Ziggs", "Zilean", "Zoe", "Zyra",
})

# Cache so the endpoint can be polled every 15s without hammering LCU.
_CACHE: dict[str, Any] = {"champion": None, "source": None, "ts": 0.0}
CACHE_TTL_SEC = 10


def _try_lcu_champ_select() -> str | None:
    """Best-effort LCU champ-select read. Returns the locked champion
    name or None on any failure."""
    try:
        from lcu.lcu_client import LcuClient
    except Exception as e:       # noqa: BLE001
        logger.debug("LcuClient import failed: %s", e)
        return None
    c = LcuClient()
    try:
        if not c.connect():
            return None
        sess = c._request("GET", "/lol-champ-select/v1/session")
    except Exception as e:       # noqa: BLE001
        logger.debug("champ-select probe failed: %s", e)
        return None
    if not sess or not isinstance(sess, dict):
        return None
    local_cell = sess.get("localPlayerCellId")
    for team in (sess.get("myTeam") or []):
        if team.get("cellId") == local_cell:
            cid = team.get("championId") or team.get("championPickIntent")
            if cid:
                # Need id → name. Quick probe: LCU champion summary cache.
                try:
                    summ = c._request(
                        "GET",
                        f"/lol-champions/v1/inventories/summoners/"
                        f"{sess.get('myTeam')[0].get('summonerId', 0)}/"
                        f"champions-minimal/{cid}",
                    )
                    if summ and summ.get("alias"):
                        return str(summ["alias"])
                except Exception:  # noqa: BLE001
                    pass
                return f"champion#{cid}"
    return None


def _try_match_db_last() -> str | None:
    """Most recent row in match_history.db - useful after a match ends
    or between games when LCU is idle."""
    if not _MATCH_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{_MATCH_DB_PATH.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT champion FROM matches "
            "WHERE champion IS NOT NULL AND champion != '' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        logger.debug("match_db probe failed: %s", e)
        return None
    if row and row["champion"]:
        return str(row["champion"])
    return None


def _try_recent_user_note() -> str | None:
    """Walk the last ~50 queue-log entries looking for a champion name
    in any user_text payload. The user typing 'playing Jinx' counts."""
    if not _QUEUE_LOG_PATH.exists():
        return None
    try:
        with _QUEUE_LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    word_re = re.compile(r"\b([A-Z][a-zA-Z]{2,15})\b")
    # Walk newest-first.
    for line in reversed(lines[-200:]):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        task = rec.get("task") or {}
        payload = task.get("payload") or {}
        text = (payload.get("user_text") or "")
        if not text:
            continue
        for match in word_re.findall(text):
            # Case-insensitive match against known champions.
            for champ in _KNOWN_CHAMPIONS:
                if champ.lower() == match.lower():
                    return champ
    return None


def current_champion(force_fresh: bool = False) -> dict:
    """Return ``{champion, source, fetched_at_epoch}``.

    ``source`` is one of: ``"lcu"`` / ``"match_db"`` / ``"user_note"`` /
    ``"cache"`` / ``"none"``. Never raises.
    """
    now = time.time()
    if not force_fresh:
        if _CACHE["ts"] and (now - _CACHE["ts"]) < CACHE_TTL_SEC:
            return {
                "champion": _CACHE["champion"],
                "source": _CACHE["source"] + " (cache)" if _CACHE["champion"] else "none",
                "fetched_at_epoch": _CACHE["ts"],
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

    _CACHE.update({"champion": champion, "source": source, "ts": now})
    return {
        "champion": champion,
        "source": source,
        "fetched_at_epoch": now,
    }
