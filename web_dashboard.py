"""
web_dashboard.py — Read-only HTTP dashboard for iPad extended display.

Serves a single-page dark-theme dashboard at :8888 designed for an iPad
mirrored to Game-PC via Duet (1180x820 logical, retina). Polls coaching
artifact JSON files at 500ms cadence — same as the tkinter overlays.

Architecture:
- Daemon thread; embedded in RC main process
- Read-only: scrapes data/*.json + ops/runtime/health.json
- No auth (LAN-only)
- Mode-adaptive: routes data based on health.json.mode
"""
import json
import logging
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_log = logging.getLogger("rc.web_dashboard")

# AUDIT (2026-04-22): vision bearer token routed through core.vision_token
# for rotation support (env / config file / legacy default).
try:
    from core.vision_token import get_vision_token as _get_vision_token
    _VISION_TOKEN = _get_vision_token()
except ImportError:
    _VISION_TOKEN = "8e8f131e212b329438218eca27372dde"

_APP_DIR: Path = Path(__file__).parent

# 2026-05-01 (slice 2B): pure-builder helpers + their shared
# read-only sqlite cache live under `dashboard/`. We re-bind them
# to the original underscored names so route handlers and module-
# level callers (`_diagnostics_cached`, `_build_state`) keep working
# without churn.
from dashboard._context import (  # noqa: E402
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    read_json as _read_json,
    ro_conn as _ro_conn,
)
from dashboard.builders import (  # noqa: E402
    SESSION_GAP_S,
    _agg_session,
    _build_diagnostics,
    _group_sessions,
    _home_last_build,
    _home_streaks,
    _home_tonight_pick,
    _home_trends_14d,
    _load_match_rows,
    _ts_to_epoch,
)

# 2026-05-01 (slice 2C): static-asset support helpers + the
# legacy_index/manifest/icon byte loaders moved into dashboard/_static.py.
# Re-bind under the original underscored names for any in-process callers.
from dashboard._static import (  # noqa: E402
    compute_asset_hash as _compute_asset_hash,
    icon_svg_bytes as _icon_svg_bytes,
    inject_asset_hash as _inject_asset_hash,
    legacy_index_html as _legacy_index_html,
    manifest_bytes as _manifest_bytes,
    resolve_safe_icon as _resolve_safe_icon,
)
from dashboard import _dispatch  # noqa: E402

# ── Haiku-backed build preview for champions not in CHAMPION_BUILDS ────
# Cached by (champion, frozenset(enemies), role, mode) for 10 minutes.
_PREVIEW_BUILD_CACHE: dict = {}
_PREVIEW_BUILD_TTL = 600   # seconds


