"""Manual smoke-test for Agent 1 scheduler."""
from __future__ import annotations

import pathlib
import tempfile

from agents.agent0_gatekeeper.evaluator import evaluate
from agents.agent1_lead import Scheduler, TaskStatus


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp()) / "q.jsonl"
    s = Scheduler(queue_log=tmp, agent0_evaluate=evaluate)

    ok = 0
    total = 0

    def check(label: str, got, want) -> None:
        nonlocal ok, total
        total += 1
        if got == want:
            ok += 1
            print(f"  OK   {label}: {got}")
        else:
            print(f"  FAIL {label}: got={got!r} want={want!r}")

    # Ungated
    t = s.file_task("audit-codebase", owner_agent="6", priority=10)
    check("ungated->ready", t.status, TaskStatus.READY)

    # Hard-gated
    t2 = s.file_task("archive-audit-dir", owner_agent="6", priority=50, categories=[8])
    check("hard->needs_approval", t2.status, TaskStatus.NEEDS_APPROVAL)

    # Cross-machine accepted
    t3 = s.file_task(
        "push-web-ui",
        owner_agent="5",
        priority=30,
        categories=[5],
        payload={"remote_path": r"\\192.168.8.237\RCClient\web\x.html", "payload_ext": ".html"},
    )
    check("xmachine->ready", t3.status, TaskStatus.READY)

    # Cross-machine rejected (bad dest)
    t4 = s.file_task(
        "push-web-ui",
        owner_agent="5",
        priority=30,
        categories=[5],
        payload={"remote_path": r"\\192.168.8.237\RCClient\etc\x.html", "payload_ext": ".html"},
    )
    check("xmachine->dead", t4.status, TaskStatus.DEAD_LETTER)

    # User override bypasses rejection
    t5 = s.file_task(
        "push-web-ui",
        owner_agent="5",
        priority=30,
        categories=[5],
        user_override=True,
        payload={"remote_path": r"\\192.168.8.237\RCClient\etc\x.html", "payload_ext": ".html"},
    )
    check("user_override->ready", t5.status, TaskStatus.READY)

    # Approve hard-gated
    s.approve(t2.id)
    check("approved->ready", s.get(t2.id).status, TaskStatus.READY)

    # Dispatch order (priority 10 first)
    n1 = s.next_ready()
    check("dispatch#1 op", n1.op if n1 else None, "audit-codebase")
    n2 = s.next_ready()
    check("dispatch#2 op", n2.op if n2 else None, "push-web-ui")  # t3 priority 30

    # Persistence - rebuild scheduler from same log, verify state restored
    s2 = Scheduler(queue_log=tmp, agent0_evaluate=evaluate)
    check("restore t1 status", s2.get(t.id).status, TaskStatus.IN_PROGRESS)
    check("restore t4 status", s2.get(t4.id).status, TaskStatus.DEAD_LETTER)

    print(f"\n{ok}/{total} cases OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
