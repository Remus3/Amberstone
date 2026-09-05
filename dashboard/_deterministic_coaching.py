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
    ``laning_choices`` makes ONE network call to the DS engine (:8860) per
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
import os
import threading
import time
from pathlib import Path

from core.coach_choices import (
    parse_choices,
    synthesize_simple_choices,
    to_jsonable,
)
from core.event_callouts import _sort_key as _callout_sort_key
from core.event_callouts import dragon_soul_callout, next_callouts
from core.heal_threat import heal_threat_callout
from core.laning_verdicts import laning_choices
from core.lead_projection import phase_for, project_lead
from core.macro_context import build_macro_context
from core.macro_decision_tree import evaluate as macro_tree_evaluate
from core.macro_response import macro_response_callout
from core.objective_playbook import playbook_callout

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

# Gold floor for "this is a completed legendary". The repo already carries two
# floors for the same notion - core.item_wpa._LEGENDARY_MIN_GOLD (2200) and
# core.personal_build_wr.LEGENDARY_GOLD_FLOOR (2000) - and MEASURED on the live
# 16.14.1 catalog both select the identical 324-item set, so the stricter value
# is used and nothing is given up by not importing either private constant.
_LEGENDARY_GOLD_FLOOR = 2200

# Tags that disqualify an owned item from being a power spike even when it clears
# the gold floor. Same three as core.item_wpa._EXCLUDE_TAGS. Boots carry the most
# weight: 171 of 173 champions hold boots at index 1 of their balanced build
# order, so any count that credits them calls shoes a power spike.
_NON_SPIKE_TAGS = frozenset({"Boots", "Consumable", "Trinket"})

# (ids, lowercased names) of every completed legendary; built once on demand.
_LEGENDARY_CATALOG_CACHE: tuple[frozenset[str], frozenset[str]] | None = None


def _current_patch() -> str:
    try:
        return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
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


def _legendary_catalog() -> tuple[frozenset[str], frozenset[str]]:
    """(item ids, lowercased display names) of every completed legendary.

    WHY not core.item_wpa.load_legendary_ids, which IS the repo's existing
    completed-legendary classifier (core/item_wpa.py:109): it gates on DDragon
    ``maps["<map_id>"]`` and additionally demands a component list or a depth.
    Arena's purchasable ids are flat 22-/44-prefixed aliases (223031 Infinity
    Edge, 226655 Luden's Echo, 443069 Hamstringer) that carry neither, so
    MEASURED on 16.14.1 ``load_legendary_ids(map_id=30)`` returns ZERO items -
    it cannot see an Arena inventory at all, and item-spike callouts are served
    for Arena. Map-gating is also the wrong question for an OWNED item: the shop
    already refuses to sell a map-illegal item, so a map filter here can only
    drop something the player provably holds.

    Same catalog + memoisation discipline as _load_item_costs. Fail-soft: an
    unreadable catalog yields empty sets, which reads as "nothing completed".
    """
    global _LEGENDARY_CATALOG_CACHE
    if _LEGENDARY_CATALOG_CACHE is not None:
        return _LEGENDARY_CATALOG_CACHE
    ids: set[str] = set()
    names: set[str] = set()
    patch = _current_patch()
    if patch:
        path = _DS_DATA / patch / "items.json"
        try:
            data = (json.loads(path.read_text(encoding="utf-8")).get("data") or {})
        except (OSError, ValueError):
            data = {}
        for iid, it in data.items():
            if not isinstance(it, dict):
                continue
            gold = it.get("gold")
            if not isinstance(gold, dict) or not gold.get("purchasable"):
                continue
            total = gold.get("total")
            if isinstance(total, bool) or not isinstance(total, (int, float)):
                continue
            if total < _LEGENDARY_GOLD_FLOOR:
                continue
            # A non-empty "into" means the item builds onward, so it is a
            # component and holding it is mid-purchase, not a completed spike.
            if it.get("into"):
                continue
            if set(it.get("tags") or ()) & _NON_SPIKE_TAGS:
                continue
            ids.add(str(iid))
            name = str(it.get("name") or "").strip().lower()
            if name:
                names.add(name)
    _LEGENDARY_CATALOG_CACHE = (frozenset(ids), frozenset(names))
    return _LEGENDARY_CATALOG_CACHE


def _owned_legendary_count(owned_item_ids: object,
                           owned_item_names: object) -> int:
    """How many COMPLETED LEGENDARIES the player owns - the power-spike count.

    WHY this is not _owned_build_item_count, the build-progress primitive the
    recall index uses: the two questions genuinely differ even though the same
    raw slot count broke both. A power spike is a fact about the player's combat
    stats, so a legendary bought OFF the recommended order still spikes and must
    count; and the build orders carry boots, which do not spike. Scoping this to
    the recommended build would both undercount off-order buys and call
    Berserker's Greaves a 1-item spike.

    Ids are authoritative (an id is unambiguous, a display name is not), with a
    name fallback for coach payloads that carry names only. Fail-soft: no usable
    signal -> 0, which reads as "nothing completed yet".
    """
    ids, names = _legendary_catalog()
    if isinstance(owned_item_ids, list) and owned_item_ids:
        return sum(1 for i in owned_item_ids
                   if i is not None and str(i).strip() in ids)
    if isinstance(owned_item_names, list) and owned_item_names:
        return sum(1 for n in owned_item_names
                   if isinstance(n, str) and n.strip().lower() in names)
    return 0


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


def _owned_build_item_count(champ: object, mode_lower: str,
                            owned_item_ids: object,
                            owned_item_names: object) -> int:
    """How many of ``champ``'s OWN build-order items the player already owns.

    WHY this exists rather than len(inventory): dashboard/_liveclient.py builds
    ``owned_items`` from EVERY inventory slot displayName - trinket, Health
    Potions, Refillable, biscuits included - so a raw len() is a slot count, not
    build progress. Indexing a curated 6-entry legendary order by that count
    names the wrong item as soon as a potion is held and falls off the end of the
    order entirely once six slots are used, which is what blanked the ARAM
    shadow ``reset_item`` column.

    Counts by item ID (an id is unambiguous; a display name is not), falling
    back to name membership when only names are available. The count is a
    MEMBERSHIP count, so an off-order ARAM purchase still advances the pointer
    instead of mis-indexing. Fail-soft: no usable signal -> 0 (nothing bought
    yet), which points the caller at the first item rather than at nothing.
    """
    orders = _load_build_orders(mode_lower)
    if not isinstance(champ, str) or not champ.strip():
        return 0
    champ_orders = orders.get(champ.strip())
    if not isinstance(champ_orders, dict):
        return 0
    order = champ_orders.get(_RECALL_BUCKET)
    if not isinstance(order, list):
        order = next((v for v in champ_orders.values() if isinstance(v, list)), None)
    if not isinstance(order, list) or not order:
        return 0

    if isinstance(owned_item_ids, list) and owned_item_ids:
        owned_ids = {str(i).strip() for i in owned_item_ids if i is not None}
        return sum(1 for iid in order if str(iid).strip() in owned_ids)

    # Name fallback: resolve the order's ids to display names via the same
    # memoised catalog, then match case-insensitively against the slot names.
    if isinstance(owned_item_names, list) and owned_item_names:
        costs = _load_item_costs()
        owned_names = {
            str(n).strip().lower() for n in owned_item_names
            if isinstance(n, str) and n.strip()
        }
        count = 0
        for iid in order:
            entry = costs.get(str(iid))
            if entry and entry[0] and entry[0].strip().lower() in owned_names:
                count += 1
        return count
    return 0


