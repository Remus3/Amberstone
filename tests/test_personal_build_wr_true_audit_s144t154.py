"""True-audit hardening of core.personal_build_wr (s144 true-audit cycle 154,
RM-1908..RM-1916).

Every case below failed on the pre-audit module:

- RM-1908 min_games <= 0 over an empty sample raised ZeroDivisionError and a
  non-int floor raised TypeError, against a "never raises" docstring.
- RM-1909 an unknown result (tracked_win NULL / 2 / text) was counted as a
  LOSS in the baseline and in every item's games.
- RM-1910 a non-str mode raised AttributeError.
- RM-1911 champion True was read as champion id 1, a blank champion matched
  rows with an empty tracked_champion_name, a non-ASCII digit string was read
  as an id, and a numeric string past 64 bits made a sqlite OverflowError that
  surfaced as read_error (a transient verdict, recomputed every poll).
- RM-1912 an item id stored as a REAL (3031.0) or as padded text missed the
  metadata and was dropped; one item twice in a final build counted two games.
- RM-1913 a participant row duplicated by a re-scrape (the participants table
  has no unique key) counted the match twice.
- RM-1914 one malformed items.json entry threw away ALL item metadata, a
  corrupt newest items.json did not fall back to an older patch, and finding no
  items.json at all was CACHED as a success forever (and, after the first
  rewrite, a pathologically nested items.json raised RecursionError).
- RM-1915 the DB was opened read-write, so a file that vanished between the
  exists() check and connect() was re-created as an empty database (and, after
  the first rewrite, a Windows device name such as CON hung the read-only open).
- RM-1916 equal-lift items and equal-count modal builds were ordered by row
  insertion order (the SELECT has no ORDER BY).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

from core import personal_build_wr as pbw
from core.failed_load_gate import FailedLoadGate

_PATCH = "16.21.1"
_ITEMS = {
    "3031": {"name": "Infinity Edge", "gold": {"total": 3400}},
    "3071": {"name": "Black Cleaver", "gold": {"total": 3000}},
    "3036": {"name": "Lord Dominik's Regards", "gold": {"total": 3000}},
    "3009": {"name": "Boots of Swiftness", "gold": {"total": 1000}},
    "1055": {"name": "Doran's Blade", "gold": {"total": 450}},
}


@pytest.fixture(autouse=True)
def _meta(tmp_path, monkeypatch):
    root = tmp_path / "dd"
    (root / _PATCH).mkdir(parents=True)
    (root / _PATCH / "items.json").write_text(
        json.dumps({"data": _ITEMS}), encoding="utf-8")
    monkeypatch.setattr(pbw, "_DDRAGON_ROOT", root)
    monkeypatch.setattr(pbw, "_META_GATE", FailedLoadGate())
    pbw.reset_cache()
    yield root
    pbw.reset_cache()


def _db(path: Path, games: list[dict], *, typed: bool = True,
        dup_participants: bool = False) -> Path:
    """games = [{win, items, champ_name, champ_id, map_id, dur, mid}].

    typed=False declares the item and win columns with NO type, so SQLite
    keeps the raw stored value (REAL, padded TEXT) instead of coercing it.
    """
    it = "INTEGER" if typed else ""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, "
        "tracked_champion_name TEXT, tracked_champion_id INTEGER, "
        f"tracked_team_id INTEGER, tracked_win {it}, map_id INTEGER, "
        "game_duration_s INTEGER)")
    conn.execute(
        "CREATE TABLE participants (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "match_id TEXT, champion_id INTEGER, team_id INTEGER, "
        + ", ".join(f"item{i} {it}" for i in range(6)) + ")")
    for i, g in enumerate(games):
        mid = g.get("mid", f"SYN_{i}")
        cid = g.get("champ_id", 999)
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
            (mid, g.get("champ_name", "TestChamp"), cid, 100, g["win"],
             g.get("map_id", 11), g.get("dur", 1800)))
        items = (list(g["items"]) + [0] * 6)[:6]
        for _ in range(2 if dup_participants else 1):
            conn.execute(
                "INSERT INTO participants (match_id, champion_id, team_id, "
                "item0, item1, item2, item3, item4, item5) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (mid, cid, 100, *items))
    conn.commit()
    conn.close()
    return path


def _strict(payload: dict) -> None:
    json.dumps(payload, allow_nan=False)


# -- RM-1908 ---------------------------------------------------------------

@pytest.mark.parametrize("floor", [0, -3])
def test_non_positive_min_games_over_an_empty_sample_never_raises(tmp_path, floor):
    db = _db(tmp_path / "r.db", [])
    r = pbw.compute_personal_build("TestChamp", db_path=db, min_games=floor)
    assert r["confidence"] == "insufficient"
    assert r["games"] == 0
    _strict(r)


@pytest.mark.parametrize("floor", [None, "8", 2.5, True, float("nan")])
def test_a_junk_floor_falls_back_to_the_default(tmp_path, floor):
    db = _db(tmp_path / "r.db",
             [{"win": 1, "items": [3031]} for _ in range(5)])
    r = pbw.compute_personal_build("TestChamp", db_path=db, min_games=floor,
                                   min_item_games=floor)
    # 5 games is below DEFAULT_MIN_GAMES (8): the default floor applied.
    assert r["confidence"] == "insufficient"


# -- RM-1909 ---------------------------------------------------------------

@pytest.mark.parametrize("unknown", [None, 2, -1])
def test_an_unknown_result_is_not_a_loss(tmp_path, unknown):
    games = ([{"win": 1, "items": [3031]} for _ in range(10)]
             + [{"win": 0, "items": [3031]} for _ in range(10)]
             + [{"win": unknown, "items": [3031]} for _ in range(5)])
    r = pbw.compute_personal_build("TestChamp", db_path=_db(tmp_path / "r.db", games))
    assert r["games"] == 20
    assert r["win_rate"] == 0.5
    ie = {it["item_id"]: it for it in r["items"]}[3031]
    assert ie["games"] == 20 and ie["wins"] == 10


def test_a_text_result_is_unknown_not_a_win(tmp_path):
    games = ([{"win": 1, "items": [3031]} for _ in range(10)]
             + [{"win": 0, "items": [3031]} for _ in range(10)]
             + [{"win": "abc", "items": [3031]} for _ in range(5)])
    db = _db(tmp_path / "r.db", games, typed=False)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    assert r["games"] == 20
    assert r["win_rate"] == 0.5


# -- RM-1910 ---------------------------------------------------------------

@pytest.mark.parametrize("mode", [1, b"sr", ["sr"], 2.0])
def test_a_non_str_mode_is_bad_mode_and_never_raises(tmp_path, mode):
    db = _db(tmp_path / "r.db", [{"win": 1, "items": [3031]}] * 20)
    r = pbw.compute_personal_build("TestChamp", mode, db_path=db)
    assert r["confidence"] == "bad_mode"
    _strict(r)


@pytest.mark.parametrize("mode", [" SR ", None, ""])
def test_a_padded_or_absent_mode_still_resolves(tmp_path, mode):
    games = [{"win": 1, "items": [3031], "mid": f"M{i}"} for i in range(20)]
    db = _db(tmp_path / "r.db", games)
    r = pbw.compute_personal_build("TestChamp", mode, db_path=db)
    assert r["mode"] == "sr"
    assert r["games"] == 20


# -- RM-1911 ---------------------------------------------------------------

def _annie(tmp_path, name="Annie"):
    games = [{"win": 1, "items": [3031], "champ_id": 1, "champ_name": name}
             for _ in range(20)]
    return _db(tmp_path / "r.db", games)


@pytest.mark.parametrize("champion", [True, False, None, 1.0, b"Annie", ["Annie"]])
def test_a_non_name_non_id_champion_is_bad_champion(tmp_path, champion):
    r = pbw.compute_personal_build(champion, db_path=_annie(tmp_path))
    assert r["confidence"] == "bad_champion"
    assert r["games"] == 0
    _strict(r)


@pytest.mark.parametrize("champion", ["", "   ", "\t"])
def test_a_blank_champion_never_matches_a_blank_tracked_name(tmp_path, champion):
    r = pbw.compute_personal_build(champion, db_path=_annie(tmp_path, name=""))
    assert r["confidence"] == "bad_champion"
    assert r["games"] == 0


def test_a_lone_surrogate_champion_is_bad_champion(tmp_path):
    # Found by the cycle-154 verifier: sqlite3 cannot bind a lone surrogate.
    champion = "Ann" + chr(0xD800) + "ie"
    r = pbw.compute_personal_build(champion, db_path=_annie(tmp_path))
    assert r["confidence"] == "bad_champion"


def test_a_non_ascii_digit_string_is_not_a_champion_id(tmp_path):
    # int() accepts Arabic-Indic digits; the champion id lookup must not.
    r = pbw.compute_personal_build("\u0661", db_path=_annie(tmp_path))
    assert r["games"] == 0
    assert r["champion_id"] is None


def test_a_numeric_string_past_64_bits_is_a_name_lookup_not_a_read_error(tmp_path):
    r = pbw.compute_personal_build("9" * 40, db_path=_annie(tmp_path))
    assert r["confidence"] == "insufficient"
    assert r["champion_id"] is None


def test_an_int_past_the_id_range_is_bad_champion(tmp_path):
    r = pbw.compute_personal_build(10 ** 30, db_path=_annie(tmp_path))
    assert r["confidence"] == "bad_champion"


def test_a_padded_name_and_numeric_id_still_resolve(tmp_path):
    db = _annie(tmp_path)
    assert pbw.compute_personal_build("  annie ", db_path=db)["games"] == 20
    r = pbw.compute_personal_build(" 1 ", db_path=db)
    assert r["games"] == 20 and r["champion_id"] == 1 and r["champion"] == "1"


# -- RM-1912 ---------------------------------------------------------------

@pytest.mark.parametrize("stored", [3031.0, " 3031", "3031"])
def test_an_item_id_stored_as_real_or_text_is_still_scored(tmp_path, stored):
    games = [{"win": 1, "items": [stored, 3009]} for _ in range(20)]
    db = _db(tmp_path / "r.db", games, typed=False)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    ids = {it["item_id"] for it in r["items"]}
    assert 3031 in ids
    assert all(isinstance(i, int) for i in r["most_common_build"])
    assert sorted(r["most_common_build"]) == [3009, 3031]


@pytest.mark.parametrize("stored", [-3031, 3031.5, float("inf"), b"3031", "3O31"])
def test_a_junk_item_id_is_skipped(tmp_path, stored):
    games = [{"win": 1, "items": [stored, 3009]} for _ in range(20)]
    db = _db(tmp_path / "r.db", games, typed=False)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    assert [it["item_id"] for it in r["items"]] == [3009]
    _strict(r)


def test_a_huge_digit_text_item_slot_is_skipped_not_a_read_error(tmp_path):
    # Found by the cycle-154 verifier: int() raises ValueError on a digit
    # string past the 4300-digit limit.
    games = [{"win": 1, "items": ["9" * 5000, 3031]} for _ in range(10)]
    db = _db(tmp_path / "r.db", games, typed=False)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    assert r["games"] == 10
    assert [it["item_id"] for it in r["items"]] == [3031]


def test_a_leading_zero_id_is_the_same_id(tmp_path):
    # Zeros are stripped before the digit-count cap, so padding is not junk.
    games = [{"win": 1, "items": ["0" * 20 + "3031"]} for _ in range(5)]
    games += [{"win": 1, "items": ["0003031"]} for _ in range(5)]
    db = _db(tmp_path / "r.db", games, typed=False)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    assert [it["item_id"] for it in r["items"]] == [3031]
    assert r["items"][0]["games"] == 10


def test_one_item_twice_in_a_build_is_one_game(tmp_path):
    games = [{"win": 1, "items": [3031, 3031, 3009]} for _ in range(10)]
    r = pbw.compute_personal_build("TestChamp", db_path=_db(tmp_path / "r.db", games))
    ie = {it["item_id"]: it for it in r["items"]}[3031]
    assert ie["games"] == 10 and ie["wins"] == 10
    assert sorted(r["most_common_build"]) == [3009, 3031]


# -- RM-1913 ---------------------------------------------------------------

def test_a_duplicated_participant_row_counts_the_match_once(tmp_path):
    games = ([{"win": 1, "items": [3031]} for _ in range(6)]
             + [{"win": 0, "items": [3031]} for _ in range(4)])
    db = _db(tmp_path / "r.db", games, dup_participants=True)
    r = pbw.compute_personal_build("TestChamp", db_path=db)
    assert r["games"] == 10
    assert r["win_rate"] == 0.6
    assert {it["item_id"]: it for it in r["items"]}[3031]["games"] == 10


# -- RM-1914 ---------------------------------------------------------------

def _write_items(root: Path, patch: str, text: str) -> None:
    (root / patch).mkdir(parents=True, exist_ok=True)
    (root / patch / "items.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("bad", [
    {"gold": {"total": "abc"}},
    {"gold": "3000"},
    {"gold": {"total": 1e400}},
    {"gold": {"total": [1]}},
    {"name": {"x": 1}, "gold": {"total": 3000}},
    "not-a-dict",
])
def test_one_bad_items_json_entry_keeps_every_other_entry(_meta, bad):
    data = dict(_ITEMS)
    data["9999"] = bad
    _write_items(_meta, _PATCH, json.dumps({"data": data}))
    meta = pbw._item_meta()
    assert meta["3031"] == {"name": "Infinity Edge", "gold": 3400}
    entry = meta.get("9999")
    if entry is not None:
        assert isinstance(entry["name"], str)
        assert isinstance(entry["gold"], int) and entry["gold"] >= 0


def test_a_nan_gold_total_is_zero_not_a_crash(_meta):
    _write_items(_meta, _PATCH,
                 '{"data": {"3031": {"name": "Infinity Edge", "gold": {"total": 3400}},'
                 ' "9998": {"name": "N", "gold": {"total": NaN}}}}')
    meta = pbw._item_meta()
    assert meta["3031"]["gold"] == 3400
    assert meta["9998"]["gold"] == 0


@pytest.mark.parametrize("newest", ["{ not json", "[]", '{"data": []}', '{"data": {}}'])
def test_an_unusable_newest_items_json_falls_back_to_an_older_patch(_meta, newest):
    _write_items(_meta, "16.22.1", newest)
    meta = pbw._item_meta()
    assert meta["3031"]["gold"] == 3400


def test_a_pathologically_nested_items_json_is_a_failure_not_a_raise(_meta, tmp_path):
    # Found by the cycle-154 verifier: json.loads recurses per nesting level,
    # so RecursionError escaped the (OSError, ValueError) parse guard.
    _write_items(_meta, _PATCH, "[" * 200000)
    assert pbw._item_meta() == {}
    assert pbw._META_CACHE is None
    games = [{"win": 1, "items": [3009]} for _ in range(10)]
    r = pbw.compute_personal_build("TestChamp", db_path=_db(tmp_path / "r.db", games))
    assert r["confidence"] == "thin"


def test_a_huge_digit_key_in_items_json_is_skipped_not_a_raise(_meta, tmp_path):
    # Found by the cycle-154 verifier: the same int() limit, outside every guard.
    data = dict(_ITEMS)
    data["9" * 5000] = {"name": "X", "gold": {"total": 3000}}
    _write_items(_meta, _PATCH, json.dumps({"data": data}))
    assert pbw._item_meta()["3031"]["gold"] == 3400
    games = [{"win": 1, "items": [3031]} for _ in range(10)]
    r = pbw.compute_personal_build("TestChamp", db_path=_db(tmp_path / "r.db", games))
    assert [it["item_id"] for it in r["items"]] == [3031]


def test_no_items_json_anywhere_is_a_failure_not_a_cached_empty(_meta):
    (_meta / _PATCH / "items.json").unlink()
    assert pbw._item_meta() == {}
    assert pbw._META_CACHE is None


# -- RM-1915 ---------------------------------------------------------------

def test_a_db_that_vanishes_after_the_exists_check_is_not_recreated(tmp_path, monkeypatch):
    ghost = tmp_path / "gone.db"
    real_is_file = Path.is_file
    monkeypatch.setattr(
        Path, "is_file", lambda self: True if self == ghost else real_is_file(self))
    r = pbw.compute_personal_build("TestChamp", db_path=ghost)
    monkeypatch.setattr(Path, "is_file", real_is_file)
    assert r["confidence"] == "read_error"
    assert not ghost.exists(), "a read opened the DB read-write and created it"


@pytest.mark.parametrize("db_path", [123, object()])
def test_a_junk_db_path_is_no_db_not_a_crash(db_path):
    r = pbw.compute_personal_build("TestChamp", db_path=db_path)
    assert r["confidence"] == "no_db"


@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform != "win32", reason="Windows device names")
@pytest.mark.parametrize("device", ["CON", "NUL", "con.db"])
def test_a_windows_device_name_is_no_db_not_a_hang(device):
    # Found by the cycle-154 verifier: Path("CON").exists() is True and a
    # read-only URI open of it blocked forever.
    r = pbw.compute_personal_build("TestChamp", db_path=device)
    assert r["confidence"] == "no_db"


def test_a_directory_is_no_db(tmp_path):
    assert pbw.compute_personal_build("TestChamp", db_path=tmp_path)["confidence"] == "no_db"


# -- RM-1916 ---------------------------------------------------------------

def _tie_games(first: int, second: int) -> list[dict]:
    a = [{"win": 1, "items": [first, 3009]} for _ in range(5)]
    b = [{"win": 1, "items": [second, 3009]} for _ in range(5)]
    return a + b


def test_ties_are_ordered_independently_of_row_order(tmp_path):
    one = pbw.compute_personal_build(
        "TestChamp", db_path=_db(tmp_path / "a.db", _tie_games(3071, 3036)))
    two = pbw.compute_personal_build(
        "TestChamp", db_path=_db(tmp_path / "b.db", _tie_games(3036, 3071)))
    assert one["most_common_build"] == two["most_common_build"]
    assert ([it["item_id"] for it in one["items"]]
            == [it["item_id"] for it in two["items"]])


# -- characterization: a well-formed sample is unchanged ----------------------

def test_well_formed_sample_numbers_are_unchanged(tmp_path):
    games = ([{"win": 1, "items": [3031, 3009, 1055]} for _ in range(12)]
             + [{"win": 0, "items": [3071, 3009]} for _ in range(6)]
             + [{"win": 0, "items": [3031, 3009]} for _ in range(2)])
    r = pbw.compute_personal_build("TestChamp", db_path=_db(tmp_path / "r.db", games))
    assert r["games"] == 20 and r["win_rate"] == 0.6 and r["confidence"] == "ok"
    by = {it["item_id"]: it for it in r["items"]}
    assert set(by) == {3031, 3071, 3009}            # 1055 is a component
    assert by[3031]["games"] == 14 and by[3031]["wins"] == 12
    assert by[3031]["lift"] > 0 > by[3071]["lift"]
    assert by[3009]["is_boots"] is True
    assert r["most_common_build"] == [3009, 3031]
    for it in r["items"]:
        assert all(math.isfinite(it[k]) for k in ("win_rate", "adj_win_rate", "lift"))
    _strict(r)
