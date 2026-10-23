"""RM-785 - residual risks of the RM-728 progress-file reaper
(tools/progress_watch.py reap()), filed by the RM-728 verifier.

(a) read-compare-act race. The compare-and-swap ran at the START of
    _mark_failed; the json parse, the new stamp, the tmp write and every
    PermissionError retry of the replace all came after it, so a writer that
    came back inside that window was overwritten. A writer that re-wrote the
    same bytes (mtime moved, bytes equal) passed the bytes-only compare. The
    fix re-checks bytes AND (mtime, size) immediately before every replace
    attempt and before the recycle call, and skips on any change.
(b) an ownerless row (no owner field, or an owner the probe cannot answer for)
    in a long step was marked failed - and drew a FAILED note on the next watch
    run - as soon as it passed 2x its ETA. The kit calls a live row abandoned
    only when its owner is PROVEN dead or it has been silent past ABANDON_S
    (fleet_headless.progress_abandoned; the statusline reads it the same way),
    so the reaper now holds an unknown owner like a live one until that grace.
(c) the keep-list name match was case-sensitive; NTFS is not, so
    'Lane-3.json' IS the lane widget's lane-3.json. The match now case-folds.

Every test runs on tmp_path with a fake bin and a fake owner probe.
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
    "rc_tools_progress_watch_rm785", _ROOT / "tools" / "progress_watch.py")
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

_kspec = importlib.util.spec_from_file_location(
    "rc_fleet_kit_fleet_headless_rm785", _ROOT / "ops" / "fleet_kit" / "fleet_headless.py")
kit = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(kit)

NOW = 1_800_000_000.0
DAY = 86400.0
OWNER = {"pid": 4242, "start": 1.0}


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _plant(d: Path, stem: str, *, status="running", age_s=0.0, eta_s=600,
           mtime_age=None, task=None, extra=None) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.json"
    doc = {"task": stem if task is None else task, "pct": 40, "step": "planted",
           "eta_s": eta_s, "status": status, "updated": _iso_utc(NOW - age_s)}
    doc.update(extra or {})
    p.write_text(json.dumps(doc), encoding="ascii", newline="\n")
    t = NOW - (age_s if mtime_age is None else mtime_age)
    os.utime(p, (t, t))
    return p


class Bin:
    def __init__(self, tmp: Path):
        self.calls = []
        self.dest = tmp / "fakebin"

    def __call__(self, path):
        self.calls.append(Path(path).name)
        self.dest.mkdir(exist_ok=True)
        Path(path).replace(self.dest / Path(path).name)
        return SimpleNamespace(ok=True, nuked=False, detail="landed (fake)")


class Alive:
    def __init__(self, answer=None, hook=None):
        self.answer, self.hook, self.calls = answer, hook, []

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


def _writer_returns(p: Path, pct=90):
    """A live writer's next item-12 write: same task, fresh stamp."""
    doc = _doc(p)
    doc.update(updated=_iso_utc(NOW), pct=pct, step="writer is back")
    p.write_text(json.dumps(doc), encoding="ascii", newline="\n")


# ---------------------------------------------------------------- (a) race

def test_a_writer_back_after_the_cas_read_but_before_the_replace_wins(tmp_path, d, monkeypatch):
    """The old compare ran before the new stamp was even built: a write that
    landed while the reaper built its doc was overwritten."""
    p = _plant(d, "race", age_s=1500, eta_s=600, extra={"owner": OWNER})
    real_iso = pw._iso_local

    def iso_then_writer(epoch):
        _writer_returns(p)
        return real_iso(epoch)

    monkeypatch.setattr(pw, "_iso_local", iso_then_writer)
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    doc = _doc(p)
    assert doc["status"] == "running" and doc["pct"] == 90
    assert not list(d.glob("*.tmp"))


def test_a_writer_back_during_a_replace_retry_wins(tmp_path, d, monkeypatch):
    """A polling reader share-locks the target (PermissionError) and the
    reaper retries; a writer that lands during the back-off must win."""
    p = _plant(d, "retry", age_s=1500, eta_s=600, extra={"owner": OWNER})
    calls = []

    def replace_locked_once(src, dst):
        calls.append(Path(dst).name)
        if len(calls) == 1:
            _writer_returns(p)
            raise PermissionError(13, "share-locked by a polling reader")
        Path(src).replace(dst)

    monkeypatch.setattr(pw, "_replace", replace_locked_once, raising=False)
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    doc = _doc(p)
    assert doc["status"] == "running" and doc["pct"] == 90
    assert calls == ["retry.json"]          # no second replace onto the writer's row
    assert not list(d.glob("*.tmp"))


def test_a_rewrite_with_identical_bytes_still_counts_as_a_change(tmp_path, d):
    """mtime is compared, not just bytes: a writer that re-wrote the same row
    is alive, and its row is left to it."""
    p = _plant(d, "touch", age_s=1500, eta_s=600, extra={"owner": OWNER})
    raw = p.read_bytes()

    def same_bytes_new_mtime():
        p.write_bytes(raw)
        os.utime(p, (NOW - 5, NOW - 5))

    rep = _reap(tmp_path, d, alive=Alive(False, hook=same_bytes_new_mtime))
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    assert p.read_bytes() == raw


