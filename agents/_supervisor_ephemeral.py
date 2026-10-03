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

# The kit passes its prompt on argv; the real task prompt rides stdin, which
# `claude -p "<this>"` reads as the context the instruction refers to.
EPHEMERAL_ARGV_PROMPT = "Complete the task given on stdin, following your charter."


# Env vars removed from the ephemeral spawn's environment (2026-09-29).
#
# MEASURED: ANTHROPIC_API_KEY is set MACHINE-WIDE on Legion. The
# RC-Phase3-Supervisor task runs `pythonw -m agents.supervisor` and inherits
# it; the spawn below used to call subprocess.run() with no env= argument, so
# on Windows the `claude` child inherited the parent's whole environment block
# and picked the key up too. That key is ORG-scoped, not workspace-scoped, and
# the CLI treats it as an auth source that TAKES PRECEDENCE over this box's
# Claude subscription login. Result: every Agent-6 dispatch from 2026-08-02
# onward died exit 1 (last success 2026-07-27, 7 consecutive weekly failures).
#
# Each entry is a variable the CLI honours as an auth/endpoint override, so
# leaving any of them in place would re-create the same precedence bug:
#   ANTHROPIC_API_KEY    - the measured culprit; org-scoped key.
#   ANTHROPIC_AUTH_TOKEN - the bearer-token equivalent of the same override.
#   ANTHROPIC_BASE_URL   - redirects the CLI at a gateway/proxy that expects
#                          its own credential, which the subscription login
#                          cannot satisfy.
# They are REMOVED, never set to "": an empty string still reads as "a key is
# configured" on some code paths, and subprocess on Windows rejects None.
#
# SCOPE: the spawn only. os.environ is never mutated and the machine-wide
# variable is never touched - RC's coaches legitimately use ANTHROPIC_API_KEY
# for direct Anthropic API calls and must keep seeing it.
#
# FLEET-KIT-v1 (MAIN order 2026-10-03): the strip now lives in the fleet kit
# (`fleet_headless.child_env`, which removes all three plus the
# CLAUDE_CODE_USE_* provider switches and sets the routed proxy URL). RC's own
# copy (`_SPAWN_ENV_STRIP` / `_build_spawn_env`) was deleted with the move;
# tests/test_supervisor_ephemeral_auth_env.py still pins the property on the
# env the child actually receives.


# Auth failure signatures, matched against the child's combined output.
#
# Without this a dead spawn yields a bare "claude exit 1" and the next person
# spends a session rediscovering the cause - which is exactly what happened
# over seven weekly failures. The needle is a fixed substring and the emitted
# cause is a CONSTANT string, so nothing derived from child output is ever
# interpolated into the message; the existing _redact_secrets calls on the
# real stdout/stderr are left exactly as they were.
_AUTH_FAILURE_SIGNATURES: tuple[tuple[str, str], ...] = (
    (
        "not scoped to a workspace",
        "the spawn presented an org-scoped API key where a workspace-scoped "
        "credential was required - an ANTHROPIC_* auth override reached the "
        "`claude` child instead of this host's subscription login",
    ),
    (
        "connectors are disabled because anthropic_api_key",
        "an ANTHROPIC_* auth source is overriding the Claude subscription "
        "login inside the spawned CLI - it must be stripped from the spawn "
        "environment",
    ),
    (
        "oauth session expired",
        "the Claude subscription OAuth session on this host is expired and "
        "could not be refreshed - the spawn environment is correct but there "
        "is no usable subscription credential; re-login with the `claude` CLI "
        "interactively on this machine",
    ),
)


