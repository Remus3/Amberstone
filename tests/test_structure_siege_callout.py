"""Instant base-siege callout (no-LLM bridge for the base-attack slow tick).

The slow "coach tick" during a base push was just inherent Haiku latency
(~6s); this deterministic callout fires the moment a turret/inhibitor falls so
coaching is on-screen immediately via the fast /api/state path, ahead of the
Haiku tick. SR + ARAM only (Arena's ring has no lane structures).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.event_callouts import next_callouts, structure_siege_callout  # noqa: E402


def _siege(callouts):
    return [c for c in callouts if c.get("kind") == "siege"]


# -- structure_siege_callout (the pure builder) --------------------------------

def test_recent_inhib_fires_active_callout():
    out = structure_siege_callout([], [{"down_at_s": 1000.0}], 1010.0)
    assert len(out) == 1
    assert out[0]["tag"] == "siege_inhib"
    assert out[0]["eta_s"] == 0          # active
    assert out[0]["kind"] == "siege"


def test_recent_turret_fires_active_callout():
    out = structure_siege_callout([{"down_at_s": 1000.0}], [], 1015.0)
    assert len(out) == 1
    assert out[0]["tag"] == "siege_turret"
    assert out[0]["eta_s"] == 0


def test_structure_older_than_recency_does_not_fire():
    # Fell 90s ago, recency window 30s -> faded, no callout.
    out = structure_siege_callout([{"down_at_s": 1000.0}], [{"down_at_s": 1000.0}], 1090.0)
    assert out == []


def test_inhib_outranks_turret_when_both_recent():
    out = structure_siege_callout([{"down_at_s": 1000.0}], [{"down_at_s": 1000.0}], 1005.0)
    assert [c["tag"] for c in out] == ["siege_inhib", "siege_turret"]


def test_future_or_malformed_events_are_failsoft():
    assert structure_siege_callout("nope", {"bad": 1}, 1000.0) == []
    assert structure_siege_callout([{"down_at_s": "x"}, None, 7], [], 1000.0) == []
    # down_at_s in the future (clock skew) -> not "recent", excluded.
    assert structure_siege_callout([{"down_at_s": 2000.0}], [], 1000.0) == []
    assert structure_siege_callout([], [], "bad-time") == []


def test_custom_recency_window():
    evs = [{"down_at_s": 1000.0}]
    assert structure_siege_callout(evs, [], 1040.0, recency_s=60.0)  # inside 60s
    assert structure_siege_callout(evs, [], 1040.0, recency_s=10.0) == []  # outside 10s


# -- next_callouts wiring + the SR/ARAM mode gate ------------------------------

def test_next_callouts_surfaces_siege_for_aram():
    out = next_callouts(
        "aram", 1010.0, level=11, item_count=3,
        turret_events=[{"down_at_s": 1000.0}],
    )
    assert _siege(out), "ARAM recent turret should surface a siege callout"


def test_next_callouts_surfaces_siege_for_sr():
    out = next_callouts(
        "sr", 1010.0, level=11, item_count=3,
        inhib_events=[{"down_at_s": 1000.0}],
    )
    tags = {c["tag"] for c in _siege(out)}
    assert "siege_inhib" in tags


def test_next_callouts_no_siege_for_arena():
    # Arena has no lane structures -> gate excludes it even with a fresh event.
    out = next_callouts(
        "arena", 1010.0, level=11, item_count=3,
        turret_events=[{"down_at_s": 1000.0}],
    )
    assert _siege(out) == []


def test_next_callouts_no_siege_when_no_recent_structure():
    out = next_callouts(
        "aram", 1200.0, level=11, item_count=3,
        turret_events=[{"down_at_s": 1000.0}],  # 200s old
    )
    assert _siege(out) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
