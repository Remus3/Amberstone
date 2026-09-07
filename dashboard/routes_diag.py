"""Diagnostics / vision / OCR / decisions routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 4 - diag and vision endpoints. ONE handler (`_serve_ocr`) reaches
the in-process vision server at 127.0.0.1:8889 using `_VISION_TOKEN`.

Three claims were CORRECTED here on 2026-08-30 (lane 8 cycle 18) after
being checked against the tree rather than inherited:
  - this module does NOT touch the Live Client API at {RC_GAME_HOST}:2999.
    `2999`, `GAME_HOST` and `game_host` have zero hits in this file outside
    the sentence that used to claim it. A name that appears only where it
    is DESCRIBED and never where it is USED is a name this module does not
    use (the same tell that produced the cycle-17 `TowerTeam` defect);
  - the group is not "read-only" - `_serve_decision_choice_post` and
    `_serve_decisions_respond_active_post` both WRITE through
    `DecisionStore.record_choice`;
  - `_VISION_TOKEN` is deferred-imported inside ONE handler, not "the OCR
    handlers" plural.

GET routes receive the BaseHTTPRequestHandler (`h`) as their sole
argument; POST routes receive `(h, payload)` - `_serve_decision_choice_post`
and `_serve_decisions_respond_active_post` both take the parsed body. (The
"sole argument" line here used to be unqualified, and was still wrong after
the three corrections above were made; found by the adversarial pass, not by
the pass that wrote them.) All of them use `h._send(code, body, ctype)`.
GET_ROUTES and POST_ROUTES are consumed by `dashboard._dispatch`
(`dashboard/_dispatch.py:114` and `:198`).

ERROR ENVELOPE, stated as narrowly as it is actually enforced: every
EXCEPTION path in this module goes through `dashboard._errors.send_error`,
which puts a generic line on the wire and the raw cause in `logs/`.
`tests/test_routes_diag_lane8_cycle18.py::test_every_five_hundred_in_this_module_routes_through_send_error`
fails on an `except` block that answers 5xx without it. It does NOT forbid
every hand-rolled 5xx: the two curated `h._send(503, ...)` calls in normal
flow are allowed on purpose, because a constant literal body carries no
exception text, and a companion test pins their COUNT at 2 so a third cannot
appear unnoticed. An earlier draft of this paragraph claimed the test caught
any hand-rolled 5xx anywhere; it did not, and promising more than a guard
delivers is how the RM-134 guard came to be trusted while this module leaked.
`diagnostics_cached` is imported directly from `dashboard._diagnostics`
(Tier 2 #2 helper-shake - no longer routed through web_dashboard).
"""
import json
from dashboard._errors import send_error
import logging
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR, read_json
from dashboard._diagnostics import diagnostics_cached
from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")


def _serve_vision_state(h) -> None:
    # Fog-of-war state derived by core/vision_tracker from Live Client
    # position freshness. Empty {} when no game running.
    d = read_json("data/vision_state.json") or {}
    h._send(200, json.dumps(d).encode("utf-8"), "application/json")


def _serve_decisions(h) -> None:
    # Pending coachable decisions detected by core/decision_detector.
    # Empty list when no game / no triggers.
    #
    # Tier 3 #15 (2026-05-01): instantiate DecisionStore directly instead
    # of routing through get_loop(). The store is a thin file-I/O wrapper
    # over data/decisions_pending.json - no need to touch the singleton's
    # threading machinery just to read the file. Decouples the API from
    # the loop's process location: a future move of the detector to
    # agents/supervisor.py won't break this endpoint.
    try:
        from core.decision_detector import DecisionStore
        pending = DecisionStore().list_pending()
        h._send(200, json.dumps({"pending": pending}).encode("utf-8"),
                "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/decisions: %s", exc)
        # Lane 8 cycle 18: the wire string is unchanged (it was already a
        # curated constant, not raw exception text - grepped, zero consumers
        # match on it). Routed through the shared envelope so this module has
        # ONE error path, and so the raw cause is logged even if this call
        # site's own log.warning is ever dropped.
        send_error(h, exc, public_msg="decisions_read_failed")


# Tier 4 #18 (2026-05-01): tail of resolved decisions for the dashboard's
# "Recent Coach Calls" panel. Reads the JSONL log directly so we don't
# depend on the in-memory pending store (which only holds active
# decisions). Cap is 50 - past that the dashboard panel doesn't add value.
_LOG_PATH = APP_DIR / "data" / "decisions_log.jsonl"


