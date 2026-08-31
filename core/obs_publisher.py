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
        "interval_s":  2.0,

        "frame_source":      false,
        "frame_source_name": "Game Capture",
        "frame_timeout_s":   1.5,
        "frame_width":       0,
        "frame_max_age_s":   3.0
    }

The `frame_*` keys are the OBS occlusion-proof frame provider (ZOI plan
spec O, 2026-07-05): when `frame_source` is true the publisher loop also
keeps a GetSourceScreenshot frame warm each tick (see
`grab_source_screenshot` + the keep-warm slot below), and the sync facade
`core.obs_frame_source.get_obs_frame` serves it to the vision pipeline.
DEFAULT OFF - with `frame_source` false (or absent) every existing
behavior of this module is unchanged.

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
import uuid
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
    except Exception as exc:  # noqa: BLE001
        _log.warning("OBS config read failed: %s", exc)
        return {}


# -- request/response lane + keep-warm frame slot (spec O, 2026-07-05) -------
# The original client is fire-and-forget only (_set_text never awaits its
# op=7 reply; _drain_pending discards everything). Frame grabbing needs a
# real request/response pair: send an op:6 Request with a unique requestId,
# await the matching op:7 RequestResponse. Non-matching messages read while
# waiting are discarded - exactly what _drain_pending would have done.
# Everything here is fail-soft (returns None, never raises) and is only
# exercised when config `obs.frame_source` is true.

_REQUEST_TIMEOUT_S = 2.0

# Bound on each frame of the op:0/op:1/op:2 handshake. `websockets.connect`
# takes an `open_timeout`, but that bounds only the OPENING handshake; a peer
# that completes it and then goes silent (while still answering keepalive
# pings) left `_identify` awaiting `ws.recv()` forever. `_stop` is read only
# at the top of the publisher loops, so `stop()` could not reclaim that
# thread either. Every other recv in this module is already bounded.
_HANDSHAKE_TIMEOUT_S = 5.0

_frame_slot_lock = threading.Lock()
_frame_slot: dict = {"data": None, "mono": 0.0}


def store_frame(data) -> None:
    """Write raw image bytes into the keep-warm slot (monotonic-stamped).
    Fail-soft no-op on empty/bad input."""
    if not data:
        return
    try:
        with _frame_slot_lock:
            _frame_slot["data"] = bytes(data)
            _frame_slot["mono"] = time.monotonic()
    except Exception:  # noqa: BLE001
        pass


def peek_frame(max_age_s: float = 3.0) -> "bytes | None":
    """Latest keep-warm frame bytes if fresher than `max_age_s`, else None.
    The sync facade (core.obs_frame_source) reads this so callers never pay
    a round-trip while the publisher loop is keeping the slot warm."""
    try:
        with _frame_slot_lock:
            data = _frame_slot["data"]
            age = time.monotonic() - float(_frame_slot["mono"] or 0.0)
        if data and age <= float(max_age_s):
            return data
        return None
    except Exception:  # noqa: BLE001
        return None


def _reset_frame_slot() -> None:
    """Test helper: clear the keep-warm slot."""
    with _frame_slot_lock:
        _frame_slot.update(data=None, mono=0.0)


