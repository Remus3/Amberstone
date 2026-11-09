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
    liveclient relay (Legion-local :2999 -> Legion :8889/latest-liveclient)
      -> allPlayers[i].items[].itemID  (per-player live inventory)
      -> this module's stat sum
      -> target_armor / target_mr / target_max_hp / target_bonus_hp
      -> DS server's rank_for / rank_items / compute_dps

When the request is from champ-select (no live game), there's no enemy
inventory to sum - caller falls back to ``compute_enemy_stats(mode,
level)`` from coach_integration.enemy_stats which provides a mode/level
scaled curve.

Item stats source: ``data/meta/ddragon_items.json`` (DDragon item
catalog). The relevant Flat* fields:
    FlatArmorMod         -> armor
    FlatSpellBlockMod    -> magic resist
    FlatHPPoolMod        -> max HP / bonus HP
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
import math
from pathlib import Path

from core.failed_load_gate import FailedLoadGate

_log = logging.getLogger("rc.enemy_aware_stats")

_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_items.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level cache of champ name -> base stat tuple. Lazy-loaded.
_CHAMP_INDEX: dict[str, dict] | None = None
# RM-443: neither index caches a failed load - it is retried after the gate's
# backoff and warned once per failure streak (core/failed_load_gate.py).
_CHAMP_GATE = FailedLoadGate()
_STAT_GATE = FailedLoadGate()


# RM-415: the live-client envelope coercion seam for this module. The readers
# below used ``envelope.get(k) or {}`` / ``or []``, which substitutes the empty
# container only for a MISSING or falsey value and forwards a RETYPED one (a
# string, a bool, an int) unchanged, so the next ``.get()`` / ``for`` raised.
# core/liveclient_cache.py validates only the TOP-LEVEL envelope; every inner
# field arrives here untouched. One seam, not a per-site isinstance ladder.
def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_num(value: object) -> float | None:
    """A finite number from an int / float / numeric string, else None.

    ``bool`` is rejected (``True >= 6`` is valid Python and silently wrong).
    An int too large for a float (a 400-digit JSON integer parses to one) is
    None, not an ``OverflowError``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            f = float(value)
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return f if math.isfinite(f) else None


_ITEM_ID_MAX_DIGITS = 9


def _item_id(value: object) -> int | None:
    """A positive item id from an int, an integral float or a digit string.

    s144 true-audit: ``int(iid)`` took ``True`` as item 1, truncated 3047.5 to
    3047, and raised ``OverflowError`` (uncaught) on an ``Infinity`` id, which
    ``json.loads`` accepts. Anything that is not exactly a positive integer is
    "no item" (None).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not value.is_integer():  # False for nan / inf too
            return None
        n = int(value)
    elif isinstance(value, str):
        s = value.strip()
        # Length cap first: int() refuses a digit string past 4300 digits
        # with ValueError, and no item id comes near nine digits.
        if not (len(s) <= _ITEM_ID_MAX_DIGITS and s.isascii() and s.isdigit()):
            return None
        n = int(s)
    else:
        return None
    return n if n > 0 else None


def _champ_key(name: object) -> str:
    """Lowercase alphanumeric lookup key: "Kai'Sa" -> "kaisa", "Lee Sin" -> "leesin"."""
    if not isinstance(name, str):
        return ""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _catalog_rows(raw: object) -> dict | None:
    """The ``data`` mapping of a DDragon catalog, or None for a wrong shape."""
    if not isinstance(raw, dict):
        return None
    data = raw.get("data", raw)
    return data if isinstance(data, dict) else None


def _stat(stats: dict, key: str) -> float:
    """One finite stat value, 0.0 when absent, non-numeric or non-finite."""
    v = _as_num(stats.get(key))
    return v if v is not None else 0.0


def _riot_growth_multiplier(level: int) -> float:
    """Canonical Riot per-level stat-growth coefficient.

    Equals ``agents.daemon_slayer.stats.growth_multiplier``; zero at
    level 1, exactly 17.0 at level 18, strictly sub-linear between.
    """
    lv = max(1, min(18, int(level)))
    return (lv - 1) * (0.7025 + 0.0175 * (lv - 1))


