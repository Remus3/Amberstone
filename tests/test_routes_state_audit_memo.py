"""S6 cost sweep - `_agent6_audit_outcomes` memoization contract.

`/api/health/all` calls `_agent6_audit_outcomes()` once per request, and that
function read + json.loads EVERY line of `agents/state/task_queue.jsonl` to
return the last 3 matching events. Measured 2026-08-02 on the live file:
4,645,089 bytes / 5,813 lines, 33.5-47.0 ms per call, at a measured 0.134
req/s. The file only grows, so the cost grew with it.

The memo is keyed on the source file's own identity, NOT on a clock. A TTL
would trade health freshness for speed, which is a product degrade; a
stat-keyed memo invalidates the instant the file changes, so the served body
stays byte-identical to the unmemoized path at every moment.

Why the key carries st_size and not st_mtime_ns alone: measured on this
machine, both the repo volume and the temp volume report st_mtime_ns in ~1 ms
steps (consecutive appends yielded deltas of 0 or ~1,000,000 ns). Two writes
inside the same millisecond therefore share an mtime. Both of the file's
mutation paths change its size - appends grow it, and
`agents.agent1_lead.scheduler.Scheduler.compact` only rewrites when the line
count strictly drops (scheduler.py:315-321) - so size is the discriminator
that mtime granularity cannot provide. `test_size_change_invalidates_even_when_mtime_is_identical`
pins exactly that.
"""
from __future__ import annotations

import json
import os
import pathlib
from unittest import mock

from dashboard._errors import GENERIC_ERROR

import dashboard.routes_state as rs


# -- fixture helpers ------------------------------------------------------

def _event(task_id: str, op: str, event: str, ts: str, status: str = "ok",
           last_error=None) -> str:
    return json.dumps({
        "event": event,
        "ts": ts,
        "task": {"id": task_id, "op": op, "status": status,
                 "last_error": last_error},
    })


# A deliberate mix: matching ops, a non-matching op, a non-matching event, a
# blank line and an unparseable line - the filter must behave identically
# memoized and unmemoized on all of them.
_LINES = [
    _event("t1", "agent6-full-audit-pass", "completed", "2026-08-01T00:00:00"),
    _event("t2", "game-summary", "completed", "2026-08-01T00:01:00"),
    _event("t3", "agent6-full-audit-pass", "started", "2026-08-01T00:02:00"),
    "",
    "{not json at all",
    _event("t4", "agent6-full-audit-pass", "failed", "2026-08-01T00:03:00",
           status="error", last_error="boom"),
    _event("t5", "agent6-full-audit-pass", "reclassified_completed",
           "2026-08-01T00:04:00"),
    _event("t6", "agent6-full-audit-pass", "completed", "2026-08-01T00:05:00"),
]


def _write_queue(root: pathlib.Path, lines) -> pathlib.Path:
    q = root / "agents" / "state" / "task_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return q


def _reset_memo() -> None:
    # Module-global memo; each test starts cold so ordering cannot leak state.
    rs._A6_MEMO = None


def _reference_outcomes(q: pathlib.Path, max_count: int = 3) -> list:
    """Independent re-implementation of the pre-memo scan.

    Deliberately not a call into routes_state: comparing the memoized result
    against the function's own uncached branch would only prove the branch
    agrees with itself.
    """
    outcomes: list = []
    for raw in q.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        task = ev.get("task") or {}
        if task.get("op") != "agent6-full-audit-pass":
            continue
        if ev.get("event") not in ("completed", "failed", "reclassified_completed"):
            continue
        outcomes.append({
            "task_id": task.get("id"),
            "event": ev.get("event"),
            "ts": ev.get("ts"),
            "status": task.get("status"),
            # Lane 8 cycle 19: the scan scrubs `last_error` before it is
            # serialized into /api/health/all - the raw text goes to logs/ only
            # (tests/test_routes_state_health_scrub.py pins that contract). This
            # oracle tracks the field mapping so it keeps testing what it is FOR,
            # namely that the memo agrees with an unmemoized scan.
            "last_error": GENERIC_ERROR if task.get("last_error") else None,
        })
    return outcomes[-max_count:]


# -- exactness: the memo must not change what is served -------------------

def test_result_is_byte_identical_to_the_unmemoized_scan(tmp_path):
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    expected = _reference_outcomes(q, 3)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        first = rs._agent6_audit_outcomes(max_count=3)
        second = rs._agent6_audit_outcomes(max_count=3)
    assert first == expected
    # The served body is json.dumps of this value, so pin the serialized form.
    assert json.dumps(second) == json.dumps(expected)


