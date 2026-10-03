"""FLEET-KIT-v1 in the inbox responder: the kit's skip rule and the idle tick.

The responder's SPAWN stays on `tools/inbox_responder_spawn.real_spawner`
(kit gap: the agreement-pinned model and the measured argv tail), but two kit
rules apply to it now and are pinned here:

- `should_skip`: never spawn on this tree's own notes or on a TERMINAL /
  no-reply note. Judged on the NAME only (gate 6 has not vetted the entry yet),
  and a skipped note is marked seen in its OWN record, never in the answered
  record (RM-386: answered means replied to).
- between ticks the kit's status file says Idle and names the next tick.

No process, no live inbox: tmp roots only.
"""
from __future__ import annotations

import json

from ops.loop import fleet_route
from tools import inbox_responder_runner as runner

NORMAL = "2026-10-03-1000-from-RSC-question.md"
TERMINAL = "2026-10-03-1001-from-LL-ack-TERMINAL.md"
NO_REPLY = "2026-10-03-1002-from-SS-fyi-no-reply.md"
OWN = "2026-10-03-1003-from-RC-outbound.md"


def test_skip_reason_is_the_kit_verdict():
    assert runner.fleet_skip_reason(NORMAL) is None
    assert runner.fleet_skip_reason(TERMINAL) == "terminal"
    assert runner.fleet_skip_reason(NO_REPLY) == "terminal"
    assert runner.fleet_skip_reason(OWN) == "self"


def test_drop_keeps_order_and_marks_skips_seen(tmp_path):
    keep = runner._drop_fleet_skips(tmp_path, [TERMINAL, NORMAL, OWN, NO_REPLY], "T1")
    assert keep == [NORMAL]
    data = json.loads(runner.skipped_path(tmp_path).read_text(encoding="ascii"))
    assert {v["reason"] for v in data.values()} == {"terminal", "self"}
    assert len(data) == 3
    # never in the answered record
    assert not runner.responder_state_path(tmp_path).exists()


def test_drop_is_idempotent_and_keeps_first_seen(tmp_path):
    runner._drop_fleet_skips(tmp_path, [TERMINAL], "T1")
    runner._drop_fleet_skips(tmp_path, [TERMINAL], "T2")
    data = json.loads(runner.skipped_path(tmp_path).read_text(encoding="ascii"))
    assert [v["ts"] for v in data.values()] == ["T1"]


def test_drop_survives_an_unwritable_record(tmp_path):
    # ops/runtime exists as a FILE: the record cannot be written, the filter
    # still answers (it is a pure function of the name)
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "runtime").write_text("x", encoding="ascii")
    assert runner._drop_fleet_skips(tmp_path, [TERMINAL, NORMAL], "T") == [NORMAL]


def test_nothing_to_skip_writes_nothing(tmp_path):
    assert runner._drop_fleet_skips(tmp_path, [NORMAL], "T") == [NORMAL]
    assert not runner.skipped_path(tmp_path).exists()


def test_run_once_never_reaches_a_spawn_on_a_terminal_note(monkeypatch, tmp_path):
    """Wired, not just defined: with only a TERMINAL note pending, the cycle
    ends `empty` before the attempt-cap gate and the spawner is never asked."""
    monkeypatch.setattr(runner, "pending_notes", lambda inbox, root, participants: [TERMINAL])
    monkeypatch.setattr(runner, "load_agreement", lambda root, participants, now: (
        {"counterparties": ["LL"], "grammar": runner.GRAMMAR_A5, "hop_budget": 1,
         "note": "n", "window_open": "x", "window_close": "y"}, None))
    monkeypatch.setattr(runner, "window_open", lambda rec, ts: True)
    monkeypatch.setattr(runner, "agreement_id_of", lambda rec: "a" * 12)
    monkeypatch.setattr(runner, "attempts_of",
                        lambda root: (_ for _ in ()).throw(AssertionError("past the skip")))
    seen = {}

    def _terminate(result, termination, detail, **kw):
        seen["t"] = (termination, detail)
        return result

    monkeypatch.setattr(runner, "_terminate", _terminate)
    monkeypatch.setattr(runner, "_finish", lambda result: result)
    monkeypatch.setattr(runner, "is_stopped", lambda root: False)
    runner.run_once(cycle_id="c", root=tmp_path, repo_root=tmp_path,
                    inbox=tmp_path, participants={"LL": tmp_path},
                    spawner=lambda req: (_ for _ in ()).throw(AssertionError("spawned")),
                    parent_env={}, now=runner.datetime.now,
                    measure_runner=lambda *a, **k: None, export=None, slot_root=None,
                    config=runner.RunnerConfig(), dry=False, log_root=tmp_path)
    assert seen.get("t") == ("empty", "none_pending")
    assert runner.skipped_path(tmp_path).is_file()


def test_write_idle_names_the_next_responder_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    fleet_route.write_idle(runner.POLL_INTERVAL_S)
    st = json.loads((tmp_path / "ops/loop/control/inbox_status.json").read_text(encoding="ascii"))
    assert st["state"] == "idle" and st["next_tick"] is not None and st["code"] == "RC"
