"""Lane 8 Headless-True-Audit, session 134 cycle 5 - coaches/tft_coach.py.

Second pass over the TFT facade (the first was lane 8 cycle 34, guarded by
tests/test_tft_coach_lane8_cycle34.py). Each defect below was measured
against the call graph before it was fixed.

S1  `reset_state` carried a worker branch that poked SIX private attributes
    of two other modules (`_engine.reset_state()`, `_live._known_augments`,
    `_live._last_write`, `_live._last_round`) inside `except Exception: pass`.
    It is unreachable in production: the only callers are `__init__` (before
    app/_game_lifecycle.py wires the worker) and `shutdown` (which drops the
    worker first). When a caller did reach it, it reset only part of the live
    analysis - not `_last_placement`, `_round_before`, the scan flags or the
    stage gate - so a REVERT could restore a round from the previous game.
    The worker is built fresh per game, so the facade has no state of it to
    reset; the branch is gone and this test pins that a wired worker is left
    alone.

S2  `_force_refresh_all` was the retired Tk right-click callback. It had no
    caller (force scans go through data/force_scan.json, core/hotkeys.py and
    dashboard/_writers.py), and its two `except Exception: pass` guards made
    any failure invisible. Removed; the census test below holds the facade
    at zero silent broad excepts.

S3  `shutdown` logged "shutdown complete" and returned None even when the
    blanking write failed, so the lobby kept the last game's board while the
    log read clean. It now returns the reset verdict and says when the
    files were NOT cleared.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import coaches.tft_coach as mod
from coaches.tft_coach import Coach

_SRC = Path(mod.__file__)


class _EngineStub:
    def __init__(self):
        self.resets = 0
        self.shutdowns = 0
        self._last_call = 99.0

    def reset_state(self):
        self.resets += 1


class _WorkerStub:
    def __init__(self):
        self._engine = _EngineStub()
        self._live = SimpleNamespace(
            _known_augments=["Augment A"],
            _last_write={"stage_round": "3-2"},
            _last_round=(3, 2),
            _last_placement="Jinx D7",
        )
        self.shutdowns = 0
        self.scans = 0

    def shutdown(self):
        self.shutdowns += 1

    def force_scan(self):
        self.scans += 1


def _coach(tmp_path: Path) -> Coach:
    return Coach(tmp_path / "tft_coaching_data.json")


def test_reset_state_leaves_a_wired_workers_state_alone(tmp_path):
    """S1: the facade owns the data files only, never the worker's internals."""
    coach = _coach(tmp_path)
    worker = _WorkerStub()
    coach.set_worker(worker)

    assert coach.reset_state() is True

    assert worker._engine.resets == 0
    assert worker._engine._last_call == 99.0
    assert worker._live._known_augments == ["Augment A"]
    assert worker._live._last_write == {"stage_round": "3-2"}
    assert worker._live._last_round == (3, 2)
    assert worker._live._last_placement == "Jinx D7"
    assert worker.shutdowns == 0
    assert worker.scans == 0


def test_shutdown_drops_the_worker_without_shutting_it_down(tmp_path):
    """Characterization: app/_game_lifecycle.py owns the worker lifecycle."""
    coach = _coach(tmp_path)
    worker = _WorkerStub()
    coach.set_worker(worker)

    coach.shutdown()

    assert coach._worker is None
    assert worker.shutdowns == 0


def test_shutdown_returns_true_and_blanks_the_files(tmp_path):
    coach = _coach(tmp_path)
    live = tmp_path / "tft_live_data.json"
    live.write_text('{"mode": "tft_live", "stage_round": "4-1"}', encoding="utf-8")

    assert coach.shutdown() is True

    assert '"stage_round": ""' in live.read_text(encoding="utf-8")


def test_shutdown_reports_a_failed_clear(tmp_path, monkeypatch, caplog):
    """S3: a failed blank is not a clean shutdown."""
    coach = _coach(tmp_path)
    monkeypatch.setattr(mod, "safe_write", lambda *_a, **_k: False)

    with caplog.at_level(logging.INFO, logger="rc.coaches.tft"):
        ok = coach.shutdown()

    assert ok is False
    lines = [r.getMessage() for r in caplog.records]
    assert any("NOT cleared" in m and r.levelno >= logging.WARNING
               for m, r in zip(lines, caplog.records))
    assert "TFT Coach facade shutdown complete" not in lines


def test_right_click_refresh_entry_point_is_gone():
    """S2: the retired Tk callback has no caller and must not come back."""
    assert not hasattr(Coach, "_force_refresh_all")


def _silent_broad_handlers(tree: ast.AST) -> list[int]:
    """Line of every `except Exception` / bare `except` whose body is `pass`."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        broad = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
        silent = all(isinstance(stmt, ast.Pass) for stmt in node.body)
        if broad and silent:
            out.append(node.lineno)
    return out


def test_facade_has_no_silent_broad_except():
    """S1 + S2 census: four `except Exception: pass` sites, now zero."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    assert _silent_broad_handlers(tree) == []


def test_census_helper_sees_a_silent_handler():
    """Positive control: the census would catch the shape it guards against."""
    tree = ast.parse("try:\n    x = 1\nexcept Exception:  # noqa: BLE001\n    pass\n")
    assert _silent_broad_handlers(tree) == [3]


@pytest.mark.parametrize("name", ["set_worker", "reset_state", "shutdown", "submit_state"])
def test_lifecycle_api_the_app_calls_still_exists(name):
    """app/_game_lifecycle.py calls set_worker / shutdown; the base API keeps the rest."""
    assert callable(getattr(Coach, name))
