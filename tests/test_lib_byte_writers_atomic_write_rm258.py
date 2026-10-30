"""RM-258 residual: two lib/ byte caches go through core.polled_json.

``lib/icons/downloader.py`` (icon PNGs) and ``lib/game_data/fetch.py`` (the
game-data pipeline's raw body cache) each hand-rolled ``_atomic_write_bytes``:
a FIXED ``<dest>.tmp`` scratch name, ``write_bytes`` and a bare rename. Two
defects followed, each pinned below for both modules:

  1. The fixed scratch name is shared by every writer of the same target, and
     anything already sitting at ``<dest>.tmp`` (a leftover, a directory) broke
     every write. core.polled_json uses a per-writer scratch name.
  2. A bare rename raised on the first transient ``PermissionError`` (WinError
     5, a reader holding the destination open) and left the scratch file
     behind (LEDGER 1350 noted that residue class for the icon writer).
     core.polled_json retries with a bounded backoff and never leaves its
     scratch file.

The bytes written are unchanged (the payload is binary either way). The guard
``tests/test_atomic_write_guard_rm258_rm261.py`` carried both modules in
``_LIB_UNCLASSIFIED``; the conversion drops them from that baseline.

Every test here is platform-portable: the transient failure is a monkeypatched
``os.replace``, never a held Windows handle.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import lib.game_data.fetch as gd_fetch
import lib.icons.downloader as dl
from core import polled_json

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\r\n" * 8

WRITERS = [
    pytest.param(dl._atomic_write_bytes, id="icons"),
    pytest.param(gd_fetch._atomic_write_bytes, id="game_data"),
]
MODULES = [
    pytest.param(dl, id="icons"),
    pytest.param(gd_fetch, id="game_data"),
]


@pytest.mark.parametrize("write", WRITERS)
def test_the_writer_puts_the_exact_bytes_on_disk(write, tmp_path):
    target = tmp_path / "sub" / "x.png"
    write(target, PNG)
    assert target.read_bytes() == PNG
    assert sorted(p.name for p in target.parent.iterdir()) == ["x.png"]


@pytest.mark.parametrize("write", WRITERS)
def test_a_leftover_at_the_old_fixed_scratch_name_does_not_block_the_write(write, tmp_path):
    """The old writers always used ``<dest>.tmp``; a directory squatting on
    that name made every write fail. A per-writer scratch name is unaffected."""
    target = tmp_path / "x.png"
    (tmp_path / "x.png.tmp").mkdir()
    write(target, PNG)
    assert target.read_bytes() == PNG


@pytest.mark.parametrize("write", WRITERS)
def test_a_transient_permission_error_on_replace_is_retried(write, tmp_path, monkeypatch):
    target = tmp_path / "x.png"
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
    write(target, PNG)
    assert target.read_bytes() == PNG
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.png"]


@pytest.mark.parametrize("write", WRITERS)
def test_an_exhausted_replace_leaves_the_target_and_no_scratch(write, tmp_path, monkeypatch):
    target = tmp_path / "x.png"
    target.write_bytes(b"old")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        write(target, PNG)
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.png"]


@pytest.mark.parametrize("mod", MODULES)
def test_the_module_does_not_hand_roll_the_rename(mod):
    """Source pin: the writer is core.polled_json's, not a local re-roll."""
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in src
    assert ".replace(path)" not in src
    assert '".tmp"' not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert mod._atomic_write_bytes is polled_json.atomic_write_bytes
