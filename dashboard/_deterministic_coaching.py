# arch: deterministic coaching resolver for /api/state | section=dashboard | frozen=no
"""Haiku-elimination wave 3 - deterministic coaching resolver for /api/state.

PURPOSE
    The live coach path otherwise pays a Claude Haiku call to answer three
    things this slice can precompute deterministically:
      1. the "trade / all-in / back off" laning A/B choices (via the DS
         matchup engine - ``core.laning_verdicts.laning_choices``),
      2. the next objective / spike callouts (pure table -
         ``core.event_callouts.next_callouts``),
      3. the macro lead read (pure diff - ``core.lead_projection.project_lead``).
    This module maps the dashboard's coach + liveclient dicts into the
    ``game_state`` shape those three pure generators read, calls them, and
    returns one merged ``{choices, callouts, lead_projection}`` dict that
    ``build_state`` splices into /api/state. The PRIMARY north-star wiring -
    these three surfaces no longer need a Claude call.

WHY A TTL CACHE
    ``laning_choices`` makes ONE network call to the DS engine (:8893) per
    invocation. The dashboard polls /api/state every ~500ms. Without a cache
    that would hammer matchup() ~2x/sec. The cache keys on a COARSE signature
    (champ, enemy comp, level, item count, mode, game_time bucketed to 5s) so
    callouts/lead refresh at a sane cadence while matchup() is called at most
    once per ~3s window per distinct game state.

FAIL-SOFT
    Every entry point swallows exceptions and degrades to fewer/empty outputs.
    A coach/lc dict that raises inside, the DS engine being down, or a missing
    build-orders file each yields ``{choices: [], callouts: [], lead: {}}`` -
    NEVER raises. ``build_state`` falls back to the coach's native choices /
    the synthesizer only when the deterministic ``choices`` list is empty.

This module touches the network only transitively (through laning_choices ->
matchup). It is plain Python (not a workflow script) so ``time.monotonic`` for
the cache clock is fine.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.coach_choices import (
    parse_choices,
    synthesize_simple_choices,
    to_jsonable,
)
from core.event_callouts import next_callouts
from core.laning_verdicts import laning_choices
from core.lead_projection import project_lead

_DS_DATA = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"

# Build-order + item-cost data is loaded lazily once and memoised. WHY here and
# not in core.event_callouts: that module is pure (no file reads); the recall
# callout needs the precomputed build-order tables + item catalog, so the
# impure lookup lives in this dashboard-layer resolver and is passed in.
_BUILD_ORDERS_CACHE: dict[str, dict] = {}
_ITEM_COST_CACHE: dict[str, tuple[str, int]] = {}
# Build-order bucket used for the recall directive. The recall callout is a
# back-TIMING signal ("you can afford your next core item"), not the comp-
# optimal item pick, so the balanced order is the honest default.
_RECALL_BUCKET = "balanced"


def _current_patch() -> str:
    try:
        return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _load_build_orders(mode_lower: str) -> dict:
    """champ -> bucket -> [item_id_str]. Memoised per mode; {} fail-soft."""
    if mode_lower in _BUILD_ORDERS_CACHE:
        return _BUILD_ORDERS_CACHE[mode_lower]
    out: dict = {}
    patch = _current_patch()
    if patch:
        path = _DS_DATA / patch / f"build_orders_{mode_lower}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            out = raw.get("build_orders") or {}
        except (OSError, ValueError):
            out = {}
    _BUILD_ORDERS_CACHE[mode_lower] = out
    return out


def _load_item_costs() -> dict[str, tuple[str, int]]:
    """item_id_str -> (display_name, total_gold). Memoised; {} fail-soft."""
    if _ITEM_COST_CACHE:
        return _ITEM_COST_CACHE
    patch = _current_patch()
    if patch:
        path = _DS_DATA / patch / "items.json"
        try:
            data = (json.loads(path.read_text(encoding="utf-8")).get("data") or {})
            for iid, it in data.items():
                if not isinstance(it, dict):
                    continue
                gold = it.get("gold")
                total = gold.get("total") if isinstance(gold, dict) else None
                if isinstance(total, (int, float)) and not isinstance(total, bool):
                    _ITEM_COST_CACHE[str(iid)] = (str(it.get("name") or ""), int(total))
        except (OSError, ValueError):
            pass
    return _ITEM_COST_CACHE


def _next_build_item(champ: object, mode_lower: str, owned_count: int):
    """Return (name, cost) of the next item in champ's build order, or None.

    Reads the balanced build order for ``champ`` and indexes at ``owned_count``
    (the next un-bought core item). Fail-soft: unknown champ / finished build /
    missing cost -> None."""
    if not isinstance(champ, str) or not champ.strip():
        return None
    orders = _load_build_orders(mode_lower)
    champ_orders = orders.get(champ.strip())
    if not isinstance(champ_orders, dict):
        return None
    order = champ_orders.get(_RECALL_BUCKET)
    if not isinstance(order, list):
        order = next((v for v in champ_orders.values() if isinstance(v, list)), None)
    if not order or not (0 <= owned_count < len(order)):
        return None
    costs = _load_item_costs()
    entry = costs.get(str(order[owned_count]))
    if not entry or not entry[0]:
        return None
    return entry

# ---------------------------------------------------------------------------
# Mode mapping. The dashboard mode_key is lower-case (sr / aram / arena / tft /
# brawl / client / game). laning_choices + project_lead want an UPPER-case mode
# ("SR" / "ARAM" / "ARENA"); next_callouts wants LOWER-case ("sr"/"aram"/
# "arena"). client + game are SR-equivalent for these three generators.
# ---------------------------------------------------------------------------
_MODE_KEY_TO_UPPER = {
    "sr": "SR",
    "client": "SR",
    "game": "SR",
    "aram": "ARAM",
    "arena": "ARENA",
}
_MODE_KEY_TO_LOWER = {
    "sr": "sr",
    "client": "sr",
    "game": "sr",
    "aram": "aram",
    "arena": "arena",
}

# Cache TTL (seconds) + size bound. 3.0s keeps matchup() to <= ~1 call / 3s per
# distinct coarse game state while the dashboard polls at 500ms.
_CACHE_TTL_S = 3.0
_CACHE_MAX = 64
# Module-level cache: sig -> (monotonic_ts, result_dict).
_CACHE: dict[tuple, tuple[float, dict]] = {}

_EMPTY_RESULT = {"choices": [], "callouts": [], "lead_projection": {}}


def _first(*vals: object) -> object:
    """Return the first value that is not None / not empty-string. WHY: coach
    wins over lc per the or-chain order the caller passes, but a present-but-0
    numeric (gold/cs 0 are real) must still win over a later None - so this only
    skips None and '', not falsy numbers."""
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _completed_item_count(lc: dict | None) -> int:
    """Best-effort count of owned completed items from the liveclient dict.

    liveclient_summary() carries ``owned_items`` (display-name list) and
    ``owned_item_ids`` (parallel id list). We count non-empty entries. Trinkets
    are already excluded by the consumers that care; for the spike-count proxy a
    coarse len() is acceptable. Returns 0 fail-soft (no lc / bad shape)."""
    if not isinstance(lc, dict):
        return 0
    owned = lc.get("owned_items")
    if isinstance(owned, list):
        return sum(1 for x in owned if x)
    ids = lc.get("owned_item_ids")
    if isinstance(ids, list):
        return sum(1 for x in ids if x)
    return 0


def _build_game_state(coach: dict, lc: dict | None, mode_key: str) -> dict:
    """Map the dashboard coach + liveclient dicts into the game_state shape the
    three pure generators read.

    Field precedence is coach-wins-then-lc (coach.get(...) or lc.get(...)) for
    every overlapping field, EXCEPT enemy_comp which only the liveclient carries
    (``lc.enemy_team`` -> game_state.enemy_comp - the modules read
    ``game_state['enemy_comp']``). Any absent field is omitted / defaulted so
    laning_choices + next_callouts + project_lead each handle the gap fail-soft.
    """
    coach = coach if isinstance(coach, dict) else {}
    lc = lc if isinstance(lc, dict) else {}

    gs: dict = {}

    my_champion = _first(coach.get("champion"), lc.get("champion"))
    if my_champion is not None:
        gs["my_champion"] = my_champion

    # enemy_comp comes ONLY from the liveclient enemy_team list.
    enemy_team = lc.get("enemy_team")
    if isinstance(enemy_team, list) and enemy_team:
        gs["enemy_comp"] = [str(c) for c in enemy_team if c]

    level = _first(coach.get("level"), lc.get("level"))
    if level is not None:
        gs["level"] = level

    kda = _first(coach.get("kda"), lc.get("kda"))
    if kda is not None:
        gs["kda"] = kda

    cs = _first(coach.get("cs"), lc.get("cs"))
    if cs is not None:
        gs["cs"] = cs

    gold = _first(coach.get("gold"), lc.get("gold"))
    if gold is not None:
        gs["gold"] = gold

    game_time_s = _first(
        coach.get("game_time_s"),
        coach.get("game_seconds"),
        lc.get("game_time_s"),
    )
    if game_time_s is not None:
        gs["game_time_s"] = game_time_s

    role = coach.get("role")
    if role:
        gs["role"] = role

    # Owned item names (for the build-next-item choice) + ids (for matchup).
    owned = _first(coach.get("items"), lc.get("owned_items"))
    if isinstance(owned, list) and owned:
        gs["items"] = owned
    item_ids = _first(coach.get("my_item_ids"), lc.get("owned_item_ids"))
    if isinstance(item_ids, list) and item_ids:
        gs["my_item_ids"] = item_ids

    # Inhibitor-down events come only from the liveclient (SR live events).
    inhib_events = lc.get("inhib_events")
    if isinstance(inhib_events, list) and inhib_events:
        gs["inhib_events"] = inhib_events

    return gs


def _cache_sig(gs: dict, mode_key: str) -> tuple:
    """Coarse cache signature. game_time bucketed to 5s so callouts/lead refresh
    on a sane cadence while matchup() (inside laning_choices) is not hammered.
    item_count keys on len so a completed-item purchase re-computes."""
    try:
        gt = float(gs.get("game_time_s") or 0.0)
    except (TypeError, ValueError):
        gt = 0.0
    enemy = gs.get("enemy_comp")
    enemy_key = tuple(enemy) if isinstance(enemy, list) else ()
    items = gs.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    try:
        lvl = int(gs.get("level") or 0)
    except (TypeError, ValueError):
        lvl = 0
    # item_count alone is not enough: laning_verdicts passes my_item_ids to
    # matchup() (item_ids_a), so the verdict depends on WHICH items are owned,
    # not just how many. Key on the id tuple so a same-count item swap (sell +
    # rebuy within the TTL) re-computes instead of serving the stale verdict.
    raw_ids = gs.get("my_item_ids")
    item_ids_key = (
        tuple(str(i) for i in raw_ids if i) if isinstance(raw_ids, list) else ()
    )
    # Inhibitor events change the callouts, so they must change the sig too
    # (same completeness rule as item ids) - key on the down-times.
    inhib = gs.get("inhib_events")
    inhib_key = (
        tuple(sorted(str(e.get("down_at_s")) for e in inhib
                     if isinstance(e, dict)))
        if isinstance(inhib, list) else ()
    )
    return (
        str(gs.get("my_champion") or ""),
        enemy_key,
        lvl,
        item_count,
        str(mode_key or ""),
        int(gt // 5),
        item_ids_key,
        inhib_key,
    )


def _evict_if_full() -> None:
    """Drop the oldest cache entry when the cache exceeds _CACHE_MAX, so a long
    session can't grow it unbounded."""
    if len(_CACHE) <= _CACHE_MAX:
        return
    # Oldest by stored monotonic timestamp.
    oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
    _CACHE.pop(oldest_key, None)


