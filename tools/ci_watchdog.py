#!/usr/bin/env python3
"""CI Watchdog - auto-fix red main-branch CI via a sandboxed headless claude.

Item 204 (scoped in docs/CI_WATCHDOG_PLAN.md). Polls GitHub Actions for a
failed main run, runs a tool-restricted headless claude on a dedicated worktree
to produce a minimal lint/compile/import/single-test fix, opens a ci-fix PR so
the fix gets its own CI, and - once that CI is green - LANDS the fix locally as
one operator commit on main (never a GitHub-side PR merge), cancels a fix whose
target run is already stale (main moved on), and escalates to a local-only
ESCALATION.md after two strikes.

Operator decisions wired here (ROADMAP item 204, UNBLOCKED 2026-06-18):
  1. Self-heal green ci-fix PRs unattended.                       -> _land
  2. Escalate to local-only ESCALATION.md after two strikes.     -> send_escalation
  3. CANCEL + restart on newest HEAD (never fix stale code).     -> is_stale

Decision 1 as amended by MAIN's kit-v13 ORDER section 4 and kit-v14 ORDER
section 4 (operator authority, 2026-10-08 / 2026-10-09): no PR is merged on
GitHub in any mode, because the web-merge committer (and a squash that keeps
the fixer as author) is a non-operator identity on main. The green fix is
squashed LOCALLY into ONE commit whose message the watchdog writes (the
fixer's message and any trailer in it never reach main), committed through
ops/fleet_kit/fleet_gitlock.py (lock + AI/bot identity refusal), checked with
fleet_identity on exactly the range being pushed, pushed as a plain
fast-forward of HEAD to main, and the PR is then closed. Any refusal leaves the
PR open and escalates, so the operator lands it by hand.

The decision logic below is pure + unit-tested (tests/test_ci_watchdog.py);
main() is the thin I/O wiring around gh / git / claude. Nothing here runs at
import time, so the module is import-safe for tests.

Safety:
  - HALT sentinel kills the loop instantly.
  - Frozen-file refusal (touches_frozen) AND the headless tool whitelist keep
    fixes off the CLAUDE.md frozen list + off behavior-change surfaces.
  - 2-strike per-run-id escalation; max 3 PR creations / 24h hard cap.
  - Headless claude runs in the dedicated worktree `resolve_worktree()`
    names (env RC_CI_WATCHDOG_WORKTREE, else RC-CIWatchdog beside the
    checkout) - NOT the live checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# FLEET-KIT v12 RACE GUARDS (FLEET-COMMON item 16 a; MAIN 2026-10-08 2031 ORDER
# step 5): the watchdog's own push runs inside the tree's git lock. The kit file
# is loaded lazily by path, so importing this module stays side-effect free.
# The headless fixer child still commits with a plain `git commit` inside the
# dedicated watchdog worktree: its tool allowlist is the execution gate and it
# carries no project hooks there; routing that commit is the follow-up RM-692.
_GITLOCK_OWNER = "ci-watchdog"
_KIT_DIR = _PROJECT_ROOT / "ops" / "fleet_kit"


def _kit_module(stem):
    """A vendored fleet-kit module, loaded lazily by path under the same
    `fleet_kit_<stem>` key the kit's own sibling loader uses (one instance)."""
    import importlib.util

    key = "fleet_kit_" + stem
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, _KIT_DIR / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def _git_lock(where, owner, verb):
    """The kit's fleet_gitlock.git_lock(where, owner, verb) context manager."""
    return _kit_module("fleet_gitlock").git_lock(where, owner, verb)

RUNTIME_DIR = _PROJECT_ROOT / "ops" / "runtime" / "ci_watchdog"
SENTINEL = RUNTIME_DIR / "last_seen_run_id.txt"
HALT = RUNTIME_DIR / "HALT"
AUDIT = RUNTIME_DIR / "audit.jsonl"
ESCALATION = RUNTIME_DIR / "ESCALATION.md"
ATTEMPTS_DIR = RUNTIME_DIR / "attempts"
PR_LOG = RUNTIME_DIR / "pr_creations.jsonl"

