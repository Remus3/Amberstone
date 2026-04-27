"""Manual smoke-test for Agent 0 evaluator (not a pytest — used in build validation).

pytest version lives in test_agent0.py.
"""
from __future__ import annotations

from agents.agent0_gatekeeper import Task, Evaluator


def main() -> int:
    e = Evaluator()

    cases: list[tuple[str, Task, bool]] = [
        (
            "accept-web-ui",
            Task(
                op="push-web-ui",
                originating_agent="5",
                remote_path=r"\\192.168.8.237\RCClient\web\index.html",
                payload_ext=".html",
                tag="ui-update",
            ),
            True,
        ),
        (
            "reject-unknown-op",
            Task(
                op="nuke-all",
                originating_agent="5",
                remote_path=r"\\192.168.8.237\RCClient\web\x.html",
                payload_ext=".html",
            ),
            False,
        ),
        (
            "reject-bad-destination",
            Task(
                op="push-web-ui",
                originating_agent="5",
                remote_path=r"\\192.168.8.237\RCClient\etc\x.html",
                payload_ext=".html",
            ),
            False,
        ),
        (
            "reject-authority",
            Task(
                op="push-web-ui",
                originating_agent="7",
                remote_path=r"\\192.168.8.237\RCClient\web\x.html",
                payload_ext=".html",
            ),
            False,
        ),
        (
            "reject-payload",
            Task(
                op="push-web-ui",
                originating_agent="5",
                remote_path=r"\\192.168.8.237\RCClient\web\x.exe",
                payload_ext=".exe",
            ),
            False,
        ),
        (
            "reject-target",
            Task(
                op="push-web-ui",
                originating_agent="5",
                remote_path=r"\\10.0.0.1\web\x.html",
                payload_ext=".html",
            ),
            False,
        ),
    ]

    ok = 0
    for label, task, expect in cases:
        d = e.evaluate(task)
        got = d.accepted
        tag = "OK" if got == expect else "FAIL"
        if got == expect:
            ok += 1
        if d.rejection:
            print(f"  {tag}  {label}: accepted={got} reason={d.rejection.reason_code} dispo={d.rejection.disposition}")
        else:
            print(f"  {tag}  {label}: accepted={got} passed={d.criteria_passed}")

    # Protected-window test with a probe returning IN_PROGRESS
    e2 = Evaluator(game_state_probe=lambda: "IN_PROGRESS")
    d = e2.evaluate(
        Task(
            op="trigger-forwarder-restart",
            originating_agent="2",
            remote_path=r"\\192.168.8.237\RCClient\forwarder\restart_trigger.txt",
            payload_ext=".txt",
            tag="restart-forwarder",
        )
    )
    tag = "OK" if not d.accepted and d.rejection.reason_code == 4 else "FAIL"
    print(f"  {tag}  protected-window: accepted={d.accepted} reason={d.rejection.reason_code} dispo={d.rejection.disposition}")
    if not d.accepted and d.rejection.reason_code == 4:
        ok += 1

    total = len(cases) + 1
    print(f"\n{ok}/{total} cases OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
