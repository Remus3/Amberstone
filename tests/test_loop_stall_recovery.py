# arch: tests for loop_controller WP-I3 stall recovery directive | section=tests | frozen=no
"""WP-I3: on the FIRST cycle-deadline breach the controller injects a one-shot
/diagnose stall-recovery directive (no /clear) that self-terminates by running the
done_sentinel final step, then extends the deadline once before any hard STOP.
stall_recovery_directive() is the pure, unit-testable core. Loaded by file path so the
module's argv-driven CFG load does not need a real launch (the .json-suffix guard makes
import-under-pytest fall back to the real config.json)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CTRL = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_stall", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recovery_is_callable(lc):
    assert callable(lc.stall_recovery_directive)


def test_recovery_has_cycle_header_for_ahk_skip(lc):
    # The AHK bridge skips line 1 (the CYCLE header) and types the rest.
    assert lc.stall_recovery_directive(7).splitlines()[0] == "CYCLE=7"


def test_recovery_invokes_diagnose_and_done_sentinel(lc):
    out = lc.stall_recovery_directive(3)
    assert "/diagnose" in out
    assert "done_sentinel.py" in out  # must always produce a claude.done either way


def test_recovery_does_not_clear(lc):
    # No /clear - the wedged session's context is exactly what /diagnose must inspect.
    assert "/clear" not in lc.stall_recovery_directive(1)


def test_recovery_is_single_typed_line(lc):
    # Exactly 2 lines: the skipped CYCLE header + one /diagnose directive line, so the
    # bridge types a single message (no accidental multi-send).
    assert len(lc.stall_recovery_directive(9).splitlines()) == 2


def test_recovery_is_ascii_clean(lc):
    out = lc.stall_recovery_directive(2)
    banned = {0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D}
    assert not [c for c in out if ord(c) in banned]
    assert out.isascii()
