"""Guards for core/lcu_events.py - the LCU WAMP event subscription registry.

The registry half is pure (no socket), so every dispatch/lifecycle rule is
unit-testable without a live client. The transport half is exercised too, as
of RM-348, against a fake ``websockets`` module rather than a live LCU - see
``TestTransportLifecycle`` at the bottom of this file.

Design rules under test, each one a real failure mode observed in a
client-plugin teardown (non-repo) that RC's polling path does not have:
  - unsubscribe is a closure, so a caller cannot leak a half-removed handle
  - the last unsubscribe for a URI releases the upstream subscription
  - one raising callback must not starve its siblings on the same URI
  - callbacks registered before a reconnect must not fire afterwards
"""

import asyncio
import sys
import types

import pytest

from core import lcu_events
from tests._asyncio_isolation import run_coro


@pytest.fixture()
def registry():
    return lcu_events.SubscriptionRegistry()


def test_subscribe_returns_unsubscribe_closure(registry):
    calls = []
    unsub = registry.subscribe("/lol-gameflow/v1/gameflow-phase", calls.append)
    assert callable(unsub)
    assert registry.active_uris() == ("/lol-gameflow/v1/gameflow-phase",)
    unsub()
    assert registry.active_uris() == ()


def test_dispatch_delivers_payload_to_every_callback(registry):
    seen_a, seen_b = [], []
    registry.subscribe("/lol-gameflow/v1/gameflow-phase", seen_a.append)
    registry.subscribe("/lol-gameflow/v1/gameflow-phase", seen_b.append)
    registry.dispatch("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    assert seen_a == ["ChampSelect"]
    assert seen_b == ["ChampSelect"]


def test_unsubscribe_removes_only_that_callback(registry):
    seen_a, seen_b = [], []
    unsub_a = registry.subscribe("/x", seen_a.append)
    registry.subscribe("/x", seen_b.append)
    unsub_a()
    registry.dispatch("/x", 1)
    assert seen_a == []
    assert seen_b == [1]
    assert registry.active_uris() == ("/x",)


def test_last_unsubscribe_releases_the_uri(registry):
    released = []
    registry.on_release = released.append
    unsub = registry.subscribe("/x", lambda _: None)
    unsub()
    assert released == ["/x"]
    assert registry.active_uris() == ()


def test_first_subscribe_acquires_once_per_uri(registry):
    acquired = []
    registry.on_acquire = acquired.append
    registry.subscribe("/x", lambda _: None)
    registry.subscribe("/x", lambda _: None)
    assert acquired == ["/x"], "second subscriber must not re-acquire upstream"


def test_raising_callback_does_not_starve_siblings(registry):
    seen = []

    def boom(_payload):
        raise RuntimeError("observer blew up")

    registry.subscribe("/x", boom)
    registry.subscribe("/x", seen.append)
    registry.dispatch("/x", "payload")
    assert seen == ["payload"], "a raising observer must not kill the stream"


def test_callbacks_from_a_previous_generation_are_dropped(registry):
    seen = []
    registry.subscribe("/x", seen.append)
    registry.bump_generation()  # simulates a socket reconnect
    registry.dispatch("/x", "after-reconnect")
    assert seen == [], "stale pre-reconnect observers must not fire"


def test_dispatch_to_unknown_uri_is_a_noop(registry):
    registry.dispatch("/never-subscribed", {"a": 1})


def test_double_unsubscribe_is_safe(registry):
    released = []
    registry.on_release = released.append
    unsub = registry.subscribe("/x", lambda _: None)
    unsub()
    unsub()
    assert released == ["/x"], "release must fire exactly once"


def test_prefix_subscription_matches_child_uris(registry):
    seen = []
    registry.subscribe("/lol-champ-select/v1/session", seen.append, prefix=True)
    registry.dispatch("/lol-champ-select/v1/session/actions/3", {"id": 3})
    assert seen == [{"id": 3}]


def test_exact_subscription_does_not_match_child_uris(registry):
    seen = []
    registry.subscribe("/lol-champ-select/v1/session", seen.append)
    registry.dispatch("/lol-champ-select/v1/session/actions/3", {"id": 3})
    assert seen == []


def test_rearm_restores_listeners_after_a_reconnect(registry):
    """A reconnect must not force every caller to re-subscribe."""
    seen = []
    registry.subscribe("/x", seen.append)
    registry.bump_generation()
    registry.dispatch("/x", "stale")
    assert seen == []
    assert registry.rearm() == ("/x",)
    registry.dispatch("/x", "fresh")
    assert seen == ["fresh"]


def test_dispatch_reports_delivery_count(registry):
    registry.subscribe("/x", lambda _: None)
    registry.subscribe("/x", lambda _: None)
    assert registry.dispatch("/x", 1) == 2
    assert registry.dispatch("/nope", 1) == 0


class TestEventFrameParsing:
    """The WAMP frame parser is pure, so malformed input is testable."""

    @staticmethod
    def parse(raw):
        return lcu_events.LcuEventBus._parse_event(raw)

    def test_valid_event_frame(self):
        raw = '[8,"OnJsonApiEvent",{"uri":"/lol-gameflow/v1/gameflow-phase",' \
              '"eventType":"Update","data":"ChampSelect"}]'
        assert self.parse(raw) == ("/lol-gameflow/v1/gameflow-phase", "ChampSelect")

    def test_bytes_frame_is_decoded(self):
        raw = b'[8,"OnJsonApiEvent",{"uri":"/a","data":1}]'
        assert self.parse(raw) == ("/a", 1)

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "not json",
            "{}",
            "[]",
            '[8,"OnJsonApiEvent"]',
            '[5,"OnJsonApiEvent",{"uri":"/a"}]',
            '[8,"OnJsonApiEvent",null]',
            '[8,"OnJsonApiEvent",{"data":1}]',
            '[8,"OnJsonApiEvent",{"uri":123}]',
            b"\xff\xfe",
        ],
    )
    def test_malformed_frames_yield_no_uri(self, raw):
        assert self.parse(raw) == (None, None)


