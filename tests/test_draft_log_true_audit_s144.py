"""s144 true-audit of lcu/draft_log.py (RM-609 champ-select draft log).

Synthetic, name-scrubbed sessions only (the RM-609 fixture shape). Each test
pins one finding of the audit:

  F1  game_id_from_match_id accepted any str.isdigit() tail, so a non-ASCII
      digit ("NA1_" + U+00B2) or a tail over Python's 4300-digit int limit
      raised ValueError out of attach_draft_log, and Arabic-Indic digits were
      silently converted to a game id.
  F2  ids and values outside SQLite's signed 64-bit INTEGER range raised
      OverflowError from store_draft / load_draft; through the live sink one
      out-of-range championId cost the WHOLE draft.
  F3  parse_draft stored the repr of a non-str assignedPosition / type.
  F4  observe_phase raised TypeError on an unhashable phase, against the
      recorder's "Never raises" contract.
  F5  a Reconnect tick dropped a pending draft one line before
      shape_snapshot's Reconnect branch could note the game id.
  F6  a sink failure at note_game_id time was never retried (the game id was
      already set, so every later note returned early): one locked-DB moment
      lost the draft for good.
  F7  a failing sink logged one WARNING per tick for the whole finalization
      window; now once per failure streak.
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from lcu import draft_log as dl
from tests.test_draft_log_rm609 import GAME_ID, MATCH_ID, _rewind_db, _session


class _Sink:
    def __init__(self, fail_first=0):
        self.calls = []
        self.fail_first = fail_first

    def __call__(self, game_id, rows, queue_id):
        if self.fail_first > 0:
            self.fail_first -= 1
            raise sqlite3.OperationalError("database is locked")
        self.calls.append((game_id, len(rows), queue_id))


def _always_fail(*_a):
    raise sqlite3.OperationalError("database is locked")


# -- F1: match id parsing -------------------------------------------------------

@pytest.mark.parametrize("match_id", [
    "NA1_\u00b2",                     # superscript two: isdigit, int() raises
    "NA1_" + "9" * 5000,             # past the 4300-digit str->int limit
    "NA1_\u0661\u0662",               # Arabic-Indic 12: not a Riot id
    "NA1_" + str(2 ** 63),            # past SQLite INTEGER
    "NA1_ 12", "NA1_+12", "NA1_-12", "NA1_1_",
], ids=["superscript", "over-4300-digits", "arabic-indic", "over-int64",
        "space", "plus", "minus", "empty-tail"])
def test_f1_bad_match_id_tail_is_none_never_raises(match_id):
    assert dl.game_id_from_match_id(match_id) is None


def test_f1_attach_with_bad_match_id_reads_none(tmp_path):
    conn = _rewind_db(tmp_path)
    out = dl.attach_draft_log(conn, "NA1_\u00b2")
    assert out["draft_source"] == "none" and out["game_id"] is None


def test_f1_good_match_ids_still_parse():
    assert dl.game_id_from_match_id(MATCH_ID) == GAME_ID
    assert dl.game_id_from_match_id(str(2 ** 63 - 1)) == 2 ** 63 - 1


# -- F2: SQLite INTEGER range ---------------------------------------------------

def test_f2_out_of_range_game_id_is_refused_not_raised(tmp_path):
    conn = _rewind_db(tmp_path)
    rows = dl.parse_draft(_session())
    assert dl.store_draft(conn, 2 ** 63, rows) == 0
    assert dl.load_draft(conn, 2 ** 63) == []
    assert dl.session_game_id({"gameId": 2 ** 64}) == 0
    assert dl.session_queue_id({"gameData": {"queue": {"id": 2 ** 64}}}) == 0


def test_f2_out_of_range_lcu_values_cost_one_field_not_the_draft(tmp_path):
    sess = _session()
    sess["actions"][1][0]["championId"] = 2 ** 70
    sess["myTeam"][4]["championId"] = -(2 ** 70)
    rows = dl.parse_draft(sess)
    assert rows[10]["champion_id"] == 0
    assert rows[18]["final_champion_id"] == 0
    conn = _rewind_db(tmp_path)
    assert dl.store_draft(conn, GAME_ID, rows, queue_id=2 ** 70) == 20
    assert len(dl.load_draft(conn, GAME_ID)) == 20
    (qid,) = conn.execute("SELECT DISTINCT queue_id FROM draft_log").fetchone()
    assert qid == 0


def test_f2_out_of_range_cell_is_unknown_cell():
    sess = _session()
    sess["actions"][1][0]["actorCellId"] = 2 ** 70
    sess["localPlayerCellId"] = 2 ** 70
    rows = dl.parse_draft(sess)
    assert rows[10]["actor_cell_id"] == -1 and rows[10]["side"] == ""
    assert all(r["is_local"] == 0 for r in rows)


# -- F3: text fields -----------------------------------------------------------

def test_f3_non_str_text_fields_are_empty_not_repr():
    sess = _session()
    sess["myTeam"][1]["assignedPosition"] = {"pos": "jungle"}
    sess["actions"][1][0]["type"] = ["pick"]
    rows = dl.parse_draft(sess)
    assert rows[10]["assigned_position"] == ""
    assert rows[10]["action_type"] == ""


# -- F4 / F5: phase handling ---------------------------------------------------

@pytest.mark.parametrize("phase", [{}, [], {"phase": "Lobby"}])
def test_f4_unhashable_phase_never_raises_and_drops(phase):
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session(game_id=0))
    rec.observe_phase(phase)
    rec.note_game_id(GAME_ID)
    assert sink.calls == []


def test_f5_reconnect_keeps_a_pending_draft():
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session(game_id=0))
    rec.observe_phase("Reconnect")
    rec.note_game_id(str(GAME_ID))
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_f5_reconnect_snapshot_persists_the_pending_draft(monkeypatch):
    from lcu import snapshot_shape
    sink = _Sink()
    monkeypatch.setattr(dl, "_RECORDER", dl.DraftRecorder(sink=sink))
    dl._RECORDER.observe_session(_session(game_id=0))
    gflow = {"gameData": {"gameId": GAME_ID, "queue": {"id": 420}}}

    def req(method, path, body=None):
        if path == "/lol-gameflow/v1/gameflow-phase":
            return "Reconnect", None
        if path == "/lol-gameflow/v1/session":
            return gflow, None
        return None, None

    monkeypatch.setattr(snapshot_shape, "_maybe_refresh_mastery", lambda r: None)
    snapshot_shape.shape_snapshot(req, {})
    assert sink.calls == [(GAME_ID, 20, 420)]


# -- F6 / F7: sink failure ------------------------------------------------------

def test_f6_failed_flush_at_note_game_id_is_retried():
    sink = _Sink(fail_first=1)
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session(game_id=0))
    rec.note_game_id(GAME_ID)            # DB locked: write refused
    assert sink.calls == []
    rec.note_game_id(GAME_ID)            # next tick: retried
    assert sink.calls == [(GAME_ID, 20, 420)]
    rec.note_game_id(GAME_ID)            # written: never rewritten
    assert len(sink.calls) == 1


def test_f6_a_second_game_id_never_rekeys_the_draft():
    sink = _Sink(fail_first=1)
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session(game_id=0))
    rec.note_game_id(GAME_ID)
    rec.note_game_id(GAME_ID + 1)
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_f6_note_game_id_without_a_draft_writes_nothing():
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.note_game_id(GAME_ID)
    assert sink.calls == []


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == "rc.lcu.draft_log" and r.levelno == logging.WARNING]


def test_f7_failing_sink_warns_once_per_streak_and_gives_up(caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu.draft_log")
    sink = _Sink(fail_first=10 ** 6)
    rec = dl.DraftRecorder(sink=sink)
    for _ in range(5):
        rec.observe_session(_session())
    for _ in range(5):
        rec.note_game_id(GAME_ID)
    # Offered _MAX_SINK_ATTEMPTS times, then dropped; warned at the first
    # refusal and at the give-up, debug in between.
    assert sink.fail_first == 10 ** 6 - dl._MAX_SINK_ATTEMPTS
    msgs = [r.getMessage() for r in _warnings(caplog)]
    assert len(msgs) == 2 and "giving up" in msgs[1]
    assert "giving up" not in msgs[0]


def test_f7_attempt_cap_resets_for_a_changed_draft():
    sink = _Sink(fail_first=dl._MAX_SINK_ATTEMPTS + 1)
    rec = dl.DraftRecorder(sink=sink)
    for _ in range(dl._MAX_SINK_ATTEMPTS + 2):
        rec.observe_session(_session())
    assert sink.calls == [] and sink.fail_first == 1
    traded = _session()
    traded["myTeam"][2]["championId"] = 103     # a late trade: new draft
    rec.observe_session(traded)                 # refused: attempt 1 of 5
    rec.observe_session(traded)                 # attempt 2 lands
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_f7_a_new_streak_after_success_warns_again(caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu.draft_log")
    sink = _Sink(fail_first=1)
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session())      # fails: warning 1
    rec.observe_session(_session())      # succeeds
    assert sink.calls == [(GAME_ID, 20, 420)]
    rec.set_sink(_always_fail)
    later = _session(game_id=GAME_ID + 1)
    rec.observe_session(later)           # new streak: warning 2
    rec.observe_session(later)
    assert len(_warnings(caplog)) == 2