WORKTREE_ENV = "RC_CI_WATCHDOG_WORKTREE"
_WORKTREE_DIRNAME = "RC-CIWatchdog"


def resolve_worktree(env=None, repo_root=None) -> Path:
    """The dedicated watchdog worktree (MAIN 2246 ORDER section 3: no machine
    path literal in a tracked file). Env RC_CI_WATCHDOG_WORKTREE, when not
    blank, wins; otherwise the `RC-CIWatchdog` folder beside the checkout."""
    env = os.environ if env is None else env
    override = (env.get(WORKTREE_ENV) or "").strip()
    if override:
        return Path(override)
    root = Path(repo_root) if repo_root is not None else _PROJECT_ROOT
    return root.parent / _WORKTREE_DIRNAME


WORKTREE = resolve_worktree()
REPO = "Remus3/Amberstone"
POLL_LIMIT = 5
MAX_ATTEMPTS = 2
MAX_PR_PER_24H = 3
_DAY_S = 24 * 3600

# Per-step subprocess timeouts (seconds). The two blocking steps need far more
# than the 120s default: a headless claude fix runs for minutes, and wait_checks
# BLOCKS on the ci-fix PR's full CI run (the self-gate). Task Scheduler bounds the
# whole cycle via ExecutionTimeLimit + MultipleInstancesPolicy=IgnoreNew, so a
# blocking poll here can never stack overlapping armed instances.
_STEP_TIMEOUTS = {"claude_fix": 600, "wait_checks": 900}

# Headless-claude fixer system prompt + the tool whitelist. In `claude -p` mode
# any tool NOT on --allowedTools is denied silently (no prompt, no hang), so this
# whitelist - not a flag - is the hard execution gate. Write is disallowed (fixes
# are Edits to existing files) and git push is reserved for the watchdog itself.
CI_FIX_PROMPT = _PROJECT_ROOT / "tools" / "ci_watchdog_fix.md"
_CLAUDE_ALLOWED_TOOLS = (
    "Edit", "Read",
    "Bash(ruff:*)", "Bash(git:*)",
    "Bash(python -m py_compile:*)", "Bash(pytest:*)",
)
_CLAUDE_DISALLOWED_TOOLS = ("Write", "Bash(git push:*)")
# Context the executor writes into the worktree for claude to Read.
_CONTEXT_FILE = ".ci_watchdog_context.md"

# Mirror of the CLAUDE.md "Frozen files" hard list (forward-slashed). A fix that
# touches any of these is refused + escalated rather than landed.
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
    "tools/diagnose.md",
    "tools/caveman.md",
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


def branch_name(run_id: int) -> str:
    """The per-run ci-fix branch the headless fix is committed onto."""
    return f"ci-fix/{run_id}"


def land_branch_name(run_id: int) -> str:
    """The throwaway LOCAL branch (off fresh origin/main) the fix is squashed onto."""
    return f"ci-land/{run_id}"


def land_message(run_id: int, head_sha: str) -> tuple[str, str]:
    """(subject, body) of the ONE operator commit that lands a green fix.

    Written by the watchdog, never taken from the fixer: whatever the headless
    fixer put in its own commit message (an attribution trailer included) is
    dropped by the squash and never reaches main."""
    subject = f"ci(fix): auto-fix red CI run {run_id}"
    body = (
        f"Landed locally by the CI Watchdog (item 204) after the {branch_name(run_id)} "
        f"PR's own checks passed on base {head_sha[:12]}. One squash commit through "
        "fleet_gitlock as the operator; the PR is closed, not merged on GitHub."
    )
    return subject, body


