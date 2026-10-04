# arch: RM-641 recording sidecar summary + allow-listed video stream with HTTP Range | section=dashboard | frozen=no
"""RM-641 (directive X-41, ADR-016 "Serving") - local match recordings on :8888.

GET /api/recordings/<id>
    Summary of the RM-637 sidecar ``data/recordings/<gameId>.json`` for the
    S5 Replay video lane: game_time_offset_s, bookmarks, death_count, status,
    owner, has_video, video_url. NEVER the file path.

GET /api/recordings/<id>/video
    The recording itself, with HTTP Range (200 full, 206 partial, 416
    unsatisfiable).

<id> is either the recorder's own sidecar name (the Live Client gameId,
core/obs_recorder.py _safe_match_id) or a Match-V5 id as the Replay view
uses it ("NA1_<gameId>"); the platform prefix is dropped to find the sidecar.

Binding rules (ADR-016 "Serving"; the dashboard is reachable over the tailnet
and recordings carry other players' voices):
  * A file is served ONLY when a sidecar names it (``obs_output_path``, which
    the recorder writes for RC-owned recordings only). The client never sends
    a path, so a path that no sidecar names is unreachable by construction.
    No folder glob, no "recordings folder" is assumed.
  * The named path must be absolute, a regular file with a video extension,
    contain NO symlink or junction anywhere in its chain, and resolve by
    os.path.realpath to itself (which also catches mount points and any other
    reparse point). The sidecar file itself must not be a link.
  * Behind the existing auth: the RC_DASH_TOKEN / X-RC-Token gate of
    dashboard/_handler.py (inert while the env var is unset, exactly as for
    the control endpoints).

Behaviour observed in external reference E; re-implemented clean-room.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import stat
import sys
from pathlib import Path

from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import prefix

log = logging.getLogger("rc.web_dashboard")

RECORDINGS_DIR = _APP_DIR / "data" / "recordings"

_PREFIX = "/api/recordings/"
# Same character class as core/obs_recorder.py _SAFE_ID, bounded like it.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PLATFORM_RE = re.compile(r"^[A-Za-z]{2,5}[0-9]?_([0-9]+)$")

_VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4",
                ".webm": "video/webm", ".mkv": "video/x-matroska",
                ".mov": "video/quicktime"}

# Our own: 256 KiB per write keeps a 6 GB file streaming without holding more
# than one buffer per request in memory.
_CHUNK = 256 * 1024

UNSATISFIABLE = "unsatisfiable"

_BYTES_RE = re.compile(r"^\s*bytes\s*=\s*(.*)$", re.I)
_SPEC_RE = re.compile(r"^\s*(\d*)\s*-\s*(\d*)\s*$")


def parse_range(header, size: int):
    """Parse a Range header against a file of ``size`` bytes.

    Returns None (serve the full body: no header, a unit we do not support, a
    syntactically invalid spec, or a multi-range we choose not to serve - RFC
    9110 lets a server ignore Range), UNSATISFIABLE (answer 416), or an
    inclusive (start, end) pair clamped to the file.
    """
    if not header or not isinstance(header, str):
        return None
    m = _BYTES_RE.match(header)
    if not m:
        return None
    spec = m.group(1)
    if "," in spec:
        return None
    s = _SPEC_RE.match(spec)
    if not s:
        return None
    a, b = s.group(1), s.group(2)
    if a == "" and b == "":
        return None
    if a == "":
        n = int(b)
        if n == 0 or size <= 0:
            return UNSATISFIABLE
        return (max(0, size - n), size - 1)
    start = int(a)
    end = int(b) if b != "" else None
    if end is not None and end < start:
        return None
    if start >= size:
        return UNSATISFIABLE
    if end is None or end >= size:
        end = size - 1
    return (start, end)


def _sidecar_name(raw_id: str):
    if not _ID_RE.match(raw_id or ""):
        return None
    m = _PLATFORM_RE.match(raw_id)
    return m.group(1) if m else raw_id


def _is_link(p: str) -> bool:
    if os.path.islink(p):
        return True
    isj = getattr(os.path, "isjunction", None)
    return bool(isj and isj(p))


def _long_path(p: str) -> str:
    """Expand 8.3 short names on Windows (GetLongPathNameW does not follow
    reparse points), so a short-name spelling is not mistaken for a link."""
    if sys.platform != "win32":
        return p
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(p, buf, len(buf))
        return buf.value if 0 < n < len(buf) else p
    except Exception:  # noqa: BLE001 - fall back to the strict comparison
        return p


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def resolve_recording_path(raw) -> str | None:
    """The servable real path for a sidecar's ``obs_output_path``, or None."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        return None
    if not os.path.isabs(raw):
        return None
    ext = os.path.splitext(raw)[1].lower()
    if ext not in _VIDEO_TYPES:
        return None
    absp = os.path.abspath(raw)
    cur = absp
    while True:
        if _is_link(cur):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    real = os.path.realpath(absp)
    if not _same(real, absp) and not _same(real, _long_path(absp)):
        return None
    try:
        st = os.stat(real, follow_symlinks=False)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return real


