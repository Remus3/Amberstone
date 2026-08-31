"""core/obs_publisher.py - lane 8 deep audit (cycle 42).

Selected on criteria 1 + 2 + 3 + 4: it parses OBS-WebSocket v5 payloads RC
does not author, it carries an auth password, it runs a daemon thread plus
an asyncio loop over a process-wide frame slot, and 468 lines of it had no
dedicated test module. Live-reachable from `dashboard/server.py:259`.

Four weaknesses are pinned here.

1. ASCII HARD RULE. The module carried four U+00B7 MIDDLE DOT characters in
   `_render_state`, i.e. in the string PUSHED TO OBS, not in a comment.
   `tests/test_p2w1_core_f.py::test_no_banned_typography` is parametrized
   over this exact file and passed green, because its `_BANNED_CHARS` set
   holds only the six historical glyphs. `tools/precommit_gate.py` was
   WIDENED to a non-ASCII catch-all on 2026-07-28 for precisely this
   disagreement ("two rules enforcing the same CLAUDE.md hard rule
   disagreed about what it means, and the looser one ran first"), but the
   widening reached the gate and not the test. The gate also scans ADDED
   lines only, so a 2026-05-01 file is invisible to it forever.

2. INPUT VALIDATION. `_identify` called `.get()` on whatever `json.loads`
   returned. Valid JSON that is not an object (a list, a string, a number,
   null) raised AttributeError OUTSIDE the local try, escaping to the
   generic loop handler as an "unexpected error". The sibling
   `request_response` already carried the `isinstance(msg, dict)` check.

3. RESOURCE LIFETIME / LIVENESS. `_identify` awaited two UNBOUNDED
   `ws.recv()` calls. `websockets.connect(open_timeout=4)` bounds only the
   opening handshake. Every other recv in the module is bounded. A peer
   that completes the handshake and then answers pings without ever
   sending Hello pinned the publisher forever, and `stop()` could not
   reclaim it because `_stop` is only read at the top of the loops.

4. CONCURRENCY. `stop()` set `self._task = None` immediately after
   `cancel()`. Cancellation is a REQUEST, so the loop is still unwinding;
   dropping the only handle let the next `start_background()` pass the
   idempotence check AND call `_stop.clear()`, resurrecting the old loop
   and running two publishers against one OBS connection and one shared
   frame slot. This is the cycle-9 `core/log_retention.py` defect (LEDGER
   1200 weakness 4) reproduced on the asyncio path.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests._asyncio_isolation import run_coro as _run_coro

_REPO_ROOT = Path(__file__).resolve().parent.parent


class _ScriptedWs:
    """Yields queued frames, then blocks forever - a peer that stops talking."""

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        if self.incoming:
            return self.incoming.pop(0)
        await asyncio.Event().wait()


class _FakeTask:
    """Minimal stand-in for the scheduler handle `spawn_task` returns."""

    def __init__(self, done: bool = False):
        self._done = done
        self.cancelled = 0

    def cancel(self):
        self.cancelled += 1

    def done(self):
        return self._done


# --- 1. ASCII hard rule --------------------------------------------------

def test_obs_publisher_module_is_pure_ascii():
    """CLAUDE.md: 7-bit ASCII authored content, code and strings included."""
    text = (_REPO_ROOT / "core" / "obs_publisher.py").read_text(encoding="utf-8")
    bad = sorted({c for c in text if ord(c) > 126})
    assert not bad, (
        "core/obs_publisher.py carries non-ASCII: "
        + ", ".join(f"U+{ord(c):04X} x{text.count(c)}" for c in bad)
    )


def test_banned_typography_guard_is_a_catch_all_not_six_glyphs():
    """The guard's DOMAIN must match its NAME.

    Pinning the mechanism that let weakness 1 sit green: a guard scoped to
    six codepoints cannot enforce a rule written about 7-bit ASCII.
    """
    import tests.test_p2w1_core_f as guard

    src = (_REPO_ROOT / "tests" / "test_p2w1_core_f.py").read_text(encoding="utf-8")
    assert "ord(c) > 126" in src, (
        "test_no_banned_typography must reject every non-ASCII codepoint, "
        "not only the six historical glyphs"
    )
    # sanity: U+00B7 really is outside the historical six
    assert "\u00b7" not in guard._BANNED_CHARS


# --- 2. input validation: non-object JSON on the handshake ---------------

@pytest.mark.parametrize("payload", ["[1, 2]", '"hello"', "42", "null", "true"])
def test_identify_survives_non_object_hello(payload):
    """Valid JSON that is not an object must be refused, never raise."""
    from core.obs_publisher import OBSPublisher

    ws = _ScriptedWs([payload])
    assert _run_coro(OBSPublisher()._identify(ws, password="")) is False


@pytest.mark.parametrize("payload", ["[1, 2]", '"hello"', "42", "null"])
def test_identify_survives_non_object_identified(payload):
    """The second frame gets the same treatment as the first."""
    from core.obs_publisher import OBSPublisher

    ws = _ScriptedWs([json.dumps({"op": 0, "d": {}}), payload])
    assert _run_coro(OBSPublisher()._identify(ws, password="")) is False


@pytest.mark.parametrize("bad_d", [[1, 2], "d", 7, None])
def test_identify_survives_non_object_d_block(bad_d):
    """Hello is an object but its `d` is not - `.get` must not be reached."""
    from core.obs_publisher import OBSPublisher

    hello = json.dumps({"op": 0, "d": bad_d})
    ws = _ScriptedWs([hello, json.dumps({"op": 2, "d": {}})])
    # No authentication block is discoverable, so this proceeds unauthenticated
    # rather than raising - the point is that it does not raise.
    assert _run_coro(OBSPublisher()._identify(ws, password="")) is True


@pytest.mark.parametrize("salt,challenge", [
    (1, "c"), ("s", 2), (None, "c"), ("s", None), ([], {}),
])
def test_identify_refuses_non_string_salt_or_challenge(salt, challenge):
    """`password + salt` on a non-str raises TypeError inside the handshake."""
    from core.obs_publisher import OBSPublisher

    hello = json.dumps({
        "op": 0,
        "d": {"authentication": {"salt": salt, "challenge": challenge}},
    })
    ws = _ScriptedWs([hello, json.dumps({"op": 2, "d": {}})])
    assert _run_coro(OBSPublisher()._identify(ws, password="pw")) is False


def test_identify_survives_non_object_authentication_block():
    """`d.authentication` is attacker-shaped too - a list has no .get."""
    from core.obs_publisher import OBSPublisher

    hello = json.dumps({"op": 0, "d": {"authentication": [1, 2]}})
    ws = _ScriptedWs([hello, json.dumps({"op": 2, "d": {}})])
    assert _run_coro(OBSPublisher()._identify(ws, password="pw")) is False


# --- 3. liveness: the handshake must be bounded --------------------------

def test_identify_gives_up_when_peer_never_sends_hello(monkeypatch):
    """A peer that opens the socket and then goes silent must not pin us."""
    from core import obs_publisher

    monkeypatch.setattr(obs_publisher, "_HANDSHAKE_TIMEOUT_S", 0.05,
                        raising=False)
    ws = _ScriptedWs([])  # blocks forever on the first recv

    async def _drive():
        return await asyncio.wait_for(
            obs_publisher.OBSPublisher()._identify(ws, password=""),
            timeout=2.0,
        )

    assert _run_coro(_drive()) is False


def test_identify_gives_up_when_peer_never_confirms(monkeypatch):
    """Hello arrives, Identified never does - the same bound applies."""
    from core import obs_publisher

    monkeypatch.setattr(obs_publisher, "_HANDSHAKE_TIMEOUT_S", 0.05,
                        raising=False)
    ws = _ScriptedWs([json.dumps({"op": 0, "d": {}})])

    async def _drive():
        return await asyncio.wait_for(
            obs_publisher.OBSPublisher()._identify(ws, password=""),
            timeout=2.0,
        )

    assert _run_coro(_drive()) is False


# --- 4. lifecycle: cancel is a request, not a stop -----------------------

def test_stop_keeps_the_handle_of_a_task_that_has_not_finished():
    from core.obs_publisher import OBSPublisher

    pub = OBSPublisher()
    task = _FakeTask(done=False)
    pub._task = task

    pub.stop()

    assert task.cancelled == 1
    assert pub._task is task, (
        "stop() dropped the only handle to a loop that is still unwinding"
    )


def test_stop_releases_the_handle_of_a_finished_task():
    from core.obs_publisher import OBSPublisher

    pub = OBSPublisher()
    pub._task = _FakeTask(done=True)

    pub.stop()

    assert pub._task is None


def test_start_background_refuses_to_spawn_beside_an_unfinished_task(monkeypatch):
    """The double-spawn this whole group exists to prevent."""
    import app._loop as _loop_mod

    from core import obs_publisher

    spawned = []

    class _Sched:
        def spawn_task(self, coro):
            coro.close()  # we never run it; avoid a never-awaited warning
            spawned.append(1)
            return _FakeTask(done=False)

    monkeypatch.setattr(obs_publisher, "_load_obs_config",
                        lambda: {"enabled": True})
    monkeypatch.setattr(_loop_mod, "get_loop", lambda: _Sched())

    pub = obs_publisher.OBSPublisher()
    pub.start_background()
    assert len(spawned) == 1

    pub.stop()               # cancel requested; the loop has NOT finished
    pub.start_background()   # must be refused

    assert len(spawned) == 1, "a second publisher loop was spawned"
    assert pub._stop.is_set(), (
        "the stop flag was cleared while the prior loop was still running"
    )


def test_start_background_spawns_again_once_the_task_is_done(monkeypatch):
    """The refusal must not latch - a finished loop is restartable."""
    import app._loop as _loop_mod

    from core import obs_publisher

    spawned = []
    handles = [_FakeTask(done=True), _FakeTask(done=True)]

    class _Sched:
        def spawn_task(self, coro):
            coro.close()
            spawned.append(1)
            return handles[len(spawned) - 1]

    monkeypatch.setattr(obs_publisher, "_load_obs_config",
                        lambda: {"enabled": True})
    monkeypatch.setattr(_loop_mod, "get_loop", lambda: _Sched())

    pub = obs_publisher.OBSPublisher()
    pub.start_background()
    pub.stop()
    pub.start_background()

    assert len(spawned) == 2
    assert not pub._stop.is_set()


def test_start_background_does_not_latch_when_the_loop_ends_on_its_own(monkeypatch):
    """Cycle-9 weakness 5, on the asyncio path.

    A task can finish WITHOUT `stop()` ever being called - the loop raised,
    or was cancelled by the scheduler. The handle is then still assigned and
    still non-None. An idempotence check that only asks `is not None` latches
    the publisher off for the rest of the process lifetime; it has to ask
    whether the task is DONE. Found by mutation M10, which the rest of this
    group could not kill because every other case calls `stop()` first.
    """
    import app._loop as _loop_mod

    from core import obs_publisher

    spawned = []

    class _Sched:
        def spawn_task(self, coro):
            coro.close()
            spawned.append(1)
            return _FakeTask(done=False)

    monkeypatch.setattr(obs_publisher, "_load_obs_config",
                        lambda: {"enabled": True})
    monkeypatch.setattr(_loop_mod, "get_loop", lambda: _Sched())

    pub = obs_publisher.OBSPublisher()
    pub.start_background()
    assert len(spawned) == 1

    pub._task._done = True   # the loop ended on its own; stop() never ran
    pub.start_background()

    assert len(spawned) == 2, "start_background latched off after the loop ended"


def test_start_background_treats_an_unrecognised_handle_as_running(monkeypatch):
    """Cycle-9 precedent: an unknown scheduler must never permit a double spawn."""
    import app._loop as _loop_mod

    from core import obs_publisher

    spawned = []

    class _OpaqueHandle:
        """No done(), no cancel() - a handle we cannot interrogate."""

    class _Sched:
        def spawn_task(self, coro):
            coro.close()
            spawned.append(1)
            return _OpaqueHandle()

    monkeypatch.setattr(obs_publisher, "_load_obs_config",
                        lambda: {"enabled": True})
    monkeypatch.setattr(_loop_mod, "get_loop", lambda: _Sched())

    pub = obs_publisher.OBSPublisher()
    pub.start_background()
    pub.stop()
    pub.start_background()

    assert len(spawned) == 1


# --- 5. characterization: the parts that were already right --------------

def test_password_never_reaches_a_log_or_the_wire(caplog):
    """Secret handling stays CLEAN: the password is hashed, never echoed."""
    import logging

    from core.obs_publisher import OBSPublisher

    secret = "s3cr3t-not-a-real-password"
    hello = json.dumps({
        "op": 0,
        "d": {"authentication": {"salt": "s", "challenge": "c"}},
    })
    ws = _ScriptedWs([hello, json.dumps({"op": 2, "d": {}})])

    with caplog.at_level(logging.DEBUG):
        ok = _run_coro(OBSPublisher()._identify(ws, password=secret))

    assert ok is True
    assert secret not in caplog.text
    assert secret not in " ".join(ws.sent), "password sent in the clear"


def test_identify_still_subscribes_to_no_events():
    """Characterization pin carried from tests/test_p2w1_core_f.py."""
    from core.obs_publisher import OBSPublisher

    ws = _ScriptedWs([json.dumps({"op": 0, "d": {}}),
                      json.dumps({"op": 2, "d": {}})])

    assert _run_coro(OBSPublisher()._identify(ws, password="")) is True
    assert json.loads(ws.sent[0])["d"]["eventSubscriptions"] == 0