def _classify_auth_failure(*streams: str) -> str | None:
    """Name the auth cause behind a failed spawn, or None if it is not one.

    Takes the child's raw stdout/stderr and returns one of the constant
    strings above. The child text itself is never returned or embedded.
    """
    haystack = " ".join(s for s in streams if isinstance(s, str)).lower()
    if not haystack:
        return None
    for needle, cause in _AUTH_FAILURE_SIGNATURES:
        if needle in haystack:
            return cause
    return None


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
        "You are running as an ephemeral session under the Amberstone",
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

    The child runs with an EXPLICIT environment (``_build_spawn_env``): the
    supervisor's own, minus the ANTHROPIC_* auth overrides, so the spawn
    rides this host's Claude subscription login rather than the machine-wide
    org-scoped API key. A failure carrying a known auth signature is named
    in the log and in the exception text (``_classify_auth_failure``).

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

    # Argument construction: the task prompt is multi-line and quote-heavy,
    # so it rides stdin, never the command line. FLEET-KIT-v1: the kit owns
    # `-p`, the model + effort pick, `--output-format json`,
    # `--no-session-persistence` and the lean MCP/settings flags; RC adds only
    # its own flags below. The kit picks opus when the work writes code and
    # sonnet otherwise, so the per-agent model maps to writes_code (an opus
    # agent is a code-writing agent) and the exact pin is no longer passed.
    extra: list[str] = [
        "--dangerously-skip-permissions",
        "--max-budget-usd", f"{budget:.2f}",
    ]
    if charter:
        extra.extend(["--append-system-prompt", charter])
    for extra_dir in payload.get("additional_dirs", []) or []:
        extra.extend(["--add-dir", str(extra_dir)])
    writes_code = "opus" in model.lower()

    stamp = _iso_now()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"{stamp} SPAWN agent={agent} task={task_id} op={op} "
            f"model={model} budget_usd={budget:.2f} timeout_sec={timeout} "
            f"charter_bytes={len(charter)} prompt_bytes={len(user_prompt)}\n"
        )

    # Spawn - FLEET-KIT-v1 (MAIN order 2026-10-03): ONLY through the fleet
    # kit, which owns the proxy route (fail closed via ops/loop/headless_env.py
    # - refused means no spawn, never a direct `claude`), the auth-override
    # strip, the run budget, the hidden console and the usage/status files.
    # bare=False: the agents commit, and the commit floors live in hooks.
    from ops.loop import fleet_route
    t0 = time.time()
    try:
        _line, proc = fleet_route.spawn(
            EPHEMERAL_ARGV_PROMPT,
            caller="supervisor_ephemeral",
            note=f"agent{agent}-{op}",
            writes_code=writes_code,
            bare=False,
            extra=extra,
            stdin=user_prompt,
            cwd=_PROJECT_ROOT,
            timeout=timeout,
        )
    except fleet_route.RouteRefused as e:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{_iso_now()} REFUSED agent={agent} task={task_id} reason={e.reason}\n")
        raise EphemeralSpawnFailed(
            f"headless route refused for task {task_id}: {e.reason}"
        ) from e
    except subprocess.TimeoutExpired as e:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{_iso_now()} TIMEOUT agent={agent} task={task_id} after={timeout}s\n")
        raise EphemeralSpawnFailed(
            f"claude subprocess timed out after {timeout}s for task {task_id}"
        ) from e

    elapsed = time.time() - t0
    if proc is None:
        raise EphemeralSpawnFailed(f"fleet kit started no process for task {task_id}")

    # Mirror the full exchange into a per-task log file so the report can
    # be inspected without tail-chasing the rolling agent log.
    # AUDIT 2026-04-28 (P-audit4-m03): redact secret-shaped strings before
    # write. An agent that introspects its environment (or a traceback that
    # exposes a key name) would otherwise leak a secret into a file on disk
    # readable by anyone with shell access.
    # 2026-09-29: ANTHROPIC_API_KEY no longer reaches the spawn env
    # (_SPAWN_ENV_STRIP), but this redaction is NOT thereby obsolete and must
    # not be weakened - the child can still surface a key by reading
    # API-Key-Claude.txt, a .env, or any other credential in the tree.
    # Name the auth cause (if any) from the RAW child output. Only the
    # constant cause string is kept; the child text is not carried over.
    auth_cause = None
    if proc.returncode != 0:
        auth_cause = _classify_auth_failure(proc.stdout, proc.stderr)
    auth_line = f"auth_cause: {auth_cause}\n" if auth_cause else ""

    try:
        per_task_log.write_text(
            f"=== task {task_id} agent{agent} op={op} ===\n"
            f"cmd-length: {sum(len(str(a)) for a in (proc.args or []))} chars\n"
            f"{auth_line}"
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
            if auth_cause:
                f.write(
                    f"{_iso_now()} AUTH-CAUSE agent={agent} task={task_id} "
                    f"{auth_cause}\n"
                )
        if auth_cause:
            log.error("ephemeral spawn auth failure (task %s): %s", task_id, auth_cause)
        if agent == "6":
            _write_agent6_failure_stub(task_id, op, payload, proc.returncode, per_task_log, stamp)
        # The exception text becomes Scheduler.fail(error=str(e)) -> the
        # task's ``last_error`` -> the /api/task/<id> wire body. stderr can
        # carry an ANTHROPIC_API_KEY echo or a secret-shaped traceback
        # fragment (same threat the per-task log redaction guards), so
        # redact the embedded stderr here too - never leak it raw to the
        # dashboard (CLAUDE.md Error-Handling rule).
        # The AUTH-CAUSE suffix is appended, not substituted, so the message
        # PREFIX shape ("claude exit N for task T: ...") is preserved for the
        # dispatcher and for the existing callers that assert on it.
        suffix = f" | AUTH-CAUSE: {auth_cause}" if auth_cause else ""
        raise EphemeralSpawnFailed(
            f"claude exit {proc.returncode} for task {task_id}: "
            f"{_redact_secrets(proc.stderr.strip()[:400])}{suffix}"
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
