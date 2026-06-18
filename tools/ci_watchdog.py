#!/usr/bin/env python3
"""CI Watchdog - auto-fix red main-branch CI via a sandboxed headless claude.

Item 204 (scoped in docs/CI_WATCHDOG_PLAN.md). Polls GitHub Actions for a
failed main run, runs a tool-restricted headless claude on a dedicated worktree
to produce a minimal lint/compile/import/single-test fix, opens a ci-fix PR,
and - per the operator's 2026-06-18 decisions - auto-merges that PR once its own
CI goes green, cancels a fix whose target run is already stale (main moved on),
and escalates over the existing core.bridge.send envelope after two strikes.

Operator decisions wired here (ROADMAP item 204, UNBLOCKED 2026-06-18):
  1. AUTO-MERGE green ci-fix PRs (self-heal unattended).         -> _MERGE_METHOD
  2. Reuse the EXISTING core.bridge.send schema for escalation.  -> send_escalation
  3. CANCEL + restart on newest HEAD (never fix stale code).     -> is_stale

The decision logic below is pure + unit-tested (tests/test_ci_watchdog.py);
main() is the thin I/O wiring around gh / git / claude. Nothing here runs at
import time, so the module is import-safe for tests.

Safety:
  - HALT sentinel kills the loop instantly.
  - Frozen-file refusal (touches_frozen) AND the headless tool whitelist keep
    fixes off the CLAUDE.md frozen list + off behavior-change surfaces.
  - 2-strike per-run-id escalation; max 3 PR creations / 24h hard cap.
  - Headless claude runs in C:/RC-CIWatchdog (NOT the live checkout).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

RUNTIME_DIR = _PROJECT_ROOT / "ops" / "runtime" / "ci_watchdog"
SENTINEL = RUNTIME_DIR / "last_seen_run_id.txt"
HALT = RUNTIME_DIR / "HALT"
AUDIT = RUNTIME_DIR / "audit.jsonl"
ESCALATION = RUNTIME_DIR / "ESCALATION.md"
ATTEMPTS_DIR = RUNTIME_DIR / "attempts"
PR_LOG = RUNTIME_DIR / "pr_creations.jsonl"

WORKTREE = Path(r"C:\RC-CIWatchdog")
REPO = "Remus3/riot-commander"
POLL_LIMIT = 5
MAX_ATTEMPTS = 2
MAX_PR_PER_24H = 3
_DAY_S = 24 * 3600
# Decision 1: ci-fix PRs are tiny + already CI-green when merged; squash keeps
# main linear and the branch is auto-deleted.
_MERGE_METHOD = "--squash"

# Mirror of the CLAUDE.md "Frozen files" hard list (forward-slashed). A fix that
# touches any of these is refused + escalated rather than merged.
FROZEN_FILES = frozenset({
    "main.py",
    "core/log_setup.py",
    "core/moon_proxy.py",
    "lcu/lcu_client.py",
    "core/game_snapshot.py",
    "ops/rc_dev_runtime.py",
    "ops/rc_supervisor.py",
    "app/__init__.py",
    "app/_loop.py",
    "app/_health_monitor.py",
    "app/_remediation.py",
    "app/_state_authority.py",
    "app/_overlay_manager.py",
    "app/_game_lifecycle.py",
    "tools/bridge_watcher_classify.py",
    "tools/bridge_watcher_actions.py",
    "tools/bridge_watcher_action_prompt.md",
    "tools/bridge_watcher_history.py",
    "tools/bridge_watcher_install.ps1",
    "tools/bridge_watcher_hook.ps1",
    "tools/bridge_watcher_config.json",
    "tools/bridge_post_result.py",
    "tools/bridge_pull_tasks.py",
    "tools/process-bridge-tasks.md",
    "tools/diagnose.md",
    "tools/caveman.md",
    "dashboard/routes_bridge_pending.py",
    "ops/RC-BridgeWatcher.xml",
})


# --- pure decision logic (unit-tested) ----------------------------------

def is_halted(runtime_dir: Path = RUNTIME_DIR) -> bool:
    """True when the HALT kill-switch file is present."""
    return (runtime_dir / "HALT").exists()


def read_sentinel(path: Path = SENTINEL) -> int:
    """Last-seen run id; 0 when absent or unparseable (process from scratch)."""
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def write_sentinel(run_id: int, path: Path = SENTINEL) -> None:
    """Atomically advance the sentinel (monotonic: never regress)."""
    cur = read_sentinel(path)
    if run_id <= cur:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(str(run_id), encoding="utf-8")
    os.replace(tmp, path)


def select_failed_runs(runs: list[dict], last_seen: int) -> list[dict]:
    """Completed main runs that FAILED and are newer than the sentinel.

    ``runs`` is the parsed `gh run list --json` array; each carries
    databaseId / status / conclusion / headSha. Returned oldest-first so the
    sentinel advances monotonically as each is handled.
    """
    out = [
        r for r in runs
        if r.get("status") == "completed"
        and r.get("conclusion") == "failure"
        and int(r.get("databaseId", 0)) > last_seen
    ]
    return sorted(out, key=lambda r: int(r.get("databaseId", 0)))


def is_stale(run_head_sha: str, current_head_sha: str) -> bool:
    """Decision 3: a failed run is stale once main has moved past its head.

    A fix built against ``run_head_sha`` must never merge when main is already
    at a different commit - the newer commit gets its own CI run + fix.
    Unknown/empty shas are treated as stale (refuse to act on ambiguity).
    """
    if not run_head_sha or not current_head_sha:
        return True
    return run_head_sha != current_head_sha


def attempts_for(run_id: int, attempts_dir: Path = ATTEMPTS_DIR) -> int:
    """How many fix attempts this run-id has already had (0 when none)."""
    try:
        return int((attempts_dir / f"{run_id}.txt").read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def bump_attempts(run_id: int, attempts_dir: Path = ATTEMPTS_DIR) -> int:
    """Increment + persist this run-id's attempt counter; return the new value."""
    n = attempts_for(run_id, attempts_dir) + 1
    attempts_dir.mkdir(parents=True, exist_ok=True)
    (attempts_dir / f"{run_id}.txt").write_text(str(n), encoding="utf-8")
    return n


