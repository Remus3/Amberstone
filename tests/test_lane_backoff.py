"""ops/loop/lane_backoff.py: MAIN ORDER 2026-11-14 0930 section 2 (D1 back-off).

A lane whose last 3 worker cycles made no own commit skips its next spawn until its
queue or the rotator has new work; each skip episode is a ledger line. The s144
driver is gitignored, so the decision and the ledger live in this tracked module and
are pinned here. Every path is under tmp_path; nothing live is read or written."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ops.loop import lane_backoff as BO


def _cyc(n, own=0, outcome="completed", fp=None):
    rec = {"cycle": n, "run_id": f"s144d{n:03d}-abc", "outcome": outcome,
           "own_commits": own, "new_commits": own}
    if fp is not None:
        rec["work_fp"] = fp
    return rec


def _write_cycles(path: Path, recs) -> Path:
    path.write_bytes("".join(json.dumps(r) + "\n" for r in recs).encode("ascii"))
    return path


def _ledger(path: Path) -> list:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="ascii").splitlines() if x]


# ------------------------------------------------------------------ the streak

def test_three_empty_worker_cycles_are_a_streak():
    assert BO.empty_streak([_cyc(1), _cyc(2), _cyc(3)])


def test_two_empty_cycles_are_not_a_streak():
    assert not BO.empty_streak([_cyc(1), _cyc(2)])


def test_one_commit_in_the_last_three_breaks_the_streak():
    assert not BO.empty_streak([_cyc(1), _cyc(2, own=1), _cyc(3), _cyc(4)])
    assert BO.empty_streak([_cyc(1, own=2), _cyc(2), _cyc(3), _cyc(4)])


def test_cycles_with_no_worker_neither_count_nor_break_the_streak():
    recs = [_cyc(1), _cyc(2, outcome="lane_held"), _cyc(3, outcome="rate_limited"),
            _cyc(4), _cyc(5, outcome="launch_failed"), _cyc(6)]
    assert BO.empty_streak(recs)


def test_an_unknown_commit_count_is_never_empty():
    rec = _cyc(3)
    del rec["own_commits"], rec["new_commits"]
    assert not BO.empty_streak([_cyc(1), _cyc(2), rec])


def test_new_commits_is_the_fallback_for_an_older_record():
    rec = _cyc(3)
    del rec["own_commits"]
    assert BO.empty_streak([_cyc(1), _cyc(2), rec])


# ------------------------------------------------------------------ the decision

def test_three_empty_cycles_skip_and_one_new_queue_item_spawns(tmp_path):
    """The ORDER's ACCEPT: 3 empty cycles skip; 1 new queue item spawns."""
    root = tmp_path
    prompts = root / BO.PROMPTS_REL
    prompts.mkdir(parents=True)
    tmpl = prompts / "s144-ds.tmpl"
    tmpl.write_bytes(b"Order:\n  1. RM-100 (closed)\n")
    (prompts / "s144-common.tmpl").write_bytes(b"common\n")
    cycles = _write_cycles(prompts / "s144_ds_cycles.jsonl", [_cyc(1), _cyc(2), _cyc(3)])
    state = prompts / "s144_ds_backoff.json"
    ledger = root / BO.LEDGER_REL

    def check(now):
        return BO.check(root, "ds", cycles_path=cycles, state_path=state,
                        ledger_path=ledger, now=now, git_blobs=lambda *_a, **_k: {})

    first = check(1000.0)
    assert first["skip"] is True
    assert "3 consecutive" in first["reason"]
    rows = _ledger(ledger)
    assert len(rows) == 1 and rows[0]["event"] == "skip" and rows[0]["lane"] == "ds"
    assert rows[0]["empty_runs"] == [r["run_id"] for r in (_cyc(1), _cyc(2), _cyc(3))]
    # a later poll with no new work still skips, and does not spam the ledger
    assert check(1030.0)["skip"] is True
    assert len(_ledger(ledger)) == 1
    # ONE new queue item -> spawn, and the resume is a ledger line too
    tmpl.write_bytes(b"Order:\n  1. RM-100 (closed)\n  2. RM-101 new row\n")
    third = check(1060.0)
    assert third["skip"] is False and "new work" in third["reason"]
    rows = _ledger(ledger)
    assert [r["event"] for r in rows] == ["skip", "resume"]


def test_the_cycle_start_fingerprint_is_the_baseline():
    fp_then = "a" * 64
    recs = [_cyc(1), _cyc(2), _cyc(3, fp=fp_then)]
    same = BO.decide(recs, fp_then, {}, now=10.0)
    assert same.skip
    moved = BO.decide(recs, "b" * 64, {}, now=10.0)
    assert not moved.skip and "new work" in moved.reason


def test_an_older_record_without_a_fingerprint_arms_on_the_first_check():
    recs = [_cyc(1), _cyc(2), _cyc(3)]
    d1 = BO.decide(recs, "f1", {}, now=10.0)
    assert d1.skip and d1.event == "skip" and d1.state["fingerprint"] == "f1"
    d2 = BO.decide(recs, "f1", d1.state, now=20.0)
    assert d2.skip and d2.event is None
    d3 = BO.decide(recs, "f2", d2.state, now=30.0)
    assert not d3.skip and d3.event == "resume"


