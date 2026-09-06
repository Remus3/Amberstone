# arch: LCU WAMP event subscription - push replacement for endpoint polling | section=core | frozen=no
"""LCU WAMP event subscription - push replacement for endpoint polling.

RC has historically polled the LCU on a fixed tick for gameflow phase and
champ-select state. The client already pushes those transitions over its own
WAMP socket, so the poll interval is pure added latency plus wasted requests.
This module subscribes instead.

Two halves, deliberately split:

  ``SubscriptionRegistry``  pure bookkeeping - no socket, no I/O. Every
      dispatch and lifecycle rule is unit-testable (tests/test_lcu_events.py).

  ``LcuEventBus``           the transport. Opens ``wss://`` against the
      lockfile port, subscribes once to ``OnJsonApiEvent``, and feeds the
      registry. Reconnects with backoff.

The registry design follows four rules, each of which exists because the
naive version fails in a specific way (observed in a client-plugin teardown
kept non-repo per the name-scrub rule):

  1. ``subscribe`` returns an unsubscribe CLOSURE. Callers never hold a
     handle they could half-remove.
  2. Upstream acquire/release is REF-COUNTED per URI. The first subscriber
     acquires, the last release lets the bus drop the URI.
  3. Every callback is isolated. One raising observer must not starve its
     siblings on the same URI - otherwise a single bad consumer silently
     kills the whole event stream.
  4. Entries are stamped with a GENERATION. After a socket reconnect the
     generation bumps, so payloads still in flight from the dead socket are
     dropped rather than replayed as if current. ``rearm()`` re-stamps the
     surviving listeners onto the new generation, so a reconnect does not
     make every caller re-subscribe.

Kill switch: ``RC_LCU_EVENTS=0`` disables the bus (``bus_enabled()`` returns
False) and callers fall back to their existing poll path. The registry keeps
working regardless - it has no I/O to disable.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import ssl
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)

# LCU pushes every JSON API change on this one WAMP topic. Subscribing once
# and filtering locally is more robust than per-endpoint topic names, which
# encode the path and change shape between client versions.
WAMP_TOPIC = "OnJsonApiEvent"
_WAMP_SUBSCRIBE = 5
_WAMP_EVENT = 8

DEFAULT_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)

# A connection has to SURVIVE this long before the backoff ladder counts as
# recovered. Resetting the moment the handshake completes means a socket that
# connects and immediately closes - client shutting down, credentials rotated
# mid-session - reconnects at the 1.0s floor forever and never reaches the
# 30.0s cap above, hammering a client that is trying to exit.
STABLE_SESSION_SECONDS = 30.0


def endpoint_topic(uri: str) -> str:
    """Per-endpoint WAMP topic name for ``uri``.

    ``/lol-gameflow/v1/gameflow-phase`` becomes
    ``OnJsonApiEvent_lol-gameflow_v1_gameflow-phase``. Subscribing to these
    instead of the ``OnJsonApiEvent`` firehose cuts the inbound volume to
    only the paths RC cares about, which matters because the firehose carries
    every JSON API change in the client.

    Both forms are supported on purpose: the firehose is resilient when a
    client version renames a path, the per-endpoint form is cheap. Callers
    that know their exact URIs should prefer this.
    """
    return f"{WAMP_TOPIC}_{uri.strip('/').replace('/', '_')}"


def bus_enabled() -> bool:
    """False only when the operator sets RC_LCU_EVENTS=0."""
    return os.environ.get("RC_LCU_EVENTS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class _Entry:
    __slots__ = ("callback", "prefix", "generation")

    def __init__(self, callback: Callable[[Any], None], prefix: bool, generation: int):
        self.callback = callback
        self.prefix = prefix
        self.generation = generation


class SubscriptionRegistry:
    """Ref-counted URI -> callback registry with generation guarding.

    Pure: holds no socket and performs no I/O. ``on_acquire`` / ``on_release``
    are set by the transport so it can learn which URIs still matter.
    """

    def __init__(self) -> None:
        self._entries: dict[str, list[_Entry]] = {}
        self._generation = 0
        self.on_acquire: Callable[[str], None] | None = None
        self.on_release: Callable[[str], None] | None = None

    @property
    def generation(self) -> int:
        return self._generation

    def active_uris(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def subscribe(
        self,
        uri: str,
        callback: Callable[[Any], None],
        prefix: bool = False,
    ) -> Callable[[], None]:
        """Register ``callback`` for ``uri``. Returns an unsubscribe closure.

        ``prefix=True`` also matches child URIs, e.g. subscribing to
        ``/lol-champ-select/v1/session`` will see
        ``/lol-champ-select/v1/session/actions/3``.
        """
        entry = _Entry(callback, prefix, self._generation)
        first = uri not in self._entries
        self._entries.setdefault(uri, []).append(entry)
        if first and self.on_acquire is not None:
            self._safe_hook(self.on_acquire, uri, "on_acquire")

        released = False

        def unsubscribe() -> None:
            # Idempotent: a second call must not fire on_release again.
            nonlocal released
            if released:
                return
            released = True
            entries = self._entries.get(uri)
            if entries is None:
                return
            try:
                entries.remove(entry)
            except ValueError:
                return
            if not entries:
                del self._entries[uri]
                if self.on_release is not None:
                    self._safe_hook(self.on_release, uri, "on_release")

        return unsubscribe

    def dispatch(self, uri: str, payload: Any) -> int:
        """Deliver ``payload`` to every current-generation match. Returns the
        number of callbacks invoked.

        Exceptions raised by a callback are logged and swallowed so one bad
        observer cannot starve the others or kill the socket read loop.
        """
        delivered = 0
        for registered_uri, entries in list(self._entries.items()):
            for entry in list(entries):
                if entry.generation != self._generation:
                    continue
                if not self._matches(registered_uri, uri, entry.prefix):
                    continue
                try:
                    entry.callback(payload)
                    delivered += 1
                except Exception:  # noqa: BLE001 - isolation boundary
                    _log.exception("LCU event observer failed for %s", registered_uri)
        return delivered

    def bump_generation(self) -> None:
        """Invalidate in-flight payloads from a socket that just died."""
        self._generation += 1

    def rearm(self) -> tuple[str, ...]:
        """Re-stamp surviving listeners onto the current generation.

        Called by the transport after a successful reconnect so existing
        callers keep working without re-subscribing. Returns the URIs that
        must be re-acquired upstream.
        """
        for entries in self._entries.values():
            for entry in entries:
                entry.generation = self._generation
        return self.active_uris()

    @staticmethod
    def _matches(registered: str, incoming: str, prefix: bool) -> bool:
        if registered == incoming:
            return True
        if not prefix:
            return False
        return incoming.startswith(registered.rstrip("/") + "/")

    @staticmethod
    def _safe_hook(hook: Callable[[str], None], uri: str, label: str) -> None:
        try:
            hook(uri)
        except Exception:  # noqa: BLE001 - isolation boundary
            _log.exception("LCU event %s hook failed for %s", label, uri)


class LcuEventBus:
    """Transport: one WAMP socket feeding a SubscriptionRegistry.

    Credentials come from the caller (the frozen ``lcu/lcu_client.py`` owns
    lockfile discovery and rotation; this module never re-implements it).
    """

    def __init__(self, host: str, port: int, password: str) -> None:
        self._host = host
        self._port = int(port)
        self._password = password
        self.registry = SubscriptionRegistry()
        self._stop = asyncio.Event()

    def subscribe(
        self,
        uri: str,
        callback: Callable[[Any], None],
        prefix: bool = False,
    ) -> Callable[[], None]:
        return self.registry.subscribe(uri, callback, prefix=prefix)

    def stop(self) -> None:
        self._stop.set()

    def _auth_header(self) -> str:
        raw = f"riot:{self._password}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        # The LCU serves a self-signed cert on loopback; RC's frozen client
        # makes the same choice for the same reason.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def run(self) -> None:
        """Connect, subscribe, dispatch. Reconnects with capped backoff."""
        if not bus_enabled():
            _log.info("LCU event bus disabled via RC_LCU_EVENTS")
            return
        try:
            import websockets
        except ImportError:
            _log.warning("websockets unavailable - LCU event bus inactive")
            return

        attempt = 0
        while not self._stop.is_set():
            connected_at: float | None = None
            try:
                url = f"wss://{self._host}:{self._port}/"
                async with websockets.connect(
                    url,
                    ssl=self._ssl_context(),
                    additional_headers={"Authorization": self._auth_header()},
                    ping_interval=None,
                ) as socket:
                    connected_at = time.monotonic()
                    await socket.send(json.dumps([_WAMP_SUBSCRIBE, WAMP_TOPIC]))
                    self.registry.rearm()
                    _log.info("LCU event bus connected on port %d", self._port)
                    await self._read_loop(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any socket fault reconnects
                _log.info("LCU event bus disconnected (%s: %s)", type(exc).__name__, exc)
            # Socket is gone: anything still in flight belongs to a dead
            # generation and must not reach observers as if it were current.
            self.registry.bump_generation()
            if self._stop.is_set():
                return
            # Only a session that actually LASTED earns a return to the floor.
            # A handshake proves the port answered, not that the connection is
            # usable, so resetting on connect alone pins a flapping socket at
            # 1.0s forever (RM-348).
            if (
                connected_at is not None
                and time.monotonic() - connected_at >= STABLE_SESSION_SECONDS
            ):
                attempt = 0
            delay = DEFAULT_BACKOFF_SECONDS[
                min(attempt, len(DEFAULT_BACKOFF_SECONDS) - 1)
            ]
            attempt += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except (asyncio.TimeoutError, TimeoutError):
                pass

    async def _read_loop(self, socket: Any) -> None:
        """Dispatch frames until the socket ends or ``stop()`` is called.

        The read is RACED against the stop event instead of driven by a plain
        ``async for``. A quiet LCU - the normal state at the client home
        screen - pushes nothing for minutes at a time, and ``ping_interval``
        is None on the connect above, so no keepalive wakes the iterator
        either. A stop check that only runs after a frame arrives therefore
        never runs at all on an idle socket: ``stop()`` would set the flag,
        this task would stay parked in the read, and RC shutdown would hang on
        it while the ``wss://`` socket stayed open (RM-348).
        """
        stop_wait = asyncio.ensure_future(self._stop.wait())
        frames = socket.__aiter__()
        try:
            while not self._stop.is_set():
                read = asyncio.ensure_future(frames.__anext__())
                done, _pending = await asyncio.wait(
                    (read, stop_wait), return_when=asyncio.FIRST_COMPLETED
                )
                if read not in done:
                    # Stop won the race. Cancelling the pending read lets the
                    # caller's ``async with`` close the socket immediately.
                    read.cancel()
                    return
                try:
                    raw = read.result()
                except StopAsyncIteration:
                    return
                if self._stop.is_set():
                    return
                uri, payload = self._parse_event(raw)
                if uri is not None:
                    self.registry.dispatch(uri, payload)
        finally:
            stop_wait.cancel()

    @staticmethod
    def _parse_event(raw: Any) -> tuple[str | None, Any]:
        """WAMP event frame -> (uri, data). Returns (None, None) on anything
        that is not a well-formed OnJsonApiEvent payload."""
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode()
            except UnicodeDecodeError:
                return None, None
        if not isinstance(raw, str) or not raw.strip():
            return None, None
        try:
            frame = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None, None
        if not isinstance(frame, list) or len(frame) < 3:
            return None, None
        if frame[0] != _WAMP_EVENT:
            return None, None
        body = frame[2]
        if not isinstance(body, dict):
            return None, None
        uri = body.get("uri")
        if not isinstance(uri, str):
            return None, None
        return uri, body.get("data")