def _compute_uncached(gs: dict, mode_key: str) -> dict:
    """The actual generator fan-out (no cache). Calls laning_choices (network
    via matchup), next_callouts (pure), project_lead (pure). Returns the merged
    dict. Wrapped by compute_deterministic in a try/except so a raise here can
    never escape."""
    mk = str(mode_key or "").strip().lower()
    upper = _MODE_KEY_TO_UPPER.get(mk, "SR")
    lower = _MODE_KEY_TO_LOWER.get(mk, "sr")

    # choices (deterministic A/B from the DS matchup engine).
    choices = laning_choices(gs, mode=upper)
    choices_json = to_jsonable(choices) if choices else []

    # callouts (pure objective/spike table).
    try:
        gt = float(gs.get("game_time_s") or 0.0)
    except (TypeError, ValueError):
        gt = 0.0
    try:
        lvl = int(gs.get("level") or 1)
    except (TypeError, ValueError):
        lvl = 1
    items = gs.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    gold = gs.get("gold")
    nxt = _next_build_item(gs.get("my_champion"), lower, item_count)
    next_name = nxt[0] if nxt else None
    next_cost = nxt[1] if nxt else None
    callouts = next_callouts(
        lower, gt, lvl, item_count, max_n=3,
        gold=gold, next_item_name=next_name, next_item_cost=next_cost,
        inhib_events=gs.get("inhib_events"),
    )

    # lead_projection (pure diff).
    lead = project_lead(gs, mode=upper)

    return {
        "choices": choices_json,
        "callouts": callouts if isinstance(callouts, list) else [],
        "lead_projection": lead if isinstance(lead, dict) else {},
    }


