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

import concurrent.futures
import json
import logging
import os
import threading
import time
import unicodedata
from pathlib import Path

from coaches.sr_draft_profile import is_sr_draft_queue
from core.coaching_payload import validate_coaching_payload
from core.queue_modes import mode_key_from_queue_id
from dashboard._adaptation_latch import compute as _latch_compute
from dashboard._context import APP_DIR, read_json
from dashboard._cs_retention import apply_cs_retention
from dashboard._liveclient import lcu_summary, liveclient_summary
from dashboard._party_mains import enrich_party_mains
from dashboard.routes_team_context import get_team_context


log = logging.getLogger("rc.web_dashboard")

# RC2 6.5 - state-pipeline latency reduction. build_state() opens two
# independent localhost relay round-trips: lcu_summary() (champ-select /
# lobby, needed immediately) and liveclient_summary() (in-game fields,
# not needed until the overlay merge well below). Running them back-to-
# back stacked two ~1s-timeout waits on the /api/state critical path. We
# overlap the liveclient round-trip with the lcu + coach-file work via a
# tiny shared thread pool. Small bounded worker count: the build is gated
# to ~2/s by the routes_state TTL, with a handful of SSE subscribers +
# pollers at worst - never a fan-out. Port-safe: same two connections,
# briefly overlapped, never multiplied.
_RELAY_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="rc-state-relay")

MODE_TO_FILE = {
    "aram":   "data/aram_coaching_data.json",
    "arena":  "data/arena_coaching_data.json",
    "brawl":  "data/brawl_coaching_data.json",
    "tft":    "data/tft_coaching_data.json",
    # SR + client share the root coaching_data.json. RM-141: jade (League
    # Classic throwback, map 453) joins them because it reuses the SR coach
    # path and adds no writer of its own. The entry is explicit rather than
    # left to the :348 fallback so the queue-map grounding tests, which
    # assert every mapped mode_key is a KEY here, stay green.
    "game":   "coaching_data.json",
    "client": "coaching_data.json",
    "sr":     "coaching_data.json",
    "jade":   "coaching_data.json",
}

# Deduped list of artifact paths the modes resolve to (preserves
# insertion order via dict.fromkeys). Callers that want to scan
# "whichever coaching JSON is freshest" - e.g. the supervisor's
# post-game summary picker - should use this instead of hardcoding
# their own list. Source-of-truth pattern per ADR-008.
MODE_FILES: tuple[str, ...] = tuple(dict.fromkeys(MODE_TO_FILE.values()))


# --- RM-405: the CALLER seam of the L3 read must not degrade silently -------
# RM-312 made a fault raised INSIDE dashboard/_lcu_inprocess visible. It cannot
# see a fault that ESCAPES that module, because _read_lcu_snapshot below wraps
# the whole call in a SECOND try/except one frame higher. Two classes land
# there and nowhere else:
#
#   * the LAZY IMPORT on the "from dashboard._lcu_inprocess import ..." line.
#     When that raises (broken/renamed module, circular import, a failure
#     inside lcu.snapshot_shape at module load), RM-312's _log_degrade does
#     not exist to run - its module never loaded;
#   * anything re-raised past lcu_summary_inprocess's own guard.
#
# Swallowed silently, either one means RC pays the :8889 relay hop that lever
# L3 exists to REMOVE, forever, with nothing in logs/ saying why - the exact
# failure RM-312 closed, one frame up. Same shape as the fix it mirrors
# (dashboard/_lcu_inprocess.py:102-160): WARN on CHANGE of the fault
# signature, then at most once per throttle window, built from the exception
# TYPE plus the innermost raising frame and NEVER from str(exc) - an LCU
# payload carries PUUIDs and this repo is public.
#
# The wording is deliberately DISTINCT from RM-312's line so a log reader can
# tell the caller seam from the module seam.
_CALLER_DEGRADE_LOG_THROTTLE_S = 60.0
_caller_degrade_log_lock = threading.Lock()
_caller_degrade_log_state: dict = {"sig": None, "ts": None}


