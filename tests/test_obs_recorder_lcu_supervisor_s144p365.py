"""S144-P-365: the OBS recorder's LCU supervisor survives a raising pass.

core/obs_recorder.py ``_main`` runs ``rec.run()``, the disk guard and
``_lcu_supervisor`` under one ``asyncio.gather``. The supervisor loop had no
broad ``try``: a raise from ``LcuEventBus(...)`` (its constructor does
``int(port)``, so a lockfile with a non-numeric port raises ValueError) or from
``bus.subscribe`` left ``_lcu_supervisor``, so ``gather`` raised, ``_main`` ended
and the recorder (and its disk guard) stopped with it. The supervisor now logs
the pass and tries again at the next rescan.
"""
from __future__ import annotations

import asyncio

from core import lcu_events
from core import obs_recorder as orc
from tests._asyncio_isolation import run_coro


class _Rec:
    """The one attribute _lcu_supervisor reads off the recorder."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()

    def on_gameflow_phase(self, _payload) -> None:  # pragma: no cover - never fired
        pass

    def on_gameflow_session(self, _payload) -> None:  # pragma: no cover - never fired
        pass


class _GoodBus:
    """Stand-in LcuEventBus: subscribes fine, run() idles until stopped."""

    instances: list = []

    def __init__(self, host, port, password) -> None:
        self.port = port
        self.stopped = asyncio.Event()
        _GoodBus.instances.append(self)

    def subscribe(self, uri, callback, prefix=False):
        return lambda: None

    def stop(self) -> None:
        self.stopped.set()

    async def run(self) -> None:
        await self.stopped.wait()


def _drive(monkeypatch, creds_seq, bus_cls, *, passes):
    """Run _lcu_supervisor for ``passes`` rescans, return (raised, rec)."""
    monkeypatch.setattr(orc, "_LCU_RESCAN_S", 0.01)
    monkeypatch.setattr(lcu_events, "LcuEventBus", bus_cls)
    seq = list(creds_seq)
    calls = {"n": 0}
    hook = {"reached": None}

    def _creds():
        calls["n"] += 1
        if calls["n"] >= passes and hook["reached"] is not None:
            hook["reached"]()
        return seq[min(calls["n"] - 1, len(seq) - 1)]

    monkeypatch.setattr(orc, "_lcu_credentials", _creds)

    async def _go():
        loop = asyncio.get_running_loop()
        reached = asyncio.Event()
        # thread-safe: _creds may run on an executor thread
        hook["reached"] = lambda: loop.call_soon_threadsafe(reached.set)
        rec = _Rec()
        sup = asyncio.ensure_future(orc._lcu_supervisor(rec))
        waiter = asyncio.ensure_future(reached.wait())
        await asyncio.wait({waiter, sup}, return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        still_running = not sup.done()
        rec._stop.set()
        try:
            await asyncio.wait_for(sup, timeout=5)
            err = None
        except Exception as exc:  # noqa: BLE001
            err = exc
        return still_running, err

    return run_coro(_go())


def test_bad_lockfile_port_does_not_end_the_supervisor(monkeypatch):
    still_running, err = _drive(
        monkeypatch,
        [("not-a-port", "pw")],
        lcu_events.LcuEventBus,
        passes=4,
    )
    assert err is None
    assert still_running, "supervisor ended after a bus constructor raise"


def test_subscribe_raise_does_not_end_the_supervisor(monkeypatch):
    class _BadSubscribe(_GoodBus):
        def subscribe(self, uri, callback, prefix=False):
            raise RuntimeError("subscribe boom")

    still_running, err = _drive(
        monkeypatch, [(2999, "pw")], _BadSubscribe, passes=4
    )
    assert err is None
    assert still_running, "supervisor ended after a bus.subscribe raise"


def test_recovers_when_credentials_become_valid(monkeypatch):
    class _PickyBus(_GoodBus):
        def __init__(self, host, port, password) -> None:
            int(port)  # the real constructor's check
            super().__init__(host, port, password)

    _GoodBus.instances.clear()
    still_running, err = _drive(
        monkeypatch,
        [("bad", "pw"), (2999, "pw")],
        _PickyBus,
        passes=6,
    )
    assert err is None
    assert still_running
    assert [b.port for b in _GoodBus.instances] == [2999]


def test_stop_still_ends_a_healthy_supervisor(monkeypatch):
    _GoodBus.instances.clear()
    still_running, err = _drive(
        monkeypatch, [(2999, "pw")], _GoodBus, passes=3
    )
    assert err is None
    assert still_running
    assert _GoodBus.instances, "a valid lockfile built no bus"
    assert all(b.stopped.is_set() for b in _GoodBus.instances)
