"""bridge_mcp_server.py - local MCP server exposing the cross-Claude bridge
to a local Claude / agent.

Speaks the MCP JSON-RPC protocol over HTTP on port 8895. Localhost-only:
it shuttles to the local RC dashboard's /api/bridge surface on
https://127.0.0.1:8888 and reads ops/runtime/bridge_inbox_pending.json
directly. Bearer auth is kept anyway (defense in depth + the same token
chain so one RC_MCP_TOKEN covers all RC MCP servers).

Why this server exists
----------------------
The cross-Claude bridge (/api/bridge GET + POST, /api/bridge/pending,
/api/bridge/status) is RC's primary mechanism for Legion <-> Game-PC <->
Peer coordination, but reaching it from a local agent today means either
shelling out to tools/bridge_cli.py or wiring urllib by hand with the
self-signed-cert dance. This wraps the same documented surface as MCP
tools so the agent can ask "what tasks are queued for me", "post this
result for task X", "post a lesson to Peer" without re-deriving the call
shapes per session.

Tools exposed:
  bridge_search(since=0.0, hours=None, limit=100, kind=None, target=None,
                source=None)
      GET /api/bridge messages. Filter by kind/target/source; `hours` is
      a convenience alternative to `since` (since wins if both given).
      Returns {now, messages, count}.

  bridge_post_note(source, summary)
      POST a free-form kind=note. Returns {ok, ts, id, kind}.

  bridge_post_task(source, target, summary, body, id="")
      POST a kind=task envelope. `body` is a dict the receiver knows how
      to execute. Blank id auto-generates a "task-<uuid>" id (matches
      the auto-stamp behavior of remote /api/bridge/inbox).

  bridge_post_result(source, target, summary, body, in_reply_to)
      POST a kind=result envelope paired with the originator's task id.

  bridge_post_lesson(source, target, summary, body)
      POST a kind=lesson envelope (cross-project lesson schema; see
      `RC_PHASE1_LESSON_SCHEMA_2026-05-02.md`).

  bridge_pending()
      Read ops/runtime/bridge_inbox_pending.json - the watcher-curated
      escalation queue (`/api/bridge/pending` mirrors it).

  bridge_status()
      Operator-facing config gate (never leaks the shared secret).

Run locally:
  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_mcp_server.py
  (or via the boot launcher tools/start_bridge_mcp.py)

Schedule at logon for persistence:
  schtasks /Create /TN "RC-Bridge-MCP" /SC ONLOGON /RL HIGHEST /F ^
    /TR "pythonw C:\\Riot Commander\\tools\\start_bridge_mcp.py"

Configure local Claude Code .mcp.json (or settings.json mcpServers):
  {
    "mcpServers": {
      "rc-bridge": {
        "type": "http",
        "url": "http://127.0.0.1:8895/mcp",
        "headers": { "Authorization": "Bearer <token-from --show-token>" }
      }
    }
  }
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.server
import json
import logging
import os
import socket
import ssl
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

HOST = "127.0.0.1"
PORT = 8895
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "rc-bridge-mcp"
SERVER_VERSION = "0.1.0"

# Bridge endpoints on the local RC dashboard. mkcert self-signed; skip
# verify (matches tools/bridge_cli.py - the bearer token on bridge
# inbound is the actual identity check, not the cert).
LEGION_BRIDGE_URL = "https://127.0.0.1:8888/api/bridge"
LEGION_BRIDGE_STATUS_URL = "https://127.0.0.1:8888/api/bridge/status"
_PENDING_PATH = _PROJECT_ROOT / "ops" / "runtime" / "bridge_inbox_pending.json"

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# Hung-tool dispatch watchdog (mirrors ds_matchdb_mcp_server.py - see
# that file for the rationale block on bounded pool + per-tool overrides).
DISPATCH_TIMEOUT_S = float(os.environ.get("RC_MCP_DISPATCH_TIMEOUT_S", "45"))
TOOL_TIMEOUT_OVERRIDES: dict[str, float] = {}
_DISPATCH_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="mcp-dispatch")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rc-bridge-mcp")

_START = time.time()

_VALID_KINDS = ("note", "task", "result", "lesson", "ping")
_VALID_TARGETS = ("legion", "gamepc", "peer", "rc")


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
    return "8e8f131e212b329438218eca27372dde"


AUTH_TOKEN = _resolve_token()


# -- HTTP shuttle helpers ---------------------------------------------------
def _http_get_json(url: str, timeout: float = 4.0) -> dict:
    """GET a JSON document from the local dashboard. Self-signed cert OK."""
    with urlopen(url, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict, timeout: float = 4.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST",
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def _shape_post_error(exc: Exception) -> dict:
    """Render an HTTP-shuttle failure as a structured tool result (never
    raises). Distinguishes "RC dashboard not running" from "RC rejected
    the post" so the caller knows which to fix."""
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8")[:400]
        except Exception:  # noqa: BLE001
            body = ""
        return {"error": f"bridge rejected: HTTP {exc.code}",
                "http_status": exc.code, "response_body": body}
    if isinstance(exc, URLError):
        return {"error": "bridge unreachable (RC dashboard down?)",
                "url": LEGION_BRIDGE_URL,
                "cause": f"{type(exc).__name__}: {exc.reason}"}
    return {"error": f"{type(exc).__name__}: {exc}"}