class TestKillSwitch:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RC_LCU_EVENTS", raising=False)
        assert lcu_events.bus_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " off "])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("RC_LCU_EVENTS", value)
        assert lcu_events.bus_enabled() is False

    def test_other_values_stay_enabled(self, monkeypatch):
        monkeypatch.setenv("RC_LCU_EVENTS", "1")
        assert lcu_events.bus_enabled() is True


class TestEndpointTopic:
    """Per-endpoint WAMP topics, as an alternative to the firehose."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("/lol-gameflow/v1/gameflow-phase",
             "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"),
            ("/lol-champ-select/v1/session",
             "OnJsonApiEvent_lol-champ-select_v1_session"),
            ("lol-summoner/v1/current-summoner",
             "OnJsonApiEvent_lol-summoner_v1_current-summoner"),
            ("/lol-gameflow/v1/gameflow-phase/",
             "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"),
        ],
    )
    def test_topic_name(self, uri, expected):
        assert lcu_events.endpoint_topic(uri) == expected

    def test_topic_is_prefixed_by_the_firehose_name(self):
        topic = lcu_events.endpoint_topic("/a/b")
        assert topic.startswith(lcu_events.WAMP_TOPIC + "_")


# --------------------------------------------------------------------------
# RM-348 - transport lifecycle
#
# NOTE ON WHAT THESE ARE NOT: LcuEventBus has ZERO in-repo consumers today
# (the module's own docstring says callers still use their poll path), so
# these are CONTRACT tests on the bus itself, not caller tests. Inventing a
# call path to wrap them in would prove nothing about production - same
# reasoning recorded for RM-346 and RM-347.
#
# Both defects are shutdown/reconnect behaviour, so neither is observable
# against a real LCU without a live client. The fake below is a websockets
# module stand-in: run() does `import websockets` at call time, so replacing
# the sys.modules entry is enough.
# --------------------------------------------------------------------------


class _FakeConnection:
    """Async context manager standing in for ``websockets.connect(...)``."""

    def __init__(self, socket):
        self._socket = socket

    async def __aenter__(self):
        return self._socket

    async def __aexit__(self, *_exc):
        return False


class _IdleSocket:
    """A connected LCU that never pushes a frame - the client home screen.

    ``__anext__`` parks on an event nobody sets, which is exactly what a real
    quiet socket does when ``ping_interval=None`` removes the keepalive.
    """

    def __init__(self, connected):
        self._connected = connected
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)
        self._connected.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Event().wait()
        raise AssertionError("unreachable - the idle socket never yields")


class _ScriptedSocket:
    """Yields ``frames`` then ends the session, like a socket that closes."""

    def __init__(self, frames=(), on_exhausted=None):
        self._frames = list(frames)
        self._on_exhausted = on_exhausted
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._frames:
            return self._frames.pop(0)
        if self._on_exhausted is not None:
            self._on_exhausted()
        raise StopAsyncIteration


def _install_fake_websockets(monkeypatch, connect):
    module = types.ModuleType("websockets")
    module.connect = connect
    monkeypatch.setitem(sys.modules, "websockets", module)


def _record_backoff_delays(monkeypatch, bus, stop_after):
    """Capture every backoff timeout and stop the bus after ``stop_after``.

    Patches ``asyncio.wait_for``, which run() uses ONLY for the interruptible
    backoff sleep - the read loop races with ``asyncio.wait`` instead, so this
    does not touch the read path. Nothing else in this test file may use
    wait_for while the patch is live.
    """
    delays = []

    async def fake_wait_for(awaitable, timeout):
        delays.append(timeout)
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()  # the un-awaited self._stop.wait() coroutine
        if len(delays) >= stop_after:
            bus.stop()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    return delays


class TestTransportLifecycle:
    @pytest.fixture(autouse=True)
    def _bus_enabled(self, monkeypatch):
        monkeypatch.delenv("RC_LCU_EVENTS", raising=False)

    def test_stop_interrupts_an_idle_connected_socket(self, monkeypatch):
        """stop() must unpark a read that no frame will ever complete.

        The pre-RM-348 loop checked the stop flag only AFTER a frame arrived,
        so on a quiet LCU the run() task stayed parked forever, RC shutdown
        hung on it and the wss:// socket leaked for the duration.
        """
        connected = asyncio.Event()
        socket = _IdleSocket(connected)
        _install_fake_websockets(monkeypatch, lambda *a, **k: _FakeConnection(socket))
        bus = lcu_events.LcuEventBus("127.0.0.1", 12345, "pw")

        async def scenario():
            task = asyncio.ensure_future(bus.run())
            await asyncio.wait_for(connected.wait(), timeout=2.0)
            bus.stop()
            await asyncio.wait_for(task, timeout=1.0)
            return True

        assert run_coro(scenario(), timeout=8.0) is True

    def test_frames_still_dispatch_through_the_raced_read(self, monkeypatch):
        """The race must not cost delivery - guards the fix against itself."""
        bus = lcu_events.LcuEventBus("127.0.0.1", 12345, "pw")
        seen = []
        bus.subscribe("/lol-gameflow/v1/gameflow-phase", seen.append)
        frame = ('[8,"OnJsonApiEvent",{"uri":"/lol-gameflow/v1/gameflow-phase",'
                 '"data":"ChampSelect"}]')
        socket = _ScriptedSocket([frame], on_exhausted=bus.stop)
        _install_fake_websockets(monkeypatch, lambda *a, **k: _FakeConnection(socket))

        run_coro(bus.run(), timeout=8.0)

        assert seen == ["ChampSelect"]
        assert socket.sent == ['[5, "OnJsonApiEvent"]']

    def test_backoff_escalates_to_the_cap_when_the_socket_flaps(self, monkeypatch):
        """A completed handshake is not a healthy session.

        Pre-RM-348 the attempt counter was zeroed the instant connect()
        returned, so a socket that connects and immediately closes retried at
        the 1.0s floor forever and never reached the 30.0s cap.
        """
        bus = lcu_events.LcuEventBus("127.0.0.1", 12345, "pw")
        _install_fake_websockets(
            monkeypatch, lambda *a, **k: _FakeConnection(_ScriptedSocket()),
        )
        delays = _record_backoff_delays(monkeypatch, bus, stop_after=12)

        run_coro(bus.run(), timeout=8.0)

        assert delays[:6] == [1.0, 2.0, 5.0, 10.0, 30.0, 30.0]
        assert delays[-1] == 30.0

    def test_a_sustained_session_returns_the_backoff_to_the_floor(self, monkeypatch):
        """The escalation is threshold-gated, not permanent.

        Not a regression test - the pre-fix code passes this too. It pins the
        other half of the contract, so "never reset at all" cannot be shipped
        as a fix for the test above.
        """
        monkeypatch.setattr(lcu_events, "STABLE_SESSION_SECONDS", 0.0)
        bus = lcu_events.LcuEventBus("127.0.0.1", 12345, "pw")
        _install_fake_websockets(
            monkeypatch, lambda *a, **k: _FakeConnection(_ScriptedSocket()),
        )
        delays = _record_backoff_delays(monkeypatch, bus, stop_after=4)

        run_coro(bus.run(), timeout=8.0)

        assert delays == [1.0, 1.0, 1.0, 1.0]

    def test_a_failed_connect_still_escalates(self, monkeypatch):
        """connected_at stays None when the handshake never lands."""
        bus = lcu_events.LcuEventBus("127.0.0.1", 12345, "pw")

        def refuse(*_a, **_k):
            raise OSError("connection refused")

        _install_fake_websockets(monkeypatch, refuse)
        delays = _record_backoff_delays(monkeypatch, bus, stop_after=5)

        run_coro(bus.run(), timeout=8.0)

        assert delays == [1.0, 2.0, 5.0, 10.0, 30.0]
