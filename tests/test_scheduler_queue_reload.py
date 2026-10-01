"""Regression: the Scheduler must see records appended by OTHER processes.

Measured defect (2026-09-29): ``Scheduler`` calls ``_load()`` exactly once,
at construction. The weekly cron shim ``ops/phase3_file_audit.py`` runs in a
SEPARATE process and appends a task envelope to ``agents/state/task_queue.jsonl``.
The long-lived supervisor (``agents/supervisor.py`` ``_dispatch_loop`` ->
``next_ready()``) therefore never sees it, so the task cannot dispatch until
the whole stack is restarted. Live proof: task ``t-f65ba5e9c492`` was filed
2026-09-27T08:00Z and was still ``ready`` and undispatched days later because
the supervisor process predated it.

These tests pin the tail-reload contract:

  1. A record appended by an external writer becomes visible to an
     ALREADY-CONSTRUCTED Scheduler (the regression itself).
  2. A partially written final line is NOT consumed, and IS consumed once
     the writer finishes it.
  3. A compaction (the file is rewritten SMALLER) is picked up by a full
     reload and does not resurrect stale state.
  4. A refresh with no new bytes parses nothing and duplicates nothing.
  5. An unreadable / locked queue log leaves the Scheduler usable and
     raises nothing.

Follow-up (verifier refutation, same session): ``refresh()`` promises
"never raises" and ``next_ready()`` leans on that. Two record shapes an
external writer can legitimately produce broke it on the FULL-RELOAD
branch, which ``next_ready()`` did not reach before the tail-reload
landed - so the blast radius of a bad record went from "cold start" to
"every dispatch tick after a compaction":

  6. A record carrying a field this build does not know (written by a
     newer build) must be skipped, not raise, across a compaction.
  7. A line that decodes to something other than an object must be
     skipped everywhere the log is parsed.

And two offset-bookkeeping tests, because a rewrite that leaves the file
LARGER than the consumed prefix is not caught by the shrink check:

  8. An in-process ``compact()`` must not skip a record the scheduler
     had not tailed yet.
  9. The same for an external in-place rewrite.

All tests use ``tmp_path`` - never the live ``agents/state/task_queue.jsonl``.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agents.agent1_lead.scheduler import (  # noqa: E402
    QueueTask,
    Scheduler,
    TaskStatus,
)


# ----- helpers ----------------------------------------------------------
def _record_line(
    task_id: str,
    *,
    op: str = "external-op",
    status: str = TaskStatus.READY,
    priority: int = 50,
    event: str = "filed",
    result: object = None,
    extra_task_fields: dict[str, object] | None = None,
) -> str:
    """Build one JSONL line exactly as ``Scheduler._append_log`` would.

    ``extra_task_fields`` models a record written by a NEWER build that
    added a dataclass field this build does not have.
    """
    ts = datetime.now(timezone.utc).isoformat()
    task = QueueTask(
        id=task_id,
        op=op,
        owner_agent="6",
        priority=priority,
        status=status,
        created_at=ts,
        updated_at=ts,
        result=result,
    )
    task_dict = asdict(task)
    if extra_task_fields:
        task_dict.update(extra_task_fields)
    rec = {"event": event, "ts": ts, "task": task_dict}
    return json.dumps(rec, separators=(",", ":"), default=str) + "\n"


def _external_append(log: Path, text: str) -> None:
    """Append raw text as a SEPARATE process would - bytes, LF only.

    Deliberately not via a second Scheduler: this models the cron shim
    writing to the same file while the supervisor holds its own instance.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as f:
        f.write(text.encode("utf-8"))


def _new_scheduler(log: Path, *, precreate: bool = False) -> Scheduler:
    """Build a Scheduler with the daemon compactor thread disabled.

    ``precreate`` writes an empty log BEFORE construction so ``_load()``
    adopts the file and records its identity. Without it the first
    ``refresh()`` sees an unknown file and takes the full-reload branch,
    which is the right behaviour but hides the incremental tail path the
    offset tests are about.
    """
    if precreate:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b"")
    # compact_interval_s=0 keeps the daemon compactor thread out of the test.
    return Scheduler(queue_log=log, compact_interval_s=0)


