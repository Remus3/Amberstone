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
                             On both frame routes a junk width / height is
                             null and then no "base" is sent; a missing,
                             junk or non-finite timestamp gives "age_s" null.
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
import math
import os
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import vision_profiles as vp
from core.polled_json import atomic_write_text

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
# s144 true-audit: bounds on what a POST may persist into the TRACKED regions
# file / a profile. Measured at the audit: the live profiles hold at most 33
# regions, names at most 28 printable ASCII characters.
_NAME_MAX = 64
_REGIONS_MAX = 256
# A 2560x1440 JPEG relay frame is ~1-2 MB of base64; the cap only stops an
# unbounded read, it never trims a real frame.
_FRAME_MAX_BYTES = 32 * 1024 * 1024
_FRAME_FORMATS = ("jpeg", "png", "webp")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: urllib copies X-RC-Token onto the redirected
    request, and the :8889 relay never redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# s144 true-audit F4: the process-default opener honours HTTP_PROXY / the
# registry proxy for 127.0.0.1 (measured: proxy_bypass("127.0.0.1:8889") is
# False with HTTP_PROXY set), which would hand the vision token to the proxy,
# and it freezes whatever proxy it saw on the first urlopen() in the process.
# The relay is loopback: no proxy, no redirect.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      _NoRedirect)


def _vision_token() -> str:
    """The :8889 token via the shared resolver, "" when none is configured.

    RM-487 (2026-10-03): this used to read config/vision_token.txt and
    NOTHING else (and the whole file, not its first line), so a token
    supplied only through RC_VISION_TOKEN produced an empty X-RC-Token and
    a 401 the calibrator rendered as "relay down". core.vision_token is
    what every other :8889 client uses. It raises RuntimeError when no
    token exists - including at IMPORT time - so both the import and the
    call stay inside the fail-soft guard.
    """
    try:
        from core.vision_token import get_vision_token
        return get_vision_token()
    except Exception:  # noqa: BLE001
        return ""


def validate_regions(obj):
    """Validate a regions payload. Returns ``(ok, err, clean)`` where ``clean``
    is a dict of name -> [x1,y1,x2,y2] ints. Rejects any malformed shape so a
    fat-fingered drag can never persist a zero-area or off-canvas crop.
    Never raises: the dashboard parses bodies with ``json.loads``, which
    accepts NaN, Infinity and 1e400 (= inf), and each is a refusal here, not
    a ValueError / OverflowError out of ``int()``. The range is checked on the
    RAW value, before ``int()`` truncates -0.5 to 0 or 10000.5 to 10000. A
    name is at most ``_NAME_MAX`` printable characters. No message quotes a
    name (RM-1376): a box refusal names the region by its 1-based position
    in the submitted object ("region 2: ..."), so an error never echoes the
    caller's text."""
    if not isinstance(obj, dict) or not obj:
        return (False, "regions must be a non-empty object", {})
    if len(obj) > _REGIONS_MAX:
        return (False, f"at most {_REGIONS_MAX} regions", {})
    clean = {}
    # RM-1376: a box refusal names the region by its 1-based position in
    # the submitted object, never by the caller's name string.
    for pos, (name, box) in enumerate(obj.items(), start=1):
        if not isinstance(name, str) or not name.strip():
            return (False, "region name must be a non-empty string", {})
        if len(name) > _NAME_MAX or not name.isprintable():
            return (False, f"region names must be at most {_NAME_MAX} "
                           "printable characters", {})
        where = f"region {pos}"
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return (False, f"{where}: expected [x1,y1,x2,y2]", {})
        coords = []
        for c in box:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                return (False, f"{where}: coordinates must be numbers", {})
            if isinstance(c, float) and not math.isfinite(c):
                return (False, f"{where}: coordinates must be finite", {})
            if c < 0 or c > _COORD_MAX:
                return (False, f"{where}: coordinates out of range", {})
            coords.append(int(c))
        x1, y1, x2, y2 = coords
        if x2 <= x1 or y2 <= y1:
            return (False, f"{where}: x2>x1 and y2>y1 required (non-empty box)", {})
        clean[name] = [x1, y1, x2, y2]
    return (True, None, clean)


def load_regions(path=None) -> dict:
    """Read the regions file. Returns {} on a missing / malformed file,
    including one whose top level is not an object. Only read and parse
    failures are swallowed; anything else is a bug and raises."""
    p = Path(path) if path is not None else REGIONS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def save_regions(obj, path=None):
    """Validate then atomic-write the regions payload. Returns
    ``(ok, err, count)``. An invalid payload is rejected without touching disk."""
    ok, err, clean = validate_regions(obj)
    if not ok:
        return (False, err, 0)
    p = Path(path) if path is not None else REGIONS_PATH
    try:
        atomic_write_text(p, json.dumps(clean, indent=2) + "\n")
        return (True, None, len(clean))
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-regions save failed: %s", exc)
        return (False, "could not write regions file - see logs", 0)


