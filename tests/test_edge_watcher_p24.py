"""P2-4: edge-triggered state watcher - startup state and reconnects never fire.

Contract under test (core/edge_watcher.py):
  * the first read of a target is a PRIMING read and never fires, whatever it
    sees (a state already present when the watcher starts is not an event);
  * only an ABSENT -> PRESENT edge fires;
  * UNREACHABLE -> PRESENT re-primes silently (a reconnect is not an event);
  * a probe that raises counts as UNREACHABLE and nothing escapes;
  * dry-run records a would_fire without calling on_appear;
  * targets are independent.
"""
from __future__ import annotations

import json

import pytest

from core.edge_watcher import ABSENT, PRESENT, UNREACHABLE, EdgeWatcher, ProbeState


class _Script:
    """Probe that replays a per-target script of states (or exceptions)."""

    def __init__(self, script):
        self._script = {t: list(v) for t, v in script.items()}

    def __call__(self, target):
        item = self._script[target].pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _run(script, dry_run=False):
    fired = []
    probe = _Script(script)
    w = EdgeWatcher(probe, fired.append, dry_run=dry_run)
    records = []
    longest = max(len(v) for v in script.values())
    for _ in range(longest):
        for target, steps in script.items():
            if probe._script[target]:
                rec = w.poll(target)
                if rec is not None:
                    records.append(rec)
    return fired, records, w


def test_tri_state_is_explicit_enum_not_truthiness():
    assert isinstance(PRESENT, ProbeState)
    assert {PRESENT, ABSENT, UNREACHABLE} == set(ProbeState)
    with pytest.raises(ValueError):
        EdgeWatcher(None, None).observe("t", True)


def test_start_with_state_present_never_fires():
    fired, records, _ = _run({"g": [PRESENT, PRESENT, PRESENT]})
    assert fired == []
    assert records == []


def test_absent_to_present_fires_exactly_once():
    fired, records, _ = _run({"g": [ABSENT, PRESENT, PRESENT, PRESENT]})
    assert fired == ["g"]
    assert len(records) == 1
    assert records[0]["action"] == "fire"


def test_unreachable_to_present_does_not_fire():
    fired, _, _ = _run({"g": [UNREACHABLE, PRESENT, PRESENT]})
    assert fired == []


def test_reconnect_mid_watch_reprimes_silently():
    # primed absent, link drops, comes back with the state present: not an edge
    fired, _, _ = _run({"g": [ABSENT, UNREACHABLE, PRESENT]})
    assert fired == []


def test_present_absent_present_fires_once():
    fired, _, _ = _run({"g": [PRESENT, ABSENT, PRESENT, PRESENT]})
    assert fired == ["g"]


def test_probe_raising_is_unreachable_no_fire_no_escape():
    fired, records, w = _run({"g": [ABSENT, RuntimeError("relay down"), PRESENT]})
    assert fired == []
    assert records == []
    assert w.last_state("g") is PRESENT


def test_probe_returning_garbage_is_unreachable():
    fired, _, w = _run({"g": [ABSENT, "yes", PRESENT]})
    assert fired == []


def test_dry_run_records_would_fire_without_calling_action():
    fired, records, _ = _run({"g": [ABSENT, PRESENT]}, dry_run=True)
    assert fired == []
    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "would_fire"
    assert rec["dry_run"] is True
    assert rec["target"] == "g"
    assert rec["prev"] == "absent"
    assert rec["state"] == "present"
    json.dumps(rec)


def test_fire_record_is_json_serialisable():
    _, records, _ = _run({"g": [ABSENT, PRESENT]})
    assert json.loads(json.dumps(records[0]))["action"] == "fire"


def test_multiple_targets_are_independent():
    fired, _, w = _run({
        "a": [PRESENT, PRESENT, PRESENT],      # startup present: silent
        "b": [ABSENT, PRESENT, PRESENT],       # genuine appear: fires
        "c": [UNREACHABLE, PRESENT, PRESENT],  # reconnect: silent
    })
    assert fired == ["b"]
    assert w.is_primed("a") and w.is_primed("b") and w.is_primed("c")


def test_on_appear_raising_is_recorded_not_escaped():
    def boom(_t):
        raise RuntimeError("action failed")
    w = EdgeWatcher(None, boom)
    w.observe("g", ABSENT)
    rec = w.observe("g", PRESENT)
    assert rec["action"] == "fire"
    assert "action failed" in rec["error"]
    json.dumps(rec)
