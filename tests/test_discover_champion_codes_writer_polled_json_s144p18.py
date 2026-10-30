"""RM-1129: scripts/discover_champion_codes.py goes through core.polled_json.

The script rewrites the TRACKED planner code maps
data/meta/tft_set<N>_champion_codes.json, which tools/gated_tft15_planner.py
(``codes_for``) and tools/gated_tft_lt02r.py (``CODES_REL``) read while a
gated TFT drain runs. Its ``atomic_write_bytes`` hand-rolled the swap:

  1. a fixed ``<name>.tmp`` scratch derived from the destination alone, so two
     runs writing one file share it;
  2. a BARE ``Path.replace`` with no WinError 5 retry, so a reader holding the
     destination for a millisecond failed the run;
  3. no fsync before the rename, and a scratch left behind when the rename
     failed.

It now delegates to ``core.polled_json.atomic_write_bytes``. The bytes are
unchanged (``encode``: indent 2, sorted keys, LF, no trailing newline;
tests/test_tft_set18_champion_codes_lt03.py pins the tracked file to it).
scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py (one-shot generator tree), so
this module carries its own source pin. Every test is platform-portable: the
transient failure is a monkeypatched ``os.replace``, never a held handle, and
no test touches a League client (the passive path runs on a GET-only stub).
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
from scripts import discover_champion_codes as dcc  # noqa: E402

_NAME = "tft_set18_champion_codes.json"
_ORIGINAL = b'{"previous": 1}'
_CODES = {"Kobuko": 1085, "Ahri": 1001}


def _write(target: pathlib.Path) -> None:
    dcc.atomic_write_bytes(target, dcc.encode(_CODES))


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    target = tmp_path / _NAME
    target.write_bytes(_ORIGINAL)
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    _write(target)
    assert json.loads(target.read_bytes()) == _CODES
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [_NAME]


def test_an_exhausted_replace_keeps_the_target_and_no_scratch(tmp_path, monkeypatch):
    target = tmp_path / _NAME
    target.write_bytes(_ORIGINAL)

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        _write(target)
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in tmp_path.iterdir()) == [_NAME]


def test_two_writes_of_one_file_use_distinct_per_writer_scratch_names(
        tmp_path, monkeypatch):
    target = tmp_path / _NAME
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    _write(target)
    _write(target)
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith(_NAME + ".") and n.endswith(".tmp")
               and n != _NAME + ".tmp" for n in seen)


def test_the_written_bytes_are_unchanged(tmp_path):
    """Same serialisation as before the move: indent 2, sorted, LF, no tail."""
    target = tmp_path / "data" / "meta" / _NAME
    _write(target)
    assert target.read_bytes() == json.dumps(
        _CODES, indent=2, sort_keys=True).encode("utf-8")
    assert b"\r" not in target.read_bytes()


def test_the_writer_does_not_hand_roll_the_rename():
    """Source pin: the script delegates instead of renaming itself."""
    src = pathlib.Path(dcc.__file__).read_text(encoding="utf-8")
    assert 'path.name + ".tmp"' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert dcc.atomic_write_bytes is polled_json.atomic_write_bytes
