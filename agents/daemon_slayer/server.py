"""Phase 3 — local HTTP server for the Daemon Slayer engine.

Wraps `stats`, `dps`, `rank` (and snapshot metadata) in plain-HTTP routes
on `:8893`. Stdlib ``ThreadingHTTPServer`` to match the rest of RC; no
FastAPI/aiohttp dependency. Snapshot is loaded once at startup and held
in memory — patch hot-reload lands in Phase 7 alongside the supervisor
entry.

Routes (all accept GET with query params for read-only sanity checking;
POST + JSON body is the contract for production callers):

  GET  /                  — index page with usage examples
  GET  /health            — engine + snapshot health
  GET  /snapshot          — patch + counts + manifest excerpt
  POST /stats             — body: {champion, level, items?, mode?}
  POST /dps               — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?, phase?}
  POST /rank              — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?, phase?,
                                    budget?, slots?, top?, sort?,
                                    include_components?, only?}
  POST /beam              — body: {champion, level, items?, mode?,
                                    target_armor?, target_mr?, phase?,
                                    slots?, beam_width?, top?,
                                    total_budget?, include_components?,
                                    only?, boots_unique?}

Errors map to:
  400 — body parse failure, missing required field, bad enum value
  404 — unknown champion or item id (KeyError from engine)
  422 — value-out-of-range / engine ValueError
  500 — anything unexpected
"""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from . import ENGINE_VERSION
from .beam import (
    DEFAULT_BEAM_WIDTH,
    DEFAULT_TOP_N as BEAM_DEFAULT_TOP_N,
    beam_search_build,
)
from .data_loader import DataSnapshot, SnapshotNotFound
from .dps import compute_dps
from .engine import build_champion
from .rank import SORT_KEYS, rank_items

