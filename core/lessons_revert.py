"""Phase 4 (c) - auto-revert helper for applied lessons.

`apply_with_revert(lesson_id, commit_sha, *, tests, ...)` is the
operator-/Claude-called wrapper around `lessons_receiver.post_decision`.

Flow:
  1. Run the listed test subset (pytest) BEFORE finalizing 'applied'.
     If tests fail without a commit_sha, the lesson is recorded as
     'queued' instead - the bridge ack reflects the actual outcome.
  2. With a commit_sha, on test failure we `git revert <sha> --no-edit`
     in a NEW commit (no history rewrite, the project rule), then
     record the lesson as 'applied' with auto_reverted=True in the
     receiver_notes; the bridge ack carries auto_reverted=True so the
     origin Claude sees what happened.
  3. On test pass the lesson finalises as 'applied' (took=True via
     post_decision's existing logic).

This is intentionally NOT wired into a daemon - the receiver still
auto-handles only schema-reject + neg-match (per section 4); the apply path
remains a Claude-driven decision. Auto-revert is a safety net for that
decision, not a daemon-fired action.

Vision section 5 Phase 4 reference: docs io RC peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from core import lessons_receiver as _receiver
from core import bridge as _bridge

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TEST_TIMEOUT_S = 600.0
DEFAULT_TEST_TARGETS: tuple[str, ...] = ("tests/test_lessons_receiver_fetch.py",)

logger = logging.getLogger("rc.core.lessons_revert")


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

@dataclass
class RevertReport:
    lesson_id: str
    decision: str             # 'applied' | 'queued'
    auto_reverted: bool
    tests_ok: bool
    tests_returncode: int
    tests_tail: str
    revert_commit_sha: Optional[str] = None
    receiver_entry: dict = field(default_factory=dict)
    followup_ack_ok: bool = False
    followup_ack_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "lesson_id": self.lesson_id,
            "decision": self.decision,
            "auto_reverted": self.auto_reverted,
            "tests_ok": self.tests_ok,
            "tests_returncode": self.tests_returncode,
            "tests_tail": self.tests_tail,
            "revert_commit_sha": self.revert_commit_sha,
            "receiver_entry": self.receiver_entry,
            "followup_ack_ok": self.followup_ack_ok,
            "followup_ack_detail": self.followup_ack_detail,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tail(text: str, max_bytes: int = 1200) -> str:
    """Trim to the last `max_bytes` bytes, preserving line boundaries."""
    if not text:
        return ""
    data = text.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return text
    trimmed = data[-max_bytes:].decode("utf-8", errors="replace")
    nl = trimmed.find("\n")
    return trimmed[nl + 1:] if nl >= 0 else trimmed


def _run_tests(targets: Iterable[str],
               *, timeout_s: float,
               cwd: Path) -> tuple[int, str]:
    """Run `pytest <targets>` and return (returncode, captured_tail).

    Uses `sys.executable -m pytest` so it picks the same interpreter as
    the parent process - critical on Windows where the project's tests
    run under Python 3.14 but other Pythons may be on PATH.
    """
    cmd = [sys.executable, "-m", "pytest", "-q", *targets]
    logger.info("running tests: %s", " ".join(shlex.quote(c) for c in cmd))
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return (124, _tail(out + f"\n(timeout after {timeout_s}s)"))
    except (OSError, ValueError) as exc:
        return (127, f"pytest invocation failed: {exc}")
    return (proc.returncode, _tail((proc.stdout or "") + (proc.stderr or "")))


def _git_revert(commit_sha: str, *, cwd: Path) -> tuple[bool, str, Optional[str]]:
    """git revert <sha> --no-edit. Returns (ok, detail, new_sha)."""
    try:
        rev = subprocess.run(
            ["git", "revert", commit_sha, "--no-edit"],
            cwd=str(cwd), capture_output=True, text=True,
            timeout=60.0, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (False, f"git revert raised: {exc}", None)
    if rev.returncode != 0:
        return (False, _tail((rev.stdout or "") + (rev.stderr or "")), None)
    # New commit sha is the current HEAD after the revert.
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd), capture_output=True, text=True,
            timeout=10.0, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (True, f"reverted, HEAD lookup raised: {exc}", None)
    new_sha = (head.stdout or "").strip() or None
    return (True, "ok", new_sha)


def _followup_ack(lesson_id: str, *, decision: str, auto_reverted: bool,
                  tests_tail: str, revert_commit_sha: Optional[str],
                  peer: str) -> tuple[bool, str]:
    """Send a kind=result ack carrying the auto-revert outcome.

    Distinct from the ack post_decision sends - this fires only when
    auto-revert engaged, so the origin Claude can flip the lesson's
    'took' status in their own sent-ledger view via the ack-watcher.
    """
    body = {
        "decision": decision,
        "rationale": "auto-revert engaged" if auto_reverted else "post-apply tests ok",
        "took": (decision == "applied") and not auto_reverted,
        "auto_reverted": auto_reverted,
        "tests_tail": tests_tail,
    }
    if revert_commit_sha:
        body["revert_commit_sha"] = revert_commit_sha
    return _bridge.send(
        source="rc",
        summary=f"lesson {lesson_id} auto_reverted={auto_reverted}",
        kind="result",
        target=peer,
        body=body,
        in_reply_to=lesson_id,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def apply_with_revert(lesson_id: str,
                      commit_sha: Optional[str] = None,
                      *,
                      rationale: str = "",
                      receiver_notes: str = "",
                      tests: Iterable[str] = DEFAULT_TEST_TARGETS,
                      timeout_s: float = DEFAULT_TEST_TIMEOUT_S,
                      cwd: Optional[Path] = None,
                      peer: str = "peer") -> RevertReport:
    """Apply a lesson with a post-application test gate.

    `lesson_id`     - the inbound lesson the operator/Claude wants to apply.
    `commit_sha`    - optional. If the apply touched code, pass the
                      commit it landed in; on test failure we revert it
                      via a NEW commit.
    `tests`         - pytest targets to run. Default = the lesson stack
                      tests; callers SHOULD widen this when the lesson
                      touched code outside the lessons modules.
    `timeout_s`     - per-pytest-run wall clock.

    Outcomes (RevertReport.decision):
      - 'applied' + auto_reverted=False : tests pass, post_decision recorded.
      - 'applied' + auto_reverted=True  : tests failed, commit_sha reverted,
                                          post_decision still marks 'applied'
                                          but receiver_notes carries the
                                          auto-revert detail + the ack
                                          flips took=False.
      - 'queued'                         : tests failed, no commit_sha to
                                          revert; safest fallback is to
                                          queue the lesson for human review
                                          (no apply ack-took claim).
    """
    work_dir = cwd or ROOT
    rc, tail = _run_tests(list(tests), timeout_s=timeout_s, cwd=work_dir)
    tests_ok = (rc == 0)

    # Branch 1 - tests pass: normal apply via the receiver. post_decision
    # already sends a kind=result ack with took=True; we do not send a
    # second one (would just look like noise on the bridge).
    if tests_ok:
        try:
            entry = _receiver.post_decision(
                lesson_id, "applied",
                rationale or "post-apply tests passed",
                receiver_notes or "tests ok",
            )
        except (LookupError, ValueError) as exc:
            return RevertReport(
                lesson_id=lesson_id,
                decision="applied",
                auto_reverted=False,
                tests_ok=True,
                tests_returncode=rc,
                tests_tail=tail,
                receiver_entry={"error": str(exc)},
            )
        return RevertReport(
            lesson_id=lesson_id,
            decision="applied",
            auto_reverted=False,
            tests_ok=True,
            tests_returncode=rc,
            tests_tail=tail,
            receiver_entry=entry,
        )

    # Branch 2 - tests fail, no commit_sha: queue for review.
    if not commit_sha:
        try:
            entry = _receiver.post_decision(
                lesson_id, "queued",
                rationale or "tests failed; queued (no commit to revert)",
                receiver_notes or _tail(tail, 600),
            )
        except (LookupError, ValueError) as exc:
            entry = {"error": str(exc)}
        return RevertReport(
            lesson_id=lesson_id,
            decision="queued",
            auto_reverted=False,
            tests_ok=False,
            tests_returncode=rc,
            tests_tail=tail,
            receiver_entry=entry,
        )

    # Branch 3 - tests fail with commit_sha: revert + flag.
    rev_ok, rev_detail, new_sha = _git_revert(commit_sha, cwd=work_dir)
    rationale_full = rationale or "auto-revert engaged after test failure"
    notes = (receiver_notes + "\n\nauto-revert: " + rev_detail).strip()
    if rev_ok and new_sha:
        notes += f"\nrevert commit: {new_sha}"
    try:
        entry = _receiver.post_decision(
            lesson_id, "applied",
            rationale_full,
            notes,
        )
    except (LookupError, ValueError) as exc:
        entry = {"error": str(exc)}

    ack_ok, ack_detail = _followup_ack(
        lesson_id,
        decision="applied",
        auto_reverted=True,
        tests_tail=tail,
        revert_commit_sha=new_sha,
        peer=peer,
    )

    return RevertReport(
        lesson_id=lesson_id,
        decision="applied",
        auto_reverted=True,
        tests_ok=False,
        tests_returncode=rc,
        tests_tail=tail,
        revert_commit_sha=new_sha,
        receiver_entry=entry,
        followup_ack_ok=ack_ok,
        followup_ack_detail=ack_detail,
    )


# ---------------------------------------------------------------------------
# CLI - keeps the apply-with-revert flow scriptable from /loop
# ---------------------------------------------------------------------------

def _cli(argv: list[str]) -> int:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="lessons_revert")
    p.add_argument("lesson_id")
    p.add_argument("--commit-sha", default=None)
    p.add_argument("--rationale", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--tests", action="append", default=None,
                   help="pytest target; repeat for multiple")
    p.add_argument("--timeout-s", type=float, default=DEFAULT_TEST_TIMEOUT_S)
    p.add_argument("--peer", default="peer")
    args = p.parse_args(argv)
    targets = tuple(args.tests) if args.tests else DEFAULT_TEST_TARGETS
    report = apply_with_revert(
        args.lesson_id,
        commit_sha=args.commit_sha,
        rationale=args.rationale,
        receiver_notes=args.notes,
        tests=targets,
        timeout_s=args.timeout_s,
        peer=args.peer,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    # exit 0 on applied+!auto_reverted; non-zero otherwise so callers can
    # branch in shell (the lesson stack already has rich JSON, the exit
    # code is a coarse health signal only).
    if report.decision == "applied" and not report.auto_reverted:
        return 0
    if report.decision == "applied" and report.auto_reverted:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))


# Re-export the touched-by-tests symbol path so test patches can reach
# _bridge.send without going through `core.bridge` directly when the
# module is reloaded under fixtures.
_BRIDGE_MODULE = _bridge
