# arch: deterministic fed-enemy threat / survive counter-hint source | section=core.build_planner | frozen=no
"""Deterministic fed-enemy threat -> C3 SURVIVE counter-hint source.

PURPOSE
    Decide whether any single enemy is provably FED - a combat lead AND an
    estimated-economy lead over the active player - with NO LLM / network /
    engine. Feeds the situational ``EnemyProfile.fed`` bool (the C3 fed
    counter-build hint fires on it, ``situational.py:407``), plus the fed
    threat's damage AXIS so the route can direct the hint (armor vs a fed
    AD threat, MR vs a fed AP threat). A sibling of core/cc_threat.py /
    core/heal_threat.py; lives under core.build_planner because the fed
    read exists solely for the build-plan hint path. Spec:
    docs/specs/2026-07-17-ds-c3-fed-counter-hint-design.md (formula
    adopted from docs/specs/leap/LEAP-08-c3-fed-criterion.md).

WHY correct-by-construction (not a prediction)
    Every input is a hard public fact from the Live Client scoreboard:
    per-player scores (kills/deaths/assists), level, and owned items
    (game_reader/snapshot_normalizer.py:300-304 reads the same fields).
    Enemy GOLD is activePlayer-only over the API, so the economy lead is
    ESTIMATED from owned-item gold value + level - the one honest economy
    signal (client precedent: web/js/lib/item_value.js). Missing or junk
    data reads as 0/0 + level 0, which can never clear the cuts - absent
    data never fires a wrong chip.

THE FED FORMULA (LEAP-08, both cuts must hold - conservative AND)
    fed(X) := (kills(X) - deaths(X)) >= KDA_LEAD_CUT
              AND est_gold(X) - est_gold(me) >= GOLD_LEAD_CUT
    est_gold(p) = sum(item gold.total over owned ids) + LEVEL_GOLD * level

    Assists are excluded from the combat gate so a high-assist support
    does not read as a fed carry. The active player is the economy
    baseline because the chip serves MY itemization decision and my
    items + level are already in every build-plan POST (role-agnostic -
    no positions API exists).

DAMAGE AXIS (existing facts only)
    DDragon info.attack vs info.magic via defensive_picks._load_champ_info
    (the index compute_threat_profile classifies with; cross-module
    private-helper import precedent: situational.py:39), overlaid with
    champion_info_overrides.merged_info (the shipped fix for the zeroed
    Seraphine/Akshan/Rell/Vex/Qiyana blocks). Strict inequality picks
    "ad"/"ap"; tie or unknown -> "" and the hint keeps its generic
    direction - under-inclusion never mis-directs.

FAIL-SOFT
    Any bad / missing / non-list input -> None / False / 0.0, never raises.
    s144 true-audit: a junk value now drops only ITSELF (one id, one level,
    one enemy row), never the whole read. Item ids share
    core.heal_threat._id_strs (int or ASCII digits, 1..10**7-1); a count is
    an int / integral float / ASCII digit string in 0.._MAX_COUNT; a level
    outside 1.._MAX_LEVEL is a missing level (0); a present-but-junk kills
    or deaths skips the row (an ABSENT one still reads 0); a non-str, blank
    or over-long champion is never named fed.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

from core.failed_load_gate import FailedLoadGate
from core.heal_threat import _id_strs

_log = logging.getLogger("rc.fed_threat")

# Net kills-minus-deaths that reads as snowballing (3-0 / 5-2 / 7-4).
KDA_LEAD_CUT = 3
# Estimated-gold lead over the active player - well above owned-item noise.
GOLD_LEAD_CUT = 2000.0
# Gold-equivalent per champion level: folds a level lead into the single
# economy estimate (a modest secondary term dominated by items).
LEVEL_GOLD = 130.0
# Plausibility bounds (s144 true-audit). A level past the game's cap (18 on
# every current queue; 30 leaves headroom) is junk - a level of 10**6 used to
# forge a 130M-gold economy lead. A scoreboard count past 10**6 is junk, the
# same bound dashboard/_liveclient._count uses.
_MAX_LEVEL = 30
_MAX_COUNT = 10 ** 6
_COUNT_MAX_DIGITS = 7
# A real champion name is under 20 chars (heal_threat uses the same 64 cap).
_MAX_NAME_LEN = 64

_ITEMS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "meta" / "ddragon_items.json"
_GOLD_MAP: dict | None = None
# RM-443: a failed load is NOT cached - retried after the gate's backoff and
# warned once per failure streak (core/failed_load_gate.py).
_GOLD_MAP_GATE = FailedLoadGate()


def _load_gold_map() -> dict:
    """Read ddragon_items.json ONCE -> {id_str: float(gold.total)}.

    The same catalog file situational.py loads (706/706 entries carry
    gold.total, probed at author time). Any load failure degrades to an
    empty map, so every estimate is level-only and the economy gate simply
    never clears (graceful - the chip stays dark rather than guessing)."""
    global _GOLD_MAP
    if _GOLD_MAP is not None:
        return _GOLD_MAP
    if not _GOLD_MAP_GATE.should_attempt():
        return {}
    out: dict = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for item_id, entry in data.items():
            try:
                total = (entry.get("gold") or {}).get("total") or 0.0
                if isinstance(total, bool):
                    continue
                price = float(total)
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
            # A NaN price made every lead compare False, an inf one made every
            # enemy fed, a negative one a discount: none is a price.
            if math.isfinite(price) and price >= 0.0:
                out[str(item_id)] = price
    except Exception as exc:  # noqa: BLE001 - any load failure -> empty map
        if _GOLD_MAP_GATE.record_failure():
            _log.warning("fed_threat gold map load failed: %s", exc)
        return {}
    _GOLD_MAP_GATE.record_success()
    _GOLD_MAP = out
    return out


def _count(value: object) -> Optional[int]:
    """A scoreboard count in 0.._MAX_COUNT, or None for a junk value.

    Accepts an int (never a bool), an integral finite float, or a plain
    ASCII digit string. s144 true-audit: ``int()`` raised OverflowError on
    inf, truncated 3.9 to 3, and read "+5" / "1_0" / Arabic-Indic digits /
    a negative count as numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not (math.isfinite(value) and value.is_integer()):
            return None
        n = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()
                and len(text) <= _COUNT_MAX_DIGITS):
            return None
        n = int(text)
    else:
        return None
    return n if 0 <= n <= _MAX_COUNT else None