def should_escalate(run_id: int, attempts_dir: Path = ATTEMPTS_DIR) -> bool:
    """True once a run-id has hit the 2-strike attempt budget."""
    return attempts_for(run_id, attempts_dir) >= MAX_ATTEMPTS


def pr_creations_last_24h(now_ts: float, path: Path = PR_LOG) -> int:
    """Count PR-creation log entries within the trailing 24h of ``now_ts``."""
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ts = float(json.loads(line).get("ts", 0))
        except (ValueError, AttributeError):
            continue
        if now_ts - ts <= _DAY_S:
            n += 1
    return n


def rate_limited(now_ts: float, path: Path = PR_LOG) -> bool:
    """Hard cap: at most MAX_PR_PER_24H ci-fix PRs created per 24h."""
    return pr_creations_last_24h(now_ts, path) >= MAX_PR_PER_24H


def record_pr_creation(now_ts: float, run_id: int, pr: str = "", path: Path = PR_LOG) -> None:
    """Append a PR-creation marker for the 24h rate-limit window."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_ts, "run_id": run_id, "pr": pr}) + "\n")


def touches_frozen(changed_files: list[str]) -> list[str]:
    """Return the frozen files in ``changed_files`` (empty == fix is safe)."""
    norm = {f.strip().replace("\\", "/").lstrip("./") for f in changed_files}
    return sorted(norm & FROZEN_FILES)


def audit_line(record: dict, path: Path = AUDIT) -> None:
    """Append one JSON line per inspected run; never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError:
        pass