# ----- 1. the regression ------------------------------------------------
def test_externally_appended_task_is_dispatchable_without_restart(
    tmp_path: Path,
) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)
    assert s.next_ready() is None, "fixture bug - queue should start empty"

    _external_append(log, _record_line("t-ext-1", op="phase3-file-audit"))

    got = s.next_ready()
    assert got is not None, (
        "next_ready() returned None - the externally filed task is invisible "
        "to the already-constructed Scheduler (the measured defect)"
    )
    assert got.id == "t-ext-1"
    assert got.op == "phase3-file-audit"
    assert got.status == TaskStatus.IN_PROGRESS
    # Dispatched exactly once.
    assert s.next_ready() is None


def test_externally_appended_task_respects_priority_order(tmp_path: Path) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)
    _external_append(log, _record_line("t-low", priority=90))
    _external_append(log, _record_line("t-high", priority=10))

    first = s.next_ready()
    second = s.next_ready()
    assert first is not None and second is not None
    assert (first.id, second.id) == ("t-high", "t-low")


# ----- 2. partial last line --------------------------------------------
def test_partial_final_line_is_not_consumed_until_complete(tmp_path: Path) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)

    whole = _record_line("t-partial", priority=20)
    head, tail = whole[:40], whole[40:]
    assert not head.endswith("\n")

    _external_append(log, _record_line("t-complete", priority=10))
    _external_append(log, head)  # writer is mid-append

    applied = s.refresh()
    assert applied == 1, "the truncated trailing record must not be consumed"
    assert s.get("t-complete") is not None
    assert s.get("t-partial") is None

    offset_before = s._log_offset

    # Writer finishes the record.
    _external_append(log, tail)
    applied = s.refresh()
    assert applied == 1
    assert s._log_offset > offset_before
    t = s.get("t-partial")
    assert t is not None and t.status == TaskStatus.READY

    assert s.next_ready().id == "t-complete"
    assert s.next_ready().id == "t-partial"
    assert s.next_ready() is None


# ----- 3. compaction / file rewritten smaller ---------------------------
def test_compaction_shrink_is_reloaded_without_resurrecting_state(
    tmp_path: Path,
) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)

    _external_append(log, _record_line("t-a", priority=10))
    _external_append(
        log, _record_line("t-a", status=TaskStatus.IN_PROGRESS, event="dispatched"),
    )
    _external_append(
        log,
        _record_line(
            "t-a", status=TaskStatus.COMPLETED, event="completed", result={"ok": True},
        ),
    )
    _external_append(log, _record_line("t-b", priority=20))
    s.refresh()
    assert s.get("t-a").status == TaskStatus.COMPLETED
    assert s.get("t-b").status == TaskStatus.READY
    size_before = log.stat().st_size

    # External compaction: latest event per task id, rewritten in place.
    compacted = (
        _record_line(
            "t-a", status=TaskStatus.COMPLETED, event="completed", result={"ok": True},
        )
        + _record_line("t-b", priority=20)
    )
    log.write_bytes(compacted.encode("utf-8"))
    assert log.stat().st_size < size_before

    s.refresh()
    assert len(s._tasks) == 2, "reload must not duplicate tasks"
    assert s.get("t-a").status == TaskStatus.COMPLETED, (
        "the compacted latest-wins file must not resurrect t-a as ready"
    )
    assert s.get("t-b").status == TaskStatus.READY

    got = s.next_ready()
    assert got is not None and got.id == "t-b", "completed t-a must not re-dispatch"
    assert s.next_ready() is None