def test_memoized_result_is_not_the_same_mutable_list(tmp_path):
    # A caller mutating the returned list must not corrupt the memo for the
    # next request.
    _reset_memo()
    _write_queue(tmp_path, _LINES)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        first = rs._agent6_audit_outcomes(max_count=3)
        first.append({"task_id": "injected"})
        second = rs._agent6_audit_outcomes(max_count=3)
    assert len(second) == 3
    assert all(o.get("task_id") != "injected" for o in second)


# -- the memo must actually memoize ---------------------------------------

def test_second_call_does_not_reread_the_file(tmp_path):
    _reset_memo()
    _write_queue(tmp_path, _LINES)
    real_read_text = pathlib.Path.read_text
    calls = []

    def counting_read_text(self, *a, **kw):
        calls.append(str(self))
        return real_read_text(self, *a, **kw)

    with mock.patch.object(rs, "APP_DIR", tmp_path):
        rs._agent6_audit_outcomes(max_count=3)
        with mock.patch.object(pathlib.Path, "read_text", counting_read_text):
            rs._agent6_audit_outcomes(max_count=3)
            rs._agent6_audit_outcomes(max_count=3)
    assert calls == [], f"unmemoized re-read of the queue file: {calls}"


# -- the memo must invalidate ---------------------------------------------

def test_append_invalidates_the_memo(tmp_path):
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        before = rs._agent6_audit_outcomes(max_count=3)
        with q.open("a", encoding="utf-8") as fh:
            fh.write(_event("t7", "agent6-full-audit-pass", "completed",
                            "2026-08-01T00:06:00") + "\n")
        after = rs._agent6_audit_outcomes(max_count=3)
    assert before != after
    assert after == _reference_outcomes(q, 3)
    assert after[-1]["task_id"] == "t7"


def test_size_change_invalidates_even_when_mtime_is_identical(tmp_path):
    # The Windows granularity guard. st_mtime_ns advances in ~1 ms steps here,
    # so a same-millisecond write can carry the previous mtime; forcing the
    # mtime back proves the memo does not depend on it alone.
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    frozen = q.stat().st_mtime_ns
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        before = rs._agent6_audit_outcomes(max_count=3)
        with q.open("a", encoding="utf-8") as fh:
            fh.write(_event("t8", "agent6-full-audit-pass", "failed",
                            "2026-08-01T00:07:00", status="error") + "\n")
        os.utime(q, ns=(frozen, frozen))
        assert q.stat().st_mtime_ns == frozen
        after = rs._agent6_audit_outcomes(max_count=3)
    assert before != after
    assert after[-1]["task_id"] == "t8"


def test_compaction_shrink_invalidates_the_memo(tmp_path):
    # Scheduler.compact rewrites the file to strictly fewer lines; the memo
    # must follow it down, not just up.
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        before = rs._agent6_audit_outcomes(max_count=3)
        _write_queue(tmp_path, _LINES[:1])
        after = rs._agent6_audit_outcomes(max_count=3)
    assert len(before) == 3
    assert after == _reference_outcomes(q, 3)
    assert len(after) == 1


def test_max_count_is_part_of_the_memo_key(tmp_path):
    # Two callers asking for different depths of the same unchanged file must
    # not receive each other's answer.
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        three = rs._agent6_audit_outcomes(max_count=3)
        one = rs._agent6_audit_outcomes(max_count=1)
        three_again = rs._agent6_audit_outcomes(max_count=3)
    assert len(three) == 3
    assert one == _reference_outcomes(q, 1)
    assert len(one) == 1
    assert three_again == three


# -- degradation contract unchanged ---------------------------------------

def test_missing_file_returns_empty_and_is_not_memoized_as_present(tmp_path):
    _reset_memo()
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        assert rs._agent6_audit_outcomes(max_count=3) == []
        q = _write_queue(tmp_path, _LINES)
        assert rs._agent6_audit_outcomes(max_count=3) == _reference_outcomes(q, 3)


def test_unreadable_file_degrades_to_empty(tmp_path):
    _reset_memo()
    _write_queue(tmp_path, _LINES)
    with mock.patch.object(rs, "APP_DIR", tmp_path), \
            mock.patch.object(pathlib.Path, "read_text",
                              side_effect=OSError("nope")):
        assert rs._agent6_audit_outcomes(max_count=3) == []


def test_a_transient_read_error_is_not_memoized(tmp_path):
    # The file is unchanged across all three calls, so a naive memo would pin
    # the error's empty result forever. A failed scan must never be cached.
    _reset_memo()
    q = _write_queue(tmp_path, _LINES)
    expected = _reference_outcomes(q, 3)
    with mock.patch.object(rs, "APP_DIR", tmp_path):
        with mock.patch.object(pathlib.Path, "read_text",
                               side_effect=OSError("transient")):
            assert rs._agent6_audit_outcomes(max_count=3) == []
        assert rs._agent6_audit_outcomes(max_count=3) == expected
