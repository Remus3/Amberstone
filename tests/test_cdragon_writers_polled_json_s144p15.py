"""RM-1126: the two CommunityDragon TFT writers go through core.polled_json.

scripts/fetch_cdragon_tft.py ``write_atomic`` rewrites the TRACKED reduced
extract data/meta/tft_set<N>_cdragon.json, which RC reads in-process
(tft/tft_set.py ``load_cdragon`` / ``roster``, tft/tft_final_board.py) while it
is up. scripts/tft_patch_delta.py ``_write_bytes_atomic`` fills the raw payload
cache under the gitignored data/tft/cdragon_raw/. Both hand-rolled the swap:

  1. a fixed ``<name>.tmp`` scratch derived from the destination alone, so two
     runs writing one file share it;
  2. a BARE ``Path.replace`` with no WinError 5 retry, so a reader holding the
     destination for a millisecond failed the run;
  3. no fsync before the rename, and a scratch left behind when the rename
     failed.

They now delegate to ``core.polled_json.atomic_write_bytes``. The bytes they
write are unchanged (tests/test_fetch_cdragon_tft.py pins ASCII + LF).
scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py (one-shot generator tree), so
this module carries its own source pin. Every test is platform-portable: the
transient failure is a monkeypatched ``os.replace``, never a held handle.
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
from scripts import fetch_cdragon_tft as fct  # noqa: E402
from scripts import tft_patch_delta as tpd  # noqa: E402

_ORIGINAL = b'{"previous": true}\n'
_OBJ = {"set": 18, "name": "synthetic"}


def _write_extract(path):
    fct.write_atomic(path, _OBJ)


def _write_cache(path):
    tpd._write_bytes_atomic(path, b'{"raw": 1}\n')


WRITERS = [
    pytest.param(_write_extract, "tft_set18_cdragon.json", id="fetch_cdragon_tft"),
    pytest.param(_write_cache, "en_us.json", id="tft_patch_delta"),
]


@pytest.mark.parametrize("write, name", WRITERS)
def test_a_transient_permission_error_on_replace_is_retried(
        tmp_path, monkeypatch, write, name):
    target = tmp_path / name
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
    write(target)
    assert target.read_bytes() != _ORIGINAL
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


@pytest.mark.parametrize("write, name", WRITERS)
def test_an_exhausted_replace_keeps_the_target_and_no_scratch(
        tmp_path, monkeypatch, write, name):
    target = tmp_path / name
    target.write_bytes(_ORIGINAL)

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        write(target)
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


@pytest.mark.parametrize("write, name", WRITERS)
def test_two_writes_of_one_file_use_distinct_per_writer_scratch_names(
        tmp_path, monkeypatch, write, name):
    target = tmp_path / name
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    write(target)
    write(target)
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith(name + ".") and n.endswith(".tmp")
               and n != name + ".tmp" for n in seen)


def test_the_extract_bytes_are_unchanged(tmp_path):
    """Same serialisation as before the move: ASCII, indent 1, one LF tail."""
    target = tmp_path / "tft_set18_cdragon.json"
    fct.write_atomic(target, {"name": "caf\u00e9"})
    assert target.read_bytes() == (
        json.dumps({"name": "caf\u00e9"}, indent=1, ensure_ascii=True)
        + "\n").encode("ascii")


@pytest.mark.parametrize("module", [fct, tpd], ids=["fetch_cdragon_tft", "tft_patch_delta"])
def test_the_writer_does_not_hand_roll_the_rename(module):
    """Source pin: the script delegates instead of renaming itself."""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    assert 'path.name + ".tmp"' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