# -- Validation helpers -----------------------------------------------------
def _norm_source(source: str) -> str | None:
    s = (source or "").strip().lower()
    return s if s else None


def _norm_target(target: str | None) -> str | None:
    if target is None:
        return None
    t = str(target).strip().lower()
    if not t:
        return None
    if t not in _VALID_TARGETS:
        return t  # tolerate unknown peers (future-proof); caller sees it
    return t


def _norm_kind(kind: str) -> str:
    k = (kind or "note").strip().lower()
    return k if k else "note"


# -- Tool implementations ---------------------------------------------------
def tool_bridge_search(since: float = 0.0, hours: float | None = None,
                       limit: int = 100, kind: str | None = None,
                       target: str | None = None,
                       source: str | None = None) -> dict:
    """GET /api/bridge messages with optional filters."""
    cap = max(1, min(int(limit), 500))
    if hours is not None and float(hours) > 0:
        since_ts = max(0.0, time.time() - float(hours) * 3600.0)
    else:
        since_ts = max(0.0, float(since or 0))
    qs = f"since={since_ts}&limit={cap}"
    if kind:
        qs += f"&kind={_norm_kind(kind)}"
    if target:
        nt = _norm_target(target)
        if nt:
            qs += f"&target={nt}"
    if source:
        ns = _norm_source(source)
        if ns:
            qs += f"&source={ns}"
    url = f"{LEGION_BRIDGE_URL}?{qs}"
    try:
        payload = _http_get_json(url)
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)
    msgs = payload.get("messages") or []
    return {"now": payload.get("now", time.time()),
            "count": len(msgs),
            "messages": msgs}


def tool_bridge_post_note(source: str, summary: str) -> dict:
    src = _norm_source(source)
    if not src:
        return {"error": "source required"}
    msg = (summary or "").strip()
    if not msg:
        return {"error": "summary required"}
    try:
        return _http_post_json(LEGION_BRIDGE_URL,
                                {"source": src, "summary": msg, "kind": "note"})
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)


def tool_bridge_post_task(source: str, target: str, summary: str,
                           body: dict | None = None,
                           id: str = "") -> dict:  # noqa: A002
    src = _norm_source(source)
    if not src:
        return {"error": "source required"}
    tgt = _norm_target(target)
    if not tgt:
        return {"error": "target required (legion|gamepc|peer|rc)"}
    msg = (summary or "").strip()
    if not msg:
        return {"error": "summary required"}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return {"error": "body must be a JSON object",
                "got": type(body).__name__}
    # Local POSTs do NOT auto-stamp an id (the auto-stamp lives behind
    # /api/bridge/inbox, the remote-peer route). bridge_pull_tasks
    # filters id-less entries, so stamp one here when blank.
    task_id = str(id or "").strip() or f"task-{uuid.uuid4().hex[:12]}"
    envelope = {"source": src, "summary": msg, "kind": "task",
                "id": task_id, "target": tgt, "body": body}
    try:
        ack = _http_post_json(LEGION_BRIDGE_URL, envelope)
        ack["id"] = ack.get("id") or task_id
        return ack
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)


