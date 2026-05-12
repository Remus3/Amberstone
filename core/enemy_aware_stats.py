# arch: enemy stats from liveclient items | section=core | frozen=no
"""Compute target_armor / target_mr / target_max_hp / target_bonus_hp from
live enemy itemization, so the DS engine's rankings adapt as the enemy
team buys defensive items.

Operator complaint that drove this (s171.4, 2026-05-12): "DS dps increase
items were always the same, not changing due to enemy items or a hyper
fed enemy rengar 1 shotting me before i could blind etc." The previous
DS preview path passed target_armor=0 / target_mr=0 / target_max_hp=0
through to ``rank_for()``, so every tick saw the SAME generic enemy
profile regardless of what the enemy team actually owned.

Pipeline:
    liveclient relay (Game-PC :2999 → Legion :8889/latest-liveclient)
      → allPlayers[i].items[].itemID  (per-player live inventory)
      → this module's stat sum
      → target_armor / target_mr / target_max_hp / target_bonus_hp
      → DS server's rank_for / rank_items / compute_dps

When the request is from champ-select (no live game), there's no enemy
inventory to sum — caller falls back to ``compute_enemy_stats(mode,
level)`` from coach_integration.enemy_stats which provides a mode/level
scaled curve.

Item stats source: ``data/meta/ddragon_items.json`` (DDragon item
catalog). The relevant Flat* fields:
    FlatArmorMod         → armor
    FlatSpellBlockMod    → magic resist
    FlatHPPoolMod        → max HP / bonus HP
We do NOT subtract base champion stats — the DS engine adds those
separately via ``compute_enemy_stats``. ``target_*`` params are
*additive deltas* on top of the base curve in s170's design.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.enemy_aware_stats")

_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_items.json"

# Module-level cache of id → stats dict. Loaded lazily on first call.
_STAT_INDEX: dict[str, dict] | None = None


def _load_stat_index() -> dict[str, dict]:
    """Read ddragon_items.json and build id → relevant-stats map.

    Returns ``{item_id: {"armor": x, "mr": y, "hp": z}}``.
    Item id keys are stored as strings; both 4-digit SR ids (``"3047"``)
    and 6-digit ARAM-skin ids (``"223047"``) live in the catalog so we
    don't need a separate alias map.
    """
    global _STAT_INDEX
    if _STAT_INDEX is not None:
        return _STAT_INDEX
    out: dict[str, dict] = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for item_id, entry in data.items():
            stats = entry.get("stats") or {}
            armor = float(stats.get("FlatArmorMod") or 0.0)
            mr    = float(stats.get("FlatSpellBlockMod") or 0.0)
            hp    = float(stats.get("FlatHPPoolMod") or 0.0)
            if armor or mr or hp:
                out[str(item_id)] = {"armor": armor, "mr": mr, "hp": hp}
    except FileNotFoundError:
        _log.warning("enemy_aware_stats: %s missing — falling back to empty index",
                     _ITEMS_PATH)
    except Exception as exc:
        _log.warning("enemy_aware_stats: load failed: %s", exc)
    _STAT_INDEX = out
    return out


def compute_target_stats_from_items(enemy_items_by_player: list[list],
                                    aggregator: str = "avg") -> dict:
    """Sum item stats per enemy, then aggregate across enemies.

    ``enemy_items_by_player``: list (one entry per enemy champion) of
    item-id lists. Item ids may be ints or strings; everything is
    coerced to str for the catalog lookup.

    ``aggregator``: ``"avg"`` (mean across enemies — typical-target),
    ``"max"`` (highest-stat enemy — worst-case for armor/MR pen),
    ``"top1"`` (only the most-itemized enemy).

    Returns ``{"target_armor": float, "target_mr": float,
    "target_max_hp": float, "target_bonus_hp": float,
    "n_enemies": int, "source": "live-items"}``.

    Aggregator semantics:
      - For armor / MR: ``"avg"`` is the right call for the team-fight
        target because DPS averages across the team.
      - For HP: ``"avg"`` again; the "1-shot me" hyper-fed case is
        not solvable by target_hp tuning alone (it needs an incoming-
        damage / defensive-build heuristic, deferred follow-up).

    ``target_max_hp`` and ``target_bonus_hp`` are kept identical for now
    because the catalog doesn't distinguish base-HP increases from
    bonus-HP increases on items (every Flat*HPPool* counts as bonus on
    top of the champ's base).
    """
    if aggregator not in ("avg", "max", "top1"):
        aggregator = "avg"
    idx = _load_stat_index()
    if not idx or not enemy_items_by_player:
        return _empty_stats()

    per_enemy: list[tuple[float, float, float]] = []
    for items in enemy_items_by_player:
        if not isinstance(items, (list, tuple)):
            continue
        a, m, hp = 0.0, 0.0, 0.0
        for iid in items:
            stat = idx.get(str(iid))
            if not stat:
                continue
            a += stat["armor"]
            m += stat["mr"]
            hp += stat["hp"]
        per_enemy.append((a, m, hp))

    if not per_enemy:
        return _empty_stats()

    if aggregator == "max":
        a = max(x[0] for x in per_enemy)
        m = max(x[1] for x in per_enemy)
        hp = max(x[2] for x in per_enemy)
    elif aggregator == "top1":
        # Most-itemized = highest total stat sum
        best = max(per_enemy, key=lambda t: sum(t))
        a, m, hp = best
    else:  # avg
        n = len(per_enemy)
        a  = sum(x[0] for x in per_enemy) / n
        m  = sum(x[1] for x in per_enemy) / n
        hp = sum(x[2] for x in per_enemy) / n

    return {
        "target_armor":    round(a, 1),
        "target_mr":       round(m, 1),
        "target_max_hp":   round(hp, 1),
        "target_bonus_hp": round(hp, 1),
        "n_enemies":       len(per_enemy),
        "source":          "live-items",
        "aggregator":      aggregator,
    }


def _empty_stats() -> dict:
    return {
        "target_armor":    0.0,
        "target_mr":       0.0,
        "target_max_hp":   0.0,
        "target_bonus_hp": 0.0,
        "n_enemies":       0,
        "source":          "empty",
        "aggregator":      "avg",
    }


def enemy_items_from_liveclient(liveclient_data: dict,
                                exclude_team: str | None = None) -> list[list[int]]:
    """Extract enemy items from a liveclient /allgamedata snapshot.

    ``liveclient_data`` is the unwrapped ``data`` field from the relay
    response (the dict containing ``activePlayer`` and ``allPlayers``).
    ``exclude_team`` filters out one team's players ("ORDER"/"CHAOS");
    pass the active player's team to get just the enemies.

    Returns ``[[item_id, item_id, ...], ...]`` (one inner list per
    enemy). Trinkets are filtered out — they don't contribute relevant
    stats and would dilute the average.
    """
    if not isinstance(liveclient_data, dict):
        return []
    players = liveclient_data.get("allPlayers") or []
    out: list[list[int]] = []
    for p in players:
        if not isinstance(p, dict):
            continue
        if exclude_team and p.get("team") == exclude_team:
            continue
        items = p.get("items") or []
        ids: list[int] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            iid = it.get("itemID") or it.get("itemId") or 0
            slot = it.get("slot")
            # Slot 6 is the trinket — skip; 0-5 are real items.
            if slot is not None and slot >= 6:
                continue
            if iid:
                try: ids.append(int(iid))
                except (TypeError, ValueError): pass
        out.append(ids)
    return out


def active_player_team(liveclient_data: dict) -> str | None:
    """Return ORDER / CHAOS for the active player so we can exclude
    their team from enemy lists."""
    if not isinstance(liveclient_data, dict):
        return None
    ap = liveclient_data.get("activePlayer") or {}
    me_name = ap.get("summonerName") or ap.get("riotIdGameName") or ""
    if not me_name:
        return None
    for p in (liveclient_data.get("allPlayers") or []):
        if not isinstance(p, dict):
            continue
        # Match on either summonerName or composed riotId
        rid = p.get("riotIdGameName") or p.get("summonerName") or ""
        if rid == me_name or me_name.startswith(rid + "#") or rid == me_name.split("#", 1)[0]:
            return p.get("team")
    return None
