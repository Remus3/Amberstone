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
import json
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
    # 2026-10-04 Y-02: the one operator-notify path. claude_quota_watch (a task
    # target) imports it and its toast spawns powershell.exe under that same
    # pythonw host; the three watchers' own toast spawns moved here.
    "core/operator_notify.py",
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
    # 2026-10-03 Wave1 merge: headless drain-wave launcher (git via _git,
    # creationflags=_NO_WINDOW); found by the import-closure completeness check.
    "ops/loop/drain_waves_2_3.py",
    # 2026-10-09: headless full-tree repo review driver (commit 07dbdc589),
    # found by the completeness check. Both git spawns (_git_bytes and the
    # check-ignore in build_manifest) already passed creationflags=_NO_WINDOW;
    # its reviewer runs go through fleet_route.spawn. Listed so it stays so.
    "ops/loop/repo_review.py",
    "tools/upstream_drift_check.py",
    # 2026-10-03, second pass: found by the IMPORT CLOSURE added to the
    # completeness check (a task target imports them, so they run under the
    # same pythonw host). routes_loop_status was already compliant;
    # sibling_name_sweep spawned git bare at _git and _has_object and now
    # carries the flag.
    "dashboard/routes_loop_status.py",
    "tools/sibling_name_sweep.py",
    # 2026-10-04 lift-1 CI repair (RM-607/RM-608): found by the import closure.
    # scripts/rewind_catchup.py (a task target) imports the RM-607 item-tape
    # store -> liveclient_cache -> the RM-608 death recap, which imports this
    # module. ensure_running's Popen already carries CREATE_NO_WINDOW; listed
    # so it stays that way.
    "core/daemon_slayer_client.py",
    # Same root, second edge (RM-637): liveclient_cache -> obs_recorder ->
    # obs_publisher -> dashboard/_state_builder pulls the dashboard dispatch
    # tree into the closure. Both sites already pass CREATE_NO_WINDOW.
    "coaches/voice_coach.py",
    # 2026-10-10 RM-735: dashboard/server.py's one-shot :8889 spawn moved into
    # the periodic liveness watchdog (spawn, taskkill, py-spy dump); every
    # child passes _NO_WINDOW. server.py itself no longer spawns.
    "dashboard/_vision_watchdog.py",
    # 2026-10-24 s133: found by the pythonw entry-point half (agents/supervisor.py
    # under RC-Phase3-Supervisor imports it). Both check_output sites already
    # passed the flag; listed so they stay that way.
    "agents/_supervisor_common.py",
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
#
# THREE SINCE 2026-10-09. tools/pytest_guard.py left the list when its only
# spawn - the RC_FULL_SUITE=1 whole-suite branch - was removed (MAIN kit-v13
# ORDER section 2, PERF-AUDIT item 10). It now spawns nothing, which
# tests/test_pytest_guard.py pins structurally, so listing it here would only
# trip the "has no subprocess spawn" assertion below.
HOOK_SPAWNERS = (
    "tools/rc_facts.py",
    "tools/precommit_gate.py",
    "tools/edit_lint_check.py",
    # 2026-10-24 s133: the kit's Stop hook, run under pythonw by the settings
    # template and found by the template half of the scope. A vendored kit file
    # is never edited here; it was compliant when swept (4688: git.exe children,
    # no console window) and listing it turns a kit regression into a red test
    # to report to MAIN rather than a flicker nobody traces.
    "ops/fleet_kit/fleet_done.py",
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
    # instead: these files spawn under a hook, and a hook's flash is the
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
#   3. (2026-10-03, hand-off residual closed) the in-repo IMPORT CLOSURE of the
#      task targets - a module a target only imports runs under the same host.
# NOT discoverable, so still hand-listed above: hook scripts (the wiring lives
# in .claude/settings.json, which is per-host and untracked), any task target
# outside the tree, and imports done dynamically (importlib by path string).
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
    file. `C:\\Example Repo\\tools\\x.py` tokenises to `Repo\\tools\\x.py`
    (the regex stops at the space), so the leading parts are dropped until a
    repo-relative path matches."""
    parts = [p for p in mention.replace("\\", "/").split("/") if p]
    for i in range(len(parts)):
        cand = "/".join(parts[i:])
        if cand in universe:
            return cand
    return None


def _module_candidates(rel: str, node: ast.AST) -> list[str]:
    """Repo-relative .py paths an import node in `rel` may resolve to.

    Covers dotted absolute imports (`tools.x`, `from ops.loop import y`) and the
    bare sibling form the tools/ scripts use after `sys.path.insert(_TOOLS)`
    (`import ds_wiki_staleness_check`) - the latter resolves in the importer's
    OWN directory. Over-approximation is safe: a candidate that is not a
    tracked file is simply dropped by the caller."""
    here = rel.rpartition("/")[0]
    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
        names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
    out = []
    for name in names:
        dotted = name.replace(".", "/")
        out += [f"{dotted}.py", f"{dotted}/__init__.py"]
        if here and "." not in name:
            out.append(f"{here}/{name}.py")
    return out


def _import_closure(roots: set[str], universe: frozenset[str], root: Path) -> set[str]:
    """Console-flash residual (hand-off 2026-10-03): a module a task target
    only IMPORTS spawns under the same pythonw host, and was discoverable only
    by hand. Walk in-repo imports from the task targets to a fixed point."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for cand in _module_candidates(rel, node):
                    if cand in universe and cand not in seen:
                        todo.append(cand)
    return seen


# ---------------------------------------------------------------------------
# PYTHONW ENTRY POINTS (2026-10-24, s133 window-silence pass). Halves 1-3 find
# task targets only through TRACKED task definitions under ops/ or tools/, and
# measured against the live `schtasks` store that day 16 of the 22 RC-* tasks
# running a .py under pythonw sat OUTSIDE the scope, as did main.py (the
# supervisor's app_cmd) and moon_vision_server.py (respawned by
# dashboard/_vision_watchdog.py). Two more halves close that, each joined with
# its in-repo import closure:
#   4. every hook script the tracked settings template
#      (ops/claude_settings.example.json) launches under pythonw.exe - READ from
#      the template, so a new pythonw hook is in scope without a list edit;
#   5. the supervisor's app_cmd script (ops/rc_config.json) plus
#      PYTHONW_ENTRY_POINTS below - hand-listed from the 2026-10-24 schtasks
#      sweep, because the machine's task store is not a tracked file.
# ---------------------------------------------------------------------------

_SETTINGS_TEMPLATE = "ops/claude_settings.example.json"
_RC_CONFIG = "ops/rc_config.json"
_PYTHONW_HOOK = re.compile(r"pythonw\.exe\W+\$CLAUDE_PROJECT_DIR/([A-Za-z0-9_./-]+\.py)")

#: Live pythonw targets of RC-* scheduled tasks and supervisor-spawned daemons,
#: from `schtasks /query` on 2026-10-24. A `-m pkg.mod` target is spelled as
#: its file. An entry that stops existing fails test_pythonw_entry_points_exist.
PYTHONW_ENTRY_POINTS = (
    "mission_control.py",
    "moon_vision_server.py",
    "agents/supervisor.py",
    "ops/phase3_file_audit.py",
    "ops/rc_supervisor.py",
    "ops/loop/inbox_tick.py",
    "scripts/data_pipeline.py",
    "scripts/rewind_catchup.py",
    "tools/claude_quota_watch.py",
    "tools/cost_health_watchdog.py",
    "tools/ddragon_mirror_refresh.py",
    "tools/hotkey_listener.py",
    "tools/lcu_agent.py",
    "tools/live_flip_watcher.py",
    "tools/liveclient_relay.py",
    "tools/moon_sync_poller.py",
    "tools/replay_chain_watch.py",
    "tools/replay_roster_pull.py",
    "tools/rofl_archiver.py",
    "tools/rofl_dedupe.py",
    "tools/start_daemon_slayer.py",
    "tools/start_ds_matchdb_mcp.py",
    "tools/upstream_drift_check.py",
)


def _pythonw_roots(root: Path, universe: frozenset[str]) -> set[str]:
    """Halves 4 and 5: pythonw-hosted hook scripts, the supervisor's app
    script and the hand-listed live entry points that exist in this tree."""
    roots = {rel for rel in PYTHONW_ENTRY_POINTS if rel in universe}
    template = root / _SETTINGS_TEMPLATE
    if template.is_file():
        text = template.read_text(encoding="utf-8", errors="replace")
        roots |= {m for m in _PYTHONW_HOOK.findall(text) if m in universe}
    config = root / _RC_CONFIG
    if config.is_file():
        try:
            app_cmd = json.loads(config.read_text(encoding="utf-8")).get("app_cmd") or []
        except (ValueError, AttributeError):
            app_cmd = []
        roots |= {str(a).replace("\\", "/") for a in app_cmd
                  if str(a).replace("\\", "/") in universe}
    return roots


def _discoverable_scope(root: Path) -> set[str]:
    py = {_repo_walk.relative_posix(p, root)
          for p in _repo_walk.repo_files(root, ("*.py",))}
    universe = frozenset(py)
    scope = {rel for rel in py if rel.startswith(_LOOP_DIR)}
    scope |= _import_closure(_pythonw_roots(root, universe), universe, root)
    task_targets: set[str] = set()
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
                task_targets.add(hit)
    scope |= task_targets
    scope |= _import_closure(task_targets, universe, root)
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
                   "tools/ci_watchdog.py", "tools/upstream_drift_check.py",
                   # halves 4 and 5 (2026-10-24): a template hook, the
                   # supervisor's app_cmd, a hand-listed live task target.
                   "tools/edit_lint_check.py", "main.py", "tools/hotkey_listener.py"):
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
        '$Script = "C:\\Example Repo\\tools\\nightly.py"\n'
        "Register-ScheduledTask -TaskName RC-Nightly\n", encoding="utf-8")

    found = _unlisted_spawners(tmp_path, set())
    assert set(found) == {"ops/loop/adjudicator.py", "tools/nightly.py"}, found
    assert _unlisted_spawners(
        tmp_path, {"ops/loop/adjudicator.py", "tools/nightly.py"}) == {}


