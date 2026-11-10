"""S144-P-344 - every production process kill and scheduled-task / task-tool reference is a named site, and registry and system-config writes stay at zero.

A kill or a scheduled-task change reaches outside the process that wrote it: a ``taskkill`` can end the operator's game
client, an ``Enable-ScheduledTask`` changes what the box runs at logon, a registry write outlives the repo. The tree has
hard rules for them (CLAUDE.md: never ``Stop-Process``, use ``taskkill /F /PID``; no scheduled-task or registry write from
a lane) but nothing listed the sites that do it. Measured 2026-11-07 by AST over every tracked production ``.py``
(outside ``tests/``, ``docs/``, the vendored ``ops/fleet_kit/`` and any ``test_*.py`` / ``conftest.py``): 40 sites in 20
files, listed in ``_SITES`` with the scope they sit in and why they are safe.

Two detectors, one census:

- CALL: a call whose function name (a bare name or the last attribute) is in ``_KILL_NAMES`` - ``proc.kill()``,
  ``os.kill(pid, 0)``, ``k32.TerminateProcess(...)``, ``os.killpg(...)``. ``os.kill(pid, 0)`` is a liveness probe on
  Python 3.14 (probed on a child this process owned: it neither raised nor ended it), and its rows say so.
- STR: a string literal (docstrings excluded - a docstring is prose, and prose may name ``taskkill``) matching
  ``_CENSUS_TOKENS`` on a word boundary, so an argv list, an f-string fragment or a PowerShell snippet is seen.

A hit is keyed ``(file, "call:<name>" or "str:<token>", scope)``, scope being ``"module"`` or the enclosing function's
dotted qualname. The set is exact: a new site fails until it is added with a reason, a site that goes away must be
dropped.

Held at ZERO, with no row allowed: a registry WRITE call (``SetValueEx``, ``CreateKey``, ``DeleteKey`` ...) and a
string naming a system-configuration tool (``setx``, ``netsh``, ``powercfg``, ``icacls``, ``reg add`` ...). Registry
READS (``OpenKey`` + ``QueryValueEx``, five files) are not in the census.

Named blind spots: a verb or tool name assembled from pieces (including a verb split into its own argv element, so
``['reg', 'add']`` is not seen while ``'reg add'`` is; none in production 2026-11-07), read from a file or from the environment, a ``getattr``
spelling, a call through a stored function object, ``os.system`` / ``shell=True`` strings (a separate guard holds those
at zero), and a script that is not ``.py`` (``.ps1`` / ``.bat`` / ``.cmd`` are outside this census).
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_KILL_NAMES = frozenset({
    "kill", "terminate", "killpg", "send_signal", "_exit", "TerminateProcess", "TerminateJobObject",
})

_CENSUS_RE = re.compile(
    r"(?<![\w-])(taskkill|schtasks|stop-process|enable-scheduledtask|disable-scheduledtask|register-scheduledtask"
    r"|unregister-scheduledtask|start-scheduledtask|stop-scheduledtask|set-scheduledtask|wmic|pkill|killall|tskill)(?![\w-])",
    re.IGNORECASE,
)

_ZERO_CALL_NAMES = frozenset({
    "SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx", "DeleteValue", "SaveKey",
    "LoadKey", "RegSetValueExW", "RegSetValueExA", "RegCreateKeyExW", "RegDeleteKeyW", "RegDeleteValueW",
    "SetEnvironmentVariable", "SetEnvironmentVariableW",
})

_ZERO_RE = re.compile(
    r"(?<![\w-])(setx|netsh|powercfg|icacls|takeown|bcdedit|new-itemproperty|set-itemproperty|remove-itemproperty"
    r"|set-executionpolicy|add-mppreference|new-netfirewallrule|set-service|stop-service|start-service"
    r"|restart-service|disable-netadapter|reg(?:\.exe)?\s+(?:add|delete|import|load|unload))(?![\w-])",
    re.IGNORECASE,
)

_WS = re.compile(r"\s+")

_LIVENESS = "liveness probe: os.kill(pid, 0) sends no signal on Python 3.14 (probed on an owned child), it only checks the pid"

# (file, "call:<name>" | "str:<token>", scope) -> why this site is safe where it is.
_SITES = {
    ("agents/_supervisor_common.py", "call:kill", "_pid_alive"): _LIVENESS,
    ("dashboard/routes_moon_sync.py", "call:kill", "_pid_alive"): _LIVENESS,
    ("ops/loop/slots.py", "call:kill", "pid_alive"): _LIVENESS + " (byte-pinned shared file, SHARED_SHA256)",
    ("ops/launcher/service_host.py", "call:kill", "pid_alive"): _LIVENESS,
    ("core/daemon_slayer_client.py", "str:schtasks", "_schtasks"):
        "the one schtasks spawn helper; callers pass /Run or /Query only, never /Create /Delete /Change",
    ("core/daemon_slayer_client.py", "str:schtasks", "spawn_ds"):
        "argv names the existing RC-DaemonSlayer task for /Run and /Query; creates or changes nothing",
    ("core/daemon_slayer_client.py", "str:schtasks", "spawn_ds_task_only"):
        "argv names the existing RC-DaemonSlayer task for /Run; creates or changes nothing",
    ("dashboard/_vision_watchdog.py", "str:taskkill", "kill_pid"):
        "taskkill /F /PID of one pid, taken only after its argv is checked to be a vision server",
    ("dashboard/routes_loop_monitor.py", "str:schtasks", "module"):
        "a substring in a _KEYWORDS bucket tuple that labels a logged tool use; executes nothing",
    ("dashboard/routes_loop_monitor.py", "str:taskkill", "module"):
        "a substring in a _KEYWORDS bucket tuple that labels a logged tool use; executes nothing",
    ("game_reader/poller.py", "str:wmic", "_PollerMixin._ensure_lcu"):
        "read-only `wmic process get commandline` fallback to find the LCU port after the lockfile route fails",
    ("ops/launcher/service_host.py", "call:TerminateJobObject", "WinJob.terminate"):
        "ends the service host's OWN job object; the PKG launcher owns every member it started",
    ("ops/launcher/service_host.py", "call:TerminateProcess", "terminate_job_listener"):
        "ends a job-listener process the host itself started, by a handle it holds",
    ("ops/launcher/service_host.py", "call:kill", "ServiceHost._kill"):
        "kills a child Popen the host itself started and owns",
    ("ops/launcher/service_host.py", "call:terminate", "ServiceHost._request_restart"):
        "terminates an owned child Popen so the host can restart it",
    ("ops/launcher/service_host.py", "call:terminate", "ServiceHost._stop_owned"):
        "terminates an owned child Popen on a stop; never a process found by name or image",
    ("ops/loop/interrupt.py", "str:taskkill", "_taskkill"):
        "taskkill /F /PID, no /T, of a pid named to the operator first; the killer is injected so tests never run it",
    ("ops/loop/lane_launcher.py", "str:taskkill", "_kill"):
        "taskkill /F /PID of a lane worker this launcher started and recorded",
    ("ops/loop/proc_tree.py", "call:TerminateJobObject", "KillJob.kill"):
        "ends only the members of the lane worker's OWN job object, which the caller created and assigned its worker to",
    ("ops/loop/proc_tree.py", "call:kill", "KillJob.close"):
        "close(kill=True) calls self.kill() on the owned job; kill=False first allows breakaway, else close ends only that job",
    ("ops/loop/proc_tree.py", "call:kill", "kill_tree"):
        "os.kill SIGKILL off Windows, then job.kill() of the owned job, for the worker pid the caller spawned and holds",
    ("ops/loop/proc_tree.py", "str:taskkill", "_taskkill_exe"):
        "the System32 taskkill.exe path kill_tree runs as /F /T /PID of the worker the caller spawned (s158 C9)",
    ("ops/loop/queue_loop.py", "call:kill", "run_cycle"):
        "the injected `kill` callback (default _taskkill) ends the cycle worker this loop spawned, then verifies it",
    ("ops/loop/queue_loop.py", "str:taskkill", "_taskkill"):
        "taskkill /F /T /PID of the worker this loop spawned; /T because the worker has children",
    ("ops/loop/queue_loop.py", "str:taskkill", "main"):
        "operator-facing hint text naming the command to stop a running loop; executes nothing",
    ("ops/loop/queue_loop.py", "str:taskkill", "run_cycle"):
        "log text naming the budget-overrun kill; executes nothing",
    ("ops/rc_supervisor.py", "call:TerminateProcess", "_kill_pid"):
        "frozen supervisor: ends one stale pid it recorded (ASKS 24, never touched from a lane)",
    ("ops/rc_supervisor.py", "call:kill", "Supervisor.stop_app"):
        "frozen supervisor: kills the app Popen it owns after terminate times out",
    ("ops/rc_supervisor.py", "call:terminate", "Supervisor.stop_app"):
        "frozen supervisor: terminates the app Popen it owns",
    ("ops/rc_supervisor.py", "str:schtasks", "_Phase3Watcher._default_restarter"):
        "frozen supervisor: `schtasks /Run` of the existing Phase 3 task; creates or changes nothing",
    ("ops/rc_supervisor.py", "str:schtasks", "_Phase3Watcher.check"):
        "frozen supervisor: log text naming the /Run it performed; executes nothing",
    ("ops/rc_supervisor.py", "str:taskkill", "_Phase3Watcher._default_restarter"):
        "frozen supervisor: taskkill /F /PID of the stale Phase 3 pid it recorded",
    ("tools/build_portable.py", "str:register-scheduledtask", "module"):
        "a regex PATTERN the portable-build scanner uses to REFUSE a payload carrying a task; executes nothing",
    ("tools/build_portable.py", "str:schtasks", "module"):
        "regex patterns and an allow-list the portable-build scanner uses to REFUSE a payload carrying a task; executes nothing",
    ("tools/credential_history_scan.py", "call:kill", "_read_blobs"):
        "kills the `git cat-file --batch` child this scan started, in a finally",
    ("tools/inbox_responder_procs.py", "call:kill", "popen_capture"):
        "last-resort kill of the headless child this helper started, after the kill_tree sequence",
    ("tools/inbox_responder_procs.py", "call:killpg", "kill_tree"):
        "POSIX branch only: kills the process group of the child this helper started",
    ("tools/inbox_responder_procs.py", "str:taskkill", "kill_tree"):
        "taskkill /F /T /PID of the headless child tree this helper started",
    ("tools/landing_sampler.py", "call:kill", "PopenChild.stop"):
        "fallback Popen.kill on the held handle of the one gate child this sampler launched",
    ("tools/landing_sampler.py", "str:taskkill", "PopenChild.stop"):
        "taskkill /F /T /PID of the one gate child (and its pytest tree) this sampler launched, on a STOP",
    ("tools/landing_sampler.py", "str:taskkill", "kill_tree_argv"):
        "builds the taskkill /F /T /PID argv for that one launched child; runs nothing itself",
    ("tools/perseus_recall.py", "call:terminate", "recall"):
        "terminates the MCP server child this call started, in a finally",
    ("tools/perseus_sync.py", "call:terminate", "Vault.close"):
        "terminates the MCP server child this sync started, in close()",
    ("tools/replay_chain_watch.py", "str:enable-scheduledtask", "main"):
        "re-enables the one existing RC replay-chain task if it was Disabled; only when no ingest is running",
    ("tools/run_packaged_smoke.py", "call:kill", "check_launcher_from_unpacked"):
        "kills the launcher Popen the smoke started; its job object then ends the services (PKG tool)",
    ("vision_server/_reap.py", "call:kill", "_default_kill"):
        "psutil kill of one pid the caller chose after an argv check (the vision-server reaper)",
    ("vision_server/_reap.py", "call:kill", "reap_stale_vision_instances"):
        "kills the enumerated handle of a stale vision server instance, argv-checked first",
}


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _scan(source: str, call_names, str_re) -> list[tuple[str, int, str]]:
    """``("call:<name>" | "str:<token>", lineno, scope)`` per hit."""
    tree = ast.parse(source)
    docs = _docstring_ids(tree)
    hits: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = [*scope, child.name]
            where = ".".join(s) or "module"
            if isinstance(child, ast.Call):
                name = _call_name(child.func)
                if name in call_names:
                    hits.append((f"call:{name}", child.lineno, where))
            elif (isinstance(child, ast.Constant) and isinstance(child.value, str) and id(child) not in docs):
                for tok in str_re.findall(child.value):
                    token = _WS.sub(" ", tok.lower())
                    hits.append((f"str:{token}", child.lineno, where))
            visit(child, s)

    visit(tree, [])
    return sorted(hits, key=lambda h: (h[1], h[0]))


def _production_files():
    out = []
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        base = rel.rsplit("/", 1)[-1]
        if rel.startswith(_SKIP_PREFIXES) or "/tests/" in rel or base.startswith("test_") or base == "conftest.py":
            continue
        out.append(p)
    return out


def _census(call_names, str_re) -> set[tuple[str, str, str]]:
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    found: set[tuple[str, str, str]] = set()
    for p in files:
        try:
            hits = _scan(p.read_text(encoding="utf-8"), call_names, str_re)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = relative_posix(p)
        found.update((rel, name, scope) for name, _line, scope in hits)
    return found


def test_every_production_kill_and_task_reference_is_a_named_site():
    found = _census(_KILL_NAMES, _CENSUS_RE)
    assert len(found) >= 20, "the walk saw almost no site, so an empty difference proves nothing"
    new = sorted(found - set(_SITES))
    gone = sorted(set(_SITES) - found)
    assert not new, f"new kill / scheduled-task site (add it to _SITES with a reason): {new}"
    assert not gone, f"stale _SITES entry (drop it): {gone}"


def test_every_site_carries_a_reason():
    assert all(len(why) > 20 for why in _SITES.values())


def test_no_stop_process_outside_prose():
    """CLAUDE.md hard rule: never Stop-Process (it hangs the MCP pipe). Docstrings and comments may name it."""
    assert not [k for k in _SITES if k[1] == "str:stop-process"]
    assert not [k for k in _census(frozenset(), _CENSUS_RE) if k[1] == "str:stop-process"]


def test_registry_writes_and_system_config_tools_stay_at_zero():
    found = _census(_ZERO_CALL_NAMES, _ZERO_RE)
    assert not found, f"a registry write or system-configuration tool in production code (halt boundary): {sorted(found)}"


def test_the_census_detector_flags_each_shape():
    cases = {
        "def f(p):\n    p.kill()\n": [("call:kill", 2, "f")],
        "import os\nos.kill(1, 0)\n": [("call:kill", 2, "module")],
        "class C:\n    def m(self, k):\n        k.TerminateProcess(h, 1)\n": [("call:TerminateProcess", 3, "C.m")],
        "import os\nos.killpg(1, 9)\n": [("call:killpg", 2, "module")],
        "def f():\n    run(['taskkill', '/F', '/PID', '1'])\n": [("str:taskkill", 2, "f")],
        "def f(t):\n    ps(f'Enable-ScheduledTask -TaskName {t}')\n": [("str:enable-scheduledtask", 2, "f")],
        "def f():\n    ps('Enable-ScheduledTask -TaskName X')\n": [("str:enable-scheduledtask", 2, "f")],
        "X = ('pytest', 'schtasks', 'git')\n": [("str:schtasks", 1, "module")],
    }
    for src, want in cases.items():
        assert _scan(src, _KILL_NAMES, _CENSUS_RE) == want, src


def test_the_census_detector_ignores_prose_and_unrelated_names():
    clean = (
        '"""taskkill /F and schtasks /Run in a module docstring."""\n'
        "def f():\n"
        '    """Never Stop-Process; use taskkill."""\n'
        "    # taskkill in a comment\n"
        "    killed = 1\n"
        "    return killed\n"
        "def kill_switch():\n    return 2\n"
        "x = 'a taskkill-like word'\n"
        "y = 'xschtasks'\n"
    )
    assert _scan(clean, _KILL_NAMES, _CENSUS_RE) == []


def test_the_zero_detector_flags_each_shape():
    cases = {
        "import winreg\ndef f(k):\n    winreg.SetValueEx(k, 'a', 0, 1, 'v')\n": [("call:SetValueEx", 3, "f")],
        "import winreg\nwinreg.CreateKey(winreg.HKEY_CURRENT_USER, 'X')\n": [("call:CreateKey", 2, "module")],
        "def f():\n    run(['reg', 'add'])\n    run('reg add HKCU\\\\X')\n": [("str:reg add", 3, "f")],
        "def f():\n    run(['setx', 'A', 'b'])\n": [("str:setx", 2, "f")],
        "def f():\n    ps('netsh advfirewall set')\n": [("str:netsh", 2, "f")],
    }
    for src, want in cases.items():
        assert _scan(src, _ZERO_CALL_NAMES, _ZERO_RE) == want, src


def test_the_zero_detector_does_not_flag_registry_reads():
    reads = (
        "import winreg\n"
        "def f():\n"
        "    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:\n"
        "        return winreg.QueryValueEx(k, 'PATH')\n"
    )
    assert _scan(reads, _ZERO_CALL_NAMES, _ZERO_RE) == []