def compute_deterministic(coach: dict, lc: dict | None, mode_key: str) -> dict:
    """Return ``{choices, callouts, lead_projection}`` for /api/state.

    TTL-cached on a coarse game-state signature (3.0s) so the DS matchup call
    inside laning_choices is not hammered by the 500ms /api/state poll. Wholly
    fail-soft: any exception yields the all-empty result, never raises.

    Args:
        coach: the coach JSON dict (may carry champion/level/kda/cs/gold/...).
        lc: the liveclient_summary() dict (enemy_team / owned_items / ...) or
            None when not in a game.
        mode_key: dashboard mode_key (sr/aram/arena/client/game/...).

    Returns:
        dict with keys ``choices`` (list[dict]), ``callouts`` (list[dict]),
        ``lead_projection`` (dict). ``choices`` is the DETERMINISTIC laning
        source - empty when the engine is down or no enemy is resolvable, in
        which case build_state falls back to the coach's native / synth choices.
    """
    try:
        gs = _build_game_state(coach, lc, mode_key)
        sig = _cache_sig(gs, mode_key)
        now = time.monotonic()
        hit = _CACHE.get(sig)
        if hit is not None and (now - hit[0]) < _CACHE_TTL_S:
            return hit[1]
        result = _compute_uncached(gs, mode_key)
        _CACHE[sig] = (now, result)
        _evict_if_full()
        return result
    except Exception:
        return dict(_EMPTY_RESULT)


def resolve_choices(coach: dict, det: dict) -> list[dict]:
    """Deterministic-FIRST choice resolution for build_state.

    Returns the choices list build_state stamps onto ``coach['choices']``:
      1. the deterministic laning choices from ``det['choices']`` when non-empty
         (the DS-matchup source),
      2. else the coach's native-emit ``choices`` (parse_choices),
      3. else the conservative synthesizer over the coach's action prose,
      4. else [].
    Fail-soft: any error yields ``det['choices']`` (already a list) or [].
    """
    try:
        det_choices = (det or {}).get("choices") or []
        if det_choices:
            return det_choices
        native = parse_choices(coach)
        return to_jsonable(native or synthesize_simple_choices(coach))
    except Exception:
        return (det or {}).get("choices") or []