# ----- 4. idle refresh is cheap ----------------------------------------
def test_refresh_with_no_new_bytes_does_not_reparse_or_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)
    _external_append(log, _record_line("t-once"))
    assert s.refresh() == 1

    offset = s._log_offset
    task_count = len(s._tasks)
    heap_len = len(s._heap)

    calls: list[str] = []
    real_apply = Scheduler._apply_task_record

    def _counting_apply(self, task_dict):  # type: ignore[no-untyped-def]
        calls.append(task_dict.get("id", ""))
        return real_apply(self, task_dict)

    monkeypatch.setattr(Scheduler, "_apply_task_record", _counting_apply)

    for _ in range(5):
        assert s.refresh() == 0

    assert calls == [], "idle refresh re-parsed the log"
    assert s._log_offset == offset
    assert len(s._tasks) == task_count
    assert len(s._heap) == heap_len


# ----- 5. unreadable / locked file --------------------------------------
def test_unreadable_queue_log_leaves_scheduler_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)
    _external_append(log, _record_line("t-known"))
    assert s.refresh() == 1

    # Another process now holds the file open for writing. Every binary
    # read of THIS path fails; writes (the append path) are untouched.
    real_open = Path.open

    def _blocked_open(self, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == log and "b" in mode and "r" in mode:
            raise PermissionError(32, "The process cannot access the file")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _blocked_open)

    _external_append(log, _record_line("t-invisible"))
    assert s.refresh() == 0, "a failed read must leave the offset untouched"
    assert s.get("t-invisible") is None

    got = s.next_ready()
    assert got is not None and got.id == "t-known"

    # Lock released: the missed record is picked up on the next tick.
    monkeypatch.undo()
    assert s.refresh() >= 1
    assert s.get("t-invisible") is not None


# ----- 6. record from a newer build (unknown dataclass field) -----------
def test_unknown_field_record_does_not_raise_on_full_reload(tmp_path: Path) -> None:
    """A field this build lacks must be skipped on BOTH read paths.

    The tail path guarded ``QueueTask(**task_dict)``; ``_load()`` did not.
    Because a compaction shrinks the log and therefore routes the next
    refresh into ``_load()``, the asymmetry turned one such record into a
    TypeError on EVERY dispatch tick after compaction.
    """
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)

    _external_append(log, _record_line("t-keep", priority=20))
    _external_append(log, _record_line("t-noise", priority=30))
    _external_append(
        log, _record_line("t-noise", status=TaskStatus.COMPLETED, event="completed"),
    )
    _external_append(
        log,
        _record_line(
            "t-future", priority=10, extra_task_fields={"deadline_at": "2026-10-01"},
        ),
    )

    # Tail path already tolerated it: 3 of 4 records applied.
    assert s.refresh() == 3
    assert s.get("t-future") is None

    # Compaction shrinks the log, so the next refresh takes _load().
    assert s.compact() == (4, 3)

    got = s.next_ready()
    assert got is not None, "next_ready() found nothing after the full reload"
    assert got.id == "t-keep"
    assert s.get("t-future") is None, "an unconstructible record must not be stored"
    assert s.next_ready() is None


# ----- 7. line that is valid JSON but not an object ---------------------
def test_non_object_json_lines_do_not_crash_the_dispatch_path(
    tmp_path: Path,
) -> None:
    """``json.loads`` returns lists, strings and numbers quite happily.

    Every reader of this log did ``rec.get("task")`` without checking the
    shape, so one such line raised AttributeError instead of being
    skipped - on the tail path, in ``_load()``, and in the disk-verify
    that ``next_ready()`` runs before every dispatch.
    """
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)

    _external_append(log, "[1, 2, 3]\n")
    _external_append(log, '"not a record"\n')
    _external_append(log, "42\n")
    _external_append(log, '{"event":"filed","ts":"now","task":"not-a-dict"}\n')
    _external_append(log, _record_line("t-ok", priority=15))

    assert s.refresh() == 1, "only the well-formed record should apply"

    got = s.next_ready()
    assert got is not None and got.id == "t-ok"

    # Same junk must survive the full-reload branch (file rewritten smaller).
    s2 = _new_scheduler(log)
    assert s2.get("t-ok") is not None
    shrunk = "[1, 2, 3]\n" + _record_line("t-ok2", priority=15)
    log.write_bytes(shrunk.encode("utf-8"))
    got2 = s2.next_ready()
    assert got2 is not None and got2.id == "t-ok2"


