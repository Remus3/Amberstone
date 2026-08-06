"""Internal: ephemeral `claude` subprocess dispatch for the Phase 3
supervisor (EphemeralStubNotWired / EphemeralSpawnFailed /
_format_task_prompt / spawn_ephemeral_llm).

Behavior-preserving split (s243) of agents/supervisor.py - see that
module's split note. The public surface is re-exported by
agents.supervisor; the facade keeps `import shutil` / `import subprocess`
so `patch("agents.supervisor.shutil"/.subprocess")` still reaches the
calls here (stdlib module singletons).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agents._supervisor_common import (
    AGENT_CHARTERS,
    AGENT_MODELS,
    CLAUDE_CLI,
    DEFAULT_SPAWN_BUDGET_USD,
    DEFAULT_SPAWN_TIMEOUT_SEC,
    LOG_ROOT,
    _PROJECT_ROOT,
    _iso_now,
    _redact_secrets,
    log,
)


class EphemeralStubNotWired(RuntimeError):
    """Retained for backwards-compat and for the explicit no-charter path.

    After the real subprocess spawn landed (2026-04-22), this is only
    raised when the ``claude`` CLI itself is missing from PATH - the
    dispatcher still translates it into ``Scheduler.fail()`` so tasks
    stay visible.
    """


class EphemeralSpawnFailed(RuntimeError):
    """Raised when claude subprocess exits non-zero or times out."""


TASK_LOG_MAX_AGE_DAYS = 7


def prune_task_logs(log_root: Path = LOG_ROOT,
                    max_age_days: float = TASK_LOG_MAX_AGE_DAYS) -> int:
    """Delete ``task-*.log`` files older than the age cap; return the count.

    Retention for the per-task spawn logs only (item 398): periodic-audit
    ephemeral spawns write ~235/day and the dir accreted 1848 files with no
    cap. Rollup ``agent<N>.log`` / supervisor logs are never touched. A file
    that cannot be deleted (held open by a live spawn) is skipped silently -
    the next prune gets it.

    Raises ValueError on a non-positive age cap (RM-161). The cutoff is
    ``now - max_age_days * 86400``, so at ``max_age_days <= 0`` it sits at or
    after now and every file the glob matches is older than it: the knob that
    bounds the corpus would erase it. The check runs BEFORE any filesystem
    work so a bad policy cannot be masked by the missing-directory early
    return. Same defect and same remedy as
    ``core/log_retention._validate_policy`` (LEDGER 1200).
    """
    if max_age_days <= 0:
        raise ValueError(
            f"max_age_days must be > 0, got {max_age_days!r} - a cutoff at or "
            "after now makes every task log older than it, so the retention "
            "cap would delete the whole corpus instead of bounding it"
        )
    if not log_root.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for p in log_root.glob("task-*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _write_agent6_failure_stub(
    task_id: str,
    op: str,
    payload: dict,
    exit_code: int,
    sidecar_log: Path,
    started_ts: str,
) -> None:
    """Write a minimal .md stub under agents/agent6_auditor/reports/ so that
    audit failures leave a visible artifact even when stderr is empty."""
    reports_dir = _PROJECT_ROOT / "agents" / "agent6_auditor" / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts_file = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        completed_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stub_path = reports_dir / f"{ts_file}-FAILED-{task_id}.md"
        tmp = stub_path.with_suffix(".tmp")
        lines = [
            f"# Agent 6 audit FAILED - {task_id}",
            "",
            f"- task_id: `{task_id}`",
            f"- op: `{op}`",
            f"- exit_code: {exit_code}",
            f"- dispatched_at: {payload.get('filed_at', 'unknown')}",
            f"- started_at: {started_ts}",
            f"- completed_at: {completed_ts}",
            f"- sidecar_log: `{sidecar_log}`",
            "",
            "No report artifact was written. Check the sidecar log for stdout/stderr.",
        ]
        tmp.write_text("\n".join(lines), encoding="utf-8")
        tmp.replace(stub_path)
    except OSError as e:
        log.warning("agent6 failure stub write failed: %s", e)


def _format_task_prompt(agent: str, task_id: str, op: str, payload: dict) -> str:
    """Build the user prompt the ephemeral claude session will see."""
    lines = [
        f"# Task dispatch - agent{agent}",
        "",
        f"- Task id: `{task_id}`",
        f"- Operation: `{op}`",
        f"- Dispatched by: Agent 1 (scheduler) on {_iso_now()}",
        "",
        "## Payload",
        "",
        "```json",
        json.dumps(payload, indent=2),
        "```",
        "",
        "## Instructions",
        "",
        "You are running as an ephemeral session under the Riot Commander",
        "Phase 3 framework. Your charter is in the system prompt above.",
        "Complete the task, then exit. Write any report artifacts the",
        "charter requires. Your final stdout message will be captured as",
        "the task result in `agents/state/task_queue.jsonl`.",
    ]
    return "\n".join(lines)


def spawn_ephemeral_llm(agent: str, task_id: str, op: str, payload: dict) -> dict:
    """Spawn a real ``claude`` subprocess for the given agent + task.

    Invocation:
        claude -p <prompt>
               --model <AGENT_MODELS[agent]>
               --dangerously-skip-permissions
               --append-system-prompt <charter-text>
               --no-session-persistence
               --output-format json
               --max-budget-usd <budget>

    stdout/stderr are streamed to ``logs/agents/agent<N>.log`` and
    captured. On exit code 0 we attempt to parse stdout as JSON; on any
    other exit code we raise ``EphemeralSpawnFailed`` which the dispatch
    loop translates into ``Scheduler.fail()``.

    Payload overrides:
      - ``spawn_budget_usd``: float dollar cap (default 2.0)
      - ``spawn_timeout_sec``: int seconds (default 900)
      - ``additional_dirs``: list[str] of extra --add-dir args
    """
    log_path = LOG_ROOT / f"agent{agent}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prune_task_logs()
    per_task_log = LOG_ROOT / f"task-{task_id}.log"

    model = AGENT_MODELS.get(agent)
    if model is None:
        raise EphemeralStubNotWired(f"no model mapping for agent{agent}")

    # Locate the claude CLI - fall back to EphemeralStubNotWired so the
    # dispatcher reports a clean failure rather than a shell error.
    claude_bin = shutil.which(CLAUDE_CLI)
    if claude_bin is None:
        raise EphemeralStubNotWired(
            f"`{CLAUDE_CLI}` not found on PATH - install Claude Code CLI "
            f"or ensure it's on the supervisor's PATH"
        )

    # Load charter. AUDIT P-audit3-m01 (2026-04-22): if the agent has a
    # declared charter path but the file is missing or unreadable, FAIL
    # LOUDLY instead of dispatching without - missing-charter spawns
    # silently widen authority and burn budget with no scope constraint.
    charter = ""
    charter_path = AGENT_CHARTERS.get(agent)
    if charter_path is not None:
        if not charter_path.exists():
            raise EphemeralStubNotWired(
                f"charter missing for agent{agent} at {charter_path}"
            )
        try:
            charter = charter_path.read_text(encoding="utf-8")
        except OSError as e:
            raise EphemeralStubNotWired(
                f"charter unreadable for agent{agent} at {charter_path}: {e}"
            ) from e
        if not charter.strip():
            raise EphemeralStubNotWired(
                f"charter empty for agent{agent} at {charter_path}"
            )

    user_prompt = _format_task_prompt(agent, task_id, op, payload)
    budget = float(payload.get("spawn_budget_usd", DEFAULT_SPAWN_BUDGET_USD))
    timeout = int(payload.get("spawn_timeout_sec", DEFAULT_SPAWN_TIMEOUT_SEC))

    # Argument construction: on Windows, `shutil.which("claude")` resolves
    # to `claude.CMD` (a batch wrapper around node). Batch scripts mangle
    # quoted multi-line prompts on the command line - newlines and
    # interleaved quotes silently get truncated. So we pipe the prompt
    # via stdin and let claude's default --input-format=text consume it.
    cmd: list[str] = [
        claude_bin,
        "--print",
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "json",
        "--max-budget-usd", f"{budget:.2f}",
    ]
    if charter:
        cmd.extend(["--append-system-prompt", charter])
    for extra_dir in payload.get("additional_dirs", []) or []:
        cmd.extend(["--add-dir", str(extra_dir)])

    stamp = _iso_now()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"{stamp} SPAWN agent={agent} task={task_id} op={op} "
            f"model={model} budget_usd={budget:.2f} timeout_sec={timeout} "
            f"charter_bytes={len(charter)} prompt_bytes={len(user_prompt)}\n"
        )

    # Spawn. CREATE_NO_WINDOW keeps pythonw.exe-hosted supervisor quiet.
    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=user_prompt,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{_iso_now()} TIMEOUT agent={agent} task={task_id} after={timeout}s\n")
        raise EphemeralSpawnFailed(
            f"claude subprocess timed out after {timeout}s for task {task_id}"
        ) from e

    elapsed = time.time() - t0

    # Mirror the full exchange into a per-task log file so the report can
    # be inspected without tail-chasing the rolling agent log.
    # AUDIT 2026-04-28 (P-audit4-m03): redact secret-shaped strings before
    # write. The supervisor injects ANTHROPIC_API_KEY into the spawn env;
    # an agent that introspects os.environ (or a traceback that exposes
    # KeyError on the var) would otherwise leak the key into a file on
    # disk readable by anyone with shell access.
    try:
        per_task_log.write_text(
            f"=== task {task_id} agent{agent} op={op} ===\n"
            f"cmd-length: {sum(len(a) for a in cmd)} chars\n"
            f"model: {model}\n"
            f"budget_usd: {budget:.2f}\n"
            f"timeout_sec: {timeout}\n"
            f"elapsed_sec: {elapsed:.1f}\n"
            f"exit_code: {proc.returncode}\n\n"
            f"--- stdout ---\n{_redact_secrets(proc.stdout)}\n\n"
            f"--- stderr ---\n{_redact_secrets(proc.stderr)}\n",
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("per-task log write failed: %s", e)

    if proc.returncode != 0:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"{_iso_now()} FAIL agent={agent} task={task_id} exit={proc.returncode} "
                f"stderr={_redact_secrets(proc.stderr[:200])!r}\n"
            )
        if agent == "6":
            _write_agent6_failure_stub(task_id, op, payload, proc.returncode, per_task_log, stamp)
        # The exception text becomes Scheduler.fail(error=str(e)) -> the
        # task's ``last_error`` -> the /api/task/<id> wire body. stderr can
        # carry an ANTHROPIC_API_KEY echo or a secret-shaped traceback
        # fragment (same threat the per-task log redaction guards), so
        # redact the embedded stderr here too - never leak it raw to the
        # dashboard (CLAUDE.md Error-Handling rule).
        raise EphemeralSpawnFailed(
            f"claude exit {proc.returncode} for task {task_id}: "
            f"{_redact_secrets(proc.stderr.strip()[:400])}"
        )

    # Parse the JSON envelope. Fall back to raw stdout if parse fails -
    # better to surface whatever the model returned than claim failure.
    result: Any
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"raw_stdout": proc.stdout.strip()}

    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"{_iso_now()} OK agent={agent} task={task_id} elapsed={elapsed:.1f}s "
            f"stdout_bytes={len(proc.stdout)}\n"
        )

    return {
        "ok": True,
        "substrate": "ephemeral_claude_cli",
        "model": model,
        "exit_code": 0,
        "elapsed_sec": round(elapsed, 2),
        "result": result,
        "task_log": str(per_task_log),
    }
