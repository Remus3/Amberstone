# arch: GET/POST vision-region calibrator (frame proxy + regions read/write + page) | section=dashboard | frozen=no
"""Vision-region calibrator - an adjustable companion tool to debug + recalibrate
the OCR crop regions in ``data/vision_regions.json``.

Each region is a named ``[x1, y1, x2, y2]`` pixel box on the :8889 vision frame.
``tools/calibrate_vision.py`` only draws the current boxes onto a static JPG; this
adds a draggable/resizable web surface (``web/vision_calibrator.html``) backed by
these routes so a box can be dragged over the live frame and saved back. It doubles
as the OBS/CV-plan OCR-reliability harness (which fields deterministic OCR reads
cleanly - the go/no-go evidence before dropping a field's Sonnet escalation).

Routes (all local / tailnet-only, single-operator - same trust model as every
other :8888 POST):
  GET  /api/vision-regions  -> {"ok": true, "regions": {name: [x1,y1,x2,y2], ...}}
  POST /api/vision-regions   body {"regions": {...}} -> validate + atomic-write
                             -> {"ok": true, "saved": <n>} ; 400 on a bad shape
                             (an invalid payload never touches the file).
  GET  /api/vision-frame    -> {"ok": true, "b64", "width", "height", "age_s"}
                             ; {"ok": false, ...} when the :8889 relay is down.
  GET  /vision-calibrator   -> the calibrator HTML page.

Never crashes the server; raw exception text stays in the log only (CLAUDE.md
error rule).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("rc.web_dashboard")

_ROOT = Path(__file__).resolve().parent.parent
REGIONS_PATH = _ROOT / "data" / "vision_regions.json"
PAGE_PATH = _ROOT / "web" / "vision_calibrator.html"
_FRAME_URL = "http://127.0.0.1:8889/latest-frame"
_COORD_MAX = 10000  # sanity ceiling - reject garbage coordinates


def _vision_token() -> str:
    try:
        return (_ROOT / "config" / "vision_token.txt").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


def validate_regions(obj):
    """Validate a regions payload. Returns ``(ok, err, clean)`` where ``clean``
    is a dict of name -> [x1,y1,x2,y2] ints. Rejects any malformed shape so a
    fat-fingered drag can never persist a zero-area or off-canvas crop."""
    if not isinstance(obj, dict) or not obj:
        return (False, "regions must be a non-empty object", {})
    clean = {}
    for name, box in obj.items():
        if not isinstance(name, str) or not name.strip():
            return (False, "region name must be a non-empty string", {})
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return (False, f"{name}: expected [x1,y1,x2,y2]", {})
        coords = []
        for c in box:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                return (False, f"{name}: coordinates must be numbers", {})
            coords.append(int(c))
        x1, y1, x2, y2 = coords
        if min(coords) < 0 or max(coords) > _COORD_MAX:
            return (False, f"{name}: coordinates out of range", {})
        if x2 <= x1 or y2 <= y1:
            return (False, f"{name}: x2>x1 and y2>y1 required (non-empty box)", {})
        clean[name] = [x1, y1, x2, y2]
    return (True, None, clean)


def load_regions(path=None) -> dict:
    """Read the regions file. Returns {} on a missing / malformed file."""
    p = Path(path) if path is not None else REGIONS_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_regions(obj, path=None):
    """Validate then atomic-write the regions payload. Returns
    ``(ok, err, count)``. An invalid payload is rejected without touching disk."""
    ok, err, clean = validate_regions(obj)
    if not ok:
        return (False, err, 0)
    p = Path(path) if path is not None else REGIONS_PATH
    try:
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
        for attempt in range(3):  # os.replace can flake WinError 5 under concurrent read
            try:
                tmp.replace(p)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        return (True, None, len(clean))
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions save failed: %s", exc)
        return (False, "could not write regions file - see logs", 0)


def fetch_frame(_fetch=None, _now=None) -> dict:
    """Proxy the latest :8889 vision frame. Returns a friendly ``{"ok": false}``
    when the relay is down (never raises, never leaks the raw error)."""
    now = _now or time.time
    if _fetch is None:
        def _fetch():
            req = urllib.request.Request(_FRAME_URL, headers={"X-RC-Token": _vision_token()})
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.read()
    try:
        d = json.loads(_fetch())
        if not d.get("b64"):
            return {"ok": False, "error": "no frame available yet"}
        return {
            "ok": True,
            "b64": d.get("b64"),
            "width": d.get("width"),
            "height": d.get("height"),
            "format": d.get("format", "jpeg"),
            "age_s": round(now() - float(d.get("ts", 0) or 0), 1),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-frame proxy failed: %s", exc)
        return {"ok": False, "error": "frame relay unavailable"}


# -- handlers ---------------------------------------------------------

def _send_json(h, code: int, payload: dict) -> None:
    h._send(code, json.dumps(payload).encode("utf-8"), "application/json")


def _serve_regions_get(h) -> None:
    try:
        _send_json(h, 200, {"ok": True, "regions": load_regions()})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_regions_post(h, body) -> None:
    try:
        if not isinstance(body, dict) or "regions" not in body:
            _send_json(h, 400, {"ok": False, "error": "body must be {\"regions\": {...}}"})
            return
        ok, err, count = save_regions(body.get("regions"))
        if ok:
            _send_json(h, 200, {"ok": True, "saved": count})
        else:
            _send_json(h, 400, {"ok": False, "error": err})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions POST: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_frame_get(h) -> None:
    try:
        _send_json(h, 200, fetch_frame())
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-frame GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_page_get(h) -> None:
    try:
        html = PAGE_PATH.read_text(encoding="utf-8")
        h._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-calibrator page: %s", exc)
        h._send(404, b"vision calibrator page not found", "text/plain; charset=utf-8")


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/vision-regions"), _serve_regions_get),
    (_equals("/api/vision-frame"), _serve_frame_get),
    (_equals("/vision-calibrator"), _serve_page_get),
]
POST_ROUTES = [
    (_equals("/api/vision-regions"), _serve_regions_post),
]
