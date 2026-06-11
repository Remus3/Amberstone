"""gamepc_mcp_server.py - MCP server exposing Game-PC tools to Legion's Claude.

Speaks the MCP JSON-RPC protocol over HTTP on port 8892. LAN-only access
between Legion (192.168.8.230) and Game-PC (192.168.8.237); auth via
`Authorization: Bearer <token>`. Token resolution mirrors the screen
agent: env RC_MCP_TOKEN -> tools/mcp_token.txt -> tools/vision_token.txt
-> hardcoded fallback.

Tools exposed:
  run_powershell(command, timeout_s=60)
      Execute PowerShell. Returns {stdout, stderr, exit_code, duration_s}.

  read_file(path, max_bytes=65536, encoding="utf-8")
      Read a local file. Auto-falls-back to base64 for binary content.
      Returns {content, encoding, bytes, truncated}.

  write_file(path, content, mode="overwrite", encoding="utf-8")
      Atomic write (tmp + replace) so half-written files never appear.
      mode="append" supported. Returns {bytes_written, path}.

  list_dir(path, glob="*", limit=200)
      Directory listing with optional glob pattern. Returns
      {entries: [{name, is_dir, size, mtime}, ...], truncated}.

  path_exists(path) -> {exists, is_file, is_dir, size, mtime}

  capture_monitor(monitor_index=0, format="jpeg", quality=85, max_width=null)
      Screenshot a monitor by 0-based index. Returns {b64, format, w, h}.
      Same monitor enum as gamepc_screen_agent.py.

  get_system_info() -> hostname, os, monitors[], python_version, uptime_s

Deploy on Game-PC:
  1. Copy this file to C:\\RC-Agent\\gamepc_mcp_server.py
     (or fetch via curl.exe -sk https://192.168.8.230:8888/agent/gamepc_mcp_server.py
      once the /agent/ allowlist is updated to include this filename.)
  2. C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe -m pip install Pillow  (only Pillow needed; everything else stdlib)
  3. (Optional) set token: $env:RC_MCP_TOKEN = "<long-random-string>"
  4. Run: C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\RC-Agent\\gamepc_mcp_server.py
  5. Schedule at logon for persistence:
       schtasks /Create /TN "RC-MCP-Server" /SC ONLOGON /RL HIGHEST /F ^
         /TR "C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe C:\\RC-Agent\\gamepc_mcp_server.py"

Configure Legion's Claude Code .mcp.json (or settings.json mcpServers):
  {
    "mcpServers": {
      "gamepc": {
        "type": "http",
        "url": "http://192.168.8.237:8892/mcp",
        "headers": { "Authorization": "Bearer <same-token-as-Game-PC>" }
      }
    }
  }

Then `/mcp` reload in Legion's Claude Code; the gamepc tools appear with
the prefix `mcp__gamepc__run_powershell`, etc.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import ctypes
import http.server
import io
import json
import logging
import os
import socket
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8892
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "gamepc-mcp"
SERVER_VERSION = "0.1.0"
SAFE_PS_LIMIT = 60       # default timeout for PS execution
PS_HARD_CEILING = 600    # tool_run_powershell clamps timeout_s to this
MAX_FILE_BYTES = 1 << 22  # 4 MiB hard cap on read/write

# -- Hung-tool watchdog -----------------------------------------------------
# Every tool handler runs under a bounded timeout enforced by a single
# shared thread pool (a bounded executor - NOT one thread per call - so a
# burst of calls cannot explode the thread count). On timeout the caller
# gets a structured MCP error result instead of a hung connection and the
# server stays responsive; the timed-out future is abandoned so a stuck
# handler cannot corrupt a later call's response.
#
# run_powershell already governs itself with a subprocess timeout (own
# hard ceiling PS_HARD_CEILING). The watchdog must sit ABOVE that so it
# never preempts / shortens / double-wraps run_powershell's own bound -
# it is a pure backstop there. Every other handler (read_file on a slow
# path, capture_monitor, list_dir, ...) has NO timeout today; that is the
# gap this closes.
DISPATCH_TIMEOUT_S = float(os.environ.get("RC_MCP_DISPATCH_TIMEOUT_S", "45"))
TOOL_TIMEOUT_OVERRIDES: dict[str, float] = {
    # run_powershell's own subprocess timeout (<= PS_HARD_CEILING) fires
    # first; this only catches a hang in subprocess machinery itself.
    "run_powershell": float(PS_HARD_CEILING) + 30.0,
}
_DISPATCH_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="mcp-dispatch")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gamepc-mcp")

_START = time.time()


# -- Auth token resolution --------------------------------------------------
def _resolve_token() -> str:
    env = os.environ.get("RC_MCP_TOKEN")
    if env:
        return env.strip()
    here = Path(__file__).resolve().parent
    for name in ("mcp_token.txt", "vision_token.txt"):
        p = here / name
        if p.exists():
            try:
                v = p.read_text(encoding="utf-8").splitlines()[0].strip()
                if v:
                    return v
            except OSError:
                pass
    # Hardcoded fallback so the dev path works without setup. Override in prod.
    return "8e8f131e212b329438218eca27372dde"


AUTH_TOKEN = _resolve_token()


# -- Monitor enumeration (Win32) --------------------------------------------
def _enum_monitor_rects() -> list[tuple[int, int, int, int]]:
    rects: list[tuple[int, int, int, int]] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    def _cb(_h, _hdc, lprect, _lp):
        r = lprect.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(_cb), 0)
    return rects


# -- Tool implementations ---------------------------------------------------
def tool_run_powershell(command: str, timeout_s: int = SAFE_PS_LIMIT) -> dict:
    if not isinstance(command, str) or not command.strip():
        return {"error": "empty command"}
    timeout_s = max(1, min(int(timeout_s), 600))
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, timeout=timeout_s, text=True,
            encoding="utf-8", errors="replace",
        )
        return {
            "stdout":     proc.stdout,
            "stderr":     proc.stderr,
            "exit_code":  proc.returncode,
            "duration_s": round(time.time() - t0, 3),
        }
    except subprocess.TimeoutExpired as e:
        return {"error": "timeout", "timeout_s": timeout_s,
                "stdout": e.stdout or "", "stderr": e.stderr or ""}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def tool_read_file(path: str, max_bytes: int = 65536, encoding: str = "utf-8") -> dict:
    p = Path(path)
    if not p.exists():
        return {"error": "not found", "path": str(p)}
    if p.is_dir():
        return {"error": "is a directory", "path": str(p)}
    cap = max(1, min(int(max_bytes), MAX_FILE_BYTES))
    full_size = p.stat().st_size
    truncated = full_size > cap
    # Stream-read up to `cap` bytes; do NOT pull the whole file into
    # memory then slice - a multi-GB log file would OOM the server.
    with open(p, "rb") as f:
        data = f.read(cap)
    try:
        return {"content": data.decode(encoding), "encoding": encoding,
                "bytes": len(data), "full_size": full_size,
                "truncated": truncated, "path": str(p)}
    except UnicodeDecodeError:
        return {"content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64", "bytes": len(data),
                "full_size": full_size, "truncated": truncated, "path": str(p)}


def tool_write_file(path: str, content: str, mode: str = "overwrite",
                     encoding: str = "utf-8") -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode(encoding) if isinstance(content, str) else bytes(content)
    if len(data) > MAX_FILE_BYTES:
        return {"error": "too large", "bytes": len(data), "limit": MAX_FILE_BYTES}
    if mode == "append":
        with open(p, "ab") as f:
            f.write(data)
        return {"path": str(p), "bytes_written": len(data), "mode": "append"}
    # Atomic overwrite - tmp + replace.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return {"path": str(p), "bytes_written": len(data), "mode": "overwrite"}


def tool_list_dir(path: str, glob: str = "*", limit: int = 200) -> dict:
    p = Path(path)
    if not p.exists():
        return {"error": "not found", "path": str(p)}
    if not p.is_dir():
        return {"error": "not a directory", "path": str(p)}
    cap = max(1, min(int(limit), 5000))
    out: list[dict] = []
    truncated = False
    for child in p.glob(glob):
        if len(out) >= cap:
            truncated = True
            break
        try:
            st = child.stat()
            out.append({
                "name":   child.name,
                "is_dir": child.is_dir(),
                "size":   st.st_size,
                "mtime":  st.st_mtime,
            })
        except OSError:
            continue
    out.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": str(p), "entries": out, "truncated": truncated,
            "count": len(out)}


def tool_path_exists(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"exists": False, "path": str(p)}
    st = p.stat()
    return {"exists": True, "is_file": p.is_file(), "is_dir": p.is_dir(),
            "size": st.st_size, "mtime": st.st_mtime, "path": str(p)}


def tool_capture_monitor(monitor_index: int = 0, format: str = "jpeg",
                          quality: int = 85, max_width: int | None = None) -> dict:
    try:
        from PIL import ImageGrab
    except ImportError:
        return {"error": "Pillow not installed (C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe -m pip install Pillow)"}
    rects = _enum_monitor_rects()
    if not rects:
        return {"error": "no monitors enumerated"}
    if monitor_index < 0 or monitor_index >= len(rects):
        return {"error": f"monitor {monitor_index} not present (have {len(rects)})",
                "monitors": [{"index": i, "w": r[2] - r[0], "h": r[3] - r[1],
                              "x": r[0], "y": r[1]} for i, r in enumerate(rects)]}
    bbox = rects[monitor_index]
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    if max_width and img.width > int(max_width):
        ratio = int(max_width) / img.width
        img = img.resize((int(max_width), int(img.height * ratio)))
    buf = io.BytesIO()
    fmt = (format or "jpeg").lower()
    if fmt == "jpeg":
        img.convert("RGB").save(buf, "JPEG", quality=int(quality), optimize=True)
        media = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=True)
        fmt = "png"; media = "image/png"
    return {"b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "format": fmt, "media_type": media,
            "width": img.width, "height": img.height,
            "monitor_index": monitor_index,
            "monitor_rect": {"x": bbox[0], "y": bbox[1],
                             "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]}}


def tool_get_system_info() -> dict:
    rects = _enum_monitor_rects()
    return {
        "hostname":       socket.gethostname(),
        "os":             sys.platform + " " + os.name,
        "python":         sys.version.split()[0],
        "server_name":    SERVER_NAME,
        "server_version": SERVER_VERSION,
        "uptime_s":       round(time.time() - _START, 1),
        "monitors": [{"index": i, "w": r[2] - r[0], "h": r[3] - r[1],
                       "x": r[0], "y": r[1]} for i, r in enumerate(rects)],
        "cwd":            os.getcwd(),
    }


TOOL_FUNCS = {
    "run_powershell":   tool_run_powershell,
    "read_file":        tool_read_file,
    "write_file":       tool_write_file,
    "list_dir":         tool_list_dir,
    "path_exists":      tool_path_exists,
    "capture_monitor":  tool_capture_monitor,
    "get_system_info":  tool_get_system_info,
}


TOOLS_SCHEMA = [
    {
        "name": "run_powershell",
        "description": (
            "Execute a PowerShell command on Game-PC and return its "
            "stdout/stderr/exit_code. Use for system queries, file ops, "
            "scheduled-task management, certificate ops, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command":    {"type": "string", "description": "PowerShell command-line to execute"},
                "timeout_s":  {"type": "integer", "default": 60, "minimum": 1, "maximum": 600},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file on Game-PC. Returns text (utf-8) or base64 for binary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string"},
                "max_bytes": {"type": "integer", "default": 65536, "maximum": MAX_FILE_BYTES},
                "encoding":  {"type": "string", "default": "utf-8"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Atomically write a file on Game-PC (tmp + replace). mode='append' for append.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":     {"type": "string"},
                "content":  {"type": "string"},
                "mode":     {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List entries in a Game-PC directory with optional glob pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":  {"type": "string"},
                "glob":  {"type": "string", "default": "*"},
                "limit": {"type": "integer", "default": 200, "maximum": 5000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "path_exists",
        "description": "Check if a path exists on Game-PC. Returns is_file, is_dir, size, mtime.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "capture_monitor",
        "description": (
            "Screenshot a monitor on Game-PC by 0-based index. Returns base64-encoded "
            "image. Index 0=primary; check get_system_info for monitor enum."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "monitor_index": {"type": "integer", "default": 0},
                "format":        {"type": "string", "enum": ["jpeg", "png"], "default": "jpeg"},
                "quality":       {"type": "integer", "default": 85, "minimum": 1, "maximum": 100},
                "max_width":     {"type": ["integer", "null"], "default": None},
            },
        },
    },
    {
        "name": "get_system_info",
        "description": "Return Game-PC hostname, OS, python version, monitor list, server uptime.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# -- MCP protocol handlers --------------------------------------------------
def handle_initialize(_params: dict) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities":    {"tools": {"listChanged": False}},
        "serverInfo":      {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_tools_list(_params: dict) -> dict:
    return {"tools": TOOLS_SCHEMA}


def _timeout_for(name: str) -> float:
    """Per-tool dispatch timeout. A self-governing long tool (e.g.
    run_powershell with its own subprocess timeout) opts into a higher
    ceiling via TOOL_TIMEOUT_OVERRIDES so this watchdog never preempts
    its own bound."""
    return float(TOOL_TIMEOUT_OVERRIDES.get(name, DISPATCH_TIMEOUT_S))


def _dispatch_tool(name: str, fn, args: dict):
    """Run one tool handler under the bounded-pool watchdog.

    Returns the raw handler result on success, or a structured MCP error
    dict (always carrying ``isError``) on bad args / handler exception /
    timeout. Never raises and never blocks past the per-tool timeout: on
    timeout the future is abandoned (the worker thread keeps running in
    the bounded pool but its result is discarded so it cannot corrupt a
    later response) and a structured error is returned immediately so the
    server stays responsive.
    """
    timeout_s = _timeout_for(name)
    fut = _DISPATCH_POOL.submit(fn, **args)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        fut.cancel()  # only helps if still queued; running threads run on
        log.warning("tool %s exceeded dispatch timeout %.1fs - abandoned",
                    name, timeout_s)
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"tool '{name}' timed out after "
                                     f"{timeout_s:.0f}s (dispatch watchdog); "
                                     f"abandoned to keep server responsive"}],
                "_timeout": True}
    except TypeError as e:
        return {"isError": True,
                "content": [{"type": "text", "text": f"bad arguments: {e}"}]}
    except Exception as e:
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"{type(e).__name__}: {e}\n"
                                     + traceback.format_exc(limit=3)}]}


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    fn = TOOL_FUNCS.get(name)
    if not fn:
        return {"isError": True,
                "content": [{"type": "text", "text": f"unknown tool: {name}"}]}
    result = _dispatch_tool(name, fn, args)
    # Structured error envelopes (bad args / exception / timeout) are
    # already MCP-shaped - pass them straight through (skip the
    # capture_monitor image-wrap + the default text envelope).
    if isinstance(result, dict) and result.get("isError"):
        return result
    # capture_monitor returns binary image data - wrap as MCP image
    # content so Claude Code renders it inline instead of dumping a
    # base64 blob into a text block. Metadata (monitor index, dims,
    # rect) follows in a sibling text block so callers still get the
    # structured info.
    if name == "capture_monitor" and isinstance(result, dict) \
            and result.get("b64") and result.get("media_type"):
        meta = {k: v for k, v in result.items() if k != "b64"}
        return {"content": [
            {"type": "image",
             "data": result["b64"],
             "mimeType": result["media_type"]},
            {"type": "text",
             "text": json.dumps(meta, indent=2, default=str)},
        ]}
    # Default: structured-result-as-text envelope.
    text = json.dumps(result, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}]}


METHOD_HANDLERS = {
    "initialize":  handle_initialize,
    "tools/list":  handle_tools_list,
    "tools/call":  handle_tools_call,
    "ping":        lambda p: {},
}


# -- HTTP server ------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    def log_message(self, fmt: str, *a: object) -> None:
        log.info("HTTP " + fmt, *a)

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {AUTH_TOKEN}":
            self._send(401, b'{"error":"unauthorized"}')
            return False
        return True

    def do_GET(self) -> None:
        # /health for liveness probes (auth-gated like everything else).
        if self.path.startswith("/health"):
            if not self._check_auth(): return
            body = json.dumps({"alive": True, "uptime_s": int(time.time() - _START),
                                "tools": list(TOOL_FUNCS.keys())}).encode()
            self._send(200, body)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        if not self.path.startswith("/mcp"):
            self._send(404, b'{"error":"not found"}'); return
        if not self._check_auth(): return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except Exception:
            n = 0
        raw = self.rfile.read(n) if n else b""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_jsonrpc(None, error=(-32700, f"Parse error: {e}"))
            return
        # Notifications (no `id`) - no response body. Server ACKs with 202.
        is_notification = "id" not in req
        method = req.get("method", "")
        rid    = req.get("id")
        params = req.get("params", {}) or {}
        # Notifications we know how to handle gracefully:
        if is_notification:
            log.info("notification: %s", method)
            self._send(202, b""); return
        handler = METHOD_HANDLERS.get(method)
        if not handler:
            self._send_jsonrpc(rid, error=(-32601, f"method not found: {method}"))
            return
        try:
            result = handler(params)
        except Exception as e:
            log.warning("handler %s raised: %s", method, e)
            self._send_jsonrpc(rid, error=(-32603, f"{type(e).__name__}: {e}"))
            return
        self._send_jsonrpc(rid, result=result)

    def _send_jsonrpc(self, rid, result=None, error=None):
        env = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            code, message = error
            env["error"] = {"code": code, "message": message}
        else:
            env["result"] = result
        self._send(200, json.dumps(env).encode())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--show-token", action="store_true",
                   help="print token and exit (for one-time copy to client config)")
    args = p.parse_args()
    if args.show_token:
        print(AUTH_TOKEN); return 0
    # Port-busy preflight: if another instance is already bound (e.g. the
    # ONLOGON scheduled task fired and now the user manually launched a
    # second copy), exit cleanly with a clear message instead of crashing
    # with a cryptic OSError 10048.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", args.port))
        probe.close()
        log.warning("port %d already serving - another gamepc-mcp instance "
                    "is running; exiting cleanly (no duplicate launch)",
                    args.port)
        return 0
    except (ConnectionRefusedError, socket.timeout, OSError):
        # Nothing listening - proceed to bind.
        pass
    finally:
        try: probe.close()
        except Exception: pass
    log.info("gamepc-mcp listening on %s:%d (tools=%d, token=...%s)",
             args.host, args.port, len(TOOL_FUNCS), AUTH_TOKEN[-4:])
    log.info("monitors: %s",
             [f"{r[2]-r[0]}x{r[3]-r[1]}@({r[0]},{r[1]})"
              for r in _enum_monitor_rects()])
    try:
        srv = http.server.ThreadingHTTPServer((args.host, args.port), _Handler)
    except OSError as e:
        log.error("bind %s:%d failed: %s", args.host, args.port, e)
        return 1
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
