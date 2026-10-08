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
2. STDIN BESIDE ARGV. RC's callers put a short instruction on argv and a
   multi-kilobyte body on stdin (`claude -p "<task>"` reading piped context).
   It reaches the child as `input=` through the `run` seam into the KIT'S OWN
   launch, so only the stdin shape is RC's; the process launch, the DEVNULL
   default and the timeout tree kill are the kit's. FLEET-KIT-v10 closed both
   asks of MAIN 1327 item 1.1: the launch is public (`fleet_headless.launch`,
   preferred here; the private `_run` is the same object and the fallback
   name), and `spawn(stdin_data=)` exists. A kit with neither launch name is
   refused before a start is counted (no fallback launch).
   The kit's own `stdin=True` (the WHOLE prompt on stdin, NO argv prompt) is
   passed through as `prompt_on_stdin=True`: that is the lane runner's and
   the loop executor's shape (`claude -p` reading its whole prompt from a
   pipe), and the only shape for a prompt over the kit's ARGV_PROMPT_MAX.
3. CWD - CLOSED in FLEET-KIT-v4: passed through as the kit's own `cwd=`; the
   budget stays in RC's own root, so the fleet cap counts every RC run in one
   place.
4. TIMEOUT - CLOSED in FLEET-KIT-v4: the child is started by the kit's own
   `_run`, so a timeout kills the whole process tree (taskkill /T /F); the kit
   records the timeout and resets the status itself; this module only
   re-raises TimeoutExpired so RC callers keep their contract.
5. The raw `CompletedProcess` (stdout, stderr, returncode) is returned beside
   the kit's usage line, because RC callers judge stderr and the full JSON.
