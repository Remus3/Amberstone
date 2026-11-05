"""True-audit s144 cycle 126 - core.duration_winrate hardening regressions.

One test per finding (RM-1603..247). Every db is synthetic: an in-memory
``matches`` table, or a tmp_path file when the own-connection path is under
test. No real rewind_history.db is read. ASCII-only authored content.
"""
from __future__ import annotations

import json
import math
import sqlite3

import pytest

from core import duration_winrate as dw

_SCHEMA = ("CREATE TABLE matches (map_id INTEGER, game_duration_s INTEGER, "
           "tracked_win INTEGER, tracked_champion_id INTEGER)")


def _fill(c, rows):
    c.execute(_SCHEMA)
    c.executemany(
        "INSERT INTO matches (map_id, game_duration_s, tracked_win, "
        "tracked_champion_id) VALUES (?,?,?,?)", rows)
    c.commit()
    return c


def _conn(rows):
    return _fill(sqlite3.connect(":memory:"), rows)


def _bucket(out, label="20-25m"):
    return {b["label"]: b for b in out["buckets"]}[label]


# RM-1603: a champion id outside SQLite's signed 64-bit range raised
# OverflowError out of a function documented "Never raises" (the route
# turned ?champion=99999999999999999999 into a 500). An out-of-range id is
# echoed as None so the payload stays JSON-safe even for a 5000-digit int
# (json.dumps of such an int raises past the 4300-digit limit).
@pytest.mark.parametrize("champ", [
    2 ** 63, -(2 ** 63) - 1, 10 ** 30,
    pytest.param(10 ** 5000, id="int-5000-digits"),
    pytest.param("9" * 5000, id="str-5000-digits"),
    "-" + "9" * 20, "9223372036854775808", 1e30])
def test_out_of_range_champion_never_raises(champ):
    rows = [(12, 1300, 1, 64)] * 6
    out = dw.compute_duration_winrate(mode="aram", champion=champ,
                                      conn=_conn(rows))
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["champion"] is None
    json.dumps(out)


@pytest.mark.parametrize("champ, want", [
    (2 ** 63 - 1, 2 ** 63 - 1),
    (-(2 ** 63), -(2 ** 63)),
    ("9223372036854775807", 2 ** 63 - 1),
    ("-9223372036854775808", -(2 ** 63)),
    ("0" * 30 + "64", 64),
    ("-0", 0),
    # Python's 4300-digit int() limit counts leading zeros.
    pytest.param("0" * 5000 + "64", 64, id="zero-padded-5000"),
    pytest.param("-" + "0" * 5000 + "1", -1, id="neg-zero-padded-5000"),
])
def test_int64_edge_champion_is_a_real_filter(champ, want):
    rows = [(12, 1300, 1, want)] * 6 + [(12, 1300, 0, 99)] * 6
    out = dw.compute_duration_winrate(mode="aram", champion=champ,
                                      conn=_conn(rows))
    assert out["n"] == 6
    assert out["champion"] == want


def test_out_of_range_champion_own_connection(tmp_path, monkeypatch):
    db = tmp_path / "rewind_history.db"
    c = sqlite3.connect(db)
    _fill(c, [(12, 1300, 1, 64)] * 6)
    c.close()
    monkeypatch.setattr(dw, "_REWIND_DB", db)
    out = dw.compute_duration_winrate(mode="aram", champion=2 ** 64)
    assert out["n"] == 0
    assert out["ok"] is True


# RM-1604: a bool champion was int()-ed into champion id 1 (True) or 0,
# and any other junk (text, NaN, a fractional float, an object) raised.
@pytest.mark.parametrize("champ", [True, False, "ashe", "", 1.5,
                                   float("nan"), float("inf"), object(),
                                   [64], b"64"])
def test_junk_champion_matches_nothing_and_never_raises(champ):
    rows = [(12, 1300, 1, 1)] * 6 + [(12, 1300, 1, 0)] * 6
    out = dw.compute_duration_winrate(mode="aram", champion=champ,
                                      conn=_conn(rows))
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["champion"] is None
    json.dumps(out)


