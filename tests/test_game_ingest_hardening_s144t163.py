"""True-audit s144t163: agents/agent2_backend/game_ingest.py hardening.

The ingester's own contract (``ingest_game_summary`` docstring) is that it
never raises on an ordinary skip condition and only raises ``IngestError``
on a hard DB failure; ``_parse_kda`` says "Never raises". Each test below
pins one way a junk post-game payload used to break that contract, or to
write a nonsense row into a Phase 3 mode DB.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest

import agents.agent2_backend.game_ingest as gi


@pytest.fixture
def aram_db(tmp_path: Path, monkeypatch) -> Path:
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(gi, "DB_DIR", tmp_path)
    dbs.init_mode("aram")
    return tmp_path / "aram.db"


def _payload(**over):
    base = {
        "game_mode": "ARAM",
        "champion": "Ahri",
        "game_time_s": 1200,
        "finished_at": "2026-04-22T12:00:00+00:00",
    }
    base.update(over)
    return base


def _rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT champion, started_at, ended_at, duration_sec, win,"
            " kills, deaths, assists FROM matches"
        ).fetchall()
    finally:
        conn.close()


# -- payload shape --------------------------------------------------------

@pytest.mark.parametrize("bad", [None, [], "ARAM", 7, ["champion"]])
def test_non_dict_payload_is_a_skip_not_a_crash(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(bad)
    assert result["inserted"] is False
    assert _rows(aram_db) == []


# -- game_time_s ----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "abc", "12:00", {"s": 1}, [1200], float("nan"), float("inf"),
    -float("inf"), True, 10 ** 12,
])
def test_junk_game_time_is_a_skip_not_a_crash(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(game_time_s=bad))
    assert result["inserted"] is False
    assert "game_time_s" in result["reason"]
    assert _rows(aram_db) == []


def test_negative_game_time_never_writes_a_start_after_the_end(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(game_time_s=-600))
    assert result["inserted"] is False
    assert _rows(aram_db) == []


def test_float_and_numeric_string_game_time_still_ingest(aram_db: Path) -> None:
    r1 = gi.ingest_game_summary(_payload(game_time_s=1234.7))
    r2 = gi.ingest_game_summary(_payload(champion="Jinx", game_time_s="900"))
    assert r1["inserted"] is True and r1["duration_sec"] == 1234
    assert r2["inserted"] is True and r2["duration_sec"] == 900


def test_zero_game_time_keeps_the_phantom_reason(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(game_time_s=0))
    assert result["inserted"] is False
    assert "phantom" in result["reason"]


# -- champion -------------------------------------------------------------

@pytest.mark.parametrize("bad", [{"name": "Ahri"}, ["Ahri"], 103, "   ", True])
def test_non_string_or_blank_champion_is_missing(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(champion=bad))
    assert result["inserted"] is False
    assert result["reason"] == "missing champion"
    assert _rows(aram_db) == []


@pytest.mark.parametrize("bad", [
    json.loads('"\\ud800"'), json.loads('"Ahri\\udfff"'), "Ah\x00ri",
    "unknown", "NULL", "None", "A" * 100_000,
])
def test_unbindable_or_placeholder_champion_is_missing(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(champion=bad))
    assert result["inserted"] is False
    assert result["reason"] == "missing champion"
    assert _rows(aram_db) == []


@pytest.mark.parametrize("good", ["Kai'Sa", "Nunu & Willump", "Bel'Veth"])
def test_real_punctuated_champion_names_still_ingest(aram_db: Path, good) -> None:
    assert gi.ingest_game_summary(_payload(champion=good))["inserted"] is True


def test_huge_int_fields_never_raise_out_of_a_reason_or_rating(aram_db: Path) -> None:
    huge = 10 ** 5000
    r1 = gi.ingest_game_summary(_payload(game_time_s=huge))
    assert r1["inserted"] is False and "game_time_s" in r1["reason"]
    assert len(r1["reason"]) < 200
    r2 = gi.ingest_game_summary(_payload(game_mode=huge))
    assert r2["inserted"] is False and "game_mode" in r2["reason"]
    r3 = gi.ingest_game_summary(_payload(stats={"x": huge}, rating="A"))
    assert r3["inserted"] is True
    r4 = gi.ingest_game_summary(_payload(game_time_s="x" * 500))
    assert r4["inserted"] is False and len(r4["reason"]) < 200


def test_padded_champion_is_stored_stripped(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(champion="  Ahri \n"))
    assert result["inserted"] is True
    assert result["champion"] == "Ahri"
    assert _rows(aram_db)[0][0] == "Ahri"


# -- game_mode ------------------------------------------------------------

def test_padded_game_mode_maps() -> None:
    assert gi._select_mode_db(" aram\n") == "aram"


@pytest.mark.parametrize("bad", [["ARAM"], {"ARAM": 1}, 450, None, ""])
def test_non_string_game_mode_maps_to_none(bad) -> None:
    assert gi._select_mode_db(bad) is None


# -- finished_at ----------------------------------------------------------

@pytest.mark.parametrize("bad", [1714000000, 1714000000.5, ["x"], {"t": 1}])
def test_non_string_finished_at_falls_back_to_now(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(finished_at=bad))
    assert result["inserted"] is True
    assert result["ended_at"].endswith("+00:00")


def test_non_utc_finished_at_is_stored_in_utc(aram_db: Path) -> None:
    result = gi.ingest_game_summary(
        _payload(finished_at="2026-04-22T14:00:00+02:00"))
    assert result["ended_at"] == "2026-04-22T12:00:00+00:00"
    assert result["started_at"] == "2026-04-22T11:40:00+00:00"


def test_naive_finished_at_is_read_as_utc(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(finished_at="2026-04-22T12:00:00"))
    assert result["ended_at"] == "2026-04-22T12:00:00+00:00"


def test_offset_variant_of_one_game_is_still_a_duplicate(aram_db: Path) -> None:
    r1 = gi.ingest_game_summary(_payload(finished_at="2026-04-22T12:00:00+00:00"))
    r2 = gi.ingest_game_summary(_payload(finished_at="2026-04-22T14:00:00+02:00"))
    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert "duplicate" in r2["reason"]
    assert len(_rows(aram_db)) == 1


# -- win ------------------------------------------------------------------

@pytest.mark.parametrize("bad", [2, -1, 0.5, 7.0, float("inf"), float("nan"), "2"])
def test_explicit_win_outside_zero_one_is_not_recorded(bad) -> None:
    assert gi._infer_win({"win": bad}) is None


def test_explicit_win_outside_zero_one_still_reads_the_action_string() -> None:
    assert gi._infer_win({"win": 5, "action": "Victory"}) == 1


@pytest.mark.parametrize("good,expected", [
    (True, 1), (False, 0), (1, 1), (0, 0), (1.0, 1), ("1", 1), (" 0 ", 0),
])
def test_explicit_win_zero_one_forms_still_pass(good, expected) -> None:
    assert gi._infer_win({"win": good}) == expected


def test_infinite_explicit_win_does_not_crash_ingest(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(win=float("inf")))
    assert result["inserted"] is True
    assert result["win"] is None


# -- kda ------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"k": float("inf"), "d": 1, "a": 2},
    {"k": float("nan"), "d": 1, "a": 2},
])
def test_non_finite_kda_never_raises(bad) -> None:
    k, d, a = gi._parse_kda(bad)
    assert k is None and (d, a) == (1, 2)


@pytest.mark.parametrize("bad", ["-1/2/3", {"k": -1, "d": 2, "a": 3}])
def test_negative_kda_component_is_rejected(bad) -> None:
    assert gi._parse_kda(bad)[0] is None


def test_bool_and_fractional_kda_components_are_rejected() -> None:
    assert gi._parse_kda({"k": True, "d": 2.5, "a": 3}) == (None, None, 3)


def test_integral_float_and_string_kda_components_still_parse() -> None:
    assert gi._parse_kda({"k": 4.0, "d": "2", "a": 3}) == (4, 2, 3)
    assert gi._parse_kda(" 10 / 3 / 15 ") == (10, 3, 15)


def test_infinite_kda_does_not_crash_ingest(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(kda={"k": math.inf, "d": 1, "a": 2}))
    assert result["inserted"] is True
    assert _rows(aram_db)[0][5] is None


@pytest.mark.parametrize("bad", [
    "99999999999999999999/0/0",
    "9" * 5000 + "/0/0",
    {"k": 10 ** 30, "d": 0, "a": 0},
    {"k": 1e300, "d": 0, "a": 0},
    {"k": 10_001, "d": 0, "a": 0},
])
def test_oversized_kda_is_null_not_an_sqlite_overflow(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(kda=bad))
    assert result["inserted"] is True
    assert _rows(aram_db)[0][5] is None


def test_kda_at_the_cap_still_parses() -> None:
    assert gi._parse_kda({"k": 10_000, "d": 0, "a": 0}) == (10_000, 0, 0)


# -- finished_at near the datetime range edges ----------------------------

@pytest.mark.parametrize("bad", [
    "0001-01-01T00:10:00",
    "0001-01-01T00:00:00+05:00",
    "9999-12-31T23:59:59-05:00",
    "1999-12-31T23:00:00+00:00",
])
def test_out_of_band_finished_at_reads_as_now(aram_db: Path, bad) -> None:
    result = gi.ingest_game_summary(_payload(finished_at=bad))
    assert result["inserted"] is True
    assert result["ended_at"].endswith("+00:00")
    assert int(result["ended_at"][:4]) >= 2026


# -- rating fields --------------------------------------------------------

def test_non_json_rating_field_does_not_crash_ingest(aram_db: Path) -> None:
    result = gi.ingest_game_summary(
        _payload(stats={"tags": {"a"}, "n": 1}, rating=b"A"))
    assert result["inserted"] is True
    conn = sqlite3.connect(aram_db)
    try:
        stored = conn.execute("SELECT final_rating_json FROM matches").fetchone()[0]
    finally:
        conn.close()
    # Only the non-JSON value becomes text; the rest of the dict survives.
    assert json.loads(stored)["stats"]["n"] == 1


def _deep_list(depth: int) -> list:
    root: list = []
    node = root
    for _ in range(depth):
        child: list = []
        node.append(child)
        node = child
    return root


def test_deeply_nested_rating_field_does_not_crash_ingest(aram_db: Path) -> None:
    result = gi.ingest_game_summary(
        _payload(stats=_deep_list(100_000), rating="A", label="B"))
    assert result["inserted"] is True
    conn = sqlite3.connect(aram_db)
    try:
        stored = conn.execute("SELECT final_rating_json FROM matches").fetchone()[0]
    finally:
        conn.close()
    loaded = json.loads(stored)
    assert loaded["rating"] == "A" and loaded["label"] == "B"
    assert loaded["stats"] == "<list>"


def test_deep_value_in_a_skip_reason_does_not_crash() -> None:
    assert gi._short_repr(_deep_list(100_000)) == "<list>"


def test_rating_json_matches_plain_json_dumps_for_normal_fields() -> None:
    fields = {"rating": "A", "stats": {"n": 1, "xs": [1, 2]}, "notes": None}
    assert gi._rating_json(fields) == json.dumps(fields)
    assert gi._rating_json({}) is None


def test_non_string_dict_key_in_rating_does_not_crash_ingest(aram_db: Path) -> None:
    result = gi.ingest_game_summary(_payload(stats={(1, 2): 3}, rating="A"))
    assert result["inserted"] is True
    conn = sqlite3.connect(aram_db)
    try:
        stored = conn.execute("SELECT final_rating_json FROM matches").fetchone()[0]
    finally:
        conn.close()
    assert '"rating": "A"' in stored


# -- dedup query errors ---------------------------------------------------

class _FirstQueryEmptyThenFail:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_a, **_k):
        self.calls += 1
        if self.calls == 1:
            return self
        raise sqlite3.OperationalError("database is locked")

    def fetchone(self):
        return None


def test_window_dedup_query_error_is_not_swallowed() -> None:
    conn = _FirstQueryEmptyThenFail()
    with pytest.raises(sqlite3.OperationalError):
        gi._already_ingested(conn, "2026-04-22T12:00:00+00:00", "Ahri",
                             duration_sec=60)


def test_window_dedup_db_error_surfaces_as_ingest_error(aram_db: Path,
                                                         monkeypatch) -> None:
    def _boom(conn, *a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(gi, "_already_ingested", _boom)
    with pytest.raises(gi.IngestError):
        gi.ingest_game_summary(_payload())


# -- connection lifetime --------------------------------------------------

def test_every_ingest_closes_its_connection(aram_db: Path, monkeypatch) -> None:
    opened: list = []
    real_connect = sqlite3.connect

    class _Tracked:
        def __init__(self, conn) -> None:
            self._conn = conn
            self.closed = False

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __enter__(self):
            self._conn.__enter__()
            return self

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

        def close(self) -> None:
            self.closed = True
            self._conn.close()

    def _connect(*a, **k):
        t = _Tracked(real_connect(*a, **k))
        opened.append(t)
        return t

    monkeypatch.setattr(gi.sqlite3, "connect", _connect)
    gi.ingest_game_summary(_payload())          # insert path
    gi.ingest_game_summary(_payload())          # duplicate path
    assert len(opened) == 2
    assert all(t.closed for t in opened)
