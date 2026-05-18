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
from pathlib import Path

from coaches.sr_draft_profile import is_sr_draft_queue
from core.coaching_payload import validate_coaching_payload
from core.queue_modes import mode_key_from_queue_id
from dashboard._context import APP_DIR, read_json
from dashboard._cs_retention import apply_cs_retention
from dashboard._liveclient import lcu_summary, liveclient_summary
from dashboard.routes_team_context import get_team_context


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
    return ""


def build_state() -> dict:
    health = read_json("ops/runtime/health.json")
    lcu_snapshot = lcu_summary()
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

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    lc = liveclient_summary()
    if lc:
        for k, v in lc.items():
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
    coach["team_context"] = get_team_context()

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
    }