def _as_int(value: object) -> int:
    """A count, with junk and missing -> 0 (fail-soft)."""
    n = _count(value)
    return 0 if n is None else n


def _level(value: object) -> int:
    """A champion level in 1.._MAX_LEVEL, else 0 (a missing level - an
    honest undercount, never a guessed or forged one)."""
    n = _as_int(value)
    return n if 1 <= n <= _MAX_LEVEL else 0


def _champ_name(value: object) -> str:
    """The stripped champion name, or "" for a non-str / blank / over-long
    one (such an entry is never named fed)."""
    if not isinstance(value, str):
        return ""
    name = value.strip()
    return name if len(name) <= _MAX_NAME_LEN else ""


def estimate_player_gold(item_ids, level) -> float:
    """Estimated on-board gold: sum(gold.total over owned ids) + LEVEL_GOLD *
    level. An unknown or junk id contributes 0 (truthful undercount), and so
    does a junk level. Fail-soft 0.0 on bad / missing input; never raises."""
    gold_map = _load_gold_map()
    total = sum(gold_map.get(i, 0.0) for i in _id_strs(item_ids))
    return total + LEVEL_GOLD * _level(level)


def _champ_axis(name: object) -> str:
    """The champion's damage axis: "ad", "ap", or "" when unknown / tied.

    DDragon info.attack vs info.magic through the champion_info_overrides
    overlay (restores the zeroed Seraphine/Akshan/Rell/Vex/Qiyana blocks).
    Fail-soft "" - the hint then keeps its generic resist direction."""
    if not isinstance(name, str) or not name.strip():
        return ""
    try:
        from core.champion_info_overrides import merged_info
        from core.defensive_picks import _load_champ_info

        idx = _load_champ_info()
        info = idx.get(name) or idx.get(name.replace("'", "")) or {}
        merged = merged_info(name.strip(), info)
        attack = _as_int(merged.get("attack"))
        magic = _as_int(merged.get("magic"))
        if attack > magic:
            return "ad"
        if magic > attack:
            return "ap"
        return ""
    except Exception as exc:  # noqa: BLE001 - unknown axis, never a raise
        _log.debug("fed_threat axis: %s", exc)
        return ""


def assess_fed_threat(enemies, enemy_items_by_player, enemy_scores,
                      enemy_levels, my_item_ids, my_level) -> Optional[dict]:
    """The TOP fed enemy as {champion, kills, deaths, axis}, or None.

    All enemy lists are index-aligned with ``enemies``; a missing / short
    row reads kills=deaths=0, level 0, items [] - absent data can never
    clear both cuts, so it never fires. The top fed enemy is picked by net
    kills then kills (the threat worth naming). Fail-soft None on any junk
    input; never raises."""
    try:
        if not isinstance(enemies, list) or not enemies:
            return None
        items_rows = enemy_items_by_player if isinstance(enemy_items_by_player, list) else []
        score_rows = enemy_scores if isinstance(enemy_scores, list) else []
        level_rows = enemy_levels if isinstance(enemy_levels, list) else []
        my_gold = estimate_player_gold(my_item_ids, my_level)

        best: Optional[dict] = None
        best_key = None
        for i, champ in enumerate(enemies):
            name = _champ_name(champ)
            if not name:
                continue
            row = score_rows[i] if i < len(score_rows) and isinstance(score_rows[i], dict) else {}
            # Absent -> 0 (unchanged); present but junk -> the row is unread.
            raw_kills, raw_deaths = row.get("kills"), row.get("deaths")
            kills = 0 if raw_kills is None else _count(raw_kills)
            deaths = 0 if raw_deaths is None else _count(raw_deaths)
            if kills is None or deaths is None:
                continue
            if kills - deaths < KDA_LEAD_CUT:
                continue
            items = items_rows[i] if i < len(items_rows) else []
            level = level_rows[i] if i < len(level_rows) else 0
            if estimate_player_gold(items, level) - my_gold < GOLD_LEAD_CUT:
                continue
            key = (kills - deaths, kills)
            if best_key is None or key > best_key:
                best_key = key
                best = {
                    "champion": name,
                    "kills": kills,
                    "deaths": deaths,
                    "axis": _champ_axis(name),
                }
        return best
    except Exception as exc:  # noqa: BLE001 - fed is advisory, never a raise
        _log.debug("fed_threat assess: %s", exc)
        return None


def compute_fed(enemies, enemy_items_by_player, enemy_scores, enemy_levels,
                my_item_ids, my_level) -> bool:
    """True when ANY enemy clears both fed cuts - the bool the situational
    ``EnemyProfile.fed`` consumes (the C3 hint fires on it)."""
    return assess_fed_threat(enemies, enemy_items_by_player, enemy_scores,
                             enemy_levels, my_item_ids, my_level) is not None