def _serve_decisions_log(h) -> None:
    """GET /api/decisions/log?limit=N - last N resolved decisions, newest
    first. N caps at 50. Tolerates a torn final line (mid-write append)."""
    try:
        # Lane 8 cycle 18: dropped a function-local re-import that shadowed the
        # module-level one on line 20 (ruff cannot see it - ruff.toml:27 turns
        # F401 off globally, so neither import was ever flagged).
        qs = parse_qs(urlparse(h.path).query)
        try:
            limit = max(1, min(50, int((qs.get("limit") or ["20"])[0])))
        except ValueError:
            limit = 20
        if not _LOG_PATH.exists():
            h._send(200, b'{"entries":[]}', "application/json"); return
        # Reads the whole file. The old comment here claimed this was
        # "bounded by the JSONL's natural size cap"; there is no cap - the
        # log is append-only and nothing rotates it (`core/log_retention.py`
        # covers no `.jsonl`, grepped 2026-08-30). The real bound is write
        # VOLUME, at most ~5 decisions per game: the live file was 3775
        # bytes on 2026-08-30 having been appended to since June. Low risk
        # today, but it grows without limit - RM-238.
        try:
            text = _LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("api/decisions/log read: %s", exc)
            h._send(200, b'{"entries":[]}', "application/json"); return
        lines = text.splitlines()
        # Lane 8 cycle 18: this over-fetched by a FIXED `+4` and then dropped
        # blank and torn lines from that window, so any tail damage came
        # straight off the result - measured at 30 good rows plus 10 torn
        # trailing lines returning 14 entries for limit=20, silently short by
        # 6, with a 200. Walk backwards from the end instead and stop once
        # `limit` VALID entries are in hand, so junk costs nothing.
        entries: list = []
        for line in reversed(lines):
            if len(entries) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn append
            if isinstance(e, dict) and e.get("id"):
                entries.append(e)
        # `entries` is already newest-first - it was built from the tail back.
        h._send(200, json.dumps({"entries": entries}).encode("utf-8"),
                "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/decisions/log: %s", exc)
        # Same as the sibling above - curated wire string preserved verbatim,
        # routed through the shared envelope.
        send_error(h, exc, public_msg="log_read_failed")


def _serve_diagnostics(h) -> None:
    try:
        payload = diagnostics_cached()
        h._send(200, payload, "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/diagnostics: %s", exc)
        # Lane 8 cycle 18: was json.dumps({"error": str(exc)}). This endpoint
        # reaches the widest surface of the three that hand-rolled the envelope
        # (dashboard/server.py:35 binds "::"), and diagnostics_cached() raises
        # with absolute paths in the message. send_error keeps the raw cause in
        # logs/ and puts only the generic line on the wire.
        send_error(h, exc)


def _serve_ocr(h) -> None:
    # Pull latest frame from vision server, run Tesseract on configured fields.
    try:
        import time
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        # Check Live Client relay freshness - if fresh (<3s), drop OCR
        # fields the API authoritatively provides (cs, kda, gold, level,
        # hp, mana, score_blue, score_red, timer).
        _AUTH = {"X-RC-Token": _VISION_TOKEN}
        drop = set()
        try:
            with _ur.urlopen(
                _ur.Request("http://127.0.0.1:8889/latest-liveclient",
                            headers=_AUTH), timeout=1
            ) as r:
                lc = json.loads(r.read())
            if (time.time() - lc.get("ts", 0)) < 3:
                drop = {"cs", "kda", "gold", "level", "hp", "mana",
                        "score_blue", "score_red", "timer"}
        except Exception as exc:  # noqa: BLE001
            # Lane 8 cycle 18: this was a bare `pass`. Falling back to "drop
            # nothing" is the correct behaviour, but it silently changes what
            # OCR returns, so it must leave a trail - otherwise a down relay
            # presents as OCR quietly re-reading fields the Live Client owns.
            log.debug("api/ocr: liveclient relay probe failed (%s: %s) - "
                      "dropping no fields", type(exc).__name__, exc)
        # Lane 8 cycle 18: `_DROP_FIELDS` is a MODULE GLOBAL
        # (core/vision_tesseract.py:539), rebound by configure_drop_fields
        # (:552) and honoured by read_fast_fields at :650 REGARDLESS of an
        # explicit fields= argument. core/vision_routing.py:97 calls
        # read_fast_fields in this same process, so this diagnostic endpoint
        # was silently disabling up to 9 fields for the COACH's OCR path until
        # the next /api/ocr call happened to reset them. Save and restore, so a
        # diagnostic GET has no lasting effect on anything else.
        from core import vision_tesseract as _vt
        _prev_drop = set(_vt._DROP_FIELDS)
        _vt.configure_drop_fields(drop)
        try:
            req = _ur.Request("http://127.0.0.1:8889/latest-frame", headers=_AUTH)
            with _ur.urlopen(req, timeout=4) as r:
                frame = json.loads(r.read())
            from core.vision_tesseract import read_fast_fields, _regions
            t0 = time.time()
            fields = read_fast_fields(frame["b64"])
            ms = int((time.time() - t0) * 1000)
            payload = {"fields": fields, "regions_used": list(_regions().keys()),
                       "frame_age_s": time.time() - frame.get("ts", 0),
                       "ocr_ms": ms}
            h._send(200, json.dumps(payload).encode(), "application/json")
        finally:
            # Restore unconditionally - the return path AND every
            # exception path, or a failed OCR call leaves the coach's
            # fields disabled, which is the worse of the two states.
            _vt.configure_drop_fields(_prev_drop)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/ocr: %s", exc)
        # Lane 8 cycle 18: was json.dumps({"error": str(exc)}). The urlopen
        # failures raised in this body carry the relay URL, and a Tesseract
        # failure carries local install paths - neither belongs on the wire.
        send_error(h, exc)


