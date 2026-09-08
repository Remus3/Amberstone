"""The inbox responder's spawn: argv, exe resolution, child env, result taxonomy.

The session this module starts reads a note written by another party, so every
decision here is about keeping that note out of places it could act from and
about making a failure say what actually failed.

ARGV IS CONSTANT. `CLAUDE_ARGV_TAIL` is built from configuration and tracked
constants only. No per-cycle text ever enters it: the note filename and the
note body travel on stdin, inside a nonce fence, and nowhere else. There is no
dollar-cap flag, by decision - RC rides the Max subscription, `total_cost_usd`
is a notional API-equivalent price rather than money billed, and a cap on that
figure produced spawn failures over spend that never happened.

THE EXE IS RESOLVED ONCE, BY THE CALLER. `resolve_claude_exe` is called at
config load and its answer is stored on the config; the cycle reads the stored
path and resolves nothing. It never returns a bare name (spawning `claude` by
name raises FileNotFoundError) and never the `.cmd` shim, and it reads PATH
only from the mapping it is handed - a scheduled task under S4U inherits
MACHINE-scope environment only, so a resolver that fell back to the process
environment would pass in an interactive dry cycle and fail in the task. The
resolution source travels with the path so the row can say which mechanism
found it.

THE FAILURE TAXONOMY SEPARATES TWO THINGS THAT LOOK ALIKE. A result whose
`structured_output` is absent or null did not propose anything, and reading
that as "nothing left to do" is how a spawn fault wears a reassuring label;
it is `no-structured-output`. A result that DID carry a proposal in the wrong
shape is `schema-mismatch`. Both are spawn failures, never `exhausted` - only
a parsed `actions == []` is exhausted, and that decision belongs to a later
gate.

No process is created here. `real_spawner` hands its request to the seam in
`tools/inbox_responder_procs.py`, which owns the only literal spawn call in
the responder.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

from tools import inbox_responder_procs as procs

try:
    from tools.inbox_responder_prompt import PROPOSAL_SCHEMA, SYSTEM_PROMPT
except ImportError:  # pragma: no cover - the prompt module is a parallel slice
    # PARALLEL-SLICE SHIM, to be deleted by the merger once S1 has landed.
    # It exists only so this slice compiles and its arms run standalone; every
    # arm in tests/test_inbox_responder_spawn.py pins the two constants itself.
    SYSTEM_PROMPT = ""
    PROPOSAL_SCHEMA = ""

ROOT = Path(__file__).resolve().parent.parent

# The loop's own config carries an ABSOLUTE path to the `.cmd` shim, which is
# the second-choice source for the real binary. A module constant rather than
# an inline path so an arm can point it somewhere harmless.
LOOP_CONFIG_PATH = ROOT / "ops" / "loop" / "config.json"

# The npm install layout: the shim sits beside `node_modules`, the native
# binary underneath it. The shim itself must never be argv[0].
_EXE_TAIL = Path("node_modules") / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
_SHIM_NAME = "claude.cmd"

# Raw stdout is capped before parsing. 4 MiB is far above any real result
# record and far below anything that would cost real memory to decode.
STDOUT_CAP_BYTES = 4 * 1024 * 1024

# The fields a complete m3 carries. `api_error_status` is deliberately absent:
# it was not in the measured 2.1.251 key list, so its absence is normal and
# must never mark a result incomplete. `structured_output` is absent too - its
# presence is the taxonomy's business, not completeness's.
_M3_REQUIRED = (
    "type",
    "subtype",
    "is_error",
    "terminal_reason",
    "num_turns",
    "duration_ms",
    "duration_api_ms",
    "total_cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class RealSpawnDisabled(Exception):
    """Raised by the runner when a real spawn was defaulted to but not armed.

    Defined here because it belongs to the spawn contract; raised nowhere in
    this module, by design. The one raise site is the runner's spawner
    defaulting, which is the only place that can know whether the operator
    armed a real spawn.
    """


@dataclass(frozen=True)
class SpawnRequest:
    """Everything the seam needs, decided before the slot is held."""

    argv: list[str]
    stdin_bytes: bytes
    env: dict
    cwd: Path
    timeout_s: int
    kill_budget: procs.KillBudget


@dataclass(frozen=True)
class SpawnResult:
    """What one spawn did. `exc` is the exception CLASS NAME, as the row wants."""

    exit_code: Optional[int]
    stdout: bytes
    stderr: bytes
    exc: Optional[str]
    wall_ms: int
    timed_out: bool
    survived_kill: bool
    kill_skipped: bool


Spawner = Callable[[SpawnRequest], SpawnResult]


def CLAUDE_ARGV_TAIL(cfg) -> list[str]:  # noqa: N802 - a constant-shaped builder
    """The read-only headless shape, measured on CLI 2.1.251.

    `--restricted` removes Bash / PowerShell / REPL / WebFetch, ignores user,
    project and local settings files, and confines the file tools to the
    working directory - which is why the working directory is a tracked-only
    export rather than the checkout. Every flag here expires on a CLI upgrade
    and is re-measured by the dry cycle, never inherited.
    """
    return [
        "-p",
        "--restricted",
        "--tools",
        "Read,Glob,Grep",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-turns",
        str(cfg.max_turns),
        "--model",
        cfg.model,
        "--output-format",
        "json",
        "--json-schema",
        PROPOSAL_SCHEMA,
        "--system-prompt",
        SYSTEM_PROMPT,
    ]


def _derive_exe(shim: Union[str, Path, None]) -> Optional[Path]:
    """The native binary that sits under an npm shim, if it is really there."""
    if not shim:
        return None
    candidate = Path(shim).parent / _EXE_TAIL
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _executor_cmd_from_loop_config() -> Optional[str]:
    try:
        data = json.loads(Path(LOOP_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("executor_cmd")
    return value if isinstance(value, str) else None


def resolve_claude_exe(
    cfg, parent_env: Mapping[str, str]
) -> tuple[Optional[Path], Optional[str]]:
    """Find the native binary, in a fixed order, and say which source found it.

    Called once at config load and never inside a cycle. Returns `(None, None)`
    when nothing is found, which is NOT a failure to start: the tick still runs
    its early gates and files its usual row, so the evidence keeps accruing and
    only a cycle that actually reaches the spawn gate reports a missing binary.
    """
    configured = getattr(cfg, "claude_exe", None)
    if configured:
        return Path(configured), "config"

    derived = _derive_exe(_executor_cmd_from_loop_config())
    if derived is not None:
        return derived, "executor_cmd"

    # PATH comes from the injected mapping alone. `shutil.which` falls back to
    # the process environment when handed None, so an absent key becomes "".
    shim = shutil.which(_SHIM_NAME, path=parent_env.get("PATH") or "")
    derived = _derive_exe(shim)
    if derived is not None:
        return derived, "which"

    return None, None


def child_env(parent_env: Mapping[str, str]) -> dict:
    """The spawned session's environment: the parent's, minus the API key.

    RC rides the Max login. A machine-scope `ANTHROPIC_API_KEY` takes
    precedence over that login and bills a metered key, so the pop happens in
    code rather than in an operator shell - a scheduled task has no shell to
    do it in.
    """
    env = dict(parent_env)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def build_request(
    cfg,
    envelope: Union[bytes, str],
    cwd: Union[str, Path],
    kill_budget: procs.KillBudget,
    *,
    env: Mapping[str, str],
) -> SpawnRequest:
    """Assemble the request. `cfg.claude_exe` is already resolved by the caller.

    `env` is passed in rather than derived, so the one call to `child_env` is
    the runner's and a mutant that skips it is visible at the runner's own
    call site.
    """
    if isinstance(envelope, str):
        stdin_bytes = envelope.encode("utf-8", "surrogatepass")
    else:
        stdin_bytes = bytes(envelope)
    return SpawnRequest(
        argv=[str(cfg.claude_exe)] + CLAUDE_ARGV_TAIL(cfg),
        stdin_bytes=stdin_bytes,
        env=dict(env),
        cwd=Path(cwd),
        timeout_s=cfg.spawn_timeout_s,
        kill_budget=kill_budget,
    )


def real_spawner(req: SpawnRequest) -> SpawnResult:
    """Hand the request to the process seam. The only spawner that is real."""
    res = procs.popen_capture(
        req.argv,
        cwd=req.cwd,
        env=req.env,
        stdin_bytes=req.stdin_bytes,
        timeout_s=req.timeout_s,
        kill_budget=req.kill_budget,
    )
    return SpawnResult(
        exit_code=res.exit_code,
        stdout=res.stdout,
        stderr=res.stderr,
        exc=res.exc,
        wall_ms=res.wall_ms,
        timed_out=res.timed_out,
        survived_kill=res.survived_kill,
        kill_skipped=res.kill_skipped,
    )


def _as_text(stdout: Union[bytes, str]) -> str:
    if isinstance(stdout, bytes):
        return stdout.decode("utf-8", "replace")
    return stdout


def parse_result(stdout: Union[bytes, str]) -> Optional[dict]:
    """Read the measured result record. Returns None when nothing parsed.

    The fields are the ones measured on 2.1.251, cache tokens included, so a
    row can carry the per-hop token and wall figures even for a spawn that
    failed a predicate. `api_error_status` is read with `.get`: it was not in
    the measured key list, so its absence records None and is never a fault.
    """
    try:
        body = json.loads(_as_text(stdout))
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None

    usage = body.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    denials = body.get("permission_denials")
    parsed = {
        "type": body.get("type"),
        "subtype": body.get("subtype"),
        "is_error": body.get("is_error"),
        "terminal_reason": body.get("terminal_reason"),
        "num_turns": body.get("num_turns"),
        "duration_ms": body.get("duration_ms"),
        "duration_api_ms": body.get("duration_api_ms"),
        "total_cost_usd": body.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "permission_denials": len(denials) if isinstance(denials, list) else 0,
        "api_error_status": body.get("api_error_status"),
        "structured_output_present": "structured_output" in body,
        "structured_output": body.get("structured_output"),
    }
    parsed["complete"] = all(parsed[name] is not None for name in _M3_REQUIRED)
    return parsed


def _proposal_shape_ok(value: Any) -> bool:
    """The runner's own shape check. No third-party validator is imported."""
    if not isinstance(value, dict):
        return False
    actions = value.get("actions")
    if not isinstance(actions, list):
        return False
    for action in actions:
        if not isinstance(action, dict):
            return False
        if not isinstance(action.get("kind"), str):
            return False
    return True


