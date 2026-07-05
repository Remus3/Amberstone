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
  GET  /api/vision-regions?source=profile  (source=reference is an alias)
                             -> the ACTIVE per-HUD-config profile's regions + base
                             {"ok": true, "regions", "base": [w,h], "source",
                              "seeded"}. A legacy_seed profile (base 1920x1080)
                             has its boxes SCALED to the reference base and
                             "seeded": true.
  POST /api/vision-regions   body {"regions": {...}} -> validate + atomic-write
                             -> {"ok": true, "saved": <n>} ; 400 on a bad shape
                             (an invalid payload never touches the file).
  POST /api/vision-regions   body {"regions": {...}, "base": [w,h],
                             "source": "profile"} -> validate + save_profile
                             -> {"ok": true, "saved": <n>, "config_key",
                              "target": "profile"} ; 400 on a bad shape
                             (save_profile is NOT called on an invalid payload).
  GET  /api/vision-frame    -> {"ok": true, "b64", "width", "height", "age_s"}
                             ; {"ok": false, ...} when the :8889 relay is down.
  GET  /api/vision-frame?source=reference  -> the saved NATIVE reference still
                             for the active profile {"ok": true, "b64", "width",
                              "height", "format": "jpeg", "age_s", "base":[w,h]}
                             ; {"ok": false, "error"} when none captured yet.
  GET  /api/vision-frame?source=reference&state=<state>  -> the named reference
                             state still (multi-state frames); state omitted /
                             "base" is the legacy base still.
  GET  /api/vision-reference-states  -> {"ok": true, "states": [{"state",
                             "exists", "width", "height"}, ...]} for the active
                             config (base + any ingested states).
  POST /api/vision-reference  body {"state", "path"} -> ingest an operator-
                             provided full-screen native screenshot as a named
                             reference state -> {"ok": true, ...} ; 400 on a
                             missing field, a dims mismatch, or a base/empty
                             label (nothing is written on a rejected ingest).
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
from urllib.parse import parse_qs, urlparse

from core import vision_profiles as vp

log = logging.getLogger("rc.web_dashboard")

_REFERENCE_FALLBACK_BASE = [2560, 1440]  # native-res default when no reference yet


def _query_param(path: str, key: str):
    """Return a single ?<key>= value from a request path (or None). Tolerant of a
    missing / malformed querystring - never raises."""
    try:
        return parse_qs(urlparse(path).query).get(key, [None])[0]
    except Exception:  # noqa: BLE001
        return None


def _query_source(path: str):
    """Return the single ?source= value from a request path (or None)."""
    return _query_param(path, "source")

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


def _scale_regions(regions: dict, sx: float, sy: float) -> dict:
    out = {}
    for name, box in (regions or {}).items():
        try:
            x1, y1, x2, y2 = box
            out[name] = [round(x1 * sx), round(y1 * sy),
                         round(x2 * sx), round(y2 * sy)]
        except Exception:  # noqa: BLE001
            out[name] = box
    return out


def _profile_regions_payload() -> dict:
    """Return the active profile's regions + base. A legacy_seed profile
    (base 1920x1080) is scaled up to the reference base so seeded boxes land on
    the native-res reference still. ``seeded`` flags a scaled fallback set."""
    prof = vp.load_profile()
    regions = prof.get("regions", {})
    base = prof.get("base", list(_REFERENCE_FALLBACK_BASE))
    if prof.get("source") == "legacy_seed":
        ref = vp.load_reference()
        if ref.get("ok") and ref.get("width") and ref.get("height"):
            ref_w, ref_h = int(ref["width"]), int(ref["height"])
        else:
            ref_w, ref_h = _REFERENCE_FALLBACK_BASE
        seed_w = base[0] if base and base[0] else 1920
        seed_h = base[1] if base and len(base) > 1 and base[1] else 1080
        regions = _scale_regions(regions, ref_w / seed_w, ref_h / seed_h)
        return {"ok": True, "regions": regions, "base": [ref_w, ref_h],
                "source": "legacy_seed", "seeded": True}
    return {"ok": True, "regions": regions, "base": base,
            "source": prof.get("source", "profile"), "seeded": False}