# -- route table ------------------------------------------------------
# -- POST handlers (slice 2C-7b) --------------------------------------


def _serve_decision_choice_post(h, payload) -> None:
    # POST /api/decisions/<id>  body: {choice: <one of decision.options + "skip">, note?}
    # Records the player's choice and removes the decision from pending.
    #
    # Tier 3 #15 (2026-05-01): same singleton-decoupling as the GET - the
    # write path is also pure file I/O and doesn't need the loop's
    # threading.Lock since DecisionStore has its own.
    #
    # ADR-007 (s169): per-decision options vary now (was hardcoded
    # contest|give|skip; new detectors use safe|punish, reset|force, etc).
    # Validate against the actual pending decision's options instead.
    try:
        decision_id = h.path[len("/api/decisions/"):].split("?", 1)[0]
        if not decision_id:
            h._send(400, b'{"error":"id required"}', "application/json"); return
        # Lane 8 cycle 18: `(payload.get("choice") or "").strip()` assumed a
        # string, so a JSON number raised AttributeError and the handler
        # answered 500 with the internal type name. A wrong TYPE is the same
        # class of caller error as a missing value - answer it the same way.
        raw_choice = payload.get("choice")
        if raw_choice is not None and not isinstance(raw_choice, str):
            h._send(400, b'{"error":"choice must be a string"}',
                    "application/json"); return
        choice = (raw_choice or "").strip()
        if not choice or len(choice) > 32:
            h._send(400, b'{"error":"choice required (<=32 chars)"}',
                    "application/json"); return
        from core.decision_detector import DecisionStore
        store = DecisionStore()
        # Verify choice is valid for THIS decision's options (+ "skip" always allowed).
        pending = store.list_pending()
        match = next((d for d in pending if d.get("id") == decision_id), None)
        if match is None:
            h._send(404, b'{"error":"id not pending"}', "application/json"); return
        allowed = set(match.get("options") or [])
        allowed.add("skip")
        if choice not in allowed:
            h._send(400, json.dumps({
                "error": "choice not in options",
                "allowed": sorted(allowed),
            }).encode(), "application/json"); return
        extra = {}
        if "note" in payload:
            extra["note"] = str(payload.get("note") or "")[:500]
        entry = store.record_choice(decision_id, choice, extra=extra)
        if entry is None:
            # Lane-8 cycle 12: record_choice returns None for "not pending"
            # AND for a transient write failure that deliberately left the
            # decision in place. Reporting the second as a permanent 404
            # tells the caller to stop when it should retry.
            if any(d.get("id") == decision_id for d in store.list_pending()):
                h._send(503, b'{"error":"could not record that choice right '
                             b'now - it is still pending, please retry"}',
                        "application/json"); return
            h._send(404, b'{"error":"id not pending"}', "application/json"); return
        h._send(200, json.dumps({"ok": True, "id": entry["id"],
                                  "choice": entry["choice"]}).encode(),
                "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/decisions POST: %s", exc)
        # Lane 8 cycle 18: was json.dumps({"error": str(exc)}), which put
        # attribute/type detail from a wrong-typed body straight back to the
        # caller. The typed rejection above now handles the common case as a
        # 400; this stays the last resort.
        send_error(h, exc)


