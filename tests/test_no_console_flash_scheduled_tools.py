"""Scheduled tools must not flash a console window on Legion.

WHY THIS EXISTS. `pythonw.exe` suppresses the console of the process IT hosts,
not of any child that process spawns. So a scheduled task can be correctly
configured to use `pythonw.exe` and STILL flash: every `subprocess.run` of a
console program (powershell, git, schtasks, cmd) allocates its own console.

Measured 2026-07-26: `tools/replay_chain_watch.py` runs under RC-ReplayChainWatch
every 15 minutes and calls `_ps()` from three sites, so the operator saw three
windows flash in sequence, four times an hour. `tools/ci_watchdog.py` already
carried the correct guard (and a comment naming this exact symptom), which is
what made the omission next door easy to miss.

The guard is `creationflags=CREATE_NO_WINDOW` (0x08000000) on every spawn in a
module that runs unattended on a schedule. This test pins that, because the
symptom is invisible in CI - it only shows up as a flicker on a desktop.

SCOPE: modules that run UNATTENDED - invoked by an RC-* scheduled task, or by
the autonomous loop (ops/loop/*), which spawns cycle after cycle with no human
at the keyboard. Interactive tools (strip_em_dashes, repair_mojibake,
build_installer) are deliberately NOT listed; a console is expected when a human
runs them from a shell.

WHY THE LIST GREW (2026-07-27). SCHEDULED_SPAWNERS is enumerated by hand from
the consumer side, so a new unattended spawner is invisible to the guard by
construction: this file was green while ops/loop/done_sentinel.py flashed a
console on every single loop cycle. The list now covers the loop modules too,
and the constant check below resolves the flag through variables instead of
grepping for a substring, because the substring form went green on a module that
never passed the flag to anything.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

CREATE_NO_WINDOW = 0x08000000

# Modules run unattended by an RC-* scheduled task that spawn a child process.
SCHEDULED_SPAWNERS = (
    "tools/replay_chain_watch.py",
    "tools/ci_watchdog.py",
    # 2026-07-26: RC-Supervisor is one of only three RC-* tasks that must stay
    # Interactive (it drives the Electron overlay), so it KEEPS a desktop after
    # the S4U sweep and its console children would flash. The other 13 tasks are
    # now S4U and structurally cannot show a window.
    "ops/rc_supervisor.py",
    # Already compliant when swept; pinned so it stays that way. The 2026-07-26
    # hand-off claimed this file was unguarded - it was not, both of its spawn
    # sites already carried the platform-guarded flag.
    "ops/rc_dev_runtime.py",
    # 2026-07-27: the autonomous loop. These run unattended every cycle, which
    # is the same exposure a scheduled task has. done_sentinel is the FINAL
    # action of every cycle and claude_stub is the dry-run executor, and both
    # were spawning a bare `git rev-parse` - the Sibling-A twin had
    # already fixed exactly these two and the fix never crossed back.
    "ops/loop/done_sentinel.py",
    "ops/loop/claude_stub.py",
    "ops/loop/loop_controller.py",
    "ops/loop/executor.py",
    "ops/loop/adjudicator.py",
    # 2026-08-01: the perseus tools spawn perseus-vault.exe, which is a
    # CONSOLE-subsystem binary (PE Subsystem=3 - measured, not assumed), so a
    # parent with no console of its own gets a window allocated for the child.
    # LATENT rather than observed: both run from a console-bearing parent today.
    # Pinned so that scheduling either one under pythonw cannot reintroduce the
    # flash silently.
    "tools/perseus_recall.py",
    "tools/perseus_sync.py",
    # 2026-08-01: THE measured flash. Ran under pythonw from the INTERACTIVE
    # RC-ClaudeQuotaWatch task every PT2H and spawned a .cmd shim with no
    # flag, so a CUI child got a fresh console. It lived OUTSIDE the repo at
    # an account-specific home directory and was therefore unguardable; moved into tools/
    # in the same session precisely so this list can see it, and the scheduled
    # task was repointed at the new path.
    "tools/claude_quota_watch.py",
)

# ---------------------------------------------------------------------------
# THE BLIND SPOT, stated so it is not mistaken for coverage. SCHEDULED_SPAWNERS
# is a hand-list of IN-REPO paths, so any scheduled task whose target lives
# outside the tree is invisible here by construction. That is not hypothetical:
# the 2026-08-01 flash was exactly that shape, and the fix required MOVING the
# file into the repo before any test could hold it.
#
# The measurement, for whoever hits this next: a 250ms EnumWindows poll came
# back CLEAN and the flash was real - polling had to drop to 8ms to catch it.
# "I watched and saw nothing" is not evidence of absence at this timescale.
# The decisive probe is to spawn the same command from pythonw twice, once
# unflagged and once flagged, and diff the visible ConsoleWindowClass set.
# ---------------------------------------------------------------------------

_SPAWN_ATTRS = {"run", "Popen", "check_output", "call", "check_call"}


def _spawn_calls(tree: ast.AST) -> list[ast.Call]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute)
                and func.attr in _SPAWN_ATTRS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"):
            found.append(node)
    return found


@pytest.mark.parametrize("rel", SCHEDULED_SPAWNERS)
def test_every_subprocess_spawn_passes_creationflags(rel: str) -> None:
    path = ROOT / rel
    assert path.exists(), f"{rel} is missing - update SCHEDULED_SPAWNERS"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = _spawn_calls(tree)
    assert calls, f"{rel} has no subprocess spawn - remove it from the list"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords if kw.arg}
        assert "creationflags" in kwargs, (
            f"{rel}:{call.lineno} spawns a child process without "
            f"creationflags. Under a pythonw.exe-hosted scheduled task this "
            f"flashes a console window on the operator's desktop. Pass "
            f"creationflags=0x08000000 (CREATE_NO_WINDOW) on Windows."
        )


def _assignments(tree: ast.AST) -> dict[str, list[ast.expr]]:
    """name -> every value expression assigned to it, at any scope.

    Scope-blind on purpose. A false MATCH would need the same identifier bound
    to a real CREATE_NO_WINDOW elsewhere in the file, which is not a way this
    bug has ever appeared; a scope-aware resolver that missed a function-local
    `flags = ...` would fail the compliant modules instead.
    """
    out: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name) and node.value is not None:
                out.setdefault(tgt.id, []).append(node.value)
    return out


def _is_no_window(expr: ast.expr, names: dict[str, list[ast.expr]],
                  seen: frozenset[str] = frozenset()) -> bool:
    """Does this expression evaluate to CREATE_NO_WINDOW on Windows?

    Accepts the three forms in the tree: the literal 0x08000000 (usually behind
    an `if os.name == "nt"` guard), `subprocess.CREATE_NO_WINDOW`, and
    `getattr(subprocess, "CREATE_NO_WINDOW", 0)`. The getattr form is checked
    for the EXACT attribute name, because a typo there returns the default 0 and
    the spawn still succeeds - it just flashes. That is the fail-open case.
    """
    if isinstance(expr, ast.Constant):
        return expr.value == CREATE_NO_WINDOW
    if isinstance(expr, ast.Attribute):
        return expr.attr == "CREATE_NO_WINDOW"
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Name) and func.id == "getattr" and len(expr.args) >= 2:
            attr = expr.args[1]
            return isinstance(attr, ast.Constant) and attr.value == "CREATE_NO_WINDOW"
        return False
    if isinstance(expr, ast.IfExp):
        return (_is_no_window(expr.body, names, seen)
                or _is_no_window(expr.orelse, names, seen))
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        return (_is_no_window(expr.left, names, seen)
                or _is_no_window(expr.right, names, seen))
    if isinstance(expr, ast.Name) and expr.id not in seen:
        return any(_is_no_window(v, names, seen | {expr.id})
                   for v in names.get(expr.id, ()))
    return False


@pytest.mark.parametrize("rel", SCHEDULED_SPAWNERS)
def test_the_no_window_constant_is_the_real_win32_value(rel: str) -> None:
    # The kwarg being PRESENT is not sufficient: a mistyped getattr attribute or
    # a variable that never held the flag both spawn fine and still flash. So
    # resolve what each creationflags argument actually evaluates to.
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names = _assignments(tree)
    for call in _spawn_calls(tree):
        flags = next((kw.value for kw in call.keywords
                      if kw.arg == "creationflags"), None)
        assert flags is not None, f"{rel}:{call.lineno} has no creationflags"
        assert _is_no_window(flags, names), (
            f"{rel}:{call.lineno} passes creationflags, but it does not resolve "
            f"to CREATE_NO_WINDOW (0x08000000). Check for a mistyped "
            f"getattr(subprocess, ...) attribute name - that form returns the "
            f"default 0 and fails open, flashing a console anyway."
        )
