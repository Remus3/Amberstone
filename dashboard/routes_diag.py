"""Diagnostics / vision / OCR / decisions routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 4 — read-only diag and vision endpoints. Several reach the
in-process vision server at 127.0.0.1:8889 (using `_VISION_TOKEN`)
and the Live Client API at 192.168.8.237:2999 (https, self-signed).

Each route receives the BaseHTTPRequestHandler (`h`) as its sole
argument and uses `h._send(code, body, ctype)` to write the response.
Module-level GET_ROUTES is consumed by `dashboard._dispatch`.

`_VISION_TOKEN` and `_diagnostics_cached` are deferred-imported from
web_dashboard inside each handler to avoid a circular import at module
load time (web_dashboard imports the dashboard package during
start-up).
"""
import json
import logging
from urllib.parse import parse_qs, urlparse

from dashboard._context import read_json
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
    try:
        from core.decision_detector import get_loop
        pending = get_loop().store().list_pending()
        h._send(200, json.dumps({"pending": pending}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/decisions: %s", exc)
        h._send(500, b'{"error":"decisions_read_failed"}', "application/json")


def _serve_diagnostics(h) -> None:
    # AUDIT 2026-04-29: 30 s TTL cache. _build_diagnostics fans out to
    # several heavy probes (DB introspection, log tail, RC + vision
    # health) and sustains ~2 s. Dashboard hits it on diagnostics-view
    # activate; nothing polls it. 30 s feels instant on repeat opens
    # without staling the data.
    try:
        from web_dashboard import _diagnostics_cached
        payload = _diagnostics_cached()
        h._send(200, payload, "application/json")
    except Exception as exc:
        log.warning("api/diagnostics: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_reload_regions(h) -> None:
    try:
        from core.vision_tesseract import reload_regions
        reload_regions()
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_ocr(h) -> None:
    # Pull latest frame from vision server, run Tesseract on configured fields.
    try:
        import time
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        # Check Live Client relay freshness — if fresh (<3s), drop OCR
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


def _close_enough(a, b, pct: float = 0.05, abs_tol: int = 2) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, abs(b) * pct)


def _serve_validate_ocr(h) -> None:
    # Cross-check OCR against Live Client API ground truth where overlap exists.
    # Self-fields (hp, mana, level, gold, kda) have authoritative API values.
    # Use those to score OCR accuracy. Returns per-field {ocr, truth, ok} + summary.
    try:
        import ssl
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        # OCR fields
        req = _ur.Request("http://127.0.0.1:8889/latest-frame",
                          headers={"X-RC-Token": _VISION_TOKEN})
        with _ur.urlopen(req, timeout=4) as r:
            frame = json.loads(r.read())
        from core.vision_tesseract import read_fast_fields
        ocr = read_fast_fields(frame["b64"])
        # Live Client truth
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        truth: dict = {}
        try:
            with _ur.urlopen("https://192.168.8.237:2999/liveclientdata/allgamedata",
                             context=ssl_ctx, timeout=3) as r:
                live = json.loads(r.read())
            me_name = live.get("activePlayer", {}).get("summonerName", "")
            me_stats = live.get("activePlayer", {}).get("championStats", {})
            me_pl = next((p for p in live.get("allPlayers", [])
                          if p.get("summonerName") == me_name), None)
            truth["hp"] = int(me_stats.get("currentHealth", 0))
            truth["mana"] = int(me_stats.get("resourceValue", 0))
            truth["level"] = me_pl.get("level") if me_pl else None
            truth["gold"] = int(live.get("activePlayer", {}).get("currentGold", 0))
            if me_pl:
                s = me_pl.get("scores", {})
                truth["kda"] = f'{s.get("kills",0)}/{s.get("deaths",0)}/{s.get("assists",0)}'
                truth["cs"] = s.get("creepScore")
            truth["timer_sec"] = int(live.get("gameData", {}).get("gameTime", 0))
        except Exception as e:
            truth = {"_error": f"live_client_unreachable: {e}"}
        checks: dict = {}
        for k in ("hp", "mana", "level", "gold", "cs", "kda"):
            o, t = ocr.get(k), truth.get(k)
            if t is None or "_error" in truth:
                checks[k] = {"ocr": o, "truth": t, "ok": None}
            elif k == "kda":
                checks[k] = {"ocr": o, "truth": t, "ok": (o == t)}
            elif k == "level":
                checks[k] = {"ocr": o, "truth": t, "ok": (o == t)}
            else:
                checks[k] = {"ocr": o, "truth": t, "ok": _close_enough(o, t)}
        ok_count = sum(1 for v in checks.values() if v["ok"] is True)
        total = sum(1 for v in checks.values() if v["ok"] is not None)
        payload = {"checks": checks, "score": f"{ok_count}/{total}",
                   "ocr_extras": {k: v for k, v in ocr.items() if k not in checks}}
        h._send(200, json.dumps(payload, indent=2).encode(), "application/json")
    except Exception as exc:
        log.warning("api/validate-ocr: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_ocr_crop(h) -> None:
    # /api/ocr-crop?field=NAME — returns the cropped PNG for visual verification.
    try:
        import base64
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        qs = parse_qs(urlparse(h.path).query)
        field = (qs.get("field") or ["timer"])[0]
        req = _ur.Request("http://127.0.0.1:8889/latest-frame",
                          headers={"X-RC-Token": _VISION_TOKEN})
        with _ur.urlopen(req, timeout=4) as r:
            frame = json.loads(r.read())
        from core.vision_tesseract import crop_png_b64
        b64png = crop_png_b64(frame["b64"], field)
        if not b64png:
            h._send(404, b"unknown field", "text/plain"); return
        h._send(200, base64.b64decode(b64png), "image/png")
    except Exception as exc:
        log.warning("api/ocr-crop: %s", exc)
        h._send(500, str(exc).encode(), "text/plain")


# ── route table ──────────────────────────────────────────────────────

# /api/ocr-crop uses prefix() because the legacy do_GET used
# `startswith` (the field is in the query string). All others are
# exact matches.
# ── POST handlers (slice 2C-7b) ──────────────────────────────────────


def _serve_decision_choice_post(h, payload) -> None:
    # POST /api/decisions/<id>  body: {choice: "contest"|"give"|"skip", note?}
    # Records the player's choice and removes the decision from pending.
    try:
        decision_id = h.path[len("/api/decisions/"):].split("?", 1)[0]
        if not decision_id:
            h._send(400, b'{"error":"id required"}', "application/json"); return
        choice = (payload.get("choice") or "").strip()
        if choice not in ("contest", "give", "skip"):
            h._send(400, b'{"error":"choice must be contest|give|skip"}',
                    "application/json"); return
        from core.decision_detector import get_loop
        extra = {}
        if "note" in payload:
            extra["note"] = str(payload.get("note") or "")[:500]
        entry = get_loop().store().record_choice(decision_id, choice, extra=extra)
        if entry is None:
            h._send(404, b'{"error":"id not pending"}', "application/json"); return
        h._send(200, json.dumps({"ok": True, "id": entry["id"],
                                  "choice": entry["choice"]}).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/decisions POST: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/vision-state"),    _serve_vision_state),
    (equals("/api/decisions"),       _serve_decisions),
    (equals("/api/diagnostics"),     _serve_diagnostics),
    (equals("/api/reload-regions"),  _serve_reload_regions),
    (equals("/api/ocr"),             _serve_ocr),
    (equals("/api/validate-ocr"),    _serve_validate_ocr),
    (prefix("/api/ocr-crop"),        _serve_ocr_crop),
]

# /api/decisions/<id> uses prefix() — the legacy elif used
# `startswith("/api/decisions/")`. The trailing slash is required so
# this doesn't shadow the GET on `/api/decisions` (no id).
POST_ROUTES = [
    (prefix("/api/decisions/"),      _serve_decision_choice_post),
]