def _log_inprocess_caller_degrade(exc: BaseException) -> None:
    """WARN once per distinct caller-seam fault, then at most once a minute.

    Never raises: it runs inside the except clause of a fail-soft path, so a
    fault in the logging itself must not escalate past the degrade.
    """
    try:
        filename, lineno, func = "?", 0, "?"
        tb = exc.__traceback__
        while tb is not None:
            filename = os.path.basename(tb.tb_frame.f_code.co_filename)
            lineno = tb.tb_lineno
            func = tb.tb_frame.f_code.co_name
            tb = tb.tb_next
        sig = (type(exc).__name__, filename, lineno, func)
        now = time.monotonic()
        with _caller_degrade_log_lock:
            prev_sig = _caller_degrade_log_state["sig"]
            prev_ts = _caller_degrade_log_state["ts"]
            if (sig == prev_sig and prev_ts is not None
                    and (now - prev_ts) < _CALLER_DEGRADE_LOG_THROTTLE_S):
                return
            _caller_degrade_log_state["sig"] = sig
            _caller_degrade_log_state["ts"] = now
        log.warning(
            "in-process LCU caller seam failed (fault escaped "
            "lcu_summary_inprocess, import included) - degrading to the :8889 "
            "relay: %s escaped at %s:%d in %s()",
            sig[0], sig[1], sig[2], sig[3])
    except Exception:  # noqa: BLE001
        pass


def _reset_caller_degrade_log_for_tests() -> None:
    """Forget the last logged caller-seam fault so the WARN is re-drivable."""
    with _caller_degrade_log_lock:
        _caller_degrade_log_state["sig"] = None
        _caller_degrade_log_state["ts"] = None


def _expire_caller_degrade_log_for_tests() -> None:
    """Expire the throttle but KEEP the last signature, so a test can drive
    the 'same fault, throttle elapsed' re-log without time travel."""
    with _caller_degrade_log_lock:
        _caller_degrade_log_state["ts"] = None


def _read_lcu_snapshot() -> dict:
    """Source the whole LCU snapshot for build_state.

    DEFAULT-OFF in-process path (RC2 RM-03 E12 lever L3): when
    ``RC_LCU_INPROCESS=1`` AND the dashboard-owned LcuClient returns a
    snapshot, build the payload in-process via lcu.snapshot_shape (no :8889
    relay round-trip). Otherwise - flag unset, client unconnected, or any
    error - fall back to the relay ``lcu_summary()`` so today's live path is
    byte-identical. Landed DARK; G1-00 live confirm (flag ON in a live
    champ-select) is owed before flipping. Imported lazily to avoid an import
    cycle through dashboard._lcu_inprocess -> lcu.lcu_client at module load.

    RM-405: the except branch is no longer SILENT. ``snap = None`` and the
    fall-through to the relay are UNCHANGED - only the trace is added, via the
    throttled, payload-free ``_log_inprocess_caller_degrade`` above. The
    success path and the ordinary ``snap is None`` (League not running) path
    are untouched: a line there would be worse than none.
    """
    if os.environ.get("RC_LCU_INPROCESS") == "1":
        try:
            from dashboard._lcu_inprocess import lcu_summary_inprocess
            snap = lcu_summary_inprocess()
        except Exception as exc:  # noqa: BLE001
            _log_inprocess_caller_degrade(exc)
            snap = None
        if snap is not None:
            return snap
    return lcu_summary()


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


# --- B4 (RM-189): live-game imperative suppression -----------------------
# Riot's third-party rules ban "notifications that dictate player action based
# on the current game state". Operator decision 2026-08-11
# (docs/OVERLAY_COMPLIANCE_PLAN.md section 6c): live coaching moves to
# pre-game and post-game; in-game keeps SILENT capture of the decision branch
# points only. Design + measurements: docs/OVERLAY_B4_DESIGN.md.
#
# Suppression lives at the PRODUCER, not the renderer, for two reasons the
# design records: the overlay's current boundary is a single CSS :not() chain
# (web/css/overlay.css:127) which fails silently, and a payload that reaches
# the client is one DevTools panel away from a reviewer. Same doctrine as B5
# ("obfuscate at the producer ... so every consumer inherits it").
#
# The KEY stays on the envelope, per the B2 precedent - a permanent falsy so
# consumers degrade instead of crashing on a missing field.
LIVE_SUPPRESSED_FIELDS = (
    "action",           # imperative headline (#rn-action)
    "immediate",        # imperative prose (#rn-immediate)
    "fight_rule",
    "next",
    "risk",
    "target_priority",  # arena "focus X"
    "round_strategy",   # arena round imperative
    "choices",          # A/B/C decision chips (#rn-choices) - the worst case
)

