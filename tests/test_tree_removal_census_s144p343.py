"""S144-P-343 - every production directory removal is a named, reasoned site; single-file unlinks may not grow.

``shutil.rmtree`` / ``os.rmdir`` / ``Path.rmdir`` / ``os.removedirs`` delete a whole tree (or a directory entry) with no
Recycle Bin and no undo; FLEET-COMMON item 9 says anything irreplaceable goes to the Recycle Bin, never a direct unlink,
and the lane halt boundary forbids a delete outside the repo. S144-P-338..342 pinned the other process-wide and
untrusted-input hazards; this is the delete half. Measured 2026-11-07 by AST over every tracked production ``.py``
(outside ``tests/``, ``docs/``, any ``/tests/`` directory and the vendored ``ops/fleet_kit/``): 21 tree-removal calls in
12 files, listed in ``_TREE_SITES`` with the scope they sit in and what makes the target safe to drop (a scratch dir this
module just made, a rolling copy of its own regenerable output, or a previous build of the same tool). The set is exact:
a new call fails until it is added with a reason, and a call that goes away must be dropped.

The single-file half is a ceiling, not a census: ``Path.unlink`` / ``os.remove`` / ``os.unlink`` appear in 43 production
files (95 calls, ``_UNLINK_CEILING``), nearly all cleaning up a tmp file the same function created or a lock the same
module owns, so naming each would be noise. A file may not gain one without lifting its number here, and a file that
loses one must lower it (the ratchet only shrinks, so a stale ceiling cannot hide a later addition).

Detector: a call whose function is an attribute named ``rmtree`` / ``rmdir`` / ``removedirs``, or a bare name that the
file's own imports resolve to ``shutil.rmtree`` / ``os.rmdir`` / ``os.removedirs``. Scope is ``"module"`` or the
enclosing function / class dotted qualname. Unlink detector: attribute ``unlink`` on anything, or ``os.remove`` /
``os.unlink`` resolved through the file's imports.

Named blind spots (measured absent from the tree 2026-11-07, so not a live gap): ``shutil.move`` / ``os.replace``
overwriting a directory, ``os.system("rmdir")`` and a ``subprocess`` ``del`` / ``rd`` / ``Remove-Item``,
the Windows handle-disposition delete in ops/launcher/first_run.py ``_win_delete_by_handle`` (a directory delete this
detector cannot see), non-call references such as ``addCleanup(shutil.rmtree, ...)`` (the
shell-string half is S144-P-316's unsafe-call census; an argv-form delete such as `powershell Remove-Item` is in neither, none exists in production today), ``tempfile.TemporaryDirectory`` cleanup (scoped by its own
``with``), ``Path.write_bytes`` truncation, and a file that fails to parse (skipped, as in the sibling censuses).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_TREE_ATTRS = frozenset({"rmtree", "rmdir", "removedirs"})
_TREE_DOTTED = frozenset({"shutil.rmtree", "os.rmdir", "os.removedirs"})
_UNLINK_DOTTED = frozenset({"os.remove", "os.unlink"})

# (file, scope, call) -> (number of calls, why dropping the target is safe).
_TREE_SITES = {
    ("core/highlight_reel.py", "build_reel", "rmtree"):
        (1, "the per-reel scratch dir (.reel-tmp-<pid>, made with exist_ok) for its clip segments, removed in the finally block"),
    ("core/highlight_reel.py", "build_reel", "rmdir"):
        (1, "rmdir only removes an EMPTY dir, and only one this call created (made_dir) after a failed reel"),
    ("ops/launcher/first_run.py", "ScratchFolder.close", "rmdir"):
        (1, "POSIX branch only: handle-relative rmdir of the one run folder this object created, identity-checked (st_dev, st_ino) first; rmdir refuses a non-empty dir (the Windows branch deletes by handle, a blind spot below)"),
    ("ops/launcher/updater.py", "_swap_into_place", "rmtree"):
        (1, "the superseded staged release, dropped only after the new one is in place; the swap rolls back before this line"),
    ("ops/launcher/updater.py", "stage", "rmtree"):
        (1, "the half-built `.partial` stage dir of this very call, removed when the stage fails; never the live `final` dir"),
    ("ops/rc_supervisor.py", "Supervisor._prune_old_backups", "rmtree"):
        (1, "frozen supervisor: rolling pre-deploy backup copies beyond the newest N (no retention >= 1 guard here, unlike the deploy module)"),
    ("ops/rc_transactional_deploy.py", "clear_pycache_for", "rmtree"):
        (1, "a `__pycache__` folder next to a just-deployed file: derived bytecode, rebuilt on the next import"),
    ("ops/rc_transactional_deploy.py", "prune_backups", "rmtree"):
        (1, "rolling deploy backups beyond backup_retention_count (>= 1 enforced, the in-flight rollback snapshot is newest)"),
    ("tools/backup_irreplaceable.py", "prune", "rmtree"):
        (1, "oldest COMPLETE snapshots beyond `keep` (never below 1); copies this tool made, the live data is not touched"),
    ("tools/build_installer.py", "build", "rmtree"):
        (1, "the build output dir, only after it was checked to be empty or a previous build of this tool"),
    ("tools/build_portable.py", "build", "rmtree"):
        (1, "PKG-owned: the portable output dir, only after it was checked to be a previous build of this tool"),
    ("tools/build_python_embed.py", "drop_certifi", "rmtree"):
        (1, "certifi inside the embeddable-Python site-packages this build is assembling; a build artifact, not a user dir"),
    ("tools/ddragon_mirror_refresh.py", "prune_stale_versions", "rmdir"):
        (1, "a version alias (symlink / junction) in the DDragon mirror: unlinks the link itself, leaves its target alone"),
    ("tools/ddragon_mirror_refresh.py", "prune_stale_versions", "rmtree"):
        (1, "an old semver-named mirror dir beyond `retain`; the mirror is re-fetchable from DDragon, `current` is always kept"),
    ("tools/inbox_responder_export.py", "_sweep_orphan_tmp", "rmtree"):
        (1, "`_TMP_PREFIX` export dirs older than the orphan age, left by a crashed export of this module"),
    ("tools/inbox_responder_export.py", "_prune", "rmtree"):
        (1, "old export dirs beyond KEEP_EXPORTS; the one being served (keep_final) is always kept, exports are regenerable"),
    ("tools/inbox_responder_export.py", "ensure_export", "rmtree"):
        (3, "this call's own tmp export dir, removed on the failure paths (the OSError path that finds `final` already present removes it and returns `final`)"),
    ("tools/run_packaged_smoke.py", "run", "rmtree"):
        (2, "PKG-owned: the smoke run's extraction tmp dir (made by this call), dropped unless --keep-temp"),
}

# file -> number of Path.unlink / os.remove / os.unlink calls. Lowered when a call goes; never raised silently.
_UNLINK_CEILING = {
    "agents/_supervisor_common.py": 2,
    "agents/_supervisor_ephemeral.py": 1,
    "agents/agent4_coach_mentor/ui_applier.py": 1,
    "agents/supervisor.py": 1,
    "coaches/experimental_builder.py": 2,
    "core/data_retention.py": 1,
    "core/highlight_reel.py": 1,
    "core/log_retention.py": 2,
    "core/log_rotation.py": 3,
    "core/log_setup.py": 1,
    "core/polled_json.py": 1,
    "core/rofl_archive.py": 1,
    "dashboard/routes_loop_control.py": 2,
    "ops/launcher/first_run.py": 3,
    "ops/launcher/service_host.py": 6,
    "ops/launcher/update_cycle.py": 2,
    "ops/launcher/updater.py": 1,
    "ops/loop/claude_stub.py": 1,
    "ops/loop/drain_waves_2_3.py": 2,
    "ops/loop/executor.py": 1,
    "ops/loop/inbox_tick.py": 2,
    "ops/loop/lane_launcher.py": 1,
    "ops/loop/loop_controller.py": 4,
    "ops/loop/slots.py": 3,
    "ops/rc_dev_runtime.py": 9,
    "ops/rc_self_monitor.py": 6,
    "ops/rc_supervisor.py": 8,
    "ops/rc_transactional_deploy.py": 6,
    "oss/win32_atomic_io/src/win32_atomic_io/_atomic.py": 1,
    "scripts/repair_tft_match_rows.py": 1,
    "tools/bootstrap_env_check.py": 1,
    "tools/build_python_embed.py": 1,
    "tools/dev_cli.py": 1,
    "tools/inbox_responder_runner.py": 5,
    "tools/lcu_push_watcher.py": 2,
    "tools/live_flip_watcher.py": 1,
    "tools/moon_sync_poller.py": 1,
    "tools/phase_watcher.py": 1,
    "tools/progress_watch.py": 2,
    "tools/repin_subagent_cli.py": 1,
    "tools/rofl_dedupe.py": 1,
    "tools/shadow_archive_split.py": 1,
    "tools/stop_claim_gate.py": 1,
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """local name -> the dotted module path it stands for, from this file's own imports."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    real = aliases.get(head, head)
    return f"{real}.{rest}" if rest else real