def load_sidecar(raw_id: str):
    """(status, sidecar-dict-or-None, sidecar_name) for a request id."""
    name = _sidecar_name(raw_id)
    if name is None:
        return 400, None, None
    p = RECORDINGS_DIR / f"{name}.json"
    sp = str(p)
    if not os.path.isfile(sp) or _is_link(sp):
        return 404, None, name
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 404, None, name
    if not isinstance(data, dict):
        return 404, None, name
    return 200, data, name


def _auth_ok(h) -> bool:
    token = os.environ.get("RC_DASH_TOKEN", "").strip()
    if not token:
        return True
    got = ""
    try:
        got = (h.headers.get("X-RC-Token") or "").strip()
    except Exception:  # noqa: BLE001
        got = ""
    return hmac.compare_digest(got.encode("utf-8", "surrogatepass"),
                               token.encode("utf-8", "surrogatepass"))


def _json(h, code: int, body: dict) -> None:
    h._send(code, json.dumps(body).encode("utf-8"), "application/json")


def _summary(data: dict, name: str) -> dict:
    servable = resolve_recording_path(data.get("obs_output_path")) is not None
    bms = data.get("bookmarks") if isinstance(data.get("bookmarks"), list) else []
    keep = ("event_id", "name", "game_time", "video_time", "provisional", "own_death")
    return {
        "ok": True,
        "match_id": name,
        "status": data.get("status"),
        "owner": data.get("owner"),
        "game_time_offset_s": data.get("game_time_offset_s"),
        "start_game_time_s": data.get("start_game_time_s"),
        "death_count": data.get("death_count"),
        "bookmarks": [{k: b.get(k) for k in keep if k in b}
                      for b in bms if isinstance(b, dict)],
        "has_video": servable,
        "video_url": f"{_PREFIX}{name}/video" if servable else None,
    }


def _stream(h, real: str) -> None:
    ctype = _VIDEO_TYPES[os.path.splitext(real)[1].lower()]
    with open(real, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        rng = parse_range(h.headers.get("Range"), size)
        if rng == UNSATISFIABLE:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{size}")
            h.send_header("Content-Length", "0")
            h.send_header("Accept-Ranges", "bytes")
            h.send_header("Cache-Control", "no-store")
            h.end_headers()
            return
        if rng is None:
            start, end, code = 0, size - 1, 200
        else:
            (start, end), code = rng, 206
        length = max(0, end - start + 1)
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(length))
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Cache-Control", "no-store")
        if code == 206:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.end_headers()
        fh.seek(start)
        left = length
        while left > 0:
            chunk = fh.read(min(_CHUNK, left))
            if not chunk:
                break
            try:
                h.wfile.write(chunk)
            except OSError:
                return  # client went away mid-seek; normal for <video>
            left -= len(chunk)


def _serve_recordings(h) -> None:
    try:
        rest = h.path.split("?", 1)[0][len(_PREFIX):]
        parts = rest.split("/")
        if len(parts) == 1:
            want_video = False
        elif len(parts) == 2 and parts[1] == "video":
            want_video = True
        else:
            _json(h, 404, {"ok": False, "error": "not_found"})
            return
        if not _auth_ok(h):
            _json(h, 401, {"error": "unauthorized"})
            return
        code, data, name = load_sidecar(parts[0])
        if code != 200:
            err = "bad_id" if code == 400 else "no_recording"
            _json(h, code, {"ok": False, "error": err})
            return
        if not want_video:
            _json(h, 200, _summary(data, name))
            return
        real = resolve_recording_path(data.get("obs_output_path"))
        if real is None:
            _json(h, 404, {"ok": False, "error": "no_video"})
            return
        _stream(h, real)
    except Exception as exc:  # noqa: BLE001 - never leak a path in a reply
        log.warning("api/recordings: %s", type(exc).__name__)
        try:
            _json(h, 500, {"ok": False, "error": "internal error - see logs"})
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (prefix(_PREFIX), _serve_recordings),
]

POST_ROUTES: list = []
