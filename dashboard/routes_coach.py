"""Coach / replay / cost routes.

Slice 2C-5 (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 5 - read-only, self-contained endpoints. All consumers live in
core.* / coaches.* - no `_VISION_TOKEN`, no Live Client probes, no
imports from web_dashboard, so no deferred-import circular guard
needed (compare with routes_diag).

Each handler receives the BaseHTTPRequestHandler (`h`) and writes its
response via `h._send(code, body, ctype)`. Module-level GET_ROUTES is
consumed by `dashboard._dispatch`.
"""
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

from core.log_scrub import scrub_log
from dashboard._context import APP_DIR
from dashboard._dispatch import equals, prefix
from dashboard._errors import GENERIC_ERROR, send_error
from dashboard._json_flags import bad_flag_body, coerce_json_flag

log = logging.getLogger("rc.web_dashboard")

# match_id format: "NA1_5438342899" - upper-case platform, digits, underscore.
# fullmatch, not match(...$): `$` also matches before a trailing newline.
_MATCH_ID_RE = re.compile(r"[A-Z0-9_]{6,40}")
# ?queue= is ASCII digits only. The old `str.isdigit()` gate let through
# Unicode digits int() rejects (a superscript two) and digit runs past the
# int-string limit - both a 500 - and silently DROPPED the filter on any other
# value, so `queue=abc` answered every queue's matches. Queue ids are at most
# four digits today; nine leaves headroom and stays far from the limit.
_QUEUE_RE = re.compile(r"[0-9]{1,9}")


def _send_json(h, code: int, obj) -> None:
    """Send `obj` as STRICT JSON. allow_nan=False makes a NaN / Infinity
    anywhere in a payload raise ValueError, which every caller's try turns
    into the generic send_error envelope - instead of a 200 body carrying a
    bare NaN token that the browser's JSON.parse rejects."""
    h._send(code, json.dumps(obj, allow_nan=False).encode("utf-8"),
            "application/json")


def _limit_param(h, default: int, lo: int = 1, hi: int = 200) -> int:
    """Clamped ?limit= query param. Cycle-8 audit (slice B): a malformed
    value (limit=abc) used to ValueError -> 500 the whole endpoint;
    degrade to the documented default instead."""
    try:
        qs = parse_qs(urlparse(h.path).query)
        limit = int((qs.get("limit") or [str(default)])[0])
    except (TypeError, ValueError):
        limit = default
    return max(lo, min(limit, hi))


def _serve_cost(h) -> None:
    # Daily spend ledger from core.cost_tracker. Tile data source.
    try:
        from core.cost_tracker import get_tracker as _gt
        t = _gt()
        payload = {
            "spend":  t.daily_spend(),
            "banner": t.banner_state(),
            "allowed": t.allow_call(),
        }
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/cost: %s", exc)
        send_error(h, exc)


def _serve_coach_trace(h) -> None:
    # Most recent coach calls (prompt + response + tokens). Used by
    # the "why did the coach say that?" dashboard tab.
    try:
        limit = _limit_param(h, default=50)
        from core.coach_trace import read_recent as _read_recent
        _send_json(h, 200, {"records": _read_recent(limit)})
    except Exception as exc:  # noqa: BLE001
        log.warning("api/coach/trace: %s", exc)
        send_error(h, exc)


def _serve_replay_matches(h) -> None:
    # AUDIT 2026-04-28 (suggestion 2.3): replay scrubber match list.
    try:
        limit = _limit_param(h, default=25)
        qs = parse_qs(urlparse(h.path).query)
        queue = (qs.get("queue") or [""])[0].strip()
        if queue and not _QUEUE_RE.fullmatch(queue):
            _send_json(h, 400, {"error": "bad queue"})
            return
        from core.replay_history import list_matches as _lm
        out = _lm(limit=limit, queue_filter=int(queue) if queue else None)
        _send_json(h, 200, {"matches": out})
    except Exception as exc:  # noqa: BLE001
        log.warning("api/replay/matches: %s", exc)
        send_error(h, exc)


