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
inventory to sum - caller falls back to ``compute_enemy_stats(mode,
level)`` from coach_integration.enemy_stats which provides a mode/level
scaled curve.

Item stats source: ``data/meta/ddragon_items.json`` (DDragon item
catalog). The relevant Flat* fields:
    FlatArmorMod         → armor
    FlatSpellBlockMod    → magic resist
    FlatHPPoolMod        → max HP / bonus HP
P1-L4 audit fix (2026-05-19): the original s170 docstring claimed
"the DS engine adds [base champion stats] separately ... ``target_*``
params are *additive deltas* on top of the base curve". That rationale
is FALSE. The engine treats ``target_armor`` / ``target_mr`` /
``target_max_hp`` as the *absolute* target state -
``agents.daemon_slayer.dps.compute_dps`` calls
``effective_target_armor(target_armor, ...)`` and applies pen directly,
adding NO target base. And the live-items branch in
``dashboard.routes_state._resolve_ds_target_stats`` *returns* this
result instead of summing it with ``compute_enemy_stats`` - the two are
mutually exclusive, never added. So summing item flats ALONE handed DS
a target whose armor/MR/HP was understated by the entire champion
base-by-level component (a level-11 tank already has ~75 base armor),
roughly halving target armor and systematically inflating physical-DPS
item deltas / skewing armor-pen rankings.

Fix: an OPT-IN champion-base layer. When the caller passes
``enemy_champions`` + ``level`` (which ``/api/ds-preview`` already
resolves), each enemy's Riot-quadratic base armor/MR/HP by level is
added to that enemy's item flats BEFORE the cross-enemy aggregate, so
the value handed to DS is a correct absolute target. Called the legacy
way (no champions) behaviour is unchanged - existing callers/tests see
item-sum-only output and ``source="live-items"``.

Base growth uses the canonical Riot coefficient
``(n-1) * (0.7025 + 0.0175 * (n-1))`` - identical to
``agents.daemon_slayer.stats.growth_multiplier`` - re-derived locally so
the caller side does not import the (frozen-adjacent) engine module.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.enemy_aware_stats")

_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_items.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level cache of champ name -> base stat tuple. Lazy-loaded.
_CHAMP_INDEX: dict[str, dict] | None = None


def _riot_growth_multiplier(level: int) -> float:
    """Canonical Riot per-level stat-growth coefficient.

    Equals ``agents.daemon_slayer.stats.growth_multiplier``; zero at
    level 1, exactly 17.0 at level 18, strictly sub-linear between.
    """
    lv = max(1, min(18, int(level)))
    return (lv - 1) * (0.7025 + 0.0175 * (lv - 1))