def test_a_finished_row_touched_after_the_read_is_not_recycled(tmp_path, d, monkeypatch):
    p = _plant(d, "olddone", status="done", age_s=9 * DAY)
    raw = p.read_bytes()
    real_parse = pw.parse_updated

    def parse_then_touch(value):
        os.utime(p, (NOW - 1, NOW - 1))     # its writer touched it: young again
        return real_parse(value)

    monkeypatch.setattr(pw, "parse_updated", parse_then_touch)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["recycled"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    assert p.read_bytes() == raw


def test_an_unchanged_row_is_still_marked_and_leaves_no_tmp(tmp_path, d):
    p = _plant(d, "plain", age_s=1500, eta_s=600, extra={"owner": OWNER})
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert rep["marked"] == ["plain"]
    assert _doc(p)["status"] == "failed"
    assert not list(d.glob("*.tmp"))


def test_state_writes_still_go_through_the_atomic_writer(tmp_path, d):
    _plant(d, "job", age_s=10, eta_s=600)
    state = tmp_path / "runtime" / "pw.json"
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: None)
    assert json.loads(state.read_text(encoding="ascii"))["schema"] == pw.STATE_SCHEMA
    assert not list(state.parent.glob("*.tmp"))


# ---------------------------------------------------------------- (b) ownerless

@pytest.mark.parametrize("extra", [None, {"owner": OWNER}], ids=["no-owner", "unknown-owner"])
def test_an_unknown_owner_past_2x_eta_inside_the_abandon_grace_is_held(tmp_path, d, extra):
    p = _plant(d, "longstep", age_s=1500, eta_s=600, extra=extra)
    rep = _reap(tmp_path, d, alive=Alive(None))
    assert rep["marked"] == []
    (h,) = rep["held"]
    assert h["file"] == "longstep.json" and "unknown" in h["why"]
    assert _doc(p)["status"] == "running"
    plan = _reap(tmp_path, d, apply=False, alive=Alive(None))
    assert plan["would_mark"] == []


def test_an_unknown_owner_silent_past_the_abandon_grace_is_marked(tmp_path, d):
    p = _plant(d, "gone", age_s=pw.OWNER_ALIVE_GRACE_S + 1, eta_s=600)
    rep = _reap(tmp_path, d, alive=Alive(None))
    assert rep["marked"] == ["gone"]
    doc = _doc(p)
    assert doc["status"] == "failed" and "owner dead" not in doc["reason"]
    assert len(doc["reason"]) <= pw.REASON_MAX


def test_a_held_ownerless_row_draws_a_stale_note_not_a_failed_one(tmp_path, d):
    _plant(d, "longstep", age_s=60, eta_s=600)
    state = tmp_path / "runtime" / "pw.json"
    sent = []
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: sent.append(k))
    _plant(d, "longstep", age_s=1500, eta_s=600)
    _reap(tmp_path, d, alive=Alive(None))
    pw.run(progress_dir=d, state_path=state, now=NOW, send=lambda t, k: sent.append(k))
    assert sent == ["progress_watch:longstep:stale"]


@pytest.mark.parametrize("answer", [True, False, None])
@pytest.mark.parametrize("age", [1500, 7199, 7201, 3 * DAY])
def test_the_mark_decision_is_past_2x_eta_and_kit_abandoned(tmp_path, d, answer, age):
    """Parity with fleet_headless.progress_abandoned (owner dead, or silent
    past ABANDON_S): the reaper marks exactly the kit-abandoned rows that are
    also past 2x their ETA."""
    p = _plant(d, "row", age_s=age, eta_s=600, extra={"owner": OWNER})
    doc = _doc(p)
    want = age > 2 * 600 and kit.progress_abandoned(doc, now=NOW, alive=lambda o: answer)
    rep = _reap(tmp_path, d, apply=False, alive=Alive(answer))
    assert (rep["would_mark"] == ["row"]) is want


# ---------------------------------------------------------------- (c) case

@pytest.mark.parametrize("stem", ["Lane-3", "LANE-12", "Inbox-Responder", "LOOP"])
def test_the_keep_list_match_is_case_insensitive(tmp_path, d, stem):
    _plant(d, stem, age_s=30 * DAY, eta_s=60, extra={"owner": OWNER})
    before = (d / f"{stem}.json").read_bytes()
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_, alive=Alive(False))
    assert rep["marked"] == [] and rep["recycled"] == [] and bin_.calls == []
    assert [h["file"] for h in rep["held"]] == [f"{stem}.json"]
    assert "kept by name" in rep["held"][0]["why"]
    assert (d / f"{stem}.json").read_bytes() == before


def test_a_finished_keep_name_in_another_case_is_never_recycled(tmp_path, d):
    _plant(d, "Lane-0", status="done", age_s=30 * DAY)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["recycled"] == []
    assert (d / "Lane-0.json").exists()


def test_a_name_that_only_resembles_a_keep_name_is_still_reaped(tmp_path, d):
    """Case-folding must not widen the keep list into a prefix match."""
    _plant(d, "lanes-report", age_s=1500, eta_s=600, extra={"owner": OWNER})
    _plant(d, "Loop2", age_s=1500, eta_s=600, extra={"owner": OWNER})
    rep = _reap(tmp_path, d, alive=Alive(False))
    assert sorted(rep["marked"]) == ["Loop2", "lanes-report"]