def _full_build_order(champ: object, mode_lower: str) -> list[str]:
    """Return the FULL ordered list of completed-item NAMES for ``champ``.

    Reuses the SAME memoised readers ``_next_build_item`` uses
    (``_load_build_orders`` + ``_load_item_costs``) over the ``balanced``
    bucket, but returns every resolvable item name in order instead of one
    index. The table is already curated (boots + legendaries, no ward / jungle
    items), so the names pass through as-is. Fail-soft: unknown champ / missing
    table / missing item catalog -> [] (so the caller leaves item_build "")."""
    if not isinstance(champ, str) or not champ.strip():
        return []
    orders = _load_build_orders(mode_lower)
    champ_orders = orders.get(champ.strip())
    if not isinstance(champ_orders, dict):
        return []
    order = champ_orders.get(_RECALL_BUCKET)
    if not isinstance(order, list):
        order = next((v for v in champ_orders.values() if isinstance(v, list)), None)
    if not isinstance(order, list) or not order:
        return []
    costs = _load_item_costs()
    names: list[str] = []
    for iid in order:
        entry = costs.get(str(iid))
        if entry and entry[0]:
            names.append(entry[0])
    return names

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


def _cv_served_enabled() -> bool:
    """RC2 P5.2 served-flip gate. DEFAULT-OFF: the local-CV laning override
    (``core.laning_cv_overrides``) drives the served A/B chips only when
    ``RC_LANING_CV_SERVED`` is truthy. The flip is operator/Gemini-gated on the
    ``tools/hz_shadow_report`` agreement delta (``docs/LIVE_GAME_GATED_SYNC.md``);
    OFF is byte-identical (the call into ``laning_choices`` is unchanged)."""
    return os.environ.get("RC_LANING_CV_SERVED", "0").strip().lower() in (
        "1", "true", "yes", "on")

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

# RC2 P5.7 (WS4): the stagnation WINDOW memory the pure core.macro_response is
# deliberately stateless about. (champion, mode_key) -> (lead_state, game_time_s
# when that state was entered). The resolver tracks how long the macro lead has
# been STABLE (no swing) and feeds the duration to stagnation_response, so the
# pure module stays testable with explicit timestamps.
_STATE_SINCE: dict[tuple[str, str], tuple[str, float]] = {}


def _reset_caches_for_tests() -> None:
    """Test seam: clear ALL module caches (TTL cache + warm-path last-good +
    inflight markers + the stagnation state-stability memory) so cases stay
    hermetic under the warm-path policy."""
    _CACHE.clear()
    _LAST_GOOD.clear()
    _STATE_SINCE.clear()
    with _REFRESH_LOCK:
        _REFRESH_INFLIGHT.clear()


def _state_stable_for_s(key: tuple[str, str], state: object,
                        game_time_s: object) -> float:
    """Seconds the macro lead ``state`` has been continuously held for ``key``.

    Resets to 0.0 on a state swing OR a new game (game_time regressed below the
    stored entry time). The WS4 stagnation window memory; fail-soft 0.0 on a
    non-numeric game_time (never raises)."""
    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        return 0.0
    st = state if isinstance(state, str) else "even"
    prev = _STATE_SINCE.get(key)
    if prev is None or prev[0] != st or gt < prev[1]:
        _STATE_SINCE[key] = (st, gt)
        return 0.0
    return gt - prev[1]


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

    # Turret-down events for the instant base-siege callout (SR + ARAM).
    turret_events = lc.get("turret_events")
    if isinstance(turret_events, list) and turret_events:
        gs["turret_events"] = turret_events

    # RM-124: MinionsSpawning anchor for the deterministic wave/cannon clock
    # (SR live event). Liveclient-only; absent -> omitted, wave_callout returns
    # None so no callout is synthesized without a real anchor.
    minion_events = lc.get("minion_events")
    if isinstance(minion_events, list) and minion_events:
        gs["minion_events"] = minion_events

    # RC2 P5.7 (WS4): neutral-objective kill events for the lost-objective macro
    # response. Liveclient-only (SR live events); absent -> omitted, the pure
    # macro_response handles the gap.
    objective_events = lc.get("objective_events")
    if isinstance(objective_events, list) and objective_events:
        gs["objective_events"] = objective_events

    # Per-team item-id pools (for the heal-threat nudge) come only from the
    # liveclient scoreboard - the coach dict never carries the other players'
    # items. Absent / empty -> omitted, heal_threat_callout handles the gap.
    enemy_item_ids = lc.get("enemy_item_ids")
    if isinstance(enemy_item_ids, list) and enemy_item_ids:
        gs["enemy_item_ids"] = enemy_item_ids
    ally_item_ids = lc.get("ally_item_ids")
    if isinstance(ally_item_ids, list) and ally_item_ids:
        gs["ally_item_ids"] = ally_item_ids

    # RC2 P5.2: my HP fraction (lc-first) for the CV override's low-HP layer.
    # Additive - omitted when no HP signal; only the gated served path reads it.
    hp_fraction = _hp_fraction(coach, lc)
    if hp_fraction is not None:
        gs["hp_fraction"] = hp_fraction

    return gs


def _stamp_vision_summary(gs: dict) -> None:
    """Stamp the fog-model ``summary`` counts onto ``gs`` for the RC2 P5.5
    objective playbook's CV upgrades + the cache sig, AND (ZOI Wave-2
    agent-macro v0) the compact per-enemy fog list ``fog_enemies`` the
    macro decision tree reads (champion / visible / is_dead /
    missing_for_s / last_seen_zone - the core.vision_tracker track
    subset). Read ONCE per compute (the spec contract; cheap -
    ``core.vision_tracker`` writes vision_state.json atomically).
    Additive + fail-soft: omitted on any error / absent file."""
    try:
        from core.laning_cv_overrides import load_vision_state  # lazy
        vs = load_vision_state()
        summary = vs.get("summary")
        if isinstance(summary, dict) and summary:
            gs["vision_summary"] = summary
        enemies = vs.get("enemies")
        if isinstance(enemies, dict) and enemies:
            fog = []
            for entry in enemies.values():
                if not isinstance(entry, dict):
                    continue
                fog.append({
                    "champion": str(entry.get("champion") or ""),
                    "visible": bool(entry.get("visible")),
                    "is_dead": bool(entry.get("is_dead")),
                    "missing_for_s": entry.get("missing_for_s"),
                    "last_seen_zone": str(entry.get("last_seen_zone") or ""),
                })
            if fog:
                gs["fog_enemies"] = fog
    except Exception:  # noqa: BLE001
        pass


def _vision_sig(gs: dict) -> tuple[int, int, int]:
    """The (visible, missing, dead) enemy counts for the cache sig so a CV
    transition near an objective re-computes the playbook row. (0,0,0) when no
    fog summary is stamped."""
    vs = gs.get("vision_summary")
    if not isinstance(vs, dict):
        return (0, 0, 0)

    def _vc(key: str) -> int:
        v = vs.get(key)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    return (_vc("visible_count"), _vc("missing_count"), _vc("dead_count"))