def _dim(v):
    """A frame dimension as a positive int up to ``_COORD_MAX``, else None.
    An integral float (2560.0) counts; a fraction, a bool or a string never
    does."""
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if 0 < v <= _COORD_MAX else None


def _finite(v):
    """``v`` rounded to 0.1 when it is a finite real number, else None. A
    NaN or an infinity must never reach a response: ``json.dumps`` writes
    them as bare tokens that no browser JSON parser accepts."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return round(f, 1) if math.isfinite(f) else None


def _age_s(now_s, ts):
    """Seconds since ``ts``, or None when ``ts`` is missing, zero,
    non-numeric or non-finite (the frame itself is still served). Zero is
    "no stamp", as in ``vision_profiles._age_since``, never the epoch."""
    if not ts or _finite(ts) is None:
        return None
    try:
        return _finite(float(now_s) - float(ts))
    except (OverflowError, TypeError, ValueError):
        return None


def _read_frame() -> bytes:
    """Read the relay body through the no-proxy, no-redirect opener, at most
    ``_FRAME_MAX_BYTES``; a larger body raises ValueError."""
    req = urllib.request.Request(_FRAME_URL,
                                 headers={"X-RC-Token": _vision_token()})
    with _OPENER.open(req, timeout=3) as r:
        raw = r.read(_FRAME_MAX_BYTES + 1)
    if len(raw) > _FRAME_MAX_BYTES:
        raise ValueError(f"relay frame over {_FRAME_MAX_BYTES} bytes")
    return raw


def fetch_frame(_fetch=None, _now=None) -> dict:
    """Proxy the latest :8889 vision frame. Returns a friendly ``{"ok": false}``
    when the relay is down (never raises, never leaks the raw error). A frame
    with a junk ``ts`` is still served, with ``age_s`` None; a junk width or
    height is None (and the frame GET then derives no ``base``)."""
    now = _now or time.time
    fetch = _fetch or _read_frame
    try:
        d = json.loads(fetch())
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-frame proxy failed: %s", exc)
        return {"ok": False, "error": "frame relay unavailable"}
    if not isinstance(d, dict):
        log.warning("vision-frame proxy: relay body is a %s, not an object",
                    type(d).__name__)
        return {"ok": False, "error": "frame relay unavailable"}
    b64 = d.get("b64")
    if not isinstance(b64, str) or not b64:
        return {"ok": False, "error": "no frame available yet"}
    fmt = d.get("format")
    return {
        "ok": True,
        "b64": b64,
        "width": _dim(d.get("width")),
        "height": _dim(d.get("height")),
        # The page splices this into a data:image/<format> URL; the relay
        # only ever sends jpeg (vision_server/_frame.py).
        "format": fmt if fmt in _FRAME_FORMATS else "jpeg",
        "age_s": _age_s(now(), d.get("ts")),
    }


# -- handlers ---------------------------------------------------------

def _send_json(h, code: int, payload: dict) -> None:
    # allow_nan=False: a non-finite number raises here (each handler's except
    # turns it into the generic 500) instead of going out as invalid JSON.
    h._send(code, json.dumps(payload, allow_nan=False).encode("utf-8"),
            "application/json")


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
        ref_w, ref_h = _dim(ref.get("width")), _dim(ref.get("height"))
        if not (ref.get("ok") and ref_w and ref_h):
            ref_w, ref_h = _REFERENCE_FALLBACK_BASE
        seed_w = base[0] if base and base[0] else 1920
        seed_h = base[1] if base and len(base) > 1 and base[1] else 1080
        regions = _scale_regions(regions, ref_w / seed_w, ref_h / seed_h)
        return {"ok": True, "regions": regions, "base": [ref_w, ref_h],
                "source": "legacy_seed", "seeded": True}
    # RM-26: a tier-2 "resolution_seed" is already at its native base, so it is
    # NOT rescaled like a legacy seed. It must still carry seeded=True: this is
    # a REGRESSION GUARD, not a UX fix. Before tier 2b an unseeded ultrawide
    # answered legacy_seed and so already got seeded=True; without this line the
    # same machine would now answer resolution_seed and silently flip to
    # seeded=False, i.e. an untuned proportional derivation would start
    # presenting as a finished calibration. The operator-visible warning is
    # unchanged in both states.
    src = prof.get("source", "profile")
    return {"ok": True, "regions": regions, "base": base,
            "source": src, "seeded": src == "resolution_seed"}


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
    """Validate regions + base then save a per-profile set. An invalid
    payload returns 400 and never calls save_profile."""
    ok, err, clean = validate_regions(body.get("regions"))
    if not ok:
        _send_json(h, 400, {"ok": False, "error": err})
        return
    ok_b, err_b, base = vp.validate_base(body.get("base"))
    if not ok_b:
        _send_json(h, 400, {"ok": False, "error": err_b})
        return
    res = vp.save_profile(vp.active_config_key(), clean, base)
    if res.get("ok"):
        _send_json(h, 200, {"ok": True, "saved": res.get("count", len(clean)),
                            "config_key": res.get("config_key"), "target": "profile"})
    else:
        _send_json(h, 500, {"ok": False, "error": "could not write profile - see logs"})


def _serve_regions_post(h, body) -> None:
    try:
        if not isinstance(body, dict) or "regions" not in body:
            _send_json(h, 400, {"ok": False, "error": 'body must be {"regions": {...}}'})
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
    w, hgt = _dim(ref.get("width")), _dim(ref.get("height"))
    out = {
        "ok": True,
        "b64": ref.get("b64"),
        "width": w,
        "height": hgt,
        "format": "jpeg",
        "age_s": _finite(ref.get("age_s")),
    }
    # The sidecar meta is a separate file: a missing or junk width / height
    # (or a NaN ts, hence a NaN age) must not become a [null, null] base or a
    # bare NaN token in the response.
    if w is not None and hgt is not None:
        out["base"] = [w, hgt]
    return out


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
                    entry["width"] = _dim(ref.get("width"))
                    entry["height"] = _dim(ref.get("height"))
            except Exception:  # noqa: BLE001
                pass
            out.append(entry)
        _send_json(h, 200, {"ok": True, "states": out})
    except Exception as exc:  # noqa: BLE001
        log.warning("vision-reference-states GET: %s", exc)
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


# PKG-5 fix round (2026-10-26): what the ingest path may name. The path came
# straight from the request body into PIL Image.open, so a UNC path
# (\\host\share\x.png, //host/share/x.png) made this machine open an
# outbound SMB connection (NTLM credentials included) and any readable file
# on the box could be probed. Now: a local file inside the reference folder,
# nothing else. A relative path is taken relative to that folder.
_INGEST_DIR_LABEL = "data/vision_calib_reference"
_INGEST_REFUSED = ("path must name a local image file inside "
                   f"{_INGEST_DIR_LABEL} (no network, device or "
                   "out-of-folder path)")


def _ingest_source(raw: str):
    """The screenshot path an ingest may open, as a resolved str, or None.

    Lexical checks run first and touch no file system, so a network or
    mapped-drive name is refused before anything tries to open it: no NUL,
    no scheme (``file://``), no UNC / device prefix (``\\\\``, ``//``,
    ``\\\\?\\``, ``\\\\.\\`` in either slash), and the joined, normalised
    path must sit strictly inside ``vp.REFERENCE_DIR``. Only then is it
    resolved (links followed) and re-checked, so a link inside the folder
    that points out of it (or at a share) is refused too. Backslashes are
    read as separators on every OS, so the answer does not depend on where
    the test runs.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip().replace("\\", "/")
    if not text or "\x00" in text or "://" in text \
            or text.lower().startswith("file:") or text.startswith("//"):
        return None
    base_raw = os.path.abspath(str(vp.REFERENCE_DIR))
    joined_raw = os.path.abspath(os.path.join(base_raw, text))
    base = os.path.normcase(base_raw)
    joined = os.path.normcase(joined_raw)
    if joined.startswith(("\\\\", "//")) or not _strictly_inside(joined, base):
        return None
    try:
        real_base = os.path.normcase(os.path.realpath(base_raw))
        real_raw = os.path.realpath(joined_raw)
    except (OSError, ValueError):
        return None
    real = os.path.normcase(real_raw)
    if real.startswith(("\\\\", "//")) or not _strictly_inside(real, real_base):
        return None
    return real_raw


