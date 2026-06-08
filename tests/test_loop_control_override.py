# arch: tests for loop_controller one-shot directive override | section=tests | frozen=no
"""The loop controller consumes a one-shot operator directive override.

POST /api/loop-control writes ops/loop/control/directive_override.md; the
controller's consume_directive_override() reads + unlinks it so it applies to
exactly one cycle, taking precedence over the gemini director. Absent => None
(byte-identical loop). Loaded by file path so the module's argv-driven CFG load
does not need a real launch (the .json-suffix guard makes import-under-pytest
fall back to the real config.json).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CTRL = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_absent_returns_none(lc, tmp_path):
    assert lc.consume_directive_override(tmp_path) is None


def test_present_returns_text_and_unlinks(lc, tmp_path):
    (tmp_path / "directive_override.md").write_text("Refactor X.", encoding="utf-8")
    out = lc.consume_directive_override(tmp_path)
    assert out == "Refactor X."
    # one-shot: the file is consumed so a second read is None
    assert not (tmp_path / "directive_override.md").exists()
    assert lc.consume_directive_override(tmp_path) is None


def test_empty_file_returns_none_and_unlinks(lc, tmp_path):
    (tmp_path / "directive_override.md").write_text("   \n", encoding="utf-8")
    assert lc.consume_directive_override(tmp_path) is None
    assert not (tmp_path / "directive_override.md").exists()


def test_helper_is_callable(lc):
    assert callable(lc.consume_directive_override)