# choices is Array.isArray()-tested by web/js/panels/coach_choices.js, so it
# must blank to [] and not None or the renderer falls through to the prose
# branch instead of the empty branch.
_LIVE_SUPPRESSED_EMPTY = {"choices": []}

# B4-b: the deterministic siblings. These are TOP-LEVEL keys on /api/state, NOT
# inside `coach`, which is why the B4-a coach-field sweep did not reach them -
# and they feed two of the only three mounts the overlay shell keeps visible
# (web/css/overlay.css:127). Both are imperative at the source:
#   core/event_callouts.py:120  "Your lvl-6 spike - look for all-in"
#   core/event_callouts.py:128  "2-item spike - force fights now"
#   core/event_callouts.py:108  "Drake spawns 5:00 - set up vision"
#   core/lead_projection.py:211 "Big lead: dive or roam, snowball it now."
# lead_projection's own source calls _LINES_BY_MODE a "per-mode directive
# table" (core/lead_projection.py:321).
#
# The two spike lines are additionally the B3 artefact ("notifications that
# alert players when a power spike hits"). B3 deleted web/js/panels/spike_cue.js
# but not this feed, so the cue survived its own removal on a second mount.
LIVE_SUPPRESSED_ENVELOPE_FIELDS = ("callouts", "lead_projection")

_LIVE_SUPPRESSED_ENVELOPE_EMPTY = {"callouts": [], "lead_projection": {}}

# The predicate itself lives in core/live_game_gate.py - B4-c added a second
# consumer (the voice path, which has no /api/state envelope in hand), and a
# private copy here is exactly how a fix stops reaching one of them. Re-exported
# under the same name so existing callers and tests are unaffected.
from core.live_game_gate import is_live_game  # noqa: E402


def suppress_live_directives(coach, health: dict | None,
                             preflip_active: bool = False):
    """Blank every coach imperative while a game is live.

    Returns a COPY - the same ``coach`` dict was handed to the shadow writers
    earlier in the tick, and blanking it in place would retroactively empty
    what they captured if any of them holds the reference. Descriptive state
    (hp, gold, kda, clock, cc_threat_cell, the STATS block) is untouched: the
    ban is on imperatives, and an over-broad strip would be its own defect.
    """
    if not isinstance(coach, dict) or not is_live_game(health, preflip_active):
        return coach
    out = dict(coach)
    for field in LIVE_SUPPRESSED_FIELDS:
        if field in out:
            out[field] = _LIVE_SUPPRESSED_EMPTY.get(field)
    return out


def suppress_live_envelope(det, health: dict | None,
                           preflip_active: bool = False):
    """Blank the top-level deterministic directive feeds while a game is live.

    Sibling of ``suppress_live_directives`` for the keys that live OUTSIDE
    ``coach`` on the served envelope. Same copy-not-mutate contract: the same
    ``det`` dict is read by the shadow writers earlier in the tick.
    """
    if not isinstance(det, dict) or not is_live_game(health, preflip_active):
        return det
    out = dict(det)
    for field in LIVE_SUPPRESSED_ENVELOPE_FIELDS:
        if field in out:
            out[field] = _LIVE_SUPPRESSED_ENVELOPE_EMPTY.get(field)
    return out


