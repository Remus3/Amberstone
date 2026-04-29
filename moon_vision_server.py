"""
moon_vision_server.py — Riot Commander vision + coaching server.

Post-2026-04-19: runs locally on Legion (RC host) at 127.0.0.1:8889.
Game-PC pushes screenshots via POST /upload-frame; coaches on Legion
read from GET /latest-frame and submit them to /vision, /ocr, /coach.
"""
import base64, collections, json, logging, os, re, sys, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("moon_vision_server.log", encoding="utf-8")]
)
log = logging.getLogger("moon_vision")

PORT         = 8889
VISION_MODEL = "claude-haiku-4-5-20251001"
COACH_MODEL  = "claude-haiku-4-5-20251001"
# AUDIT (2026-04-22): token resolved via core.vision_token (env var,
# config file, legacy default). Rotate by setting RC_VISION_TOKEN on
# both Legion and Game-PC then restarting both sides.
# AUDIT 2026-04-28 (proposal 1.7): no in-source fallback. core.vision_token
# is the only resolver; if it can't be imported, fail loud rather than
# silently authenticate every probe with a known constant.
from core.vision_token import get_vision_token as _get_vision_token
AUTH_TOKEN   = _get_vision_token()
AUTH_HEADER  = "X-RC-Token"
SYNC_DIR     = Path("moon_sync_inbox")
SYNC_DIR.mkdir(exist_ok=True)
_START_TIME  = time.time()

