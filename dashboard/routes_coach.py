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
from dashboard._errors import send_error
import logging
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR, read_json
from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")


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
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/cost: %s", exc)
        send_error(h, exc)


def _serve_coach_trace(h) -> None:
    # Most recent coach calls (prompt + response + tokens). Used by
    # the "why did the coach say that?" dashboard tab.
    try:
        limit = _limit_param(h, default=50)
        from core.coach_trace import read_recent as _read_recent
        h._send(200, json.dumps({"records": _read_recent(limit)}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/coach/trace: %s", exc)
        send_error(h, exc)


def _serve_replay_matches(h) -> None:
    # AUDIT 2026-04-28 (suggestion 2.3): replay scrubber match list.
    try:
        limit = _limit_param(h, default=25)
        qs = parse_qs(urlparse(h.path).query)
        queue = (qs.get("queue") or [""])[0]
        from core.replay_history import list_matches as _lm
        out = _lm(limit=limit, queue_filter=int(queue) if queue.isdigit() else None)
        h._send(200, json.dumps({"matches": out}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/replay/matches: %s", exc)
        send_error(h, exc)


def _serve_replay_match(h) -> None:
    # /api/replay/match/<match_id>
    try:
        mid = h.path[len("/api/replay/match/"):].split("?", 1)[0]
        # match_id format: "NA1_5438342899" - alnum + underscore only.
        import re as _re
        if not _re.match(r"^[A-Z0-9_]{6,40}$", mid):
            h._send(400, b'{"error":"bad match_id"}', "application/json")
            return
        from core.replay_history import match_detail as _md
        d = _md(mid)
        if d is None:
            h._send(404, json.dumps({"error": "not found"}).encode(),
                    "application/json")
            return
        h._send(200, json.dumps(d).encode("utf-8"), "application/json")
    except Exception as exc:
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
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/spend/gates: %s", exc)
        send_error(h, exc)


def _serve_coach_state(h) -> None:
    # Per-mode coach kill-switch state. GET only; toggle via POST.
    try:
        from core.cost_tracker import _COACH_CFG, CFG_COACH_DISABLED_MODES
        cfg = read_json(str(_COACH_CFG)) if _COACH_CFG.exists() else {}
        disabled = cfg.get(CFG_COACH_DISABLED_MODES, []) or []
        modes = ["sr", "aram", "arena", "brawl", "tft"]
        state = {m: (m not in {x.lower() for x in disabled}) for m in modes}
        h._send(200, json.dumps({"enabled": state, "disabled": disabled}).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/coach/state: %s", exc)
        send_error(h, exc)


# -- POST handlers (slice 2C-7c) --------------------------------------


def _serve_speak_post(h, payload) -> None:
    # Opt-in voice TTS for the Right Now headline. Body: {text, rate?}.
    # Throttled + deduped server-side via voice_coach module.
    try:
        from coaches.voice_coach import speak
        text = (payload.get("text") or "").strip()
        rate = int(payload.get("rate") or 0)
        if not text:
            h._send(400, b'{"error":"empty_text"}', "application/json"); return
        spoken = speak(text, rate=rate)
        h._send(200, json.dumps({"ok": True, "spoken": spoken}).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/speak: %s", exc)
        send_error(h, exc)


def _serve_champ_select_coach_post(h, payload) -> None:
    # Live champ-select coaching - Haiku call with the current pick state.
    # Dashboard POSTs whenever picks change (debounced).
    # Body: {is_aram, queue_id, my_champion, my_team, their_team, bench}
    try:
        from coaches.champ_select_coach import coach_pick
        api_key = ""
        _key_path = APP_DIR / "API-Key-Claude.txt"
        if _key_path.exists():
            api_key = _key_path.read_text(encoding="utf-8").strip()
        result = coach_pick(payload or {}, api_key)
        # Do-not-flip-blind shadow: record the deterministic pick-advisor
        # alongside the live Haiku advice so the precompute path can be
        # validated offline before any flip. Fail-soft; never blocks the route.
        try:
            from core.champ_select_advisor_deterministic import advise_pick
            from core.champ_select_shadow import log_champ_select_advice
            log_champ_select_advice(payload or {}, native=result,
                                    deterministic=advise_pick(payload or {}))
        except Exception as exc:
            log.debug("champ-select shadow: %s", exc)
        h._send(200, json.dumps(result).encode(), "application/json")
    except Exception as exc:
        log.warning("api/champ-select-coach: %s", exc)
        send_error(h, exc)


def _serve_aram_comp_verdict_post(h, payload) -> None:
    # Deterministic ZERO-spend ARAM bench verdict (no Anthropic call). Delegates
    # to core.aram_comp_verdict.comp_verdict and passes its dict through verbatim
    # ({ok, recommendation, swap_to, variant_to, reason, confidence, factors}).
    # Body (all optional): {my_champion, my_team, their_team, bench, variants,
    # current_variant}.
    try:
        from core.aram_comp_verdict import comp_verdict
        verdict = comp_verdict(payload if isinstance(payload, dict) else {})
        h._send(200, json.dumps(verdict).encode(), "application/json")
    except Exception as exc:
        log.warning("api/aram-comp-verdict: %s", exc)
        send_error(h, exc)


def _serve_coach_toggle_post(h, payload) -> None:
    # AUDIT 2026-04-28 (proposal 2.2): per-mode coach kill-switches.
    # Body: {mode: "aram", disabled: true}
    try:
        mode = str(payload.get("mode") or "").strip().lower()
        disabled = bool(payload.get("disabled"))
        from core.cost_tracker import GATES
        if mode not in set(GATES):
            h._send(400, b'{"error":"invalid mode"}', "application/json")
            return
        from core.cost_tracker import get_tracker as _gt
        cur = _gt().set_coach_disabled(mode, disabled)
        h._send(200, json.dumps({"ok": True,
                                  "disabled_modes": cur}).encode(),
                "application/json")
    except Exception as exc:
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
]

POST_ROUTES = [
    (equals("/api/speak"),               _serve_speak_post),
    (equals("/api/champ-select-coach"),  _serve_champ_select_coach_post),
    (equals("/api/coach/toggle"),        _serve_coach_toggle_post),
    (equals("/api/aram-comp-verdict"),   _serve_aram_comp_verdict_post),
]
