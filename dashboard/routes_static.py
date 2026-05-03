"""Static-asset routes: HTML/css/js, manifest, icons, agent files.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Each route receives the BaseHTTPRequestHandler as its only argument
and uses `h._send(code, body, ctype)` to write the response. Module-
level GET_ROUTES is consumed by `dashboard._dispatch`.
"""
import logging
from pathlib import Path

from dashboard._context import APP_DIR
from dashboard._dispatch import equals, prefix
from dashboard._static import (
    icon_svg_bytes,
    inject_asset_hash,
    legacy_index_html,
    manifest_bytes,
    resolve_safe_icon,
)

log = logging.getLogger("rc.web_dashboard")


def _serve_index(h) -> None:
    # 2026-04-23: serve the new modern UI from web/ by default; keep
    # the legacy inline dashboard reachable at ?ui=legacy in case the
    # new one misbehaves during a live match.
    use_legacy = ("ui=legacy" in h.path)
    if not use_legacy:
        try:
            new_index = (APP_DIR / "web" / "index.html").read_bytes()
            # AUDIT 2026-04-28 (proposal 3.1): replace the manual
            # ?v=YYYYMMDDNN cache-bust query with a content hash.
            # Computed once per request from CSS/JS mtimes — same
            # signal /api/ui-version uses, so reload behaviour is
            # consistent. No human has to bump a counter.
            new_index = inject_asset_hash(new_index)
            h._send(200, new_index, "text/html; charset=utf-8")
            return
        except Exception as exc:
            log.warning("web/index.html serve failed, falling back to legacy: %s", exc)
    h._send(200, legacy_index_html(), "text/html; charset=utf-8")


def _index_matcher(path: str) -> bool:
    return (path == "/" or path == "/index.html"
            or path.startswith("/?") or path.startswith("/index.html?"))


def _serve_web_asset(h) -> None:
    # Serve static assets from web/. Defense: drop any ".." segment
    # and reject anything with a null byte.
    rel = h.path.split("?", 1)[0].lstrip("/")
    if ".." in rel.split("/") or "\x00" in rel:
        h._send(400, b'{"error":"bad path"}', "application/json"); return
    try:
        abs_path = (APP_DIR / "web" / rel).resolve()
        web_root = (APP_DIR / "web").resolve()
        if not str(abs_path).startswith(str(web_root)) or not abs_path.is_file():
            h._send(404, b'{"error":"not found"}', "application/json"); return
        ctype = {
            ".css": "text/css; charset=utf-8",
            ".js":  "application/javascript; charset=utf-8",
            ".json":"application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(abs_path.suffix.lower(), "application/octet-stream")
        h._send(200, abs_path.read_bytes(), ctype)
    except Exception as exc:
        log.warning("static serve %s: %s", h.path, exc)
        h._send(500, b'{"error":"static_serve_failed"}', "application/json")


def _serve_manifest(h) -> None:
    h._send(200, manifest_bytes(), "application/manifest+json")


def _serve_icon(h) -> None:
    h._send(200, icon_svg_bytes(), "image/svg+xml")


def _make_icon_handler(subdir: str):
    """Build a handler that serves PNGs from data/icons/<subdir>/."""
    label = f"icons/{subdir}"
    prefix_str = f"/icons/{subdir}/"
    root = APP_DIR / "data" / "icons" / subdir

    def _handler(h):
        try:
            rel = h.path[len(prefix_str):]
            p = resolve_safe_icon(root, rel)
            if p is None:
                h._send(404, b"not found", "text/plain"); return
            h._send(200, p.read_bytes(), "image/png")
        except Exception as exc:
            log.warning("%s: %s", label, exc)
            h._send(500, b"icon_serve_failed", "text/plain")
    return _handler


# /icons/items/* lives under data/icons/aram_items/ (legacy name) — see
# the slug-naming convention in modes/aram_overlay._load_icon.
def _serve_icon_items_route(h):
    try:
        rel = h.path[len("/icons/items/"):]
        p = resolve_safe_icon(APP_DIR / "data" / "icons" / "aram_items", rel)
        if p is None:
            h._send(404, b"not found", "text/plain"); return
        h._send(200, p.read_bytes(), "image/png")
    except Exception as exc:
        log.warning("icons/items: %s", exc)
        h._send(500, b"icon_serve_failed", "text/plain")


_AGENT_ALLOWED = {
    "gamepc_screen_agent.py", "gamepc_liveclient_relay.py",
    "gamepc_lcu_agent.py", "gamepc_mcp_server.py",
    "gamepc_hotkey_listener.py",
    "GAMEPC_CLAUDE.md",
    "bridge_fetch.py", "bridge_post.py",
    "bridge_pull_tasks.py", "bridge_post_result.py",
    "bridge_task.py",
    "bridge_ping.py", "bridge_heartbeat.py",
    "bridge_setup.ps1", "gamepc_boot.ps1",
    "start_gamepc_claude.ps1",
    "process-bridge-tasks.md",
    "process-bridge-tasks-peer.md",
    "rc_rootCA.pem",
    "BRIDGE_WATCHER_PLAN.md",
    "bridge_watcher.py",
    "bridge_watcher_classify.py",
    "bridge_watcher_config.json",
    "bridge_watcher_hook.ps1",
    "bridge_watcher_install.ps1",
    "bridge_watcher_actions.py",
    "bridge_watcher_action_prompt.md",
}


def _serve_agent_file(h) -> None:
    # Serve agent files (e.g. gamepc_screen_agent.py) for Game-PC deploy.
    # Strict allowlist: only files in tools/, no path traversal.
    name = h.path[len("/agent/"):]
    if name not in _AGENT_ALLOWED:
        h._send(404, b"not found", "text/plain"); return
    try:
        # Stream-read with 4 MiB cap — same defensive pattern as
        # the MCP `tool_read_file` fix from cycle 2. Allowlisted
        # files today are <50 KB so the cap doesn't truncate, but
        # it future-proofs if logs/larger artifacts ever land in
        # the allowlist.
        _AGENT_FILE_CAP = 1 << 22
        with open(APP_DIR / "tools" / name, "rb") as _f:
            body = _f.read(_AGENT_FILE_CAP)
        if name.endswith(".md"):
            ctype = "text/markdown; charset=utf-8"
        elif name.endswith(".pem") or name.endswith(".crt"):
            ctype = "application/x-pem-file"
        elif name.endswith(".ps1"):
            ctype = "text/plain; charset=utf-8"
        elif name.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        else:
            ctype = "text/x-python; charset=utf-8"
        h._send(200, body, ctype)
    except Exception as exc:
        log.warning("agent serve %s: %s", name, exc)
        h._send(500, b"agent_read_failed", "text/plain")


# ── route table ──────────────────────────────────────────────────────

GET_ROUTES = [
    (_index_matcher,                   _serve_index),
    (prefix("/css/"),                  _serve_web_asset),
    (prefix("/js/"),                   _serve_web_asset),
    (prefix("/data/"),                 _serve_web_asset),
    (equals("/manifest.json"),         _serve_manifest),
    (equals("/icon.svg"),              _serve_icon),
    (prefix("/icons/champions/"),      _make_icon_handler("champions")),
    (prefix("/icons/maps/"),           _make_icon_handler("maps")),
    (prefix("/icons/spells/"),         _make_icon_handler("spells")),
    (prefix("/icons/runes/"),          _make_icon_handler("runes")),
    (prefix("/icons/items/"),          _serve_icon_items_route),
    (prefix("/agent/"),                _serve_agent_file),
]

POST_ROUTES: list = []