def tool_bridge_post_result(source: str, target: str, summary: str,
                             in_reply_to: str,
                             body: dict | None = None) -> dict:
    src = _norm_source(source)
    if not src:
        return {"error": "source required"}
    tgt = _norm_target(target)
    if not tgt:
        return {"error": "target required (legion|gamepc|peer|rc)"}
    reply = str(in_reply_to or "").strip()
    if not reply:
        return {"error": "in_reply_to required (the originator's task id)"}
    msg = (summary or "").strip()
    if not msg:
        return {"error": "summary required"}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return {"error": "body must be a JSON object",
                "got": type(body).__name__}
    envelope = {"source": src, "summary": msg, "kind": "result",
                "target": tgt, "in_reply_to": reply, "body": body}
    try:
        return _http_post_json(LEGION_BRIDGE_URL, envelope)
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)


def tool_bridge_post_lesson(source: str, target: str, summary: str,
                             body: dict | None = None) -> dict:
    src = _norm_source(source)
    if not src:
        return {"error": "source required"}
    tgt = _norm_target(target)
    if not tgt:
        return {"error": "target required (legion|gamepc|peer|rc)"}
    msg = (summary or "").strip()
    if not msg:
        return {"error": "summary required"}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return {"error": "body must be a JSON object",
                "got": type(body).__name__}
    envelope = {"source": src, "summary": msg, "kind": "lesson",
                "target": tgt, "body": body}
    try:
        return _http_post_json(LEGION_BRIDGE_URL, envelope)
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)


def tool_bridge_pending() -> dict:
    """Read ops/runtime/bridge_inbox_pending.json directly. This is what
    /api/bridge/pending serves; reading the file avoids needing the
    dashboard process for a pure status probe."""
    if not _PENDING_PATH.exists():
        return {"schema_version": 1, "tasks": [], "watcher_status": "no_file",
                "path": str(_PENDING_PATH)}
    try:
        raw = _PENDING_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}",
                "path": str(_PENDING_PATH)}
    if not isinstance(data, dict):
        data = {"schema_version": 1, "tasks": []}
    data.setdefault("schema_version", 1)
    data.setdefault("tasks", [])
    return data


def tool_bridge_status() -> dict:
    try:
        return _http_get_json(LEGION_BRIDGE_STATUS_URL)
    except Exception as exc:  # noqa: BLE001
        return _shape_post_error(exc)


TOOL_FUNCS = {
    "bridge_search":       tool_bridge_search,
    "bridge_post_note":    tool_bridge_post_note,
    "bridge_post_task":    tool_bridge_post_task,
    "bridge_post_result":  tool_bridge_post_result,
    "bridge_post_lesson":  tool_bridge_post_lesson,
    "bridge_pending":      tool_bridge_pending,
    "bridge_status":       tool_bridge_status,
}


_SRC = {"type": "string",
        "description": "Posting node id (legion|gamepc|peer)"}
_TGT = {"type": "string",
        "description": "Receiving node id (legion|gamepc|peer|rc); rc "
                       "is the legion alias"}
_SUM = {"type": "string",
        "description": "One-line human summary (<=2000 chars)"}
_BODY = {"type": "object",
         "description": "Free-form JSON payload the receiver interprets",
         "default": {}}