@pytest.mark.parametrize("champ", [64, "64", " 64 ", 64.0])
def test_integral_champion_forms_still_filter(champ):
    rows = [(12, 1300, 1, 64)] * 6 + [(12, 1300, 0, 99)] * 6
    out = dw.compute_duration_winrate(mode="aram", champion=champ,
                                      conn=_conn(rows))
    assert out["n"] == 6
    assert out["champion"] == 64
    assert isinstance(out["champion"], int)
    assert not isinstance(out["champion"], bool)


# RM-1605: an unknown result (NULL or any value but 0 / 1) entered the
# bucket's denominator as a LOSS, deflating the win rate (RM-610: only a
# resolved result is counted).
def test_unknown_result_is_not_a_loss():
    rows = ([(12, 1300, 1, 1)] * 5 + [(12, 1300, 0, 1)] * 5
            + [(12, 1300, None, 1)] * 3 + [(12, 1300, 2, 1)] * 2
            + [(12, 1300, -1, 1)])
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    b = _bucket(out)
    assert b["games"] == 10
    assert b["wins"] == 5
    assert b["winrate"] == 50.0
    assert out["n"] == 10


def test_unknown_results_alone_never_reach_min_bucket_n():
    rows = [(12, 1300, None, 1)] * 10
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    assert out["n"] == 0
    assert _bucket(out)["winrate"] is None


# RM-1606: a non-string / unhashable mode raised TypeError at the
# ``mode not in MODE_MAPS`` membership test instead of falling back.
@pytest.mark.parametrize("mode", [[], {}, None, 12, b"sr", 1.5])
def test_junk_mode_falls_back_to_default(mode):
    rows = [(12, 1300, 1, 1)] * 6
    out = dw.compute_duration_winrate(mode=mode, conn=_conn(rows))
    assert out["mode"] == dw.DEFAULT_MODE
    assert out["n"] == 6


# RM-1607: _open_ro pasted the raw OS path into a sqlite URI, so a '#'
# or '%' in the checkout path truncated or percent-decoded it and the
# reader silently saw an empty corpus.
@pytest.mark.parametrize("dirname", ["a#b", "p%41q", "with space"])
def test_open_ro_survives_uri_metacharacters_in_path(tmp_path, monkeypatch,
                                                     dirname):
    d = tmp_path / dirname
    d.mkdir()
    db = d / "rewind_history.db"
    c = sqlite3.connect(db)
    _fill(c, [(12, 1300, 1, 1)] * 6)
    c.close()
    monkeypatch.setattr(dw, "_REWIND_DB", db)
    out = dw.compute_duration_winrate(mode="aram")
    assert out["n"] == 6
    assert _bucket(out)["winrate"] == 100.0


def test_open_ro_is_read_only(tmp_path, monkeypatch):
    db = tmp_path / "rewind_history.db"
    c = sqlite3.connect(db)
    _fill(c, [])
    c.close()
    monkeypatch.setattr(dw, "_REWIND_DB", db)
    ro = dw._open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO matches VALUES (12, 1300, 1, 1)")
    finally:
        ro.close()


@pytest.mark.parametrize("champ", ["ashe", True, 2 ** 63])
def test_unmatchable_champion_never_opens_the_db(monkeypatch, champ):
    # A filter nothing can satisfy must not open (and so cannot leak) a
    # read-only handle: the close lives on the query path only.
    opened = []

    def _spy():
        c = sqlite3.connect(":memory:")
        opened.append(c)
        return c

    monkeypatch.setattr(dw, "_open_ro", _spy)
    out = dw.compute_duration_winrate(mode="aram", champion=champ)
    assert out["n"] == 0
    assert opened == []


def test_missing_db_is_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(dw, "_REWIND_DB", tmp_path / "absent.db")
    out = dw.compute_duration_winrate(mode="sr", champion=64)
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["champion"] == 64
    assert len(out["buckets"]) == len(dw.DEFAULT_BUCKETS)
    assert not (tmp_path / "absent.db").exists()


def test_nan_is_not_integral():
    # Guards the coercion helper's NaN branch independently of the query.
    assert dw._coerce_champion(float("nan")) is None
    assert dw._coerce_champion(math.inf) is None
    assert dw._coerce_champion(-0.0) == 0
    assert dw._coerce_champion("+64") == 64
    assert dw._coerce_champion(chr(0x0664) + chr(0x0666)) is None  # non-ASCII digits
