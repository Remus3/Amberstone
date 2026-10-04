# arch: tests for tools/progress_watch.py (Y-06) | section=tests | frozen=no
"""Y-06 (external reference J) - the progress-file staleness reader.

FLEET-COMMON item 12 makes every long job write
ops/loop/control/progress/<task>.json, and says a file that stops updating for
2x its ETA is a failure. Until this tool nothing READ those files, so the rule
was unenforceable. These tests pin the reader's contract on tmp dirs only -
never the live ops/runtime or the live progress dir:

- planted stale / done / failed / fresh files classify correctly, with the
  overrun REPORT rungs at 1.5x and 3x (report only, nothing is killed);
- both 'updated' shapes the live dir holds (naive local and tz-aware, incl.
  7-digit fractions, 'Z', '-0500' and a bare date) parse;
- eta_s 0 / null on a RUNNING file is floored instead of false-alarming;
- first sight of the dir is a silent baseline; a second run with no change
  sends nothing; a new update clears the alert so a relapse re-alerts;
- a failed send leaves state unadvanced (retried next run);
- K consecutive runs that read zero files flag the watcher itself, whether
  the dir is empty or every file in it is unreadable;
- malformed JSON is tolerated and NAMED, never a crash and never silent.
"""
from __future__ import annotations

import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rc_tools_progress_watch", _ROOT / "tools" / "progress_watch.py")
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

NOW = 1_800_000_000.0  # fixed clock; every timestamp below is relative to it


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _iso_naive_local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")


def _plant(d: Path, stem: str, *, status="running", age_s=0.0, eta_s=600,
           naive=False, raw=None):
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.json"
    if raw is not None:
        p.write_text(raw, encoding="ascii", newline="\n")
        return p
    ts = (_iso_naive_local if naive else _iso_utc)(NOW - age_s)
    doc = {"task": stem, "pct": 50, "step": "planted", "eta_s": eta_s,
           "status": status, "updated": ts}
    p.write_text(json.dumps(doc), encoding="ascii", newline="\n")
    return p


class Outbox:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, text, key):
        if self.fail:
            raise OSError("planted send failure")
        self.sent.append((key, text))


@pytest.fixture
def env(tmp_path):
    return tmp_path / "progress", tmp_path / "runtime" / "progress_watch.json"


def _run(env, now=NOW, send=None, **kw):
    d, s = env
    return pw.run(progress_dir=d, state_path=s, now=now,
                  send=send if send is not None else Outbox(), **kw)


# ---------------------------------------------------------------- timestamps

@pytest.mark.parametrize("value", [
    "2026-10-03T22:15:58.1436461-05:00",   # 7-digit fraction (PowerShell 'o')
    "2026-10-04T00:10:31-0500",            # strftime %z, no colon
    "2026-10-04T03:03:49Z",
    "2026-10-04T05:13:53.279679+00:00",
    "2026-10-04T00:19:44",                 # naive local
    "2026-10-03",                          # bare date
])
def test_every_live_updated_shape_parses(value):
    assert isinstance(pw.parse_updated(value), float)


def test_naive_is_local_and_aware_is_honoured():
    aware = pw.parse_updated(_iso_utc(NOW))
    naive = pw.parse_updated(_iso_naive_local(NOW))
    assert aware == pytest.approx(NOW)
    assert naive == pytest.approx(NOW)


@pytest.mark.parametrize("value", [None, "", "yesterday", 12345, "2026-13-45T99:00"])
def test_unparseable_updated_is_none(value):
    assert pw.parse_updated(value) is None


# ---------------------------------------------------------------- classify

def test_planted_files_classify(env):
    d, _ = env
    _plant(d, "fresh", age_s=60, eta_s=600)
    _plant(d, "fresh-naive", age_s=60, eta_s=600, naive=True)
    _plant(d, "over15", age_s=1000, eta_s=600)           # 1.67x
    _plant(d, "stale", age_s=1500, eta_s=600)            # 2.5x
    _plant(d, "over3", age_s=2000, eta_s=600)            # 3.33x
    _plant(d, "done", status="done", age_s=99999, eta_s=0)
    _plant(d, "failed", status="failed", age_s=10, eta_s=None)
    rep = _run(env, dry_run=True)
    got = {t["task"]: t["verdict"] for t in rep["tasks"]}
    assert got == {"fresh": "running", "fresh-naive": "running",
                   "over15": "overrun_1.5x", "stale": "stale",
                   "over3": "overrun_3x", "done": "done", "failed": "failed"}
    assert rep["files_read"] == 7


def test_stale_boundary_is_strictly_greater_than_2x(env):
    d, _ = env
    _plant(d, "at2x", age_s=1200, eta_s=600)
    _plant(d, "past2x", age_s=1201, eta_s=600)
    got = {t["task"]: t["verdict"] for t in _run(env, dry_run=True)["tasks"]}
    assert got == {"at2x": "overrun_1.5x", "past2x": "stale"}