def _serve_decisions_heartbeat(h) -> None:
    """ADR-007 (s169): GET /api/decisions/heartbeat -> loop liveness snapshot.

    File-backed read of data/decisions_heartbeat.json (written by the
    DecisionLoop in the Phase 3 supervisor process).

    NO CURRENT UI CONSUMER. This docstring used to say "the dashboard
    #trigger-pill polls this at ~2 Hz"; that pill was deleted with the
    header second row in `dee9cc94`, and `web/css/panels/map_state.css:119`
    records the removal while noting the backend was deliberately kept.
    Corrected 2026-08-30 (lane 8 cycle 12) after the stale line was used as
    evidence that an operator would see a heartbeat change. Grep before
    trusting it again: `#trigger-pill` and `/api/decisions/heartbeat` both
    have zero hits under web/. The endpoint remains reachable by curl and is
    the only way to read `detector_errors` today."""
    try:
        from core.decision_detector import read_heartbeat
        payload = read_heartbeat()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/decisions/heartbeat: %s", exc)
        send_error(h, exc)


def _serve_decisions_respond_active_post(h, payload) -> None:
    """ADR-007 (s169): POST /api/decisions/respond_active
    Body: {choice_index: 0|1, dismiss?: bool, note?: str}

    Resolves the FIRST pending decision by mapping `choice_index` ->
    `options[choice_index]` (or "skip" when dismiss=true). Intended for
    the Legion keybind listener - single endpoint that doesn't require
    the caller to know which decision is currently pending or which
    options apply, so Numpad 1 / Numpad 2 / Numpad 0 stay constant
    across detector types."""
    try:
        from core.decision_detector import DecisionStore
        store = DecisionStore()
        pending = store.list_pending()
        if not pending:
            h._send(404, b'{"error":"no pending decision"}',
                    "application/json"); return
        active = pending[0]
        active_id = active.get("id") or ""
        options = active.get("options") or []
        # Lane 8 cycle 18: this was `bool(payload.get("dismiss", False))`, so
        # ANY non-empty JSON string was truthy - {"dismiss": "false"} threw the
        # caller's real choice away and journalled a dismissal, and
        # record_choice is irreversible. Same wrong-type class already fixed
        # for `choice` in the sibling handler; this one had no guard.
        raw_dismiss = payload.get("dismiss", False)
        if not isinstance(raw_dismiss, bool):
            h._send(400, b'{"error":"dismiss must be true or false"}',
                    "application/json"); return
        dismiss = raw_dismiss
        if dismiss:
            choice = "skip"
        else:
            # Lane 8 cycle 18: `int(...)` silently TRUNCATED, so 1.9 resolved
            # to options[1] and 0.9 to options[0] - a client with an off-by-a
            # -fraction index had a different choice journalled than it asked
            # for, with a 200 back. `True` is an int in Python and was
            # accepted as index 1; reject that too.
            raw_idx = payload.get("choice_index")
            if isinstance(raw_idx, bool) or not isinstance(raw_idx, int):
                h._send(400, b'{"error":"choice_index must be int 0 or 1"}',
                        "application/json"); return
            idx = raw_idx
            if idx < 0 or idx >= len(options):
                h._send(400, json.dumps({
                    "error": "choice_index out of range",
                    "options": options,
                }).encode(), "application/json"); return
            choice = options[idx]
        extra = {"via": "respond_active"}
        if "note" in payload:
            extra["note"] = str(payload.get("note") or "")[:500]
        entry = store.record_choice(active_id, choice, extra=extra)
        if entry is None:
            # See the sibling handler above (lane-8 cycle 12): a failed
            # write leaves the decision pending and is retryable, which is
            # not the same as the decision having vanished.
            if any(d.get("id") == active_id for d in store.list_pending()):
                h._send(503, b'{"error":"could not record that choice right '
                             b'now - it is still pending, please retry"}',
                        "application/json"); return
            h._send(404, b'{"error":"decision vanished mid-respond"}',
                    "application/json"); return
        h._send(200, json.dumps({
            "ok": True, "id": entry["id"], "choice": entry["choice"],
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/decisions/respond_active: %s", exc)
        send_error(h, exc)


GET_ROUTES = [
    (equals("/api/vision-state"),         _serve_vision_state),
    (equals("/api/decisions"),            _serve_decisions),
    (equals("/api/decisions/log"),        _serve_decisions_log),
    (equals("/api/decisions/heartbeat"),  _serve_decisions_heartbeat),
    (equals("/api/diagnostics"),          _serve_diagnostics),
    (equals("/api/ocr"),                  _serve_ocr),
]

# /api/decisions/<id> uses prefix() - the legacy elif used
# `startswith("/api/decisions/")`. The trailing slash is required so
# this doesn't shadow the GET on `/api/decisions` (no id).
#
# /api/decisions/respond_active uses equals() and is registered BEFORE
# the prefix so the dispatcher matches it first (otherwise the prefix
# would consume "/api/decisions/respond_active" and treat
# "respond_active" as the decision id).
POST_ROUTES = [
    (equals("/api/decisions/respond_active"), _serve_decisions_respond_active_post),
    (prefix("/api/decisions/"),               _serve_decision_choice_post),
]