def _active_champion(coach: dict, lc: dict | None, lcu_snapshot: dict | None) -> str:
    """Resolve the operator's currently-active champion across signals.

    Priority order (most -> least authoritative):
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
                except Exception:  # noqa: BLE001
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


# Coaches (Haiku/Sonnet) emit non-ASCII punctuation - em/en dashes, smart
# quotes, ellipsis - into prose fields (objective, action, next, ...). Those
# flow untouched to the user-facing HUD + dashboard, violating the repo
# ASCII-only hard rule. This translation table maps them to ASCII. build_state
# is the single downstream seam ALL four coaches' output passes through to
# /api/state, so cleaning here covers every mode in one place.
_ASCII_PUNCT = {
    0x2013: "-", 0x2014: "-",     # en dash, em dash -> hyphen
    0x2018: "'", 0x2019: "'",     # left/right single quote -> apostrophe
    0x201C: '"', 0x201D: '"',     # left/right double quote -> straight
    0x2026: "...",                # horizontal ellipsis
    # Arrows + symbols the coaches emit in build/objective prose (item 559;
    # live SR play showed a U+2192 in coach.action - "CRASH BOT -> SETUP
    # DRAKE" - reaching the HUD). Mapped to readable ASCII so the fallback
    # below keeps them as e.g. "->" rather than dropping them.
    0x2192: "->", 0x2190: "<-", 0x2194: "<->",   # right/left/both arrows
    0x21D2: "=>", 0x21D0: "<=",                   # double arrows
    0x2191: "^", 0x2193: "v",                     # up/down arrows
    0x2022: "-", 0x00B7: "-",                     # bullet, middle dot
    0x00D7: "x", 0x00F7: "/",                     # multiplication, division
    0x00A0: " ",                                  # non-breaking space
}


def _ascii_clean(obj):
    """Recursively map non-ASCII punctuation in coach text to ASCII (repo rule).
    Walks the read coaching dict/list; leaves numbers/bools/None untouched."""
    if isinstance(obj, str):
        cleaned = obj.translate(_ASCII_PUNCT)
        if cleaned.isascii():
            return cleaned
        # Defense in depth: any glyph the explicit table did not enumerate (the
        # coaches are LLMs and can emit arbitrary symbols/emoji) is NFKD-folded
        # then ASCII-encoded with errors ignored, so a codepoint > 127 can never
        # reach the HUD. The explicit map ran first, so meaningful glyphs keep a
        # readable ASCII form instead of being silently dropped here.
        return (
            unicodedata.normalize("NFKD", cleaned)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    if isinstance(obj, dict):
        return {k: _ascii_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ascii_clean(v) for v in obj]
    return obj


def build_state() -> dict:
    _stages: list[tuple[str, float]] = []
    _t = time.monotonic()

    def _mark(name: str) -> None:
        nonlocal _t
        now = time.monotonic()
        _stages.append((name, now - _t))
        _t = now

    # RC2 6.5: kick off the independent liveclient relay round-trip
    # concurrently with the lcu snapshot + coach-file reads below. Its
    # result (lc) isn't consumed until the overlay merge ~30 lines down,
    # so overlapping removes that localhost round-trip from the serial
    # critical path (and bounds a hung relay at max() of the two 1s
    # timeouts, not their sum). Submitted via the module global so tests
    # patching _state_builder.liveclient_summary still take effect. Falls
    # back to an inline call if the pool can't accept the task.
    try:
        _lc_future = _RELAY_POOL.submit(liveclient_summary)
    except Exception:  # noqa: BLE001
        _lc_future = None

    health = read_json("ops/runtime/health.json")
    lcu_snapshot = _read_lcu_snapshot()
    _mark("lcu")
    # Hold the last champ_select across the fast no-draft (ARAM /
    # Mayhem / Arena) champ-select -> game transition + >5s agent-push
    # staleness. Applied before resolve_mode_key so the s150 pre-flip
    # mode survives the transient loss too.
    lcu_snapshot = apply_cs_retention(lcu_snapshot)
    # PARTY MAINS: enrich the forwarded lobby members with each non-self
    # member's top champion (Riot Champion-Mastery-V4). Non-blocking - serves
    # cached data, refreshes in the background (see dashboard._party_mains).
    lcu_snapshot = enrich_party_mains(lcu_snapshot)
    mode_key, preflip_active = resolve_mode_key(health, lcu_snapshot)
    health = apply_preflip_mirror(health, mode_key, preflip_active)

    coach_file = MODE_TO_FILE.get(mode_key, "coaching_data.json")
    coach = _ascii_clean(read_json(coach_file))
    validate_coaching_payload(coach)
    _mark("coach_file")

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    # Join the liveclient round-trip started up top (RC2 6.5). It almost
    # always completed during the lcu/coach work above, so this rarely
    # blocks. Any pool/future failure degrades to a fresh inline call so
    # behavior is identical to the pre-6.5 serial path.
    if _lc_future is not None:
        try:
            lc = _lc_future.result()
        except Exception:  # noqa: BLE001
            lc = liveclient_summary()
    else:
        lc = liveclient_summary()
    _mark("liveclient")
    # item 281: honor a force-clear sentinel BEFORE the overlay so a cleared
    # artifact can never leak stale game fields into /api/state.
    _was_cleared = isinstance(coach, dict) and bool(coach.get("cleared_at")) and not lc
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
    # coach. Stays None until the Legion LCU agent posts to
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
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001
        screen_read = {}

    # Riot compliance 2026-08-11: the summoner + ult cooldown ledger
    # (2026-05-20, core/summoner_cooldowns.py + dashboard/_state_cooldowns.py)
    # was REMOVED. Riot's third-party rules ban tracking enemy summoner-spell
    # cooldowns outright and forbid ultimate timers for every player, ally
    # included. The key is kept on the wire as a permanent null so downstream
    # consumers degrade instead of KeyError-ing; do not repopulate it. See
    # docs/OVERLAY_COMPLIANCE_PLAN.md.
    summoner_cooldowns: list | None = None

    # ZOI foundation (2026-06-21) - the settings-driven on-screen minimap rect,
    # in 1920x1080 design px, for the overlay's click-through minimap outline
    # widget (w-mmrect). Read from League's game.cfg [HUD] MinimapScale +
    # FlipMiniMap: LOCAL + free, no API. Mode-gated to surfaces that have a
    # minimap (sr/aram/brawl); null otherwise so the widget stays hidden.
    # Fail-soft: a missing game.cfg (clean checkout / CI / non-Legion) yields
    # null, never an exception.
    minimap_rect: dict | None = None
    if mode_key in ("sr", "aram", "brawl"):
        try:
            from core.league_settings import minimap_rect_payload
            minimap_rect = minimap_rect_payload()
        except Exception:  # noqa: BLE001
            minimap_rect = None
    _mark("minimap_rect")

    # ZOI item 567 slice 2: per-team colored blob centroids on the live minimap
    # (pure-numpy, LOCAL, no API). Only when in-game (lc) and we have a rect to
    # crop by. TTL-cached + fail-soft -> [] so a vision hiccup never stalls state.
    minimap_dots: list = []
    if minimap_rect and lc:
        try:
            from core.minimap_blob_detect import current_minimap_dots
            # Spec H (2026-07-08): pass the live roster so the identity pass
            # can template-match against the actual champions in this game.
            # _live_roster() reads the raw liveclient_cache which may be stale
            # or None; the already-built lc summary has enemy_team + ally_team.
            _roster = (lc.get("enemy_team") or []) + (lc.get("ally_team") or [])
            # background=True: the ~2s native grab + blob detect must not block
            # the /api/state hot path (it stalled every poller + timed out the
            # in-game overlay poll). Stale-while-revalidate serves the cached
            # dots here and refreshes on a daemon thread.
            minimap_dots = current_minimap_dots(
                minimap_rect, roster=_roster, background=True)
        except Exception:  # noqa: BLE001
            minimap_dots = []
    _mark("minimap_dots")

    # ZOI item 567 slice 3: Zone-of-Influence shading derived from the slice-2
    # minimap dots (pure, stateless - one shaded bubble per dot + a team
    # demarcation line + a map-control summary). Only on minimap surfaces with
    # dots present; gated to sr/aram. Fail-soft -> None so a hiccup never stalls
    # state. my_level / game_time_s scale ally / enemy bubbles (Live Client
    # exposes only my own data - see core/zoi_influence honest-scope note).
    zoi = None
    if minimap_dots and mode_key in ("sr", "aram"):
        try:
            from core.zoi_influence import compute_zoi
            _lc = lc or {}
            zoi = compute_zoi(
                minimap_dots,
                my_level=_lc.get("level"),
                game_time_s=_lc.get("game_time_s"),
            )
            if zoi is not None:
                # Spec H (2026-07-08): champion-identity dots for the overlay.
                # Extracted from minimap_dots AFTER the presence bubbles are
                # built; the discrete per-champion markers are a SEPARATE visual
                # layer (initial labels on the ZOI canvas), not the soft team
                # presence shading. Only dots with a champion tag + confidence
                # above the match threshold pass through. Additive only  -  every
                # existing zoi key stays byte-unchanged; absent/no-match champion
                # dots => zoi["champion_dots"] is an empty list.
                cdots = [
                    {
                        "team": d["team"],
                        "champion": d["champion"],
                        "x_frac": d["x_frac"],
                        "y_frac": d["y_frac"],
                        "confidence": d.get("identity_confidence", 0.0),
                    }
                    for d in minimap_dots
                    if isinstance(d, dict) and d.get("champion")
                    and d.get("identity_confidence", 0.0) >= 0.55
                ]
                zoi["champion_dots"] = cdots
                # ZOI Wave 2 (spec B): ADDITIVE per-district presence vector.
                # current_presence() wraps a module-level tracker (wipes on
                # new-game/mode-change/stale-gap); it and presence_payload()
                # are fail-soft (never raise). The nested try keeps the
                # existing {bubbles, demarcation, map_control} byte-identical
                # even if the presence import itself fails.
                try:
                    from core.minimap_presence import (
                        current_presence,
                        presence_payload,
                    )
                    zoi["districts"] = presence_payload(
                        current_presence(
                            minimap_dots, mode_key, _lc.get("game_time_s")
                        )
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            zoi = None
    # ZOI Wave 2 (spec C): API-ground-truth fusion over the CV district
    # presence vector. The lc event lists live ON lc itself (liveclient_summary
    # keys turret_events / inhib_events / objective_events / players).
    # Additive-only: adds zoi["districts_fused"]; every existing zoi key stays
    # byte-unchanged. Fail-soft: any failure (or a missing districts vector)
    # leaves zoi exactly as it was.
    try:
        if zoi is not None and isinstance(zoi.get("districts"), list):
            from core.district_fusion import fuse_districts
            _lc_f = lc or {}
            zoi["districts_fused"] = fuse_districts(
                zoi.get("districts"),
                _lc_f,
                mode_key,
                _lc_f.get("game_time_s"),
            )
    except Exception:  # noqa: BLE001
        pass
    # ZOI Wave 3 (spec E-2): MIA reachability rings - one growing circle per
    # fogged (not visible, not dead) enemy, origin at last-seen map position,
    # radius = missing time x est movespeed (core/mia_reachability.py is the
    # SOLE zoi.mia producer). SR-gated: shared-vision modes have no fog and
    # compute_mia is itself fail-CLOSED to SR. enemy_tracks come from the
    # in-process vision_tracker singleton (state() is {} until first ingest,
    # so the read is fail-soft). Additive-only: adds zoi["mia"]; every existing
    # zoi key stays byte-unchanged.
    try:
        if zoi is not None and mode_key == "sr":
            from core.mia_reachability import compute_mia
            from core.vision_tracker import get_tracker as _vt_get_tracker
            _vs = _vt_get_tracker().state() or {}
            _mia = compute_mia(
                _vs.get("enemies") or {},
                mode_key,
                (lc or {}).get("game_time_s"),
                minimap_rect=minimap_rect,
            )
            if _mia is not None:
                zoi["mia"] = _mia
    except Exception:  # noqa: BLE001
        pass
    _mark("zoi")

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
            compute_deterministic, resolve_choices, resolve_coach_fields,
            shadow_log_det,
            shadow_log_precomputed_choices, shadow_log_precomputed_build,
            shadow_log_live_benchmark_band, shadow_log_objective_playbook,
            shadow_log_macro_response, shadow_log_aram_coach,
            shadow_log_arena_coach,
        )
        det = compute_deterministic(coach, lc, mode_key, zoi=zoi)
        # Shadow-log BEFORE resolve_choices overwrites coach["choices"] - the
        # validation log must capture the NATIVE choices the deterministic flip
        # discards, not the post-flip result.
        shadow_log_det(coach, lc, det, mode_key)
        # HZ-C1/C2: also shadow-log what the PRECOMPUTED laning table (A/B
        # trade) + HZ-B2 build-variant table (A/B build) would offer
        # (do-not-flip-blind). Fail-soft, additive, NO effect on live output.
        shadow_log_precomputed_choices(coach, lc, mode_key,
                                       lcu_snapshot=lcu_snapshot)
        shadow_log_precomputed_build(coach, lc, mode_key)
        # RC2 P5.5 (WS3): shadow-log the deterministic objective playbook row vs
        # the native Haiku objective prose (do-not-flip-blind for a future served
        # objective-field flip). Fail-soft, additive, NO effect on live output.
        shadow_log_objective_playbook(coach, lc, det, mode_key)
        # RC2 P5.7 (WS4): shadow-log the deterministic lost-objective / stagnation
        # macro response row vs the native Haiku objective prose. Fail-soft,
        # additive, NO effect on live output.
        shadow_log_macro_response(coach, lc, det, mode_key)
        # LBAND1: also shadow-log the live personal-percentile benchmark bands
        # (do-not-flip-blind). Fail-soft, additive, NO effect on live output.
        shadow_log_live_benchmark_band(coach, lc, mode_key)
        # ARAM Stage 2: assemble the WHOLE deterministic ARAM block and
        # shadow-log it beside the live Haiku block so the operator can eyeball
        # them side-by-side in a live game. SHADOW-ONLY - mutates NO served
        # field, fail-soft, ARAM in-game ticks only. The live coach flip is a
        # later operator-gated stage; this only writes data/aram_coach_shadow.jsonl.
        shadow_log_aram_coach(coach, lc, mode_key)
        # Arena Stage 2 (R76): the Arena sibling of the ARAM shadow line above.
        # SHADOW-ONLY - mutates NO served field, fail-soft, Arena in-game ticks
        # only; writes data/arena_coach_shadow.jsonl.
        shadow_log_arena_coach(coach, lc, mode_key)
        coach["choices"] = resolve_choices(coach, det)
        # Synthesize action/immediate/fight_rule/risk from deterministic
        # data when the Haiku LLM coach did not provide them (practice tool,
        # DS-engine-only games, etc.). Only fills blank fields so the
        # Haiku coach's values are always respected when present. A cleared
        # artifact (force-clear sentinel + no live game) stays empty - never
        # resurface synthesized live-looking coaching for it (item 281).
        if not _was_cleared:
            det_fields = resolve_coach_fields(coach, det, lc, mode_key)
            for k in ("action", "immediate", "fight_rule", "risk"):
                if not coach.get(k):
                    coach[k] = det_fields.get(k, "")
    except Exception:  # noqa: BLE001
        det = {"choices": [], "callouts": [], "lead_projection": {}}
        coach["choices"] = []
    _mark("deterministic")

    # B4 (RM-189): strip every coach imperative while a game is live. Placed
    # AFTER the deterministic/shadow block on purpose - the HZ-C1 shadow
    # writers above must still capture the full native branch set to disk
    # (that is the retained in-game behaviour section 6c asks for); only the
    # SERVED envelope goes quiet. Guarded by
    # tests/test_b4_live_directive_suppression.py.
    coach = suppress_live_directives(coach, health, preflip_active)
    det = suppress_live_envelope(det, health, preflip_active)
    _mark("b4_suppress")

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
        "minimap_rect": minimap_rect,
        "minimap_dots": minimap_dots,
        "zoi": zoi,
    }


