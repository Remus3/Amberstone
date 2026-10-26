"""RM-909: the guard that no thread able to reach a live LcuClient outlives
its test module (`tests/_lcu_poller_guard.py`, wired as the module-scoped
autouse fixture `no_lcu_poller_outlives_its_module` in tests/conftest.py).

The measured leak it pins: `tests/snapshot_regressions/test_app_authority.py`
stubbed the app delegate `_on_game_start` while the lifecycle calls its own
`on_game_start`, so every TFT entry there built and started a real TftWorker
holding `core.tft_worker.make_lcu_request()`. Six such poll threads kept
calling `LcuClient.connect()` on the real clock in later test files, and the
`lcu_client.py:136` repeat they log re-armed the process-wide notice filter
inside `tests/test_lcu_lockfile_notice_dedupe.py` (LEDGER 1919).
"""
from __future__ import annotations

import ast
import queue
import threading
from pathlib import Path

from core import tft_worker
from lcu.lcu_client import LcuClient
from tests import _lcu_poller_guard as guard
from tests._timing_budget import fleet_test_guard
from tft import tft_scouting

_REPO = Path(__file__).resolve().parent.parent


class _Owner:
    """A parked poller whose only link to the LCU is `reader`."""

    def __init__(self, reader):
        self.reader = reader
        self.released = threading.Event()

    def park(self):
        self.released.wait(fleet_test_guard.budget(10))

    def stop(self):
        self.released.set()


def _parked(owner) -> threading.Thread:
    t = threading.Thread(target=owner.park, daemon=True, name="rm909-parked")
    t.start()
    return t


def test_the_measured_shape_a_tft_worker_with_the_lcu_reader_is_found():
    """The exact RM-909 leak: TftWorker._run_safe bound to a worker holding
    make_lcu_request(). The reader is lazy - no LcuClient exists yet - so the
    walk must match it by qualname, not by finding a client."""
    worker = tft_worker.TftWorker(result_queue=queue.Queue(maxsize=4),
                                  lcu_request=tft_worker.make_lcu_request())
    assert guard.reaches_lcu_client(worker._run_safe)


def test_a_tft_worker_without_the_lcu_reader_is_not_found():
    worker = tft_worker.TftWorker(result_queue=queue.Queue(maxsize=4))
    assert not guard.reaches_lcu_client(worker._run_safe)


def test_each_lcu_reach_is_found_and_a_fake_reader_is_not():
    cases = {
        "make_lcu_request": (tft_worker.make_lcu_request(), True),
        "default_lcu_get": (tft_scouting.default_lcu_get(), True),
        "a held LcuClient": (LcuClient(), True),
        "a fake reader": (lambda *_a, **_k: None, False),
    }
    for label, (reader, want) in cases.items():
        owner = _Owner(reader)
        assert guard.reaches_lcu_client(owner.park) is want, label


def test_check_module_stops_and_names_a_leaked_lcu_thread():
    owner = _Owner(tft_worker.make_lcu_request())
    before = set(threading.enumerate())
    t = _parked(owner)
    try:
        found = guard.check_module(before)
        assert found == ["'rm909-parked' (target _Owner.park)"]
        assert owner.released.is_set(), "the guard did not call the owner's stop()"
        assert not t.is_alive()
    finally:
        owner.stop()
        t.join(fleet_test_guard.budget(5))


def test_the_frozen_clients_auto_accept_thread_is_found_and_stopped():
    """The frozen client's own 1 Hz thread: owner IS the LcuClient, and the
    guard stops it through stop_auto_accept(). The tick is replaced on the
    instance so nothing reads a lockfile or logs on rc.lcu."""
    client = LcuClient()
    ticks = []
    client._auto_accept_tick = lambda: ticks.append(1)
    client._running = True
    before = set(threading.enumerate())
    t = threading.Thread(target=client._auto_accept_loop, args=(0.005,),
                         daemon=True, name="rm909-auto-accept")
    t.start()
    try:
        found = guard.check_module(before)
        assert found == ["'rm909-auto-accept' (target LcuClient._auto_accept_loop)"]
        assert client._running is False
        assert not t.is_alive()
        assert ticks, "non-vacuity: the loop really ran"
    finally:
        client._running = False
        t.join(fleet_test_guard.budget(5))


def test_a_thread_that_cannot_reach_the_lcu_is_left_alone():
    owner = _Owner(lambda *_a: None)
    before = set(threading.enumerate())
    t = _parked(owner)
    try:
        assert guard.check_module(before) == []
        assert t.is_alive() and not owner.released.is_set()
    finally:
        owner.stop()
        t.join(fleet_test_guard.budget(5))


def test_a_thread_present_before_the_module_is_not_blamed_on_it():
    owner = _Owner(tft_worker.make_lcu_request())
    t = _parked(owner)
    try:
        assert guard.check_module(set(threading.enumerate())) == []
    finally:
        owner.stop()
        t.join(fleet_test_guard.budget(5))


def test_a_walk_that_raises_counts_as_not_reaching():
    class _Hostile:
        def __getattribute__(self, name):
            raise RuntimeError("hostile attribute access")

    owner = _Owner(_Hostile())
    t = threading.Thread(target=owner.park, daemon=True)
    assert guard.thread_reaches_lcu_client(t) is False


def test_conftest_wires_the_guard_module_scoped_and_autouse():
    tree = ast.parse((_REPO / "tests" / "conftest.py").read_text(encoding="utf-8"))
    fixture = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "no_lcu_poller_outlives_its_module"), None)
    assert fixture is not None, "tests/conftest.py lost the RM-909 guard"
    kwargs = {}
    for dec in fixture.decorator_list:
        if isinstance(dec, ast.Call):
            kwargs.update({k.arg: getattr(k.value, "value", None) for k in dec.keywords})
    assert kwargs.get("scope") == "module" and kwargs.get("autouse") is True
    calls = {ast.unparse(n.func) for n in ast.walk(fixture) if isinstance(n, ast.Call)}
    assert "_lcu_poller_guard.check_module" in calls
    assert "pytest.fail" in calls