@pytest.mark.parametrize("eta", [0, None, "soon", -5, True])
def test_running_with_no_usable_eta_is_floored_not_false_alarmed(env, eta):
    d, _ = env
    _plant(d, "t", age_s=pw.MIN_ETA_S - 1, eta_s=eta)
    (t,) = _run(env, dry_run=True)["tasks"]
    assert t["verdict"] == "running"
    assert t["eta_floored"] is True
    assert t["eta_used"] == pw.MIN_ETA_S


def test_future_timestamp_reads_as_fresh(env):
    d, _ = env
    _plant(d, "skew", age_s=-3600, eta_s=600)
    (t,) = _run(env, dry_run=True)["tasks"]
    assert t["verdict"] == "running"


# ---------------------------------------------------------------- alerting

def test_first_sight_is_a_silent_baseline(env):
    d, s = env
    _plant(d, "stale", age_s=1500, eta_s=600)
    _plant(d, "failed", status="failed")
    box = Outbox()
    rep = _run(env, send=box)
    assert box.sent == []
    assert rep["baseline"] is True
    assert s.exists()


def test_transition_alerts_once_and_second_run_sends_nothing(env):
    d, _ = env
    _plant(d, "job", age_s=60, eta_s=600)
    _run(env)                                   # baseline: running
    _plant(d, "job", age_s=60, eta_s=600)       # same file content, same stamp
    box = Outbox()
    _run(env, now=NOW + 1500, send=box)         # now 1560s old -> stale
    assert [k for k, _ in box.sent] == ["progress_watch:job:stale"]
    assert "STALE" in box.sent[0][1]
    box2 = Outbox()
    _run(env, now=NOW + 1500, send=box2)        # nothing changed
    assert box2.sent == []


def test_escalation_alerts_each_rung_once(env):
    d, _ = env
    _plant(d, "job", age_s=0, eta_s=600)
    _run(env)
    box = Outbox()
    for dt in (1000, 1000, 1500, 1500, 2000, 2000):
        _run(env, now=NOW + dt, send=box)
    assert [k for k, _ in box.sent] == [
        "progress_watch:job:overrun_1.5x",
        "progress_watch:job:stale",
        "progress_watch:job:overrun_3x",
    ]


def test_recovery_clears_and_a_relapse_realerts(env):
    d, _ = env
    _plant(d, "job", age_s=0, eta_s=600)
    _run(env)
    box = Outbox()
    _run(env, now=NOW + 1500, send=box)
    assert len(box.sent) == 1
    # the writer comes back: a new 'updated' clears the alert
    _plant(d, "job", age_s=-1500, eta_s=600)
    rec = _run(env, now=NOW + 1500, send=box)
    assert len(box.sent) == 1
    (t,) = rec["tasks"]
    assert t["verdict"] == "running" and t["alerted"] == []
    # and goes quiet again -> the same verdict alerts again
    _run(env, now=NOW + 3000, send=box)
    assert [k for k, _ in box.sent] == ["progress_watch:job:stale"] * 2


def test_new_file_after_baseline_that_is_already_failed_alerts(env):
    d, _ = env
    _plant(d, "old", status="done")
    _run(env)
    _plant(d, "newcomer", status="failed")
    box = Outbox()
    _run(env, send=box)
    assert [k for k, _ in box.sent] == ["progress_watch:newcomer:failed"]


def test_done_and_running_never_alert(env):
    d, _ = env
    _plant(d, "a", age_s=0, eta_s=600)
    _run(env)
    _plant(d, "a", status="done", age_s=-10, eta_s=0)
    _plant(d, "b", age_s=0, eta_s=600)
    box = Outbox()
    _run(env, now=NOW + 5, send=box)
    assert box.sent == []


def test_failed_send_leaves_state_unadvanced(env):
    d, _ = env
    _plant(d, "job", age_s=0, eta_s=600)
    _run(env)
    rep = _run(env, now=NOW + 1500, send=Outbox(fail=True))
    assert rep["send_failures"] == 1
    box = Outbox()
    _run(env, now=NOW + 1500, send=box)
    assert [k for k, _ in box.sent] == ["progress_watch:job:stale"]


def test_dry_run_writes_nothing_and_sends_nothing(env):
    d, s = env
    _plant(d, "job", age_s=0, eta_s=600)
    _run(env)
    before = s.read_bytes()
    box = Outbox()
    rep = _run(env, now=NOW + 1500, send=box, dry_run=True)
    assert box.sent == []
    assert s.read_bytes() == before
    assert rep["would_alert"] == ["progress_watch:job:stale"]


def test_dry_run_on_first_sight_does_not_create_state(env):
    d, s = env
    _plant(d, "job")
    _run(env, dry_run=True)
    assert not s.exists()


# ---------------------------------------------------------------- malformed

def test_malformed_json_is_tolerated_and_named(env):
    d, _ = env
    _plant(d, "good", age_s=10)
    _plant(d, "broken", raw="{not json")
    _plant(d, "listy", raw="[1, 2]")
    _plant(d, "nostatus", raw=json.dumps({"task": "x", "updated": _iso_utc(NOW)}))
    _plant(d, "badts", raw=json.dumps({"status": "running", "eta_s": 60,
                                       "updated": "never"}))
    rep = _run(env, dry_run=True)
    assert rep["files_read"] == 1
    bad = {m["file"] for m in rep["malformed"]}
    assert bad == {"broken.json", "listy.json", "nostatus.json", "badts.json"}
    assert all(m["reason"] for m in rep["malformed"])