def test_pythonw_entry_points_exist() -> None:
    # A renamed or retired entry point would silently shrink half 5.
    missing = [rel for rel in PYTHONW_ENTRY_POINTS if not (ROOT / rel).is_file()]
    assert not missing, f"PYTHONW_ENTRY_POINTS names files that are gone: {missing}"


def test_pythonw_halves_reach_hooks_app_and_tasks(tmp_path: Path) -> None:
    # Positive control for halves 4 and 5 on a tree with no git index: a
    # pythonw hook in the template, the supervisor's app_cmd and a hand-listed
    # entry point each pull a spawning import into the scope; a console-python
    # hook (python.exe, not pythonw) does not.
    (tmp_path / "ops").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "core").mkdir()
    hook = ('"$LOCALAPPDATA/Programs/Python/Python314/pythonw.exe" '
            '\\"$CLAUDE_PROJECT_DIR/tools/hook_a.py\\"')
    console = ('"$LOCALAPPDATA/Programs/Python/Python314/python.exe" '
               '\\"$CLAUDE_PROJECT_DIR/tools/hook_b.py\\"')
    (tmp_path / _SETTINGS_TEMPLATE).write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": hook}, {"command": console}]}]}}),
        encoding="utf-8")
    (tmp_path / _RC_CONFIG).write_text(
        json.dumps({"app_cmd": ["pythonw.exe", "main.py"]}), encoding="utf-8")
    spawn = "import subprocess\nsubprocess.run(['git', 'status'])\n"
    (tmp_path / "tools" / "hook_a.py").write_text("import core.via_hook\n", encoding="utf-8")
    (tmp_path / "tools" / "hook_b.py").write_text(spawn, encoding="utf-8")
    (tmp_path / "core" / "via_hook.py").write_text(spawn, encoding="utf-8")
    (tmp_path / "main.py").write_text("from core import via_app\n", encoding="utf-8")
    (tmp_path / "core" / "via_app.py").write_text(spawn, encoding="utf-8")
    (tmp_path / "tools" / "hotkey_listener.py").write_text(spawn, encoding="utf-8")

    found = set(_unlisted_spawners(tmp_path, set()))
    assert found == {"core/via_hook.py", "core/via_app.py", "tools/hotkey_listener.py"}, found