def plan_dispatch(run_id: int, head_sha: str, *, worktree: Path = WORKTREE,
                  repo: str = REPO) -> list[tuple[str, list[str]]]:
    """The ordered (label, argv) command plan for one fix dispatch.

    Pure + deterministic: the dry run surfaces exactly this list and
    ``execute_dispatch`` runs it step by step. Every git command is scoped to the
    throwaway ``worktree`` (-C) and every gh command to ``repo``; ``claude`` runs
    headless (-p) tool-restricted with NO permission bypass and CANNOT push (the
    watchdog owns push/PR/landing). ``gh`` and ``python`` are kept literal here
    for a readable, portable plan - the executor maps ``gh`` to the absolute
    binary and runs the ``land_verify`` identity check in-process.
    """
    wt = str(worktree)
    branch = branch_name(run_id)
    subject, land_body = land_message(run_id, head_sha)
    instr = (
        f"Read {_CONTEXT_FILE} - it holds the failing CI step log tail and the "
        "offending commit diff. Make the minimal in-bounds fix per your system "
        "prompt, verify locally, and commit on this branch. Do NOT push or open a "
        "PR. If the failure is out of bounds, make no edits and reply with a "
        "single line starting 'ESCALATE:'."
    )
    claude = [
        "claude", "-p", instr,
        "--append-system-prompt-file", str(CI_FIX_PROMPT),
        "--allowedTools", *_CLAUDE_ALLOWED_TOOLS,
        "--disallowedTools", *_CLAUDE_DISALLOWED_TOOLS,
        "--output-format", "json",
    ]
    body = (
        f"Automated CI fix for failed run {run_id} (head {head_sha[:12]}).\n\n"
        "Scope: lint / py_compile / import / single-test only; frozen files "
        "refused. On green the CI Watchdog (item 204) lands this fix locally as "
        "one operator commit on main and closes this PR - it is never merged on "
        "GitHub."
    )
    close_note = ("Landed locally on main as one operator commit by the CI Watchdog; "
                  "closed without a GitHub merge (kit v13/v14 ORDER section 4).")
    return [
        ("fetch", ["git", "-C", wt, "fetch", "origin", "--prune"]),
        ("reset", ["git", "-C", wt, "reset", "--hard", "origin/main"]),
        ("branch", ["git", "-C", wt, "checkout", "-B", branch, "origin/main"]),
        ("gather_log", ["gh", "run", "view", str(run_id), "--repo", repo,
                        "--log-failed"]),
        ("gather_diff", ["git", "-C", wt, "show", head_sha]),
        ("claude_fix", claude),
        ("diff_names", ["git", "-C", wt, "diff", "--name-only", "origin/main"]),
        ("push", ["git", "-C", wt, "push", "-u", "origin", branch]),
        ("pr_create", ["gh", "pr", "create", "--repo", repo, "--base", "main",
                       "--head", branch,
                       "--title", f"ci(fix): auto-fix red CI run {run_id}",
                       "--body", body]),
        # Self-gate: BLOCK on the ci-fix PR's own checks (--watch) and bail on the
        # first red (--fail-fast). Exit 0 = every check green -> land; non-zero ->
        # escalate. This in-watchdog gate is why no branch protection is needed
        # (so direct-push-to-main keeps working).
        ("wait_checks", ["gh", "pr", "checks", branch, "--repo", repo,
                         "--watch", "--fail-fast"]),
        # LAND LOCALLY (kit v13/v14 ORDER section 4): re-read origin/main, refuse
        # when it moved off the tested base, squash the fix onto a throwaway
        # local branch as ONE watchdog-worded commit through fleet_gitlock (the
        # kit refuses a Claude / bot author or committer), verify the pushed
        # range with fleet_identity, fast-forward main (never forced), close PR.
        ("land_fetch", ["git", "-C", wt, "fetch", "origin", "--prune"]),
        ("land_head", ["git", "-C", wt, "rev-parse", "origin/main"]),
        ("land_branch", ["git", "-C", wt, "checkout", "-B",
                         land_branch_name(run_id), "origin/main"]),
        ("land_squash", ["git", "-C", wt, "merge", "--squash", branch]),
        ("land_commit", ["git", "-C", wt, "commit", "-m", subject, "-m", land_body]),
        ("land_verify", ["python", str(_KIT_DIR / "fleet_identity.py"), "check",
                         "origin/main..HEAD"]),
        ("land_push", ["git", "-C", wt, "push", "origin", "HEAD:main"]),
        ("pr_close", ["gh", "pr", "close", branch, "--repo", repo, "--delete-branch",
                      "--comment", close_note]),
    ]


