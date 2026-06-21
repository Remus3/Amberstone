# arch: BaseHTTPRequestHandler routing for :8889 | section=vision | frozen=no
"""HTTP handler - routes /health, /stats, /monitor, /latest-frame, /upload-*,
/vision, /coach, /ocr, /lcu-*, /sync.

Split out of moon_vision_server.py during Phase 2.4.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

from ._config import (AUTH_HEADER, AUTH_TOKEN, SYNC_DIR, VISION_MODEL,
                      _START_TIME, api_key_present, log)
from ._frame import get_latest_frame, handle_upload_frame
from ._inference import handle_coach, handle_ocr, handle_vision
from ._relay import (_lcu_cmd_lock, _lcu_cmd_results, get_latest_liveclient,
                     get_latest_lcu, handle_upload_liveclient,
                     handle_upload_lcu, lcu_drain_pending, lcu_queue_command,
                     lcu_record_result)
from ._stats import get_stats

MONITOR_HTML_PATH = Path(__file__).parent.parent / "moon_monitor.html"


class Handler(BaseHTTPRequestHandler):
    def _auth(self) -> bool:
        return self.headers.get(AUTH_HEADER, "") == AUTH_TOKEN

    # -- GET ----------------------------------------------------------------
    def do_GET(self) -> None:
        # Public: health, stats, monitor page
        if self.path == "/health":
            self._j(200, {"alive": True, "model": VISION_MODEL,
                          "api_key_ok": api_key_present(),
                          "uptime_s": int(time.time() - _START_TIME)})
        elif self.path in ("/stats", "/stats/"):
            try:
                self._j(200, get_stats())
            except Exception as e:  # noqa: BLE001
                log.error("Stats error: %s", e)
                self._j(500, {"error": str(e)})
        elif self.path in ("/monitor", "/monitor.html"):
            try:
                # Look next to server script AND in same dir as working directory
                candidates = [
                    MONITOR_HTML_PATH,
                    Path(__file__).parent.parent / "moon_monitor.html",
                    Path.cwd() / "moon_monitor.html",
                    Path.home() / "Desktop" / "moon_monitor.html",
                    SYNC_DIR / "moon_monitor.html",   # delivered via PUT
                    SYNC_DIR / "monitor.html",        # alternate PUT name
                ]
                found = next((p for p in candidates if p.exists()), None)
                if found:
                    html = found.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self._cors()
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self._j(404, {"error": "moon_monitor.html not found",
                                  "searched": [str(p) for p in candidates]})
            except Exception as e:  # noqa: BLE001
                log.error("Monitor serve error: %s", e)
                self._j(500, {"error": str(e)})
        elif self.path == "/latest-frame" or self.path.startswith("/latest-frame?"):
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            src = self._query_source()
            f = get_latest_frame(src)
            if not f.get("b64"):
                self._j(404, {"error": "no_frame_yet", "ts": 0, "source": src})
                return
            self._j(200, f)
        elif self.path == "/latest-frame/meta" or self.path.startswith("/latest-frame/meta?"):
            # Lightweight: metadata only, no payload. Useful for monitor pages.
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            src = self._query_source()
            f = get_latest_frame(src)
            f.pop("b64", None)
            self._j(200, f)
        elif self.path == "/latest-liveclient":
            # Live Client API snapshot from the Legion-local relay.
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            lc = get_latest_liveclient()
            if not lc.get("data"):
                self._j(404, {"error": "no_liveclient_yet", "ts": 0})
                return
            self._j(200, lc)
        elif self.path == "/latest-lcu":
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            s = get_latest_lcu()
            if not s.get("data"):
                self._j(404, {"error": "no_lcu_yet", "ts": 0})
                return
            self._j(200, s)
        elif self.path == "/lcu-cmd-pending":
            # Agent drains queued commands. Returns and clears queue.
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            self._j(200, {"commands": lcu_drain_pending()})
        elif self.path == "/lcu-cmd-result" or self.path.startswith("/lcu-cmd-result?"):
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            rid = None
            for kv in q.split("&"):
                if kv.startswith("id="):
                    try:
                        rid = int(kv[3:])
                    except ValueError:
                        pass
            if rid is None:
                self._j(400, {"error": "id required"})
                return
            with _lcu_cmd_lock:
                rec = _lcu_cmd_results.get(rid)
            if rec is None:
                self._j(404, {"error": "pending"})
                return
            self._j(200, rec)
        elif self.path == "/sync/list":
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            self._j(200, {"files": [f.name for f in SYNC_DIR.iterdir() if f.is_file()]})
        elif self.path.startswith("/sync/get/"):
            if not self._auth():
                self._j(401, {"error": "unauthorized"})
                return
            fp = SYNC_DIR / self.path[10:]
            if fp.exists():
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._j(404, {"error": "not found"})
        else:
            self._j(404, {"error": "unknown"})

    # -- POST ---------------------------------------------------------------
    def do_POST(self) -> None:
        if not self._auth():
            self._j(401, {"error": "unauthorized"})
            return
        # SAFETY: cap body size BEFORE rfile.read so a bad Content-Length can't
        # OOM us. 10 MiB is well above the 7 MiB frame cap inside
        # handle_upload_frame.
        try:
            cl = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._j(400, {"error": "bad content-length"})
            return
        if cl > 10 * 1024 * 1024:
            self._j(413, {"error": "payload too large"})
            return
        body = self.rfile.read(cl)
        try:
            handlers = {
                "vision": handle_vision,
                "coach": handle_coach,
                "ocr": handle_ocr,
                "upload-frame": handle_upload_frame,
                "upload-liveclient": handle_upload_liveclient,
                "upload-lcu": handle_upload_lcu,
                "lcu-cmd": lambda b: {"id": lcu_queue_command(json.loads(b or '{}'))},
                "lcu-cmd-done": lambda b: (lcu_record_result(
                    (json.loads(b or '{}')).get("id"),
                    (json.loads(b or '{}')).get("result")) or {"ok": True}),
            }
            h = handlers.get(self.path.lstrip("/"))
            if h:
                self._j(200, h(body))
            else:
                self._j(404, {"error": "unknown"})
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", self.path, e)
            self._j(500, {"error": str(e)})

    # -- PUT ----------------------------------------------------------------
    def do_PUT(self) -> None:
        if not self._auth():
            self._j(401, {"error": "unauthorized"})
            return
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            fname = Path(self.path.split("/")[-1]).name
            # Write monitor files to both cwd AND sync inbox for discoverability
            if fname in ("moon_monitor.html", "monitor.html"):
                (Path.cwd() / "moon_monitor.html").write_bytes(data)
            fp = SYNC_DIR / fname
            fp.write_bytes(data)
            self._j(200, {"ok": True})
        except Exception as e:  # noqa: BLE001
            self._j(500, {"error": str(e)})

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-RC-Token")

    def do_OPTIONS(self) -> None:
        """Preflight CORS requests from browser."""
        self.send_response(204)
        self._cors()
        self.end_headers()

    # -- Helpers ------------------------------------------------------------
    def _query_source(self) -> str | None:
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        for kv in q.split("&"):
            if kv.startswith("source="):
                return unquote(kv[len("source="):])
        return None

    def _j(self, code: int, obj: dict) -> None:
        try:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self._cors()
            self.end_headers()
            self.wfile.write(b)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # client closed connection early - harmless

    def log_message(self, fmt: str, *a: object) -> None:
        log.debug("HTTP " + fmt, *a)