def _serve_replay_match(h) -> None:
    # /api/replay/match/<match_id>
    try:
        mid = h.path[len("/api/replay/match/"):].split("?", 1)[0]
        if not _MATCH_ID_RE.fullmatch(mid):
            h._send(400, b'{"error":"bad match_id"}', "application/json")
            return
        from core.replay_history import match_detail as _md
        d = _md(mid)
        if d is None:
            _send_json(h, 404, {"error": "not found"})
            return
        _send_json(h, 200, d)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/replay/match: %s", exc)
        send_error(h, exc)


def _serve_spend_gates(h) -> None:
    # API spend gates for the Settings dev card: per-gate label + explain +
    # disabled flag, plus per-match cost (usd + tokens) averaged over the
    # last N full matches. GET only; flip a gate via POST /api/coach/toggle.
    try:
        from core.cost_tracker import get_tracker as _gt
        t = _gt()
        payload = {"gates": t.gates_state(), "per_match": t.recent_match_avg()}
        _send_json(h, 200, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/spend/gates: %s", exc)
        send_error(h, exc)


def _serve_coach_state(h) -> None:
    # Per-gate coach kill-switch state. GET only; toggle via POST.
    # Lane 8 s144: reported from the tracker's own gates_state(), the truth
    # every coach and /api/spend/gates read. This route used to hard-code five
    # modes (the registry has seven - vision and champ_select were never
    # reported), read coach_settings.json alone (the tracker merges
    # ops/rc_config.json under it) and apply its own `x.lower()`, so a
    # non-string entry 500ed here while the tracker gated on it fine.
    # `disabled` is now the disabled GATE names, not the raw persisted list.
    try:
        from core.cost_tracker import get_tracker as _gt
        gates = _gt().gates_state()
        state = {g: not s["disabled"] for g, s in gates.items()}
        disabled = [g for g, s in gates.items() if s["disabled"]]
        _send_json(h, 200, {"enabled": state, "disabled": disabled})
    except Exception as exc:  # noqa: BLE001
        log.warning("api/coach/state: %s", exc)
        send_error(h, exc)


# -- POST handlers (slice 2C-7c) --------------------------------------
# RM-762 (2026-10-22): POST /api/speak and its handler were removed - no
# in-tree sender, no token, and a remote command-injection path until
# edd0e2622. Pinned by tests/test_dead_endpoint_cleanup_item186.py.


def _serve_branch_review(h) -> None:
    # B4-e (RM-189): the POST-GAME half of the compliance split. In-game, RC
    # captures the decision branch set silently and renders nothing; this
    # route reads one match's series back for review afterwards. Read-only,
    # no Anthropic call, no live probe.
    #
    # ?run=<game_run_id> selects a match; omitted serves the most recent.
    try:
        from core.branch_review import load_branch_series
        qs = parse_qs(urlparse(h.path).query)
        run = (qs.get("run") or [""])[0].strip() or None
        out = load_branch_series(run)
        _send_json(h, 200, out)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/branch-review: %s", exc)
        send_error(h, exc)


def _serve_branch_review_runs(h) -> None:
    # Match picker for the review view - the runs present in the corpus tail.
    try:
        from core.branch_review import list_recent_runs
        runs = list_recent_runs(limit=_limit_param(h, 20, hi=100))
        _send_json(h, 200, {"runs": runs})
    except Exception as exc:  # noqa: BLE001
        log.warning("api/branch-review/runs: %s", exc)
        send_error(h, exc)


# s144 true-audit cycle 107: True once a failed champ-select shadow pass has
# been logged at WARNING; reset by the next pass that completes. A race between
# two handler threads costs at most one extra WARNING line.
_SHADOW_WARNED = False


def _pick_view(payload) -> dict | None:
    """The pick state coach_pick reads out of a request body, or None when
    coach_pick refuses the body (not an object, or no usable champion).

    coach_pick's OWN rules, imported rather than restated: names sanitised and
    length-capped (`_name`), list fields only a list or tuple of at most
    `_MAX_NAMES` entries (`_names`), and ARAM from a real `true` or from a queue
    that maps to the ARAM mode (`_mode_key`). The deterministic advisor reads
    this view, so it answers the request Haiku answered, not the raw body.

    The shadow writer is NOT given this view: it applies the same rules to the
    raw body itself, and the name rule is not idempotent (a marker can grow a
    63-character name past the 64-character cap, so a second pass would refuse
    a name the prompt carried)."""
    from coaches.champ_select_coach import _mode_key, _name, _names
    if not isinstance(payload, dict):
        return None
    my_champion = _name(payload.get("my_champion"))
    if not my_champion:
        return None
    return {
        "my_champion": my_champion,
        "is_aram": payload.get("is_aram") is True or _mode_key(payload) == "aram",
        "my_team": _names(payload.get("my_team")),
        "their_team": _names(payload.get("their_team")),
        "bench": _names(payload.get("bench")),
    }


def _exc_text(exc: BaseException, secret: str) -> str:
    """Exception text for a log line: the secret removed, control characters
    escaped so the text cannot start a log line, a broken __str__ survived."""
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not hide the cause
        text = "<exception text unavailable>"
    secret = secret if isinstance(secret, str) else ""
    # Longest first, so the bare key cannot leave a padded copy's edges behind.
    for s in sorted({secret, secret.strip()} - {""}, key=len, reverse=True):
        text = text.replace(s, "[redacted]")
    return scrub_log(text)


def _champ_select_shadow(payload, view: dict, result) -> None:
    """Do-not-flip-blind shadow: record the deterministic pick-advisor beside
    the live Haiku advice so the precompute path can be validated offline
    before any flip. Never raises. A failure (both callees are fail-soft, so in
    practice an import failure) is a WARNING once, then DEBUG until a pass
    completes - a silent DEBUG-only failure would stop the corpus growing with
    nothing in the log."""
    global _SHADOW_WARNED
    try:
        from core.champ_select_advisor_deterministic import advise_pick
        from core.champ_select_shadow import log_champ_select_advice
        log_champ_select_advice(payload, native=result,
                                deterministic=advise_pick(view))
    except Exception as exc:  # noqa: BLE001 - never blocks the coach reply
        level = logging.DEBUG if _SHADOW_WARNED else logging.WARNING
        _SHADOW_WARNED = True
        log.log(level, "champ-select shadow skipped: %s: %s",
                type(exc).__name__, _exc_text(exc, ""))
        return
    _SHADOW_WARNED = False


def _serve_champ_select_coach_post(h, payload) -> None:
    # Live champ-select coaching - Haiku call with the current pick state.
    # Dashboard POSTs whenever picks change (debounced).
    # Body: {is_aram, queue_id, my_champion, my_team, their_team, bench}
    api_key = ""
    try:
        from coaches._base_coach import read_api_key
        from coaches.champ_select_coach import coach_pick
        # 2026-09-29: this route used to read API-Key-Claude.txt and NOTHING
        # else, so once the operator rotated the key into ANTHROPIC_API_KEY
        # and deleted the file it passed "" to coach_pick and champ-select
        # coaching went silently off with a valid key in the environment.
        # Delegating to the shared reader gives the whole process ONE order
        # (env first, file fallback) instead of a seventh local variant;
        # dashboard/_screen_read.py:89 already imports this same helper, so
        # no new package edge. read_api_key never raises, so the route keeps
        # its fail-soft posture - "" reaches coach_pick's own missing-key
        # guard and answers 200 with "(API key missing - coach disabled)".
        api_key = read_api_key(APP_DIR)
        result = coach_pick(payload or {}, api_key)
        # s144 true-audit cycle 107 (RM-1381): the advisor used to get the
        # RAW body - is_aram read with bool() (so "false" meant ARAM), queue_id
        # ignored (so an ARAM queue meant Rift), lists uncapped and unsanitised
        # - and the shadow row's deterministic half described another request.
        # It now reads coach_pick's view, and runs only for a body coach_pick
        # accepted (the shadow writes no row for any other).
        view = _pick_view(payload)
        if view is not None:
            _champ_select_shadow(payload, view, result)
        _send_json(h, 200, result)
    except Exception as exc:  # noqa: BLE001
        # One log line, the key removed: send_error would log str(exc)
        # verbatim, and an HTTP layer can quote a header value back.
        log.warning("api/champ-select-coach: %s: %s",
                    type(exc).__name__, _exc_text(exc, api_key))
        _send_json(h, 500, {"error": GENERIC_ERROR})


def _serve_aram_comp_verdict_post(h, payload) -> None:
    # Deterministic ZERO-spend ARAM bench verdict (no Anthropic call). Delegates
    # to core.aram_comp_verdict.comp_verdict and passes its dict through verbatim
    # ({ok, recommendation, swap_to, variant_to, reason, confidence, factors}).
    # Body (all optional): {my_champion, my_team, their_team, bench, variants,
    # current_variant}.
    try:
        from core.aram_comp_verdict import comp_verdict
        verdict = comp_verdict(payload if isinstance(payload, dict) else {})
        _send_json(h, 200, verdict)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/aram-comp-verdict: %s", exc)
        send_error(h, exc)


def _serve_coach_toggle_post(h, payload) -> None:
    # AUDIT 2026-04-28 (proposal 2.2): per-mode coach kill-switches.
    # Body: {mode: "aram", disabled: true}
    try:
        mode = str(payload.get("mode") or "").strip().lower()
        # RM-414: parsed, never bare-truthy. `bool(payload.get("disabled"))`
        # read {"disabled": "false"} as True, engaged the kill-switch and
        # PERSISTED it to coach_settings.json. Absent keeps the old default
        # (False); an ambiguous value is a 400 BEFORE anything is written.
        # Rule: dashboard/_json_flags.py.
        disabled = coerce_json_flag(payload, "disabled", False)
        from core.cost_tracker import GATES
        if mode not in set(GATES):
            h._send(400, b'{"error":"invalid mode"}', "application/json")
            return
        if disabled is None:
            h._send(400, bad_flag_body("disabled"), "application/json")
            return
        from core.cost_tracker import get_tracker as _gt
        cur = _gt().set_coach_disabled(mode, disabled)
        _send_json(h, 200, {"ok": True, "disabled_modes": cur})
    except Exception as exc:  # noqa: BLE001
        log.warning("api/coach/toggle: %s", exc)
        send_error(h, exc)


# -- route table ------------------------------------------------------

# Ordering: more-specific paths first. /api/replay/match/ uses prefix()
# for the trailing match_id; everything else is exact (with optional
# query string handled by equals()).
GET_ROUTES = [
    (equals("/api/cost"),             _serve_cost),
    (equals("/api/spend/gates"),      _serve_spend_gates),
    (equals("/api/coach/trace"),      _serve_coach_trace),
    (equals("/api/coach/state"),      _serve_coach_state),
    (equals("/api/replay/matches"),   _serve_replay_matches),
    (prefix("/api/replay/match/"),    _serve_replay_match),
    # More-specific path first: /runs must not be swallowed by the bare route.
    (equals("/api/branch-review/runs"), _serve_branch_review_runs),
    (equals("/api/branch-review"),    _serve_branch_review),
]

POST_ROUTES = [
    (equals("/api/champ-select-coach"),  _serve_champ_select_coach_post),
    (equals("/api/coach/toggle"),        _serve_coach_toggle_post),
    (equals("/api/aram-comp-verdict"),   _serve_aram_comp_verdict_post),
]