def spawn_ok(res: SpawnResult) -> tuple[Optional[str], Optional[dict]]:
    """Judge one spawn. Returns `(detail, parsed)`; `detail is None` is success.

    Every miss is a spawn failure and never `exhausted`. `binary-not-found` is
    not produced here: that case never calls the spawner, so there is no result
    to judge, and the gate that skipped the call owns the detail.
    """
    if res.exc is not None:
        return f"exc:{res.exc}", None
    if res.timed_out:
        return "timeout", None
    if res.exit_code != 0:
        return f"exit:{res.exit_code}", None
    if len(res.stdout) > STDOUT_CAP_BYTES:
        return "stdout-oversize", None

    parsed = parse_result(res.stdout)
    if parsed is None:
        return "bad-json", None
    if parsed["type"] != "result":
        return "bad-json", parsed
    if parsed["is_error"] is not False or parsed["subtype"] != "success":
        return f"is_error:{parsed['subtype']}", parsed
    if parsed["terminal_reason"] != "completed":
        return f"terminal:{parsed['terminal_reason']}", parsed

    if not parsed["structured_output_present"] or parsed["structured_output"] is None:
        return "no-structured-output", parsed
    if not _proposal_shape_ok(parsed["structured_output"]):
        return "schema-mismatch", parsed

    return None, parsed
