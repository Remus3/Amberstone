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
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.fed_threat")

# Net kills-minus-deaths that reads as snowballing (3-0 / 5-2 / 7-4).
KDA_LEAD_CUT = 3
# Estimated-gold lead over the active player - well above owned-item noise.
GOLD_LEAD_CUT = 2000.0
# Gold-equivalent per champion level: folds a level lead into the single
# economy estimate (a modest secondary term dominated by items).
LEVEL_GOLD = 130.0

_ITEMS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "meta" / "ddragon_items.json"
_GOLD_MAP: dict | None = None


def _load_gold_map() -> dict:
    """Read ddragon_items.json ONCE -> {id_str: float(gold.total)}.

    The same catalog file situational.py loads (706/706 entries carry
    gold.total, probed at author time). Any load failure degrades to an
    empty map, so every estimate is level-only and the economy gate simply
    never clears (graceful - the chip stays dark rather than guessing)."""
    global _GOLD_MAP
    if _GOLD_MAP is not None:
        return _GOLD_MAP
    out: dict = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for item_id, entry in data.items():
            try:
                out[str(item_id)] = float((entry.get("gold") or {}).get("total") or 0.0)
            except (TypeError, ValueError, AttributeError):
                continue
    except Exception as exc:  # noqa: BLE001 - any load failure -> empty map
        _log.debug("fed_threat gold map: %s", exc)
    _GOLD_MAP = out
    return out


def _as_int(value: object) -> int:
    """Coerce a scoreboard number to int; junk -> 0 (fail-soft)."""
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _id_strs(ids: object) -> list[str]:
    """Coerce an item-id list to string ids; bad input -> [] (the Live
    Client itemID can arrive int or str - mirrors heal_threat._id_strs)."""
    if not isinstance(ids, list):
        return []
    out: list[str] = []
    for i in ids:
        if isinstance(i, bool) or i is None:
            continue
        if isinstance(i, (int, float)):
            out.append(str(int(i)))
        elif isinstance(i, str) and i.strip():
            out.append(i.strip())
    return out


def estimate_player_gold(item_ids, level) -> float:
    """Estimated on-board gold: sum(gold.total over owned ids) + LEVEL_GOLD *
    level. An unknown id contributes 0 (truthful undercount). Fail-soft 0.0
    on bad / missing input."""
    gold_map = _load_gold_map()
    total = sum(gold_map.get(i, 0.0) for i in _id_strs(item_ids))
    return total + LEVEL_GOLD * max(0, _as_int(level))


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
            row = score_rows[i] if i < len(score_rows) and isinstance(score_rows[i], dict) else {}
            kills = _as_int(row.get("kills"))
            deaths = _as_int(row.get("deaths"))
            if kills - deaths < KDA_LEAD_CUT:
                continue
            items = items_rows[i] if i < len(items_rows) else []
            level = level_rows[i] if i < len(level_rows) else 0
            if estimate_player_gold(items, level) - my_gold < GOLD_LEAD_CUT:
                continue
            key = (kills - deaths, kills)
            if best_key is None or key > best_key:
                best_key = key
                name = champ.strip() if isinstance(champ, str) else str(champ)
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
