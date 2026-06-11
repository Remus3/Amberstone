# arch: builds /api/state payload | section=dashboard | frozen=no
"""Dashboard state-shape builder.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`build_state()` is the canonical /api/state payload assembler - it picks
the active coaching artifact based on `ops/runtime/health.json`, overlays
fresh Live Client API fields on top so the dashboard placeholders
(game_time, kda, level, gold, hp, mana, cs) populate immediately, and
returns the merged dict the dashboard polls at 500ms.

`MODE_TO_FILE` is the public mapping consumed by `build_state()` and
exposed for any caller that wants to know which artifact corresponds to
a given mode key.

Imports `lcu_summary` + `liveclient_summary` directly from
`dashboard._liveclient` (no re-export round-trip through web_dashboard)
and `read_json` directly from `dashboard._context`.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from coaches.sr_draft_profile import is_sr_draft_queue
from core.coaching_payload import validate_coaching_payload
from core.queue_modes import mode_key_from_queue_id
from dashboard._adaptation_latch import compute as _latch_compute
from dashboard._context import APP_DIR, read_json
from dashboard._cs_retention import apply_cs_retention
from dashboard._liveclient import lcu_summary, liveclient_summary
from dashboard.routes_team_context import get_team_context


log = logging.getLogger("rc.web_dashboard")

MODE_TO_FILE = {
    "aram":   "data/aram_coaching_data.json",
    "arena":  "data/arena_coaching_data.json",
    "brawl":  "data/brawl_coaching_data.json",
    "tft":    "data/tft_coaching_data.json",
    # SR + client share the root coaching_data.json
    "game":   "coaching_data.json",
    "client": "coaching_data.json",
    "sr":     "coaching_data.json",
}

# Deduped list of artifact paths the modes resolve to (preserves
# insertion order via dict.fromkeys). Callers that want to scan
# "whichever coaching JSON is freshest" - e.g. the supervisor's
# post-game summary picker - should use this instead of hardcoding
# their own list. Source-of-truth pattern per ADR-008.
MODE_FILES: tuple[str, ...] = tuple(dict.fromkeys(MODE_TO_FILE.values()))


def _preflip_mode_from_lcu(lcu_snapshot: dict | None) -> str | None:
    """Derive a dashboard mode_key from LCU lobby/champ-select queue_id.

    Champ-select wins over lobby (more specific). Returns ``None`` when
    no recognised queue_id is available, so the caller falls back to the
    health.mode default ("client").
    """
    if not isinstance(lcu_snapshot, dict):
        return None
    cs = lcu_snapshot.get("champ_select")
    if isinstance(cs, dict):
        m = mode_key_from_queue_id(cs.get("queue_id"))
        if m:
            return m
    lobby = lcu_snapshot.get("lobby")
    if isinstance(lobby, dict) and not lobby.get("is_custom"):
        m = mode_key_from_queue_id(lobby.get("queue_id"))
        if m:
            return m
    return None


_PREFLIP_FLAG_MAP = {
    "aram":  "aram_mode",
    "arena": "arena_mode",
    "brawl": "brawl_mode",
    "tft":   "tft_mode",
    "sr":    "has_game",
}


def resolve_mode_key(health: dict, lcu_snapshot: dict | None) -> tuple[str, bool]:
    """Return (mode_key, preflip_active).

    Same priority order as ``build_state``:
      1. LiveClient flags (aram/arena/tft/has_game) - authoritative once
         the game is actually running.
      2. LCU lobby/champ-select queue_id pre-flip - so the dashboard
         switches to the right mode panel before the in-game match.
      3. ``health.mode`` fallback (legacy code paths).
      4. ``"client"`` default.
    """
    if health.get("aram_mode"):  return ("aram",  False)
    if health.get("arena_mode"): return ("arena", False)
    if health.get("tft_mode"):   return ("tft",   False)
    if health.get("has_game"):   return ("sr",    False)
    pre = _preflip_mode_from_lcu(lcu_snapshot)
    if pre:
        return (pre, True)
    return (health.get("mode", "client"), False)


def apply_preflip_mirror(health: dict, mode_key: str, preflip_active: bool) -> dict:
    """Return a copy of ``health`` with the per-mode flag set when the
    s150 LCU pre-flip is the source of ``mode_key``.

    Without this, the dashboard's ``onHealth`` resolver recomputes
    ``tag="client"`` every health tick from the still-False health.json
    flags and races ``onState``'s pre-flipped mode - flapping the mode
    pill, augments pill, and win% pill in lockstep on every cadence cycle.
    Used by both ``build_state`` (HTTP /api/state) and
    ``agents.agent2_backend.file_ingest`` (WS /push) so both paths agree.
    """
    if not preflip_active:
        return health
    flag = _PREFLIP_FLAG_MAP.get(mode_key)
    if not flag:
        return health
    return {**health, flag: True}


def _active_champion(coach: dict, lc: dict | None, lcu_snapshot: dict | None) -> str:
    """Resolve the operator's currently-active champion across signals.

    Priority order (most → least authoritative):
      1. ``liveclient.champion`` - in-game, derived from LiveClient
         ``allPlayers[]`` matched on summoner name. Single source of truth
         once the game is running.
      2. ``coach.champion`` - the coach JSON's persisted field (ARAM /
         Arena / Brawl / TFT shapes carry it; SR's ``coaching_data.json``
         doesn't - falls through).
      3. ``lcu.champ_select.local_pick.champion_name`` - pre-game.
      4. Empty string when nothing resolves.

    Used by ``build_state`` to stamp ``state.cs_archetype_pick`` - purely
    decorative for the dashboard's archetype-picker UI. Coaches resolve
    champion independently from their own upstream state.
    """
    if isinstance(lc, dict):
        champ = lc.get("champion")
        if champ:
            return str(champ)
    if isinstance(coach, dict):
        champ = coach.get("champion")
        if champ:
            return str(champ)
    if isinstance(lcu_snapshot, dict):
        cs = lcu_snapshot.get("champ_select")
        if isinstance(cs, dict):
            local = cs.get("local_pick") or cs.get("local_member") or {}
            if isinstance(local, dict):
                for key in ("champion_name", "championName", "champion"):
                    v = local.get(key)
                    if v:
                        return str(v)
            # item 244: the live SR/draft champ-select payload carries
            # my_champion as a numeric championId (51) + local_cell, not a
            # local_pick name dict. Resolve it to a display name so
            # cs_archetype_pick populates pre-game. Fail-soft; 0 = no pick.
            mc = cs.get("my_champion")
            if mc:
                try:
                    from core.archetype_picks import champion_name_by_key
                    name = champion_name_by_key(mc)
                    if name:
                        return name
                except Exception:
                    pass
    return ""


def apply_cleared_at(coach, lc):
    """Honor an operator force-clear sentinel (``coach.cleared_at``).

    item 281: a force-clear writes ``cleared_at`` into the coaching artifact
    but historically nothing consumed it, so a stale game kept rendering as
    a live ACTIVE MATCH whenever ``mode_key`` resolved back to that mode -
    an 11-day-old ARAM game resurfaced every time the operator sat in an
    ARAM lobby (``health.aram_mode`` true). When the sentinel is present AND
    there is no live game to overlay, return an empty payload so /api/state
    never surfaces a phantom match. A real game overwrites the artifact
    without the sentinel, so live coaching is unaffected; the ``not lc``
    guard additionally refuses to hide a live game if a stray sentinel
    somehow survives.
    """
    if isinstance(coach, dict) and coach.get("cleared_at") and not lc:
        return {}
    return coach


# S7 (2026-06-10): per-stage cost breakdown for slow builds. The
# routes_state wrapper already WARNs on total cost; this names WHICH
# stage burned it (live games showed 700ms builds with no attribution).
# Throttled so an SSE loop stuck slow cannot spam the log.
_SLOW_STAGES_WARN_S = 0.25
_SLOW_STAGES_THROTTLE_S = 30.0
_slow_stages_last_warn = 0.0


def _warn_slow_stages(stages: list[tuple[str, float]]) -> None:
    global _slow_stages_last_warn
    total = sum(s for _, s in stages)
    if total < _SLOW_STAGES_WARN_S:
        return
    now = time.monotonic()
    if now - _slow_stages_last_warn < _SLOW_STAGES_THROTTLE_S:
        return
    _slow_stages_last_warn = now
    top = sorted(stages, key=lambda x: x[1], reverse=True)[:3]
    log.warning("state-build stages slow: total=%dms top: %s",
                int(total * 1000),
                " ".join(f"{n}={int(s * 1000)}ms" for n, s in top))


def build_state() -> dict:
    _stages: list[tuple[str, float]] = []
    _t = time.monotonic()

    def _mark(name: str) -> None:
        nonlocal _t
        now = time.monotonic()
        _stages.append((name, now - _t))
        _t = now

    health = read_json("ops/runtime/health.json")
    lcu_snapshot = lcu_summary()
    _mark("lcu")
    # Hold the last champ_select across the fast no-draft (ARAM /
    # Mayhem / Arena) champ-select → game transition + >5s agent-push
    # staleness. Applied before resolve_mode_key so the s150 pre-flip
    # mode survives the transient loss too.
    lcu_snapshot = apply_cs_retention(lcu_snapshot)
    mode_key, preflip_active = resolve_mode_key(health, lcu_snapshot)
    health = apply_preflip_mirror(health, mode_key, preflip_active)

    coach_file = MODE_TO_FILE.get(mode_key, "coaching_data.json")
    coach = read_json(coach_file)
    validate_coaching_payload(coach)
    _mark("coach_file")

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    lc = liveclient_summary()
    _mark("liveclient")
    # item 281: honor a force-clear sentinel BEFORE the overlay so a cleared
    # artifact can never leak stale game fields into /api/state.
    coach = apply_cleared_at(coach, lc)
    if lc:
        for k, v in lc.items():
            if coach.get(k) in (None, "", 0):
                coach[k] = v
        # Merge time-latched STATS metrics (cs_at_10, csd_at_15) into coach.
        # Coach values win when present; latch fills the blanks only.
        # The latch module holds game-scoped state across /api/state ticks.
        for k, v in _latch_compute(lc).items():
            if coach.get(k) in (None, "", 0):
                coach[k] = v

    # Phase 8 step 1: derive sr_draft flag from queue_id and stamp it
    # alongside the existing is_aram sibling. Phase 8's UI gates the
    # 3-build chooser on this flag.
    cs = lcu_snapshot.get("champ_select") if isinstance(lcu_snapshot, dict) else None
    if isinstance(cs, dict):
        cs["sr_draft"] = is_sr_draft_queue(cs.get("queue_id"))

    # FU02: splice the latest team_context payload (5+5 enrichment) into
    # coach. Stays None until the Game-PC LCU agent posts to
    # /api/team-context/refresh. Dashboard panel reads coach.team_context
    # and falls back to skeleton rows when fields are empty.
    _mark("latch_overlay")
    coach["team_context"] = get_team_context()
    _mark("team_context")

    # s182 (2026-05-13) - surface the operator's effective archetype pick
    # for the active champion. Resolves DDragon-tag default + persisted
    # override; empty champion produces empty dict so dashboard JS can
    # branch on ``state.cs_archetype_pick.champion`` truthiness without
    # null-checking nested fields. Coach integration reads from
    # core.archetype_picks directly (own pipeline); this stamp is purely
    # decorative for the picker UI to show the current effective pick.
    cs_archetype_pick: dict = {}
    try:
        champ = _active_champion(coach, lc, lcu_snapshot)
        if champ:
            from core.archetype_picks import get_archetype_for
            cs_archetype_pick = get_archetype_for(champ)
    except Exception:
        cs_archetype_pick = {}

    # s184 (2026-05-13) - first-purchase archetype-mismatch nudge. Reads
    # ``cs_archetype_pick`` + liveclient owned_item_ids; if operator's
    # first non-trivial completed item isn't in the dispatcher's top-15
    # for their picked archetype, surface a soft chip on the dashboard.
    # Dedup'd per (champion, game-session); engine-down silently skips.
    archetype_nudge: dict = {}
    try:
        from core.archetype_mismatch import compute_nudge_payload
        archetype_nudge = compute_nudge_payload(
            coach=coach,
            lc=lc,
            lcu_snapshot=lcu_snapshot,
            cs_archetype_pick=cs_archetype_pick,
        )
    except Exception:
        archetype_nudge = {}
    _mark("archetype")

    # s240 - on-demand VLM coach ("SCREEN READ"). Dedicated field,
    # independent of coach.immediate so an operator-triggered read isn't
    # clobbered by the next coach tick. Defaults to {} and is wrapped so
    # a malformed/missing file can never break /api/state (mirrors the
    # s184 archetype_nudge stamping pattern).
    screen_read: dict = {}
    try:
        sr = read_json("data/screen_read.json")
        if isinstance(sr, dict):
            screen_read = sr
    except Exception:
        screen_read = {}

    # 2026-05-20 - summoner + ult cooldown ledger. Backend ships per-player
    # blocks (d/f spell + ult, sorted by next-up ascending). The Live
    # Client API doesn't expose summoner-cast events so the panel renders
    # everything as READY today; the wire is here so a future event
    # source (decision_detector OCR, LCU plugin) can light up the
    # remaining-cd column without UI/transport churn. Null when no game.
    summoner_cooldowns: list | None = None
    try:
        from dashboard._state_cooldowns import compute_state_cooldowns
        summoner_cooldowns = compute_state_cooldowns(lc)
    except Exception:
        summoner_cooldowns = None
    _mark("cooldowns")

    # Haiku-elimination wave 3 (item 265 W3A): deterministic-FIRST coaching.
    # The DS matchup engine (laning A/B) + the pure callout/lead generators
    # produce the A/B choices, the objective/spike callouts, and the macro
    # lead read WITHOUT a Claude call. Falls back to the coach's native
    # `choices` / the synthesizer only when the deterministic laning path
    # yields nothing (engine down / no enemy). The existing #rn-choices chip
    # UI renders coach["choices"] unchanged; the NEW callouts + lead_projection
    # keys are additive (frontend slice renders them in a later wave).
    det = {"choices": [], "callouts": [], "lead_projection": {}}
    try:
        from dashboard._deterministic_coaching import (
            compute_deterministic, resolve_choices, shadow_log_det,
            shadow_log_precomputed_choices, shadow_log_precomputed_build,
        )
        det = compute_deterministic(coach, lc, mode_key)
        # Shadow-log BEFORE resolve_choices overwrites coach["choices"] - the
        # validation log must capture the NATIVE choices the deterministic flip
        # discards, not the post-flip result.
        shadow_log_det(coach, lc, det, mode_key)
        # HZ-C1/C2: also shadow-log what the PRECOMPUTED laning table (A/B
        # trade) + HZ-B2 build-variant table (A/B build) would offer
        # (do-not-flip-blind). Fail-soft, additive, NO effect on live output.
        shadow_log_precomputed_choices(coach, lc, mode_key)
        shadow_log_precomputed_build(coach, lc, mode_key)
        coach["choices"] = resolve_choices(coach, det)
    except Exception:
        det = {"choices": [], "callouts": [], "lead_projection": {}}
        coach["choices"] = []
    _mark("deterministic")
    _warn_slow_stages(_stages)

    return {
        "mode_key": mode_key,
        "coach_source": coach_file,
        "health": {
            "alive":          health.get("alive"),
            "pid":            health.get("pid"),
            "mode":           health.get("mode"),
            "has_game":       health.get("has_game"),
            # Per-mode flags drive `onHealth` mode resolution in the
            # dashboard. Without them, has_game=True would always fall
            # through to `tag="sr"` and flap against onState's mode_key
            # ("arena"/"aram"/"brawl"/"tft"), flashing mode-gated UI like
            # the augments pill on every health tick.
            "aram_mode":      health.get("aram_mode"),
            "arena_mode":     health.get("arena_mode"),
            "brawl_mode":     health.get("brawl_mode"),
            "tft_mode":       health.get("tft_mode"),
            "ui_pulse_age_s": health.get("ui_pulse_age_s"),
            "game_poll_age_s": health.get("game_poll_worker_age_s"),
        },
        "coach": coach,
        "liveclient": lc,
        "lcu": lcu_snapshot,
        "cs_archetype_pick": cs_archetype_pick,
        "archetype_nudge": archetype_nudge,
        "screen_read": screen_read,
        "summoner_cooldowns": summoner_cooldowns,
        "callouts": det.get("callouts") or [],
        "lead_projection": det.get("lead_projection") or {},
    }


