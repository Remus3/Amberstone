"""RM-1128: scripts/build_spell_cast_rates.py writes through core.polled_json.

The script regenerates the tracked data/daemon_slayer/spell_cast_rates.json,
which the Daemon Slayer :8860 process reads IN-PROCESS while it is up
(agents/daemon_slayer/ult_rates.py _load_spells, the get_spell_casts_per_sec
lookup; the read is lazy, so a DS process can be opening the file during a
regeneration). The old writer hand-rolled the swap:

  1. a fixed ``spell_cast_rates.json.tmp`` scratch derived from the
     destination alone, shared with any second writer of the file;
  2. a BARE ``Path.replace`` with no WinError 5 retry, so a DS read holding
     the file for a millisecond failed the whole regeneration;
  3. no fsync before the rename, and the scratch left behind when the rename
     failed.

It now delegates to ``core.polled_json.atomic_write_bytes``. The bytes it
writes are unchanged (json.dumps indent 2, ASCII, LF, no trailing newline;
tests/test_ds_writers_lf_rm448.py keeps the text-mode newline pin and
tests/test_json_authored_glyph_hygiene.py the ASCII pin). scripts/ sits outside
the repo-wide guard tests/test_atomic_write_guard_rm258_rm261.py, so this module
carries its own source pin. Every test drives the real main() over a small
synthetic rewind DB (hand-written champion names and match ids, no real game
data), and the transient failure is a monkeypatched ``os.replace``, never a
held handle.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402
from scripts import build_spell_cast_rates as bscr  # noqa: E402

_ORIGINAL = b'{"previous": true}\n'


def _make_db(path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE matches (match_id TEXT, game_duration_s REAL, queue_id INTEGER)")
        conn.execute(
            "CREATE TABLE participants (match_id TEXT, champion_name TEXT, "
            "spell1_casts INTEGER, spell2_casts INTEGER, spell3_casts INTEGER, "
            "spell4_casts INTEGER)")
        for i in range(6):
            mid = f"SYNTH_{i}"
            conn.execute("INSERT INTO matches VALUES (?, ?, ?)",
                         (mid, 1200.0 + i * 60, 450 if i % 2 else 420))
            conn.execute("INSERT INTO participants VALUES (?, ?, ?, ?, ?, ?)",
                         (mid, "Testchamp", 100 + i, 40, 30, 8))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def target(tmp_path, monkeypatch):
    db = tmp_path / "rewind_history.db"
    _make_db(db)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    path = out_dir / "spell_cast_rates.json"
    path.write_bytes(_ORIGINAL)
    monkeypatch.setattr(bscr, "DB_PATH", db)
    monkeypatch.setattr(bscr, "OUTPUT", path)
    # main() prints OUTPUT.relative_to(ROOT); root the fixture under tmp_path.
    monkeypatch.setattr(bscr, "ROOT", tmp_path)
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
    assert bscr.main() == 0
    doc = json.loads(target.read_bytes().decode("utf-8"))
    assert "Testchamp" in doc["by_champ_mode"]
    assert calls["n"] == 2
    assert sorted(p.name for p in target.parent.iterdir()) == ["spell_cast_rates.json"]


def test_an_exhausted_replace_keeps_the_target_and_no_scratch(target, monkeypatch):
    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        bscr.main()
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in target.parent.iterdir()) == ["spell_cast_rates.json"]


def test_two_runs_use_distinct_per_writer_scratch_names(target, monkeypatch):
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    assert bscr.main() == 0
    assert bscr.main() == 0
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith("spell_cast_rates.json.") and n.endswith(".tmp")
               and n != "spell_cast_rates.json.tmp" for n in seen)


def test_the_written_bytes_are_unchanged(target):
    assert bscr.main() == 0
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert not raw.endswith(b"\n")
    assert raw == json.dumps(json.loads(raw.decode("ascii")), indent=2).encode("ascii")


def test_main_does_not_hand_roll_the_rename():
    """Source pin: main() delegates instead of renaming itself."""
    src = pathlib.Path(bscr.__file__).read_text(encoding="utf-8")
    assert 'OUTPUT.suffix + ".tmp"' not in src
    assert "tmp.replace(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
