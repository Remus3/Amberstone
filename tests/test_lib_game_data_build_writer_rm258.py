"""RM-258 residual: lib/game_data/build.py `_dump` goes through core.polled_json.

``_dump`` writes the game-data pipeline's four build outputs (champions.json,
items.json, caveats.json, report.json). It hand-rolled a FIXED
``<dest>.tmp`` scratch name, ``write_text`` and a bare ``Path.replace``, so:

  1. anything already sitting at ``<dest>.tmp`` (a leftover, a directory)
     broke every write - core.polled_json uses a per-writer scratch name;
  2. one transient ``PermissionError`` (WinError 5, a reader holding the
     destination open) raised at once and orphaned the scratch file -
     core.polled_json retries with a bounded backoff and never leaves it.

The bytes on disk are unchanged: indent=1, sorted keys, ASCII-escaped, one
trailing LF and no CR (tests/test_game_data_reconcile.py
test_output_is_byte_stable_across_two_runs covers stability end to end).

Every test here is platform-portable: the transient failure is a monkeypatched
``os.replace``, never a held Windows handle. Non-ASCII test strings are built
with chr() so this file stays 7-bit ASCII.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.game_data.build as gd_build
from core import polled_json

E_ACUTE, EM_DASH, RSQUO = chr(0xE9), chr(0x2014), chr(0x2019)
OBJ = {"b": [1, 2], "a": {"name": "K" + E_ACUTE + "d"}}
EXPECTED = (json.dumps(OBJ, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def test_dump_writes_the_exact_ascii_lf_bytes(tmp_path):
    target = tmp_path / "sub" / "champions.json"
    gd_build._dump(target, OBJ)
    raw = target.read_bytes()
    assert raw == EXPECTED
    assert b"\r" not in raw
    assert sorted(p.name for p in target.parent.iterdir()) == ["champions.json"]


def test_non_ascii_strings_are_escaped_so_the_output_stays_pure_ascii(tmp_path):
    target = tmp_path / "x.json"
    payload = {EM_DASH: RSQUO}
    gd_build._dump(target, payload)
    raw = target.read_bytes()
    raw.decode("ascii")
    assert json.loads(raw) == payload


def test_a_leftover_at_the_old_fixed_scratch_name_does_not_block_the_write(tmp_path):
    """The old writer always used ``<dest>.tmp``; a directory squatting on
    that name made every write fail."""
    target = tmp_path / "items.json"
    (tmp_path / "items.json.tmp").mkdir()
    gd_build._dump(target, OBJ)
    assert target.read_bytes() == EXPECTED


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    target = tmp_path / "report.json"
    target.write_bytes(b"old")
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    gd_build._dump(target, OBJ)
    assert target.read_bytes() == EXPECTED
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json"]


def test_an_exhausted_replace_leaves_the_target_and_no_scratch(tmp_path, monkeypatch):
    target = tmp_path / "caveats.json"
    target.write_bytes(b"old")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        gd_build._dump(target, OBJ)
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["caveats.json"]


def test_the_module_does_not_hand_roll_the_rename():
    """Source pin: the writer is core.polled_json's, not a local re-roll."""
    src = Path(gd_build.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in src
    assert ".replace(path)" not in src
    assert '".tmp"' not in src
    assert ".write_text(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert gd_build.atomic_write_bytes is polled_json.atomic_write_bytes
