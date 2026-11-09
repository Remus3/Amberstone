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

7. ONE USAGE LEDGER, ALWAYS LABELLED (MAIN 2026-10-08 2246 ORDER section 7,
   FLEET-COMMON 14 e). Every usage row carries a kit `kind` and a NON-EMPTY
   note label: a caller that names no note is labelled by its own `caller`
   name (the kit would otherwise log note "" and kind "unattributed"). The
   default root is the MAIN checkout even when this file is loaded from a
   linked worktree (the kit's own `main_checkout`), so the budget, the status
   file and the usage rows MAIN reads stay in one place; the child then still
   runs in the worktree (cwd defaults to this file's tree). In the main tree
   nothing changes.

The STOP flags (`ops/loop/control/STOP`, `ops/runtime/INBOX_RESPONDER_STOP`)
and the responder's agreement-record arming check are NOT enforced by the kit
and are NOT moved here: they stay in front of their own callers, unchanged.

Stdlib only, runnable as a bare script (`--help`) for the PowerShell runners,
and importable with no repo root on sys.path (siblings load by file path).
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
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
# RC-5: the repin tool's unknown-option control (tools/repin_subagent_cli.py
# UNKNOWN_NOTE), plus every older label of that control in the usage ledger.
_DESIGNED_NEGATIVE_NOTE = re.compile(
    r"-designed-negative-rc1$|^(?:repin-subagent-cli|[a-z0-9]+-canary)-unknown$")


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
    """No headless run was started. `reason` is a short constant code. `code`
    is the machine class to match on (kit v14, MAIN 2026-10-09 0930 step 5): a
    kit refusal carries the kit's own Refused.code ("proxy-unreachable",
    "budget-spent", ...); an RC gate refusal carries its reason."""

    def __init__(self, reason: str, detail: str = "", code: str | None = None):
        super().__init__(f"headless route refused: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail
        self.code = code or reason


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


def _kit_root(k) -> Path:
    """The budget / status / usage root (module docstring item 7): the MAIN
    checkout when ROOT is a linked worktree, else ROOT itself, unchanged."""
    root = Path(ROOT)
    find_main = getattr(k, "main_checkout", None)
    if not callable(find_main):
        return root
    try:
        main = Path(find_main(root))
        return main if main != root.resolve() else root
    except OSError:
        return root


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
          session_id: Optional[str] = None, resume: Optional[str] = None,
          log_path: Optional[str] = None):
    """Start ONE headless run through the kit. Returns `(usage_line, proc)`.

    `kind` (kit v8, FLEET-COMMON 14 e) labels the usage line build / inbox /
    triage; omitted, it is named "build" here, because the v18 kit refuses a
    missing kind (code "no-kind") and no longer infers one from the note. An
    empty `note` is replaced by `caller`, so the row is never unlabelled
    (module docstring item 7); `root` omitted is `_kit_root` (the MAIN
    checkout), with the child's cwd kept in this tree.
    `model`, `effort`, `session_id`, `resume` and `log_path` are the kit's own
    parameters, passed through only when set (module docstring item 6);
    `log_path` (RM-795) makes the kit stream the run as stream-json into that
    file instead of capturing one json result.
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
    note = note or caller
    if kind is None:
        # Kit v18: a missing kind is refused ("no-kind"), the kit no longer
        # infers one. RC's route callers are build workers; inbox / triage
        # callers pass their kind explicitly.
        kind = "build"
    if root is not None:
        root = Path(root)
    else:
        root = _kit_root(k)
        if cwd is None and root != Path(ROOT):
            cwd = ROOT
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
        ("session_id", session_id), ("resume", resume),
        ("log_path", log_path)) if value is not None}
    if prompt_on_stdin:
        opt_kw["stdin"] = True
    try:
        line = do_spawn(root, CODE, prompt, note=note, writes_code=writes_code, bare=bare,
                        rules_file=rules_file, timeout=timeout, extra=tuple(extra),
                        run=_run, url_source=lambda: url, connect=_connect,
                        exe_source=_exe_source, cwd=cwd, **opt_kw)
    except k.Refused as exc:
        he._log_refusal(caller, "kit")
        raise RouteRefused("kit", str(exc),
                           code=getattr(exc, "code", None) or "refused") from None
    except subprocess.TimeoutExpired:
        _idle(k, root)
        raise
    if "timeout" in seen:
        raise seen["timeout"]
    return line, seen.get("proc")


def is_designed_negative(row: dict) -> bool:
    """True for a usage row that failed exactly as a designed negative must.

    The kit logs a child's real rc and owns the row's shape, so a run that
    SHOULD exit 1 can only say so in its note label. Only that exit counts: a
    labelled run that exited otherwise, or exited 1 for any other named reason,
    is a real failure. A pre-kit-v27 row has error null; v27 has the stderr tail.
    """
    if not _DESIGNED_NEGATIVE_NOTE.search(str(row.get("note") or "")):
        return False
    error = row.get("error")
    return (row.get("rc") == 1 and row.get("is_error") is not True and not row.get("limit")
            and (error is None or "unknown option" in str(error).lower()))


def row_failed(row: dict) -> bool:
    """RC's one definition of a failed usage row: a non-zero exit, a named error
    (a timeout has rc null) or a child-reported error, less designed negatives."""
    if _DESIGNED_NEGATIVE_NOTE.search(str(row.get("note") or "")):
        return not is_designed_negative(row)
    return (row.get("rc") not in (0, None) or bool(row.get("error"))
            or row.get("is_error") is True)


def usage_failures(root=None, last: int = 300) -> dict:
    """Read-only count over the last `last` rows of the kit's usage ledger."""
    k = kit()
    path = (Path(root) if root is not None else _kit_root(k)) / k.USAGE_REL
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    rows = []
    for text in raw.splitlines():
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    rows = rows[-last:] if last > 0 else []
    failed: dict = {}
    for row in rows:
        if row_failed(row):
            note = str(row.get("note") or "")
            failed[note] = failed.get(note, 0) + 1
    return {"rows": len(rows), "failed": sum(failed.values()),
            "designed_negative": sum(1 for r in rows if is_designed_negative(r)),
            "failed_notes": failed}


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
    k = kit()
    _idle(k, Path(root) if root is not None else _kit_root(k), nt)


EXIT_USAGE = 2
# The CLI's options (s144 true-audit cycle 178). A value flag CONSUMES the
# next token, so a value that looks like a flag ("--prompt --prompt-stdin")
# is only a value; the old membership test over the whole argv read it as
# the flag too. Anything else before `--` is a usage error, never ignored: a
# typo such as --prompt_stdin used to be dropped and the run went ahead
# without it.
_VALUE_FLAGS = frozenset(("--caller", "--prompt", "--prompt-file", "--note", "--timeout",
                          "--kind", "--model", "--effort", "--cwd", "--root", "--last"))
_BOOL_FLAGS = frozenset(("--writes-code", "--prompt-stdin", "--usage-failures"))


class _UsageError(ValueError):
    """A malformed command line; the message names the option, never a value
    read from a file."""


def _parse(args: Sequence[str]) -> dict:
    """{flag: value or True}; raises _UsageError on an unknown, repeated or
    value-less flag."""
    opts: dict = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok not in _VALUE_FLAGS and tok not in _BOOL_FLAGS:
            raise _UsageError(f"unknown argument {tok!r}")
        if tok in opts:
            raise _UsageError(f"{tok} given more than once")
        if tok in _BOOL_FLAGS:
            opts[tok] = True
            i += 1
            continue
        if i + 1 >= len(args):
            raise _UsageError(f"{tok} needs a value")
        opts[tok] = args[i + 1]
        i += 2
    return opts


def _timeout_s(raw: str) -> float:
    """--timeout as a finite positive number of seconds. nan, inf, zero and a
    negative are refused here rather than handed to the kit's process wait."""
    try:
        value = float(raw)
    except ValueError:
        raise _UsageError("--timeout must be a number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise _UsageError("--timeout must be a finite number of seconds above zero")
    return value


def _last_n(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise _UsageError("--last must be a whole number") from None
    if value < 0:
        raise _UsageError("--last must not be negative")
    return value


def _read_prompt(path: str) -> str:
    """The prompt file as text. A UTF-8 BOM (PowerShell 5.1 writes one) is
    dropped rather than sent to the model. A read or decode failure names the
    file and the problem only: a decode error's own text quotes the bytes."""
    try:
        return Path(path).read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _UsageError(f"prompt file {path!r} is not UTF-8 text") from None
    except ValueError:  # a NUL in the path (a direct main(argv=) caller)
        raise _UsageError(f"prompt file {path!r} is not a usable path") from None
    except OSError as exc:
        raise _UsageError(f"prompt file {path!r} cannot be read "
                          f"({exc.strerror or type(exc).__name__})") from None


def _write(stream, text: str) -> None:
    """Write text the stream's encoding may not carry. A python whose stdout
    is a pipe writes the ANSI code page (cp1252 here) unless the caller sets
    PYTHONIOENCODING, and only run_lane.ps1 does: a result holding U+2192
    raised UnicodeEncodeError AFTER the run had finished (exit 1, result
    lost). Such a character is written as a backslash escape instead."""
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(enc, "backslashreplace").decode(enc, "replace"))


def _result_text(line, proc) -> str:
    text = line.get("result") if isinstance(line, dict) else None
    if text is None:
        out = getattr(proc, "stdout", None)
        return out if isinstance(out, str) else ""
    return text if isinstance(text, str) else json.dumps(text)


def main(argv=None) -> int:
    """CLI for the PowerShell runners.

    fleet_route.py --caller NAME (--prompt TEXT | --prompt-file PATH)
                   [--writes-code] [--note NAME] [--timeout S]
                   [--kind build|inbox|triage] [--model M] [--effort E]
                   [--cwd DIR] [--prompt-stdin] [-- EXTRA...]
           fleet_route.py --usage-failures [--root DIR] [--last N]

    `--model` / `--effort` are the kit's own parameters, passed through only
    when given (an empty value, like an empty --cwd / --kind, is "not given").
    `--cwd` is the child's working directory (the budget, status and usage
    files stay under this tree's root). `--prompt-stdin` sends the whole
    prompt on stdin (the kit's stdin=True); a prompt longer than the kit's
    ARGV_PROMPT_MAX goes there anyway, exactly as the kit's own CLI does.
    `-- EXTRA` reaches the kit's `extra=` (the kit's own CLI has no such door).
    `--timeout` is a finite number of seconds above zero (default 3600).

    Prints the run's result text to stdout and the child's stderr to stderr;
    a character the stream's encoding cannot carry is written as a backslash
    escape. Exit: the child's code (1 when the kit reports no integer code),
    2 for a usage error (an unknown, repeated or value-less option, a bad
    number, an unreadable or non-UTF-8 prompt file, an empty prompt; nothing
    starts), 3 when
    the route or the kit refused, 4 when the kit's timeout killed the run
    (the kit CLI's codes).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    extra: list = []
    if "--" in args:
        i = args.index("--")
        args, extra = args[:i], args[i + 1:]
    try:
        opts = _parse(args)
        if opts.get("--usage-failures"):
            # Read-only (RC-5): the failure count; starts nothing, needs no route.
            last = _last_n(opts.get("--last", "300"))
            doc = usage_failures(root=opts.get("--root"), last=last)
            _write(sys.stdout, json.dumps(doc, indent=1, sort_keys=True) + "\n")
            return 0
        caller = opts.get("--caller")
        prompt = opts.get("--prompt")
        pfile = opts.get("--prompt-file")
        if not caller or (prompt is None) == (pfile is None):
            raise _UsageError("--caller and exactly one of --prompt / --prompt-file "
                              "are required")
        timeout = _timeout_s(opts.get("--timeout", "3600"))
        if pfile is not None:
            prompt = _read_prompt(pfile)
        if not prompt.strip():
            # An empty prompt would still spend one of the tree's 24 h runs.
            raise _UsageError("the prompt is empty")
    except _UsageError as exc:
        _write(sys.stderr, f"fleet_route: {exc}\n")
        _write(sys.stderr, main.__doc__ or "")
        return EXIT_USAGE
    on_stdin = bool(opts.get("--prompt-stdin")) or len(prompt) > kit().ARGV_PROMPT_MAX
    try:
        line, proc = spawn(prompt, caller=caller, note=opts.get("--note") or "",
                           writes_code=bool(opts.get("--writes-code")), extra=extra,
                           timeout=timeout, kind=opts.get("--kind") or None,
                           model=opts.get("--model") or None,
                           effort=opts.get("--effort") or None,
                           cwd=opts.get("--cwd") or None, prompt_on_stdin=on_stdin)
    except RouteRefused as exc:
        _write(sys.stderr, f"{exc}\n")
        return EXIT_REFUSED
    except subprocess.TimeoutExpired:
        # The kit has killed the whole process tree and written the usage line
        # (error "timeout"); the runner gets the kit CLI's timeout code, not a
        # traceback.
        _write(sys.stderr, "headless run timed out; the kit killed the process tree\n")
        return EXIT_TIMEOUT
    _write(sys.stdout, _result_text(line, proc) + "\n")
    err = getattr(proc, "stderr", None)
    if isinstance(err, str) and err:
        _write(sys.stderr, err)
    rc = line.get("rc") if isinstance(line, dict) else None
    # A bool is an int to isinstance; it is not an exit code.
    return rc if type(rc) is int else 1


if __name__ == "__main__":
    raise SystemExit(main())
