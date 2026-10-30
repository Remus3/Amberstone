"""RM-1127: scripts/patch_champion.py save_builds writes through core.polled_json.

save_builds rewrites the tracked data/meta_build/aram_champion_builds.json,
which RC reads IN-PROCESS while it is up (coaches/aram_coach.py
_load_build_note, coaches/arena_coach.py, coaches/brawl_coach.py,
coaches/_arena_item_advisor.py _ARAM_BUILDS_PATH). The old writer hand-rolled
the swap:

  1. a fixed ``aram_champion_builds.json.tmp`` scratch derived from the
     destination alone, shared with any second writer of the file;
  2. a BARE ``Path.replace`` with no WinError 5 retry, so a coach reading the
     file for a millisecond failed the whole --apply run;
  3. no fsync before the rename, and the scratch left behind when the rename
     failed.

It now delegates to ``core.polled_json.atomic_write_bytes``. The bytes it
writes are unchanged (json.dumps indent 2, ensure_ascii False, UTF-8, LF, no
trailing newline; tests/test_tracked_writer_lf_bytes.py pins LF under a
forced-CRLF harness). scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py, so this module carries its own
source pin. Every test is platform-portable: the transient failure is a
monkeypatched ``os.replace``, never a held handle.
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
from scripts import patch_champion as pc  # noqa: E402

_ORIGINAL = b'{"previous": true}\n'
_PAYLOAD = {"Ahri": {"aram_tier": "S", "build_note": "Luden's Echo - \u00e9"}}


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "aram_champion_builds.json"
    path.write_bytes(_ORIGINAL)
    monkeypatch.setattr(pc, "BUILDS_FILE", path)
    return path


def test_a_transient_permission_error_on_replace_is_retried(target, monkeypatch):
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    pc.save_builds(_PAYLOAD)
    assert json.loads(target.read_bytes().decode("utf-8")) == _PAYLOAD
    assert calls["n"] == 2
    assert sorted(p.name for p in target.parent.iterdir()) == [
        "aram_champion_builds.json"]


def test_an_exhausted_replace_keeps_the_target_and_no_scratch(target, monkeypatch):
    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        pc.save_builds(_PAYLOAD)
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in target.parent.iterdir()) == [
        "aram_champion_builds.json"]


def test_two_saves_use_distinct_per_writer_scratch_names(target, monkeypatch):
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    pc.save_builds(_PAYLOAD)
    pc.save_builds(_PAYLOAD)
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith("aram_champion_builds.json.") and n.endswith(".tmp")
               and n != "aram_champion_builds.json.tmp" for n in seen)


def test_the_written_bytes_are_unchanged(target):
    pc.save_builds(_PAYLOAD)
    expected = json.dumps(_PAYLOAD, indent=2, ensure_ascii=False).encode("utf-8")
    assert target.read_bytes() == expected


def test_save_builds_does_not_hand_roll_the_rename():
    """Source pin: save_builds delegates instead of renaming itself."""
    src = pathlib.Path(pc.__file__).read_text(encoding="utf-8")
    assert 'with_suffix(".json.tmp")' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