def _strictly_inside(path: str, base: str) -> bool:
    """True when ``path`` is below ``base`` (both normalised, same case
    folding), never ``base`` itself or a sibling sharing its prefix."""
    try:
        return path != base and os.path.commonpath([path, base]) == base
    except ValueError:  # different drives
        return False


def _serve_reference_post(h, body) -> None:
    """Ingest an operator-provided screenshot as a named reference state.
    body ``{state, path}`` -> vp.ingest_reference_from_path -> 200 ok / 400 error.
    ``path`` must resolve inside data/vision_calib_reference (``_ingest_source``).
    Never leaks a raw exception (CLAUDE.md error rule)."""
    try:
        state = body.get("state") if isinstance(body, dict) else None
        path = body.get("path") if isinstance(body, dict) else None
        if not isinstance(state, str) or not state.strip() \
                or not isinstance(path, str) or not path.strip():
            _send_json(h, 400, {"ok": False,
                                "error": 'body must be {"state": str, "path": str}'})
            return
        source = _ingest_source(path)
        if source is None:
            log.warning("vision-reference POST: refused a path outside %s",
                        _INGEST_DIR_LABEL)
            _send_json(h, 400, {"ok": False, "error": _INGEST_REFUSED})
            return
        res = vp.ingest_reference_from_path(source, state)
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