# ── Stats tracking ─────────────────────────────────────────────────────────
_stats_lock = threading.Lock()
_stats = {
    "vision":          {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "coach":           {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "ocr":             {"calls": 0, "errors": 0, "total_ms": 0},
    "frame_upload":    {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
    "liveclient_upload": {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
}
_log_ring = collections.deque(maxlen=80)   # rolling request log
_latency_ring = collections.deque(maxlen=60)  # last 60 latencies for sparkline

# ── Latest-frame cache (uploaded by Game-PC screen agent) ──────────────────
# Per-source slots so the continuous RC-ScreenAgent stream does not clobber
# one-shot captures from other sources (e.g. "dashboard-screenshot"). The
# `_latest_frame` dict is kept for backward compatibility and mirrors the
# most recent upload regardless of source.
_frame_lock = threading.Lock()
_latest_frame = {"b64": None, "ts": 0.0, "size": 0, "source": None,
                 "width": None, "height": None, "format": None}
_frames_by_source: dict = {}  # source -> frame dict

def _record(kind, ms, ok=True, tokens=0):
    ts = time.strftime("%H:%M:%S")
    status = "OK" if ok else "ERR"
    with _stats_lock:
        s = _stats[kind]
        s["calls"] += 1
        s["total_ms"] += ms
        if not ok:
            s["errors"] += 1
        if tokens:
            s["tokens_est"] = s.get("tokens_est", 0) + tokens
        _log_ring.append({"ts": ts, "kind": kind, "ms": ms, "ok": ok})
        _latency_ring.append({"kind": kind, "ms": ms, "ts": time.time()})

def get_stats():
    with _stats_lock:
        # Deep copy stats to plain dicts (avoid deque serialization issues)
        stats_copy = {}
        for k, v in _stats.items():
            stats_copy[k] = dict(v)
        log_copy = [dict(x) for x in list(_log_ring)[-30:]]
        lat_copy = [dict(x) for x in list(_latency_ring)]
        return {
            "uptime_s":     int(time.time() - _START_TIME),
            "stats":        stats_copy,
            "log":          log_copy,
            "latency_60":   lat_copy,
            "python":       sys.version.split()[0],
            "vision_model": VISION_MODEL,
            "coach_model":  COACH_MODEL,
            "api_key_ok":   bool(_API_KEY),
        }


# ── API key ────────────────────────────────────────────────────────────────
def _load_key():
    for p in [Path(__file__).parent / "API-Key-Claude.txt",
              Path.home() / "API-Key-Claude.txt",
              Path.home() / "Desktop" / "API-Key-Claude.txt"]:
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                log.info("Key from %s", p); return k
    return os.environ.get("ANTHROPIC_API_KEY", "")

_API_KEY = _load_key()
_client  = None

def _get_client():
    global _client, _API_KEY
    if _client is None:
        import anthropic
        if not _API_KEY: _API_KEY = _load_key()
        _client = anthropic.Anthropic(api_key=_API_KEY)
    return _client


# ── Vision prompt ──────────────────────────────────────────────────────────
_VISION_PROMPT = """Analyze TFT screenshot. Return ONLY valid JSON:
{"traits_active":["N.O.V.A. 3"],"board_units":["Aatrox 2-star","Caitlyn"],
"bench_units":["Kindred","empty"],"shop_units":["Akali","Leona","unknown","Corki","empty"],
"items_equipped":{"Aatrox":["Warmog"]},"items_on_bench":[],"augments":["Crest"],
"gold":null,"hp":null,"level":null,"stage_round":null,
"is_augment_select":false,"augment_choices":[],"last_round_result":null,"round_damage":null}
RULES: Read TRAITS panel (left), SHOP names (bottom cards), BENCH, BOARD (your side only).
Never output trait names as unit names. Spectating -> board_units=["SPECTATING"]."""

def _parse_json(raw):
    # AUDIT (2026-04-22): bare `except: pass` replaced with specific
    # JSONDecodeError catches so SystemExit/KeyboardInterrupt propagate.
    for t in [raw, raw.strip("`").strip()]:
        t2 = t[4:].strip() if t.startswith("json") else t
        try: return json.loads(t2)
        except json.JSONDecodeError: pass
    fb=raw.find("{"); lb=raw.rfind("}")
    if fb!=-1 and lb>fb:
        try: return json.loads(raw[fb:lb+1])
        except json.JSONDecodeError: pass
    return None


# ── LCU relay (Game-PC pushes session state + drains cmd queue) ───────────
_lcu_lock = threading.Lock()
_lcu_state = {"data": None, "ts": 0.0}
_lcu_cmd_lock = threading.Lock()
_lcu_cmd_queue = []     # [{id, cmd}]
_lcu_cmd_results = {}   # id -> result
_lcu_cmd_seq = 0


def handle_upload_lcu(body):
    if not body: return {"error": "empty"}
    try:
        parsed = json.loads(body)
    except Exception as e:
        return {"error": f"bad_json: {e}"}
    with _lcu_lock:
        _lcu_state.update({"data": parsed, "ts": time.time(),
                            "size": len(body)})
    _record("lcu_upload", 0, ok=True)
    return {"ok": True}


def get_latest_lcu():
    with _lcu_lock:
        return dict(_lcu_state)


def lcu_queue_command(cmd: dict) -> int:
    """Dashboard adds a command; agent drains via /lcu-cmd-pending."""
    global _lcu_cmd_seq
    with _lcu_cmd_lock:
        _lcu_cmd_seq += 1
        cid = _lcu_cmd_seq
        _lcu_cmd_queue.append({"id": cid, "cmd": cmd, "ts": time.time()})
    return cid


def lcu_drain_pending() -> list:
    """Agent calls this; returns and clears the pending queue."""
    with _lcu_cmd_lock:
        items = list(_lcu_cmd_queue)
        _lcu_cmd_queue.clear()
    return items


def lcu_record_result(cmd_id: int, result: dict) -> None:
    with _lcu_cmd_lock:
        _lcu_cmd_results[cmd_id] = {"result": result, "ts": time.time()}
        # bound size
        if len(_lcu_cmd_results) > 100:
            oldest = sorted(_lcu_cmd_results.items(), key=lambda x: x[1]["ts"])[:50]
            for k, _ in oldest:
                _lcu_cmd_results.pop(k, None)


# Add lcu_upload to stats so the monitor shows traffic
with _stats_lock:
    if "lcu_upload" not in _stats:
        _stats["lcu_upload"] = {"calls": 0, "errors": 0, "total_ms": 0}


# ── Live Client API relay (Game-PC pushes /liveclientdata snapshots) ──────
_liveclient_lock = threading.Lock()
_liveclient = {"data": None, "ts": 0.0, "size": 0}

def handle_upload_liveclient(body):
    """Game-PC liveclient relay POSTs /liveclientdata/allgamedata JSON.
    Body is the raw JSON from Riot's :2999 endpoint."""
    t0 = time.time()
    if not body:
        _record("liveclient_upload", 0, ok=False)
        return {"error": "empty body"}
    try:
        parsed = json.loads(body)
    except Exception as e:
        _record("liveclient_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": f"bad_json: {e}"}
    with _liveclient_lock:
        _liveclient.update({
            "data": parsed,
            "ts":   time.time(),
            "size": len(body),
        })
    ms = int((time.time() - t0) * 1000)
    with _stats_lock:
        _stats["liveclient_upload"]["bytes"] = (
            _stats["liveclient_upload"].get("bytes", 0) + len(body)
        )
    _record("liveclient_upload", ms, ok=True)
    return {"ok": True, "size": len(body), "ts": _liveclient["ts"]}


def get_latest_liveclient():
    with _liveclient_lock:
        return dict(_liveclient)


# ── Frame upload / fetch ───────────────────────────────────────────────────
def handle_upload_frame(body):
    """Game-PC agent POSTs the latest screenshot here.
    Body: {image_b64, source?, width?, height?, format?, primary?}

    `primary` (default True, for back-compat with the single-stream
    deployment) controls whether this upload also updates the global
    `_latest_frame` slot that coaches read via `/latest-frame` with no
    source filter. A secondary stream (e.g. UI-debug capture of the RC
    dashboard on monitor 1) should pass `primary=False` so it lands in
    `_frames_by_source[src]` only and doesn't clobber the League game
    frame the vision coaches are consuming. Legion-side readers that
    want that secondary stream query `/latest-frame?source=<channel>`.
    """
    t0 = time.time()
    try:
        d = json.loads(body)
    except Exception:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_json"}
    img = d.get("image_b64", "")
    if not img:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "no image_b64"}
    # 2026-04-27 audit: cap b64 payload at ~7 MB (≈5 MB decoded). Typical
    # frames are ~150 KB; anything 50× that is either a 4K screenshot we
    # don't want to cache or a misbehaving uploader. Without this, a stray
    # 100 MB upload would OOM the server before magic-byte validation runs.
    _MAX_FRAME_B64 = 7_000_000
    if len(img) > _MAX_FRAME_B64:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "frame_too_large", "size": len(img), "limit": _MAX_FRAME_B64}
    # 2026-04-25: Magic-byte validation. Catches a corrupt / truncated /
    # non-image payload at upload time so coaches don't get garbage at
    # the /latest-frame fetch and waste a Sonnet call analyzing it. Cost
    # is one base64 decode of the leading 16 bytes — negligible vs the
    # ~150 KB frame we're about to cache.
    try:
        import base64 as _b64
        head = _b64.b64decode(img[:64], validate=False)[:8]
        is_jpeg = head[:3] == b"\xff\xd8\xff"
        is_png  = head[:8] == b"\x89PNG\r\n\x1a\n"
        if not (is_jpeg or is_png):
            _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
            return {"error": "not_an_image",
                    "head_hex": head.hex(),
                    "size": len(img)}
    except Exception as _exc:
        log.debug("frame magic check failed: %s", _exc)
        # Don't fail-closed on validation glitches — let the frame through
        # so a corner-case base64 layout doesn't blackhole real captures.
    src = d.get("source", "unknown")
    primary = bool(d.get("primary", True))
    frame = {
        "b64":    img,
        "ts":     time.time(),
        "size":   len(img),
        "source": src,
        "width":  d.get("width"),
        "height": d.get("height"),
        "format": d.get("format", "png"),
        "primary": primary,
    }
    with _frame_lock:
        _frames_by_source[src] = dict(frame)
        if primary:
            _latest_frame.update(frame)
    ms = int((time.time() - t0) * 1000)
    with _stats_lock:
        _stats["frame_upload"]["bytes"] = (
            _stats["frame_upload"].get("bytes", 0) + len(img)
        )
    _record("frame_upload", ms, ok=True)
    return {"ok": True, "size": len(img), "ts": frame["ts"],
            "source": src, "primary": primary}


def get_latest_frame(source: str | None = None):
    """Return a copy of the latest cached frame metadata + b64.

    If `source` is given, returns the most recent upload from that source
    only (or an empty dict if none seen). Otherwise returns the overall
    latest upload regardless of source.
    """
    with _frame_lock:
        if source is not None:
            return dict(_frames_by_source.get(source, {"b64": None, "ts": 0.0}))
        return dict(_latest_frame)


# ── Handlers ───────────────────────────────────────────────────────────────
def _crop_to_primary(img_b64: str) -> tuple[str, str]:
    """AUDIT 2026-04-29 (gap C): the Game-PC screen agent stitches both
    monitors into one frame (3840×1280 typical). League runs on monitor 0
    at 1920×1080; the right half of the stitched frame is the dashboard
    on the iPad-via-Duet display, which Sonnet wastes time analysing.

    Crop to the primary 1920×1080 region before /vision. Cuts Sonnet
    input by ~50% (image area) → roughly halves latency and cost.

    Returns (cropped_b64, media_type). On any decode/encode failure,
    returns the original b64 + best-guess media type — the worst case
    is "we burned 3.6 s instead of 1.8 s on this one call".

    Disable via env: RC_VISION_NO_CROP=1.
    """
    if os.environ.get("RC_VISION_NO_CROP") == "1":
        mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
        return img_b64, mt
    try:
        from PIL import Image
        import base64 as _b64
        import io as _io
        raw = _b64.b64decode(img_b64)
        img = Image.open(_io.BytesIO(raw))
        w, h = img.size
        # Already small? Skip — this is a non-stitched frame from a
        # single-monitor capture (or a future cropped agent).
        if w <= 1920 and h <= 1080:
            mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
            return img_b64, mt
        cropped = img.crop((0, 0, min(1920, w), min(1080, h)))
        buf = _io.BytesIO()
        # JPEG quality 85 keeps text legible while being ~70% smaller
        # than PNG. Sonnet sees the same content either way.
        cropped.save(buf, format="JPEG", quality=85, optimize=True)
        out = _b64.b64encode(buf.getvalue()).decode("ascii")
        log.debug("Vision crop: %dx%d → %dx%d (%d → %d KB)",
                  w, h, cropped.width, cropped.height,
                  len(raw)//1024, len(buf.getvalue())//1024)
        return out, "image/jpeg"
    except Exception as exc:
        log.warning("Vision crop failed (%s) — sending original frame", exc)
        mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
        return img_b64, mt


def _record_to_cost_tracker(resp, *, model: str, purpose: str) -> None:
    """AUDIT 2026-04-29 (in-game audit gap B): the vision server holds
    the only Anthropic client that runs Sonnet for vision calls. Without
    this hook, cost_tracker stays at $0.00 forever even as vision burns
    real dollars. Best-effort: a telemetry hiccup must never break the
    coach loop, so failures are swallowed."""
    try:
        from core.cost_tracker import get_tracker as _gt
        u = getattr(resp, "usage", None)
        _gt().record_call(
            model=model,
            input_tokens=getattr(u, "input_tokens", 0) or 0 if u else 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0 if u else 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0 if u else 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0 if u else 0,
            purpose=purpose,
        )
    except Exception as e:
        log.debug("cost_tracker record_call: %s", e)


def handle_vision(body):
    d=json.loads(body); img=d.get("image_b64",""); model=d.get("model",VISION_MODEL)
    if not img: return {"error":"no image_b64"}
    # AUDIT 2026-04-29 (gap C): crop stitched dual-monitor frame to the
    # primary 1920×1080 region before sending. Halves Sonnet input area.
    img_send, media_type = _crop_to_primary(img)
    t0=time.time()
    try:
        resp=_get_client().messages.create(model=model, max_tokens=1400,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64",
                    "media_type": media_type,
                    "data":img_send}},
                {"type":"text","text":_VISION_PROMPT}]}])
        ms=int((time.time()-t0)*1000)
        raw=resp.content[0].text.strip()
        result=_parse_json(raw)
        tok=getattr(resp, 'usage', None)
        tokens=(tok.input_tokens+tok.output_tokens) if tok else 0
        # AUDIT 2026-04-29 (gap B): feed cost_tracker.
        _record_to_cost_tracker(resp, model=model, purpose="vision_relay")
        if result is None:
            _record("vision", ms, ok=False)
            return {"error":"parse_failed","raw":raw[:200]}
        _record("vision", ms, ok=True, tokens=tokens)
        log.info("Vision OK %dms tok=%d", ms, tokens)
        return {"ok":True,"result":result,"latency_ms":ms}
    except Exception as e:
        ms=int((time.time()-t0)*1000)
        _record("vision", ms, ok=False)
        raise

