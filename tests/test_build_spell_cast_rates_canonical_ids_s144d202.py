"""S144-D-202: scripts/build_spell_cast_rates.py keys rows by the DDragon id.

The generator reads ``participants.champion_name`` from the rewind DB, which
carries the Match-V5 ``championName``. For one champion that string is not the
DDragon id: Match-V5 says ``FiddleSticks``, DDragon (and so every Daemon Slayer
roster key) says ``Fiddlesticks``. The generator wrote the Match-V5 string
verbatim, so the shipped table keys that champion as ``FiddleSticks`` and
``ult_rates.get_spell_casts_per_sec("Fiddlesticks", ...)`` never finds its own
row: it silently reads the file-level ``global_fallback`` instead of the
measured median (measured 2026-11-09 on the shipped table: W 0.0324 fallback
vs 0.0731 measured for SR).

The fix canonicalises each name onto the DDragon id set before aggregating
(exact id first, then a case-insensitive match); an unknown name passes
through unchanged, and a missing roster file degrades to pass-through with a
stderr warning, never a crash. Re-keying the already-shipped rows changes
served DS output, so it is a separate Tier-2 step (see the S144-D-203 guard,
which pins the shipped offender).

Every test drives the real main() over a small synthetic rewind DB: synthetic
match ids, no real game data.
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

from scripts import build_spell_cast_rates as bscr  # noqa: E402

_ROSTER = {
    "type": "champion",
    "data": {
        "Fiddlesticks": {"id": "Fiddlesticks", "name": "Fiddlesticks"},
        "MonkeyKing": {"id": "MonkeyKing", "name": "Wukong"},
        "Veigar": {"id": "Veigar", "name": "Veigar"},
    },
}


def _make_db(path: pathlib.Path, rows: list[tuple[str, int]]) -> None:
    """``rows`` = (champion_name, count); every row is an SR game."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE matches (match_id TEXT, game_duration_s REAL, queue_id INTEGER)")
        conn.execute(
            "CREATE TABLE participants (match_id TEXT, champion_name TEXT, "
            "spell1_casts INTEGER, spell2_casts INTEGER, spell3_casts INTEGER, "
            "spell4_casts INTEGER)")
        n = 0
        for name, count in rows:
            for _ in range(count):
                mid = f"SYNTH_{n}"
                n += 1
                conn.execute("INSERT INTO matches VALUES (?, ?, ?)",
                             (mid, 1200.0, 420))
                conn.execute("INSERT INTO participants VALUES (?, ?, ?, ?, ?, ?)",
                             (mid, name, 120, 60, 30, 6))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def run(tmp_path, monkeypatch):
    out = tmp_path / "out" / "spell_cast_rates.json"
    roster = tmp_path / "ddragon_champions.json"
    roster.write_text(json.dumps(_ROSTER), encoding="utf-8")
    monkeypatch.setattr(bscr, "OUTPUT", out)
    monkeypatch.setattr(bscr, "ROOT", tmp_path)
    monkeypatch.setattr(bscr, "DDRAGON_CHAMPIONS", roster)

    def _run(rows: list[tuple[str, int]]) -> dict:
        db = tmp_path / "rewind_history.db"
        if db.exists():
            db.unlink()
        _make_db(db, rows)
        monkeypatch.setattr(bscr, "DB_PATH", db)
        assert bscr.main() == 0
        return json.loads(out.read_text(encoding="utf-8"))["by_champ_mode"]

    return _run


def test_match_v5_casing_is_written_under_the_ddragon_id(run):
    table = run([("FiddleSticks", 6)])
    assert "FiddleSticks" not in table
    assert set(table) == {"Fiddlesticks"}
    # 6 SR samples clear MIN_SAMPLES, so the mode bucket is kept too.
    assert set(table["Fiddlesticks"]) == {"global", "SR"}


def test_both_spellings_pool_into_one_row(run):
    # 3 + 3 rows: each spelling alone is under MIN_SAMPLES for the SR bucket;
    # pooled they clear it, which proves they were merged BEFORE the reduce.
    assert bscr.MIN_SAMPLES == 5
    table = run([("FiddleSticks", 3), ("Fiddlesticks", 3)])
    assert set(table) == {"Fiddlesticks"}
    assert "SR" in table["Fiddlesticks"]


def test_an_exact_id_and_an_unknown_name_pass_through(run):
    table = run([("MonkeyKing", 5), ("Veigar", 5), ("Testchamp", 5)])
    assert set(table) == {"MonkeyKing", "Veigar", "Testchamp"}


def test_a_missing_roster_file_degrades_to_pass_through(run, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bscr, "DDRAGON_CHAMPIONS", tmp_path / "absent.json")
    table = run([("FiddleSticks", 5)])
    assert set(table) == {"FiddleSticks"}
    assert "roster" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"data": 7}',
                                     b'{"data": {"X": 3, "Y": {"id": 9}}}'])
def test_a_junk_roster_file_never_raises(run, monkeypatch, tmp_path, payload):
    bad = tmp_path / "bad_roster.json"
    bad.write_bytes(payload)
    monkeypatch.setattr(bscr, "DDRAGON_CHAMPIONS", bad)
    table = run([("FiddleSticks", 5)])
    assert set(table) == {"FiddleSticks"}


def test_the_shipped_roster_maps_the_match_v5_spelling():
    """The real roster file the script reads by default resolves the
    offender - a guard that the default path points at a real DDragon list."""
    ids = bscr._ddragon_ids_by_casefold(bscr.DDRAGON_CHAMPIONS)
    assert len(ids) > 150
    assert bscr._canon_champ("FiddleSticks", ids) == "Fiddlesticks"
    assert bscr._canon_champ("Fiddlesticks", ids) == "Fiddlesticks"
