"""Lane 8 Headless-True-Audit cycle 12 - core/decision_detector.py.

Regression tests for four defects found by the depth audit. Each test is
named for the weakness it pins and was verified RED against the pre-fix
module before the fix landed.

W1 CORRECTNESS  - detect_postfight_objective counted every ChampionKill
                  TWICE (once resolving the killer's team, once the
                  victim's), so the "+3 kill differential" its docstring
                  promises fired at a true +2, and the title rendered
                  DOUBLE the real number to the player ("+4 fight" for a
                  +2 fight). It is the one detector with no test class in
                  tests/test_decision_detector_adr007.py.
W2 CONCURRENCY  - _write_pending / _write_heartbeat used a bare
                  Path.replace. On Windows that raises PermissionError
                  (WinError 5) while a reader holds the destination open,
                  and both callers swallowed it. decisions_pending.json is
                  read cross-process by dashboard/routes_diag.py and
                  dashboard/routes_metrics.py, so the contention is
                  routine by design. Consequence: record_choice() appended
                  to the JSONL log and then silently failed to remove the
                  decision, so one decision logged TWICE and stayed
                  pending forever.
W3 OBSERVABILITY- the ADR-007 heartbeat reported alive with a healthy
                  incrementing counter while detectors raised on every
                  tick. The pill exists so the operator can tell the loop
                  is alive "even when it's silently deciding not to fire",
                  but it could not separate that from "crashing".
W4 INPUT VALID. - list_pending() returned whatever JSON the file held.
                  A non-list (or a list of non-dicts) then wedged
                  reconcile() with TypeError inside the loop's broad
                  except, every tick, forever, without repairing the file.

LANE 8 CYCLE 26 - the W2 tests changed how contention is PRODUCED, not what
they assert. They used to open the destination on a thread and let win32's
share lock supply the PermissionError. POSIX renames straight through an open
read handle, so on the Linux CI runner
test_record_choice_does_not_double_log_when_the_write_fails was RED (the write
succeeded, so record_choice returned a dict instead of None) and the three
transient-reader tests were vacuously GREEN, having provoked no fault at all.
The fault is now injected at the os.replace boundary by
tests/_replace_faults.replace_fails, so the retry loop runs on every platform;
the OS-shaped question is a separate platform-gated test at the end of W2.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

import core.decision_detector as dd
from core.polled_json import _REPLACE_RETRY_DELAYS_S as _DELAYS
from tests._replace_faults import replace_fails
from core.decision_detector import (
    DecisionLoop,
    DecisionStore,
    _enemy_has_smite,
    detect_postfight_objective,
)


# -- fixtures ------------------------------------------------------------------

def _postfight_snapshot(kills, game_time: float = 905.0) -> dict:
    """Snapshot with a Dragon window open (killed at 620 + 300s respawn =
    920, i.e. +15s from game_time 905) so detect_postfight_objective gets
    past its objective gate and we are measuring the kill-diff arithmetic
    alone. `kills` is a list of (killer_name, victim_name)."""
    events = [{"EventName": "ChampionKill", "EventTime": game_time - 5,
               "KillerName": k, "VictimName": v} for k, v in kills]
    events.append({"EventName": "DragonKill", "EventTime": 620.0})
    return {
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC"},
        "activePlayer": {"summonerName": "Me"},
        "allPlayers": [
            {"summonerName": "Me", "team": "ORDER"},
            {"summonerName": "A1", "team": "ORDER"},
            {"summonerName": "A2", "team": "ORDER"},
            {"summonerName": "E1", "team": "CHAOS"},
            {"summonerName": "E2", "team": "CHAOS"},
            {"summonerName": "E3", "team": "CHAOS"},
        ],
        "events": {"Events": events},
    }


# -- W1: kill differential is counted once, not twice --------------------------

class TestPostfightKillDiffNotDoubled:

    def test_three_ally_kills_reports_plus_three_not_six(self):
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")]), {})
        assert d is not None, "a true +3 differential must still fire"
        assert d.context["kill_diff"] == 3

    def test_title_shows_the_true_differential(self):
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")]), {})
        assert d is not None
        # The player must not be shown "+6 fight" for a 3-kill swing.
        assert "+3 fight" in d.title
        assert "+6" not in d.title
        assert "kill diff +3" in d.subtitle

    def test_true_plus_two_does_not_fire(self):
        """Docstring promises "+3 (or better)". Doubling made +2 fire."""
        d = detect_postfight_objective(
            _postfight_snapshot([("Me", "E1"), ("A1", "E2")]), {})
        assert d is None

    def test_ally_deaths_subtract_once(self):
        """4 ally kills - 1 ally death = +3. Doubling reported +6."""
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Me", "E1"),
             ("E1", "A1")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_non_champion_killer_still_counts_the_victim(self):
        """A turret/minion execute has no KillerName in allPlayers. The
        event must still count once, from the victim's side."""
        snap = _postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Turret_T2", "E1")])
        d = detect_postfight_objective(snap, {})
        assert d is not None
        assert d.context["kill_diff"] == 4


