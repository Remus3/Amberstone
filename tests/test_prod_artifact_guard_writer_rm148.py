"""RM-148: the session hermeticity guard must tell a TEST writing a prod path
from the LIVE RC rewriting its own state.

Both directions are asserted, as the row requires:
- TRUE POSITIVE: a test (this process) writes a guarded prod path -> still
  fails, live RC or not.
- FALSE POSITIVE (the bug): a live RC rewrites `data/vision_state.json` with
  no in-process write -> passes.
And the strict CI behaviour is kept: with no live RC every change fails.
"""
from __future__ import annotations

import json
import os

import pytest

from tests import conftest as C

_VS = "data/vision_state.json"
_SENTINEL = "agents/state/lockfile.sentinel"


def _sizes(**over):
    base = {rel: 100 for rel in C._PROD_ARTIFACT_GUARD}
    base.update(over)
    return base


def test_live_rc_rewrite_without_in_process_write_is_excused():
    before, after = _sizes(), _sizes(**{_VS: 90})
    assert C._classify_prod_changes(before, after, set(), live_rc=2228) == []


def test_in_process_write_fails_even_with_live_rc():
    before, after = _sizes(), _sizes(**{_VS: 90})
    out = C._classify_prod_changes(before, after, {_VS}, live_rc=2228)
    assert out == [_VS + " 100->90"]


def test_no_live_rc_every_change_fails():
    before, after = _sizes(), _sizes(**{_VS: 90})
    assert C._classify_prod_changes(before, after, set(), live_rc=None) == [
        _VS + " 100->90"]


def test_non_rc_owned_artifact_is_never_excused():
    assert _SENTINEL not in C._LIVE_RC_OWNED
    before, after = _sizes(), _sizes(**{_SENTINEL: None})
    assert C._classify_prod_changes(before, after, set(), live_rc=2228) == [
        _SENTINEL + " 100->None"]


def test_recorder_sees_real_in_process_writes(tmp_path, monkeypatch):
    """End to end through the real audit hook: watch a tmp file as if it
    were a guarded artifact and write it the ways a test might."""
    target = tmp_path / "vision_state.json"
    target.write_text("{}", encoding="ascii")
    rec = C._PROD_WRITES
    monkeypatch.setitem(rec.watched, C._norm(target), _VS)
    was_active = rec.active
    saved = set(rec.written)
    rec.active = True
    try:
        rec.written.discard(_VS)
        target.read_text(encoding="ascii")
        assert _VS not in rec.written, "a READ must not count as a write"

        target.write_text("{1}", encoding="ascii")
        assert _VS in rec.written

        rec.written.discard(_VS)
        tmp = tmp_path / "x.tmp"
        tmp.write_text("{}", encoding="ascii")
        os.replace(tmp, target)
        assert _VS in rec.written, "atomic tmp+replace must be attributed"

        rec.written.discard(_VS)
        fd = os.open(target, os.O_WRONLY | os.O_APPEND)
        os.close(fd)
        assert _VS in rec.written, "os.open for append must be attributed"
    finally:
        rec.written.clear()
        rec.written.update(saved)
        rec.active = was_active


def test_recorder_inactive_records_nothing(tmp_path, monkeypatch):
    rec = C._ProdWriteRecorder()
    target = tmp_path / "f"
    monkeypatch.setitem(rec.watched, C._norm(target), "data/f")
    rec.on_event("open", (str(target), "w", 0))
    assert rec.written == set()
    rec.active = True
    rec.on_event("open", (str(target), "w", 0))
    assert rec.written == {"data/f"}


def test_live_rc_probe_never_names_this_process(monkeypatch, tmp_path):
    fake_root = tmp_path
    (fake_root / "ops" / "runtime").mkdir(parents=True)
    (fake_root / "ops" / "runtime" / "health.json").write_text(
        json.dumps({"pid": os.getpid()}), encoding="ascii")
    monkeypatch.setattr(C, "_REPO_ROOT", fake_root)
    assert C._live_rc_pid() is None


@pytest.mark.parametrize("pid", [0, -1, 2 ** 31 - 2])
def test_live_rc_probe_dead_or_invalid_pid(monkeypatch, tmp_path, pid):
    (tmp_path / "ops" / "runtime").mkdir(parents=True)
    (tmp_path / "ops" / "runtime" / "health.json").write_text(
        json.dumps({"pid": pid}), encoding="ascii")
    monkeypatch.setattr(C, "_REPO_ROOT", tmp_path)
    assert C._live_rc_pid() is None