def _serve_regions_get(h) -> None:
    try:
        if _query_source(h.path) in ("profile", "reference"):
            _send_json(h, 200, _profile_regions_payload())
            return
        _send_json(h, 200, {"ok": True, "regions": load_regions()})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _save_profile_from_body(h, body) -> None:
    """Validate then save a per-profile region set. An invalid payload returns
    400 and never calls save_profile (mirrors the legacy save_regions guard)."""
    ok, err, clean = validate_regions(body.get("regions"))
    if not ok:
        _send_json(h, 400, {"ok": False, "error": err})
        return
    base = body.get("base")
    res = vp.save_profile(vp.active_config_key(), clean, base)
    if res.get("ok"):
        _send_json(h, 200, {"ok": True, "saved": res.get("count", len(clean)),
                            "config_key": res.get("config_key"), "target": "profile"})
    else:
        _send_json(h, 500, {"ok": False, "error": "could not write profile - see logs"})


def _serve_regions_post(h, body) -> None:
    try:
        if not isinstance(body, dict) or "regions" not in body:
            _send_json(h, 400, {"ok": False, "error": "body must be {\"regions\": {...}}"})
            return
        if body.get("source") == "profile" or "base" in body:
            _save_profile_from_body(h, body)
            return
        ok, err, count = save_regions(body.get("regions"))
        if ok:
            _send_json(h, 200, {"ok": True, "saved": count})
        else:
            _send_json(h, 400, {"ok": False, "error": err})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions POST: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _reference_frame_payload(state=None) -> dict:
    """Remap vp.load_reference(state) to the frame-endpoint shape (adds base).
    Passes a {"ok": False, "error"} through unchanged. No state -> the legacy
    base call (keeps the old 1-arg signature working, byte-for-byte)."""
    ref = vp.load_reference(state=state) if state else vp.load_reference()
    if not ref.get("ok"):
        return {"ok": False, "error": ref.get("error", "no reference captured yet")}
    w, hgt = ref.get("width"), ref.get("height")
    return {
        "ok": True,
        "b64": ref.get("b64"),
        "width": w,
        "height": hgt,
        "format": "jpeg",
        "age_s": ref.get("age_s"),
        "base": [w, hgt],
    }


def _serve_frame_get(h) -> None:
    try:
        if _query_source(h.path) == "reference":
            _send_json(h, 200, _reference_frame_payload(state=_query_param(h.path, "state")))
            return
        out = fetch_frame()
        if out.get("ok") and out.get("width") is not None and out.get("height") is not None:
            out.setdefault("base", [out["width"], out["height"]])
        _send_json(h, 200, out)
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-frame GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_reference_states_get(h) -> None:
    """List the reference states present for the active config as
    ``{ok, states:[{state, exists, width, height}]}``. A per-state dims read is
    best-effort (omitted / null when unavailable)."""
    try:
        out = []
        for st in vp.list_reference_states():
            entry = {"state": st, "exists": True}
            try:
                ref = vp.load_reference() if st == "base" else vp.load_reference(state=st)
                if ref.get("ok"):
                    entry["width"] = ref.get("width")
                    entry["height"] = ref.get("height")
            except Exception:  # noqa: BLE001
                pass
            out.append(entry)
        _send_json(h, 200, {"ok": True, "states": out})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-reference-states GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_reference_post(h, body) -> None:
    """Ingest an operator-provided screenshot as a named reference state.
    body ``{state, path}`` -> vp.ingest_reference_from_path -> 200 ok / 400 error.
    Never leaks a raw exception (CLAUDE.md error rule)."""
    try:
        state = body.get("state") if isinstance(body, dict) else None
        path = body.get("path") if isinstance(body, dict) else None
        if not isinstance(state, str) or not state.strip() \
                or not isinstance(path, str) or not path.strip():
            _send_json(h, 400, {"ok": False,
                                "error": "body must be {\"state\": str, \"path\": str}"})
            return
        res = vp.ingest_reference_from_path(path, state)
        _send_json(h, 200 if res.get("ok") else 400, res)
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-reference POST: %s", exc)
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
    (_equals("/api/vision-reference-states"), _serve_reference_states_get),
    (_equals("/vision-calibrator"), _serve_page_get),
]
POST_ROUTES = [
    (_equals("/api/vision-regions"), _serve_regions_post),
    (_equals("/api/vision-reference"), _serve_reference_post),
]
