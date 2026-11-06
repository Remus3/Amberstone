"""s147 F1: 0x800710E0 is not always an ExecutionTimeLimit kill (tools/rc_facts.py).

Measured 2026-10-31 on Legion. After the 19:03:56 reboot RC-ClaudeQuotaWatch,
RC-CostHealthWatchdog and RC-PatchRefresh all carried LastTaskResult
0x800710E0, and rc_facts labelled every one an "ExecutionTimeLimit kill". The
Task Scheduler Operational log held event 153 ("did not launch task ... as it
missed its schedule") for exactly those three at 19:07:34, and QuotaWatch and
PatchRefresh run under the default PT72H limit, which no run came near. They
were missed-run skips: with StartWhenAvailable off the scheduler skips the
catch-up run and records the refusal code.

Pinned here:

  - a 0x800710E0 whose own attempt logged event 153, or a later successful
    run (event 201, return code 0), reads MISSED with the missed-run label;
  - a real termination (event 111 or 329), or a run whose duration reached
    the ExecutionTimeLimit, still reads FAILURE with the kill label;
  - an event from an EARLIER attempt explains nothing;
  - an unreadable log (None) or an empty one keeps the old label (fail soft);
  - Get-ScheduledTaskInfo's LastRunTime is good to the minute only (its
    seconds echo the minutes: 19:07:07 for a 19:07:34 event), so the attempt
    match tolerates that skew;
  - the event query is windowless, splices only safe task names, fails soft
    to None, and runs only when some row carries 0x800710E0.

Every label assertion is on the EXACT string, written out literally: a test
that only checks a substring passes when both branches print the same text.

Nothing here reads the real event log or Task Scheduler. All authored content
is 7-bit ASCII.
"""

from __future__ import annotations

import json
import time

import tools.rc_facts as rc_facts
from tests._module_view import bind_subprocess

CODE = 2147946720  # 0x800710E0
_DAY = 86400.0

KILL = "0x800710E0 (Win32 4320, request refused) - ExecutionTimeLimit kill"
MISSED_153 = ("0x800710E0 (Win32 4320, request refused) - missed-run skip "
              "(event 153, missed its schedule, 0.0d ago)")
MISSED_201 = ("0x800710E0 (Win32 4320, request refused) - missed-run skip "
              "(no termination; a later run completed OK, event 201 rc=0, 0.0d ago)")


def _ev(eid, age_s, rc=None):
    return {"id": eid, "age_s": float(age_s), "rc": rc}


def _classify(events, *, last_run_age_s=3600.0, time_limit_s=72 * 3600.0,
              name="RC-ClaudeQuotaWatch", state="Ready"):
    return rc_facts.classify_task_result(
        name, state, CODE, last_run_age_s=last_run_age_s,
        time_limit_s=time_limit_s, events=events,
    )


def test_the_two_labels_are_different_strings():
    """Guards the guard: every exact-label test below is worthless if the
    missed-run label still carries the kill wording."""
    assert KILL != MISSED_153 and KILL != MISSED_201
    assert "kill" not in MISSED_153.lower()
    assert "kill" not in MISSED_201.lower()


# ------------------------------------------------------------ classification


def test_event_153_in_the_last_attempt_reads_as_a_missed_run_skip():
    # The measured shape: LastRunTime 19:07:07 (seconds echo the minutes),
    # event 153 at 19:07:34, so the event is 27 s NEWER than the reported run.
    verdict, detail = _classify([_ev(153, 3600.0 - 27.0)])
    assert verdict == rc_facts.VERDICT_MISSED
    assert detail == MISSED_153


def test_a_later_successful_run_reads_as_a_missed_run_skip():
    verdict, detail = _classify([_ev(100, 600.0), _ev(201, 599.0, rc=0)],
                                last_run_age_s=600.0)
    assert verdict == rc_facts.VERDICT_MISSED
    assert detail == MISSED_201


