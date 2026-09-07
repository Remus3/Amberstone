"""
lcu/lcu_rune_writer.py - Champion select rune auto-writer for Amberstone.

Polls LCU champ select session every ~1s (RC2 P6.2; env RC_RUNEWRITER_POLL_SEC).
When a champion is selected (intent OR locked), loads the recommended
rune page from rune_recommendations_{aram|sr}.json and writes it to
the LCU immediately - replacing the Overlay App E workflow.

Manages only pages prefixed "RC: " - never touches user-created pages.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.lcu.runes")

_APP_DIR = Path(__file__).parent.parent

# -- Rune ID constants (from ddragon_runes.json) ----------------------------

# Tree IDs
_TREES = {
    "Precision":   8000,
    "Domination":  8100,
    "Sorcery":     8200,
    "Inspiration": 8300,
    "Resolve":     8400,
}

# Keystone -> ID
_KEYSTONES = {
    # Precision
    "Press the Attack": 8005,
    "Lethal Tempo":     8008,
    "Fleet Footwork":   8021,
    "Conqueror":        8010,
    # Domination
    "Electrocute":      8112,
    "Dark Harvest":     8128,
    "Hail of Blades":   9923,
    # Sorcery
    "Summon Aery":      8214,
    "Arcane Comet":     8229,
    "Phase Rush":       8230,
    # Resolve
    "Grasp of the Undying": 8437,
    "Aftershock":       8439,
    "Guardian":         8465,
    # Inspiration
    "Glacial Augment":  8351,
    "Unsealed Spellbook": 8360,
    "First Strike":     8369,
}

# Primary tree rows 1-3 defaults (ADC-optimised)
# These are the 3 non-keystone row picks for the PRIMARY tree.
# Layout: [row1_id, row2_id, row3_id]
_PRIMARY_ROWS: dict[str, dict[str, list[int]]] = {
    "Precision": {
        # Row1: Absorb Life(9101) / Triumph(9111) / Presence of Mind(8009)
        # Row2: Legend:Alacrity(9104) / Legend:Haste(9105) / Legend:Bloodline(9103)
        # Row3: Coup de Grace(8014) / Cut Down(8017) / Last Stand(8299)
        "_default":       [9111, 9104, 8014],   # Triumph + Alacrity + CdG
        "Conqueror":      [9111, 9104, 8014],   # Conqueror -> Triumph+Alacrity+CdG
        "Fleet Footwork": [8009, 9104, 8014],   # FoF -> PoM+Alacrity+CdG
    },
    "Domination": {
        # Row1: Cheap Shot(8126) / Taste of Blood(8139) / Sudden Impact(8143)
        # Row2: Sixth Sense(8137) / Grisly Mementos(8140) / Deep Ward(8141)
        # Row3: Treasure Hunter(8135) / Relentless Hunter(8105) / Ultimate Hunter(8106)
        "_default": [8139, 8137, 8135],  # Taste of Blood + Sixth Sense + Treasure Hunter
    },
    "Sorcery": {
        # Row1: Axiom Arcanist(8224) / Manaflow Band(8226) / Nimbus Cloak(8275)
        # Row2: Transcendence(8210) / Celerity(8234) / Absolute Focus(8233)
        # Row3: Scorch(8237) / Waterwalking(8232) / Gathering Storm(8236)
        "_default": [8226, 8210, 8236],  # Manaflow + Transcendence + Gathering Storm
    },
    "Resolve": {
        # Row1: Demolish(8446) / Font of Life(8463) / Shield Bash(8401)
        # Row2: Conditioning(8429) / Second Wind(8444) / Bone Plating(8473)
        # Row3: Overgrowth(8451) / Revitalize(8453) / Unflinching(8242)
        "_default": [8401, 8473, 8453],  # Shield Bash + Bone Plating + Revitalize
    },
    "Inspiration": {
        # Row1: Hextech Flashtraption(8306) / Magical Footwear(8304) / Cash Back(8321)
        # Row2: Triple Tonic(8313) / Time Warp Tonic(8352) / Biscuit Delivery(8345)
        # Row3: Cosmic Insight(8347) / Approach Velocity(8410) / Jack Of All Trades(8316)
        "_default": [8304, 8345, 8347],  # Magical Footwear + Biscuit + Cosmic Insight
    },
}

# Secondary tree - best 2 picks for each tree (ADC-optimised)
# Layout: [pick1_id, pick2_id]
_SECONDARY_PICKS: dict[str, list[int]] = {
    "Precision":   [9111, 9104],   # Triumph + Legend: Alacrity
    "Domination":  [8143, 8135],   # Sudden Impact + Treasure Hunter
    "Sorcery":     [8226, 8236],   # Manaflow Band + Gathering Storm
    "Resolve":     [8473, 8453],   # Bone Plating + Revitalize
    "Inspiration": [8304, 8347],   # Magical Footwear + Cosmic Insight
}

# Stat shards: [row1, row2, row3]
_SHARDS_SR   = [5005, 5008, 5001]  # Attack Speed | Adaptive Force | Health Scaling
_SHARDS_ARAM = [5005, 5008, 5001]  # Attack Speed | Adaptive Force | Health Scaling

# Lazy {rune display-name: perk id} map, built from ddragon_runes.json the
# first time it's needed. Lets a user-curated build override the hardcoded
# minor-rune defaults below (item 212) without re-listing every id here.
_PERK_BY_NAME: Optional[dict[str, int]] = None


def _perk_by_name() -> dict[str, int]:
    """Return {rune display-name: id} parsed from data/meta/ddragon_runes.json.

    Cached after the first read. Returns an empty dict if the file is
    missing or malformed so callers fall back to defaults rather than crash.
    """
    global _PERK_BY_NAME
    if _PERK_BY_NAME is None:
        m: dict[str, int] = {}
        try:
            p = _APP_DIR / "data" / "meta" / "ddragon_runes.json"
            for tree in json.loads(p.read_text(encoding="utf-8")):
                for slot in tree.get("slots", []):
                    for r in slot.get("runes", []):
                        nm, rid = r.get("name"), r.get("id")
                        if isinstance(nm, str) and isinstance(rid, int):
                            m[nm] = rid
        except Exception as exc:  # noqa: BLE001
            # Audit cycle 10 (P2-W1-app-B): do NOT cache the failure -
            # pre-fix a transient read error pinned an empty map for the
            # process lifetime (cache-poisoning class), silently dropping
            # every user-curated minor-rune override from then on.
            _log.debug("perk-by-name load failed: %s", exc)
            return {}
        _PERK_BY_NAME = m
    return _PERK_BY_NAME


# -- Core resolver ---------------------------------------------------------

def _substitute_colliding_secondary(primary_tree: str, secondary_tree: str) -> str:
    """Return the secondary tree name to actually USE for `primary_tree`.

    League rejects a rune page whose subStyleId equals its primaryStyleId, so a
    caller asking for the same tree twice gets a different one substituted in.
    Sole owner of that rule - `build_perk_ids` and `resolve_tree_ids` both go
    through here so the perk ids and the style ids can never disagree.
    """
    if primary_tree != secondary_tree:
        return secondary_tree
    _log.warning(
        "Primary and secondary trees are the same (%r) - using %s as secondary",
        secondary_tree, "Resolve" if primary_tree != "Resolve" else "Precision")
    return "Resolve" if primary_tree != "Resolve" else "Precision"


def resolve_tree_ids(primary_tree: str, secondary_tree: str) -> tuple[int, int]:
    """Resolve tree NAMES to the (primaryStyleId, subStyleId) pair that MATCHES
    the perk ids `build_perk_ids` returns for the same input.

    Lane 8 cycle 39. Every call site used to re-derive the sub style itself with
    a bare `_TREES.get(secondary, 0)`, which is correct only while the two names
    differ. `build_perk_ids` substitutes a colliding secondary INTERNALLY and
    could not report it, so a same-tree request produced a page carrying
    subStyleId == primaryStyleId with the substituted tree's runes sitting in
    it - malformed on two counts, and posted only after `_write_page` had
    already deleted the page it was replacing.

    Unknown names resolve to 0 on that side, preserving the `if not sub_id`
    rejection every call site already performs.
    """
    pri_id = _TREES.get(primary_tree, 0)
    if not pri_id or not _TREES.get(secondary_tree, 0):
        # Unknown on either side: no substitution to reason about, and the
        # caller's own guard rejects the pair. Report what was asked for.
        return pri_id, _TREES.get(secondary_tree, 0)
    return pri_id, _TREES[_substitute_colliding_secondary(primary_tree, secondary_tree)]


def build_perk_ids(
    keystone: str,
    primary_tree: str,
    secondary_tree: str,
    is_aram: bool = False,
    minor_primary: Optional[list[str]] = None,
    minor_secondary: Optional[list[str]] = None,
) -> Optional[list[int]]:
    """
    Resolve (keystone name, primary_tree name, secondary_tree name) -> 9-element perk_ids.
    Returns None if keystone or trees are unrecognised.

    Layout: [keystone, pri_row1, pri_row2, pri_row3, sec1, sec2, shard1, shard2, shard3]

    minor_primary / minor_secondary (item 212): optional user-chosen rune
    display-names. When the FULL set resolves (3 primary rows / 2 secondary
    picks) they override the hardcoded defaults; any miss keeps defaults so a
    malformed page is never pushed.
    """
    ks_id = _KEYSTONES.get(keystone)
    if not ks_id:
        _log.warning("Unknown keystone %r - skipping rune write", keystone)
        return None

    pri_id = _TREES.get(primary_tree)
    sec_id = _TREES.get(secondary_tree)
    if not pri_id or not sec_id:
        _log.warning("Unknown trees %r / %r", primary_tree, secondary_tree)
        return None

    # Lane 8 cycle 39: the substitution rule lives in ONE place now, so
    # resolve_tree_ids cannot drift from the perks produced here.
    secondary_tree = _substitute_colliding_secondary(primary_tree, secondary_tree)
    sec_id = _TREES[secondary_tree]

    # Primary rows: look for keystone-specific override, fall back to _default
    pri_rows_map = _PRIMARY_ROWS.get(primary_tree, {})
    pri_rows = pri_rows_map.get(keystone) or pri_rows_map.get("_default", [])
    if len(pri_rows) < 3:
        _log.warning("No primary row defaults for %r", primary_tree)
        return None

    sec_picks = _SECONDARY_PICKS.get(secondary_tree, [])
    if len(sec_picks) < 2:
        _log.warning("No secondary pick defaults for %r", secondary_tree)
        return None

    # item 212: honor user-chosen minor runes when the full set resolves.
    # Any unresolved name or wrong count keeps the defaults above so we
    # never push a malformed page.
    name_map = _perk_by_name()
    if minor_primary:
        mp = [name_map.get(n) for n in minor_primary]
        if len(mp) == 3 and all(isinstance(x, int) for x in mp):
            pri_rows = mp
    if minor_secondary:
        ms = [name_map.get(n) for n in minor_secondary]
        if len(ms) == 2 and all(isinstance(x, int) for x in ms):
            sec_picks = ms

    shards = _SHARDS_ARAM if is_aram else _SHARDS_SR

    return [ks_id, pri_rows[0], pri_rows[1], pri_rows[2],
            sec_picks[0], sec_picks[1],
            shards[0], shards[1], shards[2]]


def load_rune_rec(champion: str, mode: str) -> Optional[tuple[str, str, str]]:
    """
    Load (keystone, primary_tree, secondary_tree) from rune_recommendations_{mode}.json.
    Returns None if champion not found.
    """
    _ARAM_MODES = {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}
    fname = (
        "rune_recommendations_aram.json"
        if mode.upper() in _ARAM_MODES or "ARAM" in mode.upper()
        else "rune_recommendations_sr.json"
    )
    try:
        p = _APP_DIR / "data" / "meta_build" / fname
        if not p.exists():
            _log.warning("Rune rec file not found: %s", fname)
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        rec = data.get(champion)
        if not rec or not isinstance(rec, dict):
            _log.debug("No rune rec for %r in %s", champion, fname)
            return None
        ks  = rec.get("keystone", "")
        pri = rec.get("primary_tree", "")
        sec = rec.get("secondary_tree", "")
        if ks and pri and sec:
            return (ks, pri, sec)
        return None
    except Exception as exc:  # noqa: BLE001
        _log.debug("load_rune_rec: %s", exc)
        return None


def build_champ_id_map() -> dict[int, str]:
    """Build {champion_id_int: display_name} from ddragon_champions.json."""
    try:
        p = _APP_DIR / "data" / "meta" / "ddragon_champions.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        result: dict[int, str] = {}
        for name, info in (raw.get("data") or {}).items():
            try:
                cid = int(info.get("key", -1))
                if cid >= 0:
                    result[cid] = info.get("name", name)  # display name e.g. "Miss Fortune" not "MissFortune"
            except (ValueError, TypeError):
                pass
        _log.debug("Champion ID map: %d entries", len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        _log.warning("build_champ_id_map: %s", exc)
        return {}



# -- Summoner spell preference reader --------------------------------------

# ARAM spell IDs
_SPELL_FLASH    = 4
_SPELL_SNOWBALL = 32   # Mark (ARAM)
_SPELL_EXHAUST  = 3
_SPELL_TELEPORT = 12
_SPELL_IGNITE   = 14
_SPELL_HEAL     = 7

_SPELL_PREFS_PATH = _APP_DIR / "data" / "spell_prefs.json"

def load_spell_pair(mode: str, is_aram: bool) -> tuple[int, int]:
    """
    Load (spell1_id, spell2_id) from spell_prefs.json.
    is_aram: True for ARAM/KIWI; False for SR.
    Falls back to safe defaults if file missing or invalid.
    """
    try:
        if _SPELL_PREFS_PATH.exists():
            prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding='utf-8'))
            key   = "aram_mode" if is_aram else "sr_mode"
            pref  = prefs.get(key, "snowball" if is_aram else "teleport")
        else:
            pref = "snowball" if is_aram else "teleport"
    except Exception:  # noqa: BLE001
        pref = "snowball" if is_aram else "teleport"

    if is_aram:
        if pref == "exhaust":
            return (_SPELL_FLASH, _SPELL_EXHAUST)
        # snowball or ai or anything else -> Flash + Snowball
        return (_SPELL_FLASH, _SPELL_SNOWBALL)
    else:
        if pref == "exhaust":
            return (_SPELL_FLASH, _SPELL_EXHAUST)
        if pref == "ignite":
            return (_SPELL_FLASH, _SPELL_IGNITE)
        # teleport or ai or anything else -> Flash + Teleport
        return (_SPELL_FLASH, _SPELL_TELEPORT)


# ARAM-family mode strings the LCU lobby / champ-select reports.
_ARAM_MODE_STRINGS = frozenset(
    {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}
)


def resolve_spell_pair(champion: str, mode: str) -> tuple[int, int]:
    """Resolve the INTENDED summoner-spell pair for a champ + LCU game mode.

    CS2 (2026-06-08): the operator-facing source of truth is the same
    spell_prefs.json the RuneWriter already reads via load_spell_pair -
    sr_mode=teleport (Flash+Teleport) for SR, aram_mode=snowball
    (Flash+Snowball) for ARAM. This wrapper turns the raw LCU mode
    string into the is_aram bool load_spell_pair expects, routing
    KIWI / ARAM Mayhem to the ARAM pair, everything else to SR.

    ``champion`` is accepted for forward-compat (a future per-champ
    override could key off it) but is not used today - the pair is
    mode-driven so it stays correct for every champion.
    """
    is_aram = (mode or "").upper() in _ARAM_MODE_STRINGS or "ARAM" in (mode or "").upper()
    return load_spell_pair(mode, is_aram)


# Audit cycle 10 (P2-W1-app-B): serializes save_spell_pref writers -
# concurrent calls shared one .tmp name (cycle-9 shared-tmp race class)
# and a transient os.replace WinError 5 silently dropped the write.
# Mirrors coaches/_base_coach.safe_write (lock + bounded replace retry).
_SPELL_PREFS_LOCK = threading.Lock()


def save_spell_pref(mode_key: str, value: str) -> None:
    """Write updated spell preference to spell_prefs.json (atomic write)."""
    try:
        with _SPELL_PREFS_LOCK:
            if _SPELL_PREFS_PATH.exists():
                prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding='utf-8'))
            else:
                prefs = {}
            prefs[mode_key] = value
            tmp = _SPELL_PREFS_PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                           encoding='utf-8')
            for attempt in range(3):
                try:
                    tmp.replace(_SPELL_PREFS_PATH)
                    break
                except PermissionError:
                    # os.replace transient WinError 5 under concurrent
                    # read - retry with backoff, give up after 3.
                    if attempt == 2:
                        _log.warning("save_spell_pref: replace gave up after 3 tries")
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                    else:
                        time.sleep(0.015 * (2 ** attempt))
    # Narrowed 2026-07-19: Path.exists / read_text / write_text / Path.replace
    # raise OSError (PermissionError is retried inline above); read_text raises
    # UnicodeDecodeError and json.loads raises JSONDecodeError, both ValueError
    # subclasses; prefs[mode_key] = value raises TypeError when the file stored
    # a JSON list instead of an object, and json.dumps raises TypeError /
    # ValueError. Those are every raising statement in the try.
    except (OSError, TypeError, ValueError) as exc:
        _log.debug("save_spell_pref: %s", exc)


# -- Per-champion-per-mode spell memory (RC2 E6) ---------------------------
#
# data/spell_prefs.json gains a per-champ map alongside the existing
# aram_mode / sr_mode keys (which stay the generic fallback):
#
#   {"by_champ": {"<MODE_TAG>": {"<champion display name>": [s1, s2]}}}
#
# MODE_TAG is the collector-aligned tag ("SR" / "ARAM" / ...), so a
# remembered pair never leaks across modes. The champion key is the DDragon
# DISPLAY name (e.g. "Miss Fortune") - the same string the RuneWriter's
# _id_to_name returns and the postgame corpus stores in champion_name.

# LCU/dashboard mode string -> collector mode tag. Mirrors
# lcu.lcu_postgame_collector._MODE_MAP + dashboard.routes_adaptive_summoners.
_MODE_TAGS = {
    "CLASSIC": "SR", "SR": "SR",
    "ARAM": "ARAM", "KIWI": "ARAM", "ARAM_5V5": "ARAM", "ARAM_MAYHEM": "ARAM",
    "CHERRY": "ARENA", "ARENA": "ARENA",
    "NEXUSBLITZ": "BRAWL", "URF": "BRAWL", "BRAWL": "BRAWL",
    "TFT": "TFT",
}


def mode_tag(mode: str) -> str:
    """LCU game-mode string -> collector mode tag ('SR' default)."""
    m = (mode or "").upper()
    if m in _MODE_TAGS:
        return _MODE_TAGS[m]
    if "ARAM" in m:
        return "ARAM"
    return "SR"


def load_champ_spell_pref(champion: str, mode: str) -> Optional[tuple[int, int]]:
    """Remembered (s1, s2) for a champion+mode, or None.

    Reads spell_prefs.json["by_champ"][<mode_tag>][<champion>]. Returns None
    when the file is missing/malformed, the mode or champion has no entry, or
    the stored value is not a 2-element int list - callers then fall back to
    the WR pick / role default.
    """
    if not champion:
        return None
    try:
        if not _SPELL_PREFS_PATH.exists():
            return None
        prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding="utf-8"))
        by_champ = prefs.get("by_champ")
        if not isinstance(by_champ, dict):
            return None
        per_mode = by_champ.get(mode_tag(mode))
        if not isinstance(per_mode, dict):
            return None
        pair = per_mode.get(champion)
        if (isinstance(pair, (list, tuple)) and len(pair) == 2
                and all(isinstance(x, int) for x in pair)):
            return (int(pair[0]), int(pair[1]))
    except Exception as exc:  # noqa: BLE001
        _log.debug("load_champ_spell_pref(%s/%s): %s", champion, mode, exc)
    return None


def save_champ_spell_pref(champion: str, mode: str,
                          pair: tuple[int, int]) -> None:
    """Persist a remembered (s1, s2) for champion+mode (atomic, locked).

    Writes spell_prefs.json["by_champ"][<mode_tag>][<champion>] = [s1, s2],
    creating the nested maps as needed and preserving every other key.
    Shares _SPELL_PREFS_LOCK + the bounded replace-retry with save_spell_pref
    so concurrent writers never share a .tmp or drop a write on a transient
    WinError 5.
    """
    if not champion:
        return
    try:
        s1, s2 = int(pair[0]), int(pair[1])
    except (TypeError, ValueError, IndexError):
        return
    try:
        with _SPELL_PREFS_LOCK:
            if _SPELL_PREFS_PATH.exists():
                prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding="utf-8"))
                if not isinstance(prefs, dict):
                    prefs = {}
            else:
                prefs = {}
            by_champ = prefs.get("by_champ")
            if not isinstance(by_champ, dict):
                by_champ = {}
                prefs["by_champ"] = by_champ
            tag = mode_tag(mode)
            per_mode = by_champ.get(tag)
            if not isinstance(per_mode, dict):
                per_mode = {}
                by_champ[tag] = per_mode
            per_mode[champion] = [s1, s2]

            tmp = _SPELL_PREFS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            for attempt in range(3):
                try:
                    tmp.replace(_SPELL_PREFS_PATH)
                    break
                except PermissionError:
                    if attempt == 2:
                        _log.warning(
                            "save_champ_spell_pref: replace gave up after 3 tries")
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                    else:
                        time.sleep(0.015 * (2 ** attempt))
    # Narrowed 2026-07-19: same raise surface as save_spell_pref above -
    # OSError from exists/read_text/write_text/replace, ValueError from
    # UnicodeDecodeError + JSONDecodeError, TypeError/ValueError from
    # json.dumps. mode_tag (:397) is pure str/dict work and cannot raise, and
    # prefs / by_champ / per_mode are all isinstance-guarded to dict above.
    except (OSError, TypeError, ValueError) as exc:
        _log.debug("save_champ_spell_pref(%s/%s): %s", champion, mode, exc)


# ==============================================================================
# RuneWriter
# ==============================================================================

# Lane 8 cycle 39. RC_RUNEWRITER_POLL_SEC used to be read straight into the
# class body as `float(os.environ.get(...))`, unvalidated. Two measured arms:
#
#   "0" / "-1"  -> POLL_INTERVAL 0.0, and _stop_event.wait(0.0) returns
#                  instantly (2000 waits in 0.0011s). The poll loop became an
#                  unbounded spin issuing LCU HTTP requests as fast as the
#                  League client could answer them.
#   "abc"       -> ValueError at MODULE IMPORT. main.py:254 catches that as
#                  "RuneWriter init failed" (rune auto-apply silently off), and
#                  the same failure breaks every other importer of this module:
#                  coaches/rune_pages.py, coaches/loadout_resolver.py,
#                  dashboard/routes_loadout.py, dashboard/routes_sr_draft.py.
#
# A FLOOR, not a ceiling: a deliberately slow poll is the operator's business,
# an unbounded spin against the game client is not. 0.1s is 10x the shipped
# 1.0s rate and still bounded, so a deliberate fast setting still works.
_MIN_POLL_INTERVAL = 0.1
_DEFAULT_POLL_INTERVAL = 1.0


def _poll_interval_from_env(
    raw: Optional[str] = None,
    *,
    _sentinel: object = object(),
) -> float:
    """Parse RC_RUNEWRITER_POLL_SEC into a usable poll interval.

    Never raises: an unparseable, non-finite, zero or negative value falls back
    to the 1.0s default, and anything below the floor is raised to it.
    """
    if raw is None:
        raw = os.environ.get("RC_RUNEWRITER_POLL_SEC")
    if raw is None or str(raw).strip() == "":
        return _DEFAULT_POLL_INTERVAL
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _log.warning(
            "RC_RUNEWRITER_POLL_SEC=%r is not a number - using %.1fs",
            raw, _DEFAULT_POLL_INTERVAL)
        return _DEFAULT_POLL_INTERVAL
    # float() accepts "nan" and "inf". nan fails EVERY comparison, so a naive
    # `if value < floor` check would pass it straight through into wait().
    if not math.isfinite(value):
        _log.warning(
            "RC_RUNEWRITER_POLL_SEC=%r is not finite - using %.1fs",
            raw, _DEFAULT_POLL_INTERVAL)
        return _DEFAULT_POLL_INTERVAL
    if value < _MIN_POLL_INTERVAL:
        _log.warning(
            "RC_RUNEWRITER_POLL_SEC=%r is below the %.1fs floor - clamping "
            "(a zero or negative interval spins the LCU)", raw,
            _MIN_POLL_INTERVAL)
        return _MIN_POLL_INTERVAL
    return value


class RuneWriter:
    """
    Background thread that monitors champion select and auto-writes
    the RC-recommended rune page to the LCU client.

    Replaces Overlay App E / Moba rune auto-apply.
    Only manages pages with the prefix "RC: " - never touches other pages.
    """

    PAGE_PREFIX = "RC: "
    # RC2 P6.2: tightened 2.0 -> 1.0s for faster rune/spell auto-apply across
    # ALL modes (slowest champ-select cadence per the IO timing map). Port-safe:
    # a single loop adds ~0.5 calls/s to the lockfile port. Env-tunable.
    POLL_INTERVAL = _poll_interval_from_env()
    MAX_RETRIES   = 3     # attempts to write rune page on failure

    def __init__(self, lcu_client) -> None:
        self._lcu = lcu_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None
        self._champ_id_map: dict[int, str] = {}
        self._last_applied_champion: str = ""  # champion we last wrote runes for
        self._last_applied_mode: str = ""
        self._in_champ_select = False
        # RC2 E6 - spell auto-push state, mirrors the rune idempotency above.
        # Spells are pushed ONCE per (champion, mode) lock; after that a live
        # pair that differs from _spell_pushed_pair is treated as an operator
        # MANUAL change - we stop overwriting it and remember it.
        self._spell_pushed_champion: str = ""
        self._spell_pushed_mode: str = ""
        self._spell_pushed_pair: Optional[tuple[int, int]] = None
        self._spell_manual_override = False
        # RC2 - mid-pick (pre-lock hover) spell state, mirroring the post-lock
        # pair above. The MID-PICK branch of _sync_spells used to re-push the
        # generic mode default (Flash+Teleport for SR, role-BLIND) every ~1s
        # poll, reverting the operator's manual ADC spells during the long
        # ranked-draft hover window. These two vars give that branch the same
        # push-once + respect-manual-change behavior as the post-lock branch.
        self._midpick_pushed_pair: Optional[tuple[int, int]] = None
        self._midpick_manual_override = False
        # RC2 E12-L2 - lobby gameMode is immutable mid-champ-select, so the
        # first successful read per session is authoritative. Memoize it to
        # stop one GET /lol-lobby/v2/lobby per poll tick. Cleared on champ-
        # select exit / champ change via _reset_spell_state. Port-safe: this
        # strictly REDUCES LCU GETs - it never adds a loop or speeds a poll.
        self._cached_lobby_mode: Optional[str] = None

    def start(self) -> None:
        self._champ_id_map = build_champ_id_map()
        self._stop_event.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:  # noqa: BLE001
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._run_async())
            _log.info("RuneWriter started (%d champion IDs loaded, async)", len(self._champ_id_map))
        else:
            self._thread = threading.Thread(
                target=self._run, name="RuneWriter", daemon=True
            )
            self._thread.start()
            _log.info("RuneWriter started (%d champion IDs loaded, thread)", len(self._champ_id_map))

    def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass  # noqa: BLE001
            self._task = None
        _log.info("RuneWriter stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll()
            except Exception as exc:  # noqa: BLE001
                _log.debug("RuneWriter poll error: %s", exc)
            self._stop_event.wait(self.POLL_INTERVAL)

    async def _run_async(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._poll)
            except asyncio.CancelledError:
                return
            except BaseException as exc:  # noqa: BLE001
                # Layer-2: a BaseException escape (not just Exception) must not
                # kill the poll loop - the 8d2b4e2b caveat ("if the RuneWriter
                # poll loop itself died, _poll never runs"). _poll's own
                # self-heal then re-runs next iteration.
                _log.debug("RuneWriter poll error: %s", exc)
            try:
                await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                return

    def _poll(self) -> None:
        # Self-heal the shared LcuClient off a dead pre-restart port BEFORE
        # reading champ select. Mirrors the frozen _auto_accept_tick pattern
        # (lcu/lcu_client.py:224-226). WHY: after a mid-session League client
        # restart the sibling spawn_task auto-accept coroutine was observed to
        # stop ticking (2026-07-04, pid 6440); that tick is what normally
        # refreshes/reconnects the ONE shared _lcu, so once it went silent the
        # client stayed pinned to the dead port and get_champ_select() returned
        # None on every poll -> no rune push. Doing it here makes the writer
        # independent of the sibling loop. Both methods are mtime-guarded /
        # idempotent (cheap to call every poll). getattr-guarded so lean test
        # fakes without these methods stay green; fail-soft so a heal error
        # never kills the poll.
        try:
            refresh = getattr(self._lcu, "_refresh_conn_if_changed", None)
            if callable(refresh):
                refresh()
            if not getattr(self._lcu, "_port", None):
                connect = getattr(self._lcu, "connect", None)
                if callable(connect):
                    connect()
        except Exception as exc:  # noqa: BLE001
            _log.debug("RuneWriter: conn self-heal: %s", exc)

        session = self._lcu.get_champ_select()

        if not session or not isinstance(session, dict):
            # Not in champ select
            if self._in_champ_select:
                _log.info("RuneWriter: champ select ended - re-armed for next pick")
                self._in_champ_select = False
                self._last_applied_champion = ""
                self._last_applied_mode = ""
                self._reset_spell_state()
            return

        # INFO on the enter transition so the game-1-only silence bug
        # (reference_runewriter_dies_after_game1) is diagnosable from the day
        # log: the re-arm above always clears _last_applied, so if a LATER
        # champ-select produces no "champ select entered" line, get_champ_select()
        # never returned a session for it (the writer's LCU view went stale) -
        # NOT a re-arm failure. If the line IS present but no "applying runes"
        # follows, the gap is in _detect_my_champion instead.
        if not self._in_champ_select:
            _log.info("RuneWriter: champ select entered")
        self._in_champ_select = True

        # Get game mode from lobby
        mode = self._detect_game_mode()

        # CS2 (2026-06-08): self-correct summoner spells on EVERY poll, before
        # the champion-detected early-return below. The client randomises the
        # spell defaults (Flash+Heal / Flash+Teleport) on champ-select entry;
        # correcting only once (the old side-effect of a successful rune write)
        # left the wrong pair stuck if the rune POST failed (3-page account
        # cap) or the client re-randomised after RC's single push. _sync_spells
        # is idempotent - it PATCHes only when the live pair differs - so
        # running it every 2s costs nothing once the spells are right.
        self._sync_spells(session, mode)

        # Find my champion (intent or locked)
        champion_name = self._detect_my_champion(session)
        if not champion_name:
            return  # still picking, nothing to apply yet

        # Only re-apply if champion or mode changed
        if (champion_name == self._last_applied_champion and
                mode == self._last_applied_mode):
            return

        _log.info("RuneWriter: champion=%s mode=%s - applying runes", champion_name, mode)
        success = self._apply_runes(champion_name, mode)
        if success:
            self._last_applied_champion = champion_name
            self._last_applied_mode = mode
        else:
            _log.warning("RuneWriter: rune write failed for %s/%s", champion_name, mode)

    def _reset_spell_state(self) -> None:
        """Clear per-lock spell-push state (champ-select exit / champ change)."""
        self._spell_pushed_champion = ""
        self._spell_pushed_mode = ""
        self._spell_pushed_pair = None
        self._spell_manual_override = False
        self._midpick_pushed_pair = None
        self._midpick_manual_override = False
        # RC2 E12-L2 - drop the memoized lobby mode so the next session
        # re-reads the live lobby (mode can differ across champ-selects).
        self._cached_lobby_mode = None

    def _wr_spell_pair(self, champion: str, mode: str) -> Optional[tuple[int, int]]:
        """Highest-win-rate spell pair for champion+mode from the postgame
        corpus, or None.

        Thin, fail-soft adapter over
        dashboard.routes_adaptive_summoners.best_wr_spell_pair, which reads
        data/postgame_stats.db read-only. Any import / DB / query failure (or
        an empty corpus) returns None so the caller falls back to the role
        default. Overridable in tests.
        """
        if not champion:
            return None
        try:
            from dashboard.routes_adaptive_summoners import (
                _postgame_db_path, best_wr_spell_pair,
            )
            db = _postgame_db_path()
            if not db.exists():
                return None
            import sqlite3
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3.0)
            try:
                return best_wr_spell_pair(conn, champion, mode)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            _log.debug("RuneWriter: _wr_spell_pair(%s/%s): %s",
                       champion, mode, exc)
            return None

    def _resolve_intended_pair(self, champion: str, mode: str) -> tuple[int, int]:
        """Pick the spell pair to push on a fresh (champion, mode) lock.

        Priority (RC2 E6):
          1. REMEMBERED pair for this champ+mode (spell_prefs.json by_champ).
          2. HIGHEST-WR pair for this champ+mode from the postgame corpus.
          3. Role-centric default (spells_for_role on the assignedPosition),
             with the generic resolve_spell_pair as a final mode-level
             fallback when the role is unknown.

        ``champion`` may be "" (mid-pick, no lock) - then steps 1-2 no-op and
        we return the mode/role default.
        """
        remembered = load_champ_spell_pref(champion, mode)
        if remembered is not None:
            return remembered
        wr = self._wr_spell_pair(champion, mode)
        if wr is not None:
            return wr
        return resolve_spell_pair(champion, mode)

    def _sync_spells(self, session: dict, mode: str) -> bool:
        """RC2 E6: push the intended spell pair ONCE per champion lock, then
        respect a manual change instead of flipping it back.

        The pre-E6 code (CS2) re-resolved the generic mode default and PATCHed
        whenever the live pair differed - on every 1.0s poll. That reverted an
        operator's manual spell change within ~1s (the operator-reported
        flip-back). E6 mirrors the rune _last_applied idempotency:

          * On a NEW (champion, mode) lock: resolve the intended pair
            (remembered > WR > role default), PATCH it once, and record it.
          * On a later poll of the SAME lock: if the live pair equals what RC
            pushed, do nothing. If it DIFFERS, the operator changed it by hand
            - stop overwriting AND remember that pair for champ+mode.

        Before a champion is locked (champion == "") the generic mode default
        is still self-corrected every poll (preserves the CS2 mid-pick
        behavior) but is NOT recorded as a preference.

        Fail-soft: returns False (no write, no raise) when the session is
        missing, my cell can't be found, or an LCU call errors.
        """
        if not session or not isinstance(session, dict):
            return False
        try:
            my_cell = session.get("localPlayerCellId", -1)
            my_pick = None
            for player in session.get("myTeam", []) or []:
                if isinstance(player, dict) and player.get("cellId") == my_cell:
                    my_pick = player
                    break
            if my_pick is None:
                return False  # my cell not in the session yet - nothing to do

            try:
                cur = (int(my_pick.get("spell1Id", 0) or 0),
                       int(my_pick.get("spell2Id", 0) or 0))
            except (TypeError, ValueError):
                cur = (0, 0)

            champion = self._detect_my_champion(session)

            role = my_pick.get("assignedPosition") or ""

            # --- mid-pick (no champion locked): role-aware self-correct that
            # respects a manual change, mirroring the post-lock branch below.
            # Previously this pushed the GENERIC mode default (role-BLIND
            # Flash+Teleport for SR) on EVERY ~1s poll, reverting the
            # operator's manual ADC spells throughout the ranked-draft hover
            # window. Now: resolve a role-aware pair, push it ONCE, then stop
            # if the live pair drifts (operator changed it). No champ key
            # exists yet, so we do NOT record a per-champ preference here.
            if not champion:
                try:
                    from lcu.lcu_pregame import spells_for_role
                    want = spells_for_role(role) if role else resolve_spell_pair("", mode)
                except Exception:  # noqa: BLE001
                    want = resolve_spell_pair("", mode)
                if self._midpick_manual_override:
                    return True  # operator owns the spells now - never re-push
                if (self._midpick_pushed_pair is not None
                        and cur == self._midpick_pushed_pair):
                    return True  # still our pair - nothing to do
                if (self._midpick_pushed_pair is not None
                        and cur != (0, 0)):
                    # Live pair drifted from what RC pushed -> operator changed
                    # it by hand. Stop overwriting (no champ key to remember).
                    self._midpick_manual_override = True
                    return True
                ok = bool(self._lcu.set_summoner_spells(
                    want[0], want[1], current_pair=cur))
                self._midpick_pushed_pair = (int(want[0]), int(want[1]))
                return ok

            # --- NEW (champion, mode) lock: push the intended pair ONCE ---
            if (champion != self._spell_pushed_champion
                    or mode != self._spell_pushed_mode):
                self._reset_spell_state()
                want = self._resolve_intended_pair_for(champion, mode, role)
                ok = bool(self._lcu.set_summoner_spells(
                    want[0], want[1], current_pair=cur))
                # Record what we intended regardless of whether the PATCH was
                # needed (cur may already equal want) so the next poll won't
                # mistake the already-correct pair for a manual change.
                self._spell_pushed_champion = champion
                self._spell_pushed_mode = mode
                self._spell_pushed_pair = (int(want[0]), int(want[1]))
                self._spell_manual_override = False
                return ok

            # --- SAME lock, already pushed once ---
            if self._spell_manual_override:
                return True  # operator owns the spells now - never re-push

            if self._spell_pushed_pair is not None and cur == self._spell_pushed_pair:
                return True  # still our pair - nothing to do, no re-push

            if self._spell_pushed_pair is not None and cur != (0, 0):
                # Live pair drifted from what RC pushed -> operator changed it
                # by hand. Stop overwriting AND remember it for next time.
                self._spell_manual_override = True
                save_champ_spell_pref(champion, mode, cur)
                _log.info(
                    "RuneWriter: manual spell change %s detected for %s/%s "
                    "- remembered, will not re-push", cur, champion, mode)
                return True

            return True
        except Exception as exc:  # noqa: BLE001
            _log.debug("RuneWriter: _sync_spells: %s", exc)
            return False

    def _resolve_intended_pair_for(
        self, champion: str, mode: str, role: str,
    ) -> tuple[int, int]:
        """Intended pair with a role-aware final fallback.

        Like _resolve_intended_pair but, when there is no remembered pair and
        no WR data, prefers the role-centric default (spells_for_role on the
        champ-select assignedPosition) over the generic mode default.
        """
        remembered = load_champ_spell_pref(champion, mode)
        if remembered is not None:
            return remembered
        wr = self._wr_spell_pair(champion, mode)
        if wr is not None:
            return wr
        try:
            from lcu.lcu_pregame import spells_for_role
            if role:
                return spells_for_role(role)
        except Exception:  # noqa: BLE001
            pass
        return resolve_spell_pair(champion, mode)

    def _detect_game_mode(self) -> str:
        """Detect current game mode from lobby config.

        RC2 E12-L2: memoized per champ-select session. The lobby gameMode is
        immutable while champ-select is open, so the first successful read is
        cached and every later tick is served from cache (no per-tick GET
        /lol-lobby/v2/lobby). _reset_spell_state invalidates the cache on
        champ-select exit / champ change. Port-safe - strictly fewer LCU GETs.
        """
        if self._cached_lobby_mode is not None:
            return self._cached_lobby_mode
        try:
            lobby = self._lcu._request("GET", "/lol-lobby/v2/lobby")
            if lobby and isinstance(lobby, dict):
                gc = lobby.get("gameConfig", {})
                self._cached_lobby_mode = gc.get("gameMode", "CLASSIC").upper()
                return self._cached_lobby_mode
        # D-CLASS, narrowing is mechanically impossible: the callee already
        # swallows. LCUClient._request (lcu/lcu_client.py:173-183) returns None
        # on URLError / OSError / TimeoutError / JSONDecodeError /
        # UnicodeDecodeError / ValueError, and returns None on any non-2xx at
        # :160 - so no transport or JSON exception ever reaches this handler.
        # lcu/lcu_client.py is on the CLAUDE.md frozen list; do not edit it.
        except Exception:  # noqa: BLE001
            pass
        return "CLASSIC"

    def _detect_my_champion(self, session: dict) -> str:
        """
        Find my champion name from the champ select session.
        Returns champion name string (from ddragon) or "" if not yet selected.
        Prefers locked champion (championId) over intent (championPickIntent).
        """
        try:
            my_cell = session.get("localPlayerCellId", -1)
            my_team = session.get("myTeam", [])

            for player in my_team:
                if not isinstance(player, dict):
                    continue
                if player.get("cellId") != my_cell:
                    continue

                # Locked champion takes priority
                champ_id = player.get("championId", 0)
                if champ_id and champ_id > 0:
                    return self._id_to_name(champ_id)

                # Intent (hovered) champion
                intent_id = player.get("championPickIntent", 0)
                if intent_id and intent_id > 0:
                    return self._id_to_name(intent_id)

                return ""  # found my slot but no champ selected

        # Narrowed 2026-07-19: session.get raises AttributeError when a caller
        # hands in a non-dict session; iterating my_team and comparing
        # champ_id > 0 raise TypeError on a non-iterable / non-numeric shape.
        # _id_to_name (:924) cannot raise - build_champ_id_map (:249) swallows
        # everything and returns {} at :264-266. Those are every raising
        # statement in the try.
        except (AttributeError, TypeError) as exc:
            _log.debug("_detect_my_champion: %s", exc)
        return ""

    def _id_to_name(self, champ_id: int) -> str:
        """Resolve champion ID to display name."""
        name = self._champ_id_map.get(champ_id, "")
        if not name:
            _log.debug("Unknown champion ID %d - refreshing map", champ_id)
            self._champ_id_map = build_champ_id_map()
            name = self._champ_id_map.get(champ_id, "")
        return name

    def _apply_runes(self, champion: str, mode: str) -> bool:
        """
        Load rune recommendation and write page to LCU.
        Returns True on success.
        """
        is_aram = mode in ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")

        rec = load_rune_rec(champion, mode)
        if not rec:
            # Fall back to ARAM runes for ARAM modes, SR runes for others
            fallback_mode = "ARAM" if is_aram else "CLASSIC"
            _log.debug("No rune rec for %s/%s - using generic %s defaults", champion, mode, fallback_mode)
            # Use a safe default for ADC: Lethal Tempo / Precision / Domination
            rec = ("Lethal Tempo", "Precision", "Domination")

        keystone, primary_tree, secondary_tree = rec
        perk_ids = build_perk_ids(keystone, primary_tree, secondary_tree, is_aram)
        if not perk_ids:
            return False

        # Lane 8 cycle 39: resolve_tree_ids applies the SAME colliding-secondary
        # substitution build_perk_ids just applied, so the style ids always
        # describe the perks above. A bare _TREES.get here shipped a page whose
        # subStyleId equalled its primaryStyleId.
        pri_id, sec_id = resolve_tree_ids(primary_tree, secondary_tree)
        if not pri_id or not sec_id:
            _log.warning("Unknown tree IDs for %s / %s", primary_tree, secondary_tree)
            return False

        mode_tag = "ARAM" if is_aram else "SR"
        page_name = f"{self.PAGE_PREFIX}{champion} {mode_tag}"

        success = self._write_page(page_name, pri_id, sec_id, perk_ids)

        # Summoner spells are owned by _sync_spells (CS2, 2026-06-08), which
        # runs every _poll BEFORE this rune write and is self-correcting +
        # idempotent. The previous "push spells iff the rune write succeeded"
        # side-effect was the CS2 root cause: a failed rune POST (3-page
        # account cap) skipped the spell push entirely, leaving the client's
        # randomised Flash+Heal / Flash+TP default in place. No spell write
        # here anymore - it would be a redundant unconditional double-PATCH.

        return success

    def _write_page(
        self,
        name: str,
        primary_style_id: int,
        sub_style_id: int,
        selected_perk_ids: list[int],
    ) -> bool:
        """
        Delete any existing RC-managed pages, then POST the new page.
        Returns True on success.
        """
        # 1. Delete existing RC pages
        try:
            pages = self._lcu.get_all_rune_pages() or []
            for p in pages:
                if (isinstance(p, dict) and
                        p.get("isDeletable") and
                        str(p.get("name", "")).startswith(self.PAGE_PREFIX)):
                    page_id = p.get("id")
                    if page_id:
                        self._lcu._request("DELETE", f"/lol-perks/v1/pages/{page_id}")
                        _log.debug("Deleted old RC page: %s (id=%s)", p.get("name"), page_id)
        # D-CLASS, narrowing is mechanically impossible: both callees already
        # swallow. get_all_rune_pages (lcu/lcu_client.py:384) returns a list or
        # None after pure isinstance/.get work, and _request
        # (lcu/lcu_client.py:173-183) returns None on every transport and JSON
        # error plus any non-2xx at :160 - so no exception from the LCU round
        # trip ever reaches this handler. lcu/lcu_client.py is frozen; do not
        # edit it.
        except Exception as exc:  # noqa: BLE001
            _log.debug("_write_page delete step: %s", exc)

        # 2. POST new page
        payload = {
            "name":             name,
            "primaryStyleId":   primary_style_id,
            "subStyleId":       sub_style_id,
            "selectedPerkIds":  selected_perk_ids,
            "current":          True,
            "isRecommendationOverride": False,
        }

        # 2026-04-27 audit: exponential backoff (0.5s, 1s, 2s) instead of
        # flat 0.5s. Champ-select windows often have multiple LCU calls
        # in-flight; a flat retry hammers the client during the exact
        # 1.5s window when it's most likely transiently busy. Also: log
        # the final failure at WARNING so a sustained outage surfaces.
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = self._lcu._request("POST", "/lol-perks/v1/pages", data=payload)
                if result and isinstance(result, dict) and result.get("id"):
                    page_id = result["id"]
                    # 3. Set as active page
                    self._lcu._request("PUT", "/lol-perks/v1/currentpage",
                                       data={"id": page_id})
                    _log.info(
                        "RuneWriter: wrote [%s] id=%s  perks=%s",
                        name, page_id, selected_perk_ids
                    )
                    return True
                else:
                    _log.debug("POST page attempt %d failed: %s", attempt + 1, result)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                _log.debug("_write_page POST attempt %d: %s", attempt + 1, exc)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))

        _log.warning("RuneWriter: gave up after %d attempts for [%s]: %s",
                     self.MAX_RETRIES, name, last_exc)
        return False