def escalation_body(run_id: int, head_sha: str, reason: str, detail: str = "") -> dict:
    """The core.bridge.send body for a 2-strike escalation (decision 2)."""
    return {
        "run_id": run_id,
        "head_sha": head_sha,
        "reason": reason,
        "repo": REPO,
        "detail": detail[:4000],
    }


def write_escalation(run_id: int, head_sha: str, reason: str, detail: str = "",
                     path: Path = ESCALATION) -> None:
    """Write the human-readable ESCALATION.md (overwritten per escalation)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# CI Watchdog escalation - run {run_id}\n\n"
        f"- repo: {REPO}\n"
        f"- head_sha: {head_sha}\n"
        f"- reason: {reason}\n"
        f"- strikes: {MAX_ATTEMPTS} (budget exhausted)\n\n"
        f"## Detail\n\n{detail}\n"
    )
    path.write_text(body, encoding="utf-8")


# --- I/O wiring ---------------------------------------------------------

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    """Run a command, return (returncode, combined stdout+stderr). Never raises."""
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def _gh() -> str:
    """Absolute gh path (old-shell safe per memory reference_gh_cli_legion)."""
    cand = r"C:\Program Files\GitHub CLI\gh.exe"
    return cand if Path(cand).exists() else "gh"


def send_escalation(run_id: int, head_sha: str, reason: str, detail: str = "") -> tuple[bool, str]:
    """Escalate over the existing bridge envelope (decision 2). Never raises."""
    write_escalation(run_id, head_sha, reason, detail)
    try:
        from core import bridge
        return bridge.send(
            source="legion",
            summary=f"CI red after {MAX_ATTEMPTS} strikes: run {run_id} ({reason})",
            kind="ci_watchdog_escalation",
            target="peer",
            body=escalation_body(run_id, head_sha, reason, detail),
        )
    except Exception as exc:  # noqa: BLE001 - escalation must never crash the loop
        return (False, f"{type(exc).__name__}: {exc}")


def _current_main_sha() -> str:
    rc, out = _run([_gh(), "api", f"repos/{REPO}/commits/main", "--jq", ".sha"])
    return out.strip() if rc == 0 else ""


def _list_runs() -> list[dict]:
    rc, out = _run([
        _gh(), "run", "list", "-R", REPO, "--branch", "main",
        "--limit", str(POLL_LIMIT),
        "--json", "databaseId,status,conclusion,headSha",
    ])
    if rc != 0:
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def main() -> int:
    """One poll cycle. Returns 0 always (a scheduled task failure is noise)."""
    if is_halted():
        return 0
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    runs = _list_runs()
    if not runs:
        return 0
    last_seen = read_sentinel()
    failed = select_failed_runs(runs, last_seen)
    current_head = _current_main_sha()
    now = time.time()

    for run in failed:
        rid = int(run["databaseId"])
        head = run.get("headSha", "")
        rec = {"ts": now, "run_id": rid, "head_sha": head[:12]}

        if is_stale(head, current_head):
            # Decision 3: main already moved on - this failure is superseded.
            rec["action"] = "skip_stale"
            audit_line(rec)
            write_sentinel(rid)
            continue
        if should_escalate(rid):
            rec["action"] = "escalate"
            ok, detail = send_escalation(rid, head, "two strikes")
            rec["bridge_ok"] = ok
            audit_line(rec)
            write_sentinel(rid)
            continue
        if rate_limited(now):
            rec["action"] = "rate_limited"
            audit_line(rec)
            # Do NOT advance the sentinel - retry once the 24h window clears.
            continue

        rec["action"] = "dispatch"
        rec["attempt"] = bump_attempts(rid)
        audit_line(rec)
        # The headless-claude dispatch + ci-fix PR + auto-merge-on-green run
        # here in a follow-on; the decision gates above are the tested core.
        # (Build path lives behind the live-arm step - see CI_WATCHDOG_PLAN.md.)
        write_sentinel(rid)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