def test_event_111_termination_still_reads_as_a_kill():
    events = [_ev(100, 1000.0), _ev(111, 700.0), _ev(201, 699.0, rc=1)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_event_329_time_limit_termination_reads_as_a_kill():
    events = [_ev(100, 1000.0), _ev(329, 700.0), _ev(111, 700.0)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_a_termination_wins_over_a_success_logged_after_it():
    """The killed action's own event 201 lands AFTER event 111. Even if it
    carried return code 0 it must not launder the kill into a skip."""
    events = [_ev(100, 1000.0), _ev(111, 700.0), _ev(201, 699.0, rc=0)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_event_153_does_not_hide_event_111_in_the_same_attempt():
    """A kill always wins: a 153 in the same attempt must not mask event 111.
    A 153-first ordering passed every other test (verifier mutant, s147)."""
    events = [_ev(100, 1000.0), _ev(153, 950.0), _ev(111, 700.0)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_event_153_does_not_hide_event_329_in_the_same_attempt():
    events = [_ev(100, 1000.0), _ev(153, 950.0), _ev(329, 700.0)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_event_153_does_not_hide_a_run_at_the_time_limit():
    # A 300 s run under a PT5M limit, no 111/329 logged, then a 153.
    events = [_ev(100, 1000.0), _ev(201, 700.0, rc=0), _ev(153, 650.0)]
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_a_run_at_the_time_limit_reads_as_a_kill_without_event_111():
    events = [_ev(100, 1000.0), _ev(201, 700.0, rc=0)]  # 300 s run, PT5M limit
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_a_run_under_the_time_limit_is_not_a_duration_kill():
    events = [_ev(100, 1000.0), _ev(201, 999.0 - 298.0, rc=0)]  # 299 s run
    verdict, detail = _classify(events, last_run_age_s=1000.0, time_limit_s=300.0)
    assert verdict == rc_facts.VERDICT_MISSED
    assert detail == ("0x800710E0 (Win32 4320, request refused) - missed-run skip "
                      "(no termination; a later run completed OK, event 201 rc=0, 0.0d ago)")


def test_an_event_from_an_earlier_attempt_explains_nothing():
    verdict, detail = _classify([_ev(153, 20000.0)], last_run_age_s=3600.0)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert detail == KILL


def test_the_attempt_match_tolerates_the_lastruntime_seconds_quirk():
    # LastRunTime HH:50:50 for a real HH:50:10 event: the event reads 40 s
    # OLDER than the reported run and must still match it.
    verdict, detail = _classify([_ev(153, 3600.0 + 40.0)], last_run_age_s=3600.0)
    assert verdict == rc_facts.VERDICT_MISSED
    assert detail == MISSED_153


def test_an_unread_or_empty_event_log_keeps_the_kill_label():
    for events in (None, []):
        verdict, detail = _classify(events)
        assert verdict == rc_facts.VERDICT_FAILURE, events
        assert detail == KILL, events


def test_the_running_daemon_duplicate_suppression_is_unchanged():
    verdict, detail = rc_facts.classify_task_result(
        "RC-MissionControl", "Running", CODE, events=[_ev(153, 10.0)])
    assert verdict == rc_facts.VERDICT_OK
    assert detail == "duplicate launch refused while the daemon is up"


# ------------------------------------------------------------- banner lines


def _iso(now: float, age_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - age_s))


def _row(name, *, last_run, events=None, time_limit="PT72H"):
    row = {"name": name, "state": "Ready", "last_result": CODE,
           "last_run": last_run, "next_run": None,
           "triggers": "MSFT_TaskTimeTrigger", "time_limit": time_limit,
           "repetition": "PT2H"}
    if events is not None:
        row["events"] = events
    return row


def test_banner_names_the_reboot_skips_and_the_real_kill(tmp_path):
    now = time.time()
    rows = [
        _row("RC-ClaudeQuotaWatch", last_run=_iso(now, 3600.0),
             events=[{"id": 153, "time": _iso(now, 3600.0 - 27.0), "rc": None}]),
        _row("RC-PatchRefresh", last_run=_iso(now, 3600.0),
             events=[{"id": 153, "time": _iso(now, 3600.0 - 27.0), "rc": None}]),
        _row("RC-ReplayRosterPull", last_run=_iso(now, 3600.0), time_limit="PT45M",
             events=[{"id": 100, "time": _iso(now, 3600.0), "rc": None},
                     {"id": 111, "time": _iso(now, 900.0), "rc": None}]),
        # No event data at all: the probe did not run or failed soft.
        _row("RC-CleanupScratch", last_run=_iso(now, 3600.0)),
    ]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    got = {a.split()[3]: a for a in anomalies if a.startswith("Legion: scheduled task ")}
    assert got["RC-ClaudeQuotaWatch"] == (
        "Legion: scheduled task RC-ClaudeQuotaWatch MISSED - " + MISSED_153)
    assert got["RC-PatchRefresh"] == (
        "Legion: scheduled task RC-PatchRefresh MISSED - " + MISSED_153)
    assert got["RC-ReplayRosterPull"] == (
        "Legion: scheduled task RC-ReplayRosterPull FAILURE - " + KILL)
    assert got["RC-CleanupScratch"] == (
        "Legion: scheduled task RC-CleanupScratch FAILURE - " + KILL)
    for a in anomalies:
        assert a.isascii(), a


# -------------------------------------------------------------- event probe


class _P:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_event_probe_is_windowless_and_groups_by_task_name(monkeypatch):
    seen = []
    payload = [
        {"task": "\\RC-PatchRefresh", "id": 153, "time": "2026-10-31T19:07:34.0495880-05:00",
         "rc": None},
        {"task": "\\RC-ClaudeQuotaWatch", "id": 201, "time": "2026-10-31T18:54:00.2600503-05:00",
         "rc": 0},
        {"task": "\\RC-SomethingElse", "id": 153, "time": "2026-10-31T19:07:34.0-05:00",
         "rc": None},
    ]

    def fake_run(args, **kw):
        seen.append((args, kw))
        return _P(0, json.dumps(payload))

    bind_subprocess(monkeypatch, rc_facts, run=fake_run)
    got = rc_facts._task_events(["RC-PatchRefresh", "RC-ClaudeQuotaWatch"], time.time() - _DAY)
    assert got == {
        "RC-PatchRefresh": [{"id": 153, "time": "2026-10-31T19:07:34.0495880-05:00",
                             "rc": None}],
        "RC-ClaudeQuotaWatch": [{"id": 201, "time": "2026-10-31T18:54:00.2600503-05:00",
                                 "rc": 0}],
    }
    assert len(seen) == 1
    args, kw = seen[0]
    assert kw.get("creationflags") == rc_facts._NO_WINDOW
    cmd = " ".join(args)
    assert "Microsoft-Windows-TaskScheduler/Operational" in cmd
    for eid in (100, 111, 153, 201, 329):
        assert f"EventID={eid}" in cmd, eid
    assert "\\RC-PatchRefresh" in cmd and "\\RC-ClaudeQuotaWatch" in cmd


def test_event_probe_fails_soft_to_none(monkeypatch):
    for result in (_P(3, ""), _P(0, ""), _P(0, "not json")):
        bind_subprocess(monkeypatch, rc_facts, run=lambda *a, _r=result, **k: _r)
        assert rc_facts._task_events(["RC-PatchRefresh"], time.time()) is None

    def boom(*_a, **kw):
        raise rc_facts.subprocess.TimeoutExpired("powershell.exe", kw.get("timeout"))

    bind_subprocess(monkeypatch, rc_facts, run=boom)
    assert rc_facts._task_events(["RC-PatchRefresh"], time.time()) is None


def test_event_probe_never_splices_an_unsafe_task_name(monkeypatch):
    calls = []
    bind_subprocess(monkeypatch, rc_facts,
                    run=lambda *a, **k: calls.append(a) or _P(0, "[]"))
    assert rc_facts._task_events(["RC-x' or '1'='1"], time.time()) == {}
    assert calls == []


def test_tasks_probe_queries_events_only_for_timeout_code_rows(monkeypatch):
    now = time.time()
    rows = [
        {"name": "RC-PatchRefresh", "state": "Ready", "last_result": CODE,
         "last_run": _iso(now, 3600.0)},
        {"name": "RC-CostHealthWatchdog", "state": "Ready", "last_result": 0,
         "last_run": _iso(now, 60.0)},
    ]
    asked = []

    def fake_events(names, since_ts):
        asked.append((sorted(names), since_ts))
        return {"RC-PatchRefresh": [{"id": 153, "time": _iso(now, 3573.0), "rc": None}]}

    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [dict(r) for r in rows])
    monkeypatch.setattr(rc_facts, "_task_events", fake_events)
    got = rc_facts._legion_tasks_with_events()
    assert [n for n, _s in asked] == [["RC-PatchRefresh"]]
    # The window opens before the reported run, by the LastRunTime slack.
    assert asked[0][1] < rc_facts._parse_ts(rows[0]["last_run"])
    by = {r["name"]: r for r in got}
    assert by["RC-PatchRefresh"]["events"] == [
        {"id": 153, "time": _iso(now, 3573.0), "rc": None}]
    assert "events" not in by["RC-CostHealthWatchdog"]

    # No 0x800710E0 row: the event log is never touched.
    asked.clear()
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [dict(rows[1])])
    rc_facts._legion_tasks_with_events()
    assert asked == []


def test_tasks_probe_fails_soft_when_the_log_cannot_be_read(monkeypatch):
    now = time.time()
    row = {"name": "RC-PatchRefresh", "state": "Ready", "last_result": CODE,
           "last_run": _iso(now, 3600.0)}
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [dict(row)])
    monkeypatch.setattr(rc_facts, "_task_events", lambda names, since_ts: None)
    got = rc_facts._legion_tasks_with_events()
    assert got == [row]
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: None)
    assert rc_facts._legion_tasks_with_events() is None


def test_main_prints_the_missed_run_label_end_to_end(monkeypatch, tmp_path):
    import io
    import sys as _sys

    now = time.time()
    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}', encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", dict)
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [
        _row("RC-ClaudeQuotaWatch", last_run=_iso(now, 3600.0))])
    monkeypatch.setattr(rc_facts, "_task_events", lambda names, since_ts: {
        "RC-ClaudeQuotaWatch": [{"id": 153, "time": _iso(now, 3573.0), "rc": None}]})
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    buf = io.StringIO()
    monkeypatch.setattr(_sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    text = buf.getvalue()
    assert "RC-ClaudeQuotaWatch MISSED - " + MISSED_153 in text
    assert "RC-ClaudeQuotaWatch FAILURE" not in text
