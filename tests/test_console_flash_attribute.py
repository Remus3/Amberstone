"""Guard: the console-flash attributor joins on (pid, start time), never pid alone.

WHY THIS EXISTS. A console flash is a window that lives about 20-40 ms, so the
only way to name its owner is post hoc: a window detector stamps the event, a
separate process-start tracer records who started when, and something joins the
two afterwards. A pid-only join is wrong BY CONSTRUCTION on this box - measured
2026-09-14, a conhost pid was re-issued eight minutes after a flash, so the
naive join would have credited the window to a process that did not exist yet.

The join therefore refuses two shapes outright:

* a candidate whose start is AFTER the event (it cannot own an earlier window);
* a pid carrying MORE THAN ONE start at or before the event (re-issued, so the
  record cannot say which of the two owned the window).

The rest of the module is about making absence provable rather than assumed: a
missing process trace reports UNATTRIBUTED with its reason instead of guessing,
a heartbeat gap over 90 s reports DEAD-WINDOW so a dead sampler cannot read as
a quiet machine, and a positive-control capture asserts that an unflagged spawn
DID produce a window and a flagged one did NOT.

THE FIXTURE IS A PUBLIC-REPO HAZARD BY DEFAULT, which is why it is synthetic and
why one of the tests below reads its committed bytes: a real capture carries the
account home directory and neighbouring project directory names in every command
line, and `.log` is not in tests/test_no_hardcoded_home_path.py RUNNABLE_SUFFIXES
so that guard would never scan it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# A HARD import. `pytest.importorskip` would make "the attributor does not
# exist" and "the attributor is correct" the same green run.
from tools import console_flash_attribute as cfa  # noqa: E402
from tools import sibling_name_sweep as sweep  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "console_flash_control_synthetic.log"


def _attribute(text: str):
    return cfa.attribute(cfa.parse_capture(text))


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

_PID = 41412

_RECYCLED = """\
START ts=2026-09-15T22:29:00.000000Z seconds=90 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=90
EVENT ts=2026-09-15T22:29:13.250000Z event=0x8002 hwnd=0x00120abc pid=41412 exe=conhost.exe cls=ConsoleWindowClass
PROCESS ts=2026-09-15T22:37:42.708000Z name=conhost.exe pid=41412 ppid=26692 created=2026-09-15T22:37:42.700000Z
HEARTBEAT ts=2026-09-15T22:29:30.000000Z pumps=3600 pumps_per_second=120.0 events=1
END ts=2026-09-15T22:30:30.000000Z events=1 pumps=10800
"""

_IN_TIME = """\
START ts=2026-09-15T22:29:00.000000Z seconds=90 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=90
PROCESS ts=2026-09-15T22:29:13.205000Z name=conhost.exe pid=41412 ppid=26692 created=2026-09-15T22:29:13.200000Z
EVENT ts=2026-09-15T22:29:13.250000Z event=0x8002 hwnd=0x00120abc pid=41412 exe=conhost.exe cls=ConsoleWindowClass
HEARTBEAT ts=2026-09-15T22:29:30.000000Z pumps=3600 pumps_per_second=120.0 events=1
END ts=2026-09-15T22:30:30.000000Z events=1 pumps=10800
"""


def test_join_uses_pid_and_start_time_not_pid_alone() -> None:
    late = _attribute(_RECYCLED)
    assert len(late.attributions) == 1
    only = late.attributions[0]
    assert only.event.pid == _PID
    assert only.record is None, (
        "a trace record that starts AFTER the event was joined to it - that is "
        "the measured pid-recycle failure the join exists to refuse"
    )
    assert only.reason == cfa.REASON_START_AFTER_EVENT

    early = _attribute(_IN_TIME)
    assert len(early.attributions) == 1
    joined = early.attributions[0]
    assert joined.record is not None, (
        "the same pid started 50 ms BEFORE the event must join - a join that "
        "refuses everything is as useless as one that accepts everything"
    )
    assert joined.record.pid == _PID
    assert joined.record.name == "conhost.exe"
    assert joined.reason == ""


_RECYCLED_BOTH_BEFORE = """\
START ts=2026-09-15T22:29:00.000000Z seconds=90 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=90
PROCESS ts=2026-09-15T22:29:01.000000Z name=where.exe pid=41412 ppid=26692 created=2026-09-15T22:29:01.000000Z
PROCESS ts=2026-09-15T22:29:13.205000Z name=conhost.exe pid=41412 ppid=26692 created=2026-09-15T22:29:13.200000Z
EVENT ts=2026-09-15T22:29:13.250000Z event=0x8002 hwnd=0x00120abc pid=41412 exe=conhost.exe cls=ConsoleWindowClass
END ts=2026-09-15T22:30:30.000000Z events=1 pumps=10800
"""


_DELIVERY_LAG = """\
START ts=2026-09-15T18:36:52.000000Z seconds=70 pid=4242
START-TRACE ts=2026-09-15T18:36:52.010000Z seconds=70
CONTROL ts=2026-09-15T18:36:56.466451Z seq=1 flagged=0 name=cmd.exe pid=7812
EVENT ts=2026-09-15T18:36:56.496736Z event=0x8002 hwnd=0x000a0108 pid=7812 exe=cmd.exe cls=ConsoleWindowClass
PROCESS ts=2026-09-15T18:36:58.101376Z name=cmd.exe pid=7812 ppid=17132 created=2026-09-15T18:36:57.868207Z
HEARTBEAT ts=2026-09-15T18:37:22.459392Z pumps=5276 pumps_per_second=175.8 events=1
END ts=2026-09-15T18:38:02.455109Z events=1 pumps=12351
"""


def test_trace_start_stamp_lag_is_bounded_not_ignored() -> None:
    # MEASURED 2026-09-15 by the positive control in this repository:
    # Win32_ProcessStartTrace TIME_CREATED is an EVENT-GENERATION stamp, not the
    # process creation time, and WMI delivered it 1.40 s AFTER a cmd.exe that
    # the control had already spawned and the detector had already seen. A
    # strict "created must be <= the event" rule therefore refused all four
    # genuine control pairs. The rule is kept and given the measured bound
    # instead of being dropped - an unbounded tolerance would re-admit the
    # eight-minute pid recycle the join exists to refuse.
    report = _attribute(_DELIVERY_LAG)
    only = report.attributions[0]
    assert only.record is not None, (
        "a trace record delivered 1.4 s late is the MEASURED normal case; "
        "refusing it makes every real capture UNATTRIBUTED"
    )
    assert only.record.name == "cmd.exe"
    assert cfa.TRACE_LAG_SECONDS < 480, (
        "the tolerance must stay far below the eight-minute pid recycle "
        "measured on this box, or it re-admits exactly that failure"
    )
    assert report.controls[0].events, "control 1 must join through its own pid"


def test_pid_reissued_before_the_event_is_refused_not_guessed() -> None:
    report = _attribute(_RECYCLED_BOTH_BEFORE)
    only = report.attributions[0]
    assert only.record is None
    assert only.reason == cfa.REASON_PID_RECYCLED


# ---------------------------------------------------------------------------
# Ancestry
# ---------------------------------------------------------------------------

_CHAIN = """\
START ts=2026-09-15T22:29:00.000000Z seconds=90 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=90
SNAPSHOT phase=START ts=2026-09-15T22:29:00.020000Z name=bash.exe pid=900 ppid=404 created=2026-09-15T22:00:00.000000Z
PROCESS ts=2026-09-15T22:29:10.001000Z name=pythonw.exe pid=20720 ppid=900 created=2026-09-15T22:29:10.000000Z
PROCESS ts=2026-09-15T22:29:10.011000Z name=git.exe pid=41410 ppid=20720 created=2026-09-15T22:29:10.010000Z
PROCESS ts=2026-09-15T22:29:10.021000Z name=conhost.exe pid=41412 ppid=41410 created=2026-09-15T22:29:10.020000Z
EVENT ts=2026-09-15T22:29:10.035000Z event=0x8002 hwnd=0x00120abc pid=41412 exe=conhost.exe cls=ConsoleWindowClass
END ts=2026-09-15T22:30:30.000000Z events=1 pumps=10800
"""


def test_ancestry_walks_to_root_unknown() -> None:
    report = _attribute(_CHAIN)
    only = report.attributions[0]
    assert only.record is not None
    names = [rec.name for rec in only.chain]
    assert names == ["conhost.exe", "git.exe", "pythonw.exe", "bash.exe"]
    # pid 404 has no record, so the walk stops there and SAYS SO rather than
    # implying the chain was complete.
    assert only.chain_text.endswith(cfa.ROOT_UNKNOWN)
    assert cfa.ROOT_UNKNOWN in cfa.render(report)


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------

_GAP = """\
START ts=2026-09-15T22:29:00.000000Z seconds=300 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=300
HEARTBEAT ts=2026-09-15T22:29:30.000000Z pumps=3600 pumps_per_second=120.0 events=0
HEARTBEAT ts=2026-09-15T22:31:30.000000Z pumps=7200 pumps_per_second=30.0 events=0
END ts=2026-09-15T22:32:00.000000Z events=0 pumps=9000
"""

_TIGHT = """\
START ts=2026-09-15T22:29:00.000000Z seconds=300 pid=4242
START-TRACE ts=2026-09-15T22:29:00.010000Z seconds=300
HEARTBEAT ts=2026-09-15T22:29:30.000000Z pumps=3600 pumps_per_second=120.0 events=0
HEARTBEAT ts=2026-09-15T22:30:00.000000Z pumps=7200 pumps_per_second=120.0 events=0
END ts=2026-09-15T22:30:30.000000Z events=0 pumps=9000
"""


def test_heartbeat_gap_is_reported_dead_window() -> None:
    gapped = _attribute(_GAP)
    assert len(gapped.dead_windows) == 1, (
        "120 s between heartbeats is a span in which the sampler proved "
        "nothing, and an unreported gap reads as a quiet machine"
    )
    span = gapped.dead_windows[0]
    assert span.seconds == 120.0
    assert cfa.DEAD_WINDOW in cfa.render(gapped)

    tight = _attribute(_TIGHT)
    assert tight.dead_windows == [], (
        "30 s heartbeats are the designed cadence - flagging those would make "
        "DEAD-WINDOW noise and get it ignored"
    )
    assert cfa.DEAD_WINDOW not in cfa.render(tight)


_NO_TRACE = """\
START ts=2026-09-15T22:29:00.000000Z seconds=90 pid=4242
START-TRACE UNAVAILABLE ts=2026-09-15T22:29:00.010000Z reason=cim-subscription-refused
PROCESS ts=2026-09-15T22:29:13.205000Z name=conhost.exe pid=41412 ppid=26692 created=2026-09-15T22:29:13.200000Z
EVENT ts=2026-09-15T22:29:13.250000Z event=0x8002 hwnd=0x00120abc pid=41412 exe=conhost.exe cls=ConsoleWindowClass
END ts=2026-09-15T22:30:30.000000Z events=1 pumps=10800
"""


def test_start_trace_unavailable_is_surfaced() -> None:
    report = _attribute(_NO_TRACE)
    assert report.trace_available is False
    assert report.attributions, "an event with no trace is still an event"
    for item in report.attributions:
        assert item.record is None, (
            "a PROCESS line that survived a failed subscription must not be "
            "joined - a partial trace is not a trace"
        )
        assert item.reason == cfa.REASON_NO_TRACE
    text = cfa.render(report)
    assert cfa.TRACE_UNAVAILABLE in text
    assert cfa.REASON_NO_TRACE in text


# ---------------------------------------------------------------------------
# The committed fixture
# ---------------------------------------------------------------------------


def test_fixture_carries_no_path_or_account() -> None:
    raw = FIXTURE.read_bytes()
    assert raw, "the fixture is empty - an empty file passes every check below"
    text = raw.decode("ascii")
    assert ":\\" not in text and ":/" not in text, (
        "a drive-rooted path in a tracked capture publishes the account home "
        "directory and the names of neighbouring projects on this box"
    )
    assert "Users" not in text
    findings = sweep.structural_findings(
        text, path="tests/fixtures/console_flash_control_synthetic.log",
        source="worktree",
    )
    assert findings == [], [f.literal for f in findings]


def test_positive_control_log_parses() -> None:
    report = _attribute(FIXTURE.read_text(encoding="ascii"))
    joined = [a for a in report.attributions if a.record is not None]
    assert len(joined) == 2, "both unflagged controls must show a console window"

    with_event = [c for c in report.controls if c.events]
    without_event = [c for c in report.controls if not c.events]
    assert len(with_event) == 2
    assert len(without_event) == 1, (
        "the flagged control must appear as a START with NO event - that is "
        "what proves 'spawned and not visible' rather than 'not sampled'"
    )
    assert without_event[0].control.flagged is True
    assert [c.control.seq for c in with_event] == [1, 2]

    assert report.heartbeat_after_controls is True, (
        "without a heartbeat AFTER the last control, a silent detector and a "
        "clean desktop are the same log"
    )