def audit_line(record: dict, path: Path = AUDIT) -> None:
    """Append one JSON line per inspected run; never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError:
        pass


def escalation_body(run_id: int, head_sha: str, reason: str, detail: str = "") -> dict:
    """The on-disk record shape for a 2-strike escalation (decision 2).

    Retained as the structured escalation payload; the cross-Claude bridge was
    decommissioned 2026-06-24 so escalation is now local-only (ESCALATION.md)."""
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

ROUTE_REFUSED_MARK = "HEADLESS_ROUTE_REFUSED:"


def _fleet_route():
    """`ops/loop/fleet_route.py`. Imported lazily so this module stays import-safe."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from ops.loop import fleet_route
    return fleet_route


def _claude_fix_via_kit(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """The `claude_fix` step, started ONLY through the fleet kit (FLEET-KIT-v1).

    The plan's argv stays the readable contract the dry run prints; here its
    task text and its RC-specific flags are handed to the kit, which owns the
    proxy route, budget, model, lean flags, child env and hidden console. The
    kit sets `--output-format json` itself, so that pair is dropped from the
    extras. writes_code=True: the fix commits on its branch. bare=False: the
    commit floors live in hooks (precommit_gate PreToolUse, .githooks).
    Returns (rc, stdout+stderr) like `_run`; a refusal returns the route mark
    and starts nothing.
    """
    fr = _fleet_route()
    prompt = argv[2]
    extra = list(argv[3:])
    if "--output-format" in extra:
        i = extra.index("--output-format")
        del extra[i:i + 2]
    try:
        _line, proc = fr.spawn(prompt, caller="ci_watchdog", note="ci-fix",
                               writes_code=True, bare=False, extra=extra,
                               cwd=cwd, timeout=timeout)
    except fr.RouteRefused as exc:
        return 1, f"{ROUTE_REFUSED_MARK} {exc}"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    if proc is None:
        return 1, "fleet kit returned no process"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120,
         env: dict | None = None) -> tuple[int, str]:
    """Run a command, return (returncode, combined stdout+stderr). Never raises."""
    # CREATE_NO_WINDOW: this runs under a pythonw.exe-hosted scheduled task every
    # 2 min; without it each git/gh child allocates a console that flashes onscreen.
    no_window = 0x08000000 if os.name == "nt" else 0
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout, creationflags=no_window, env=env,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def _gh() -> str:
    """Absolute gh path (old-shell safe per memory reference_gh_cli_legion)."""
    cand = r"C:\Program Files\GitHub CLI\gh.exe"
    return cand if Path(cand).exists() else "gh"