def _champ_select_brief_via_coach(champ: str, enemies: list, allies: list,
                                   role: str, mode: str) -> dict:
    """Ask Haiku for a unified champ-select brief: build path + runes + ally
    notes. One API call per unique context. Returns dict with build, runes,
    ally_notes. Cached aggressively."""
    key = (champ, frozenset(enemies), frozenset(allies), role, mode)
    now = time.time()
    cached = _PREVIEW_BUILD_CACHE.get(key)
    if cached and (now - cached["ts"]) < _PREVIEW_BUILD_TTL:
        return cached["brief"]
    empty = {"build": [], "runes": {}, "ally_notes": ""}
    try:
        key_path = Path(_APP_DIR) / "API-Key-Claude.txt"
        api_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else ""
        if not api_key.startswith("sk-ant-"):
            return empty
        import anthropic as _a
        client = _a.Anthropic(api_key=api_key)
        aram_note = ""
        if mode.upper() in ("ARAM", "KIWI"):
            aram_note = (
                "This is ARAM — no lane phase, single mid lane, can't recall to "
                "base. Prioritize items that complete fast, sustain (BT/Shieldbow "
                "for squishy carries, Spirit Visage for AP bruisers). Skip Teleport. "
                "Prefer one early tank/sustain item over pure damage for mid-game "
                "fights. Item path should reflect the constant-combat pacing."
            )
        prompt = (
            f"You are a League champ-select advisor. Return STRICT JSON only.\n\n"
            f"CHAMPION: {champ}\n"
            f"MODE: {mode}\n"
            f"ROLE: {role or 'default'}\n"
            f"ENEMIES: {', '.join(enemies) if enemies else '(unknown)'}\n"
            f"ALLIES: {', '.join(allies) if allies else '(unknown)'}\n"
            f"{aram_note}\n\n"
            f"Output JSON with this exact shape (no markdown, no commentary):\n"
            f'{{\n'
            f'  "build": ["item1", ..., "item7"],\n'
            f'  "runes": {{\n'
            f'    "keystone": "Keystone name",\n'
            f'    "primary_tree": "Precision|Domination|Sorcery|Resolve|Inspiration",\n'
            f'    "secondary_tree": "same set, different from primary",\n'
            f'    "shards": ["Adaptive|Attack Speed|Ability Haste",\n'
            f'               "Adaptive|Armor|Magic Resist|Move Speed|Health Scaling",\n'
            f'               "Armor|Magic Resist|Health|Tenacity and Slow Resist"]\n'
            f'  }},\n'
            f'  "ally_notes": "ONE sentence: who on my team is the main carry/engage and '
            f'what my priority is in teamfights."\n'
            f'}}\n\n'
            f"Rules:\n"
            f"- 'build' = 7 entries in purchase order (6 legendaries + boots slotted realistically).\n"
            f"- Item names must match League in-game spelling exactly.\n"
            f"- Avoid redundant items (e.g. no Lord Dominik's AND Mortal Reminder).\n"
            f"- Consider enemy threats for item choices (armor/MR/heal/burst).\n"
            f"- For runes, return the keystone + trees + 3 shards the champ actually runs.\n"
            f"- 'ally_notes' = empty string if ALLIES is unknown."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip any stray code fences
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except Exception:
            # Best-effort salvage: find first { ... last }
            a, b = text.find("{"), text.rfind("}")
            if a != -1 and b > a:
                try: data = json.loads(text[a:b+1])
                except Exception: data = {}
            else:
                data = {}
        brief = {
            "build":      data.get("build") or [],
            "runes":      data.get("runes") or {},
            "ally_notes": (data.get("ally_notes") or "")[:300],
        }
        _PREVIEW_BUILD_CACHE[key] = {"ts": now, "brief": brief}
        if len(_PREVIEW_BUILD_CACHE) > 200:
            oldest = sorted(_PREVIEW_BUILD_CACHE.items(), key=lambda x: x[1]["ts"])[:100]
            for k, _ in oldest:
                _PREVIEW_BUILD_CACHE.pop(k, None)
        return brief
    except Exception as exc:
        _log.warning("_champ_select_brief_via_coach(%s): %s", champ, exc)
        return empty

# ── Cross-Claude bridge ─────────────────────────────────────────────────
# Tier 2 helper-shake (2026-05-01): the bridge log moved to
# dashboard/_bridge_log.py. Keep the underscore-prefixed names re-bound
# here so any in-process caller that still does `from web_dashboard
# import _bridge_post` keeps working without churn.
from dashboard._bridge_log import (  # noqa: E402, F401
    BRIDGE_LOG_DISK_MAX as _BRIDGE_LOG_DISK_MAX,
    BRIDGE_LOG_PATH as _BRIDGE_LOG_PATH,
    BRIDGE_ROTATE_INTERVAL as _BRIDGE_ROTATE_INTERVAL,
    bridge_hydrate_from_disk as _bridge_hydrate_from_disk,
    bridge_maybe_rotate as _bridge_maybe_rotate,
    bridge_post as _bridge_post,
    bridge_since as _bridge_since,
)


# Tier 2 helper-shake (2026-05-01): the diagnostics cache moved to
# dashboard/_diagnostics.py. Re-bind under the original underscored
# names so any in-process caller that still does `from web_dashboard
# import _diagnostics_cached` keeps working without churn.
from dashboard._diagnostics import (  # noqa: E402, F401
    _DIAG_CACHE,
    _DIAG_LOCK,
    _DIAG_TTL_S,
    diagnostics_cached as _diagnostics_cached,
)

# Tier 2 helper-shake (2026-05-01): the atomic JSON writers moved to
# dashboard/_writers.py. Re-bind under the original underscored names
# so any in-process caller that still does `from web_dashboard import
# _set_pregame` keeps working without churn.
from dashboard._writers import (  # noqa: E402, F401
    atomic_write_json as _atomic_write_json,
    force_vision_scan as _force_vision_scan,
    set_pregame as _set_pregame,
)

# Tier 2 helper-shake (2026-05-01): the LCU + Live Client summary
# helpers moved to dashboard/_liveclient.py. Re-bind under the original
# underscored names so in-process callers that still do
# `from web_dashboard import _liveclient_summary` keep working.
from dashboard._liveclient import (  # noqa: E402, F401
    lcu_summary as _lcu_summary,
    liveclient_summary as _liveclient_summary,
)

# Tier 2 helper-shake (2026-05-01): the state-shape builder + sim-scenario
# loader + MODE_TO_FILE moved to dashboard/_state_builder.py. Re-bind under
# the original underscored names so any in-process caller that still does
# `from web_dashboard import _build_state` keeps working without churn.
from dashboard._state_builder import (  # noqa: E402, F401
    MODE_TO_FILE as _MODE_TO_FILE,
    build_state as _build_state,
    sim_states as _sim_states,
)


# Paths that only the agents supervisor (:8890) implements. :8888 proxies
# GETs for these so the new dashboard, when accessed via :8888, gets full
# side-panel data without having to know about port 8890.
_SUPERVISOR_PROXY_PATHS = (
    "/api/activity",
    "/api/adaptation",
    "/api/advisories",
    "/api/day-of-week",
    "/api/digest",
    "/api/duration",
    "/api/env",
    "/api/insight-card",
    "/api/locked-champion",
    "/api/minimap-crop",
    "/api/queue",
    "/api/session",
    "/api/session-games",
    "/api/sim",           # matches /api/sim, /api/sim/<name>, /api/sim/_manifest
    "/api/task",          # /api/task/<id>
    "/api/time-of-day",
    "/api/trending",
)
_SUPERVISOR_ORIGIN = "http://127.0.0.1:8890"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        _log.debug("HTTP " + fmt, *a)

    def _proxy_to_supervisor(self):
        """Forward the current GET to 127.0.0.1:8890 and stream the
        response back. Body is read in full first so we can set a proper
        Content-Length; requests here return <100KB (minimap PNG is the
        biggest) so memory cost is negligible."""
        import urllib.request as _ur
        import urllib.error as _ue
        url = _SUPERVISOR_ORIGIN + self.path
        try:
            req = _ur.Request(url, method=self.command)
            # Pass through conditional headers the dashboard might send.
            for h in ("If-None-Match", "If-Modified-Since", "Accept"):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)
            with _ur.urlopen(req, timeout=4) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/octet-stream")
                self._send(r.status, body, ctype)
        except _ue.HTTPError as e:
            # Forward the non-2xx response — 404 from supervisor should
            # still look like 404 to the dashboard, not 500 here.
            try:
                body = e.read() or b""
            except Exception:
                body = b""
            ctype = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self._send(e.code, body, ctype)
        except Exception as exc:
            _log.debug("proxy %s: %s", self.path, exc)
            self._send(502, b'{"error":"supervisor_unreachable"}', "application/json")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # AUDIT 2026-04-29: Strict-Transport-Security so any browser that
        # touches the dashboard once over HTTPS never falls back to plain
        # HTTP for this origin again — eliminates the original Game-PC
        # "http://… not connecting" symptom permanently. 1-year max-age is
        # standard. We don't include preload / includeSubDomains because
        # this is LAN-only and we don't own the rest of the IP space.
        # Only set when the connection itself is TLS — when wrap_socket
        # is in play, the underlying request socket has an .cipher() attr.
        try:
            sock = self.connection
            if hasattr(sock, "cipher") and callable(sock.cipher):
                self.send_header("Strict-Transport-Security", "max-age=31536000")
        except Exception:
            pass
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass

    def do_GET(self):
        # Slice 2C (2026-05-01): all GET routes live in dashboard/routes_*.
        # Anything that doesn't match a registered route either falls
        # through to the agents-supervisor proxy (:8890) for routes that
        # only exist there, or returns 404.
        if _dispatch.dispatch_get(self):
            return
        if any(self.path == p or self.path.startswith(p + "?") or self.path.startswith(p + "/")
               for p in _SUPERVISOR_PROXY_PATHS):
            # 2026-04-23: forward routes that only exist on the agents
            # supervisor (:8890) through :8888 so the new dashboard's
            # side panels (adaptation, activity, env, minimap-crop,
            # locked-champion, etc.) populate when accessed via 8888.
            self._proxy_to_supervisor()
        else:
            self._send(404, b"not found", "text/plain")

    def _csrf_ok(self) -> bool:
        """AUDIT 2026-04-28 (deferred-low-value): same-origin guard for
        POST endpoints. RC is LAN-only so cross-site CSRF is mitigated by
        threat model, but a misbehaving / compromised tab on Legion could
        still cross-origin-POST into 8888. Browsers send Origin (and
        Referer) on cross-origin POSTs; non-browser clients (curl, our
        own scripts) typically send neither and are allowed.

        Rule: if Origin or Referer is present, its hostname must match
        the request's Host header — OR the origin must itself be a local
        loopback address (127.0.0.1 / localhost) coming from a script on
        the same machine. Absent both headers → allow (script caller).
        """
        try:
            origin  = self.headers.get("Origin", "") or ""
            referer = self.headers.get("Referer", "") or ""
            if not origin and not referer:
                return True
            host = (self.headers.get("Host", "") or "").strip().lower()
            if not host:
                return False
            host_h, _, _ = host.partition(":")
            from urllib.parse import urlparse
            local_aliases = {"127.0.0.1", "localhost", "::1"}
            for src in (origin, referer):
                if not src:
                    continue
                # "null" Origin is what some sandboxed iframes / file://
                # contexts send. Treat as cross-origin.
                if src == "null":
                    return False
                p = urlparse(src)
                src_hp = (p.hostname or "").lower()
                if not src_hp:
                    return False
                # Same hostname is fine (port may differ — e.g. dashboard
                # opened via localhost vs LAN IP from same machine).
                if src_hp == host_h:
                    continue
                # Origin from local loopback when request host is the LAN
                # bind is also fine — script callers, dev probes.
                if src_hp in local_aliases and host_h not in local_aliases:
                    continue
                if host_h in local_aliases and src_hp in local_aliases:
                    continue
                # Anything else: reject.
                return False
            return True
        except Exception:
            # Don't block POSTs on parse errors — fail open with a log.
            _log.debug("csrf_ok parse failed; allowing")
            return True

    def do_POST(self):
        # 2026-04-27 audit: cap POST body at 1 MiB. RC is LAN-only and the
        # legitimate inputs (chat text, /api/bridge messages) are tiny —
        # an unbounded read on Content-Length: 999999999 would let a LAN
        # attacker (or a misbehaving tab) allocate a multi-GB buffer per
        # request. Also: don't echo the exception message back to the
        # client, since urllib/json error strings can leak file paths or
        # unrelated headers.
        # AUDIT 2026-04-28 (deferred-low-value): same-origin CSRF guard.
        # Browser-driven cross-origin POSTs (Origin/Referer mismatch) are
        # rejected with 403; script callers without those headers pass.
        if not self._csrf_ok():
            _log.warning("do_POST CSRF reject path=%s origin=%r referer=%r host=%r",
                         self.path,
                         self.headers.get("Origin"),
                         self.headers.get("Referer"),
                         self.headers.get("Host"))
            self._send(403, b'{"error":"cross_origin"}', "application/json")
            return
        _MAX_POST_BYTES = 1 << 20
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > _MAX_POST_BYTES:
                self._send(413, b'{"error":"payload_too_large"}', "application/json")
                return
            body = self.rfile.read(n) if n else b""
            payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except Exception as exc:
            _log.debug("do_POST bad_body: %s", exc)
            self._send(400, b'{"error":"bad_body"}', "application/json")
            return

        # Slice 2C-7d (2026-05-01): every POST route lives in
        # dashboard/routes_*. Dispatcher handled or it's a 404.
        if _dispatch.dispatch_post(self, payload):
            return
        self._send(404, b"not found", "text/plain")


# Slice 2D (2026-05-01): _DualProtocolHTTPServer + start_dashboard live
# in dashboard/server.py. Re-export here so `from web_dashboard import
# start_dashboard` (main.py) keeps working without churn.
from dashboard.server import (  # noqa: E402, F401
    _DualProtocolHTTPServer,
    start_dashboard,
)