# ---------------------------------------------------------------------------
# THE FLAG THAT DOES NOTHING (2026-10-24, s133). Every check above asks whether
# a spawn passes CREATE_NO_WINDOW. That flag governs CONSOLE-subsystem children
# only, and pythonw.exe is a GUI binary: `[sys.executable, "-m", "ruff"]` run
# from a pythonw-hosted module passes the flag, goes green above, and still
# flashes, because the pythonw child has no console and ruff's own wrapper then
# spawns ruff.exe unflagged. Measured that day with Security 4688 events plus a
# SetWinEventHook watcher: all 34 console windows created on the desktop in 15
# minutes were that ruff.exe, from tools/edit_lint_check.py on every Edit/Write
# of any Claude session in the tree, and 25 of them stole the foreground.
# A `-m` run from these modules goes through the interpreter's console twin
# (python.exe), which under CREATE_NO_WINDOW gets a hidden console the
# grandchild inherits.
# ---------------------------------------------------------------------------


def _module_runner_sites(tree: ast.AST) -> list[int]:
    """Line of every `[sys.executable, "-m", ...]` argv literal (list or tuple)."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
            continue
        head, flag = node.elts[0], node.elts[1]
        if (isinstance(head, ast.Attribute) and head.attr == "executable"
                and isinstance(head.value, ast.Name) and head.value.id == "sys"
                and isinstance(flag, ast.Constant) and flag.value == "-m"):
            out.append(node.lineno)
    return out


def _module_runners(root: Path, rels: set[str]) -> dict[str, list[int]]:
    out = {}
    for rel in sorted(rels):
        path = root / rel
        if not path.is_file():
            continue
        sites = _module_runner_sites(ast.parse(path.read_text(encoding="utf-8")))
        if sites:
            out[rel] = sites
    return out


def test_no_module_runner_is_rehosted_in_pythonw() -> None:
    offenders = _module_runners(ROOT, set(ALL_SPAWNERS) | _discoverable_scope(ROOT))
    assert not offenders, (
        f"`[sys.executable, '-m', ...]` in a pythonw-hosted module: {offenders}. "
        f"Under pythonw that child is a GUI process, CREATE_NO_WINDOW does "
        f"nothing for it, and the module's own console grandchild (ruff.exe "
        f"from `-m ruff`) flashes a visible console. Run it through the console "
        f"twin: `_console_interpreter()` in tools/edit_lint_check.py."
    )


def test_module_runner_check_catches_a_synthetic_rehost(tmp_path: Path) -> None:
    # Positive control: the exact 2026-10-24 call shape is found, the fixed
    # shape is not, and an empty enumeration would fail the first assertion.
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "bad.py").write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-m', 'ruff', 'check'], creationflags=0x08000000)\n",
        encoding="utf-8")
    (tools / "good.py").write_text(
        "import subprocess\n"
        "subprocess.run([_console_interpreter(), '-m', 'ruff'], creationflags=0x08000000)\n",
        encoding="utf-8")
    assert _module_runners(tmp_path, {"tools/bad.py", "tools/good.py"}) == {"tools/bad.py": [2]}


@pytest.mark.parametrize("rel", ["tools/edit_lint_check.py", "tools/precommit_gate.py"])
def test_console_interpreter_maps_pythonw_to_its_console_twin(rel: str, tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_twin_{Path(rel).stem}", ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    both = tmp_path / "both"
    both.mkdir()
    (both / "pythonw.exe").write_bytes(b"")
    (both / "python.exe").write_bytes(b"")
    lone = tmp_path / "lone"
    lone.mkdir()
    (lone / "pythonw.exe").write_bytes(b"")
    assert mod._console_interpreter(str(both / "pythonw.exe")) == str(both / "python.exe")
    assert mod._console_interpreter(str(both / "PYTHONW.EXE")) == str(both / "python.exe")
    # No twin on disk: keep the interpreter rather than return a path that is not there.
    assert mod._console_interpreter(str(lone / "pythonw.exe")) == str(lone / "pythonw.exe")
    # A console interpreter is already right.
    assert mod._console_interpreter(str(both / "python.exe")) == str(both / "python.exe")