TOOLS_SCHEMA = [
    {
        "name": "bridge_search",
        "description": ("Read messages from the cross-Claude bridge log. "
                        "Filter by kind/target/source; `hours` is a "
                        "convenience for `since` (since wins if both)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "number", "default": 0,
                          "description": "Unix timestamp lower bound"},
                "hours": {"type": "number",
                          "description": "Convenience: messages within "
                                         "the last N hours"},
                "limit": {"type": "integer", "default": 100, "minimum": 1,
                          "maximum": 500},
                "kind":   {"type": "string",
                           "enum": list(_VALID_KINDS),
                           "description": "Filter to one kind"},
                "target": {"type": "string",
                           "description": "Filter to one target node"},
                "source": {"type": "string",
                           "description": "Filter to one source node"},
            },
        },
    },
    {
        "name": "bridge_post_note",
        "description": ("Post a free-form kind=note to the bridge. The "
                        "deque + JSONL backup record it; no peer-routing."),
        "inputSchema": {
            "type": "object",
            "properties": {"source": _SRC, "summary": _SUM},
            "required": ["source", "summary"],
        },
    },
    {
        "name": "bridge_post_task",
        "description": ("Post a kind=task envelope addressed to a peer. "
                        "`body` carries the executable payload the "
                        "receiver knows how to action. Blank id "
                        "auto-stamps task-<uuid>."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": _SRC, "target": _TGT, "summary": _SUM,
                "body": _BODY,
                "id": {"type": "string", "default": "",
                       "description": "Explicit task id; blank auto-stamps"},
            },
            "required": ["source", "target", "summary"],
        },
    },
    {
        "name": "bridge_post_result",
        "description": ("Post a kind=result envelope paired with the "
                        "originator's task id. Receiver matches "
                        "in_reply_to to clear the pending entry."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": _SRC, "target": _TGT, "summary": _SUM,
                "in_reply_to": {"type": "string",
                                "description": "Task id this result answers"},
                "body": _BODY,
            },
            "required": ["source", "target", "summary", "in_reply_to"],
        },
    },
    {
        "name": "bridge_post_lesson",
        "description": ("Post a kind=lesson envelope (cross-project "
                        "lesson schema). Body should include the "
                        "Phase-1 schema fields the receiver expects."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": _SRC, "target": _TGT, "summary": _SUM,
                "body": _BODY,
            },
            "required": ["source", "target", "summary"],
        },
    },
    {
        "name": "bridge_pending",
        "description": ("Read the watcher-curated escalation queue from "
                        "ops/runtime/bridge_inbox_pending.json. Does NOT "
                        "require the dashboard process to be running."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bridge_status",
        "description": ("Operator-facing config gate via /api/bridge/status; "
                        "never leaks the shared secret."),
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
    return float(TOOL_TIMEOUT_OVERRIDES.get(name, DISPATCH_TIMEOUT_S))


def _dispatch_tool(name: str, fn, args: dict) -> dict:
    timeout_s = _timeout_for(name)
    fut = _DISPATCH_POOL.submit(fn, **args)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        fut.cancel()
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
    except Exception as e:  # noqa: BLE001
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
    if isinstance(result, dict) and result.get("isError"):
        return result
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

    def _send(self, status: int, body: bytes,
              ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            pass

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {AUTH_TOKEN}":
            self._send(401, b'{"error":"unauthorized"}')
            return False
        return True

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            if not self._check_auth():
                return
            body = json.dumps({"alive": True,
                               "uptime_s": int(time.time() - _START),
                               "tools": list(TOOL_FUNCS.keys())}).encode()
            self._send(200, body)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        if not self.path.startswith("/mcp"):
            self._send(404, b'{"error":"not found"}')
            return
        if not self._check_auth():
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except Exception:  # noqa: BLE001
            n = 0
        raw = self.rfile.read(n) if n else b""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:  # noqa: BLE001
            self._send_jsonrpc(None, error=(-32700, f"Parse error: {e}"))
            return
        is_notification = "id" not in req
        method = req.get("method", "")
        rid = req.get("id")
        params = req.get("params", {}) or {}
        if is_notification:
            log.info("notification: %s", method)
            self._send(202, b"")
            return
        handler = METHOD_HANDLERS.get(method)
        if not handler:
            self._send_jsonrpc(rid, error=(-32601, f"method not found: {method}"))
            return
        try:
            result = handler(params)
        except Exception as e:  # noqa: BLE001
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
        self._send(200, json.dumps(env, default=str).encode())


def serve_forever(host: str = HOST, port: int = PORT) -> int:
    """Bind + serve. Returns an int exit code (mirrors the
    tools/start_*.py launcher contract)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
        probe.close()
        log.warning("port %d already serving - another rc-bridge-mcp "
                    "instance is running; exiting cleanly", port)
        return 0
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass
    finally:
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass
    log.info("rc-bridge-mcp listening on %s:%d (tools=%d, token=...%s)",
             host, port, len(TOOL_FUNCS), AUTH_TOKEN[-4:])
    try:
        srv = http.server.ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        log.error("bind %s:%d failed: %s", host, port, e)
        return 1
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--show-token", action="store_true",
                   help="print token and exit (for client config setup)")
    args = p.parse_args()
    if args.show_token:
        print(AUTH_TOKEN)
        return 0
    return serve_forever(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
