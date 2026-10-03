"""RC's one door into the fleet kit: every routed headless `claude` goes here.

FLEET-KIT-v1 (MAIN order 2026-10-03, operator authority): a headless run starts
only through `ops/fleet_kit/fleet_headless.spawn`. The kit owns the proxy URL
check, the TCP probe, the 120-runs-per-24h budget, the lean flags, the model and
effort pick, the child environment, the hidden console, the usage line and the
live status file. This module adds ONLY what the kit cannot express in v1, and
every one of those additions is a named kit gap reported to MAIN, not a patch:

1. FAIL CLOSED THROUGH `ops/loop/headless_env.py` (LEDGER 1460). The URL the
   kit receives comes from `headless_env.resolve_base_url`, so a refusal is
   still logged to `logs/headless_route.log` by the gate the CLAUDE.md rule
   names, and the kit's own `check_url` + probe then run on top of it. The
   kit's probe is pointed at `headless_env._probe`, so there is ONE probe
   implementation in RC and the suite's fakes cover both.
2. STDIN. The kit passes the prompt on argv only. A multi-kilobyte body would
   hit the Windows command-line ceiling and leak into process listings, so a
   caller may pass `stdin=`; it reaches the child through the kit's own `run`
   seam (`subprocess.run(..., input=...)`), which is how `claude -p "<task>"`
   reads piped context.
3. CWD. The kit uses `root` both as the child's working directory and as the
   home of its budget and status files. A caller whose child must run in a
   throwaway worktree passes `cwd=`; the budget stays in RC's own root, so the
   fleet cap counts every RC run in one place.
4. A RAISED TIMEOUT leaves the kit's status file at "running". This module
   writes "idle" back through the kit's own `write_status` before re-raising.
5. The raw `CompletedProcess` (stdout, stderr, returncode) is returned beside
   the kit's usage line, because RC callers judge stderr and the full JSON.

The STOP flags (`ops/loop/control/STOP`, `ops/runtime/INBOX_RESPONDER_STOP`)
and the responder's agreement-record arming check are NOT enforced by the kit
and are NOT moved here: they stay in front of their own callers, unchanged.

Stdlib only, runnable as a bare script (`--help`) for the PowerShell runners,
and importable with no repo root on sys.path (siblings load by file path).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
CODE = "RC"
KIT_PATH = ROOT / "ops" / "fleet_kit" / "fleet_headless.py"
EXIT_REFUSED = 3
# The responder's scheduled task fires every 5 minutes (POLL_INTERVAL_S in
# tools/inbox_responder_runner.py); the idle status names the next tick.
DEFAULT_TICK_S = 300


def _load(name: str, path: Path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def kit():
    """The vendored `fleet_headless` module, loaded by file path."""
    return _load("rc_fleet_kit_fleet_headless", KIT_PATH)


def _headless_env():
    try:
        from ops.loop import headless_env as mod  # noqa: PLC0415
        return mod
    except ImportError:
        return _load("rc_ops_loop_headless_env", Path(__file__).resolve().parent / "headless_env.py")


class RouteRefused(RuntimeError):
    """No headless run was started. `reason` is a short constant code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"headless route refused: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail


class _Closed:
    def close(self) -> None:
        return None


def _connect(addr, timeout=2.0):
    """The kit's `connect` seam, answered by RC's one probe implementation."""
    host, port = addr
    failure = _headless_env()._probe(host, port, timeout)
    if failure is not None:
        raise OSError(failure)
    return _Closed()


def _exe_source():
    return kit().claude_exe()


# Seams a test replaces. Production never rebinds them.
_kit_spawn = None  # None -> kit().spawn


def spawn(prompt: str, *, caller: str, note: str = "", writes_code: bool = False,
          bare: bool = False, rules_file=None, extra: Sequence[str] = (),
          stdin: Optional[str] = None, cwd=None, timeout: float = 3600,
          root=None):
    """Start ONE headless run through the kit. Returns `(usage_line, proc)`.

    Raises `RouteRefused` before anything starts when either the RC gate or the
    kit refuses. `proc` is the raw CompletedProcess the kit's `run` seam saw.
    """
    he = _headless_env()
    try:
        url = he.resolve_base_url(caller=caller)
    except he.HeadlessRouteRefused as exc:
        raise RouteRefused(exc.reason, exc.detail) from None

    k = kit()
    root = Path(root) if root is not None else ROOT
    seen = {}

    def _run(argv, **kw):
        if cwd is not None:
            kw["cwd"] = str(cwd)
        if stdin is not None:
            kw["input"] = stdin
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
        proc = subprocess.run(argv, **kw)  # noqa: PLW1510 - rc is judged by the caller
        seen["proc"] = proc
        return proc

    do_spawn = _kit_spawn or k.spawn
    try:
        line = do_spawn(root, CODE, prompt, note=note, writes_code=writes_code, bare=bare,
                        rules_file=rules_file, timeout=timeout, extra=tuple(extra),
                        run=_run, url_source=lambda: url, connect=_connect,
                        exe_source=_exe_source)
    except k.Refused as exc:
        he._log_refusal(caller, "kit")
        raise RouteRefused("kit", str(exc)) from None
    except subprocess.TimeoutExpired:
        _idle(k, root)
        raise
    return line, seen.get("proc")


def _idle(k, root, next_tick=None) -> None:
    try:
        k.write_status(root, CODE, "idle", "Idle", time.time(),
                       k.RunBudget(Path(root) / k.BUDGET_REL), next_tick=next_tick)
    except OSError:
        pass


def write_idle(next_tick_s: Optional[float] = DEFAULT_TICK_S, root=None) -> None:
    """Scheduler tick between runs: "Idle" plus when the next tick fires.

    Never raises: a status-file fault must not cost the tick that wrote it.
    """
    nt = None if next_tick_s is None else time.time() + float(next_tick_s)
    _idle(kit(), Path(root) if root is not None else ROOT, nt)


def main(argv=None) -> int:
    """CLI for the PowerShell runners.

    fleet_route.py --caller NAME (--prompt TEXT | --prompt-file PATH)
                   [--writes-code] [--note NAME] [--timeout S] [-- EXTRA...]

    Prints the run's result text to stdout and the child's stderr to stderr.
    Exit: the child's code, or 3 when the route or the kit refused.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    extra: list = []
    if "--" in args:
        i = args.index("--")
        args, extra = args[:i], args[i + 1:]

    def _opt(flag, default=None):
        if flag in args:
            j = args.index(flag)
            if j + 1 < len(args):
                return args[j + 1]
        return default

    caller = _opt("--caller")
    prompt = _opt("--prompt")
    pfile = _opt("--prompt-file")
    if not caller or (prompt is None) == (pfile is None):
        sys.stderr.write(main.__doc__ or "")
        return 2
    if pfile is not None:
        prompt = Path(pfile).read_text(encoding="utf-8")
    try:
        line, proc = spawn(prompt, caller=caller, note=_opt("--note", "") or "",
                           writes_code="--writes-code" in args, extra=extra,
                           timeout=float(_opt("--timeout", "3600")))
    except RouteRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_REFUSED
    text = line.get("result")
    if text is None and proc is not None:
        text = proc.stdout
    sys.stdout.write((text or "") + "\n")
    if proc is not None and proc.stderr:
        sys.stderr.write(proc.stderr)
    rc = line.get("rc")
    return rc if isinstance(rc, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