def _fog_sig(gs: dict) -> tuple:
    """Per-enemy fog key for the cache sig (ZOI Wave-2 agent-macro v0).

    The macro decision tree reads MORE than the (visible, missing, dead)
    counts _vision_sig carries: per-enemy last_seen_zone and the MIA
    duration thresholds. Same sig-completeness rule as item ids / inhib /
    objective events - a zone flip or a threshold-crossing MIA duration
    must re-compute instead of serving the stale macro row. missing_for_s
    is bucketed to 10s so the sig does not churn every tick (the 5s
    game-time bucket already bounds entry lifetime). () when no fog is
    stamped; fail-soft on malformed entries."""
    fog = gs.get("fog_enemies")
    if not isinstance(fog, list):
        return ()
    out = []
    for e in fog:
        if not isinstance(e, dict):
            continue
        m = e.get("missing_for_s")
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            m_bucket = int(float(m) // 10.0)
        else:
            m_bucket = -1
        out.append((
            str(e.get("champion") or ""),
            bool(e.get("visible")),
            bool(e.get("is_dead")),
            str(e.get("last_seen_zone") or ""),
            m_bucket,
        ))
    return tuple(sorted(out))


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
    # RC2 P5.7 (WS4): objective kill events drive the lost-objective macro row,
    # so they must change the sig too (same completeness rule) - key on
    # (name, killer_team, down_at_s) so a fresh enemy objective kill re-computes
    # the row mid-bucket instead of serving the stale callouts.
    obj_events = gs.get("objective_events")
    obj_events_key = (
        tuple(sorted(
            f"{e.get('name')}:{e.get('killer_team')}:{e.get('down_at_s')}"
            for e in obj_events if isinstance(e, dict)))
        if isinstance(obj_events, list) else ()
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
        obj_events_key,
        enemy_items_key,
        ally_items_key,
        _vision_sig(gs),
        # ZOI Wave-2 agent-macro v0: the macro tree reads per-enemy fog
        # (zone + MIA duration), so a fog change must invalidate the cache
        # (sig-completeness rule) - the counts alone miss zone flips.
        _fog_sig(gs),
    )


def _evict_if_full() -> None:
    """Drop the oldest cache entry when the cache exceeds _CACHE_MAX, so a long
    session can't grow it unbounded."""
    if len(_CACHE) <= _CACHE_MAX:
        return
    # Oldest by stored monotonic timestamp.
    oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
    _CACHE.pop(oldest_key, None)


def _compute_uncached(gs: dict, mode_key: str, zoi: dict | None = None) -> dict:
    """The actual generator fan-out (no cache). Calls laning_choices (network
    via matchup), next_callouts (pure), project_lead (pure). Returns the merged
    dict. Wrapped by compute_deterministic in a try/except so a raise here can
    never escape.

    ``zoi`` (ZOI Wave-2 agent-macro): the district-enrichment seam for the
    macro decision tree. v0 is fog-only and IGNORES the zoi content - the
    kwarg is threaded through to build_macro_context/evaluate now so the
    v1 district wave only changes the pure modules, not this wiring."""
    mk = str(mode_key or "").strip().lower()
    upper = _MODE_KEY_TO_UPPER.get(mk)
    lower = _MODE_KEY_TO_LOWER.get(mk)
    if upper is None or lower is None:
        # tft / brawl / unknown have no laning / build / SR-objective model;
        # serve empty rather than silently scoring them against the SR tables
        # (and skip the needless DS matchup call every tick).
        return dict(_EMPTY_RESULT)

    # choices (deterministic A/B from the DS matchup engine). RC2 P5.2: when the
    # served-flip gate is ON, fold the live-CV laning override onto the chips;
    # OFF keeps the call byte-identical (so the static path is unchanged).
    if _cv_served_enabled():
        choices = laning_choices(
            gs, mode=upper, apply_cv=True, hp_fraction=gs.get("hp_fraction"),
        )
    else:
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
    gold = gs.get("gold")
    # Two DIFFERENT item counts, because the two consumers ask different
    # questions. Neither may be the raw inventory slot count: the liveclient slot
    # list carries the trinket + potions, so a raw len() named the wrong build
    # item once a potion was held and told a player holding nothing but a trinket
    # and a potion they had hit a 2-item power spike.
    #
    # Build order -> BUILD PROGRESS (which of my own core items do I already own).
    # Item spike  -> COMPLETED LEGENDARIES (a fact about my combat stats, so an
    #                off-order legendary counts and boots do not).
    build_progress = _owned_build_item_count(
        gs.get("my_champion"), lower, gs.get("my_item_ids"), items,
    )
    nxt = _next_build_item(gs.get("my_champion"), lower, build_progress)
    next_name = nxt[0] if nxt else None
    next_cost = nxt[1] if nxt else None
    legendary_count = _owned_legendary_count(gs.get("my_item_ids"), items)
    # RM-124: the wave/cannon clock stays gated OFF (do-not-flip-blind) until
    # the provisional cadence table is validated against one real game. Flip
    # RC_WAVE_CALLOUT=1 to emit it live once validated.
    _enable_wave = os.environ.get("RC_WAVE_CALLOUT", "0") == "1"
    callouts = next_callouts(
        lower, gt, lvl, legendary_count, max_n=3,
        gold=gold, next_item_name=next_name, next_item_cost=next_cost,
        inhib_events=gs.get("inhib_events"),
        turret_events=gs.get("turret_events"),
        objective_events=gs.get("objective_events"),
        minion_events=gs.get("minion_events"),
        enable_wave=_enable_wave,
    )
    if not isinstance(callouts, list):
        callouts = []

    # lead_projection (pure diff). Computed BEFORE the playbook so the playbook
    # row can read the macro state (ahead/even/behind).
    lead = project_lead(gs, mode=upper)

    # RC2 P5.5 (WS3): the objective playbook row joins the objective schedule +
    # the lead read into one kind="playbook" directive for the soonest
    # contestable objective. Additive (no Haiku replacement, no flip gate) and
    # eta-sorted in beside its schedule row.
    play = playbook_callout(callouts, lead, gs.get("vision_summary"), phase_for(gt))
    if play is not None:
        callouts = sorted([*callouts, play], key=_callout_sort_key)

    # RC2 P5.7 (WS4): lost-objective / stagnation reactive macro advisory. Like
    # the heal nudge it is a standing row (eta_s None); when it fires it is a
    # higher-priority reactive directive (you just lost baron / the game has
    # stalled), so it takes the single trailing advisory slot AHEAD of the heal
    # nudge (the two rarely co-fire). SR-only (objective_events + the side-lane
    # stagnation calls are SR concepts). Additive (no Haiku replacement, no flip
    # gate). The stagnation window duration comes from the resolver state memory.
    macro = None
    dt_macro = None
    if lower == "sr":
        lead_state = lead.get("state") if isinstance(lead, dict) else None
        warm_key = (str(gs.get("my_champion") or ""), str(mode_key or ""))
        macro = macro_response_callout(
            gs.get("objective_events"), lead, gt, gs.get("inhib_events"),
            stable_for_s=_state_stable_for_s(warm_key, lead_state, gt),
        )
        # ZOI Wave-2 agent-macro (fog-only v0): the deterministic macro
        # decision tree (core.macro_decision_tree, registry-of-pure-
        # predicates) over the per-enemy fog state + objective schedule.
        # SR-only like the WS4 row above. A live objective-danger/gank read
        # outranks the WS4 stagnation row in the advisory slot (see the
        # priority chain below). Fail-soft: any error -> no row, output
        # byte-identical to the pre-tree path.
        try:
            ctx = build_macro_context(
                "sr", gt,
                enemies=gs.get("fog_enemies"),
                objective_events=gs.get("objective_events"),
                lead=lead, zoi=zoi,
            )
            dt_macro = macro_tree_evaluate(ctx, zoi=zoi)
            if not isinstance(dt_macro, dict):
                dt_macro = None
        except Exception:  # noqa: BLE001
            dt_macro = None

    # Heal-threat / anti-heal nudge (pure set-membership over the live item
    # pools). Standing advisory (eta_s None) - keep the 2 most-urgent timed
    # rows and append ONE advisory as the 3rd so it is always visible when it
    # fires without crowding out an active "Baron NOW". The WS4 macro response
    # wins the slot over the heal nudge when both fire. When neither fires, cap
    # to 3 so the playbook splice cannot grow the list past the dashboard's
    # 3-row density (the overlay clamps to 2).
    heal = heal_threat_callout(
        gs.get("enemy_comp"), gs.get("enemy_item_ids"),
        gs.get("ally_item_ids"), mode=lower,
    )
    # RC2 L2: dragon soul-point row (SR-only state read over objective_events).
    # A standing advisory like macro/heal; it takes the single trailing slot
    # below a fresh lost-objective macro directive but ABOVE the heal nudge - a
    # soul-point inflection outweighs an item-counter cue. Naturally SR-only
    # (no dragons feed objective_events off the Rift), gated for symmetry.
    soul = dragon_soul_callout(gs.get("objective_events")) if lower == "sr" else None
    # Advisory-slot priority: decision_tree > ws4_macro > soul > heal. The
    # kind="macro" decision-tree row is a LIVE objective-danger/gank read,
    # so it outranks the WS4 stagnation/lost-objective response; when it is
    # None the chain (and the served bytes) are unchanged.
    advisory = dt_macro or macro or soul or heal
    if advisory is not None:
        callouts = callouts[:2] + [advisory]
    else:
        callouts = callouts[:3]

    # ZOI map-control callout from the minimap blob dots (item 567 slice 3).
    # Appended here inside _compute_uncached so the callouts list is complete
    # BEFORE it enters the cache - avoids mutation-based accumulation (the
    # external append in _state_builder.py mutated the cached dict, causing
    # 5-7x duplication of the map_control row across ticks within the 3s TTL).
    # SR-only: the quadrant labels (bot river / dragon, top river, etc.) are
    # Summoner's Rift map concepts with no ARAM equivalent (Howling Abyss is a
    # single lane with no river, no dragon pit, no top/bot split).
    if zoi is not None and lower == "sr":
        try:
            from core.zoi_influence import zoi_callout
            co = zoi_callout(zoi)
            if co is not None:
                callouts = callouts + [co]
        except Exception:  # noqa: BLE001
            pass

    return {
        "choices": choices_json,
        "callouts": callouts,
        "lead_projection": lead if isinstance(lead, dict) else {},
    }


def compute_deterministic(coach: dict, lc: dict | None, mode_key: str,
                          zoi: dict | None = None) -> dict:
    """Return ``{choices, callouts, lead_projection}`` for /api/state.

    TTL-cached on a coarse game-state signature (3.0s) so the DS matchup call
    inside laning_choices is not hammered by the 500ms /api/state poll. Wholly
    fail-soft: any exception yields the all-empty result, never raises.

    Args:
        coach: the coach JSON dict (may carry champion/level/kda/cs/gold/...).
        lc: the liveclient_summary() dict (enemy_team / owned_items / ...) or
            None when not in a game.
        mode_key: dashboard mode_key (sr/aram/arena/client/game/...).
        zoi: the _state_builder zoi block ({bubbles, demarcation,
            map_control, ...}) or None. ZOI Wave-2 agent-macro seam: v0 is
            fog-only and IGNORES the content (zoi=None output is byte-
            identical), but the kwarg lands now so the district-enriched v1
            only touches the pure modules.

    Returns:
        dict with keys ``choices`` (list[dict]), ``callouts`` (list[dict]),
        ``lead_projection`` (dict). ``choices`` is the DETERMINISTIC laning
        source - empty when the engine is down or no enemy is resolvable, in
        which case build_state falls back to the coach's native / synth choices.
    """
    try:
        gs = _build_game_state(coach, lc, mode_key)
        # RC2 P5.5: read the fog summary once here so the cache sig + the
        # objective playbook (in _compute_uncached) share one vision read.
        _stamp_vision_summary(gs)
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
            result = _compute_uncached(gs, mode_key, zoi=zoi)
            _store_result(sig, warm_key, result)
            return result

        # Warm path: serve the last good result NOW, refresh in background.
        _spawn_refresh(sig, warm_key, gs, mode_key, zoi=zoi)
        return hit[1] if hit is not None else last
    except Exception:  # noqa: BLE001
        return dict(_EMPTY_RESULT)


def _store_result(sig: tuple, warm_key: tuple[str, str], result: dict) -> None:
    _CACHE[sig] = (time.monotonic(), result)
    _LAST_GOOD[warm_key] = result
    if len(_LAST_GOOD) > _CACHE_MAX:
        _LAST_GOOD.pop(next(iter(_LAST_GOOD)), None)
    _evict_if_full()


def _spawn_refresh(sig: tuple, warm_key: tuple[str, str], gs: dict,
                   mode_key: str, zoi: dict | None = None) -> None:
    """Single-flight background recompute. Concurrent /api/state + SSE
    builders that miss the same sig must not stack matchup calls."""
    with _REFRESH_LOCK:
        if sig in _REFRESH_INFLIGHT:
            return
        _REFRESH_INFLIGHT.add(sig)

    def _run() -> None:
        try:
            result = _compute_uncached(gs, mode_key, zoi=zoi)
            _store_result(sig, warm_key, result)
        except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001
        return (det or {}).get("choices") or []


def resolve_coach_fields(coach: dict, det: dict | None, lc: dict | None,
                          mode_key: str) -> dict[str, str]:
    """Synthesize action, immediate, fight_rule, risk from deterministic data.

    These four coach-text fields normally come from the Haiku LLM coach via
    coaching_data.json. When the deterministic path is active (practice tool,
    DS engine up but no Haiku call), the Haiku coach is bypassed and these
    fields are blank in /api/state. This synthesizer fills them from the
    already-computed deterministic surfaces (callouts, lead_projection, enemy
    CC threat) so the overlay's coach-text rows never go blank.

    The callout with the highest priority (index 0) provides ``action`` and
    ``immediate``. ``risk`` is derived from the lead projection state (ahead /
    even / behind). ``fight_rule`` is derived from the enemy CC threat data
    when available, else from the lead state.

    Returns:
        dict with keys action, immediate, fight_rule, risk (all str, never
        None). Fields are empty strings when no deterministic data is available.

    Fail-soft: any error yields the all-empty dict; never raises.
    """
    det = det if isinstance(det, dict) else {}
    lc = lc if isinstance(lc, dict) else {}

    # --- action + immediate: highest-priority callout line, else A-choice ---
    action = ""
    callouts = det.get("callouts")
    if isinstance(callouts, list) and callouts:
        first = callouts[0]
        if isinstance(first, dict):
            line = first.get("line")
            if isinstance(line, str) and line.strip():
                action = line.strip()
    if not action:
        choices = det.get("choices")
        if isinstance(choices, list) and choices:
            first_c = choices[0]
            if isinstance(first_c, dict):
                label = first_c.get("label")
                if isinstance(label, str) and label.strip():
                    action = label.strip()
    # When the coach already filled action (e.g. "HOLD"), leave immediate
    # alone even if blank - the coach intentionally retired that slot (ARAM
    # coach: "Do NOT emit an Immediate prose field"). Only synthesize
    # immediate when the action field itself needed deterministic fallback.
    immediate = action if not (coach.get("action") or "").strip() else ""

    # --- risk: from lead projection state ---
    lead = det.get("lead_projection")
    lead_state = "even"
    if isinstance(lead, dict):
        lead_state = lead.get("state", "even")
    risk_map = {"ahead": "LOW", "even": "MEDIUM", "behind": "HIGH"}
    risk = risk_map.get(lead_state, "MEDIUM")

    # --- fight_rule: from enemy CC threat, else lead-state heuristic ---
    fight_rule = ""
    try:
        enemies = lc.get("enemy_team")
        if isinstance(enemies, list) and enemies:
            mk = str(mode_key or "").strip().lower()
            mode_upper = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}.get(
                mk, "SR")
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            cc = enemy_cc_threat_line(enemies, mode_upper) or ""
            if cc:
                fight_rule = cc
    except Exception:  # noqa: BLE001
        pass

    if not fight_rule:
        rules = {
            "ahead": "FAIR FIGHT - press advantage, trade on cooldowns",
            "even": "FAIR FIGHT - trade only on cooldowns, avoid coinflips",
            "behind": "PICK ONLY - fight with your team, avoid solo engages",
        }
        fight_rule = rules.get(lead_state, rules["even"])

    return {
        "action": action,
        "immediate": immediate,
        "fight_rule": fight_rule,
        "risk": risk,
    }


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
    except Exception:  # noqa: BLE001
        return