# -- W2: atomic replace survives a concurrent reader ---------------------------

class TestWritePendingUnderConcurrentReader:
    """A bare os.replace onto a file a reader holds open raises
    PermissionError (WinError 5) on Windows. core/polled_json measures the
    real contention window at <100 ms and retries for ~275 ms, so a BRIEF
    overlapping read must now succeed. An indefinite hold cannot be beaten
    by any atomic-rename design - what matters there is that the store
    stays CONSISTENT rather than double-logging.

    The fault is INJECTED at os.replace (see the module docstring); it is no
    longer borrowed from a real held handle, which only ever produced it on
    win32. The read that causes it is nonetheless real and cross-process:
    dashboard/routes_diag.py and dashboard/routes_metrics.py both read
    decisions_pending.json from the RC main process."""

    @staticmethod
    def _brief_contention(path):
        """Two failed replaces, then a real one.

        That is the poller's read window expressed deterministically: it must
        CLEAR for the ~275 ms retry to be able to win, so a transient fault is
        what exercises the retry loop. A permanent one exercises exhaustion,
        which is a different test.
        """
        return replace_fails(path, times=2)

    def test_write_pending_survives_a_transient_reader(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "log.jsonl")
        store._write_pending([{"id": "x", "expires_at_game_time": 9e9}])
        with self._brief_contention(pending) as rec:
            assert store._write_pending([]) is True
        assert rec.attempts == 3, "the write did not re-attempt after a fault"
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_record_choice_survives_a_transient_reader(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        log = tmp_path / "decisions_log.jsonl"
        store = DecisionStore(pending_path=pending, log_path=log)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        with self._brief_contention(pending) as rec:
            assert store.record_choice("objective_contest:Dragon:920",
                                       "contest") is not None
        assert rec.attempts == 3
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_record_choice_does_not_double_log_when_the_write_fails(
            self, tmp_path):
        """The measured pre-fix behaviour: the JSONL append ran first and
        the pending write's failure was swallowed, so ONE decision logged
        TWICE and never left the pending list. A failed write must now
        record nothing at all.

        The permanent fault is injected rather than borrowed from an
        indefinitely held handle. As a held-handle test this was RED on the
        Linux runner: the rename succeeded, so record_choice returned a dict
        and the double-log branch it guards was never reached there at all."""
        pending = tmp_path / "decisions_pending.json"
        log = tmp_path / "decisions_log.jsonl"
        store = DecisionStore(pending_path=pending, log_path=log)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        with replace_fails(pending) as rec:        # every attempt fails
            first = store.record_choice("objective_contest:Dragon:920",
                                        "contest")
            second = store.record_choice("objective_contest:Dragon:920",
                                         "give")
        # Both calls must exhaust the loop: one attempt per backoff delay,
        # plus the initial attempt, twice over.
        assert rec.attempts == 2 * (len(_DELAYS) + 1), (
            f"retry loop not exhausted twice: {rec}")
        assert first is None and second is None
        assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""
        # The decision is still pending, so the player's next click works.
        assert [d["id"] for d in store.list_pending()] == [
            "objective_contest:Dragon:920"]
        assert store.record_choice("objective_contest:Dragon:920",
                                   "contest") is not None
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        assert len(lines) == 1, f"one decision must log once, got {lines}"

    def test_heartbeat_write_survives_a_transient_reader(
            self, tmp_path, monkeypatch):
        path = tmp_path / "decisions_heartbeat.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        with loop._heartbeat_lock:
            loop._eval_count = 1
            loop._last_eval_unix = time.time()
        loop._write_heartbeat()
        with loop._heartbeat_lock:
            loop._eval_count = 2
        with self._brief_contention(path) as rec:
            loop._write_heartbeat()
        assert rec.attempts == 3, "the heartbeat write did not re-attempt"
        assert json.loads(path.read_text(encoding="utf-8"))["counter"] == 2

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="POSIX rename ignores an open read handle; there is no OS "
               "fault to observe, which is why the tests above inject theirs")
    def test_the_real_os_still_share_locks_a_held_pending_file(self, tmp_path):
        """The one question replace_fails() cannot answer: is it real?

        The tests above simulate the share lock, so this asserts the OS
        property alone - no store, no retry loop - and stays true whatever
        core/decision_detector does next. Red here on win32 would mean the
        premise of the retry loop is gone and the injected faults model a
        condition that no longer occurs."""
        pending = tmp_path / "decisions_pending.json"
        pending.write_text("[]", encoding="utf-8")
        scratch = tmp_path / "decisions_pending.os_probe"
        scratch.write_text("[]", encoding="utf-8")
        with open(pending, encoding="utf-8"):
            with pytest.raises(PermissionError):
                os.replace(scratch, pending)
        scratch.unlink()


