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
import re
from pathlib import Path

import pytest

from tests import _repo_walk

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
    # ops/loop/adjudicator.py dropped 2026-10-03: since merge fcc53a232 it spawns
    # only through ops/loop/fleet_route.spawn (the kit's own _run, which carries
    # the kit's no-window flag); it holds no direct subprocess call any more.
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
    # 2026-09-08: the inbox responder's single process seam, run unattended by
    # RC-InboxResponder under pythonw every 5 minutes. It is the ONLY module in
    # the responder carrying a literal subprocess call - the spawn, exec and
    # export modules all go through it - so listing this one file gives the
    # guard exactly the two calls that matter (the Popen and the taskkill).
    "tools/inbox_responder_procs.py",
    # 2026-10-03: found by the completeness check below, not by hand. The three
    # loop modules were already compliant (every site resolves to _NO_WINDOW);
    # upstream_drift_check (RC-UpstreamDriftCheck, daily, pythonw) was not -
    # its trigger_refresh spawned two children bare - and now carries the flag.
    "ops/loop/interrupt.py",
    "ops/loop/lane_launcher.py",
    "ops/loop/queue_loop.py",
    "tools/upstream_drift_check.py",
)

# Modules run by a CLAUDE HOOK, which is the same exposure by a different route:
# a hook is hosted by an interpreter with no console of its own, so every
# console-subsystem child it spawns gets a fresh console allocated and flashes.
#
# WHY THESE FOUR, 2026-09-14. A sibling's (code LL) pythonw Stop hook and
# PreToolUse gate spawning git.exe without CREATE_NO_WINDOW, measured
# 2026-09-14, was the live instance of this shape on the box. RC's own four
# hook scripts were ALREADY compliant when swept - spawn sites / flagged read
# 2/2 (rc_facts.py:92, :110), 3/3 (precommit_gate.py:66, :254, :540), 1/1
# (pytest_guard.py:56) and 1/1 (edit_lint_check.py:68), every one of them
# `creationflags=_NO_WINDOW` resolving through
# `getattr(subprocess, "CREATE_NO_WINDOW", 0)`. They are listed so that stays
# true, because the guard's failure mode is a NEW spawn in an old file, and
# nothing else would notice: a hook's console flash is invisible in CI and
# shows up only as a flicker on a desktop.
HOOK_SPAWNERS = (
    "tools/rc_facts.py",
    "tools/precommit_gate.py",
    "tools/pytest_guard.py",
    "tools/edit_lint_check.py",
)

#: Both tests below run over the union. Unattended-by-schedule and
#: unattended-by-hook are the same defect with two entry points.
ALL_SPAWNERS = SCHEDULED_SPAWNERS + HOOK_SPAWNERS

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
# tools/console_flash_control.py is that probe made repeatable, and it is
# deliberately absent from both lists above: its unflagged spawns ARE the
# positive control, so listing it would redden the guard on the one file whose
# job is to produce the symptom.
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


@pytest.mark.parametrize("rel", ALL_SPAWNERS)
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


@pytest.mark.parametrize("rel", ALL_SPAWNERS)
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