def _shadow_schema_keys(module, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """The comparison columns a shadow module records, read from that module.

    WHY: the two live-artifact readers below each used to hardcode their own key
    tuple, and both silently drifted behind the shadow modules that define the
    row schema - the ARAM reader never read choices / item_extra / objective and
    the Arena reader never read choices. A column the reader refuses to read can
    NEVER appear on the live side, which made the shadow report show a
    structurally impossible "Haiku never emits choices" (both=0, live_only=0)
    when the coach emits it just fine. Deriving the reader from the WRITER's
    schema is the direction that cannot rot: a key added to the shadow row is
    captured on both sides at once.
    """
    keys = getattr(module, "_BLOCK_KEYS", None)
    if isinstance(keys, (tuple, list)) and keys:
        return tuple(str(k) for k in keys)
    return fallback


def _live_aram_block(path: Path | None = None) -> dict:
    """Read the live ARAM Haiku block from the artifact.

    Returns the comparison columns core.aram_coach_shadow records, read from
    data/aram_coaching_data.json (the live coach writes many more fields).
    Fail-soft: a missing / unreadable / malformed artifact -> {} (then
    log_aram_coach normalizes to all-empty). Never raises. ``path`` overrides
    the artifact location (test seam)."""
    target = path if path is not None else (
        Path(__file__).resolve().parent.parent / "data" / "aram_coaching_data.json"
    )
    try:
        data = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    from core import aram_coach_shadow  # lazy
    keys = _shadow_schema_keys(aram_coach_shadow, (
        "action", "fight_rule", "risk", "reset_item",
        "item_build", "item_build_reasons", "choices",
        "item_extra", "objective",
    ))
    return {k: data.get(k) for k in keys if k in data}


def _live_arena_block(path: Path | None = None) -> dict:
    """Read the live Arena Haiku block (the seven coach fields) from the
    artifact.

    Returns the comparison columns core.arena_coach_shadow records, read from
    data/arena_coaching_data.json (the live coach writes many more fields).
    Fail-soft: a missing / unreadable / malformed artifact -> {} (then
    log_arena_coach normalizes to all-empty). Never raises. ``path`` overrides
    the artifact location (test seam)."""
    target = path if path is not None else (
        Path(__file__).resolve().parent.parent / "data" / "arena_coaching_data.json"
    )
    try:
        data = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    from core import arena_coach_shadow  # lazy
    keys = _shadow_schema_keys(arena_coach_shadow, (
        "action", "round_strategy", "fight_rule", "augment_advice",
        "anvil_advice", "target_priority", "risk", "choices",
    ))
    return {k: data.get(k) for k in keys if k in data}


def shadow_log_aram_coach(coach: dict, lc: dict | None, mode_key: str,
                          *, path=None, live_path=None) -> None:
    """Fail-soft Stage 2 ARAM deterministic-vs-Haiku shadow-log.

    Assembles the deterministic ARAM block (core.aram_deterministic_coach.
    build_block) from the available dashboard state + the existing ARAM build /
    anti-tank / heal-threat surfaces, reads the live Haiku block from
    data/aram_coaching_data.json, and appends ONE record per distinct coarse
    state to data/aram_coach_shadow.jsonl so the operator can eyeball the two
    side-by-side. SHADOW-ONLY: NEVER mutates coach / lc / any served field,
    never raises, has NO effect on /api/state output.

    Fires only for an ARAM in-game tick - mode_key == "aram" AND lc["champion"]
    present (the item-386 live-game gate; the stale coach file keeps `champion`
    after a game ends, so coach-side presence alone is not enough). ``path``
    overrides the jsonl target and ``live_path`` the live-artifact source (test
    seams).

    PARTIAL-READ (by design): wave_pct is vision-only and usually ABSENT
    server-side, so decide_action just gets None (no tier shift); a missing
    enemy CC line / build table degrades the corresponding block fields to
    empty inside build_block. The assembler works from whatever is present.
    """
    try:
        mk = str(mode_key or "").strip().lower()
        if mk != "aram":
            return
        # Live-game gate (item-386): only a real in-game liveclient tick carries
        # lc["champion"]. Cheap pre-check before any engine read.
        if not (isinstance(lc, dict) and lc.get("champion")):
            return

        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return
        enemy_comp = [str(e) for e in (gs.get("enemy_comp") or [])]

        # hp_pct: prefer a direct coach hp_pct, else derive from the 0..1
        # hp_fraction _build_game_state already resolved (lc hp / hp_max).
        hp_pct = None
        if isinstance(coach, dict):
            raw = coach.get("hp_pct")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                hp_pct = float(raw)
        if hp_pct is None:
            frac = gs.get("hp_fraction")
            if isinstance(frac, (int, float)) and not isinstance(frac, bool):
                hp_pct = float(frac) * 100.0

        # Enemy-CC threat line (drives fight_rule / risk). Fail-soft to "".
        cc_line = ""
        try:
            from core.enemy_cc_threat_context import enemy_cc_threat_line  # lazy
            cc_line = enemy_cc_threat_line(enemy_comp, "ARAM") or ""
        except Exception:  # noqa: BLE001
            cc_line = ""

        # Next build item (anchors the no-recall reset line). Reuses the same
        # balanced-order reader the recall callout uses; None when unknown.
        items = gs.get("items")
        item_count = len(items) if isinstance(items, list) else 0
        # Index the build order by BUILD PROGRESS, not by inventory slots: the
        # liveclient slot list carries the trinket + potions, so a raw len()
        # over-indexes a 6-entry order and blanks reset_item outright once six
        # slots are in use. item_count stays the raw slot count because
        # item_extra is a 7th-SLOT question, not a build-progress one.
        build_progress = _owned_build_item_count(
            champ, "aram", gs.get("my_item_ids"), items,
        )
        nxt = _next_build_item(champ, "aram", build_progress)
        next_name = nxt[0] if nxt else None
        next_cost = nxt[1] if nxt else None

        # Anti-tank hint reason (ARAM). Fail-soft to "".
        antitank_hint = ""
        try:
            from core.ds_antitank_hint import build_antitank_hint  # lazy
            ah = build_antitank_hint(str(champ), enemy_comp, mode="ARAM")
            if isinstance(ah, dict):
                antitank_hint = ah.get("hint") or ""
        except Exception:  # noqa: BLE001
            antitank_hint = ""

        # Heal-threat / anti-heal reason (ARAM). Fail-soft to "".
        heal_line = ""
        try:
            from core.heal_threat import heal_threat_callout  # lazy
            ht = heal_threat_callout(
                enemy_comp, gs.get("enemy_item_ids"),
                gs.get("ally_item_ids"), mode="aram",
            )
            if isinstance(ht, dict):
                heal_line = ht.get("line") or ""
        except Exception:  # noqa: BLE001
            heal_line = ""

        # The deterministic build path: fill item_build from the SAME curated
        # ARAM build-order table _next_build_item reads (the full ordered
        # completed-item list, not just the next index). build_block joins the
        # first 4-6 names and folds the anti-tank + heal reasons into
        # item_build_reasons. Fail-soft: any failure -> [] so item_build stays
        # "" (unchanged shadow behavior). Does NOT touch reset_item /
        # _next_build_item logic above.
        try:
            build_order = _full_build_order(champ, "aram")
        except Exception:  # noqa: BLE001
            build_order = []

        # Per-item build reasons. The deterministic source is the ARAM
        # item-interaction cue corpus - the SAME comp-shape + purchase-timing
        # snapshot the live coach folds in as additive context
        # (coaches/aram_coach.py:281), so reading it here is non-circular: it is
        # a precomputed corpus, not a Haiku output. Without this the ONLY reason
        # source was the anti-tank / anti-heal hints, which is why the shadow
        # report showed an empty deterministic item_build_reasons on ~1050 ticks
        # where Haiku produced a full map.
        # A cue the corpus does not carry renders CUE_SENTINEL ("-"); recording
        # that would manufacture fake coverage in the very report this is meant
        # to make honest, so sentinels are dropped. The corpus is a TRACKED
        # artifact as of 2026-07-30 - it used to be gitignored, which made this
        # whole reason source machine-local and silently empty everywhere else
        # (the except below degrades to {} without a log line). It is now pinned
        # by tests/test_aram_item_interaction_snapshot_tracked.py; the fail-soft
        # path stays because a corrupt file must still not kill a tick.
        cue_reasons: dict = {}
        try:
            from core.aram_item_interaction_context import (  # lazy
                CUE_SENTINEL,
                item_interaction_cues,
            )
            raw_cues = item_interaction_cues(
                enemy_comp, gs.get("game_time_s"), build_order, game_mode="ARAM",
            )
            if isinstance(raw_cues, dict):
                cue_reasons = {
                    str(k): v for k, v in raw_cues.items()
                    if isinstance(v, str) and v.strip()
                    and v.strip() != CUE_SENTINEL
                }
        except Exception:  # noqa: BLE001
            cue_reasons = {}
        # Tower HP drives the deterministic objective; owned-item count drives
        # item_extra. Tower HP is vision-only INPUT state echoed on the coach
        # dict (NOT a Haiku output field, so reading it is non-circular) and is
        # often absent server-side, like wave_pct - build_block coerces fail-
        # soft, so an absent / non-numeric value degrades objective to "".
        my_tower_hp = coach.get("my_tower_hp") if isinstance(coach, dict) else None
        enemy_tower_hp = coach.get("enemy_tower_hp") if isinstance(coach, dict) else None
        from core.aram_deterministic_coach import build_block  # lazy
        det_block = build_block(
            hp_pct=hp_pct,
            wave_pct=None,  # vision-only; absent server-side -> no tier shift
            low_enemy_count=None,
            cc_threat_line=cc_line,
            build_order=build_order,
            item_build_reasons=cue_reasons,
            next_item_name=next_name,
            next_item_remaining_gold=next_cost,
            antitank_hint=antitank_hint,
            heal_threat_line=heal_line,
            owned_item_count=item_count,
            my_tower_hp=my_tower_hp,
            enemy_tower_hp=enemy_tower_hp,
        )

        live_block = _live_aram_block(live_path)

        from core.aram_coach_shadow import log_aram_coach  # lazy
        log_aram_coach(det_block, live_block, lc, mk, path=path)
    except Exception:  # noqa: BLE001
        return


def shadow_log_arena_coach(coach: dict, lc: dict | None, mode_key: str,
                           *, path=None, live_path=None) -> None:
    """Fail-soft Stage 2 Arena deterministic-vs-Haiku shadow-log.

    Assembles the deterministic Arena block (core.arena_deterministic_coach.
    build_block) from the available dashboard state + the existing Arena
    per-round item advisor / CC-threat / frontline surfaces, reads the live
    Haiku block from data/arena_coaching_data.json, and appends ONE record per
    distinct coarse state to data/arena_coach_shadow.jsonl so the operator can
    eyeball the two side-by-side. SHADOW-ONLY: NEVER mutates coach / lc / any
    served field, never raises, has NO effect on /api/state output.

    Fires only for an Arena in-game tick - mode_key == "arena" AND
    lc["champion"] present (the item-386 live-game gate; the stale coach file
    keeps `champion` after a game ends, so coach-side presence alone is not
    enough). ``path`` overrides the jsonl target and ``live_path`` the
    live-artifact source (test seams).

    PARTIAL-READ (by design): low_opp_count has NO live source, so
    decide_action just gets None (the ALL IN promotion stays dormant); a
    missing CC line / frontline read / build DB degrades the corresponding
    block fields to empty inside build_block. The assembler works from
    whatever is present.
    """
    try:
        mk = str(mode_key or "").strip().lower()
        if mk != "arena":
            return
        # Live-game gate (item-386): only a real in-game liveclient tick carries
        # lc["champion"]. Cheap pre-check before any engine read.
        if not (isinstance(lc, dict) and lc.get("champion")):
            return

        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return

        # hp_pct: prefer a direct coach hp_pct, else derive from the 0..1
        # hp_fraction _build_game_state already resolved (lc hp / hp_max).
        hp_pct = None
        if isinstance(coach, dict):
            raw = coach.get("hp_pct")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                hp_pct = float(raw)
        if hp_pct is None:
            frac = gs.get("hp_fraction")
            if isinstance(frac, (int, float)) and not isinstance(frac, bool):
                hp_pct = float(frac) * 100.0

        camp_phase = coach.get("camp_phase") if isinstance(coach, dict) else None
        round_label = coach.get("round") if isinstance(coach, dict) else None
        alive_teams = coach.get("alive_teams") if isinstance(coach, dict) else None

        # Alive opponents: the SAME filter the live per-round item advisor uses
        # (coaches/arena_coach.py) - skip self, partner, and dead cells; fall
        # back to the liveclient enemy_comp when no scoreboard is present.
        alive_opps: list[str] = []
        teams = coach.get("teams") if isinstance(coach, dict) else None
        if isinstance(teams, list):
            for t in teams:
                if not isinstance(t, dict):
                    continue
                if t.get("is_you") or t.get("is_partner") or t.get("is_dead"):
                    continue
                name = t.get("name")
                if name:
                    alive_opps.append(str(name))
        if not alive_opps:
            alive_opps = [str(e) for e in (gs.get("enemy_comp") or [])]

        # Enemy-CC threat line (drives fight_rule / risk). Fail-soft to "".
        cc_line = ""
        try:
            from core.enemy_cc_threat_context import enemy_cc_threat_line  # lazy
            cc_line = enemy_cc_threat_line(alive_opps, "ARENA") or ""
        except Exception:  # noqa: BLE001
            cc_line = ""

        # Frontline classification for the kill-order line. Per-name guarded so
        # one unresolvable name cannot blank the rest. Fail-soft to empty set.
        frontline_names: set[str] = set()
        try:
            from core.aram_comp_verdict import compute_factors  # lazy
            for name in alive_opps:
                try:
                    if compute_factors([name]).get("frontline_count"):
                        frontline_names.add(name)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            frontline_names = set()

        # Not-yet-built item names via the live per-round Arena advisor (dedup
        # vs owned + tank/heal re-rank; NAME strings). gs["items"] carries
        # display names (arena coach items / liveclient owned_items are both
        # name lists); a dict entry degrades to its displayName just in case.
        build_remaining = None
        try:
            owned_names = []
            for it in (gs.get("items") or []):
                if isinstance(it, dict):
                    it = it.get("displayName") or it.get("name")
                if it:
                    owned_names.append(str(it))
            gold = gs.get("gold")
            try:
                gold_i = int(gold)
            except (TypeError, ValueError):
                gold_i = 0
            hp_i = int(hp_pct) if hp_pct is not None else 100
            from coaches._arena_item_advisor import recompute_arena_build  # lazy
            build_remaining = recompute_arena_build(
                champion=str(champ),
                current_items=owned_names,
                gold=gold_i,
                alive_opponents=alive_opps,
                hp_pct=hp_i,
            )
        except Exception:  # noqa: BLE001
            build_remaining = None

        from core.arena_deterministic_coach import build_block  # lazy
        det_block = build_block(
            hp_pct=hp_pct,
            camp_phase=camp_phase,
            low_opp_count=None,  # no live source; ALL IN promotion dormant
            alive_teams=alive_teams,
            cc_threat_line=cc_line,
            alive_opponents=alive_opps,
            frontline_names=frontline_names,
            build_remaining=build_remaining,
        )

        live_block = _live_arena_block(live_path)

        from core.arena_coach_shadow import log_arena_coach  # lazy
        log_arena_coach(
            det_block, live_block, lc, mk, round_label=round_label, path=path,
        )
    except Exception:  # noqa: BLE001
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


def _hp_fraction(coach: dict, lc: dict | None) -> float | None:
    """Best-effort current HP as a 0..1 fraction of max, or None.

    The activePlayer hp / hp_max is the truth (lc-first), with a coach fallback.
    Returns None when no HP signal is present - the CV override's low-HP layer
    then simply does not fire (RC2 P5.1). Fail-soft, mirrors _mana_fraction."""
    for src in (lc, coach):
        if not isinstance(src, dict):
            continue
        cur = src.get("hp")
        mx = src.get("hp_max") or src.get("maxHealth")
        try:
            if cur is not None and mx:
                f = float(cur) / float(mx)
                if 0.0 <= f <= 1.5:
                    return f
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return None


def _native_laning_action(coach) -> str | None:
    """The Haiku laning verdict to score against the precompute for the HZ-C1
    agreement gate. The coach top-line ``action`` carries the laning verdict
    when alive ("TRADE" / "FALL BACK" / "HOLD"), but on some alive ticks it is
    blank (whitespace/empty), the intent only living in the ``immediate`` prose.
    When ``action`` is blank, fall back to ``immediate`` so an alive laning tick
    still captures a native signal instead of logging None (cycle-53: alive
    ticks logged an empty native_action, starving the agreement sample). A
    dead/disabled overlay action ("WAIT RESPAWN" / "COACHING DISABLED") is
    non-blank, so it is preserved verbatim and excluded downstream by the
    report's non-laning-state guard (never overridden by ``immediate``)."""
    if not isinstance(coach, dict):
        return None
    for key in ("action", "immediate"):
        val = coach.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _native_build_text(coach) -> str | None:
    """The Haiku BUILD recommendation to score against the precompute lean for
    the HZ-C2 build-agreement gate. The build precompute side is a lean
    (anti_tank / anti_squishy), so the native side must be the live build
    advice, NOT the laning ``action`` (item 502 fix: capturing ``action`` here
    scored the wrong axis, so build agreement was structurally 0/0). Joins the
    Haiku ``item_build`` path + per-item reason keys + the Arena vs-tanks /
    vs-healing hints into one text blob for the report's classify_build_lean.
    Returns None when no build advice is present (then the tick is not
    comparable, the honest no-signal state)."""
    if not isinstance(coach, dict):
        return None
    parts: list[str] = []
    ib = coach.get("item_build")
    if isinstance(ib, str) and ib.strip():
        parts.append(ib)
    elif isinstance(ib, list):
        parts.append(" ".join(str(x) for x in ib))
    reasons = coach.get("item_build_reasons")
    if isinstance(reasons, dict):
        parts.append(" ".join(str(k) for k in reasons))
    for key in ("vs_tanks", "vs_healing", "item_extra"):
        val = coach.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    text = " ".join(p for p in parts if p).strip()
    return text or None


def shadow_log_precomputed_choices(coach: dict, lc: dict | None, mode_key: str,
                                   *, path=None, lcu_snapshot=None) -> None:
    """Fail-soft HZ-C1 validation shadow-log. Records what the PRECOMPUTED
    laning table (``core.precomputed_laning_coach``) would offer for this game
    state - including whether the seed table covered the matchup - to
    data/hz_choice_shadow.jsonl, alongside live coaching. Never raises and has
    NO effect on live output. Only fires when the LIVECLIENT champion is
    present (a real in-game tick) - the coach payload keeps its champion
    forever after a game ends, so coach-champion presence alone would log a
    junk row on every idle /api/state tick. A coverage MISS during a live game
    is recorded too (the seed coverage rate on real games is itself the
    validation signal). ``path`` overrides the jsonl target (test seam).

    ``lcu_snapshot`` supplies the canonical Riot ``game_id`` (captured from the
    gameflow session at lcu/snapshot_shape.py:431-439) so a branch series can
    be bound to one match for the B4 post-game review. Keyword-only with a
    default because a dozen existing call sites pass three positional args."""
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
        from core.laning_scenario_precompute import load_laning_scenarios, lookup
        from core.hz_choice_shadow import log_precomputed_choices
        from core.archetype_picks import canonical_champion_id  # lazy

        level = gs.get("level")
        band = plc.band_for_level(level)
        mana_fraction = _mana_fraction(coach, lc)
        # Live ult-cooldown is not surfaced to the coach dict today; default to
        # the all_up baseline (cd_state_for(None)). A future event source can
        # thread it through here without touching the reader.
        ult_up = None
        mana_state = plc.mana_state_for(mana_fraction)
        cd_state = plc.cd_state_for(ult_up)
        # v4: the completed-legendary count drives BOTH the next-build-item
        # index and the item-state lookup axis. Use the canonical
        # _completed_item_count over the liveclient (the existing coarse proxy).
        item_count = _completed_item_count(lc)
        item_state = plc.item_state_for(item_count)

        payload = load_laning_scenarios(lower)
        enemy_comp = gs.get("enemy_comp") or []
        enemy = plc.resolve_enemy(
            str(champ), [str(e) for e in enemy_comp], lower, payload=payload,
        )

        choices: list = []
        covered = False
        cv = None
        verdict_blocks = None
        if enemy:
            # Same split as the served path: the ORDER is indexed by build
            # progress (slot counts include the trinket + potions and run off
            # the end of a 6-entry order), while the recorded item_count stays
            # the raw slot count because it is the item_state lookup axis the
            # seed table was generated against.
            build_progress = _owned_build_item_count(
                champ, lower, gs.get("my_item_ids"), gs.get("items"),
            )
            next_item = _next_build_item(champ, lower, build_progress)
            cc = plc.precomputed_choices(
                str(champ), enemy, level,
                mana_fraction=mana_fraction, ult_up=ult_up,
                mode=lower, payload=payload, next_item=next_item,
                item_count=item_count,
            )
            choices = to_jsonable(cc)
            covered = bool(cc)
            # RC2 P5.1: compute the CV override (enemy dead/missing from
            # data/vision_state.json, my low HP) against the STATIC band
            # verdict. SHADOW-ONLY - rides the record so hz_shadow_report can
            # re-measure agreement WITH CV applied; the served `choices` are
            # NOT altered here (the flip is operator/Gemini-gated).
            from core.laning_cv_overrides import resolve_cv_override  # lazy
            base_verdict = plc.resolve_band(
                str(champ), enemy, level,
                mana_fraction=mana_fraction, ult_up=ult_up,
                mode=lower, payload=payload, item_count=item_count,
            )
            cv = resolve_cv_override(
                enemy, _hp_fraction(coach, lc), base_verdict,
            )
            # v4: pull the resolved cell's new verdict blocks for the shadow row
            # (spec 7.4) so a future agreement pass can score cooldown-window /
            # spike-timing. Shadow-only; the same band/mana/cd/item-state the
            # reader resolved by. Fail-soft to None (uncovered / v3 cell).
            cell = lookup(
                payload, canonical_champion_id(str(champ)),
                canonical_champion_id(enemy), band, mana_state, cd_state,
                item_state,
            )
            if isinstance(cell, dict):
                cw = cell.get("cooldown_window")
                st = cell.get("spike_timing")
                if isinstance(cw, dict) or isinstance(st, dict):
                    verdict_blocks = {
                        "cooldown_window": cw if isinstance(cw, dict) else None,
                        "spike_timing": st if isinstance(st, dict) else None,
                    }

        log_precomputed_choices(
            mk, str(champ), enemy,
            choices=choices, band=band, mana_state=mana_state, cd_state=cd_state,
            covered=covered,
            native_action=_native_laning_action(coach),
            native_choices=to_jsonable(parse_choices(coach)),
            game_time_s=gs.get("game_time_s"),
            level=level, item_count=item_count, cv_override=cv,
            verdict_blocks=verdict_blocks, path=path,
            game_id=(lcu_snapshot.get("game_id")
                     if isinstance(lcu_snapshot, dict) else None),
        )
    except Exception:  # noqa: BLE001
        return


def shadow_log_objective_playbook(coach: dict, lc: dict | None, det: dict,
                                  mode_key: str, *, path=None) -> None:
    """Fail-soft RC2 P5.5 (WS3) do-not-flip-blind shadow-log. Records the
    deterministic objective playbook directive (the ``kind="playbook"`` row
    already produced inside ``det['callouts']``) alongside the native Haiku
    ``objective`` prose to data/objective_playbook_shadow.jsonl, so a FUTURE flip
    of the served ``objective`` FIELD onto the deterministic directive can be
    agreement-gated. The callout ROW itself ships additive today (no flip); this
    only validates the field flip. Never raises and has NO effect on live output.
    Fires only on a real SR in-game tick (lc champion present + SR objective
    model). ``path`` overrides the jsonl target (test seam)."""
    try:
        # HZ-D4 live-game gate: lc["champion"] is only populated during a real
        # game; the stale coach file keeps `champion` after a game ends.
        if not (isinstance(lc, dict) and lc.get("champion")):
            return
        mk = str(mode_key or "").strip().lower()
        # Objectives are SR-only (next_callouts emits them only for "sr"); ARAM /
        # Arena / tft / brawl never produce a playbook row, so do not log them.
        if _MODE_KEY_TO_LOWER.get(mk) != "sr":
            return
        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return

        play = None
        callouts = (det or {}).get("callouts")
        if isinstance(callouts, list):
            for row in callouts:
                if isinstance(row, dict) and row.get("kind") == "playbook":
                    play = row
                    break

        lead = (det or {}).get("lead_projection")
        lead_state = lead.get("state") if isinstance(lead, dict) else None
        gt = gs.get("game_time_s")
        native_obj = coach.get("objective") if isinstance(coach, dict) else None

        from core.objective_playbook_shadow import log_objective_playbook
        log_objective_playbook(
            mk, str(champ), playbook=play,
            native_objective=native_obj if isinstance(native_obj, str) else None,
            lead_state=lead_state, phase=phase_for(gt),
            game_time_s=gt, path=path,
        )
    except Exception:  # noqa: BLE001
        return


def shadow_log_macro_response(coach: dict, lc: dict | None, det: dict,
                              mode_key: str, *, path=None) -> None:
    """Fail-soft RC2 P5.7 (WS4) shadow-log. Records the deterministic macro
    response (the ``kind="macro_response"`` lost-objective / stagnation row
    already produced inside ``det['callouts']``) alongside the native Haiku
    ``objective`` prose to data/macro_response_shadow.jsonl, so the WS4 triggers
    can be confirmed to fire at the right moments on real games before the row is
    trusted (and a future served-field flip can be agreement-gated). The callout
    ROW itself ships additive today (no flip); this only validates. Never raises
    and has NO effect on live output. Fires only on a real SR in-game tick (lc
    champion present + SR objective model). ``path`` overrides the jsonl target
    (test seam)."""
    try:
        # HZ-D4 live-game gate: lc["champion"] is only populated during a real
        # game; the stale coach file keeps `champion` after a game ends.
        if not (isinstance(lc, dict) and lc.get("champion")):
            return
        mk = str(mode_key or "").strip().lower()
        # Lost-objective + the side-lane stagnation calls are SR concepts; ARAM /
        # Arena / tft / brawl never produce a macro_response row, so do not log.
        if _MODE_KEY_TO_LOWER.get(mk) != "sr":
            return
        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return

        macro = None
        callouts = (det or {}).get("callouts")
        if isinstance(callouts, list):
            for row in callouts:
                if isinstance(row, dict) and row.get("kind") == "macro_response":
                    macro = row
                    break

        lead = (det or {}).get("lead_projection")
        lead_state = lead.get("state") if isinstance(lead, dict) else None
        gt = gs.get("game_time_s")
        native_obj = coach.get("objective") if isinstance(coach, dict) else None

        from core.macro_response_shadow import log_macro_response
        log_macro_response(
            mk, str(champ), macro=macro,
            native_objective=native_obj if isinstance(native_obj, str) else None,
            lead_state=lead_state, phase=phase_for(gt),
            game_time_s=gt, path=path,
        )
    except Exception:  # noqa: BLE001
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
                owned_count=item_count, owned_ids=gs.get("my_item_ids"),
            )
            choices = to_jsonable(cc)
            covered = bool(cc)

        log_precomputed_build(
            mk, str(champ), enemy_comp, lean=lean,
            choices=choices, covered=covered,
            native_action=_native_build_text(coach),
            native_choices=[],
            item_count=item_count, game_time_s=gs.get("game_time_s"), path=path,
        )
    except Exception:  # noqa: BLE001
        return