async def request_response(ws, request_type, request_data=None,
                           timeout_s: float = _REQUEST_TIMEOUT_S):
    """Send an op:6 Request and await the op:7 RequestResponse whose
    requestId matches. Returns the op:7 `d` payload dict, or None on
    timeout / connection error / any failure. Never raises."""
    rid = "rc-req-" + uuid.uuid4().hex
    payload: dict = {"op": 6, "d": {"requestType": str(request_type),
                                    "requestId": rid}}
    if request_data is not None:
        payload["d"]["requestData"] = request_data
    try:
        await ws.send(json.dumps(payload))
        deadline = time.monotonic() + max(0.05, float(timeout_s))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(msg, dict) or msg.get("op") != 7:
                continue
            d = msg.get("d") or {}
            if d.get("requestId") == rid:
                return d
    except (asyncio.TimeoutError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001
        return None


def _decode_image_data(image_data) -> "bytes | None":
    """Decode a GetSourceScreenshot imageData payload (a base64 data URI,
    e.g. "data:image/jpg;base64,<b64>") to raw image bytes, or None."""
    try:
        if not isinstance(image_data, str) or not image_data:
            return None
        b64 = image_data.split("base64,", 1)[-1]
        raw = base64.b64decode(b64)
        return raw or None
    except Exception:  # noqa: BLE001
        return None


async def grab_source_screenshot(ws, source_name, image_width: int = 0,
                                 timeout_s: float = _REQUEST_TIMEOUT_S):
    """GetSourceScreenshot over an already-identified OBS-WS connection.
    Returns raw JPEG bytes (decoded from the base64 payload) or None; a
    successful grab also warms the keep-warm slot. `image_width` <= 0 asks
    OBS for the source's native resolution. Never raises."""
    data: dict = {"sourceName": str(source_name), "imageFormat": "jpg"}
    try:
        w = int(image_width or 0)
    except (TypeError, ValueError):
        w = 0
    if w >= 8:  # OBS-WS v5 rejects widths below 8
        data["imageWidth"] = w
    d = await request_response(ws, "GetSourceScreenshot", data,
                               timeout_s=timeout_s)
    if not isinstance(d, dict):
        return None
    status = d.get("requestStatus") or {}
    if status.get("result") is False:
        return None
    raw = _decode_image_data((d.get("responseData") or {}).get("imageData"))
    if raw:
        store_frame(raw)
    return raw


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
            level_part = f" - lv{level}" if level else ""
            return f"{mode} - {champ} {kda}{level_part} - {gt}"

        # Lobby / champ-select / out-of-game: mode + the most relevant pregame field.
        # `coach.pregame` is a free-form string the dashboard's chat input
        # pushes through; if present it's usually the user's recent note.
        # Collapse whitespace (newlines, double spaces) so the OBS text
        # source stays single-line regardless of how the user typed.
        pregame = " ".join((coach.get("pregame") or "").split())
        if pregame:
            # cap to ~50 chars so OBS doesn't get a wall of text
            short = pregame[:50] + ("..." if len(pregame) > 50 else "")
            return f"{mode} - {short}"
        return mode
    except Exception as exc:  # noqa: BLE001
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
        if ((self._thread and self._thread.is_alive())
                or self._handle_running(self._task)):
            return
        self._stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:  # noqa: BLE001
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

    @staticmethod
    def _handle_running(handle) -> bool:
        """True unless `handle` is PROVABLY finished.

        An unrecognised handle counts as RUNNING, so an unknown scheduler
        can never license a double spawn. This is the cycle-9
        `core/log_retention.py` rule (LEDGER 1200 weakness 4/5) applied to
        the asyncio path.
        """
        if handle is None:
            return False
        done = getattr(handle, "done", None)
        if callable(done):
            try:
                return not bool(done())
            except Exception:  # noqa: BLE001
                return True
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if not self._thread.is_alive():
                self._thread = None
        task = self._task
        if task is not None:
            cancel = getattr(task, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:  # noqa: BLE001
                    pass
            # `cancel()` is a REQUEST, not a stop: the loop only unwinds
            # when it next reaches an await. Dropping the handle here let
            # the next start_background() pass its idempotence check AND
            # call `_stop.clear()`, resurrecting this loop and running two
            # publishers against one OBS connection and one frame slot.
            if not self._handle_running(task):
                self._task = None

    def _run(self, cfg: dict) -> None:
        """Thread entrypoint (fallback path). Owns its own asyncio loop so
        we can use the `websockets` lib when not riding the main AppLoop."""
        try:
            asyncio.run(self._async_loop(cfg))
        except Exception:  # noqa: BLE001
            _log.exception("OBS publisher loop crashed")

    async def _async_loop(self, cfg: dict) -> None:
        host        = cfg.get("host", "127.0.0.1")
        port        = int(cfg.get("port", 4455))
        password    = cfg.get("password", "") or ""
        source_name = cfg.get("source_name", "RC State")
        interval_s  = float(cfg.get("interval_s", 2.0))
        url = f"ws://{host}:{port}"
        # Keep-warm frame lane (spec O) - DEFAULT OFF. When obs.frame_source
        # is false/absent the loop below is byte-identical to the original.
        frame_source_on = bool(cfg.get("frame_source"))
        frame_source_name = str(cfg.get("frame_source_name") or "Game Capture")
        try:
            frame_width = int(cfg.get("frame_width", 0) or 0)
        except (TypeError, ValueError):
            frame_width = 0
        try:
            frame_timeout_s = float(cfg.get("frame_timeout_s", 1.5))
        except (TypeError, ValueError):
            frame_timeout_s = 1.5

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
                        if frame_source_on:
                            # Keep the frame slot warm AFTER the drain so the
                            # drain cannot eat our op:7; request_response
                            # discards any stray replies it reads itself.
                            try:
                                await grab_source_screenshot(
                                    ws, frame_source_name,
                                    image_width=frame_width,
                                    timeout_s=frame_timeout_s)
                            except Exception:  # noqa: BLE001
                                pass
                        await asyncio.sleep(interval_s)
            except (OSError, asyncio.TimeoutError):
                # OBS not running, wrong port, or handshake timed out.
                _log.debug("OBS connect failed for %s; backoff %ds",
                           url, _BACKOFF_AFTER_DROP_S)
            except websockets.exceptions.ConnectionClosed:
                # Mid-session disconnect - common on OBS restart.
                _log.debug("OBS connection closed; reconnecting in %ds",
                           _BACKOFF_AFTER_DROP_S)
            except Exception as exc:  # noqa: BLE001
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
        hello = await self._recv_object(ws)
        if hello is None or hello.get("op") != 0:
            return False
        d = hello.get("d")
        if not isinstance(d, dict):
            d = {}
        # eventSubscriptions=0: the publisher only pushes SetInputSettings
        # and never consumes events. The OBS-WS default (omitted field) is
        # subscribe-to-ALL, which floods the never-read recv queue.
        identify = {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 0}}
        auth = d.get("authentication")
        if auth:
            if not isinstance(auth, dict):
                _log.warning("OBS sent a malformed authentication block (%s)",
                             type(auth).__name__)
                return False
            if not password:
                _log.warning("OBS requires a password but none configured")
                return False
            salt = auth.get("salt", "")
            challenge = auth.get("challenge", "")
            if not isinstance(salt, str) or not isinstance(challenge, str):
                # Concatenating a non-str here raises TypeError inside the
                # handshake, which the caller can only report as a generic
                # "unexpected error" and then retry forever.
                _log.warning("OBS sent a non-string salt/challenge")
                return False
            secret = base64.b64encode(
                hashlib.sha256((password + salt).encode("utf-8")).digest()
            ).decode("ascii")
            response = base64.b64encode(
                hashlib.sha256((secret + challenge).encode("utf-8")).digest()
            ).decode("ascii")
            identify["d"]["authentication"] = response
        await ws.send(json.dumps(identify))
        idd = await self._recv_object(ws)
        return idd is not None and idd.get("op") == 2

    async def _recv_object(self, ws, timeout_s: "float | None" = None):
        """Await one frame; return it only if it is a JSON OBJECT, else None.

        Three refusals in one place, all previously missing:
          * TIMEOUT - see `_HANDSHAKE_TIMEOUT_S`.
          * malformed JSON - was already handled.
          * valid JSON that is not an object. `json.loads("[1,2]")` and
            `json.loads("null")` both succeed, and the `.get()` that
            followed raised AttributeError OUTSIDE the local try, so it
            escaped to the publisher loop's generic handler and was logged
            as an "unexpected error" before reconnecting forever. The
            sibling `request_response` already carried this isinstance
            check; the handshake did not.
        """
        limit = _HANDSHAKE_TIMEOUT_S if timeout_s is None else timeout_s
        try:
            raw = await asyncio.wait_for(ws.recv(),
                                         timeout=max(0.01, float(limit)))
        except (asyncio.TimeoutError, TimeoutError):
            _log.debug("OBS handshake frame timed out after %.2fs", limit)
            return None
        except Exception:  # noqa: BLE001
            return None
        try:
            msg = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        return msg if isinstance(msg, dict) else None

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
        except Exception:  # noqa: BLE001
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
