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
import threading
import time
from pathlib import Path

from core.coach_choices import (
    parse_choices,
    synthesize_simple_choices,
    to_jsonable,
)
from core.event_callouts import next_callouts
from core.heal_threat import heal_threat_callout
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

# S7 (2026-06-10): the matchup call inside laning_choices costs ~690ms (live
# stage breakdown: deterministic=692ms of a 706ms build). Paying it inline on
# every 5s game-time bucket froze /api/state + the SSE tick for that long -
# the operator's "champ select / dashboard updates slow". Warm-path policy:
# once ANY result exists for the current (champion, mode), a sig miss returns
# the last good result immediately and refreshes the cache on a background
# single-flight thread. Cold start (new game / new champion) stays
# synchronous so the first real tick is correct, and tests see unchanged
# single-call behavior.
_REFRESH_INFLIGHT: set[tuple] = set()
_REFRESH_LOCK = threading.Lock()
# (champion, mode_key) -> last computed result for the warm-path fallback.
_LAST_GOOD: dict[tuple[str, str], dict] = {}


def _reset_caches_for_tests() -> None:
    """Test seam: clear ALL module caches (TTL cache + warm-path last-good +
    inflight markers) so cases stay hermetic under the warm-path policy."""
    _CACHE.clear()
    _LAST_GOOD.clear()
    with _REFRESH_LOCK:
        _REFRESH_INFLIGHT.clear()


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

    # Per-team item-id pools (for the heal-threat nudge) come only from the
    # liveclient scoreboard - the coach dict never carries the other players'
    # items. Absent / empty -> omitted, heal_threat_callout handles the gap.
    enemy_item_ids = lc.get("enemy_item_ids")
    if isinstance(enemy_item_ids, list) and enemy_item_ids:
        gs["enemy_item_ids"] = enemy_item_ids
    ally_item_ids = lc.get("ally_item_ids")
    if isinstance(ally_item_ids, list) and ally_item_ids:
        gs["ally_item_ids"] = ally_item_ids

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
    # Per-team item pools drive the heal-threat callout, so they must change
    # the sig too (same sig-completeness rule as item ids / inhib events) - an
    # enemy completing a sustain item or an ally buying anti-heal must re-compute
    # instead of serving the stale nudge.
    enemy_items = gs.get("enemy_item_ids")
    enemy_items_key = (
        tuple(sorted(str(i) for i in enemy_items if i))
        if isinstance(enemy_items, list) else ()
    )
    ally_items = gs.get("ally_item_ids")
    ally_items_key = (
        tuple(sorted(str(i) for i in ally_items if i))
        if isinstance(ally_items, list) else ()
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
        enemy_items_key,
        ally_items_key,
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
    upper = _MODE_KEY_TO_UPPER.get(mk)
    lower = _MODE_KEY_TO_LOWER.get(mk)
    if upper is None or lower is None:
        # tft / brawl / unknown have no laning / build / SR-objective model;
        # serve empty rather than silently scoring them against the SR tables
        # (and skip the needless DS matchup call every tick).
        return dict(_EMPTY_RESULT)

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

    # Heal-threat / anti-heal nudge (pure set-membership over the live item
    # pools). Standing advisory (eta_s None) - keep the 2 most-urgent timed
    # objectives and append it as the 3rd row so it is always visible when it
    # fires without crowding out an active "Baron NOW".
    heal = heal_threat_callout(
        gs.get("enemy_comp"), gs.get("enemy_item_ids"),
        gs.get("ally_item_ids"), mode=lower,
    )
    if heal is not None:
        callouts = (callouts[:2] if isinstance(callouts, list) else []) + [heal]

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

        warm_key = (str(gs.get("my_champion") or ""), str(mode_key or ""))
        last = _LAST_GOOD.get(warm_key)
        if last is None:
            # Cold start for this champion/mode: pay the compute inline so
            # the first real tick carries a verdict (and single-call tests
            # keep their synchronous contract).
            result = _compute_uncached(gs, mode_key)
            _store_result(sig, warm_key, result)
            return result

        # Warm path: serve the last good result NOW, refresh in background.
        _spawn_refresh(sig, warm_key, gs, mode_key)
        return hit[1] if hit is not None else last
    except Exception:
        return dict(_EMPTY_RESULT)


def _store_result(sig: tuple, warm_key: tuple[str, str], result: dict) -> None:
    _CACHE[sig] = (time.monotonic(), result)
    _LAST_GOOD[warm_key] = result
    if len(_LAST_GOOD) > _CACHE_MAX:
        _LAST_GOOD.pop(next(iter(_LAST_GOOD)), None)
    _evict_if_full()


def _spawn_refresh(sig: tuple, warm_key: tuple[str, str], gs: dict,
                   mode_key: str) -> None:
    """Single-flight background recompute. Concurrent /api/state + SSE
    builders that miss the same sig must not stack matchup calls."""
    with _REFRESH_LOCK:
        if sig in _REFRESH_INFLIGHT:
            return
        _REFRESH_INFLIGHT.add(sig)

    def _run() -> None:
        try:
            result = _compute_uncached(gs, mode_key)
            _store_result(sig, warm_key, result)
        except Exception:
            pass
        finally:
            with _REFRESH_LOCK:
                _REFRESH_INFLIGHT.discard(sig)

    threading.Thread(target=_run, name="det-coach-refresh",
                     daemon=True).start()


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


def shadow_log_det(coach: dict, lc: dict | None, det: dict, mode_key: str,
                   *, path=None) -> None:
    """Fail-soft B1 validation shadow-log. Records the deterministic surfaces
    plus the native choices resolve_choices discards, to
    data/det_coach_shadow.jsonl, alongside live coaching. Never raises and has
    NO effect on live output. Only fires for a real game (enemy_comp present).

    MUST be called BEFORE build_state overwrites coach["choices"] with
    resolve_choices(): it reads the NATIVE choices via parse_choices(coach), and
    the whole point of the log is to capture what the deterministic flip
    discards. ``path`` overrides the jsonl target (test seam)."""
    try:
        gs = _build_game_state(coach, lc, mode_key)
        enemy = gs.get("enemy_comp")
        champ = gs.get("my_champion")
        if not enemy or not champ:
            return
        native = to_jsonable(parse_choices(coach) or [])
        items = gs.get("items")
        item_count = len(items) if isinstance(items, list) else 0
        from core.det_coach_shadow import log_det_coaching  # lazy import
        log_det_coaching(
            str(mode_key or ""), str(champ), [str(e) for e in enemy],
            det=det if isinstance(det, dict) else {},
            native_choices=native,
            game_time_s=gs.get("game_time_s"),
            level=gs.get("level"),
            item_count=item_count,
            path=path,
        )
    except Exception:
        return


def _mana_fraction(coach: dict, lc: dict | None) -> float | None:
    """Best-effort current mana as a 0..1 fraction of the pool, or None.

    Reads a direct ``mana_pct`` / ``mana_fraction`` (0..1, or 0..100 percent)
    first, else derives ``mana`` / ``max_mana`` (``maxMana``) from the coach or
    liveclient dict. Returns None when no mana signal is present - the HZ-C1
    reader then defaults to the full-rotation cell. Fail-soft."""
    for src in (coach, lc):
        if not isinstance(src, dict):
            continue
        for k in ("mana_pct", "mana_fraction"):
            v = src.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                f = float(v)
                return f / 100.0 if f > 1.0 else f
        cur = src.get("mana")
        mx = src.get("max_mana") or src.get("maxMana")
        try:
            if cur is not None and mx:
                f = float(cur) / float(mx)
                if 0.0 <= f <= 1.5:
                    return f
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return None


def shadow_log_precomputed_choices(coach: dict, lc: dict | None, mode_key: str,
                                   *, path=None) -> None:
    """Fail-soft HZ-C1 validation shadow-log. Records what the PRECOMPUTED
    laning table (``core.precomputed_laning_coach``) would offer for this game
    state - including whether the seed table covered the matchup - to
    data/hz_choice_shadow.jsonl, alongside live coaching. Never raises and has
    NO effect on live output. Only fires when the LIVECLIENT champion is
    present (a real in-game tick) - the coach payload keeps its champion
    forever after a game ends, so coach-champion presence alone would log a
    junk row on every idle /api/state tick. A coverage MISS during a live game
    is recorded too (the seed coverage rate on real games is itself the
    validation signal). ``path`` overrides the jsonl target (test seam)."""
    try:
        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return
        # HZ-D4 live-game gate: lc["champion"] is only populated during a
        # real game (dashboard/_liveclient.py), while the stale coach file
        # keeps `champion` after the game ends. Without this, every idle
        # tick logs a junk row (enemy=null, covered=false).
        if not (isinstance(lc, dict) and lc.get("champion")):
            return
        mk = str(mode_key or "").strip().lower()
        lower = _MODE_KEY_TO_LOWER.get(mk)
        if lower is None:
            return  # tft / brawl have no laning table; do not score vs SR

        from core import precomputed_laning_coach as plc  # lazy import
        from core.laning_scenario_precompute import load_laning_scenarios
        from core.hz_choice_shadow import log_precomputed_choices

        level = gs.get("level")
        band = plc.band_for_level(level)
        mana_fraction = _mana_fraction(coach, lc)
        # Live ult-cooldown is not surfaced to the coach dict today; default to
        # the all_up baseline (cd_state_for(None)). A future event source can
        # thread it through here without touching the reader.
        ult_up = None
        mana_state = plc.mana_state_for(mana_fraction)
        cd_state = plc.cd_state_for(ult_up)
        items = gs.get("items")
        item_count = len(items) if isinstance(items, list) else 0

        payload = load_laning_scenarios(lower)
        enemy_comp = gs.get("enemy_comp") or []
        enemy = plc.resolve_enemy(
            str(champ), [str(e) for e in enemy_comp], lower, payload=payload,
        )

        choices: list = []
        covered = False
        if enemy:
            next_item = _next_build_item(champ, lower, item_count)
            cc = plc.precomputed_choices(
                str(champ), enemy, level,
                mana_fraction=mana_fraction, ult_up=ult_up,
                mode=lower, payload=payload, next_item=next_item,
            )
            choices = to_jsonable(cc)
            covered = bool(cc)

        log_precomputed_choices(
            mk, str(champ), enemy,
            choices=choices, band=band, mana_state=mana_state, cd_state=cd_state,
            covered=covered,
            native_action=coach.get("action") if isinstance(coach, dict) else None,
            native_choices=to_jsonable(parse_choices(coach)),
            game_time_s=gs.get("game_time_s"),
            level=level, item_count=item_count, path=path,
        )
    except Exception:
        return


def shadow_log_precomputed_build(coach: dict, lc: dict | None, mode_key: str,
                                 *, path=None) -> None:
    """Fail-soft HZ-C2 validation shadow-log. Records which durability VARIANT
    the precomputed HZ-B2 table (``core.precomputed_build_coach``) would
    recommend for this enemy comp - including whether the seed table covered the
    champion - to data/hz_build_shadow.jsonl, alongside live coaching. Never
    raises and has NO effect on live output. Fires only when the LIVECLIENT
    champion is present (a real in-game tick) - coach-champion presence alone
    would log a junk row on every idle tick (stale post-game coach file). A
    coverage MISS during a live game is recorded too. ``path`` overrides the
    jsonl target (test seam)."""
    try:
        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return
        # HZ-D4 live-game gate - same rationale as
        # shadow_log_precomputed_choices: only a real in-game liveclient
        # tick carries lc["champion"].
        if not (isinstance(lc, dict) and lc.get("champion")):
            return
        mk = str(mode_key or "").strip().lower()
        lower = _MODE_KEY_TO_LOWER.get(mk)
        if lower is None:
            return  # tft / brawl have no build table; do not score vs SR

        from core import precomputed_build_coach as pbc  # lazy import
        from core.build_order_variants import load_build_order_variants
        from core.hz_build_shadow import log_precomputed_build

        enemy_comp = [str(e) for e in (gs.get("enemy_comp") or [])]
        items = gs.get("items")
        item_count = len(items) if isinstance(items, list) else 0

        lean_tuple = pbc.comp_lean(enemy_comp)
        lean = lean_tuple[0] if lean_tuple else None

        payload = load_build_order_variants(lower)
        choices: list = []
        covered = False
        if lean is not None:
            cc = pbc.build_choices(
                str(champ), enemy_comp, lower,
                payload=payload, item_costs=_load_item_costs(),
                owned_count=item_count,
            )
            choices = to_jsonable(cc)
            covered = bool(cc)

        log_precomputed_build(
            mk, str(champ), enemy_comp, lean=lean,
            choices=choices, covered=covered,
            native_action=coach.get("action") if isinstance(coach, dict) else None,
            native_choices=to_jsonable(parse_choices(coach)),
            item_count=item_count, game_time_s=gs.get("game_time_s"), path=path,
        )
    except Exception:
        return