def _gitlock_commit(argv: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    """`fleet_gitlock.py run --owner ci-watchdog -- <git commit argv>`, in-process.

    The kit takes the tree's git lock, clears a dead index.lock, refuses a path
    claimed by another live agent, and refuses a Claude / bot author or
    committer (FLEET-COMMON 16/17) before git runs. A refusal is a failed step
    (rc 3), never a bypass."""
    try:
        kit = _kit_module("fleet_gitlock")
        return kit.run(["--owner", _GITLOCK_OWNER, "--", *argv], cwd=cwd,
                       runner=lambda c: _run(list(c), cwd=Path(cwd), timeout=timeout))
    except RuntimeError as exc:  # the kit's LockRefused is a RuntimeError
        return 3, str(exc)
    except (OSError, subprocess.SubprocessError, ImportError) as exc:
        return 3, f"{type(exc).__name__}: {exc}"


def _identity_check(cwd: Path, rev_range: str) -> tuple[int, str]:
    """fleet_identity's `check <rev_range>`, in-process (no console child under
    pythonw). Fails closed: no `fleet.operatorIdent` in the worktree's local
    config, an unlistable range, or anything but exactly ONE commit is a refusal.
    Reports finding CLASSES only, never a name or address."""
    try:
        ident = _kit_module("fleet_identity")
        idents = ident.operator_idents(str(cwd))
        if not idents:
            return 1, f"IDENTITY: no {ident.CONFIG_KEY} in the worktree's local git config"
        rows = ident.commits(str(cwd), [rev_range])
        if rows is None:
            return 1, f"IDENTITY: could not list {rev_range}"
        if len(rows) != 1:
            return 1, f"IDENTITY: {rev_range} holds {len(rows)} commit(s), expected exactly 1"
        found = ident.violations(rows, idents)
        if found:
            return 1, "IDENTITY: " + ", ".join(sorted({cls for _sha, cls in found}))
        return 0, "IDENTITY: 1 commit(s) clean"
    except Exception as exc:  # noqa: BLE001 - fail closed, never crash the loop
        return 1, f"IDENTITY: {type(exc).__name__}: {exc}"


def send_escalation(run_id: int, head_sha: str, reason: str, detail: str = "") -> tuple[bool, str]:
    """Record a 2-strike escalation to the local ESCALATION.md. Never raises.

    The cross-Claude bridge was decommissioned 2026-06-24, so escalation is now
    local-only: the operator reads ESCALATION.md + audit.jsonl."""
    try:
        write_escalation(run_id, head_sha, reason, detail)
        return (True, "escalation recorded to ESCALATION.md")
    except Exception as exc:  # noqa: BLE001 - escalation must never crash the loop
        return (False, f"{type(exc).__name__}: {exc}")


def _first_escalate_line(text: str) -> str:
    """The first ESCALATE: line claude emitted (the out-of-bounds reason)."""
    for line in (text or "").splitlines():
        if "ESCALATE:" in line:
            return line.strip()
    return "ESCALATE:"


def _write_context(worktree: Path, run_id: int, head_sha: str,
                   log_out: str, diff_out: str) -> None:
    """Drop the failing-log tail + offending diff into the worktree for claude."""
    try:
        log_tail = "\n".join((log_out or "").splitlines()[-200:])[:8000]
        body = (
            f"# CI Watchdog context - run {run_id} (head {head_sha})\n\n"
            f"## Failing step log (tail)\n\n```\n{log_tail}\n```\n\n"
            f"## Offending commit diff\n\n```diff\n{(diff_out or '')[:12000]}\n```\n"
        )
        (Path(worktree) / _CONTEXT_FILE).write_text(body, encoding="utf-8")
    except OSError:
        pass


def _default_runner(worktree: Path):
    """The live ``runner(label, argv) -> (rc, out)`` for one dispatch."""
    wt = str(worktree)

    def runner(label, argv):
        cmd = list(argv)
        if cmd and cmd[0] == "gh":
            cmd[0] = _gh()
        timeout = _STEP_TIMEOUTS.get(label, 120)
        if label == "claude_fix":
            # FLEET-KIT-v1: the only path that starts `claude`. Fails closed
            # (route refused -> no spawn, never a direct claude).
            return _claude_fix_via_kit(cmd, Path(wt), timeout)
        if label in ("push", "land_push"):
            # FLEET-KIT v12 item 16 a: a push runs inside the tree's git
            # lock. A refusal (lock held, leftover index.lock) is a failed
            # step, never a bypass.
            try:
                with _git_lock(wt, _GITLOCK_OWNER, "push"):
                    return _run(cmd, cwd=Path(wt), timeout=timeout)
            except RuntimeError as exc:
                return 3, str(exc)
        if label == "land_commit":
            # FLEET-COMMON 16/17: the commit goes through fleet_gitlock run.
            return _gitlock_commit(cmd, Path(wt), timeout)
        if label == "land_verify":
            return _identity_check(Path(wt), cmd[-1])
        return _run(cmd, cwd=Path(wt), timeout=timeout)

    return runner


_LAND_STEPS = ("land_fetch", "land_head", "land_branch", "land_squash",
               "land_commit", "land_verify", "land_push")


def _land(steps: dict, runner, head_sha: str) -> tuple[str, str]:
    """Land a green fix on main locally. Returns ("", "") once main carries it,
    else (reason, detail) with main untouched and the PR left open.

    Order is the safety argument: the base is re-read and must still be the
    tested ``head_sha`` (decision 3) before anything is built; the commit is
    made through the kit's identity-refusing lock; the identity check reads
    exactly the range being pushed; the push is a plain fast-forward, so a main
    that moved in the meantime rejects it instead of being overwritten.
    """
    for label in _LAND_STEPS:
        rc, out = runner(label, steps[label])
        if rc != 0:
            return (f"not landed: step {label} failed (rc {rc}); PR left open for "
                    "the operator to land locally", (out or "")[:2000])
        if label == "land_head" and is_stale(head_sha, (out or "").strip()):
            return ("not landed: main moved off the tested base during the check "
                    "watch; PR left open for the operator to land locally",
                    (out or "").strip()[:80])
    return "", ""


def execute_dispatch(run_id: int, head_sha: str, *, arm: bool,
                     worktree: Path = WORKTREE, repo: str = REPO,
                     runner=None) -> dict:
    """Run (arm=True) or merely surface (arm=False) one fix dispatch.

    Dry run (default) mutates nothing and runs no command - it returns the plan
    so the operator can inspect exactly what an armed run would do. Armed, it
    syncs the throwaway worktree, runs the tool-restricted headless fix, enforces
    the frozen-file guard BETWEEN the fix and any push, then pushes + opens the
    ci-fix PR, BLOCKS on that PR's own CI checks, and ONLY when they pass lands
    the fix locally as one operator commit on main (``_land``) and closes the
    PR. A red PR or any land refusal escalates; nothing is ever merged on
    GitHub. ``runner(label, argv) -> (rc, stdout)`` is injectable for tests.
    """
    plan = plan_dispatch(run_id, head_sha, worktree=worktree, repo=repo)
    if not arm:
        return {"mode": "dry_run", "run_id": run_id, "head_sha": head_sha,
                "branch": branch_name(run_id), "steps": plan}

    steps = {label: argv for label, argv in plan}
    if runner is None:
        runner = _default_runner(worktree)

    # 1. sync the dedicated worktree onto a fresh ci-fix/<id> branch off main
    for label in ("fetch", "reset", "branch"):
        rc, out = runner(label, steps[label])
        if rc != 0:
            return {"action": "error", "stage": label, "detail": (out or "")[:2000]}

    # 2. gather the failing-log tail + offending diff -> context file claude Reads
    _, log_out = runner("gather_log", steps["gather_log"])
    _, diff_out = runner("gather_diff", steps["gather_diff"])
    _write_context(worktree, run_id, head_sha, log_out, diff_out)

    # 3. tool-restricted headless fix; an ESCALATE: line short-circuits cleanly
    _, fix_out = runner("claude_fix", steps["claude_fix"])
    if (fix_out or "").startswith(ROUTE_REFUSED_MARK):
        return {"action": "error", "stage": "claude_fix_route",
                "detail": (fix_out or "")[:2000]}
    if "ESCALATE:" in (fix_out or ""):
        return {"action": "escalate", "reason": _first_escalate_line(fix_out),
                "detail": (fix_out or "")[:2000]}

    # 4. frozen-file guard BETWEEN the fix and any push (defense in depth vs the
    #    whitelist) - refuse + escalate rather than land a frozen-file edit
    _, names_out = runner("diff_names", steps["diff_names"])
    changed = [ln.strip() for ln in (names_out or "").splitlines() if ln.strip()]
    if not changed:
        return {"action": "no_change", "detail": "headless fix produced no edits"}
    frozen = touches_frozen(changed)
    if frozen:
        return {"action": "escalate", "changed": changed,
                "reason": "fix touches frozen file(s): " + ", ".join(frozen)}

    # 5. push -> open PR (the self-gate + local landing follow in steps 6-7)
    rc, out = runner("push", steps["push"])
    if rc != 0:
        return {"action": "error", "stage": "push", "detail": (out or "")[:2000]}
    rc, pr_out = runner("pr_create", steps["pr_create"])
    if rc != 0:
        return {"action": "error", "stage": "pr_create", "detail": (pr_out or "")[:2000]}
    lines = [ln.strip() for ln in (pr_out or "").splitlines() if ln.strip()]
    pr = lines[-1] if lines else ""
    # 6. self-gate: BLOCK on the ci-fix PR's OWN CI; land ONLY when green.
    #    A red (or timed-out) check escalates - we never land an unverified fix.
    rc, checks_out = runner("wait_checks", steps["wait_checks"])
    if rc != 0:
        return {"action": "escalate", "pr": pr, "changed": changed,
                "reason": "ci-fix PR checks did not pass - not landed",
                "detail": (checks_out or "")[:2000]}
    # 7. land locally as ONE operator commit (never a GitHub-side merge), then
    #    close the PR. A refusal leaves main untouched and the PR open.
    reason, detail = _land(steps, runner, head_sha)
    if reason:
        return {"action": "escalate", "pr": pr, "changed": changed,
                "reason": reason, "detail": detail}
    rc, out = runner("pr_close", steps["pr_close"])
    return {"action": "landed", "pr": pr, "changed": changed,
            "close_rc": rc, "close_out": (out or "")[:500]}


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


def main(arm: bool = False) -> int:
    """One poll cycle. Returns 0 always (a scheduled-task failure is noise).

    arm=False (default) is a READ-ONLY dry run: it logs each decision + the
    would-run dispatch plan to audit.jsonl but mutates NO persistent state
    (sentinel / attempts / pr-log) and runs no gh/git/claude side effects. The
    scheduled task invokes the module bare -> dry run; arming = adding ``--arm``
    to the task action once the live red-main dry run looks right.
    """
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
        rec = {"ts": now, "run_id": rid, "head_sha": head[:12], "arm": arm}

        if is_stale(head, current_head):
            # Decision 3: main already moved on - this failure is superseded.
            rec["action"] = "skip_stale"
            audit_line(rec)
            if arm:
                write_sentinel(rid)
            continue
        if should_escalate(rid):
            rec["action"] = "escalate"
            if arm:
                ok, _ = send_escalation(rid, head, "two strikes")
                rec["bridge_ok"] = ok
                write_sentinel(rid)
            audit_line(rec)
            continue
        if rate_limited(now):
            rec["action"] = "rate_limited"
            audit_line(rec)
            # Do NOT advance the sentinel - retry once the 24h window clears.
            continue

        result = execute_dispatch(rid, head, arm=arm)
        rec["action"] = "dispatch"
        rec["dispatch"] = result.get("action") or result.get("mode")
        if arm:
            rec["attempt"] = bump_attempts(rid)
            if result.get("pr"):
                rec["pr"] = result["pr"]
                record_pr_creation(now, rid, result["pr"])
            if result.get("action") == "escalate":
                ok, _ = send_escalation(
                    rid, head, result.get("reason", "dispatch escalate"),
                    result.get("detail", ""))
                rec["bridge_ok"] = ok
            audit_line(rec)
            write_sentinel(rid)
        else:
            # Dry run: surface the plan, leave the sentinel where it is so the
            # inspection is idempotent (re-runnable against the same red run).
            rec["plan_steps"] = [s[0] for s in result.get("steps", [])]
            audit_line(rec)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(arm="--arm" in sys.argv[1:]))