def _load_champ_index() -> dict[str, dict]:
    """Read ddragon_champions.json -> name -> base armor/MR/HP scaling.

    Returns ``{key: {"armor","armorperlevel","mr","mrperlevel",
    "hp","hpperlevel"}}``. Empty dict on a failed load (base layer then
    no-ops, preserving the legacy items-only result).

    s144 true-audit: each champion is indexed under its DDragon ``id``, its
    display ``name`` and its catalog key, each verbatim AND as a
    :func:`_champ_key`. The Live Client ``championName`` the dashboard passes is
    the DISPLAY name ("Kai'Sa", "Lee Sin", "Wukong", "Nunu & Willump"); keyed by
    ``id`` alone those enemies silently got zero base. A malformed row (non-dict
    entry or ``stats``) is skipped and a non-numeric or non-finite stat reads
    0.0, so one bad row no longer disables the whole layer. Only an unreadable
    file, malformed JSON or a wrong top-level shape is a failed load.
    """
    global _CHAMP_INDEX
    if _CHAMP_INDEX is not None:
        return _CHAMP_INDEX
    if not _CHAMP_GATE.should_attempt():
        return {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if _CHAMP_GATE.record_failure():
            _log.warning("enemy_aware_stats: %s missing - base layer disabled",
                         _CHAMPS_PATH)
        return {}
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        if _CHAMP_GATE.record_failure():
            _log.warning("enemy_aware_stats: champ index load failed: %s", exc)
        return {}
    data = _catalog_rows(raw)
    if data is None:
        if _CHAMP_GATE.record_failure():
            _log.warning("enemy_aware_stats: %s has no champion mapping",
                         _CHAMPS_PATH)
        return {}
    out: dict[str, dict] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        st = _as_dict(entry.get("stats"))
        row = {
            "armor":         _stat(st, "armor"),
            "armorperlevel": _stat(st, "armorperlevel"),
            "mr":            _stat(st, "spellblock"),
            "mrperlevel":    _stat(st, "spellblockperlevel"),
            "hp":            _stat(st, "hp"),
            "hpperlevel":    _stat(st, "hpperlevel"),
        }
        for name in (entry.get("id"), entry.get("name"), key):
            if not isinstance(name, str):
                continue
            for k in (name, _champ_key(name)):
                if k:
                    out.setdefault(k, row)
    _CHAMP_GATE.record_success()
    _CHAMP_INDEX = out
    return out


def _champ_base_by_level(champ: str, level: int) -> tuple[float, float, float, float]:
    """(base_armor, base_mr, max_hp_from_base, bonus_hp_from_growth).

    ``max_hp_from_base`` is base hp + per-level growth (the champion's
    own HP, no items). ``bonus_hp_from_growth`` is JUST the per-level
    growth portion - bonus-HP-scaling items (Giant Slayer, BotRK) key
    off bonus HP, so champion BASE hp is excluded from that field
    (mirrors the engine's bonus-vs-max distinction). Unknown champ -> 0s.
    ``champ`` may be the DDragon id or the display name.
    """
    idx = _load_champ_index()
    if not isinstance(champ, str) or not champ:
        return 0.0, 0.0, 0.0, 0.0
    s = idx.get(champ) or idx.get(_champ_key(champ))
    if not s:
        return 0.0, 0.0, 0.0, 0.0
    g = _riot_growth_multiplier(level)
    base_armor = s["armor"] + s["armorperlevel"] * g
    base_mr = s["mr"] + s["mrperlevel"] * g
    grown_hp = s["hpperlevel"] * g
    max_hp = s["hp"] + grown_hp
    return base_armor, base_mr, max_hp, grown_hp

# Module-level cache of id -> stats dict. Loaded lazily on first call.
_STAT_INDEX: dict[str, dict] | None = None


def _load_stat_index() -> dict[str, dict]:
    """Read ddragon_items.json and build id -> relevant-stats map.

    Returns ``{item_id: {"armor": x, "mr": y, "hp": z}}``.
    Item id keys are stored as strings; both 4-digit SR ids (``"3047"``)
    and 6-digit ARAM-skin ids (``"223047"``) live in the catalog so we
    don't need a separate alias map.

    s144 true-audit: a malformed row (non-dict entry or ``stats``) is skipped
    and a non-numeric or non-finite stat (``json.loads`` accepts ``NaN`` /
    ``Infinity``) reads 0.0, so one bad row neither disables the index nor
    poisons ``target_*`` with nan / inf. Only an unreadable file, malformed
    JSON or a wrong top-level shape is a failed load (not cached).
    """
    global _STAT_INDEX
    if _STAT_INDEX is not None:
        return _STAT_INDEX
    if not _STAT_GATE.should_attempt():
        return {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if _STAT_GATE.record_failure():
            _log.warning("enemy_aware_stats: %s missing - falling back to empty index",
                         _ITEMS_PATH)
        return {}
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        if _STAT_GATE.record_failure():
            _log.warning("enemy_aware_stats: load failed: %s", exc)
        return {}
    data = _catalog_rows(raw)
    if data is None:
        if _STAT_GATE.record_failure():
            _log.warning("enemy_aware_stats: %s has no item mapping", _ITEMS_PATH)
        return {}
    out: dict[str, dict] = {}
    for item_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        stats = _as_dict(entry.get("stats"))
        armor = _stat(stats, "FlatArmorMod")
        mr = _stat(stats, "FlatSpellBlockMod")
        hp = _stat(stats, "FlatHPPoolMod")
        if armor or mr or hp:
            out[str(item_id)] = {"armor": armor, "mr": mr, "hp": hp}
    _STAT_GATE.record_success()
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

    s144 true-audit: the base layer needs ``enemy_champions`` as a list or
    tuple and ``level`` as a finite number (int, float or numeric string,
    never ``bool``); anything else degrades to the item-only path instead of
    raising out of ``int(level)`` or splitting a ``str`` into letters. Item ids
    go through :func:`_item_id`, so ``3075``, ``3075.0`` and ``"3075"`` all hit
    the catalog. ``enemy_items_by_player`` that is not a list or tuple is no
    data (``_empty_stats()``), and so is a result that is not finite (stats
    near the float maximum can sum to inf), never a raise or an inf target.
    """
    if aggregator not in ("avg", "max", "top1"):
        aggregator = "avg"
    if not isinstance(enemy_items_by_player, (list, tuple)):
        return _empty_stats()
    idx = _load_stat_index()
    if not idx or not enemy_items_by_player:
        return _empty_stats()

    lvl = _as_num(level)
    champ_list = (list(enemy_champions)
                  if isinstance(enemy_champions, (list, tuple)) else [])
    use_base = bool(champ_list) and lvl is not None

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
            key = _item_id(iid)
            stat = idx.get(str(key)) if key is not None else None
            if not stat:
                continue
            a += stat["armor"]
            m += stat["mr"]
            hp += stat["hp"]
        if use_base:
            champ = champ_list[enemy_i] if enemy_i < len(champ_list) else ""
            b_armor, b_mr, b_maxhp, b_growhp = _champ_base_by_level(
                champ if isinstance(champ, str) else "", int(lvl)
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

    if not all(math.isfinite(v) for v in (a, m, max_hp, bonus_hp)):
        _log.debug("enemy_aware_stats: non-finite target from the catalog - empty")
        return _empty_stats()

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
    players = _as_list(liveclient_data.get("allPlayers"))
    out: list[list[int]] = []
    for p in players:
        if not isinstance(p, dict):
            continue
        if exclude_team and p.get("team") == exclude_team:
            continue
        items = _as_list(p.get("items"))
        ids: list[int] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            # A junk id (bool, fraction, nan / inf, non-digit string) is "no
            # item", never an OverflowError from ``int(inf)``.
            iid = _item_id(it.get("itemID") or it.get("itemId"))
            # An unparseable slot is "slot unknown" (same as absent), never a
            # TypeError from comparing a string to 6.
            slot = _as_num(it.get("slot"))
            # Slot 6 is the trinket - skip; 0-5 are real items.
            if slot is not None and slot >= 6:
                continue
            if iid is not None:
                ids.append(iid)
        out.append(ids)
    return out


def _single_team(players: list[dict]) -> str | None:
    """The one team every matched player is on, else None (none or ambiguous)."""
    teams = {_as_str(p.get("team")) for p in players}
    teams.discard("")
    return teams.pop() if len(teams) == 1 else None


def active_player_team(liveclient_data: dict) -> str | None:
    """Return ORDER / CHAOS for the active player so we can exclude
    their team from enemy lists.

    s144 true-audit: an EXACT full Riot ID match (a roster ``riotId`` or
    ``summonerName`` equal to the active player's ``riotId`` /
    ``summonerName``) wins first. Only without one does the game-name match
    run, and if game-name matches sit on BOTH teams (a shared game name with a
    different tag) the answer is None, never the first one found. A team that
    is not a non-empty string is None too.
    """
    if not isinstance(liveclient_data, dict):
        return None
    ap = _as_dict(liveclient_data.get("activePlayer"))
    me_name = _as_str(ap.get("summonerName") or ap.get("riotIdGameName"))
    if not me_name:
        return None
    me_full = {me_name, _as_str(ap.get("riotId"))}
    me_full.discard("")
    roster = [p for p in _as_list(liveclient_data.get("allPlayers"))
              if isinstance(p, dict)]

    exact = [p for p in roster
             if _as_str(p.get("riotId")) in me_full
             or _as_str(p.get("summonerName")) in me_full]
    if exact:
        return _single_team(exact)

    by_game_name = []
    for p in roster:
        # Match on either summonerName or composed riotId
        rid = _as_str(p.get("riotIdGameName") or p.get("summonerName"))
        if not rid:
            continue
        if rid == me_name or me_name.startswith(rid + "#") or rid == me_name.split("#", 1)[0]:
            by_game_name.append(p)
    return _single_team(by_game_name)
