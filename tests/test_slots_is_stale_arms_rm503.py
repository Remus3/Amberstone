"""RM-503: assert WHICH ARM of `slots.is_stale` fired, not only the verdict.

The only prior guard on the age arm wrote a live pid at 100x `stale_after` and
asserted stale. MEASURED 2026-10-02 it was green under the current age arm, under
a candidate hard ceiling at 4x, and under a mutant ceiling at 1x - one
assertion, three states, and its arm attribution moved silently. The cheap
discriminator is the `pid_alive` call count: the age arm returns before any
liveness probe, the pid arm makes exactly one.

These tests pin the age just past `stale_after` (1.5x), below any plausible
ceiling, so the AGE arm is identified. `ops/loop/slots.py` itself is a
byte-identical cross-repo file and is not edited here.

Re-pinned 2026-10-04 (joint-round C4): slots.py gained HARD_STALE_MULTIPLE
(2.0). A READABLE lock with a live pid is no longer reclaimed on age alone
between stale_after and stale_after * HARD_STALE_MULTIPLE - that band now
reaches the pid arm. The age arm survives only as the hard ceiling, pinned
just past it (HARD_STALE_MULTIPLE + 0.5) with zero liveness probes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_slots():
    spec = importlib.util.spec_from_file_location(
        "rc_loop_slots_rm503_under_test", ROOT / "ops" / "loop" / "slots.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


slots = _load_slots()
STALE_AFTER = 100.0


def _lock(tmp_path: Path, age: float) -> Path:
    path = tmp_path / "0.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - age}),
                    encoding="utf-8")
    return path


def _counting_pid_alive(monkeypatch, verdict: bool = True) -> list[int]:
    calls: list[int] = []

    def fake(pid: int) -> bool:
        calls.append(pid)
        return verdict

    monkeypatch.setattr(slots, "pid_alive", fake)
    return calls


def test_live_holder_just_past_stale_after_is_kept_by_the_pid_arm(tmp_path, monkeypatch):
    """C4: below the hard ceiling a live holder keeps its slot; age alone is
    not evidence the holder is gone, so pid_alive is consulted exactly once."""
    assert 1.5 < slots.HARD_STALE_MULTIPLE
    calls = _counting_pid_alive(monkeypatch, verdict=True)
    assert slots.is_stale(_lock(tmp_path, 1.5 * STALE_AFTER), STALE_AFTER) is False
    assert calls == [os.getpid()]


def test_dead_holder_just_past_stale_after_is_stale_by_the_pid_arm(tmp_path, monkeypatch):
    calls = _counting_pid_alive(monkeypatch, verdict=False)
    assert slots.is_stale(_lock(tmp_path, 1.5 * STALE_AFTER), STALE_AFTER) is True
    assert calls == [os.getpid()]


def test_live_holder_just_past_the_hard_ceiling_is_stale_by_the_age_arm(tmp_path, monkeypatch):
    """The fail-open ceiling: a reused pid must never deadlock the bucket."""
    calls = _counting_pid_alive(monkeypatch, verdict=True)
    age = (slots.HARD_STALE_MULTIPLE + 0.5) * STALE_AFTER
    assert slots.is_stale(_lock(tmp_path, age), STALE_AFTER) is True
    assert calls == [], "ceiling arm must fire BEFORE any liveness probe"


def test_live_holder_inside_stale_after_reaches_the_pid_arm(tmp_path, monkeypatch):
    """Control: below stale_after the verdict comes from pid_alive, once."""
    calls = _counting_pid_alive(monkeypatch, verdict=True)
    assert slots.is_stale(_lock(tmp_path, 0.5 * STALE_AFTER), STALE_AFTER) is False
    assert calls == [os.getpid()]


def test_dead_holder_inside_stale_after_is_stale_by_the_pid_arm(tmp_path, monkeypatch):
    calls = _counting_pid_alive(monkeypatch, verdict=False)
    assert slots.is_stale(_lock(tmp_path, 0.5 * STALE_AFTER), STALE_AFTER) is True
    assert calls == [os.getpid()]