# -- W3: the heartbeat admits detector failures --------------------------------

class TestHeartbeatSurfacesDetectorErrors:

    def _run_one_pass(self, loop, snapshot):
        loop._fetch_snapshot = lambda: (snapshot, 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01          # keep the guard fast; 1 Hz is prod
        t = threading.Thread(target=loop._loop, daemon=True)
        t.start()
        time.sleep(0.3)
        loop._stop.set()
        t.join(timeout=3)

    def test_partial_detector_failure_is_reported(self, tmp_path, monkeypatch):
        """events.Events arriving as a str (an upstream shape change)
        crashes 2 of 6 detectors on every tick. Before the fix the pill
        read alive=True with a clean counter and no failure signal."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        self._run_one_pass(loop, {
            "gameData": {"gameTime": 900.0, "gameMode": "CLASSIC"},
            "activePlayer": {"summonerName": "Me"},
            "allPlayers": [{"summonerName": "Me", "team": "ORDER"}],
            "events": {"Events": "shape-changed"},
        })
        hb = loop.heartbeat()
        assert hb["counter"] > 0, "loop must still be running"
        assert hb["detector_errors"] == 2
        # Registry order ends with detect_throwing_lead, so it is the last
        # of the two crashers to be recorded.
        assert "detect_throwing_lead" in (hb["last_detector_error"] or "")
        assert "AttributeError" in (hb["last_detector_error"] or "")

    def test_healthy_pass_reports_zero_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        self._run_one_pass(loop, _postfight_snapshot([("Me", "E1")]))
        hb = loop.heartbeat()
        assert hb["counter"] > 0
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None

    def test_read_heartbeat_defaults_carry_the_new_keys(
            self, tmp_path, monkeypatch):
        """The dashboard pill reads through read_heartbeat(); its
        no-file sentinel must carry the same keys as heartbeat()."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "missing.json")
        hb = dd.read_heartbeat()
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None

    def test_read_heartbeat_backfills_keys_for_a_legacy_file(
            self, tmp_path, monkeypatch):
        """A heartbeat file written by the pre-fix loop has neither key.
        read_heartbeat must not KeyError the dashboard route."""
        path = tmp_path / "hb.json"
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
        path.write_text(json.dumps({
            "counter": 12, "last_eval_unix": time.time() - 1.0,
            "age_s": 1.0, "alive": True, "game_time": 600.0, "detectors": 6,
        }), encoding="utf-8")
        hb = dd.read_heartbeat()
        assert hb["counter"] == 12
        assert hb["detector_errors"] == 0
        assert hb["last_detector_error"] is None


# -- W4: a malformed pending file cannot wedge the loop ------------------------

class TestPendingFileShapeValidation:

    @pytest.mark.parametrize("raw", [
        '{"id": "not-a-list"}',       # a dict
        'null',                       # JSON null
        '"a string"',                 # a bare string
        '[1, 2, 3]',                  # list of non-dicts
        '[{"no_id": true}]',          # dicts without the required id
        '[{"id": 17}]',               # id present but not a string
    ])
    def test_list_pending_returns_a_list_of_id_carrying_dicts(
            self, tmp_path, raw):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text(raw, encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert store.list_pending() == []

    def test_reconcile_does_not_raise_on_a_malformed_file(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('{"id": "not-a-list"}', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        store.reconcile([], game_time=100.0)   # raised TypeError before

    def test_reconcile_repairs_the_malformed_file(self, tmp_path):
        """6e: the fix must also recover the already-bad state, not just
        stop future corruption."""
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('{"id": "not-a-list"}', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        store.reconcile([], game_time=100.0)
        assert json.loads(pending.read_text(encoding="utf-8")) == []

    def test_good_entries_survive_validation(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text(json.dumps(
            [{"id": "keep:1", "expires_at_game_time": 9e9},
             "junk",
             {"id": "keep:2", "expires_at_game_time": 9e9}]),
            encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert [d["id"] for d in store.list_pending()] == ["keep:1", "keep:2"]

    def test_record_choice_on_a_malformed_file_returns_none(self, tmp_path):
        pending = tmp_path / "decisions_pending.json"
        pending.write_text('[1, 2, 3]', encoding="utf-8")
        store = DecisionStore(pending_path=pending,
                              log_path=tmp_path / "l.jsonl")
        assert store.record_choice("anything", "contest") is None


# -- Findings raised by the adversarial pass on this slice ---------------------

class TestAdversarialFollowups:
    """Four defects the refutation pass on cycle 12 found in the cycle-12
    fix itself. Each was measured, then pinned here."""

    def test_same_team_kill_nets_zero(self):
        """An ally killing an ally is one kill and one death for the same
        team. The first single-count fix credited it +1 - further from the
        truth than the doubled version it replaced, which netted 0."""
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("Me", "A1")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_enemy_killing_enemy_nets_zero(self):
        d = detect_postfight_objective(_postfight_snapshot(
            [("Me", "E1"), ("A1", "E2"), ("A2", "E3"), ("E1", "E2")]), {})
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_non_dict_player_row_does_not_raise(self):
        """The self-team lookup was a hand-rolled loop with no isinstance
        guard, so a non-dict allPlayers row ahead of the active player
        raised before the guarded _team_of was ever reached."""
        snap = _postfight_snapshot([("Me", "E1"), ("A1", "E2"), ("A2", "E3")])
        snap["allPlayers"].insert(0, "not-a-dict")
        d = detect_postfight_objective(snap, {})     # must not raise
        assert d is not None
        assert d.context["kill_diff"] == 3

    def test_a_failed_log_append_restores_the_decision(self, tmp_path):
        """THE REGRESSION THE ADVERSARIAL PASS CAUGHT. Ordering the pending
        write first fixed the double-log but opened the mirror hole: if the
        JSONL append then failed, the decision was gone from pending, never
        logged, and the caller was told ok. The invariant is that a decision
        is either still pending or logged exactly once - never neither.

        The log path is a DIRECTORY, so only the append raises. Patching
        Path.open instead makes this test vacuous: write_text() goes through
        Path.open too, so the PENDING write fails first, record_choice
        returns None at the earlier branch, and the test passes without ever
        reaching the code it claims to guard - measured, the mutant survived
        until this was changed."""
        pending = tmp_path / "decisions_pending.json"
        log_dir = tmp_path / "decisions_log.jsonl"
        log_dir.mkdir()
        store = DecisionStore(pending_path=pending, log_path=log_dir)
        store._write_pending([{"id": "objective_contest:Dragon:920",
                               "type": "objective_contest",
                               "expires_at_game_time": 9e9}])
        assert store.record_choice("objective_contest:Dragon:920",
                                   "contest") is None
        # Still pending, so the player's click is not silently swallowed.
        assert [d["id"] for d in store.list_pending()] == [
            "objective_contest:Dragon:920"]
        assert list(log_dir.iterdir()) == []

    def test_last_detector_error_is_length_capped(self, tmp_path, monkeypatch):
        """The string is served by /api/decisions/heartbeat and an exception
        message can quote snapshot fields, including a Riot ID."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")

        def _explode(snapshot, vision_state):
            raise ValueError("x" * 5000)

        monkeypatch.setattr(dd, "DECISION_REGISTRY", [_explode])
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        loop._fetch_snapshot = lambda: (_postfight_snapshot([]), 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01
        t = threading.Thread(target=loop._loop, daemon=True)
        t.start()
        time.sleep(0.3)
        loop._stop.set()
        t.join(timeout=3)
        hb = loop.heartbeat()
        assert hb["detector_errors"] == 1
        assert len(hb["last_detector_error"]) <= dd._MAX_ERR_CHARS

    def test_repeated_failures_do_not_log_every_tick(self, tmp_path,
                                                     monkeypatch, caplog):
        """At 1 Hz an unchanged breakage would write ~3600 WARNING lines an
        hour. Log on change of signature, then at most once a minute."""
        monkeypatch.setattr(dd, "_HEARTBEAT_PATH", tmp_path / "hb.json")

        def _explode(snapshot, vision_state):
            raise ValueError("same every time")

        monkeypatch.setattr(dd, "DECISION_REGISTRY", [_explode])
        loop = DecisionLoop(store=DecisionStore(
            pending_path=tmp_path / "p.json", log_path=tmp_path / "l.jsonl"))
        loop._fetch_snapshot = lambda: (_postfight_snapshot([]), 0.1)
        loop._read_vision_state = lambda: {}
        loop._poll_s = 0.01
        with caplog.at_level("WARNING", logger="rc.decision_detector"):
            t = threading.Thread(target=loop._loop, daemon=True)
            t.start()
            time.sleep(0.4)
            loop._stop.set()
            t.join(timeout=3)
        warns = [r for r in caplog.records if "detectors failed" in r.message]
        assert loop.heartbeat()["counter"] >= 5, "loop must have ticked a lot"
        assert len(warns) == 1, f"expected one warning, got {len(warns)}"


# -- W5: the Smite probe reads the field its docstring cites -------------------

class TestSmiteFieldNames:

    def test_reads_raw_display_name(self):
        """The docstring cites rawName ...SummonerSmite_DisplayName; the
        code only ever read displayName + rawDescription."""
        p = {"summonerSpells": {"summonerSpellOne": {
            "rawDisplayName":
                "GeneratedTip_SummonerSpell_SummonerSmite_DisplayName"}}}
        assert _enemy_has_smite(p) is True

    def test_full_live_client_shape_still_detected(self):
        p = {"summonerSpells": {"summonerSpellOne": {
            "displayName": "Smite",
            "rawDescription":
                "GeneratedTip_SummonerSpell_SummonerSmite_Description",
            "rawDisplayName":
                "GeneratedTip_SummonerSpell_SummonerSmite_DisplayName"}}}
        assert _enemy_has_smite(p) is True

    def test_non_smite_spells_are_not_detected(self):
        p = {"summonerSpells": {
            "summonerSpellOne": {
                "displayName": "Flash",
                "rawDisplayName":
                    "GeneratedTip_SummonerSpell_SummonerFlash_DisplayName"},
            "summonerSpellTwo": {
                "displayName": "Ignite",
                "rawDisplayName":
                    "GeneratedTip_SummonerSpell_SummonerDot_DisplayName"}}}
        assert _enemy_has_smite(p) is False