# ----- 8. in-process compaction must not skip an untailed record --------
def test_in_process_compaction_does_not_skip_an_unconsumed_record(
    tmp_path: Path,
) -> None:
    """``_log_offset`` is only advanced by ``refresh()``, so it routinely
    lags the end of the file. Compaction then MOVES records to lower byte
    positions. When the compacted file is still larger than that stale
    offset the shrink check does not fire, and the incremental read
    starts PAST a record that was never applied - a silent skip, which is
    the one outcome the offset bookkeeping must never produce.
    """
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)

    filed_a = _record_line("t-a", op="a" * 200, priority=30)
    done_a = _record_line(
        "t-a", op="a" * 200, status=TaskStatus.COMPLETED, event="completed",
    )
    ext = _record_line("t-ext", op="e" * 400, priority=10)

    _external_append(log, filed_a)
    _external_append(log, done_a)
    assert s.refresh() == 2
    consumed = s._log_offset

    # Arrives after our last tick - the scheduler has NOT seen it yet.
    _external_append(log, ext)
    assert s.get("t-ext") is None

    # Precondition: the compacted file stays larger than the consumed
    # prefix, so the "file shrank" branch does NOT rescue us.
    assert len(done_a) + len(ext) >= consumed, "test lost its own precondition"

    assert s.compact() == (3, 2)

    got = s.next_ready()
    assert got is not None, (
        "the untailed record was skipped by compaction - the byte offset "
        "pointed past it in the rewritten file"
    )
    assert got.id == "t-ext"


def test_external_inplace_rewrite_does_not_skip_an_unconsumed_record(
    tmp_path: Path,
) -> None:
    """Same hazard, but the rewrite happens in another process, so
    invalidating our own bookkeeping inside ``compact()`` cannot help.
    The byte in front of ``_log_offset`` is no longer a newline, which is
    what proves the offset no longer refers to this file's records.
    """
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)

    filed_a = _record_line("t-a", op="a" * 200, priority=30)
    done_a = _record_line(
        "t-a", op="a" * 200, status=TaskStatus.COMPLETED, event="completed",
    )
    ext = _record_line("t-ext", op="e" * 400, priority=10)

    _external_append(log, filed_a)
    _external_append(log, done_a)
    assert s.refresh() == 2
    consumed = s._log_offset

    _external_append(log, ext)
    assert s.get("t-ext") is None

    rewritten = (done_a + ext).encode("utf-8")
    assert len(rewritten) >= consumed, "test lost its own precondition"
    log.write_bytes(rewritten)

    got = s.next_ready()
    assert got is not None, (
        "an external in-place compaction moved the record below the stale "
        "offset and it was never applied"
    )
    assert got.id == "t-ext"


# ----- 10. a record whose priority would poison the heap ----------------
def test_non_numeric_priority_record_cannot_break_dispatch(tmp_path: Path) -> None:
    """Heap entries are ``(priority, counter, task_id)``.

    A record carrying a string priority constructs fine and then raises
    ``'<' not supported between instances of 'str' and 'int'`` the first
    time it is compared against a normal entry - i.e. at an unrelated
    dispatch, not at the record that caused it. Neither read path
    defended against it, and the tail path made it reachable on a LIVE
    tick rather than only at cold start.
    """
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)

    _external_append(log, _record_line("t-sane", priority=10))
    _external_append(log, _record_line("t-poison", priority="90"))
    assert s.refresh() == 1, "the poison record must not be applied"
    assert s.get("t-poison") is None

    got = s.next_ready()
    assert got is not None and got.id == "t-sane"

    # Also rejected on the in-place update branch: t-sane is already
    # known, so a later bad record must not setattr its priority.
    _external_append(log, _record_line("t-sane", priority="threefiddy"))
    s.refresh()
    assert s.get("t-sane").priority == 10

    # And on the cold-start / full-reload path.
    s2 = _new_scheduler(log)
    assert s2.get("t-poison") is None
    assert s2.get("t-sane") is not None
