"""Round 12 coverage - input-latency rollup + file_ingest mode-transition callback."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest


# ── Input latency rollup ─────────────────────────────────────────────

def test_latency_stats_empty_returns_none_fields() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    s = sup.input_latency_stats()
    assert s["n"] == 0
    assert s["avg_ms"] is None
    assert s["min_ms"] is None
    assert s["max_ms"] is None
    assert s["p95_ms"] is None


def test_latency_stats_accumulates_and_caps() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    # Push 25 samples - buffer caps at 20.
    for i, v in enumerate([50, 80, 120, 200, 350, 600,
                           50, 80, 100, 150, 220, 280,
                           40, 90, 110, 170, 230, 310,
                           75, 95, 130, 190, 260, 400, 500]):
        sup.record_input_latency(float(v))
    s = sup.input_latency_stats()
    assert s["n"] == 20                      # capped
    assert s["min_ms"] is not None and s["min_ms"] > 0
    assert s["max_ms"] is not None and s["max_ms"] >= s["min_ms"]
    assert s["avg_ms"] is not None
    assert s["p95_ms"] is not None
    # p95 should be near the top of the distribution.
    assert s["p95_ms"] >= s["avg_ms"]


def test_latency_stats_single_sample() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    sup.record_input_latency(123.4)
    s = sup.input_latency_stats()
    assert s["n"] == 1
    assert s["avg_ms"] == 123.4
    assert s["min_ms"] == 123.4
    assert s["max_ms"] == 123.4
    assert s["p95_ms"] == 123.4


# ── File-ingest mode-transition callback ────────────────────────────

@pytest.mark.timeout(10)
def test_mode_transition_fires_on_health_change(tmp_path: Path) -> None:
    """Simulate health.json mtime advances with different mode values -
    the callback should receive only transitions (not first sighting
    or duplicates)."""
    from agents.agent2_backend.file_ingest import FileIngest

    calls: list[tuple[str, str]] = []
    def _cb(prev, new):
        calls.append((prev, new))

    class _FakeWS:
        push_subscribers = 0
        async def broadcast_push(self, _env):
            pass

    ingest = FileIngest(_FakeWS(), on_mode_transition=_cb)

    # Point HEALTH_PATH at a tmp file so we don't touch production state.
    health = tmp_path / "health.json"
    from agents.agent2_backend import file_ingest as fi_mod
    fi_mod.HEALTH_PATH = health

    def _write_mode(mode: str) -> None:
        health.write_text(json.dumps({"mode": mode, "alive": True}),
                          encoding="utf-8")
        time.sleep(0.02)          # ensure mtime increments

    async def drive():
        _write_mode("client")
        await ingest._tick()       # first sighting, no prev - no callback
        _write_mode("game")
        await ingest._tick()       # transition
        _write_mode("game")
        await ingest._tick()       # same file contents, different mtime
                                   # NOTE: we DO re-parse, but mode didn't change
        _write_mode("client")
        await ingest._tick()       # transition back
    asyncio.run(drive())

    assert calls == [("client", "game"), ("game", "client")]


@pytest.mark.timeout(5)
def test_mode_transition_same_mode_no_callback(tmp_path: Path) -> None:
    from agents.agent2_backend.file_ingest import FileIngest

    calls: list[tuple[str, str]] = []
    def _cb(prev, new):
        calls.append((prev, new))

    class _FakeWS:
        async def broadcast_push(self, _env): pass

    ingest = FileIngest(_FakeWS(), on_mode_transition=_cb)
    health = tmp_path / "health.json"
    from agents.agent2_backend import file_ingest as fi_mod
    fi_mod.HEALTH_PATH = health

    async def drive():
        health.write_text(json.dumps({"mode": "client"}), encoding="utf-8")
        await ingest._tick()
        # Change a non-mode field and bump mtime - mode same.
        time.sleep(0.02)
        health.write_text(json.dumps({"mode": "client", "pid": 123}),
                          encoding="utf-8")
        await ingest._tick()
    asyncio.run(drive())
    assert calls == []


def test_mode_transition_callback_exception_swallowed(tmp_path: Path) -> None:
    """Callback raising must not break the ingest loop."""
    from agents.agent2_backend.file_ingest import FileIngest

    def _bad_cb(prev, new):
        raise RuntimeError("intentional")

    class _FakeWS:
        async def broadcast_push(self, _env): pass

    ingest = FileIngest(_FakeWS(), on_mode_transition=_bad_cb)
    health = tmp_path / "health.json"
    from agents.agent2_backend import file_ingest as fi_mod
    fi_mod.HEALTH_PATH = health

    async def drive():
        health.write_text(json.dumps({"mode": "client"}), encoding="utf-8")
        await ingest._tick()         # prime last_mode
        time.sleep(0.02)
        health.write_text(json.dumps({"mode": "game"}), encoding="utf-8")
        await ingest._tick()         # callback raises - must be caught
    asyncio.run(drive())
    # If we reach here without propagating, the swallow worked.


# ── s171.8: LCU-phase overlay for effective mode ────────────────────

def test_effective_mode_trusts_health_when_in_game() -> None:
    """LiveClient-confirmed in-game (health.mode='game') wins over LCU.

    Once LiveClient :2999 fires, that's authoritative - don't downgrade
    to LCU-derived "champ_select" if LCU briefly disagrees during the
    GameStart → InProgress transition.
    """
    from agents.agent2_backend.file_ingest import FileIngest
    assert FileIngest._compute_effective_mode({"mode": "game"}, "ChampSelect") == "game"
    assert FileIngest._compute_effective_mode({"mode": "in_progress"}, "GameStart") == "in_progress"


def test_effective_mode_lcu_overlay_when_health_client() -> None:
    """Legion can't see Game-PC's LCU lockfile → health.mode='client'
    through the entire CS+loading window. LCU phase fills the gap so
    the supervisor's warm-Agent-7 prime hook fires on time."""
    from agents.agent2_backend.file_ingest import FileIngest
    fn = FileIngest._compute_effective_mode
    assert fn({"mode": "client"}, "ChampSelect") == "champ_select"
    assert fn({"mode": "client"}, "GameStart") == "game"
    assert fn({"mode": "client"}, "InProgress") == "game"


def test_effective_mode_falls_back_to_health_when_lcu_unknown() -> None:
    """Without LCU signal (None / Lobby / EndOfGame), use raw health."""
    from agents.agent2_backend.file_ingest import FileIngest
    fn = FileIngest._compute_effective_mode
    assert fn({"mode": "client"}, None) == "client"
    assert fn({"mode": "client"}, "Lobby") == "client"
    assert fn({"mode": "client"}, "EndOfGame") == "client"
    # Empty health.mode → None (matches existing transition behavior).
    assert fn({}, None) is None
