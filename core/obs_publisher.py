"""
core/obs_publisher.py - push RC state to OBS Studio as a text-source update.

Tier 3 #11 (2026-05-01). Turns RC into a streaming overlay for free:
the same data the dashboard renders gets formatted into a one-line
summary and pushed to a Text source in OBS via OBS-WebSocket v5
(built into OBS 28+).

Disabled by default. To enable, add to `config/coach_settings.json`:

    "obs": {
        "enabled":     true,
        "host":        "127.0.0.1",
        "port":        4455,
        "password":    "",
        "source_name": "RC State",
        "interval_s":  2.0
    }

Then create a Text (GDI+) source in OBS named "RC State" (or whatever
you set source_name to). The publisher updates that source's text every
`interval_s` seconds.

Resilience:
* If the `obs` block is absent or `enabled` is false, `start_background()`
  is a no-op - RC behavior unchanged.
* If OBS isn't running when the daemon starts, the publisher backs off
  10s and retries. Same for connection drops.
* If the auth handshake fails (wrong password, mismatched protocol),
  it logs once and waits 15s before retrying.
* All exceptions in the loop body are caught - the daemon never
  crashes RC.

Architecture matches `core/vision_tracker.py` and `core/decision_detector.py`:
singleton via `get_publisher()`, `start_background()` spawns a daemon
thread, the thread runs `asyncio.run(_async_loop())` so we can use the
`websockets` library cleanly.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import threading
import time
from pathlib import Path

import websockets

_log = logging.getLogger("rc.obs_publisher")
_APP_DIR = Path(__file__).resolve().parent.parent

_BACKOFF_AFTER_DROP_S = 10
_BACKOFF_AFTER_AUTH_FAIL_S = 15


def _load_obs_config() -> dict:
    """Read the `obs` block from config/coach_settings.json. Returns {} if
    absent, malformed, or unreadable."""
    try:
        cfg_path = _APP_DIR / "config" / "coach_settings.json"
        if not cfg_path.exists():
            return {}
        full = json.loads(cfg_path.read_text(encoding="utf-8"))
        return (full.get("obs") or {}) if isinstance(full, dict) else {}
    except Exception as exc:
        _log.warning("OBS config read failed: %s", exc)
        return {}


def _render_state() -> str:
    """One-line summary of current RC state, suitable for an OBS text
    source. Pulled directly from `dashboard._state_builder.build_state()`
    so the formatter sees the same merged liveclient + coach + health
    payload the dashboard does.

    Returns empty string on any failure - caller treats that as "skip
    this tick" and OBS keeps the previous text on screen.
    """
    try:
        from dashboard._state_builder import build_state
        s = build_state()
        mode = (s.get("mode_key") or "client").upper()
        coach = s.get("coach") or {}
        lc = s.get("liveclient") or {}

        # In-game shape: champion + KDA + level + game_time
        if lc:
            champ = lc.get("champion") or coach.get("champion") or "?"
            kda   = lc.get("kda") or "0/0/0"
            level = lc.get("level")
            gt    = lc.get("game_time") or "?"
            level_part = f" · lv{level}" if level else ""
            return f"{mode} · {champ} {kda}{level_part} · {gt}"

        # Lobby / champ-select / out-of-game: mode + the most relevant pregame field.
        # `coach.pregame` is a free-form string the dashboard's chat input
        # pushes through; if present it's usually the user's recent note.
        # Collapse whitespace (newlines, double spaces) so the OBS text
        # source stays single-line regardless of how the user typed.
        pregame = " ".join((coach.get("pregame") or "").split())
        if pregame:
            # cap to ~50 chars so OBS doesn't get a wall of text
            short = pregame[:50] + ("..." if len(pregame) > 50 else "")
            return f"{mode} · {short}"
        return mode
    except Exception as exc:
        _log.debug("OBS render: %s", exc)
        return ""


class OBSPublisher:
    """Singleton-ish daemon that maintains an OBS-WebSocket connection
    and periodically updates a Text source with the rendered RC state."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._task = None  # asyncio.Task / Future when running on the AppLoop
        self._stop = threading.Event()
        # last-pushed text so we don't spam SetInputSettings when the
        # state hasn't changed (cheap to compute, saves OBS-side work)
        self._last_pushed: str = ""

    def start_background(self) -> None:
        """Launch the publisher if `obs.enabled` is true in config.
        Prefers spawning `_async_loop` directly on the main AppLoop (the
        websockets lib is already async); falls back to a daemon thread
        running `asyncio.run(_async_loop)` when no loop exists.
        No-op when disabled or already running."""
        cfg = _load_obs_config()
        if not cfg.get("enabled"):
            _log.debug("OBS publisher disabled (config.obs.enabled=%r)",
                       cfg.get("enabled"))
            return
        if (self._thread and self._thread.is_alive()) or self._task is not None:
            return
        self._stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._async_loop(cfg))
            _log.info("OBS publisher started (host=%s port=%s source=%r interval=%ss, async)",
                      cfg.get("host", "127.0.0.1"), cfg.get("port", 4455),
                      cfg.get("source_name", "RC State"),
                      cfg.get("interval_s", 2.0))
        else:
            self._thread = threading.Thread(
                target=self._run, args=(cfg,),
                name="obs-publisher", daemon=True,
            )
            self._thread.start()
            _log.info("OBS publisher started (host=%s port=%s source=%r interval=%ss, thread)",
                      cfg.get("host", "127.0.0.1"), cfg.get("port", 4455),
                      cfg.get("source_name", "RC State"),
                      cfg.get("interval_s", 2.0))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None

    def _run(self, cfg: dict) -> None:
        """Thread entrypoint (fallback path). Owns its own asyncio loop so
        we can use the `websockets` lib when not riding the main AppLoop."""
        try:
            asyncio.run(self._async_loop(cfg))
        except Exception:
            _log.exception("OBS publisher loop crashed")

    async def _async_loop(self, cfg: dict) -> None:
        host        = cfg.get("host", "127.0.0.1")
        port        = int(cfg.get("port", 4455))
        password    = cfg.get("password", "") or ""
        source_name = cfg.get("source_name", "RC State")
        interval_s  = float(cfg.get("interval_s", 2.0))
        url = f"ws://{host}:{port}"

        while not self._stop.is_set():
            try:
                async with websockets.connect(url, open_timeout=4) as ws:
                    if not await self._identify(ws, password):
                        _log.warning("OBS auth failed; will retry in %ds",
                                     _BACKOFF_AFTER_AUTH_FAIL_S)
                        await asyncio.sleep(_BACKOFF_AFTER_AUTH_FAIL_S)
                        continue
                    _log.info("OBS publisher connected; updating %r every %.1fs",
                              source_name, interval_s)
                    self._last_pushed = ""  # force first push after reconnect
                    while not self._stop.is_set():
                        text = _render_state()
                        if text and text != self._last_pushed:
                            await self._set_text(ws, source_name, text)
                            self._last_pushed = text
                        # OBS replies (op=7) to every request even though we
                        # never await them; drain so the recv queue cannot
                        # fill up and stall the connection (see
                        # _drain_pending).
                        await self._drain_pending(ws)
                        await asyncio.sleep(interval_s)
            except (OSError, asyncio.TimeoutError):
                # OBS not running, wrong port, or handshake timed out.
                _log.debug("OBS connect failed for %s; backoff %ds",
                           url, _BACKOFF_AFTER_DROP_S)
            except websockets.exceptions.ConnectionClosed:
                # Mid-session disconnect - common on OBS restart.
                _log.debug("OBS connection closed; reconnecting in %ds",
                           _BACKOFF_AFTER_DROP_S)
            except Exception as exc:
                _log.warning("OBS publisher unexpected error: %s", exc)
            if not self._stop.is_set():
                await asyncio.sleep(_BACKOFF_AFTER_DROP_S)

    async def _identify(self, ws, password: str) -> bool:
        """OBS-WebSocket v5 handshake: server sends Hello (op=0); client
        responds with Identify (op=1) including auth response if a
        password is required; server confirms with Identified (op=2).

        Auth scheme (per OBS-WS v5 spec):
            secret   = base64(sha256(password + salt))
            response = base64(sha256(secret + challenge))
        """
        hello_raw = await ws.recv()
        try:
            hello = json.loads(hello_raw)
        except Exception:
            return False
        if hello.get("op") != 0:
            return False
        d = hello.get("d") or {}
        # eventSubscriptions=0: the publisher only pushes SetInputSettings
        # and never consumes events. The OBS-WS default (omitted field) is
        # subscribe-to-ALL, which floods the never-read recv queue.
        identify = {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 0}}
        auth = d.get("authentication")
        if auth:
            if not password:
                _log.warning("OBS requires a password but none configured")
                return False
            salt = auth.get("salt", "")
            challenge = auth.get("challenge", "")
            secret = base64.b64encode(
                hashlib.sha256((password + salt).encode("utf-8")).digest()
            ).decode("ascii")
            response = base64.b64encode(
                hashlib.sha256((secret + challenge).encode("utf-8")).digest()
            ).decode("ascii")
            identify["d"]["authentication"] = response
        await ws.send(json.dumps(identify))
        idd_raw = await ws.recv()
        try:
            idd = json.loads(idd_raw)
        except Exception:
            return False
        return idd.get("op") == 2

    async def _drain_pending(self, ws) -> None:
        """Discard buffered incoming messages (request responses, stray
        events). `_set_text` is fire-and-forget, but OBS still answers
        every request with an op=7 RequestResponse; unread messages pile
        up in the websockets recv queue until backpressure pauses the
        transport and the keepalive ping times the connection out
        (connection flap every ~minute of steady pushes). Draining once
        per tick keeps the queue empty. Never raises - a dead connection
        surfaces on the next send/recv in the caller."""
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=0.05)
        except (asyncio.TimeoutError, TimeoutError):
            return
        except Exception:
            return

    async def _set_text(self, ws, source_name: str, text: str) -> None:
        """Fire a SetInputSettings request to update the Text source's
        `text` field. Fire-and-forget - we don't await the response, so
        a slow OBS reply doesn't stall the publisher loop."""
        request = {
            "op": 6,
            "d": {
                "requestType": "SetInputSettings",
                "requestId":   f"rc-{time.time():.6f}",
                "requestData": {
                    "inputName":     source_name,
                    "inputSettings": {"text": text},
                    "overlay":       True,
                },
            },
        }
        await ws.send(json.dumps(request))


_publisher: OBSPublisher | None = None


def get_publisher() -> OBSPublisher:
    """Return the process-wide OBSPublisher singleton."""
    global _publisher
    if _publisher is None:
        _publisher = OBSPublisher()
    return _publisher
