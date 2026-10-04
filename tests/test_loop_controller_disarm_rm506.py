"""RM-506: `control/STOP` is a cycle-level brake that the next launch deletes; a
DURABLE disarm must survive a `main()` startup.

Decision (recorded in ops/loop/loop_controller.py): STOP keeps its meaning
(unlinked at startup so a self-restart is not blocked by its own prior halt),
and `control/DISARMED` is the separate durable sentinel main() never deletes.
The load-bearing half is that the sentinel SURVIVES startup.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def lc(monkeypatch, tmp_path):
    mod = importlib.import_module("ops.loop.loop_controller")
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    monkeypatch.setattr(mod, "CTL", tmp_path)
    mod._test_lines = lines
    return mod


def test_reset_on_start_never_names_the_durable_sentinel(lc):
    assert lc.DISARM_NAME not in lc.RESET_ON_START
    assert "STOP" in lc.RESET_ON_START


def test_durable_sentinel_survives_startup_reset(lc, tmp_path: Path):
    (tmp_path / "STOP").write_text("x", encoding="utf-8")
    (tmp_path / lc.DISARM_NAME).write_text("operator", encoding="utf-8")
    lc.reset_control_files()
    assert not (tmp_path / "STOP").exists(), "STOP stays the cycle-level brake"
    assert (tmp_path / lc.DISARM_NAME).exists()


def test_main_refuses_to_start_when_disarmed_and_touches_nothing(lc, monkeypatch,
                                                                 tmp_path: Path):
    (tmp_path / lc.DISARM_NAME).write_text("operator", encoding="utf-8")
    (tmp_path / "STOP").write_text("halt", encoding="utf-8")

    def _no_claim():
        raise AssertionError("claim_repo must not run while DISARMED")

    monkeypatch.setattr(lc, "claim_repo", _no_claim)
    with pytest.raises(SystemExit) as exc:
        lc.main()
    assert exc.value.code == lc.EXIT_DISARMED
    assert (tmp_path / lc.DISARM_NAME).exists()
    assert (tmp_path / "STOP").exists(), "a disarmed launch must not clear STOP"


def test_wait_for_halts_on_the_durable_sentinel(lc, tmp_path: Path, monkeypatch):
    (tmp_path / lc.DISARM_NAME).write_text("operator", encoding="utf-8")
    monkeypatch.setitem(lc.CFG, "poll_sec", 0)
    import time
    with pytest.raises(SystemExit) as exc:
        lc.wait_for(tmp_path / "never", time.time() + 5)
    assert exc.value.code == lc.EXIT_DISARMED


def test_no_sentinel_means_no_disarm(lc, tmp_path: Path):
    assert lc.disarm_path() is None
    lc.halt_if_disarmed("probe")  # must not exit