def _subprocess_import_forms(tree: ast.AST) -> list[str]:
    """Every import of `subprocess` that is NOT a bare `import subprocess`."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" and alias.asname:
                    out.append(f"import subprocess as {alias.asname}")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names = ", ".join(a.name for a in node.names)
            out.append(f"from subprocess import {names}")
    return out


@pytest.mark.parametrize("rel", HOOK_SPAWNERS)
def test_hook_spawners_import_subprocess_by_name_only(rel: str) -> None:
    # PINS THE SCANNER'S BLIND SPOT. _spawn_calls above matches only
    # `subprocess.<attr>(`, so `import subprocess as sp` or
    # `from subprocess import run` makes every spawn in the file invisible to
    # the guard - which goes GREEN while the module flashes. There is no way to
    # resolve that from the call site alone, so the import form is pinned
    # instead: these four files spawn under a hook, and a hook's flash is the
    # one this repository has actually paid for.
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    forms = _subprocess_import_forms(tree)
    assert forms == [], (
        f"{rel} imports subprocess under an alias or by name ({forms}). "
        f"The creationflags scanner in this file only sees `subprocess.run(` "
        f"and friends, so those spawns would be invisible to it. Use a bare "
        f"`import subprocess`."
    )


# ---------------------------------------------------------------------------
# COMPLETENESS (2026-10-03). Every check above runs over a HAND-LIST, so a new
# spawn in a module that is not on the list is invisible by construction - the
# same blind spot the 2026-07-27 note records, still open after it: re-adding a
# direct subprocess call to ops/loop/adjudicator.py (dropped from the list when
# it moved onto fleet_route.spawn) would have stayed green. So the guard's
# DISCOVERABLE scope is now enumerated from the tree and every spawning module
# in it must be listed or allowlisted with a reason.
#
# DISCOVERABLE SCOPE, two halves:
#   1. every tracked .py under ops/loop/ - the autonomous loop runs every one
#      of its modules unattended, cycle after cycle;
#   2. every tracked .py named as a target by a tracked scheduled-task
#      definition (*.xml / *.ps1 directly under ops/ or tools/ whose text
#      registers a task) - the RC-* entry points themselves.
# NOT discoverable, so still hand-listed above: hook scripts (the wiring lives
# in .claude/settings.json, which is per-host and untracked), modules a task
# target IMPORTS (no transitive walk - tools/inbox_responder_procs.py is listed
# by hand for exactly that reason), and any task target outside the tree.
# ---------------------------------------------------------------------------

#: Spawning modules in the discoverable scope that are deliberately NOT held to
#: the creationflags check. Every entry needs a reason; a frozen file that
#: cannot be made compliant goes here, never edited. Empty today: every
#: discovered spawner is compliant and listed.
SPAWN_ALLOWLIST: dict[str, str] = {}

_LOOP_DIR = "ops/loop/"
_TASK_DEF_DIRS = ("ops/", "tools/")
_TASK_DEF_MARKERS = ("ScheduledTask", "<Task ", "schtasks")
_PY_MENTION = re.compile(r"[A-Za-z0-9_./\\-]+\.py\b")

_SUBPROCESS_SPAWNS = _SPAWN_ATTRS | {"getoutput", "getstatusoutput"}


def _spawn_sites(tree: ast.AST) -> list[tuple[int, str]]:
    """Every process-spawning call, in every form, as (lineno, form).

    Deliberately WIDER than _spawn_calls: it also sees `import subprocess as
    sp`, `from subprocess import run`, os.system / os.popen / os.spawn* /
    os.exec* / os.startfile and asyncio.create_subprocess_*. Discovery must not
    share the per-file scanner's blind spot, or a module spawning only through
    an alias would be neither listed nor found.
    """
    sub_names = {"subprocess"}
    bare: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    sub_names.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            bare.update(a.asname or a.name for a in node.names
                        if a.name in _SUBPROCESS_SPAWNS)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in bare:
            out.append((node.lineno, func.id))
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner, attr = func.value.id, func.attr
            if ((owner in sub_names and attr in _SUBPROCESS_SPAWNS)
                    or (owner == "os" and (attr in {"system", "popen", "startfile"}
                                           or attr.startswith(("spawn", "exec"))))
                    or (owner == "asyncio"
                        and attr.startswith("create_subprocess_"))):
                out.append((node.lineno, f"{owner}.{attr}"))
    return sorted(out)


def _resolve_mention(mention: str, universe: frozenset[str]) -> str | None:
    """Longest path suffix of a task-definition .py mention that is a tracked
    file. `C:\\Riot Commander\\tools\\x.py` tokenises to `Commander\\tools\\x.py`
    (the regex stops at the space), so the leading parts are dropped until a
    repo-relative path matches."""
    parts = [p for p in mention.replace("\\", "/").split("/") if p]
    for i in range(len(parts)):
        cand = "/".join(parts[i:])
        if cand in universe:
            return cand
    return None


def _discoverable_scope(root: Path) -> set[str]:
    py = {_repo_walk.relative_posix(p, root)
          for p in _repo_walk.repo_files(root, ("*.py",))}
    universe = frozenset(py)
    scope = {rel for rel in py if rel.startswith(_LOOP_DIR)}
    for path in _repo_walk.repo_files(root, ("*.xml", "*.ps1")):
        rel = _repo_walk.relative_posix(path, root)
        head, _, name = rel.rpartition("/")
        if f"{head}/" not in _TASK_DEF_DIRS or not name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(m in text for m in _TASK_DEF_MARKERS):
            continue
        for mention in _PY_MENTION.findall(text):
            hit = _resolve_mention(mention, universe)
            if hit:
                scope.add(hit)
    return scope


def _unlisted_spawners(root: Path, listed: set[str]) -> dict[str, list]:
    out = {}
    for rel in sorted(_discoverable_scope(root)):
        if rel in listed:
            continue
        sites = _spawn_sites(ast.parse((root / rel).read_text(encoding="utf-8")))
        if sites:
            out[rel] = sites
    return out


def test_discoverable_scope_is_not_vacuous() -> None:
    # An empty scope and a fully-listed tree give the same green verdict, so
    # anchor the enumeration on files each half must reach.
    _repo_walk.self_check(ROOT)
    scope = _discoverable_scope(ROOT)
    for anchor in ("ops/loop/executor.py", "ops/loop/adjudicator.py",
                   "tools/ci_watchdog.py", "tools/upstream_drift_check.py"):
        assert anchor in scope, f"{anchor} fell out of the discoverable scope"
    spawning = [rel for rel in scope
                if _spawn_sites(ast.parse((ROOT / rel).read_text(encoding="utf-8")))]
    assert len(spawning) >= 5, spawning


def test_allowlist_entries_carry_a_reason_and_still_apply() -> None:
    scope = _discoverable_scope(ROOT)
    for rel, reason in SPAWN_ALLOWLIST.items():
        assert reason.strip(), f"{rel} is allowlisted without a reason"
        assert rel not in ALL_SPAWNERS, f"{rel} is both listed and allowlisted"
        assert rel in scope, f"{rel} is allowlisted but outside the scope - drop it"
        assert _spawn_sites(ast.parse((ROOT / rel).read_text(encoding="utf-8"))), (
            f"{rel} is allowlisted but no longer spawns - drop it")


def test_every_discovered_spawner_is_listed_or_allowlisted() -> None:
    unlisted = _unlisted_spawners(ROOT, set(ALL_SPAWNERS) | set(SPAWN_ALLOWLIST))
    assert not unlisted, (
        f"Modules in the guard's discoverable scope spawn a child process but "
        f"are neither in SCHEDULED_SPAWNERS / HOOK_SPAWNERS nor in "
        f"SPAWN_ALLOWLIST, so nothing checks their creationflags: {unlisted}. "
        f"Pass creationflags=CREATE_NO_WINDOW and list the module, or allowlist "
        f"it with a reason."
    )


def test_completeness_check_catches_a_synthetic_spawn(tmp_path: Path) -> None:
    # Positive control: the exact regression this check exists for - a direct
    # spawn re-added to the adjudicator - plus an aliased one in a scheduled
    # task's target, on a tree with no git index (the walker's pruned path).
    loop = tmp_path / "ops" / "loop"
    loop.mkdir(parents=True)
    (loop / "adjudicator.py").write_text(
        "import subprocess\nsubprocess.run(['git', 'status'])\n", encoding="utf-8")
    (loop / "quiet.py").write_text("x = 1\n", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "nightly.py").write_text(
        "from subprocess import Popen as P\nP(['schtasks'])\n", encoding="utf-8")
    (tools / "interactive.py").write_text(
        "import os\nos.system('cls')\n", encoding="utf-8")
    (tmp_path / "ops" / "install_RC_Nightly.ps1").write_text(
        '$Script = "C:\\Riot Commander\\tools\\nightly.py"\n'
        "Register-ScheduledTask -TaskName RC-Nightly\n", encoding="utf-8")

    found = _unlisted_spawners(tmp_path, set())
    assert set(found) == {"ops/loop/adjudicator.py", "tools/nightly.py"}, found
    assert _unlisted_spawners(
        tmp_path, {"ops/loop/adjudicator.py", "tools/nightly.py"}) == {}
