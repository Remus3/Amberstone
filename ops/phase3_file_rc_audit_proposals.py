"""File proposals from the full-RC audit for frozen files.

Frozen per CLAUDE.md SHard rules:
  main.py, core/log_setup.py, core/moon_proxy.py, lcu/lcu_client.py,
  core/game_snapshot.py, core/rc_dev_runtime.py (actually at ops/rc_dev_runtime.py),
  ops/rc_supervisor.py, app/__init__.py, app/_health_monitor.py,
  app/_remediation.py, app/_state_authority.py, app/_overlay_manager.py,
  app/_game_lifecycle.py.

Idempotent - reruns skip already-queued proposals.
"""
from __future__ import annotations

from agents.agent1_lead import Scheduler, TaskStatus


PROPOSALS = [
    (
        "high", "P-rc-frozen-lcu-urlopen", "2",
        "lcu_client.py: urlopen without context manager",
        "lcu/lcu_client.py:71 opens a response via urlopen() without "
        "`with`; if json parsing raises mid-read, the socket is not "
        "guaranteed to close until GC runs. Wrap in `with` - two-line "
        "change. FROZEN file - needs explicit user approval before edit.",
    ),
    (
        "medium", "P-rc-frozen-moon_proxy-except-breadth", "2",
        "core/moon_proxy.py: too-broad Exception catch",
        "core/moon_proxy.py:64 catches `Exception` and returns None for "
        "both timeout and 401. Caller cannot distinguish transient vs "
        "permanent failures, so retry logic can't discriminate. Split "
        "into (TimeoutError, ConnectionError) -> retry-ok, (HTTPError) "
        "-> inspect .code. FROZEN file.",
    ),
    (
        "medium", "P-rc-frozen-app-init-swallow", "2",
        "app/__init__.py: init/shutdown exception swallowing",
        "app/__init__.py lines 115, 410, 421 catch Exception on coach/"
        "worker init/shutdown and proceed as if the subsystem is live. "
        "Symptoms: silent partial boot, zombie workers. Replace the "
        "pass-through with explicit log+disable-that-subsystem path. "
        "FROZEN file.",
    ),
    (
        "medium", "P-rc-frozen-overlay-mgr-swallow", "2",
        "app/_overlay_manager.py: cascading except-pass in visibility toggles",
        "app/_overlay_manager.py has 8 `except Exception: pass` blocks in "
        "visibility toggles (lines 66-67, 133-134, 137-138, 142-143, "
        "146-147, 218-219, 227-228). Silent overlay failures leave "
        "stale window state. With _HEADLESS=True these are all no-ops, "
        "but un-hiding when headless is flipped off would inherit the "
        "swallowing. FROZEN file.",
    ),
    (
        "low", "P-rc-frozen-claude-md-path-typo", "2",
        "CLAUDE.md lists frozen `core/rc_dev_runtime.py` but file is at ops/",
        "CLAUDE.md §Hard rules frozen list says `core/rc_dev_runtime.py` "
        "- the actual file lives at `ops/rc_dev_runtime.py`. Documentation "
        "inconsistency. Propose editing CLAUDE.md to match filesystem. "
        "Not a code change.",
    ),
]


def main() -> int:
    s = Scheduler()
    existing_ids = set()
    for status in (TaskStatus.READY, TaskStatus.IN_PROGRESS,
                   TaskStatus.NEEDS_APPROVAL, TaskStatus.AGENT0_REVIEW,
                   TaskStatus.RETRY_PENDING):
        for t in s.list_by_status(status):
            pid = t.payload.get("proposal_id")
            if pid:
                existing_ids.add(pid)

    filed = 0
    for severity, label, owner, title, fix in PROPOSALS:
        if label in existing_ids:
            print(f"  skip  {label}")
            continue
        priority = {"high": 15, "medium": 35, "low": 65}.get(severity, 50)
        t = s.file_task(
            op=f"apply-proposal-{label.lower()}",
            owner_agent=owner,
            priority=priority,
            categories=[],
            payload={
                "proposal_id": label,
                "severity": severity,
                "title": title,
                "fix_snippet": fix,
                "source_report": "full-rc-audit-20260422",
                "frozen_file_proposal": True,
                "filed_by": "agent6",
            },
        )
        filed += 1
        print(f"  filed {label} -> {t.id} priority={t.priority}")
    print(f"\n{filed} filed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