def test_malformed_alerts_once_after_baseline(env):
    d, _ = env
    _plant(d, "good", age_s=10)
    _run(env)
    _plant(d, "broken", raw="{not json")
    box = Outbox()
    _run(env, send=box)
    _run(env, send=box)
    assert [k for k, _ in box.sent] == ["progress_watch:broken:malformed"]


def test_corrupt_state_file_is_a_fresh_baseline_not_a_crash(env):
    d, s = env
    _plant(d, "job", status="failed")
    s.parent.mkdir(parents=True)
    s.write_text("{garbage", encoding="ascii")
    box = Outbox()
    rep = _run(env, send=box)
    assert rep["baseline"] is True and rep["state_reset"] is True
    assert box.sent == []
    json.loads(s.read_text(encoding="ascii"))


# ---------------------------------------------------------------- self-check

def test_empty_dir_for_k_runs_flags_itself_once(env):
    d, _ = env
    d.mkdir(parents=True)
    box = Outbox()
    reps = [_run(env, send=box, k=3) for _ in range(5)]
    assert [r["self_check_failed"] for r in reps] == [False, False, True, True, True]
    assert [k for k, _ in box.sent] == ["progress_watch:selfcheck"]
    assert reps[-1]["exit_code"] != 0


def test_nonempty_dir_with_zero_readable_files_flags_itself(env):
    d, _ = env
    _plant(d, "broken", raw="{nope")
    reps = [_run(env, k=2) for _ in range(2)]
    assert reps[-1]["self_check_failed"] is True
    assert reps[-1]["files_seen"] == 1 and reps[-1]["files_read"] == 0


def test_missing_dir_counts_as_zero_read(env):
    reps = [_run(env, k=2) for _ in range(2)]
    assert reps[-1]["self_check_failed"] is True


def test_self_check_rearms_after_a_good_read(env):
    d, _ = env
    d.mkdir(parents=True)
    box = Outbox()
    for _ in range(3):
        _run(env, send=box, k=3)
    _plant(d, "job", age_s=0)
    ok = _run(env, send=box, k=3)
    assert ok["self_check_failed"] is False and ok["zero_read_streak"] == 0
    (d / "job.json").unlink()
    for _ in range(3):
        _run(env, send=box, k=3)
    assert [k for k, _ in box.sent] == ["progress_watch:selfcheck"] * 2


# ---------------------------------------------------------------- transport

def test_default_sender_appends_a_note_to_the_steer_log(tmp_path, monkeypatch):
    steer = pw._steer_module()
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(steer, "CONTROL_DIR", ctl)
    monkeypatch.setattr(steer, "STEER_LOG", ctl / "STEER.jsonl")
    monkeypatch.setattr(steer, "STEER_CURSOR", ctl / "STEER.cursor")
    pw.steer_send("progress_watch: task job STALE", "progress_watch:job:stale")
    (line,) = (ctl / "STEER.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(line)
    assert rec["tier"] == "note"
    assert rec["key"] == "progress_watch:job:stale"
    assert rec["source"] == "progress_watch"


def test_alert_text_is_ascii(env):
    d, _ = env
    _plant(d, "job", age_s=0)
    _run(env)
    p = d / "job.json"
    doc = json.loads(p.read_text(encoding="ascii"))
    doc["step"] = "caf" + chr(0xE9) + " " + chr(0x2014) + " step"  # planted non-ASCII
    p.write_text(json.dumps(doc), encoding="ascii")
    box = Outbox()
    _run(env, now=NOW + 1500, send=box)
    (_, text), = box.sent
    text.encode("ascii")


def test_human_report_is_one_line_per_task_and_ascii(env):
    d, _ = env
    _plant(d, "alpha", age_s=10)
    _plant(d, "beta", status="done")
    _plant(d, "gamma", raw="{bad")
    out = pw.format_report(_run(env, dry_run=True))
    lines = out.splitlines()
    out.encode("ascii")
    assert lines[0].startswith("progress_watch: 2/3 files read")
    for stem in ("alpha", "beta", "gamma"):
        assert sum(1 for ln in lines if ln.strip().startswith(stem + ":")) == 1


def test_state_write_is_atomic_json(env):
    d, s = env
    _plant(d, "job")
    _run(env)
    doc = json.loads(s.read_text(encoding="ascii"))
    assert doc["schema"] == 1 and "job" in doc["tasks"]
    assert not list(s.parent.glob("*.tmp"))


def test_now_defaults_to_wall_clock(env):
    d, _ = env
    _plant(d, "job", age_s=NOW - time.time())  # i.e. updated == real now
    d2, s = env
    rep = pw.run(progress_dir=d2, state_path=s, send=Outbox(), dry_run=True)
    assert rep["tasks"][0]["verdict"] == "running"