def _scan(source: str) -> tuple[list[tuple[str, str]], int]:
    """``([(scope, call)], unlink_count)`` for one module; scope is "module" or a function qualname."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    trees: list[tuple[str, str]] = []
    unlinks = 0

    def visit(node: ast.AST, scope: list[str]) -> None:
        nonlocal unlinks
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = [*scope, child.name]
            if isinstance(child, ast.Call):
                f = child.func
                dotted = _dotted(f)
                real = _resolve(dotted, aliases) if dotted else ""
                where = ".".join(s) or "module"
                if (isinstance(f, ast.Attribute) and f.attr in _TREE_ATTRS) or real in _TREE_DOTTED:
                    trees.append((where, real.rsplit(".", 1)[-1] if real in _TREE_DOTTED else f.attr))
                elif (isinstance(f, ast.Attribute) and f.attr == "unlink") or real in _UNLINK_DOTTED:
                    unlinks += 1
            visit(child, s)

    visit(tree, [])
    return sorted(trees), unlinks


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def _measure():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    tree_found: dict[tuple[str, str, str], int] = {}
    unlink_found: dict[str, int] = {}
    for p in files:
        rel = relative_posix(p)
        try:
            trees, unlinks = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for scope, call in trees:
            key = (rel, scope, call)
            tree_found[key] = tree_found.get(key, 0) + 1
        if unlinks:
            unlink_found[rel] = unlinks
    return tree_found, unlink_found


def test_every_production_tree_removal_is_a_named_site():
    found, _ = _measure()
    assert len(found) >= 5, "the walk saw almost no site, so an empty difference proves nothing"
    want = {k: n for k, (n, _why) in _TREE_SITES.items()}
    new = sorted(k for k in found if k not in want)
    gone = sorted(k for k in want if k not in found)
    changed = sorted((k, want[k], found[k]) for k in want if k in found and want[k] != found[k])
    assert not new, f"new rmtree / rmdir call (add it to _TREE_SITES with a reason, or use a tmp dir that cleans itself): {new}"
    assert not gone, f"stale _TREE_SITES entry (drop it): {gone}"
    assert not changed, f"call count moved (key, listed, found): {changed}"


def test_every_tree_site_carries_a_reason():
    assert all(n >= 1 and len(why) > 30 for n, why in _TREE_SITES.values())


def test_single_file_unlinks_never_grow_past_the_ceiling():
    _, found = _measure()
    assert len(found) >= 20, "the walk saw almost no unlink, so an empty difference proves nothing"
    grew = sorted((f, _UNLINK_CEILING.get(f, 0), n) for f, n in found.items() if n > _UNLINK_CEILING.get(f, 0))
    shrank = sorted((f, n, found.get(f, 0)) for f, n in _UNLINK_CEILING.items() if found.get(f, 0) < n)
    assert not grew, f"a file gained an unlink / os.remove (file, ceiling, found); lift the ceiling only with a reason: {grew}"
    assert not shrank, f"a file lost an unlink; lower its _UNLINK_CEILING (file, ceiling, found): {shrank}"


def test_the_detector_flags_each_shape():
    cases = {
        "import shutil\ndef f(p):\n    shutil.rmtree(p)\n": ([("f", "rmtree")], 0),
        "from shutil import rmtree as rt\nrt('x')\n": ([("module", "rmtree")], 0),
        "import os\nclass C:\n    def m(self):\n        os.rmdir('d')\n": ([("C.m", "rmdir")], 0),
        "from pathlib import Path\ndef f(p):\n    Path(p).rmdir()\n": ([("f", "rmdir")], 0),
        "import os as o\no.removedirs('a/b')\n": ([("module", "removedirs")], 0),
        "def f(p):\n    p.unlink()\n    p.unlink(missing_ok=True)\n": ([], 2),
        "import os\nos.remove('x')\nos.unlink('y')\n": ([], 2),
        "from os import remove\nremove('x')\n": ([], 1),
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_look_alikes():
    clean = (
        "import shutil, os\n"
        "shutil.copytree('a', 'b')\n"
        "os.replace('a', 'b')\n"
        "os.makedirs('d')\n"
        "x = 'shutil.rmtree'\n"
        "def rmtree_helper():\n    return 1\n"
        "d = {}\nd.pop('k')\nitems = []\nitems.remove(3)\n"
    )
    assert _scan(clean) == ([], 0)
