"""
lan_bridge.py — Riot Commander LAN bridge (Game-PC).
Runs on Game-PC port 8888.

Supports:
  PUT  /path/to/file   — Moon-PC or other device writes file to Game-PC filesystem
  GET  /data/...       — Moon-PC reads data files (coaching, live, comp_state, etc.)
  GET  /jobs           — Moon-PC polls for pending vision/coach jobs
  POST /jobs/result    — Moon-PC submits job results back to Game-PC
  GET  /health         — liveness check
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json
import logging
import logging.handlers
import os
import time
import threading

# AUDIT-OPUS LOG-002: plain FileHandler grew unbounded to 7.8 MB during audit.
# Replace basicConfig with a RotatingFileHandler: 3 MB × 3 backups = 12 MB cap.
_log_path = r"C:\Riot Commander\logs\lan_bridge.log"
try:
    _lan_handler = logging.handlers.RotatingFileHandler(
        _log_path, maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _lan_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _lan_root = logging.getLogger()
    _lan_root.setLevel(logging.INFO)
    # Clear any pre-existing handlers to avoid double-logging
    for _h in list(_lan_root.handlers):
        _lan_root.removeHandler(_h)
    _lan_root.addHandler(_lan_handler)
except Exception:
    # Fallback to basicConfig if rotation setup fails
    logging.basicConfig(
        filename=_log_path,
        level=logging.INFO,
        format="%(asctime)s %(message)s"
    )

BASE = Path(r"C:\Riot Commander")
os.chdir(BASE)

_READABLE = {
    "data/tft_live_data.json",
    "data/tft_coaching_data.json",
    "data/comp_state.json",
    "data/comp_state.json",
    "ops/runtime/health.json",
    "data/ocr_debug",   # directory
}

# Job queue: Game-PC queues vision/ocr jobs, Moon-PC polls and picks them up
_job_lock   = threading.Lock()
_job_queue  = []    # [{id, type, payload, ts}]
_job_results = {}   # {id: result}
_JOB_TTL    = 30    # seconds before job expires

def _allowed_read(path_str: str) -> bool:
    p = path_str.lstrip("/")
    for allowed in _READABLE:
        if p.startswith(allowed):
            return True
    return False


# AUDIT C2 (2026-04-22): PUT previously accepted any path under BASE via
# simple `BASE / path` concatenation, allowing `..` traversal writes to
# arbitrary filesystem locations with no auth. Writable prefixes are now
# enumerated and every candidate is resolve()-checked to guarantee
# containment. Extensions are also whitelisted.
_WRITABLE_PREFIXES = (
    "moon_sync_inbox/",
    "data/ocr_debug/",
)
_WRITABLE_EXTS = {".json", ".txt", ".png", ".jpg", ".jpeg", ".webp"}


def _safe_put_path(path_str: str) -> Path | None:
    """Return the resolved write target iff it's under ``BASE`` *and* an
    allowlisted prefix *and* carries a whitelisted extension. Otherwise
    ``None`` — caller must reject with 403."""
    raw = path_str.lstrip("/")
    if not any(raw.startswith(pfx) for pfx in _WRITABLE_PREFIXES):
        return None
    if Path(raw).suffix.lower() not in _WRITABLE_EXTS:
        return None
    candidate = (BASE / raw).resolve()
    try:
        candidate.relative_to(BASE.resolve())
    except ValueError:
        return None
    return candidate


class BridgeHandler(BaseHTTPRequestHandler):
    def do_PUT(self):
        try:
            target = _safe_put_path(self.path)
            if target is None:
                self.send_response(403); self.end_headers()
                self.wfile.write(b"forbidden")
                logging.warning(f"PUT REFUSED {self.path}")
                return
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 64 * 1024 * 1024:      # cap at 64 MiB
                self.send_response(413); self.end_headers()
                self.wfile.write(b"payload too large or empty")
                logging.warning(f"PUT REFUSED size={length} path={self.path}")
                return
            data = self.rfile.read(length)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
            self.send_response(200); self.end_headers()
            self.wfile.write(b"OK")
            logging.info(f"PUT {self.path} ({len(data)} bytes)")
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(str(e).encode())
            logging.error(f"PUT error: {e}")

    def do_GET(self):
        path = self.path.lstrip("/").split("?")[0]

        if path == "health":
            payload = json.dumps({"alive": True, "ts": time.time()}).encode()
            self._json(200, payload)
            return

        if path == "jobs":
            # Moon-PC polls for pending jobs
            with _job_lock:
                now = time.time()
                fresh = [j for j in _job_queue if now - j["ts"] < _JOB_TTL]
                _job_queue[:] = fresh
                payload = json.dumps(fresh).encode()
            self._json(200, payload)
            return

        # Static file serve — allow .html, .json, .js, .css, .png, .txt from project root
        fp = BASE / path
        SAFE_EXTS = {'.html','.json','.js','.css','.png','.ico','.txt','.vbs','.bat','.py'}
        is_safe = fp.suffix.lower() in SAFE_EXTS
        # Also allow directory listings for data/ and ops/ paths
        is_allowed_dir = any(path.startswith(p) for p in ('data/','ops/','assets/'))
        if is_safe or _allowed_read(path):
            try:
                if fp.is_file():
                    data = fp.read_bytes()
                    self.send_response(200)
                    ct_map = {'.html':'text/html; charset=utf-8','.json':'application/json',
                              '.js':'application/javascript','.css':'text/css',
                              '.png':'image/png','.ico':'image/x-icon','.txt':'text/plain'}
                    ct = ct_map.get(fp.suffix.lower(), 'application/octet-stream')
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                elif fp.is_dir() and is_allowed_dir:
                    files = [f.name for f in fp.iterdir() if f.is_file()]
                    self._json(200, json.dumps(files).encode())
                    return
            except Exception as e:
                self._json(500, json.dumps({"error": str(e)}).encode())
                return

        self._json(404, b'{"error":"not found"}')

    def do_POST(self):
        path = self.path.lstrip("/")
        if path == "jobs/result":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode())
                job_id = body.get("id", "")
                result = body.get("result", {})
                # Remove from queue, store result
                with _job_lock:
                    _job_queue[:] = [j for j in _job_queue if j["id"] != job_id]
                    _job_results[job_id] = {"result": result, "ts": time.time()}
                # Write result to appropriate data file based on job type
                jtype = body.get("type", "")
                if jtype == "vision" and result:
                    try:
                        out = BASE / "data" / "tft_live_data.json"
                        existing = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
                        existing.update(result)
                        tmp = out.with_suffix(".json.tmp")
                        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
                        tmp.replace(out)
                        logging.info(f"Moon vision result written for job {job_id}")
                    except Exception as e:
                        logging.error(f"Vision result write: {e}")
                self._json(200, b'{"ok":true}')
            except Exception as e:
                self._json(500, json.dumps({"error": str(e)}).encode())
        else:
            self._json(404, b'{"error":"not found"}')

    def _json(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logging.info(fmt % args)


# ARCH-003: dead client API removed — use core/moon_proxy.py for all Moon-PC calls.
# add_vision_job / get_job_result removed: bypassed by BUG-5 fix, moon_proxy is canonical.

if __name__ == "__main__":
    logging.info("LAN bridge starting on 0.0.0.0:8888")
    HTTPServer(("0.0.0.0", 8888), BridgeHandler).serve_forever()