def shadow_log_live_benchmark_band(coach: dict, lc: dict | None, mode_key: str,
                                   *, path=None) -> None:
    """Fail-soft LBAND1 validation shadow-log. Records the live personal-
    percentile benchmark bands (``core.live_benchmark_band``) that WOULD be
    surfaced for this game state to data/live_benchmark_band_shadow.jsonl,
    alongside live coaching. Never raises and has NO effect on live output.
    SR-only (LBAND1's benchmark data is SR-family); fires only when the
    LIVECLIENT champion is present (a real in-game tick) AND a band actually
    fired (a checkpoint moment with a trustworthy distribution). ``path``
    overrides the jsonl target (test seam)."""
    try:
        gs = _build_game_state(coach, lc, mode_key)
        champ = gs.get("my_champion")
        if not champ:
            return
        # Live-game gate - same rationale as shadow_log_precomputed_choices:
        # only a real in-game liveclient tick carries lc["champion"].
        if not (isinstance(lc, dict) and lc.get("champion")):
            return
        mk = str(mode_key or "").strip().lower()
        if _MODE_KEY_TO_LOWER.get(mk) != "sr":
            return  # LBAND1 bands SR-family only

        from core import live_benchmark_band as lbb  # lazy import
        from core.live_benchmark_band_shadow import log_live_bands

        bands = lbb.band_metrics(
            str(champ), gs.get("game_time_s") or 0.0,
            cs=gs.get("cs"), level=gs.get("level"), mode="SR",
        )
        if not bands:
            return

        log_live_bands(
            mk, str(champ), bands=bands,
            game_time_s=gs.get("game_time_s"), cs=gs.get("cs"),
            level=gs.get("level"),
            native_action=coach.get("action") if isinstance(coach, dict) else None,
            path=path,
        )
    except Exception:  # noqa: BLE001
        return
