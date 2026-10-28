"""s144 true-audit (RM-1036): core/live_session_recorder.py hardening.

Each test pins one measured weakness of the RM-605 recorder / reader:
  1. a crash tear that splits a multi-byte UTF-8 character in the FINAL line
     raised UnicodeDecodeError from read_session (not SessionFormatError), so
     the "torn final line is tolerated" contract failed for any recording
     that names a non-ASCII player or champion, and tools/replay_session.py
     (which catches OSError / SessionFormatError only) died on a traceback;
  2. a recorder that reopened an existing <gameId>.jsonl (an RC restart in
     the same game) appended after the torn tail, turning it into an INTERIOR
     bad line, so read_session refused the whole recording;
  3. a write that failed part-way left the handle open, so the next frame was
     appended onto the partial line - the same whole-file loss;
  4. a non-finite gameTime / source_ts was written as the bare token
     Infinity / NaN (not JSON for any non-Python reader, and replayed into
     /api/state as such), and an infinite gameTime split one game into two
     sessions with a repeated seq;
  5. a persistent writer failure logged one WARNING per frame (2 per second
     for a whole game);
  6. flush(timeout) / close(timeout) blocked forever on a full queue behind a
     wedged writer, ignoring their timeout.

Fixtures are synthetic: no real Riot IDs or summoner names.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from core import live_session_recorder as lsr
from tests._timing_budget import fleet_test_guard

HEADER_FIELDS = {
    "config_key": "1920x1080|HUDScale=0.5",
    "patch": "99.1.1",
    "ENGINE_VERSION": "0.0.1-test",
    "mode_key": "aram",
}
GID = "9000000001"
# Source stays ASCII: the non-ASCII test names are built from code points.
_HAN = chr(0x4E00)                                      # 3 bytes in UTF-8
_ACCENTED = "Synth" + chr(0xE9) + "tique"               # 2-byte character


def _snap(game_time, name="SyntheticPlayer#TEST"):
    return {
        "activePlayer": {"summonerName": name, "currentGold": 500.0},
        "gameData": {"gameMode": "ARAM", "gameTime": game_time},
    }


def _recorder(tmp_path, vision=None):
    return lsr.LiveSessionRecorder(
        sessions_dir=tmp_path,
        header_fields=lambda snapshot: dict(HEADER_FIELDS),
        game_id_provider=lambda: GID,
        vision_provider=(lambda: vision),
    )


def _hdr_line():
    return json.dumps(dict(HEADER_FIELDS, kind="header", schema=lsr.SCHEMA_VERSION))


def _frame_line(seq, name="SyntheticPlayer#TEST"):
    return json.dumps({"kind": "frame", "seq": seq, "captured_at": 1.0 + seq,
                       "game_time": float(seq), "snapshot": _snap(float(seq), name)},
                      ensure_ascii=False)


def _strict_loads(raw):
    def _refuse(tok):
        raise ValueError(f"non-JSON constant {tok}")
    return json.loads(raw, parse_constant=_refuse)


@pytest.fixture(autouse=True)
def _reset():
    lsr._reset_for_tests()
    yield
    lsr._reset_for_tests()


# -- 1. reader: torn final line split inside a UTF-8 character ----------------

def test_reader_tolerates_torn_final_line_split_inside_utf8(tmp_path):
    p = tmp_path / "s.jsonl"
    torn = _frame_line(1, name=_ACCENTED + _HAN).encode("utf-8")
    cut = torn.index(_HAN.encode()) + 1   # mid-character
    p.write_bytes((_hdr_line() + "\n" + _frame_line(0) + "\n").encode("utf-8") + torn[:cut])
    header, frames = lsr.read_session(p)
    assert header["kind"] == "header"
    assert [f["seq"] for f in frames] == [0]


def test_reader_interior_invalid_utf8_is_a_session_format_error(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_bytes((_hdr_line() + "\n").encode("utf-8") + b'{"kind":"fr\xe4\xb8\n'
                  + (_frame_line(1) + "\n").encode("utf-8"))
    with pytest.raises(lsr.SessionFormatError):
        lsr.read_session(p)


def test_reader_header_invalid_utf8_is_a_session_format_error(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_bytes(b'{"kind":"header","x":"\xff"}\n')
    with pytest.raises(lsr.SessionFormatError):
        lsr.read_session(p)


def test_reader_still_round_trips_non_ascii_content(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_bytes((_hdr_line() + "\n" + _frame_line(0, name=_ACCENTED) + "\n")
                  .encode("utf-8"))
    _, frames = lsr.read_session(p)
    assert frames[0]["snapshot"]["activePlayer"]["summonerName"] == _ACCENTED


# -- 2. writer: reopening a file with a torn tail ------------------------------

def test_append_after_a_torn_tail_keeps_the_recording_readable(tmp_path):
    p = tmp_path / (GID + ".jsonl")
    # A previous RC process died mid-write in this same game.
    p.write_bytes((_hdr_line() + "\n" + _frame_line(0) + "\n").encode("utf-8")
                  + _frame_line(1).encode("utf-8")[:20])
    rec = _recorder(tmp_path)
    rec.record(_snap(5.0))
    rec.record(_snap(6.0))
    assert rec.flush()
    rec.close()
    header, frames = lsr.read_session(p)
    assert [f["game_time"] for f in frames] == [0.0, 5.0, 6.0]
    raw = p.read_bytes().split(b"\n")
    assert raw[-1] == b""
    assert sum(1 for x in raw[:-1] if json.loads(x)["kind"] == "header") == 1


def test_append_after_a_torn_header_rewrites_the_header(tmp_path):
    p = tmp_path / (GID + ".jsonl")
    p.write_bytes(_hdr_line().encode("utf-8")[:15])   # died inside the header
    rec = _recorder(tmp_path)
    rec.record(_snap(5.0))
    assert rec.flush()
    rec.close()
    header, frames = lsr.read_session(p)
    assert header["schema"] == lsr.SCHEMA_VERSION
    assert [f["game_time"] for f in frames] == [5.0]


def test_repair_leaves_a_clean_file_byte_identical(tmp_path):
    p = tmp_path / (GID + ".jsonl")
    body = (_hdr_line() + "\n" + _frame_line(0) + "\n").encode("utf-8")
    p.write_bytes(body)
    assert lsr._repair_torn_tail(p) == 0
    assert p.read_bytes() == body
    assert lsr._repair_torn_tail(tmp_path / "absent.jsonl") == 0


def test_repair_finds_a_newline_beyond_one_scan_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(lsr, "_TAIL_SCAN_CHUNK", 8)
    p = tmp_path / (GID + ".jsonl")
    keep = (_hdr_line() + "\n").encode("utf-8")
    p.write_bytes(keep + b"x" * 50)
    assert lsr._repair_torn_tail(p) == 50
    assert p.read_bytes() == keep


# -- 3. writer: a write that fails part-way -------------------------------------

class _TearOnceHandle:
    """Writes half of the first frame line, then raises (disk full)."""

    def __init__(self, real, state):
        self._real = real
        self._state = state

    def write(self, s):
        if self._state["armed"] and s.startswith('{"kind":"frame"'):
            self._state["armed"] = False
            self._real.write(s[: len(s) // 2])
            self._real.flush()
            raise OSError(28, "No space left on device")
        return self._real.write(s)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_a_partial_write_does_not_poison_the_recording(tmp_path, monkeypatch):
    state = {"armed": True}
    real_open = lsr._open_append
    monkeypatch.setattr(lsr, "_open_append",
                        lambda path: _TearOnceHandle(real_open(path), state))
    rec = _recorder(tmp_path)
    for gt in (1.0, 2.0, 3.0):
        rec.record(_snap(gt))
    assert rec.flush()
    rec.close()
    assert state["armed"] is False
    _, frames = lsr.read_session(tmp_path / (GID + ".jsonl"))
    assert [f["game_time"] for f in frames] == [2.0, 3.0]


# -- 4. non-finite numbers -------------------------------------------------------

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_game_time_is_null_and_does_not_split_the_session(tmp_path, bad):
    rec = _recorder(tmp_path)
    rec.record(_snap(100.0))
    rec.record({"gameData": {"gameMode": "ARAM"}, "note": "no gameTime here"}, ts=bad)
    rec._q.put(('{"gameData":{}}', bad, 1.0, bad, {}))   # a derived non-finite value
    rec.record(_snap(101.0))
    assert rec.flush()
    rec.close()
    lines = (tmp_path / (GID + ".jsonl")).read_text(encoding="utf-8").splitlines()
    parsed = [_strict_loads(x) for x in lines]   # every line is strict JSON
    frames = parsed[1:]
    assert [f["seq"] for f in frames] == [0, 1, 2, 3]
    assert frames[2]["game_time"] is None
    assert all("source_ts" not in f for f in frames[1:3])


def test_non_finite_inside_the_snapshot_and_vision_is_written_as_null(tmp_path):
    rec = _recorder(tmp_path, vision={"enemies": [{"x": float("nan")}]})
    snap = _snap(float("inf"))
    snap["allPlayers"] = [{"scores": [float("-inf"), 2.5]}]
    assert rec.record(snap) is True
    assert rec.flush()
    rec.close()
    lines = (tmp_path / (GID + ".jsonl")).read_text(encoding="utf-8").splitlines()
    frame = _strict_loads(lines[1])
    assert frame["snapshot"]["gameData"]["gameTime"] is None
    assert frame["snapshot"]["allPlayers"] == [{"scores": [None, 2.5]}]
    assert frame["vision_state"] == {"enemies": [{"x": None}]}
    assert snap["gameData"]["gameTime"] == float("inf")   # caller's object untouched


def test_a_circular_snapshot_is_dropped_not_raised(tmp_path):
    rec = _recorder(tmp_path)
    snap = _snap(1.0)
    snap["self"] = snap
    assert rec.record(snap) is False
    rec.close()


def test_game_time_reader_rejects_non_finite():
    assert lsr._game_time(_snap(float("inf"))) is None
    assert lsr._game_time(_snap(float("nan"))) is None
    assert lsr._game_time(_snap(12)) == 12.0


# -- 5. persistent writer failure is warned once per streak ---------------------

def test_a_persistent_writer_failure_warns_once_per_streak(tmp_path, caplog):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    rec = _recorder(blocker)            # mkdir on a file path fails every frame
    caplog.set_level(logging.DEBUG, logger="rc.live_session_recorder")
    for gt in range(6):
        rec.record(_snap(float(gt)))
    assert rec.flush()
    warns = [r for r in caplog.records
             if r.name == "rc.live_session_recorder" and r.levelno >= logging.WARNING]
    assert len(warns) == 1
    # Recovery is reported, and the next failure streak warns again.
    rec._dir = tmp_path / "ok"
    rec.record(_snap(10.0))
    assert rec.flush()                  # frame 10 is written before the swap back
    rec._dir = blocker
    rec.end_session()
    rec.record(_snap(11.0))
    assert rec.flush()
    rec.close()
    warns = [r for r in caplog.records
             if r.name == "rc.live_session_recorder" and r.levelno >= logging.WARNING]
    assert len(warns) == 2
    assert any("recovered" in r.getMessage() for r in caplog.records)


# -- 6. flush / close honour their timeout on a full queue ----------------------

def test_flush_and_close_honour_their_timeout_when_the_queue_is_full(tmp_path, monkeypatch):
    monkeypatch.setattr(lsr, "_QUEUE_MAX", 2)
    gate = threading.Event()
    entered = threading.Event()

    def stalled_vision():
        entered.set()
        gate.wait(10)
        return None

    rec = _recorder(tmp_path)
    rec._vision_provider = stalled_vision
    try:
        assert rec.record(_snap(0.0)) is True
        assert entered.wait(5)
        assert rec.record(_snap(1.0)) and rec.record(_snap(2.0))   # queue full
        t0 = time.perf_counter()
        assert rec.flush(timeout=0.2) is False
        rec.close(timeout=0.2)
        elapsed = time.perf_counter() - t0
        assert elapsed < fleet_test_guard.budget(2.0)
    finally:
        gate.set()
    assert rec.flush(timeout=5)
    rec.close(timeout=5)
    assert not rec._thread.is_alive()
