"""Diagnostics / vision / OCR / decisions routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 4 - read-only diag and vision endpoints. Several reach the
in-process vision server at 127.0.0.1:8889 (using `_VISION_TOKEN`)
and the Live Client API at 192.168.8.237:2999 (https, self-signed).

Each route receives the BaseHTTPRequestHandler (`h`) as its sole
argument and uses `h._send(code, body, ctype)` to write the response.
Module-level GET_ROUTES is consumed by `dashboard._dispatch`.

`_VISION_TOKEN` is deferred-imported from web_dashboard inside the
OCR handlers to avoid a circular import at module load time.
`diagnostics_cached` is imported directly from `dashboard._diagnostics`
(Tier 2 #2 helper-shake - no longer routed through web_dashboard).
"""
import json
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
    except Exception as exc:
        log.warning("api/decisions: %s", exc)
        h._send(500, b'{"error":"decisions_read_failed"}', "application/json")


# Tier 4 #18 (2026-05-01): tail of resolved decisions for the dashboard's
# "Recent Coach Calls" panel. Reads the JSONL log directly so we don't
# depend on the in-memory pending store (which only holds active
# decisions). Cap is 50 - past that the dashboard panel doesn't add value.
_LOG_PATH = APP_DIR / "data" / "decisions_log.jsonl"


def _serve_decisions_log(h) -> None:
    """GET /api/decisions/log?limit=N - last N resolved decisions, newest
    first. N caps at 50. Tolerates a torn final line (mid-write append)."""
    try:
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(h.path).query)
        try:
            limit = max(1, min(50, int((qs.get("limit") or ["20"])[0])))
        except ValueError:
            limit = 20
        if not _LOG_PATH.exists():
            h._send(200, b'{"entries":[]}', "application/json"); return
        # Read whole file - bounded by the JSONL's natural size cap (the
        # detector emits at most ~5 decisions per game).
        try:
            text = _LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("api/decisions/log read: %s", exc)
            h._send(200, b'{"entries":[]}', "application/json"); return
        lines = text.splitlines()
        # Take last N candidates (we'll skip torn ones, so over-fetch a bit
        # so a torn tail line doesn't shrink the result).
        candidates = lines[-(limit + 4):]
        entries: list = []
        for line in candidates:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if isinstance(e, dict) and e.get("id"):
                    entries.append(e)
            except json.JSONDecodeError:
                continue  # tolerate torn append
        # Newest first
        entries = list(reversed(entries))[:limit]
        h._send(200, json.dumps({"entries": entries}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/decisions/log: %s", exc)
        h._send(500, b'{"error":"log_read_failed"}', "application/json")


def _serve_diagnostics(h) -> None:
    try:
        payload = diagnostics_cached()
        h._send(200, payload, "application/json")
    except Exception as exc:
        log.warning("api/diagnostics: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


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
        except Exception:
            pass
        from core.vision_tesseract import configure_drop_fields
        configure_drop_fields(drop)
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
    except Exception as exc:
        log.warning("api/ocr: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# ── route table ──────────────────────────────────────────────────────
# ── POST handlers (slice 2C-7b) ──────────────────────────────────────


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
        choice = (payload.get("choice") or "").strip()
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
            h._send(404, b'{"error":"id not pending"}', "application/json"); return
        h._send(200, json.dumps({"ok": True, "id": entry["id"],
                                  "choice": entry["choice"]}).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/decisions POST: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_decisions_heartbeat(h) -> None:
    """ADR-007 (s169): GET /api/decisions/heartbeat → loop liveness snapshot.

    File-backed read of data/decisions_heartbeat.json (written by the
    DecisionLoop in the Phase 3 supervisor process). The dashboard
    #trigger-pill polls this at ~2 Hz to render the eval counter +
    green/amber/red alive indicator."""
    try:
        from core.decision_detector import read_heartbeat
        payload = read_heartbeat()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/decisions/heartbeat: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_decisions_respond_active_post(h, payload) -> None:
    """ADR-007 (s169): POST /api/decisions/respond_active
    Body: {choice_index: 0|1, dismiss?: bool, note?: str}

    Resolves the FIRST pending decision by mapping `choice_index` →
    `options[choice_index]` (or "skip" when dismiss=true). Intended for
    the Game-PC keybind listener - single endpoint that doesn't require
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
        dismiss = bool(payload.get("dismiss", False))
        if dismiss:
            choice = "skip"
        else:
            try:
                idx = int(payload.get("choice_index"))
            except (TypeError, ValueError):
                h._send(400, b'{"error":"choice_index must be int 0 or 1"}',
                        "application/json"); return
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
            h._send(404, b'{"error":"decision vanished mid-respond"}',
                    "application/json"); return
        h._send(200, json.dumps({
            "ok": True, "id": entry["id"], "choice": entry["choice"],
        }).encode(), "application/json")
    except Exception as exc:
        log.warning("api/decisions/respond_active: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


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
