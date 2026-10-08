#!/usr/bin/env python
"""FLEET-KIT v8 item 14 - RC's inbox folded into the lane / loop tick.

MAIN 2026-10-05 0310 ORDER section 3-4 and 0327 RULING:
- every lane fire (and every loop-controller cycle) reads the inbox FIRST, via
  the kit's fleet_inbox.scan / classify, unattended;
- SKIP / ACK notes get a mechanical ledger line, never a note and never a spawn;
- ORDER / FIX / RULING escalate to a work row (never damped, never triaged);
- anything else gets at most ONE triage spawn per tick through the KIT's spawn,
  kind="triage", fleet_inbox.triage_spawn_kwargs(True) (sonnet, effort low,
  non-bare: kit v11 ruling R1, RC's floors live in hooks);
- an ANSWER verdict leaves as ONE batched note per destination with a HOP line,
  only when may_reply() and OutboundCap allow it;
- ONE agreement record: MAIN a counterparty plus a MAIN outbox row for the
  sha256 check, no hop budget of its own (the kit's 120 / 24 h is the budget).

Nothing here starts a real process or reads the live inbox: every root is a
tmp dir and every spawn goes through the kit's own seams with a fake `run`.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tick_mod = _load("rc_loop_inbox_tick_test", ROOT / "ops" / "loop" / "inbox_tick.py")
fi = tick_mod.fleet_inbox
fh = tick_mod.fleet_headless

NOW = datetime(2026, 10, 7, 22, 0, 0)


# ---- fixtures --------------------------------------------------------------

def _record(**over):
    rec = {
        "schema": tick_mod.AGREEMENT_SCHEMA,
        "counterparties": ["CS", "EW", "LW", "MAIN", "RSC", "SS"],
        "main": {"code": "MAIN", "outbox": "X:/main/moon_sync_outbox"},
        "budget": "kit",
        "expires": "2026-11-01T00:00:00",
        "authored_by": "operator",
        "authored_at": "2026-10-07T22:00:00",
        "note": "MAIN 0327 RULING: one record, no own hop budget",
    }
    rec.update(over)
    return rec


PARTS = {"CS": Path("cs"), "EW": Path("ew"), "LW": Path("lw"),
         "RSC": Path("rsc"), "SS": Path("ss")}
RETIRED = {"LL"}


def _note(inbox: Path, name: str, body: str, mtime: float) -> Path:
    import os
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / name
    p.write_text(body, encoding="ascii", newline="\n")
    os.utime(p, (mtime, mtime))
    return p


def _seen_rows(root: Path) -> list:
    p = root / fi.SEEN_REL
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="ascii").splitlines() if x]


class _Spy:
    """A spawn seam that records calls and answers with a canned verdict."""

    def __init__(self, text="VERDICT: ACK"):
        self.calls, self.text = [], text

    def __call__(self, root, code, prompt, **kw):
        self.calls.append({"root": root, "code": code, "prompt": prompt, **kw})
        return {"rc": 0, "result": self.text, "kind": kw.get("kind")}


def _tick(root, inbox, **kw):
    kw.setdefault("agreement", _record())
    kw.setdefault("participants", {k: root / "sib" / k for k in PARTS})
    kw.setdefault("retired", RETIRED)
    kw.setdefault("verify", lambda note, outbox: True)
    kw.setdefault("now", NOW)
    return tick_mod.tick(root, inbox=inbox, **kw)


# ---- 1. agreement shape (MAIN 0327 RULING) -----------------------------------

def test_the_v8_record_arms():
    rec, detail = tick_mod.validate_agreement(_record(), participants=PARTS,
                                              retired=RETIRED, now=NOW)
    assert rec is not None, detail
    assert detail == ""


@pytest.mark.parametrize("over,want", [
    ({"hop_budget": 32}, "own_hop_budget"),
    ({"counterparties": ["CS", "EW", "LL", "LW", "MAIN", "RSC", "SS"]}, "retired"),
    ({"counterparties": ["CS", "EW", "LW", "RSC", "SS"]}, "main_missing"),
    ({"counterparties": ["CS", "LW", "MAIN", "RSC", "SS"]}, "participant_missing"),
    ({"counterparties": ["CS", "EW", "LW", "MAIN", "RSC", "SS", "ZZ"]}, "unmapped"),
    ({"main": {"code": "MAIN"}}, "main_outbox"),
    ({"main": None}, "main_outbox"),
    ({"budget": 32}, "budget"),
    ({"schema": "old"}, "schema"),
    ({"expires": "not-a-date"}, "expires"),
    ({"expires": "2026-10-01T00:00:00"}, "expired"),
])
def test_the_record_fails_closed(over, want):
    rec, detail = tick_mod.validate_agreement(_record(**over), participants=PARTS,
                                              retired=RETIRED, now=NOW)
    assert rec is None
    assert want in detail


def test_the_old_32_hop_record_does_not_arm_the_tick():
    old = {"counterparties": ["CS", "LL", "LW", "RSC", "SS"], "hop_budget": 32,
           "expires": "2026-11-01T00:00:00", "note": "x", "window_open": "x",
           "window_close": "x", "grammar": "A5-measurement-only",
           "model": "claude-sonnet-4-5", "contract_version": 2}
    rec, detail = tick_mod.validate_agreement(old, participants=PARTS,
                                              retired=RETIRED, now=NOW)
    assert rec is None and detail


def test_load_agreement_reads_the_runtime_record(tmp_path):
    p = tmp_path / tick_mod.AGREEMENT_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_record()), encoding="ascii")
    rec, detail = tick_mod.load_agreement(tmp_path, participants=PARTS,
                                          retired=RETIRED, now=NOW)
    assert rec is not None, detail
    assert tick_mod.load_agreement(tmp_path / "nope", participants=PARTS,
                                   retired=RETIRED, now=NOW) == (None, "no_agreement")


# ---- 2. the tick reads the inbox: classification routing --------------------

def test_an_empty_inbox_is_a_zero_tick(tmp_path):
    spy = _Spy()
    s = _tick(tmp_path, tmp_path / "inbox", spawn=spy)
    assert s["unseen"] == 0 and spy.calls == []
    assert tick_mod.summary_line(s).startswith("inbox: 0 unseen")


def test_ack_and_skip_notes_get_a_ledger_line_and_no_spawn(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-ANSWER-to-RC-x.md", "# From SS - ANSWER\n", 1)
    _note(inbox, "2026-10-07-1001-from-CS-INFORMATION-to-RC-y.md", "# x\n", 2)
    _note(inbox, "2026-10-07-1002-from-LW-QUESTION-to-RC-z-TERMINAL.md", "# x\n", 3)
    _note(inbox, "2026-10-07-1003-from-RC-ANSWER-to-MAIN-own.md", "# x\n", 4)
    spy = _Spy()
    s = _tick(tmp_path, inbox, spawn=spy)
    assert spy.calls == [], "a mechanical ack never spawns"
    assert s["acked"] == 2 and s["skipped"] == 2
    assert {r["action"] for r in _seen_rows(tmp_path)} == {"ack", "skip"}
    assert len(_seen_rows(tmp_path)) == 4
    # a second fire finds nothing unseen
    assert _tick(tmp_path, inbox, spawn=spy)["unseen"] == 0


def test_an_order_from_main_escalates_to_a_work_row_never_a_triage(tmp_path):
    inbox = tmp_path / "inbox"
    name = "2026-10-07-2200-from-MAIN-ORDER-to-RC-do-a-thing.md"
    _note(inbox, name, "# From MAIN - ORDER to RC\n\nHOP: 1\n", 1)
    spy, asked = _Spy(), []
    s = _tick(tmp_path, inbox, spawn=spy,
              verify=lambda note, outbox: asked.append((Path(note).name, outbox)) or True)
    assert spy.calls == []
    assert s["escalated"] == 1
    assert asked == [(name, "X:/main/moon_sync_outbox")], "sha256 check vs MAIN outbox row"
    rows = [json.loads(x) for x in (tmp_path / tick_mod.WORK_REL)
            .read_text(encoding="ascii").splitlines()]
    assert rows[0]["op"] == "queued", "RM-685: queued through kit enqueue_work"
    assert rows[0]["note"] == name and rows[0]["cls"] == "ORDER"
    (row,) = tick_mod.pending(tmp_path)
    assert row["note"] == name and row["provenance"] == "main-verified"
    assert _seen_rows(tmp_path)[0]["verdict"] == "ESCALATED"


def test_an_unverified_main_order_is_flagged_not_dropped(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-2200-from-MAIN-FIX-to-RC-x.md", "# x\n", 1)
    _tick(tmp_path, inbox, spawn=_Spy(), verify=lambda n, o: False)
    (row,) = tick_mod.pending(tmp_path)
    assert row["op"] == "queued" and row["cls"] == "FIX"
    assert row["provenance"] == "main-unverified"


def test_an_unclassifiable_note_gets_one_triage_through_the_kit_shape(tmp_path):
    inbox = tmp_path / "inbox"
    name = "2026-10-07-1000-from-SS-QUESTION-to-RC-which-port.md"
    _note(inbox, name, "# From SS - QUESTION to RC\n\nwhich port?\n", 1)
    spy = _Spy("VERDICT: NOREPLY")
    s = _tick(tmp_path, inbox, spawn=spy)
    (c,) = spy.calls
    assert c["code"] == "RC" and c["kind"] == "triage" and c["note"] == name
    # kit v11 ruling R1: RC's floors live in hooks, so triage runs non-bare.
    for k, v in fi.triage_spawn_kwargs(True).items():
        assert k in c and c[k] == v, k
    assert c["bare"] is False
    assert c["floors_in_hooks"] is True
    assert "which port?" in c["prompt"]
    assert s["triaged"] == 1
    assert _seen_rows(tmp_path)[0]["verdict"] == "NOREPLY"


def test_rc_declares_its_floors_live_in_hooks():
    # Literal expectation (kit v11 R1): precommit_gate PreToolUse + .githooks.
    assert tick_mod.FLOORS_IN_HOOKS is True


def test_at_most_max_triage_spawns_per_tick_the_rest_wait(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    _note(inbox, "2026-10-07-1001-from-CS-QUESTION-to-RC-b.md", "# x\n", 2)
    spy = _Spy()
    s = _tick(tmp_path, inbox, spawn=spy, max_triage=1)
    assert len(spy.calls) == 1 and s["deferred"] == 1
    assert len(_seen_rows(tmp_path)) == 1, "the deferred note stays unseen"
    _tick(tmp_path, inbox, spawn=spy, max_triage=1)
    assert len(spy.calls) == 2 and len(_seen_rows(tmp_path)) == 2


def test_no_armed_agreement_means_no_triage_spawn_but_free_acks_still_run(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    _note(inbox, "2026-10-07-1001-from-SS-ANSWER-to-RC-b.md", "# x\n", 2)
    spy = _Spy()
    s = _tick(tmp_path, inbox, spawn=spy, agreement=None)
    assert spy.calls == []
    assert s["acked"] == 1 and s["deferred"] == 1
    assert s["armed"] is False


def test_a_spawn_refusal_leaves_the_note_unseen(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)

    def refuse(*a, **k):
        raise fh.Refused("run budget exhausted (120/120)")

    s = _tick(tmp_path, inbox, spawn=refuse)
    assert s["deferred"] == 1 and _seen_rows(tmp_path) == []
    assert "refused" in s["errors"][0]


def test_an_answer_verdict_leaves_as_one_batched_note_with_a_hop_line(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    _note(inbox, "2026-10-07-1001-from-SS-QUESTION-to-RC-b.md", "# x\n", 2)
    spy = _Spy("VERDICT: ANSWER\nport 8888")
    sent = []
    s = _tick(tmp_path, inbox, spawn=spy, max_triage=2,
              deliver=lambda to, fname, body: sent.append((to, fname, body)) or 1)
    assert len(sent) == 1, "several answers to one destination go in ONE note"
    to, fname, body = sent[0]
    assert to == "SS" and "-from-RC-ANSWER-to-SS-batched-2-answers" in fname
    assert "HOP: 2" in body and body.count("port 8888") == 2
    assert s["sent"] == 1
    rows = (tmp_path / fi.OUTBOUND_REL).read_text(encoding="ascii").splitlines()
    assert json.loads(rows[0])["to"] == "SS"


def test_the_default_delivery_writes_rehashes_and_ledgers(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    dest = tmp_path / "sib" / "SS"
    dest.mkdir(parents=True)
    s = _tick(tmp_path, inbox, spawn=_Spy("VERDICT: ANSWER\nport 8888"))
    (sent,) = list(dest.iterdir())
    assert "-from-RC-ANSWER-to-SS-" in sent.name and s["sent"] == 1
    row = json.loads((tmp_path / tick_mod.DELIVERIES_REL).read_text(encoding="ascii"))
    import hashlib
    assert row["sha256"] == hashlib.sha256(sent.read_bytes()).hexdigest()
    assert row["reached"] == "1/1"


def test_an_unreachable_destination_holds_the_note(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    s = _tick(tmp_path, inbox, spawn=_Spy("VERDICT: ANSWER\nok"))
    assert s["sent"] == 0 and s["held"] == 1
    assert list((tmp_path / tick_mod.HELD_REL).iterdir())


def test_the_outbound_cap_holds_an_answer(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n", 1)
    cap = fi.OutboundCap(tmp_path)
    for i in range(fi.OUTBOUND_CAP):
        cap.record(f"n{i}.md", "ANSWER", "CS")
    sent = []
    s = _tick(tmp_path, inbox, spawn=_Spy("VERDICT: ANSWER\nok"),
              deliver=lambda *a: sent.append(a) or 1)
    assert sent == [] and s["held"] == 1


def test_no_reply_past_the_hop_limit(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md", "# x\n\nHOP: 2\n", 1)
    spy = _Spy("VERDICT: ANSWER\nok")
    s = _tick(tmp_path, inbox, spawn=spy, deliver=lambda *a: 1)
    assert spy.calls == [], "classify() already acks a note at the hop limit"
    assert s["acked"] == 1 and s["sent"] == 0


def test_a_non_counterparty_sender_gets_no_reply(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-ZZ-QUESTION-to-RC-a.md", "# x\n", 1)
    sent = []
    s = _tick(tmp_path, inbox, spawn=_Spy("VERDICT: ANSWER\nok"),
              deliver=lambda *a: sent.append(a) or 1)
    assert sent == [] and s["held"] == 1


def test_dry_writes_no_ledger(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-ANSWER-to-RC-x.md", "# x\n", 1)
    _note(inbox, "2026-10-07-2200-from-MAIN-ORDER-to-RC-y.md", "# x\n", 2)
    spy = _Spy()
    s = _tick(tmp_path, inbox, spawn=spy, dry=True)
    assert s["unseen"] == 2 and spy.calls == []
    assert not (tmp_path / fi.SEEN_REL).exists()
    assert not (tmp_path / tick_mod.WORK_REL).exists()


def test_a_held_tick_lock_skips_the_fire(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-ANSWER-to-RC-x.md", "# x\n", 1)
    lock = tmp_path / tick_mod.LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    import time
    lock.write_text(json.dumps({"pid": 1, "ts": time.time()}), encoding="ascii")
    s = _tick(tmp_path, inbox, spawn=_Spy())
    assert s["locked"] is True and _seen_rows(tmp_path) == []


def test_a_stale_tick_lock_is_reclaimed(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, "2026-10-07-1000-from-SS-ANSWER-to-RC-x.md", "# x\n", 1)
    lock = tmp_path / tick_mod.LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 1, "ts": 0}), encoding="ascii")
    s = _tick(tmp_path, inbox, spawn=_Spy())
    assert s["locked"] is False and len(_seen_rows(tmp_path)) == 1
    assert not lock.exists(), "the tick releases its lock"


# ---- 3. usage kind labelling through the REAL kit spawn ----------------------

def test_the_default_spawn_is_the_kit_and_labels_the_usage_line_triage(tmp_path):
    inbox = tmp_path / "inbox"
    name = "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md"
    _note(inbox, name, "# x\n", 1)
    argvs = []

    def run(argv, **kw):
        argvs.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"result": "VERDICT: NOREPLY", "total_cost_usd": 0.01}), "")

    class _C:
        def close(self):
            return None

    seams = {"run": run, "url_source": lambda: "http://127.0.0.1:18080",
             "connect": lambda addr, timeout=2.0: _C(),
             "exe_source": lambda: "claude-fake.exe"}
    s = _tick(tmp_path, inbox, spawn_kw=seams)
    assert s["triaged"] == 1, s
    (argv,) = argvs
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low"
    assert "--bare" not in argv and "--strict-mcp-config" in argv, "v11 R1: non-bare"
    lines = [json.loads(x) for x in (tmp_path / fh.USAGE_REL)
             .read_text(encoding="ascii").splitlines()]
    assert lines[-1]["kind"] == "triage" and lines[-1]["note"] == name


def test_fleet_route_passes_kind_through_to_the_kit(monkeypatch, tmp_path):
    fr = _load("rc_ops_loop_fleet_route_kind_test", ROOT / "ops" / "loop" / "fleet_route.py")
    seen = {}

    def fake(root, code, prompt, **kw):
        seen.update(kw)
        return {"rc": 0, "result": "x"}

    monkeypatch.setattr(fr, "_kit_spawn", fake)
    monkeypatch.setattr(fr, "_launch", lambda argv, **kw: None)

    class _HE:
        class HeadlessRouteRefused(Exception):
            pass

        @staticmethod
        def resolve_base_url(caller):
            return "http://127.0.0.1:18080"

        @staticmethod
        def _log_refusal(*a):
            return None

    monkeypatch.setattr(fr, "_headless_env", lambda: _HE)
    fr.spawn("p", caller="t", note="drain-x", kind="build", root=tmp_path)
    assert seen["kind"] == "build"
    seen.clear()
    fr.spawn("p", caller="t", note="drain-x", root=tmp_path)
    assert "kind" not in seen, "an omitted kind keeps the pre-v8 call shape"


def test_drain_runs_are_labelled_build():
    src = (ROOT / "ops" / "loop" / "drain_waves_2_3.py").read_text(encoding="utf-8")
    call = src[src.index("fr.spawn(prompt, caller=CALLER"):]
    call = call[:call.index("\n    except")]
    assert 'kind="build"' in call


# ---- 4. the fire's checklist carries the inbox step (item 13 d) ---------------

def test_fire_step_completes_the_inbox_row_with_the_summary(tmp_path):
    lp = _load("rc_loop_lane_progress_inbox_test", ROOT / "ops" / "loop" / "lane_progress.py")
    prog = lp.LaneProgress.for_lane(2, 7, [("I1", tick_mod.STEP_TASK), ("L1", "Prepare")],
                                    root=tmp_path, emit=lambda _s: None)
    prog.start()
    doc = json.loads((tmp_path / "ops/loop/control/progress/lane-2.json").read_text("ascii"))
    assert doc["checklist"][0]["id"] == "I1"
    s = tick_mod.fire_step(prog, root=tmp_path, inbox=tmp_path / "inbox",
                           agreement=None, participants={}, retired=set(),
                           spawn=_Spy(), now=NOW)
    assert s["unseen"] == 0
    doc = json.loads((tmp_path / "ops/loop/control/progress/lane-2.json").read_text("ascii"))
    assert [r["id"] for r in doc["checklist"]] == ["L1"]
    assert doc["step"].startswith("I1 inbox: 0 unseen")
    last = json.loads((tmp_path / tick_mod.LAST_REL).read_text(encoding="ascii"))
    assert last["unseen"] == 0


def test_fire_step_never_raises(tmp_path):
    lp = _load("rc_loop_lane_progress_inbox_test2", ROOT / "ops" / "loop" / "lane_progress.py")
    prog = lp.LaneProgress.for_lane(0, 1, [("I1", "x")], root=tmp_path, emit=lambda _s: None)
    prog.start()

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    s = tick_mod.fire_step(prog, tick=boom)
    assert s["errors"] and "kaboom" in s["errors"][0]


def test_launch_lane_reads_the_inbox_first(tmp_path, monkeypatch):
    launcher = _load("rc_loop_lane_launcher_inbox_test", ROOT / "ops" / "loop" / "lane_launcher.py")
    lp = launcher._progress_mod()
    lanes = launcher.lanes
    root = tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"
    wt = tmp_path / "wt"
    wt.mkdir()
    claim = lanes.try_acquire_lane("ds", run_id="r1", worktree=str(wt), root=root)
    assert claim["ok"]
    monkeypatch.setattr(launcher, "ensure_worktree", lambda *a, **k: wt)
    order = []
    real = lp.LaneProgress._write

    def spy(self, step, status):
        order.append([r["id"] for r in self.cl.rows()])
        return real(self, step, status)

    monkeypatch.setattr(lp.LaneProgress, "_write", spy)

    def fake_tick(root, **kw):
        order.append("TICK")
        return {"unseen": 0}

    import os

    class _P:
        pid = os.getpid()

    launcher.launch_lane("ds", run_id="r1", token=claim["token"], log_dir=tmp_path / "l",
                         spawn=lambda *a: _P(), progress_root=tmp_path / "main",
                         session=1, inbox_tick=fake_tick)
    assert order[0] == ["I1", "L1", "L2", "L3"], "the inbox step is first on the list"
    assert order[1] == ["I1", "L1", "L2", "L3"], "I1 marked running before the pass"
    assert order[2] == "TICK" and order[3] == ["L1", "L2", "L3"]
    lanes.release_lane(claim["token"])


def test_loop_controller_cycle_checklist_starts_with_the_inbox(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "loop_controller_uut_inbox", ROOT / "ops" / "loop" / "loop_controller.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    prog = lc.cycle_checklist(3, root=tmp_path, emit=lambda _s: None)
    assert [r["id"] for r in prog.cl.rows()][:2] == ["I1", "C1"]
    src = (ROOT / "ops" / "loop" / "loop_controller.py").read_text(encoding="utf-8")
    body = src[src.index("def main():"):]
    assert "inbox_tick.fire_step(prog" in body
    assert body.index("prog.start()") < body.index("inbox_tick.fire_step(prog")


def test_cli_main_writes_last_summary_for_scheduled_runs(tmp_path, monkeypatch):
    # Item F: RC-InboxResponder now runs this CLI under pythonw (no stdout), so
    # the summary file is the only read-back of a scheduled fire.
    fake = {"ts": "t", "unseen": 3, "armed": True, "errors": []}
    monkeypatch.setattr(tick_mod, "tick", lambda root, **kw: dict(fake))
    assert tick_mod.main(["--root", str(tmp_path)]) == 0
    last = json.loads((tmp_path / tick_mod.LAST_REL).read_text(encoding="ascii"))
    assert last["unseen"] == 3 and last["armed"] is True


def test_cli_main_dry_writes_no_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(tick_mod, "tick", lambda root, **kw: {"unseen": 0})
    assert tick_mod.main(["--root", str(tmp_path), "--dry"]) == 0
    assert not (tmp_path / tick_mod.LAST_REL).exists()
