"""S144-P-334 - every production subprocess spawn names creationflags (no console flash).

CLAUDE.md "Windows": background daemons run under ``pythonw.exe`` and "every console-subsystem
child of a windowless parent needs ``creationflags=CREATE_NO_WINDOW``". The only guard so far,
tests/test_no_console_flash_scheduled_tools.py, pins a HAND-ENUMERATED list of unattended
spawners, so a new spawner in a runtime module is invisible to it by construction (its own
docstring records the list growing after exactly that miss). This census inverts it, the way the
RM-258 atomic-write guard does: EVERY tracked non-test ``.py`` is scanned.

Two zones:

- RUNTIME (everything except the operator-CLI trees below): zero tolerance. A ``subprocess``
  spawn here must pass ``creationflags=`` (any expression but a literal ``0`` / ``None``) or
  splat ``**kwargs`` (the guard cannot see inside, so it does not guess). Measured 2026-11-07
  over the git index (alias-aware AST): 39 unflagged spawns in 29 non-test files, every one of
  them in the operator-CLI trees; the runtime zone is clean. Three more spawns splat **kwargs
  and are trusted: tools/console_flash_control.py:80 and tools/ci_impact_selector.py:331 / :358
  (the last two splat ``_PATH_TEXT``, which carries only text / encoding / errors, so they are
  in truth unflagged CI-selector spawns: an operator-CLI file, left to a later step).
- OPERATOR CLI (``tools/``, ``scripts/``, ``ops/audit/``, ``ops/migrate/``): a developer runs
  these from a console, where a child inherits that console and nothing flashes. They are held
  in ``_BASELINE`` (file -> unflagged-spawn count), which only shrinks: a new file, or a file
  whose count rises, fails; an entry that stops offending fails until it is dropped. A tool that
  gains an unattended caller (a scheduled task, a watcher) belongs in
  tests/test_no_console_flash_scheduled_tools.py and converts here.

Stated limits: only ``subprocess.<fn>`` through the module or an import alias (``import
subprocess as sp``, ``from subprocess import run``) is seen; ``os.system``, ``os.popen`` and
``asyncio.create_subprocess_*`` are not covered (none exists in non-test code today, probed
2026-11-07), and a positional ``Popen`` creationflags (the 9th argument) is not read.``ops/fleet_kit/`` is the vendored kit
(byte-pinned, never edited here) and is not scanned.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_FUNCS = frozenset({"run", "check_output", "check_call", "call", "Popen"})
_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_CLI_TREES = ("tools/", "scripts/", "ops/audit/", "ops/migrate/")

# file -> number of spawns with no creationflags. Only shrinks.
_BASELINE = {
    "ops/audit/p0_inventory.py": 1,
    "ops/audit/p3c23_token_equiv.py": 2,
    "ops/audit/p3c24_token_equiv.py": 1,
    "scripts/install_hooks.py": 2,
    "scripts/precommit_pycompile.py": 1,
    "tools/ascii_escape_py.py": 1,
    "tools/build_installer.py": 1,
    "tools/build_python_embed.py": 1,
    "tools/bootstrap_env_check.py": 2,
    "tools/build_rank_baselines.py": 1,
    "tools/ci_impact_selector.py": 1,
    "tools/citation_audit.py": 1,
    "tools/dev_cli.py": 2,
    "tools/drift_guard.py": 2,
    "tools/ds_feed_index.py": 1,
    "tools/freeze_witness.py": 1,
    "tools/md_guard_selector.py": 1,
    "tools/p3_ascii_census.py": 1,
    "tools/package_portable.py": 1,
    "tools/repair_mojibake.py": 1,
    "tools/repo_insights.py": 1,
    "tools/rewrite_sha_citations.py": 1,
    "tools/run_packaged_smoke.py": 3,
    "tools/scheduled_boot_verify.py": 1,
    "tools/sibling_sweep_ci.py": 1,
    "tools/strip_em_dashes.py": 1,
    "tools/strip_smart_quotes.py": 1,
    "tools/timeline_ingest.py": 1,
    "tools/truth_gate.py": 4,
}


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(names bound to the subprocess module, bare names bound to a spawn function)."""
    mods: set[str] = set()
    funcs: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name == "subprocess")
        elif isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            funcs.update((a.asname or a.name) for a in n.names if a.name in _FUNCS)
    return mods, funcs