def handle_coach(body):
    d=json.loads(body); p=d.get("prompt",""); model=d.get("model",COACH_MODEL)
    if not p: return {"error":"no prompt"}
    t0=time.time()
    try:
        resp=_get_client().messages.create(model=model, max_tokens=600,
            messages=[{"role":"user","content":p}])
        ms=int((time.time()-t0)*1000)
        text=resp.content[0].text.strip()
        tok=getattr(resp,'usage',None)
        tokens=(tok.input_tokens+tok.output_tokens) if tok else 0
        # AUDIT 2026-04-29 (gap B): feed cost_tracker.
        _record_to_cost_tracker(resp, model=model, purpose="coach_relay")
        _record("coach", ms, ok=True, tokens=tokens)
        log.info("Coach OK %dms tok=%d", ms, tokens)
        return {"ok":True,"text":text,"latency_ms":ms}
    except Exception as e:
        ms=int((time.time()-t0)*1000)
        _record("coach", ms, ok=False)
        raise

_TESSERACT_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def handle_ocr(body):
    d=json.loads(body); crops=d.get("crops",{})
    if not crops: return {"error":"no crops"}
    try:
        import pytesseract; from PIL import Image, ImageEnhance
    except ImportError: return {"error":"pytesseract/PIL missing"}
    # winget install does not add Tesseract to PATH on Windows; pin to default.
    import os.path as _osp
    if not pytesseract.pytesseract.tesseract_cmd or not _osp.isfile(pytesseract.pytesseract.tesseract_cmd):
        if _osp.isfile(_TESSERACT_DEFAULT):
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_DEFAULT
    results={}
    t0=time.time()
    def _pre(b64,scale=3):
        img=Image.open(BytesIO(base64.b64decode(b64))).convert("L")
        w,h=img.size; img=img.resize((w*scale,h*scale),Image.LANCZOS)
        return ImageEnhance.Contrast(img).enhance(2.5)
    # AUDIT (2026-04-22): specific exception classes — pytesseract raises
    # pytesseract.TesseractError / EnvironmentError / OSError on tool
    # failures; PIL raises PIL.UnidentifiedImageError / OSError on crop
    # decode. Keep the silent-continue behaviour (OCR is best-effort) but
    # stop swallowing SystemExit/KeyboardInterrupt.
    _OCR_EXC = (RuntimeError, OSError, ValueError, AttributeError)
    if "stage_round" in crops:
        try:
            t=re.sub(r"[^0-9\-]","",pytesseract.image_to_string(_pre(crops["stage_round"],4),
                config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-").strip())
            m=re.match(r"^([1-7])-([1-7])$",t)
            if m:
                s,r2=int(m.group(1)),int(m.group(2))
                if 1<=s<=7 and 1<=r2<=(4 if s==1 else 7): results["stage_round"]=f"{s}-{r2}"
        except _OCR_EXC: pass
    if "level" in crops:
        try:
            t=pytesseract.image_to_string(_pre(crops["level"]),
                config="--oem 3 --psm 7 -c tessedit_char_whitelist=Llv0123456789 ").strip()
            m=re.search(r"\d+",t)
            if m and 1<=int(m.group())<=10: results["level"]=int(m.group())
        except _OCR_EXC: pass
    if "gold" in crops:
        try:
            t=re.sub(r"[^0-9]","",pytesseract.image_to_string(_pre(crops["gold"]),
                config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789").strip())
            if t and 0<=int(t)<=999: results["gold"]=int(t)
        except _OCR_EXC: pass
    ms=int((time.time()-t0)*1000)
    _record("ocr", ms, ok=True)
    log.info("OCR: %s %dms", results, ms)
    return {"ok":True,"result":results}


# ── HTTP handler ───────────────────────────────────────────────────────────
MONITOR_HTML_PATH = Path(__file__).parent / "moon_monitor.html"

class Handler(BaseHTTPRequestHandler):
    def _auth(self):
        return self.headers.get(AUTH_HEADER,"") == AUTH_TOKEN

    def do_GET(self):
        # Public: health, stats, monitor page
        if self.path == "/health":
            self._j(200,{"alive":True,"model":VISION_MODEL,
                         "api_key_ok":bool(_API_KEY),
                         "uptime_s":int(time.time()-_START_TIME)})
        elif self.path in ("/stats", "/stats/"):
            try:
                self._j(200, get_stats())
            except Exception as e:
                log.error("Stats error: %s", e)
                self._j(500, {"error": str(e)})
        elif self.path in ("/monitor", "/monitor.html"):
            try:
                # Look next to server script AND in same dir as working directory
                candidates = [
                    MONITOR_HTML_PATH,
                    Path(__file__).parent / "moon_monitor.html",
                    Path.cwd() / "moon_monitor.html",
                    Path.home() / "Desktop" / "moon_monitor.html",
                    SYNC_DIR / "moon_monitor.html",   # delivered via PUT
                    SYNC_DIR / "monitor.html",        # alternate PUT name
                ]
                found = next((p for p in candidates if p.exists()), None)
                if found:
                    html = found.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type","text/html; charset=utf-8")
                    self.send_header("Content-Length",str(len(html)))
                    self._cors()
                    self.end_headers(); self.wfile.write(html)
                else:
                    self._j(404,{"error":"moon_monitor.html not found","searched":[str(p) for p in candidates]})
            except Exception as e:
                log.error("Monitor serve error: %s", e)
                self._j(500, {"error": str(e)})
        elif self.path == "/latest-frame" or self.path.startswith("/latest-frame?"):
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            # Optional ?source=<name> picks a specific source's latest frame.
            src = None
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            for kv in q.split("&"):
                if kv.startswith("source="):
                    from urllib.parse import unquote
                    src = unquote(kv[len("source="):])
            f = get_latest_frame(src)
            if not f.get("b64"):
                self._j(404,{"error":"no_frame_yet","ts":0,"source":src}); return
            self._j(200, f)
        elif self.path == "/latest-frame/meta" or self.path.startswith("/latest-frame/meta?"):
            # Lightweight: metadata only, no payload. Useful for monitor pages.
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            src = None
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            for kv in q.split("&"):
                if kv.startswith("source="):
                    from urllib.parse import unquote
                    src = unquote(kv[len("source="):])
            f = get_latest_frame(src); f.pop("b64", None)
            self._j(200, f)
        elif self.path == "/latest-liveclient":
            # Live Client API snapshot relayed from Game-PC.
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            lc = get_latest_liveclient()
            if not lc.get("data"):
                self._j(404,{"error":"no_liveclient_yet","ts":0}); return
            self._j(200, lc)
        elif self.path == "/latest-lcu":
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            s = get_latest_lcu()
            if not s.get("data"):
                self._j(404,{"error":"no_lcu_yet","ts":0}); return
            self._j(200, s)
        elif self.path == "/lcu-cmd-pending":
            # Agent drains queued commands. Returns and clears queue.
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            self._j(200, {"commands": lcu_drain_pending()})
        elif self.path == "/sync/list":
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            self._j(200,{"files":[f.name for f in SYNC_DIR.iterdir() if f.is_file()]})
        elif self.path.startswith("/sync/get/"):
            if not self._auth(): self._j(401,{"error":"unauthorized"}); return
            fp=SYNC_DIR/self.path[10:]
            if fp.exists():
                data=fp.read_bytes(); self.send_response(200)
                self.send_header("Content-Length",str(len(data))); self.end_headers()
                self.wfile.write(data)
            else: self._j(404,{"error":"not found"})
        else:
            self._j(404,{"error":"unknown"})

    def do_POST(self):
        if not self._auth(): self._j(401,{"error":"unauthorized"}); return
        body=self.rfile.read(int(self.headers.get("Content-Length",0)))
        try:
            handlers={"vision":handle_vision,"coach":handle_coach,"ocr":handle_ocr,
                      "upload-frame":handle_upload_frame,
                      "upload-liveclient":handle_upload_liveclient,
                      "upload-lcu":handle_upload_lcu,
                      "lcu-cmd":lambda b: {"id": lcu_queue_command(json.loads(b or '{}'))},
                      "lcu-cmd-done":lambda b: (lcu_record_result(
                          (json.loads(b or '{}')).get("id"),
                          (json.loads(b or '{}')).get("result")) or {"ok": True})}
            h=handlers.get(self.path.lstrip("/"))
            if h: self._j(200,h(body))
            else: self._j(404,{"error":"unknown"})
        except Exception as e:
            log.error("%s: %s",self.path,e); self._j(500,{"error":str(e)})

    def do_PUT(self):
        if not self._auth(): self._j(401,{"error":"unauthorized"}); return
        data=self.rfile.read(int(self.headers.get("Content-Length",0)))
        try:
            fname = Path(self.path.split("/")[-1]).name
            # Write monitor files to both cwd AND sync inbox for discoverability
            if fname in ("moon_monitor.html", "monitor.html"):
                (Path.cwd() / "moon_monitor.html").write_bytes(data)
            fp = SYNC_DIR / fname
            fp.write_bytes(data); self._j(200,{"ok":True})
        except Exception as e: self._j(500,{"error":str(e)})

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-RC-Token")

    def do_OPTIONS(self):
        """Preflight CORS requests from browser."""
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _j(self,code,obj):
        try:
            b=json.dumps(obj).encode(); self.send_response(code)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(b)))
            self._cors()
            self.end_headers(); self.wfile.write(b)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # client closed connection early — harmless

    def log_message(self,fmt,*a): log.debug("HTTP "+fmt,*a)


if __name__=="__main__":
    if not _API_KEY: log.error("No API key"); sys.exit(1)

    # Guard: exit cleanly if another instance is already on this port
    import socket as _sock
    _probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    _probe.settimeout(1)
    _already = _probe.connect_ex(("127.0.0.1", PORT)) == 0
    _probe.close()
    if _already:
        log.warning("Port %d already in use — another instance is running. Exiting.", PORT)
        sys.exit(0)   # clean exit, not error — autostart VBS sees success

    _get_client(); log.info("Moon Vision Server on 0.0.0.0:%d  python=%s",PORT,sys.executable)
    s=HTTPServer(("0.0.0.0",PORT),Handler)
    try: s.serve_forever()
    except KeyboardInterrupt: s.shutdown()
