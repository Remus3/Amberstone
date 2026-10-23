"""RM-728 (KF-P11) - the progress-file reaper in tools/progress_watch.py.

FLEET-COMMON item 12 says a progress file silent for 2x its ETA is a failure,
but tools/progress_watch.py only REPORTED it (its docstring: "this tool only
reads and reports"), and no writer expires its own file, so
ops/loop/control/progress/ only ever grew (152 files at the 2026-10-09 review;
rows 'running' for days). The reaper:

- marks a running (or kit 'blocked') row failed once it is silent past 2x
  its ETA - unless its recorded owner is alive or unknown and the silence is
  still inside the kit's ABANDON_S grace (RM-785 b: only a PROVEN-dead owner
  is reaped at 2x; tests/test_progress_reaper_rm785.py);
- moves finished (done / failed) rows older than 7 days - by BOTH the
  'updated' stamp and the file mtime - to the Recycle Bin, through the
  checked core.recycle_bin path, never an unlink;
- only touches a file it can prove is an item-12 record: a top-level *.json
  regular file whose stem is a kit task stem and whose "task" equals that
  stem; lane-*.json, inbox-responder.json and loop.json are kept by name;
- is plan-only unless apply=True, and refuses a progress dir outside the
  repo root.

Every test runs on tmp_path with a fake bin and a fake owner probe: no real
file is recycled and no real process is probed.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rc_tools_progress_watch_rm728", _ROOT / "tools" / "progress_watch.py")
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

_kspec = importlib.util.spec_from_file_location(
    "rc_fleet_kit_fleet_headless_rm728", _ROOT / "ops" / "fleet_kit" / "fleet_headless.py")
kit = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(kit)

NOW = 1_800_000_000.0
DAY = 86400.0
# RM-785 (b): a row is reaped at 2x its ETA only when its owner is PROVEN
# dead, so the mark-at-2x tests plant this owner and answer Alive(False).
OWNER = {"pid": 4242, "start": 1.0}


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _plant(d: Path, stem: str, *, status="running", age_s=0.0, eta_s=600,
           mtime_age=None, task=None, extra=None, raw=None) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.json"
    if raw is not None:
        p.write_text(raw, encoding="ascii", newline="\n")
    else:
        doc = {"task": stem if task is None else task, "pct": 40, "step": "planted",
               "eta_s": eta_s, "status": status, "updated": _iso_utc(NOW - age_s),
               "checklist": [{"id": "A1", "task": "x", "state": None, "eta_s": None}]}
        doc.update(extra or {})
        p.write_text(json.dumps(doc), encoding="ascii", newline="\n")
    t = NOW - (age_s if mtime_age is None else mtime_age)
    os.utime(p, (t, t))
    return p


class Bin:
    """Fake checked recycler: moves the file into tmp 'bin' and says so."""

    def __init__(self, tmp: Path, result=None):
        self.calls = []
        self.dest = tmp / "fakebin"
        self.result = result

    def __call__(self, path):
        self.calls.append(Path(path).name)
        if self.result is not None:
            return self.result(Path(path))
        self.dest.mkdir(exist_ok=True)
        Path(path).replace(self.dest / Path(path).name)
        return SimpleNamespace(ok=True, nuked=False, detail="landed (fake)")


class Alive:
    def __init__(self, answer=None, hook=None):
        self.answer = answer
        self.hook = hook
        self.calls = []

    def __call__(self, owner):
        self.calls.append(owner)
        if self.hook:
            self.hook()
        return self.answer


@pytest.fixture
def d(tmp_path):
    return tmp_path / "ops" / "loop" / "control" / "progress"


@pytest.fixture(autouse=True)
def _no_live_steer(monkeypatch):
    """A watch run inside main() must never reach the live steer log (run()
    swallows a send error, so the attempt is recorded and checked after)."""
    attempts = []
    monkeypatch.setattr(pw, "steer_send", lambda text, key: attempts.append(key))
    yield
    assert attempts == []


def _reap(tmp_path, d, *, apply=True, recycle=None, alive=None, **kw):
    return pw.reap(progress_dir=d, root=tmp_path, now=NOW, apply=apply,
                   recycle=recycle if recycle is not None else Bin(tmp_path),
                   alive=alive if alive is not None else Alive(None), **kw)


def _doc(p: Path) -> dict:
    return json.loads(p.read_text(encoding="ascii"))


# ---------------------------------------------------------------- mark failed

def test_running_row_past_2x_eta_is_marked_failed_keeping_its_fields(tmp_path, d):
    p = _plant(d, "job", age_s=1500, eta_s=600, extra={"owner": OWNER})   # 2.5x
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert rep["marked"] == ["job"]
    doc = _doc(p)
    assert doc["status"] == "failed"
    assert doc["pct"] == 40 and doc["step"] == "planted" and doc["eta_s"] == 600
    assert doc["checklist"] and doc["task"] == "job"
    assert "2x" in doc["reason"] and len(doc["reason"]) <= 120
    assert pw.parse_updated(doc["updated"]) == pytest.approx(NOW)
    doc_bytes = p.read_bytes()
    doc_bytes.decode("ascii")
    assert not list(d.glob("*.tmp"))


@pytest.mark.parametrize("age,eta,marked", [
    (1200, 600, False),     # exactly 2x: not past it
    (1000, 600, False),     # 1.67x: report rung only
    (1201, 600, True),
    (599, 0, False),        # eta 0 floored to MIN_ETA_S (300): 2x = 600
    (601, None, True),
])
def test_only_rows_past_2x_their_eta_are_marked(tmp_path, d, age, eta, marked):
    _plant(d, "job", age_s=age, eta_s=eta, extra={"owner": OWNER})
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert (rep["marked"] == ["job"]) is marked
    assert (_doc(d / "job.json")["status"] == "failed") is marked


def test_kit_blocked_row_is_reaped_like_running(tmp_path, d):
    _plant(d, "blk", status="blocked", age_s=5000, eta_s=600,
           extra={"reason": "proxy unreachable", "owner": OWNER})
    assert _reap(tmp_path, d, alive=Alive(False))["marked"] == ["blk"]


def test_fresh_blocked_row_classifies_as_blocked_not_malformed(tmp_path, d):
    _plant(d, "blk", status="blocked", age_s=10, eta_s=600)
    rep = pw.run(progress_dir=d, state_path=tmp_path / "s.json", now=NOW,
                 send=lambda *a: None, dry_run=True)
    (t,) = rep["tasks"]
    assert t["verdict"] == "blocked"
    assert rep["malformed"] == []


def test_owner_proven_alive_inside_grace_is_held_not_marked(tmp_path, d):
    owner = {"pid": 4242, "start": 1.0}
    _plant(d, "slow", age_s=1500, eta_s=600, extra={"owner": owner})
    alive = Alive(True)
    rep = _reap(tmp_path, d, alive=alive)
    assert rep["marked"] == []
    assert [h["file"] for h in rep["held"]] == ["slow.json"]
    assert "alive" in rep["held"][0]["why"]
    assert alive.calls == [owner]
    assert _doc(d / "slow.json")["status"] == "running"


def test_owner_alive_but_silent_past_kit_grace_is_marked(tmp_path, d):
    _plant(d, "slow", age_s=pw.OWNER_ALIVE_GRACE_S + 1, eta_s=600,
           extra={"owner": {"pid": 4242, "start": 1.0}})
    assert _reap(tmp_path, d, alive=Alive(True))["marked"] == ["slow"]


def test_owner_dead_is_marked_and_says_so(tmp_path, d):
    _plant(d, "gone", age_s=1500, eta_s=600, extra={"owner": {"pid": 4242, "start": 1.0}})
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert rep["marked"] == ["gone"]
    assert "owner dead" in _doc(d / "gone.json")["reason"]


def test_a_row_rewritten_between_read_and_mark_is_left_alone(tmp_path, d):
    p = _plant(d, "race", age_s=1500, eta_s=600, extra={"owner": OWNER})

    def writer_comes_back():
        doc = _doc(p)
        doc["updated"] = _iso_utc(NOW)
        doc["pct"] = 90
        p.write_text(json.dumps(doc), encoding="ascii")

    rep = _reap(tmp_path, d, alive=Alive(False, hook=writer_comes_back))
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    doc = _doc(p)
    assert doc["status"] == "running" and doc["pct"] == 90


# ---------------------------------------------------------------- recycle

def test_finished_rows_older_than_7_days_go_to_the_bin(tmp_path, d):
    _plant(d, "old-done", status="done", age_s=8 * DAY)
    _plant(d, "old-failed", status="failed", age_s=8 * DAY)
    _plant(d, "young-done", status="done", age_s=6 * DAY)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert sorted(bin_.calls) == ["old-done.json", "old-failed.json"]
    assert sorted(rep["recycled"]) == ["old-done", "old-failed"]
    assert (d / "young-done.json").exists()


@pytest.mark.parametrize("age,mtime_age", [(8 * DAY, 60), (60, 8 * DAY)])
def test_both_clocks_must_be_old_before_a_row_is_recycled(tmp_path, d, age, mtime_age):
    _plant(d, "row", status="done", age_s=age, mtime_age=mtime_age)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["recycled"] == []


def test_a_stale_running_row_is_marked_not_recycled_in_the_same_pass(tmp_path, d):
    _plant(d, "ancient", age_s=30 * DAY, eta_s=600)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert rep["marked"] == ["ancient"] and bin_.calls == []
    plan = _reap(tmp_path, d, apply=False, recycle=bin_)
    assert plan["would_recycle"] == []          # its 'updated' is now


def test_refused_recycle_keeps_the_file_and_is_reported(tmp_path, d):
    _plant(d, "a", status="done", age_s=9 * DAY)
    _plant(d, "b", status="done", age_s=9 * DAY)
    refuse = Bin(tmp_path, result=lambda p: SimpleNamespace(
        ok=False, nuked=False, detail="refused: bin policy unreadable"))
    rep = _reap(tmp_path, d, recycle=refuse)
    assert sorted(r["file"] for r in rep["refused"]) == ["a.json", "b.json"]
    assert rep["recycled"] == []
    assert (d / "a.json").exists() and (d / "b.json").exists()


def test_a_nuked_result_halts_the_pass(tmp_path, d):
    _plant(d, "a", status="done", age_s=9 * DAY)
    _plant(d, "b", status="done", age_s=9 * DAY)
    nuke = Bin(tmp_path, result=lambda p: SimpleNamespace(
        ok=False, nuked=True, detail="gone but NOT found in the Recycle Bin"))
    rep = _reap(tmp_path, d, recycle=nuke)
    assert len(nuke.calls) == 1
    assert rep["halted"] and rep["exit_code"] != 0


# ---------------------------------------------------------------- ownership

def test_keep_set_is_never_touched(tmp_path, d):
    for stem in ("lane-0", "lane-12", "inbox-responder", "loop"):
        _plant(d, stem, status="done", age_s=30 * DAY)
    _plant(d, "lane-3", age_s=30 * DAY, eta_s=60)          # stale running lane
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["marked"] == [] and rep["recycled"] == []
    assert _doc(d / "lane-3.json")["status"] == "running"
    assert {h["file"] for h in rep["held"]} == {
        "lane-0.json", "lane-12.json", "inbox-responder.json", "loop.json", "lane-3.json"}


def test_files_without_the_ownership_marker_are_never_touched(tmp_path, d):
    _plant(d, "mismatch", status="done", age_s=30 * DAY, task="mismatch RM-752 TLS")
    _plant(d, "mismatch-run", age_s=30 * DAY, task="someone-else")
    _plant(d, "broken", raw="{not json", age_s=30 * DAY)
    _plant(d, "listy", raw="[1, 2]", age_s=30 * DAY)
    _plant(d, "badts", status="done", age_s=30 * DAY, extra={"updated": "never"})
    _plant(d, "nostatus", status="weird", age_s=30 * DAY)
    notes = d / "report.findings.md"
    notes.write_text("notes", encoding="ascii")
    os.utime(notes, (NOW - 30 * DAY, NOW - 30 * DAY))
    (d / "x.json").mkdir()
    (d / "x.json" / "inner.json").write_text("{}", encoding="ascii")
    _plant(d, "has space", status="done", age_s=30 * DAY)
    before = {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["marked"] == [] and rep["recycled"] == []
    assert {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()} == before
    held = {h["file"] for h in rep["held"]}
    assert held >= {"mismatch.json", "mismatch-run.json", "broken.json", "listy.json",
                    "badts.json", "nostatus.json", "x.json", "has space.json"}
    assert "report.findings.md" not in held and rep["ignored"] >= 1


def test_a_progress_dir_outside_the_root_is_refused(tmp_path):
    outside = tmp_path / "elsewhere" / "progress"
    _plant(outside, "old", status="done", age_s=30 * DAY)
    _plant(outside, "stale", age_s=30 * DAY)
    bin_ = Bin(tmp_path)
    rep = pw.reap(progress_dir=outside, root=tmp_path / "repo", now=NOW, apply=True,
                  recycle=bin_, alive=Alive(None))
    assert rep["dir_state"] == "refused" and rep["exit_code"] != 0
    assert bin_.calls == [] and _doc(outside / "stale.json")["status"] == "running"


def test_missing_dir_is_a_quiet_no_op(tmp_path, d):
    rep = _reap(tmp_path, d)
    assert rep["dir_state"] == "missing" and rep["exit_code"] == 0


# ---------------------------------------------------------------- plan-only

def test_plan_only_by_default_changes_nothing(tmp_path, d):
    _plant(d, "stale", age_s=1500, eta_s=600, extra={"owner": OWNER})
    _plant(d, "old", status="done", age_s=8 * DAY)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    bin_ = Bin(tmp_path)
    rep = pw.reap(progress_dir=d, root=tmp_path, now=NOW, recycle=bin_, alive=Alive(False))
    assert rep["apply"] is False
    assert rep["would_mark"] == ["stale"] and rep["would_recycle"] == ["old"]
    assert rep["marked"] == [] and rep["recycled"] == [] and bin_.calls == []
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before


# ---------------------------------------------------------------- integration

def test_kit_written_rows_are_recognised_and_reaped(tmp_path):
    # ownerless (owner=0): reaped once silent past the kit's abandon grace
    kit.write_progress(tmp_path, "kitjob", 30, "kit step", 600, "running",
                       clock=lambda: NOW - pw.OWNER_ALIVE_GRACE_S - 600, owner=0)
    kit.write_progress(tmp_path, "kitdone", 100, "end", 0, "done",
                       clock=lambda: NOW - 9 * DAY, owner=0)
    d = tmp_path / "ops" / "loop" / "control" / "progress"
    os.utime(d / "kitdone.json", (NOW - 9 * DAY, NOW - 9 * DAY))
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert rep["marked"] == ["kitjob"] and rep["recycled"] == ["kitdone"]
    assert kit.close_progress(tmp_path, "kitjob") is None   # already final per the kit


def test_a_marked_row_alerts_once_as_failed_on_the_next_watch_run(tmp_path, d):
    _plant(d, "job", age_s=60, eta_s=600)
    state = tmp_path / "runtime" / "pw.json"
    sent = []
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: sent.append(k))
    _plant(d, "job", age_s=1500, eta_s=600, extra={"owner": OWNER})
    _reap(tmp_path, d, alive=Alive(False))
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: sent.append(k))
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: sent.append(k))
    assert sent == ["progress_watch:job:failed"]


def test_reaper_constants_track_the_kit():
    assert set(kit.PROGRESS_STATES) <= set(pw.STATUSES)
    assert pw.OWNER_ALIVE_GRACE_S == kit.ABANDON_S
    assert pw.STALE_FACTOR == 2.0
    assert pw.PRUNE_AGE_S == 7 * DAY


def test_main_root_resolves_a_linked_worktree_to_the_main_checkout(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: " + str(main / ".git" / "worktrees" / "wt") + "\n",
                             encoding="ascii")
    assert pw.main_root(wt) == main.resolve()
    assert pw.main_root(main) == main.resolve()


# ---------------------------------------------------------------- CLI

def test_cli_apply_without_reap_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        pw.main(["--apply", "--dir", str(tmp_path), "--state", str(tmp_path / "s.json")])


def _cli(tmp_path, d, *extra):
    return pw.main(["--dir", str(d), "--state", str(tmp_path / "runtime" / "s.json"),
                    "--root", str(tmp_path), "--reap", *extra], now=NOW)


def test_cli_reap_is_plan_only_without_apply(tmp_path, d, monkeypatch, capsys):
    _plant(d, "stale", age_s=10 * DAY, eta_s=600, mtime_age=10 * DAY)
    _plant(d, "old", status="done", age_s=10 * DAY)
    called = []
    monkeypatch.setattr(pw, "_recycle_default", lambda p: called.append(p))
    monkeypatch.setattr(pw, "_alive_default", lambda o: None)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    assert _cli(tmp_path, d) == 0
    out = capsys.readouterr().out
    out.encode("ascii")
    assert "would mark failed: stale" in out and "would recycle: old" in out
    assert called == [] and {p.name: p.read_bytes() for p in d.iterdir()} == before


def test_cli_dry_run_forces_plan_only_even_with_apply(tmp_path, d, monkeypatch, capsys):
    _plant(d, "old", status="done", age_s=10 * DAY)
    called = []
    monkeypatch.setattr(pw, "_recycle_default", lambda p: called.append(p))
    monkeypatch.setattr(pw, "_alive_default", lambda o: None)
    assert _cli(tmp_path, d, "--apply", "--dry-run") == 0
    assert called == [] and (d / "old.json").exists()
    assert "would recycle: old" in capsys.readouterr().out


def test_cli_apply_marks_and_recycles_through_the_defaults(tmp_path, d, monkeypatch, capsys):
    _plant(d, "stale", age_s=pw.OWNER_ALIVE_GRACE_S + 600, eta_s=600)   # ownerless
    _plant(d, "old", status="done", age_s=10 * DAY)
    bin_ = Bin(tmp_path)
    monkeypatch.setattr(pw, "_recycle_default", bin_)
    monkeypatch.setattr(pw, "_alive_default", lambda o: None)
    assert _cli(tmp_path, d, "--apply") == 0
    out = capsys.readouterr().out
    assert "marked failed: stale" in out and "recycled: old" in out
    assert bin_.calls == ["old.json"]
    assert _doc(d / "stale.json")["status"] == "failed"


def test_cli_json_carries_the_reap_report(tmp_path, d, monkeypatch, capsys):
    _plant(d, "old", status="done", age_s=10 * DAY)
    monkeypatch.setattr(pw, "_alive_default", lambda o: None)
    assert _cli(tmp_path, d, "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["reap"]["would_recycle"] == ["old"]


def test_default_recycler_is_the_checked_core_helper(monkeypatch, tmp_path):
    import core.recycle_bin as rb
    seen = []
    monkeypatch.setattr(rb, "recycle_checked", lambda p: seen.append(str(p)) or "r")
    assert pw._recycle_default(tmp_path / "x.json") == "r"
    assert seen == [str(tmp_path / "x.json")]