def _unflagged_spawns(source: str) -> int:
    """Count subprocess spawns with no usable creationflags in ``source``."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    count = 0
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        hit = (
            isinstance(f, ast.Attribute) and f.attr in _FUNCS
            and isinstance(f.value, ast.Name) and f.value.id in mods
        ) or (isinstance(f, ast.Name) and f.id in funcs)
        if not hit:
            continue
        flagged = False
        for kw in n.keywords:
            if kw.arg is None:  # **kwargs: trusted
                flagged = True
            elif kw.arg == "creationflags":
                v = kw.value
                flagged = not (isinstance(v, ast.Constant) and v.value in (0, None))
        if not flagged:
            count += 1
    return count


def _tree_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            n = _unflagged_spawns(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if n:
            out[rel] = n
    return out


def test_walk_is_not_vacuous():
    files = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert "core/polled_json.py" in files
    assert "tools/truth_gate.py" in files
    assert "ops/loop/done_sentinel.py" in files


def test_runtime_zone_has_no_unflagged_spawn():
    bad = {f: n for f, n in _tree_counts().items() if not f.startswith(_CLI_TREES)}
    assert not bad, (
        "a runtime module spawns a child with no creationflags= (a console flashes under "
        f"pythonw); pass CREATE_NO_WINDOW (platform-guarded) or splat **kwargs: {bad}")


def test_operator_cli_trees_only_shrink():
    counts = _tree_counts()
    grown = {f: n for f, n in counts.items() if n > _BASELINE.get(f, 0)}
    assert not grown, (
        "a new or grown unflagged spawn in an operator-CLI tree: pass creationflags= "
        f"(preferred) or justify it in _BASELINE: {grown}")


def test_baseline_is_exact():
    counts = _tree_counts()
    stale = sorted(f for f in _BASELINE if f not in counts)
    assert not stale, f"no longer offend - drop from _BASELINE: {stale}"
    assert counts.keys() >= _BASELINE.keys()
    lowered = {f: (n, counts[f]) for f, n in _BASELINE.items() if counts[f] < n}
    assert not lowered, f"count fell - lower the _BASELINE entry: {lowered}"
    assert all(f.startswith(_CLI_TREES) for f in _BASELINE)
    assert [f for f in _BASELINE if not (REPO_ROOT / f).is_file()] == []


def test_detector_sees_each_spawn_shape():
    assert _unflagged_spawns("import subprocess\nsubprocess.run(['git'])\n") == 1
    assert _unflagged_spawns("import subprocess as sp\nsp.Popen(['git'])\n") == 1
    assert _unflagged_spawns("from subprocess import check_output as co\nco(['git'])\n") == 1
    assert _unflagged_spawns("import subprocess\nsubprocess.call(['git'], creationflags=0)\n") == 1
    assert _unflagged_spawns(
        "import subprocess\nsubprocess.run(['git'], creationflags=None)\n") == 1
    # a different module's run() is not a subprocess spawn
    assert _unflagged_spawns("import asyncio\nasyncio.run(main())\n") == 0
    assert _unflagged_spawns("def run(x):\n    return x\nrun(1)\n") == 0


def test_detector_passes_the_flagged_shapes():
    assert _unflagged_spawns(
        "import subprocess\nsubprocess.run(['git'], creationflags=0x08000000)\n") == 0
    assert _unflagged_spawns(
        "import subprocess\nsubprocess.run(['git'], creationflags=NO_WINDOW)\n") == 0
    assert _unflagged_spawns(
        "import subprocess\nsubprocess.run(['git'], **kw)\n") == 0
    assert _unflagged_spawns(
        "from subprocess import Popen\nPopen(['git'], creationflags=_flags())\n") == 0
