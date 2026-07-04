"""Regression: RuneWriter._poll self-heals the shared LcuClient BEFORE reading
champ select, so the writer no longer depends on the sibling auto-accept
coroutine being alive to heal the connection.

Root cause (2026-07-04, pid 6440): after a mid-session League client restart,
the in-process spawn_task auto-accept + RuneWriter coroutines stopped ticking.
The auto-accept tick is what normally calls _refresh_conn_if_changed() /
connect() on the ONE shared _lcu, so once it went silent the LcuClient never
healed off the dead pre-restart port. get_champ_select() then returned None on
every RuneWriter poll and no rune page was pushed.

Mitigation under test: RuneWriter._poll replicates the frozen
_auto_accept_tick pattern (lcu/lcu_client.py:224-226) at the top of its own
poll - refresh, then connect() if _port is falsy - getattr-guarded (so test
fakes lacking these methods stay green) and fail-soft (a heal error must never
kill the poll)."""
from __future__ import annotations

import threading

from lcu.lcu_rune_writer import RuneWriter


class _FakeLcuStaleHeals:
    """LCU stuck on a dead pre-restart port; refresh flips it to the live port.

    get_champ_select() returns None until _port == live_port, mirroring the
    real client where a request on the dead port yields None until creds are
    swapped to the rotated lockfile port.
    """

    def __init__(self, dead_port, live_port, session):
        self._port = dead_port
        self._live_port = live_port
        self._session = session
        self.refresh_calls = 0
        self.connect_calls = 0

    def _refresh_conn_if_changed(self):
        self.refresh_calls += 1
        # Lockfile rotation detected: swap to the fresh live port.
        self._port = self._live_port

    def connect(self):
        self.connect_calls += 1
        return True

    def get_champ_select(self):
        if self._port == self._live_port:
            return self._session
        return None


class _FakeLcuPortCleared:
    """LCU with creds cleared (_port None, e.g. lockfile briefly gone). refresh
    is a no-op; the poll must fall through to connect() because _port is falsy.
    """

    def __init__(self, session):
        self._port = None
        self._session = session
        self.refresh_calls = 0
        self.connect_calls = 0

    def _refresh_conn_if_changed(self):
        self.refresh_calls += 1

    def connect(self):
        self.connect_calls += 1
        self._port = 59333  # connect() establishes a live port
        return True

    def get_champ_select(self):
        return self._session if self._port else None


class _FakeLcuNoHealMethods:
    """Bare fake lacking _refresh_conn_if_changed / connect - pins the getattr
    fail-soft so pre-existing writer/spell tests (whose fakes lack these) stay
    green.
    """

    def __init__(self, session):
        self._session = session

    def get_champ_select(self):
        return self._session


def _make_writer(lcu):
    """Mirror tests/test_lcu_rune_writer_rearm.py::_make_writer but inject a
    caller-supplied LCU fake (we are exercising the connection self-heal)."""
    w = RuneWriter.__new__(RuneWriter)  # skip __init__ (no build_champ_id_map / LCU)
    w._lcu = lcu
    w._stop_event = threading.Event()
    w._last_applied_champion = ""
    w._last_applied_mode = ""
    w._in_champ_select = False
    w._applied: list = []
    w._detect_game_mode = lambda: "ARAM"
    w._sync_spells = lambda session, mode: True
    w._detect_my_champion = lambda session: (session or {}).get("champ", "")

    def _apply(champion, mode):
        w._applied.append((champion, mode))
        return True

    w._apply_runes = _apply
    return w


def test_poll_reheals_stale_lcu_then_reads_champ_select():
    # LCU is stuck on the dead pre-restart port 63654; the live client is on
    # 59333. get_champ_select() returns None until the refresh swaps the port.
    session = {"champ": "Sivir"}
    lcu = _FakeLcuStaleHeals(dead_port=63654, live_port=59333, session=session)
    w = _make_writer(lcu)

    w._poll()  # ONE poll must self-heal, then read the session

    assert lcu.refresh_calls == 1, "poll must call _refresh_conn_if_changed once"
    assert lcu._port == 59333, "refresh must have swapped to the live port"
    # The champ-select was detected on the SAME poll after the heal.
    assert w._applied == [("Sivir", "ARAM")]
    assert w._in_champ_select is True


def test_poll_calls_connect_when_port_cleared():
    session = {"champ": "Olaf"}
    lcu = _FakeLcuPortCleared(session=session)
    w = _make_writer(lcu)

    w._poll()

    assert lcu.connect_calls == 1, "falsy _port must trigger connect()"
    assert lcu._port == 59333
    assert w._applied == [("Olaf", "ARAM")]


def test_poll_survives_lcu_without_heal_methods():
    # Bare LCU lacking the heal methods (like the existing rearm/spell fakes):
    # the poll must not raise and must still read the session.
    session = {"champ": "Yuumi"}
    lcu = _FakeLcuNoHealMethods(session=session)
    w = _make_writer(lcu)

    w._poll()  # must not raise despite missing _refresh_conn_if_changed / connect

    assert w._applied == [("Yuumi", "ARAM")]
    assert w._in_champ_select is True
