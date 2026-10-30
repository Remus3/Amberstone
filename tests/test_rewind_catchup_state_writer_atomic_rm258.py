"""RM-258 family: the rewind catch-up state writer goes through core.polled_json.

``scripts/rewind_catchup.py`` ``save_state`` hand-rolled the atomic write: a
destination-derived ``<state>.tmp`` scratch (``with_suffix``), a text-mode
``Path.write_text`` and a BARE ``Path.replace``. Its output
``data/rewind_catchup.state.json`` is read at runtime while the catch-up runs:
``core/ops_panels.py`` (the ingest panel's ``catchup`` row, last_run_outcome /
last_run_at) re-reads it on every dashboard poll, and the weekly
``RC-RewindCatchup`` task writes it on every terminating path
(``record_run``). Three defects, each pinned below:

  1. A bare rename raised on the first transient ``PermissionError``
     (WinError 5, a reader holding the destination open) and failed the run.
     core.polled_json retries with a bounded backoff and never leaves its
     scratch file.
  2. Text mode on Windows rewrites every ``\\n`` as ``\\r\\n``, so the state
     landed on disk CRLF while the serialized payload was LF.
  3. The scratch name came from the destination alone, so two writers shared
     one ``rewind_catchup.state.tmp`` (the RM-261 collision).

The payload shape is unchanged: ``indent=2``, ASCII-escaped (json's default
``ensure_ascii``), no trailing newline.

scripts/ sits outside the repo-wide guard
``tests/test_atomic_write_guard_rm258_rm261.py`` (one-shot generator tree),
so this module carries its own source pin. Every test is platform-portable:
the transient failure is a monkeypatched ``os.replace``, never a held handle.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402
from scripts import rewind_catchup  # noqa: E402

_STATE = {
    "last_run_outcome": "ok",
    "last_run_at": 1700000000.0,
    "last_error": "caf" + chr(0xE9),
    "last_run_rc": 0,
}


def _expected_bytes(state: dict) -> bytes:
    return json.dumps(state, indent=2).encode("utf-8")


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    target = tmp_path / "rewind_catchup.state.json"
    monkeypatch.setattr(rewind_catchup, "STATE_PATH", target)
    return target


def test_state_bytes_are_lf_ascii_and_round_trip(state_path):
    rewind_catchup.save_state(_STATE)
    raw = state_path.read_bytes()
    assert b"\r" not in raw
    assert raw == _expected_bytes(_STATE)
    assert rewind_catchup.load_state() == _STATE


def test_a_transient_permission_error_on_replace_is_retried(state_path, monkeypatch):
    state_path.write_bytes(b"{}")
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    rewind_catchup.save_state(_STATE)
    assert state_path.read_bytes() == _expected_bytes(_STATE)
    assert calls["n"] == 2
    assert sorted(p.name for p in state_path.parent.iterdir()) == [state_path.name]


def test_an_exhausted_replace_leaves_the_old_state_and_no_scratch(state_path, monkeypatch):
    state_path.write_bytes(b"{}")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        rewind_catchup.save_state(_STATE)
    assert state_path.read_bytes() == b"{}"
    assert sorted(p.name for p in state_path.parent.iterdir()) == [state_path.name]


def test_the_state_writer_does_not_hand_roll_the_rename():
    """Source pin: save_state delegates instead of renaming itself."""
    src = pathlib.Path(rewind_catchup.__file__).read_text(encoding="utf-8")
    body = src.split("def save_state(", 1)[1].split("\ndef ", 1)[0]
    assert ".replace(" not in body
    assert "with_suffix(" not in body
    assert ".write_text(" not in body
    assert "atomic_write_text(" in body