def _load_champ_index() -> dict[str, dict]:
    """Read ddragon_champions.json -> name -> base armor/MR/HP scaling.

    Returns ``{champ: {"armor","armorperlevel","mr","mrperlevel",
    "hp","hpperlevel"}}``. Empty dict on any failure (base layer then
    no-ops, preserving the legacy items-only result).
    """
    global _CHAMP_INDEX
    if _CHAMP_INDEX is not None:
        return _CHAMP_INDEX
    out: dict[str, dict] = {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for _key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            name = entry.get("id") or entry.get("name") or _key
            st = entry.get("stats") or {}
            out[str(name)] = {
                "armor":        float(st.get("armor") or 0.0),
                "armorperlevel": float(st.get("armorperlevel") or 0.0),
                "mr":           float(st.get("spellblock") or 0.0),
                "mrperlevel":   float(st.get("spellblockperlevel") or 0.0),
                "hp":           float(st.get("hp") or 0.0),
                "hpperlevel":   float(st.get("hpperlevel") or 0.0),
            }
    except FileNotFoundError:
        _log.warning("enemy_aware_stats: %s missing - base layer disabled",
                     _CHAMPS_PATH)
    except Exception as exc:  # noqa: BLE001
        _log.warning("enemy_aware_stats: champ index load failed: %s", exc)
    _CHAMP_INDEX = out
    return out


def _champ_base_by_level(champ: str, level: int) -> tuple[float, float, float, float]:
    """(base_armor, base_mr, max_hp_from_base, bonus_hp_from_growth).

    ``max_hp_from_base`` is base hp + per-level growth (the champion's
    own HP, no items). ``bonus_hp_from_growth`` is JUST the per-level
    growth portion - bonus-HP-scaling items (Giant Slayer, BotRK) key
    off bonus HP, so champion BASE hp is excluded from that field
    (mirrors the engine's bonus-vs-max distinction). Unknown champ -> 0s.
    """
    idx = _load_champ_index()
    s = idx.get(str(champ))
    if not s:
        return 0.0, 0.0, 0.0, 0.0
    g = _riot_growth_multiplier(level)
    base_armor = s["armor"] + s["armorperlevel"] * g
    base_mr = s["mr"] + s["mrperlevel"] * g
    grown_hp = s["hpperlevel"] * g
    max_hp = s["hp"] + grown_hp
    return base_armor, base_mr, max_hp, grown_hp

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
        _log.warning("enemy_aware_stats: %s missing - falling back to empty index",
                     _ITEMS_PATH)
    except Exception as exc:
        _log.warning("enemy_aware_stats: load failed: %s", exc)
    _STAT_INDEX = out
    return out


def compute_target_stats_from_items(enemy_items_by_player: list[list],
                                    aggregator: str = "avg",
                                    *,
                                    enemy_champions: list | None = None,
                                    level: int | None = None) -> dict:
    """Per-enemy resist/HP, then aggregate across enemies.

    ``enemy_items_by_player``: list (one entry per enemy champion) of
    item-id lists. Item ids may be ints or strings; everything is
    coerced to str for the catalog lookup.

    ``aggregator``: ``"avg"`` (mean across enemies - typical-target),
    ``"max"`` (highest-stat enemy - worst-case for armor/MR pen),
    ``"top1"`` (only the most-itemized enemy).

    ``enemy_champions`` + ``level`` (P1-L4 fix, both required together):
    opt-in champion-base layer. When supplied, each enemy's Riot-quadratic
    base armor/MR/HP-by-level is added to that enemy's item flats BEFORE
    the cross-enemy aggregate, so the result is a correct *absolute*
    target (what the DS engine expects - it adds no target base itself).
    ``enemy_champions[i]`` aligns positionally with
    ``enemy_items_by_player[i]``; a shorter/longer list is zipped to the
    items length and missing/unknown names contribute zero base (graceful
    degradation to the legacy item-only value for that enemy).

    When ``enemy_champions`` / ``level`` are omitted, behaviour is the
    pre-fix item-sum-only path and ``source="live-items"`` (unchanged for
    existing callers). With the base layer ``source="live-items+base"``.

    Aggregator semantics:
      - For armor / MR: ``"avg"`` is the right call for the team-fight
        target because DPS averages across the team.
      - For HP: ``"avg"`` again; the "1-shot me" hyper-fed case is
        not solvable by target_hp tuning alone (it needs an incoming-
        damage / defensive-build heuristic, deferred follow-up).

    ``target_max_hp`` = champion max HP (base + per-level growth) + item
    flat HP. ``target_bonus_hp`` = per-level growth HP + item flat HP -
    champion BASE hp is excluded because bonus-HP-scaling items (Giant
    Slayer / BotRK) key off bonus HP, mirroring the engine's bonus-vs-max
    distinction. Without the base layer the catalog can't split base from
    bonus on items, so the two stay equal (item HP only).
    """
    if aggregator not in ("avg", "max", "top1"):
        aggregator = "avg"
    idx = _load_stat_index()
    if not idx or not enemy_items_by_player:
        return _empty_stats()

    use_base = bool(enemy_champions) and level is not None
    champ_list = list(enemy_champions) if enemy_champions else []

    # 4-tuple per enemy: (armor, mr, max_hp, bonus_hp). Without the base
    # layer max_hp == bonus_hp == item HP (legacy parity).
    per_enemy: list[tuple[float, float, float, float]] = []
    enemy_i = -1
    for items in enemy_items_by_player:
        if not isinstance(items, (list, tuple)):
            continue
        enemy_i += 1
        a, m, hp = 0.0, 0.0, 0.0
        for iid in items:
            stat = idx.get(str(iid))
            if not stat:
                continue
            a += stat["armor"]
            m += stat["mr"]
            hp += stat["hp"]
        if use_base:
            champ = champ_list[enemy_i] if enemy_i < len(champ_list) else ""
            b_armor, b_mr, b_maxhp, b_growhp = _champ_base_by_level(
                str(champ), int(level)
            )
            per_enemy.append((a + b_armor, m + b_mr,
                              hp + b_maxhp, hp + b_growhp))
        else:
            per_enemy.append((a, m, hp, hp))

    if not per_enemy:
        return _empty_stats()

    if aggregator == "max":
        a = max(x[0] for x in per_enemy)
        m = max(x[1] for x in per_enemy)
        max_hp = max(x[2] for x in per_enemy)
        bonus_hp = max(x[3] for x in per_enemy)
    elif aggregator == "top1":
        # Most-itemized = highest total stat sum (armor+mr+max_hp).
        best = max(per_enemy, key=lambda t: t[0] + t[1] + t[2])
        a, m, max_hp, bonus_hp = best
    else:  # avg
        n = len(per_enemy)
        a        = sum(x[0] for x in per_enemy) / n
        m        = sum(x[1] for x in per_enemy) / n
        max_hp   = sum(x[2] for x in per_enemy) / n
        bonus_hp = sum(x[3] for x in per_enemy) / n

    return {
        "target_armor":    round(a, 1),
        "target_mr":       round(m, 1),
        "target_max_hp":   round(max_hp, 1),
        "target_bonus_hp": round(bonus_hp, 1),
        "n_enemies":       len(per_enemy),
        "source":          "live-items+base" if use_base else "live-items",
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
    enemy). Trinkets are filtered out - they don't contribute relevant
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
            # Slot 6 is the trinket - skip; 0-5 are real items.
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
