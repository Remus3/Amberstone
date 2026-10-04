"""RM-274: `HttpClient._hosts` must be bounded in a process that runs for days.

One `_HostState` per hostname used to be created and never evicted, and the
hostname set is not statically bounded (`lib/scrapers/_base.py` forwards any
`http...` path verbatim). Acceptance: a bounded map whose eviction NEVER drops
a host whose breaker is open or whose half-open probe is in flight - evicting
those would silently reset protection for exactly the host that earned it.
"""
from __future__ import annotations

import time

import pytest

from lib.http import client as C


@pytest.fixture
def small_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "MAX_TRACKED_HOSTS", 8)
    bl = tmp_path / "blocklist.json"
    bl.write_text('{"hosts": [], "suffixes": []}', encoding="ascii")
    return C.HttpClient(blocklist_path=bl)


def _open_breaker(cli, host):
    for _ in range(C.BREAKER_THRESHOLD):
        cli._on_failure(host, OSError("down"))
    assert cli._host_state(host).opened_at is not None


def test_map_stays_bounded_under_many_hosts(small_cap):
    for i in range(500):
        small_cap._host_state(f"h{i}.example")
    assert len(small_cap._hosts) <= C.MAX_TRACKED_HOSTS


def test_open_breaker_survives_eviction_pressure(small_cap):
    _open_breaker(small_cap, "bad.example")
    opened_at = small_cap._hosts["bad.example"].opened_at
    for i in range(500):
        small_cap._host_state(f"h{i}.example")
    assert "bad.example" in small_cap._hosts
    assert small_cap._hosts["bad.example"].opened_at == opened_at
    # Still refusing calls: protection was not reset.
    with pytest.raises(C.CircuitOpen):
        small_cap._check_breaker("bad.example", time.monotonic())


def test_probe_in_flight_survives_eviction_pressure(small_cap):
    _open_breaker(small_cap, "probe.example")
    st = small_cap._hosts["probe.example"]
    st.opened_at = time.monotonic() - C.BREAKER_COOLDOWN_SEC - 1
    small_cap._check_breaker("probe.example", time.monotonic())
    assert st.probe_in_flight is True
    for i in range(500):
        small_cap._host_state(f"h{i}.example")
    assert small_cap._hosts.get("probe.example") is st
    with pytest.raises(C.CircuitOpen):
        small_cap._check_breaker("probe.example", time.monotonic())


def test_partial_failure_count_outlives_healthy_hosts(small_cap):
    small_cap._on_failure("flaky.example", OSError("x"))
    for i in range(C.MAX_TRACKED_HOSTS - 2):
        small_cap._host_state(f"h{i}.example")
    small_cap._host_state("trigger.example")  # forces one eviction pass
    small_cap._host_state("trigger2.example")
    assert small_cap._hosts["flaky.example"].failures == 1


def test_all_protected_hosts_may_exceed_cap_rather_than_drop_one(small_cap):
    for i in range(C.MAX_TRACKED_HOSTS + 3):
        _open_breaker(small_cap, f"down{i}.example")
    assert all(f"down{i}.example" in small_cap._hosts
               for i in range(C.MAX_TRACKED_HOSTS + 3))
