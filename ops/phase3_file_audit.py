"""File a fresh agent6-full-audit-pass task into the scheduler queue.

Invoked by the ``RC-Phase3-PeriodicAudit`` scheduled task on a weekly
cadence so Agent 6 does a self-review even when no human is asking.

Idempotent: if a non-terminal audit task already exists, this no-ops so
we don't pile up duplicate audits during multi-day outages.

The scheduled task runs this under ``pythonw.exe`` with no output
redirection, so the ``print()`` calls below go to a console that does not
exist and ``LastTaskResult`` is 0 on the skip path, the file path and after
most silent problems alike. Every invocation therefore also appends one
ISO-8601 UTC line to ``logs/phase3_file_audit.log`` - see ``_log`` - and a
genuine failure exits nonzero so the session-start banner can see it.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agents.agent1_lead import Scheduler, TaskStatus
from core.polled_json import _replace_with_retry

AUDIT_OP = "agent6-full-audit-pass"
NON_TERMINAL = (
    TaskStatus.READY, TaskStatus.IN_PROGRESS,
    TaskStatus.NEEDS_APPROVAL, TaskStatus.AGENT0_REVIEW,
    TaskStatus.RETRY_PENDING, TaskStatus.PENDING,
)

# Resolved from __file__, never from cwd: the scheduled task happens to set
# WorkingDirectory to the repo root today, but that is not ours to rely on.
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "phase3_file_audit.log"
# A weekly append is tiny, but this runs for years. One rotated generation is
# kept, so the pair is bounded at roughly twice the cap.
LOG_MAX_BYTES = 256 * 1024


def _write_log_line(line: str) -> None:
    """Append one line, rotating first if the file has hit the cap.

    Split out from ``_log`` so a test can make the IO half fail on demand.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        oversize = LOG_PATH.stat().st_size >= LOG_MAX_BYTES
    except OSError:
        oversize = False
    if oversize:
        _replace_with_retry(LOG_PATH, LOG_PATH.with_suffix(LOG_PATH.suffix + ".1"))
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def _log(fields: str) -> None:
    """Best-effort ops-log append. A logging failure never costs us the audit."""
    try:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_log_line(f"{stamp} {fields}")
    except Exception:  # noqa: BLE001 - the filing matters more than its log line
        pass


def _flatten(text: str) -> str:
    """Fold a multi-line traceback onto one greppable line."""
    return " | ".join(part.strip() for part in text.strip().splitlines() if part.strip())


def main() -> int:
    """Run the shim, logging and swallowing any unexpected exception.

    Returns 0 on both the file and skip paths (both are healthy outcomes) and
    1 on an unexpected exception, so ``LastTaskResult`` is a real health
    signal instead of a constant 0.
    """
    try:
        return _run()
    except Exception as exc:  # noqa: BLE001 - invisible under pythonw otherwise
        _log(
            f"outcome=error task=- error={type(exc).__name__}: {exc} "
            f"traceback={_flatten(traceback.format_exc())}"
        )
        print(f"error: {type(exc).__name__}: {exc}")
        return 1


def _run() -> int:
    s = Scheduler()
    # Skip when a prior audit is still queued / running.
    for status in NON_TERMINAL:
        for t in s.list_by_status(status):
            if t.op == AUDIT_OP:
                print(f"skip: {AUDIT_OP} already {t.status} ({t.id})")
                _log(f"outcome=skip op={AUDIT_OP} task={t.id} blocking_status={t.status}")
                return 0

    t = s.file_task(
        op=AUDIT_OP,
        owner_agent="6",
        priority=0,
        categories=[],
        payload={
            "scope": "full-phase3-repo-audit",
            "blocks_all_subsequent": True,
            "trigger": "periodic-cron",
            "filed_at": datetime.now(timezone.utc).isoformat(),
            "spawn_budget_usd": 3.00,        # a bit more headroom than $2
            "spawn_timeout_sec": 1200,       # 20 min
        },
        user_override=True,                  # cron-filed counts as implicit approval
    )
    print(f"filed: {t.id} priority={t.priority} status={t.status}")
    _log(f"outcome=filed op={AUDIT_OP} task={t.id} priority={t.priority} status={t.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