6. EFFORT, MODEL, SESSION - THIN PASS-THROUGH (MAIN 0839 ORDER, kit v10: "RC:
   route lanes through spawn / the CLI, use effort="). `effort=`, `model=`,
   `session_id=` and `resume=` go to the kit's same-named parameters ONLY when
   the caller sets them; RC adds no default and no validation of its own, so
   the kit's `pick_effort` / `pick_model` stay the one policy and the kit's
   own check refuses a bad value before anything starts. The RC-local
   `--effort` argv knob (the loop executor's) is retired into `effort=`.

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
EXIT_TIMEOUT = 4  # the kit CLI's own code for a run its timeout killed
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
# None -> the kit's own process launch, `fleet_headless._run`: stdin DEVNULL
# unless a body is given, and a timeout kills the WHOLE process tree
# (taskkill /T /F) before TimeoutExpired is re-raised into the kit, which then
# records error "timeout" and resets the status. tests/conftest.py rebinds it to
# a subprocess.run forwarder so caller-shape tests can keep stubbing run.
_launch = None


def _kit_launcher(k):
    """The kit's launch function, or None when this kit version has none.

    v10 names it publicly (`launch`); `_run` is the pre-v10 private name of
    the same object, kept as the fallback for an older vendored kit."""
    for name in ("launch", "_run"):
        fn = getattr(k, name, None)
        if callable(fn):
            return fn
    return None


def spawn(prompt: str, *, caller: str, note: str = "", writes_code: bool = False,
          bare: bool = False, rules_file=None, extra: Sequence[str] = (),
          stdin: Optional[str] = None, cwd=None, timeout: float = 3600,
          root=None, kind: Optional[str] = None, model: Optional[str] = None,
          effort: Optional[str] = None, prompt_on_stdin: bool = False,
          session_id: Optional[str] = None, resume: Optional[str] = None):
    """Start ONE headless run through the kit. Returns `(usage_line, proc)`.

    `kind` (kit v8, FLEET-COMMON 14 e) labels the usage line build / inbox /
    triage; omitted, the kit infers it from the note (drain-* -> build) and the
    pre-v8 call shape is kept byte-for-byte (no `kind=` reaches the kit).
    `model`, `effort`, `session_id` and `resume` are the kit's own parameters,
    passed through only when set (module docstring item 6).
    `prompt_on_stdin=True` is the kit's `stdin=True`: the WHOLE prompt rides
    stdin and the argv carries none of it. It cannot be combined with `stdin`
    (a body beside an argv instruction): both would feed the one pipe.

    Raises `RouteRefused` before anything starts when either the RC gate or the
    kit refuses. `proc` is the raw CompletedProcess the kit's `run` seam saw.
    """
    if prompt_on_stdin and stdin is not None:
        raise ValueError("prompt_on_stdin and stdin both feed stdin - pick one")
    he = _headless_env()
    try:
        url = he.resolve_base_url(caller=caller)
    except he.HeadlessRouteRefused as exc:
        raise RouteRefused(exc.reason, exc.detail) from None

    k = kit()
    root = Path(root) if root is not None else ROOT
    launch = _launch or _kit_launcher(k)
    if launch is None:
        # Fail closed before the kit counts a start: without the kit's own
        # launch there is no process-tree kill on timeout, and RC must not
        # quietly fall back to a launch that leaves claude's children running.
        he._log_refusal(caller, "kit")
        raise RouteRefused("kit", "vendored kit has no _run launcher")
    seen = {}

    def _run(argv, **kw):
        if stdin is not None:
            kw["input"] = stdin
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
        try:
            proc = launch(argv, **kw)
        except subprocess.TimeoutExpired as exc:
            seen["timeout"] = exc
            raise
        seen["proc"] = proc
        return proc

    # FLEET-KIT-v4: the child's working directory is the kit's own `cwd=`
    # parameter (budget, status and usage stay under root). The child is
    # started by the kit's own launch (`_run`), so a timeout kills the whole
    # process tree; the kit then catches it, writes the usage line with error
    # "timeout" and sets the status back to idle. RC callers keep their
    # contract (TimeoutExpired is raised), so it is re-raised here after the
    # kit has finished its record. The `run` seam is still RC's for ONE thing:
    # the body rides stdin BESIDE a short argv instruction (`input=` into the
    # kit's own `_run`), which the kit's `stdin=True` (the whole prompt on
    # stdin, no argv prompt) does not express - see the module docstring.
    do_spawn = _kit_spawn or k.spawn
    # Only what the caller set reaches the kit: an omitted parameter keeps the
    # earlier call shape byte-for-byte and leaves the kit's own pick in force.
    opt_kw = {key: value for key, value in (
        ("kind", kind), ("model", model), ("effort", effort),
        ("session_id", session_id), ("resume", resume)) if value is not None}
    if prompt_on_stdin:
        opt_kw["stdin"] = True
    try:
        line = do_spawn(root, CODE, prompt, note=note, writes_code=writes_code, bare=bare,
                        rules_file=rules_file, timeout=timeout, extra=tuple(extra),
                        run=_run, url_source=lambda: url, connect=_connect,
                        exe_source=_exe_source, cwd=cwd, **opt_kw)
    except k.Refused as exc:
        he._log_refusal(caller, "kit")
        raise RouteRefused("kit", str(exc)) from None
    except subprocess.TimeoutExpired:
        _idle(k, root)
        raise
    if "timeout" in seen:
        raise seen["timeout"]
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
                   [--writes-code] [--note NAME] [--timeout S]
                   [--kind build|inbox|triage] [--model M] [--effort E]
                   [--cwd DIR] [--prompt-stdin] [-- EXTRA...]

    `--model` / `--effort` are the kit's own parameters, passed through only
    when given. `--cwd` is the child's working directory (the budget, status
    and usage files stay under this tree's root). `--prompt-stdin` sends the
    whole prompt on stdin (the kit's stdin=True); a prompt longer than the
    kit's ARGV_PROMPT_MAX goes there anyway, exactly as the kit's own CLI does.
    `-- EXTRA` reaches the kit's `extra=` (the kit's own CLI has no such door).

    Prints the run's result text to stdout and the child's stderr to stderr.
    Exit: the child's code, 3 when the route or the kit refused, 4 when the
    kit's timeout killed the run (the kit CLI's codes).
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
    on_stdin = "--prompt-stdin" in args or len(prompt) > kit().ARGV_PROMPT_MAX
    try:
        line, proc = spawn(prompt, caller=caller, note=_opt("--note", "") or "",
                           writes_code="--writes-code" in args, extra=extra,
                           timeout=float(_opt("--timeout", "3600")),
                           kind=_opt("--kind"), model=_opt("--model"),
                           effort=_opt("--effort"), cwd=_opt("--cwd"),
                           prompt_on_stdin=on_stdin)
    except RouteRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_REFUSED
    except subprocess.TimeoutExpired:
        # The kit has killed the whole process tree and written the usage line
        # (error "timeout"); the runner gets the kit CLI's timeout code, not a
        # traceback.
        sys.stderr.write("headless run timed out; the kit killed the process tree\n")
        return EXIT_TIMEOUT
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