def test_a_new_empty_cycle_after_a_resume_skips_again():
    recs = [_cyc(1), _cyc(2), _cyc(3)]
    d1 = BO.decide(recs, "f1", {}, now=10.0)
    d2 = BO.decide(recs, "f2", d1.state, now=20.0)
    assert not d2.skip
    d3 = BO.decide(recs + [_cyc(4, fp="f2")], "f2", d2.state, now=30.0)
    assert d3.skip and d3.event == "skip"


def test_a_long_skip_logs_again_after_an_hour_with_the_count():
    recs = [_cyc(1), _cyc(2), _cyc(3)]
    d = BO.decide(recs, "f", {}, now=0.0)
    for t in range(30, 3600, 30):
        d = BO.decide(recs, "f", d.state, now=float(t))
        assert d.event is None
    d = BO.decide(recs, "f", d.state, now=3600.0)
    assert d.skip and d.event == "skip" and d.state["skips"] > 100


def test_no_streak_clears_a_skipping_state_with_a_resume():
    d1 = BO.decide([_cyc(1), _cyc(2), _cyc(3)], "f", {}, now=0.0)
    d2 = BO.decide([_cyc(1), _cyc(2), _cyc(3), _cyc(4, own=1)], "f", d1.state, now=5.0)
    assert not d2.skip and d2.event == "resume" and d2.state == {}


def test_a_productive_lane_never_writes_state_or_ledger(tmp_path):
    cycles = _write_cycles(tmp_path / "c.jsonl", [_cyc(1, own=1), _cyc(2), _cyc(3)])
    out = BO.check(tmp_path, "queue", cycles_path=cycles, state_path=tmp_path / "s.json",
                   ledger_path=tmp_path / "l.jsonl", now=1.0,
                   git_blobs=lambda *_a, **_k: pytest.fail("no fingerprint without a streak"))
    assert out["skip"] is False
    assert not (tmp_path / "s.json").exists() and not (tmp_path / "l.jsonl").exists()


# ------------------------------------------------------------------ the fingerprint

def test_fingerprint_moves_on_each_new_work_signal(tmp_path):
    root = tmp_path
    prompts = root / BO.PROMPTS_REL
    prompts.mkdir(parents=True)
    (prompts / "s144-gated.tmpl").write_bytes(b"t\n")
    blobs = {"ROADMAP.md": "r1", "BACKLOG.md": "b1", "tools/headless-gated.md": "d1"}

    def fp(**kw):
        return BO.fingerprint(BO.lane_signals(root, "gated", git_blobs=lambda *_a, **_k: blobs,
                                              **kw))

    base = fp(in_game=False)
    assert fp(in_game=False) == base
    assert fp(in_game=True) != base                          # a live game for gated
    blobs["ROADMAP.md"] = "r2"
    assert fp(in_game=False) != base                         # a new row on main
    blobs["ROADMAP.md"] = "r1"
    kick = root / BO.LANES_REL / "S144_WORK_GATED"
    kick.parent.mkdir(parents=True)
    kick.write_bytes(b"merger: new work\n")
    assert fp(in_game=False) != base                         # the rotator / merger kick


def test_git_blobs_reads_main_and_skips_a_missing_path(tmp_path):
    def run(args, **kw):
        assert args[:3] == ["git", "ls-tree", "main"]
        return subprocess.CompletedProcess(args, 0, stdout=(
            "100644 blob aaa\tROADMAP.md\n100644 blob bbb\tBACKLOG.md\n"), stderr="")

    got = BO.git_blobs(tmp_path, ["ROADMAP.md", "BACKLOG.md", "tools/x.md"], run=run)
    assert got == {"ROADMAP.md": "aaa", "BACKLOG.md": "bbb"}


def test_tail_cycles_reads_only_the_tail_and_skips_bad_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_bytes(b"{bad\n" + b"".join(json.dumps(_cyc(i)).encode() + b"\n"
                                         for i in range(1, 400)))
    recs = BO.tail_cycles(p, tail_bytes=4096)
    assert recs and recs[-1]["cycle"] == 399 and all("cycle" in r for r in recs)
    assert BO.tail_cycles(tmp_path / "absent.jsonl") == []


def test_ledger_and_state_files_are_ascii_lf(tmp_path):
    cycles = _write_cycles(tmp_path / "c.jsonl", [_cyc(1), _cyc(2), _cyc(3)])
    BO.check(tmp_path, "research", cycles_path=cycles, state_path=tmp_path / "s.json",
             ledger_path=tmp_path / "l.jsonl", now=1.0, git_blobs=lambda *_a, **_k: {})
    for name in ("s.json", "l.jsonl"):
        data = (tmp_path / name).read_bytes()
        assert b"\r" not in data
        data.decode("ascii")


def test_tail_cycles_takes_a_str_path_and_reads_the_same_records(tmp_path):
    """s165 C10: the read is Path(path).open("rb"), so a str path (the shape a driver
    may pass) reads exactly what the Path does, and an absent str path is []."""
    p = tmp_path / "c.jsonl"
    p.write_bytes(b"".join(json.dumps(_cyc(i)).encode() + b"\n" for i in range(1, 50)))
    assert BO.tail_cycles(str(p), tail_bytes=512) == BO.tail_cycles(p, tail_bytes=512)
    assert BO.tail_cycles(str(p))[-1]["cycle"] == 49
    assert BO.tail_cycles(str(tmp_path / "absent.jsonl")) == []
