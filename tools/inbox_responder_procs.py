"""The inbox responder's single process seam.

Every child process the responder creates - the export's git calls, the
`claude.exe` spawn, every measure and every pre-check - is born in
`popen_capture` below. Nothing else in the responder writes a literal
`subprocess.Popen(`.

That concentration buys two properties that are otherwise invisible:

CONSOLE FLASH. `pythonw.exe` suppresses the console of the process it hosts,
not of any child that process spawns, so an unattended scheduled task that
spawns a console program flashes a window on the operator's desktop.
`CREATION_FLAGS` is written into the two literal spawn calls here, and
`tests/test_no_console_flash_scheduled_tools.py` lists this file so an AST
guard holds both of them.

KILL ALLOWANCE. A timeout that receives the full tree kill costs
`KILL_CMD_TIMEOUT_S + KILL_WAIT_S` on top of its own timeout. A cycle in which
every process times out has 14 such terms, which puts the summed worst case at
1160 s against a 600 s task execution time limit. `KillBudget` restores the
bound: the runner mints ONE budget per cycle and binds it into the export
runner, the spawn request and the measure runner, so the first timeout of a
cycle gets the full sequence and every later one gets `proc.kill()` with no
wait - 0 s by construction, recorded as `kill_skipped`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Sequence

# CREATE_NO_WINDOW. The literal rather than `subprocess.CREATE_NO_WINDOW`,
# because that attribute does not exist off Windows and this module is imported
# on CI as well as on Legion.
CREATION_FLAGS = 0x08000000 if os.name == "nt" else 0

# Assigned exactly ONCE each, at module level. The summed-timeout arm in
# tests/test_inbox_responder_task.py derives the ETL bound from these three
# names by census, so a second assignment anywhere in this file breaks it.
KILL_CMD_TIMEOUT_S = 30
KILL_WAIT_S = 30
KILL_ALLOWANCE_PER_CYCLE = 1

# Narrow enough to keep the BLE ratchet clean, wide enough to cover everything
# a spawn or a kill can actually raise: OSError (binary missing, permission,
# no such process), ValueError (bad argument shape) and the subprocess family
# (TimeoutExpired, SubprocessError).
_SPAWN_ERRORS = (OSError, ValueError, subprocess.SubprocessError)


@dataclass(frozen=True)
class ProcResult:
    """What one child process did. `exc` is the exception CLASS NAME.

    The runner files a failed call as `exc:<cls>`, so the seam records the name
    rather than the object - it is the shape the row wants and it serialises.
    """

    exit_code: Optional[int]
    stdout: bytes
    stderr: bytes
    timed_out: bool
    survived_kill: bool
    kill_skipped: bool
    wall_ms: int
    exc: Optional[str]


class KillBudget:
    """The per-cycle allowance of full tree kills. `take()` is one-way."""

    def __init__(self, n: int = KILL_ALLOWANCE_PER_CYCLE) -> None:
        self._remaining = int(n)

    @property
    def remaining(self) -> int:
        return self._remaining

    def take(self) -> bool:
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True


def kill_tree(pid: int) -> None:
    """Kill the process and everything under it. Errors are swallowed.

    A kill is best-effort cleanup on a path that has already failed, so a
    missing taskkill or an already-reaped pid must never become the reason the
    cycle raises.
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=CREATION_FLAGS,
                timeout=KILL_CMD_TIMEOUT_S,
                capture_output=True,
            )
        except _SPAWN_ERRORS:
            pass
        return
    # POSIX: popen_capture starts the child in its own session, so the pid is
    # its own process-group leader and the group is the tree.
    try:
        os.killpg(pid, getattr(signal, "SIGKILL", 9))
    except _SPAWN_ERRORS:
        pass


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _as_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", "surrogatepass")
    return b""


def popen_capture(
    argv: Sequence[str],
    *,
    cwd,
    env,
    stdin_bytes: bytes,
    timeout_s: float,
    kill_budget: KillBudget,
) -> ProcResult:
    """Run one child to completion under `timeout_s`, capturing both streams.

    Never raises for a process-level fault: a binary that will not start, a
    timeout, a child that survives its kill - each comes back as a field on the
    ProcResult so the caller can file a row and keep going.
    """
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            creationflags=CREATION_FLAGS,
            start_new_session=(os.name != "nt"),
        )
    except _SPAWN_ERRORS as exc:
        return ProcResult(
            exit_code=None,
            stdout=b"",
            stderr=b"",
            timed_out=False,
            survived_kill=False,
            kill_skipped=False,
            wall_ms=_elapsed_ms(started),
            exc=type(exc).__name__,
        )

    exit_code: Optional[int] = None
    stdout = b""
    stderr = b""
    timed_out = False
    survived_kill = False
    kill_skipped = False
    exc_name: Optional[str] = None

    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout_s)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        # Whatever the timeout managed to buffer, if anything. No second
        # communicate on either branch - that is what hangs a wedged child.
        stdout = _as_bytes(getattr(exc, "output", None))
        stderr = _as_bytes(getattr(exc, "stderr", None))
        if kill_budget.take():
            kill_tree(proc.pid)
            try:
                proc.wait(KILL_WAIT_S)
            except subprocess.TimeoutExpired:
                survived_kill = True
            except _SPAWN_ERRORS:
                pass
        else:
            # The allowance is spent. TerminateProcess on the immediate child
            # returns at once; no tree walk, no wait, so this costs 0 s.
            kill_skipped = True
            try:
                proc.kill()
            except _SPAWN_ERRORS:
                pass
    except _SPAWN_ERRORS as exc:
        exc_name = type(exc).__name__

    return ProcResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        survived_kill=survived_kill,
        kill_skipped=kill_skipped,
        wall_ms=_elapsed_ms(started),
        exc=exc_name,
    )
