"""s134 true-audit of tft/sources/eog_file.py (lane 8, cycle 11).

One test per confirmed weakness; each was red before the fix:

  F1  a junk id (a superscript digit string, or a digit string past
      CPython's 4300-digit int() limit) in a row's playerId or in the
      injected local id raised inside the parse, so the whole snapshot - all
      8 players - was dropped instead of the local player reading unknown.
  F2  a lone surrogate in an identity string (json.loads accepts "\\ud800")
      made the HMAC key raise UnicodeEncodeError: the whole snapshot lost.
  F3  locate() took a bool and a NaN as a stamp; a NaN was placed in the
      current match's last round.
  F4  an int past SQLite's signed 64-bit range (gameId, health, game length)
      passed the parse and every store validator, then raised OverflowError
      in the writer thread, so the match row was never written.
  F5  every fail-soft branch (parse, poll, ingest, local-id helper) logged at
      DEBUG only: a failure that repeats on every rewrite never reached the
      log at the default level.
  F6  a file without a usable gameId: two games in a row shared one match
      (None == None), and a restarted process restarted round_seq at 1 and
      overwrote the stored rounds.

Fixtures are the synthetic rewrites of tests/test_tft_sources_eog_file.py
(tests/fixtures/tft_sources/); nothing reads %LOCALAPPDATA%, data/ or logs/.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

import pytest

from tft.rounds.store import RoundStore
from tft.sources import eog_file as ef

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "tft_sources"
SALT = b"tft02-synthetic-salt-0123456789ab"
LOCAL_PLAYER_ID = 900002  # the fixture's sentinel playerId of the local row
BIG = 2 ** 64  # past SQLite's signed 64-bit INTEGER


def _rewrites():
    tl = json.loads((FIX / "timeline.json").read_text(encoding="ascii"))
    out = []
    for r in tl["rewrites"]:
        doc = json.loads((FIX / r["file"]).read_text(encoding="ascii"))
        out.append((doc, float(tl["t0_epoch"]) + float(r["t"])))
    return out


def _players(doc):
    return doc["statsBlock"]["players"]


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def eog_path(tmp_path, monkeypatch):
    p = tmp_path / "Logs" / "TFTEoGStats.json"
    p.parent.mkdir(parents=True)
    monkeypatch.setattr(ef.p0, "eog_stats_path", lambda: p)
    return p


@pytest.fixture
def store(tmp_path):
    s = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _fresh_warn_once(monkeypatch):
    monkeypatch.setattr(ef, "_WARNED", set(), raising=False)


def _put(path: Path, doc, mtime: float):
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(json.dumps(doc, indent=1).encode("ascii"))
    tmp.replace(path)
    os.utime(path, (mtime, mtime))


def _replay(eog_path, ingest, clock, docs):
    out = []
    for doc, mtime in docs:
        _put(eog_path, doc, mtime)
        clock.now = mtime + 1.0
        out.append(ingest.poll())
    return out


def _local_row(doc):
    return next(p for p in _players(doc) if p.get("playerId") == LOCAL_PLAYER_ID)


# ---------------------------------------------------------------- F1 junk ids


SUPERSCRIPT_2 = chr(0xB2)  # str.isdigit() is True, int() refuses it
ARABIC_3 = chr(0x663)  # an Arabic-Indic digit: str.isdigit() is True, not ASCII


@pytest.mark.parametrize("junk", [SUPERSCRIPT_2, "9" * 5000], ids=["superscript", "5000-digits"])
def test_f1_a_junk_row_player_id_leaves_the_snapshot_and_still_finds_the_local(junk):
    doc, mtime = copy.deepcopy(_rewrites()[0])
    rows = _players(doc)
    other = next(i for i, p in enumerate(rows) if p.get("playerId") != LOCAL_PLAYER_ID)
    rows[other]["playerId"] = junk
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=LOCAL_PLAYER_ID)
    assert snap is not None and len(snap.players) == 8
    assert snap.local_key is not None
    assert sum(1 for p in snap.players if p.is_local) == 1


@pytest.mark.parametrize("junk", [SUPERSCRIPT_2, "9" * 5000, f" {ARABIC_3} "],
                         ids=["superscript", "5000-digits", "arabic-indic"])
def test_f1_a_junk_injected_id_is_unknown_not_a_lost_snapshot(junk):
    doc, mtime = copy.deepcopy(_rewrites()[0])
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=junk)
    assert snap is not None and len(snap.players) == 8
    assert snap.local_key is None
    assert {p.is_local for p in snap.players} == {None}


def test_f1_a_digit_string_and_an_int_valued_float_still_select_the_local():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    for v in (str(LOCAL_PLAYER_ID), f" {LOCAL_PLAYER_ID} ", float(LOCAL_PLAYER_ID)):
        snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=v)
        assert snap.local_key is not None, v
    _local_row(doc)["playerId"] = str(LOCAL_PLAYER_ID)
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=LOCAL_PLAYER_ID)
    assert snap.local_key is not None


# ---------------------------------------------------------------- F2 surrogates


@pytest.mark.parametrize("field", ["riotIdGameName", "riotIdTagLine", "summonerName", "PUUID"])
def test_f2_a_lone_surrogate_in_an_identity_never_drops_the_snapshot(field):
    doc, mtime = copy.deepcopy(_rewrites()[0])
    rows = _players(doc)
    for p in rows:
        p[field] = "ab\ud800cd"
        if field == "summonerName":  # reach the last basis: no PUUID, no Riot id
            p.pop("PUUID", None)
            p.pop("riotIdGameName", None)
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    assert snap is not None and len(snap.players) == 8
    assert len({p.player_key for p in snap.players}) == 8


def test_f2_a_surrogate_tag_falls_back_to_the_bare_name():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    p = _players(doc)[1]
    clean = ef._identity({k: v for k, v in p.items() if k != "riotIdTagLine"})
    p["riotIdTagLine"] = "\udfff"
    assert ef._identity(p) == clean


# ---------------------------------------------------------------- F3 locate


def test_f3_locate_refuses_a_bool_and_non_finite_stamps(eog_path, store):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    rw = _rewrites()
    res = _replay(eog_path, ing, clock, rw)
    assert ing.locate(rw[5][1] + 1) == (res[0].match_id, 6)  # the control still places
    for bad in (True, False, float("nan"), float("inf"), float("-inf"), "1.0", None):
        assert ing.locate(bad) is None, bad


# ---------------------------------------------------------------- F4 int64


def test_f4_a_game_id_past_int64_still_writes_its_match(eog_path, store):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    docs = copy.deepcopy(_rewrites()[:2])
    for doc, _ in docs:
        doc["gameId"] = BIG
    res = _replay(eog_path, ing, clock, docs)
    assert [r.round_seq for r in res] == [1, 2]
    assert store.flush()
    got = store.get_match(res[0].match_id)
    assert got is not None
    assert got["match"]["game_id"] is None
    assert [r["round_seq"] for r in got["rounds"]] == [1, 2]


def test_f4_out_of_range_numbers_read_as_absent():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    doc["queueId"] = BIG
    doc["statsBlock"]["gameLengthSeconds"] = BIG
    _players(doc)[0]["health"] = BIG
    _players(doc)[1]["health"] = -BIG
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    assert (snap.queue_id, snap.game_length_s) == (None, None)
    assert (snap.players[0].hp_raw, snap.players[1].hp_raw) == (None, None)
    assert snap.players[2].hp_raw is not None  # the control row is untouched


# ---------------------------------------------------------------- F5 warn once


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING and r.name == ef.__name__]


def test_f5_a_repeating_poll_failure_warns_once_naming_the_type_only(eog_path, monkeypatch, caplog):
    doc, mtime = _rewrites()[0]
    _put(eog_path, doc, mtime)
    src = ef.EogFileSource(salt=SALT, clock=Clock(mtime + 1))

    def boom(**_kw):
        raise TypeError("SECRET-VALUE")

    monkeypatch.setattr(ef.p0, "read_eog", boom)
    caplog.set_level(logging.DEBUG, logger=ef.__name__)
    assert src.poll() is None and src.poll() is None
    assert src.stats["errors"] == 2
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "TypeError" in warns[0].getMessage()
    assert "SECRET-VALUE" not in caplog.text


def test_f5_a_failing_ingest_and_parse_and_helper_each_warn_once(eog_path, store, monkeypatch,
                                                                  caplog):
    caplog.set_level(logging.DEBUG, logger=ef.__name__)
    doc, mtime = _rewrites()[0]

    def bad_helper():
        raise KeyError("SECRET-ID")

    src = ef.EogFileSource(salt=SALT, clock=Clock(mtime + 1), local_player_id=bad_helper)
    ing = ef.EogIngest(store, salt=SALT, source=src)
    monkeypatch.setattr(ef, "_parse", lambda *a: (_ for _ in ()).throw(ValueError("SECRET")))
    for _ in range(2):
        assert ef.parse_eog(doc, salt=SALT) is None
    monkeypatch.setattr(ing, "_match_for", lambda s: (_ for _ in ()).throw(RuntimeError("SECRET")))
    snap = object.__new__(ef.EogSnapshot)
    for _ in range(2):
        assert ing.ingest(snap) is None
    for _ in range(2):
        assert src._resolve_local_id() is None
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 3, msgs
    assert any("ValueError" in m for m in msgs)
    assert any("RuntimeError" in m for m in msgs)
    assert any("KeyError" in m for m in msgs)
    assert "SECRET" not in caplog.text


# ---------------------------------------------------------------- F6 no gameId


def _without_game_id(docs):
    docs = copy.deepcopy(docs)
    for doc, _ in docs:
        doc.pop("gameId", None)
    return docs


def test_f6_a_restart_without_a_game_id_resumes_instead_of_overwriting(eog_path, store):
    rw = _without_game_id(_rewrites())
    clock = Clock()
    a = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    first = _replay(eog_path, a, clock, rw[:3])
    assert store.flush()
    clock2 = Clock()
    b = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock2))
    again = _replay(eog_path, b, clock2, rw[2:])
    assert [r.round_seq for r in again] == [3, 4, 5, 6]
    assert {r.match_id for r in first + again} == {first[0].match_id}
    assert store.flush()
    doc = store.get_match(first[0].match_id)
    assert [r["round_seq"] for r in doc["rounds"]] == [1, 2, 3, 4, 5, 6]


def test_f6_two_games_without_a_game_id_are_two_matches(eog_path, store):
    rw = _without_game_id(_rewrites())
    second = copy.deepcopy(rw[:2])
    for doc, _ in second:
        for i, p in enumerate(_players(doc)):  # another lobby: other identities
            p["riotIdGameName"] = f"OtherLobby{i}"
            p["PUUID"] = "0" * 36
    shift = 3600.0
    second = [(d, t + shift) for d, t in second]
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    one = _replay(eog_path, ing, clock, rw[:2])
    two = _replay(eog_path, ing, clock, second)
    assert one[0].match_id != two[0].match_id
    assert [r.round_seq for r in two] == [1, 2]
    assert store.flush()
    assert len(store.list_matches()) == 2