_log = logging.getLogger("daemon_slayer.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8893

_INDEX_HTML = """<!doctype html>
<meta charset=utf-8>
<title>Daemon Slayer engine</title>
<style>
  body {{ font: 14px/1.45 system-ui, sans-serif; max-width: 780px;
         margin: 2em auto; padding: 0 1em; color: #1a1a1a; }}
  h1, h2 {{ font-weight: 600; }}
  code, pre {{ background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
  pre {{ padding: 10px; overflow-x: auto; }}
  table {{ border-collapse: collapse; }}
  td, th {{ padding: 4px 10px; border-bottom: 1px solid #eee; text-align: left; }}
  .ok {{ color: #1f7a1f; font-weight: 600; }}
</style>
<h1>Daemon Slayer engine — v{version}</h1>
<p class=ok>snapshot patch <code>{patch}</code> &middot; {n_champ} champions &middot; {n_items} items</p>

<h2>Routes</h2>
<table>
<tr><th>method</th><th>path</th><th>purpose</th></tr>
<tr><td>GET</td><td><a href=/health>/health</a></td><td>liveness + version</td></tr>
<tr><td>GET</td><td><a href=/snapshot>/snapshot</a></td><td>patch + counts</td></tr>
<tr><td>POST</td><td>/stats</td><td>resolve champion stats at level + items</td></tr>
<tr><td>POST</td><td>/dps</td><td>auto-attack DPS over rotation scenarios</td></tr>
<tr><td>POST</td><td>/rank</td><td>rank items by DPS delta</td></tr>
<tr><td>POST</td><td>/beam</td><td>full-build beam search (top-N complete builds)</td></tr>
</table>

<h2>Example</h2>
<pre>curl -sX POST http://127.0.0.1:{port}/dps \\
  -H "content-type: application/json" \\
  -d '{{"champion":"Aatrox","level":11,"items":["6692","3006"],
       "mode":"ARAM","target_armor":80}}'</pre>

<p>GET equivalents accept the same fields as query parameters
(<code>items</code> comma-separated):
<a href="/stats?champion=Aatrox&level=11&items=6692,3006">
/stats?champion=Aatrox&amp;level=11&amp;items=6692,3006</a></p>
"""


# ---------------------------------------------------------------- snapshot cache


class _SnapshotCache:
    """Single-snapshot holder. Loaded once at server start; tests can
    inject by passing ``snapshot=`` to ``start_server``. Hot-reload on
    patch change is Phase 7."""

    def __init__(self) -> None:
        self._snap: Optional[DataSnapshot] = None
        self._lock = threading.Lock()

    def set(self, snap: DataSnapshot) -> None:
        with self._lock:
            self._snap = snap

    def get(self) -> DataSnapshot:
        with self._lock:
            if self._snap is None:
                raise RuntimeError("snapshot not loaded yet")
            return self._snap


_CACHE = _SnapshotCache()


def _load_default_snapshot(
    patch: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> DataSnapshot:
    return DataSnapshot.load(patch=patch, data_root=data_root)


# ---------------------------------------------------------------- handler


class _ApiError(Exception):
    """Mapped to a JSON 4xx/5xx by the handler."""

    def __init__(self, status: int, message: str, *, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def _coerce_str_list(value: Any, field_name: str) -> list[str]:
    """Accept ``list[str|int]`` (from JSON) or comma-separated string (from
    a query param). Returns canonicalised list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    raise _ApiError(400, f"{field_name}: expected list or comma-separated string, got {type(value).__name__}")


def _required_str(body: dict, key: str) -> str:
    v = body.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise _ApiError(400, f"missing required field: {key}")
    return str(v).strip()


def _opt_int(body: dict, key: str, default: Optional[int] = None) -> Optional[int]:
    v = body.get(key, default)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected integer, got {v!r}")


def _opt_float(body: dict, key: str, default: float = 0.0) -> float:
    v = body.get(key, default)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise _ApiError(400, f"{key}: expected number, got {v!r}")


def _opt_bool(body: dict, key: str, default: bool = False) -> bool:
    v = body.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def _opt_str(body: dict, key: str, default: Optional[str] = None) -> Optional[str]:
    v = body.get(key, default)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


# ---------------------------------------------------------------- route handlers


def _route_stats(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _required_str(body, "champion")
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    augments = _coerce_str_list(body.get("augments"), "augments")
    try:
        resolved = build_champion(snap, champion_id=champion, level=level,
                                  item_ids=items, mode=mode, augments=augments)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return resolved.to_dict()


def _route_dps(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _required_str(body, "champion")
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    phase = _opt_str(body, "phase")
    augments = _coerce_str_list(body.get("augments"), "augments")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    try:
        result = compute_dps(snap, champion_id=champion, level=level,
                             item_ids=items, mode=mode,
                             target_armor=target_armor, target_mr=target_mr,
                             phase=phase, augments=augments)
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_rank(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _required_str(body, "champion")
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    phase = _opt_str(body, "phase")
    augments = _coerce_str_list(body.get("augments"), "augments")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    budget = _opt_int(body, "budget", None)
    slot_count = _opt_int(body, "slots", 6) or 6
    top_n = _opt_int(body, "top", 20)
    if top_n is None:
        top_n = 20
    sort_by = _opt_str(body, "sort", "delta") or "delta"
    if sort_by not in SORT_KEYS:
        raise _ApiError(400, f"sort: must be one of {list(SORT_KEYS)}, got {sort_by!r}")
    include_components = _opt_bool(body, "include_components", False)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = rank_items(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            phase=phase,
            budget=budget, slot_count=slot_count, top_n=top_n,
            include_components=include_components,
            only_item_ids=only_ids, sort_by=sort_by,
            augments=augments,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_beam(body: dict) -> dict:
    snap = _CACHE.get()
    champion = _required_str(body, "champion")
    level = _opt_int(body, "level", 1) or 1
    items = _coerce_str_list(body.get("items"), "items")
    mode = _opt_str(body, "mode", "SR") or "SR"
    target_armor = _opt_float(body, "target_armor", 0.0)
    target_mr = _opt_float(body, "target_mr", 0.0)
    phase = _opt_str(body, "phase")
    if phase is not None and phase not in ("early", "mid", "late"):
        raise _ApiError(400, f"phase: must be early|mid|late, got {phase!r}")
    slot_count = _opt_int(body, "slots", 6) or 6
    beam_width = _opt_int(body, "beam_width", DEFAULT_BEAM_WIDTH) or DEFAULT_BEAM_WIDTH
    top_n = _opt_int(body, "top", BEAM_DEFAULT_TOP_N) or BEAM_DEFAULT_TOP_N
    total_budget = _opt_int(body, "total_budget", None)
    include_components = _opt_bool(body, "include_components", False)
    boots_unique = _opt_bool(body, "boots_unique", True)
    only_ids: Optional[list[str]] = None
    if "only" in body and body["only"] not in (None, ""):
        only_ids = _coerce_str_list(body["only"], "only")
    try:
        result = beam_search_build(
            snap,
            champion_id=champion, level=level,
            current_item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            phase=phase,
            slot_count=slot_count, beam_width=beam_width, top_n=top_n,
            total_budget=total_budget,
            include_components=include_components,
            only_item_ids=only_ids,
            boots_unique=boots_unique,
        )
    except KeyError as e:
        raise _ApiError(404, str(e))
    except ValueError as e:
        raise _ApiError(422, str(e))
    return result.to_dict()


def _route_health() -> dict:
    try:
        snap = _CACHE.get()
        return {
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "patch": snap.patch,
            "champions": len(snap.champions),
            "items": len(snap.items),
        }
    except RuntimeError:
        return {
            "status": "loading",
            "engine_version": ENGINE_VERSION,
            "patch": None,
            "champions": 0,
            "items": 0,
        }


def _route_snapshot() -> dict:
    snap = _CACHE.get()
    manifest = snap.manifest or {}
    return {
        "patch": snap.patch,
        "champions": len(snap.champions),
        "items": len(snap.items),
        "scenarios_by_id": len(snap.scenarios_by_id),
        "scenarios_by_lolmath": len(snap.scenarios_by_lolmath),
        "manifest": {
            "phase": manifest.get("phase"),
            "extracted_at": manifest.get("extracted_at"),
            "ddragon_version": manifest.get("ddragon_version"),
            "sources": manifest.get("sources"),
            "counts": manifest.get("counts"),
        },
    }


# ---------------------------------------------------------------- dispatcher


_POST_ROUTES = {
    "/stats": _route_stats,
    "/dps": _route_dps,
    "/rank": _route_rank,
    "/beam": _route_beam,
}

# GET routes that need a body merge from query params for the same handler.
_GET_DISPATCH_ROUTES = set(_POST_ROUTES.keys())


class Handler(BaseHTTPRequestHandler):
    server_version = f"DaemonSlayer/{ENGINE_VERSION}"

    # Quiet the default access-log spam — we surface our own.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _log.debug("%s - %s", self.address_string(), format % args)

    # ----- helpers

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error(self, status: int, message: str, detail: Any = None) -> None:
        payload: dict[str, Any] = {"error": message, "status": status}
        if detail is not None:
            payload["detail"] = detail
        self._send_json(status, payload)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise _ApiError(400, f"invalid JSON body: {e}")
        if not isinstance(data, dict):
            raise _ApiError(400, "JSON body must be an object")
        return data

    def _query_to_body(self, query: str) -> dict:
        if not query:
            return {}
        parsed = parse_qs(query, keep_blank_values=False)
        # Collapse single-value lists; keep multi-value as comma-separated for
        # caller convenience (matches the JSON-list form via _coerce_str_list).
        out: dict[str, Any] = {}
        for key, values in parsed.items():
            if len(values) == 1:
                out[key] = values[0]
            else:
                out[key] = ",".join(values)
        return out

    # ----- entry points

    def _index_payload(self) -> str:
        try:
            snap = _CACHE.get()
            patch = snap.patch
            n_champ = len(snap.champions)
            n_items = len(snap.items)
        except RuntimeError:
            patch = "loading"
            n_champ = 0
            n_items = 0
        return _INDEX_HTML.format(
            version=ENGINE_VERSION, patch=patch,
            n_champ=n_champ, n_items=n_items,
            port=self.server.server_address[1],
        )

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path in ("", "/"):
                self._send_html(200, self._index_payload())
                return
            if path == "/health":
                self._send_json(200, _route_health())
                return
            if path == "/snapshot":
                self._send_json(200, _route_snapshot())
                return
            if path in _GET_DISPATCH_ROUTES:
                body = self._query_to_body(url.query)
                payload = _POST_ROUTES[path](body)
                self._send_json(200, payload)
                return
            self._send_error(404, f"no such route: {path}")
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception as e:  # noqa: BLE001
            _log.exception("unhandled error in GET %s", path)
            self._send_error(500, f"internal error: {e}")

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        try:
            if path not in _POST_ROUTES:
                self._send_error(404, f"no such route: {path}")
                return
            body = self._read_json_body()
            # Allow query-string overrides on POST too — handy for testing.
            if url.query:
                merged = self._query_to_body(url.query)
                merged.update(body)
                body = merged
            payload = _POST_ROUTES[path](body)
            self._send_json(200, payload)
        except _ApiError as e:
            self._send_error(e.status, e.message, e.detail)
        except Exception as e:  # noqa: BLE001
            _log.exception("unhandled error in POST %s", path)
            self._send_error(500, f"internal error: {e}")


# ---------------------------------------------------------------- bootstrap


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    snapshot: Optional[DataSnapshot] = None,
    patch: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> ThreadingHTTPServer:
    """Create and return a server bound to ``host:port``. Caller drives the
    serving loop (``server.serve_forever()`` for blocking, or
    ``threading.Thread(target=server.serve_forever)`` for a daemon thread).

    A snapshot can be injected directly (test path) or loaded from disk
    via the ``patch`` / ``data_root`` overrides.
    """
    if snapshot is None:
        snapshot = _load_default_snapshot(patch=patch, data_root=data_root)
    _CACHE.set(snapshot)
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def serve_forever(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                  patch: Optional[str] = None,
                  data_root: Optional[Path] = None) -> int:
    """Blocking entry point used by the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        srv = start_server(host=host, port=port, patch=patch, data_root=data_root)
    except SnapshotNotFound as e:
        _log.error("snapshot not found: %s", e)
        return 2
    snap = _CACHE.get()
    _log.info("Daemon Slayer engine v%s on http://%s:%d  (patch %s, %d champions, %d items)",
              ENGINE_VERSION, host, port, snap.patch,
              len(snap.champions), len(snap.items))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        _log.info("shutting down")
    finally:
        srv.server_close()
    return 0
