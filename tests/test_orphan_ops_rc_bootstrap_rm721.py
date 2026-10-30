"""RM-721 (e) dead-code drift guard: ops/rc_bootstrap.py stays deleted (s144 repo lane).

ops/rc_bootstrap.py was an import-time side-effect module from the initial
commit (2026-04-26, last touched 2026-06-24). Importing it spawned the
supervisor (`pythonw.exe ops/rc_supervisor.py --config ops/rc_config.json`)
and the self-healing watchdog (`powershell.exe -File
ops/run_self_healing_watchdog.ps1`) when a process scan did not find them.
It was removed in session 144 because it was dead on two independent facts:

  1. ZERO callers. No tracked .py / .ps1 / .bat / .cmd / .json / .yml /
     .js / .html / .xml file names it outside dated history (docs/,
     BACKLOG.md) and the decorative atlas.html DUST label list, which names
     basenames as particles and never imports or runs anything (it also
     still lists other removed files). It has no `__main__` block, so no
     scheduled task or launcher can run it, and a read-only scheduled-task
     query at removal time named it nowhere.
  2. Its ONE intended trigger is closed. Its docstring said "when
     hot-reloaded into the running app". The only runtime import-by-name
     path, ops/rc_dev_runtime.py `_reload_modules`, is fed solely by the
     `reload_modules` / `reload_safe_modules` commands, and both filter the
     requested names through the `SAFE_RELOAD_MODULES` allowlist, which never
     held `ops.rc_bootstrap`. Its job is owned by the RC-Supervisor
     scheduled task.

It also shipped in the portable bundle (tools/build_portable.py
`exclusion_reason` returned None for it), so removing it drops a module that
spawned processes on import from the bundle. The whole file is recoverable
from git history.

Same shape as tests/test_orphan_scripts_parse_external_arena_s144.py and
tests/test_orphan_ops_commands_json_rm721.py. If you find yourself adding it
back, first confirm a real caller exists.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "ops/rc_bootstrap.py"
_TOKEN = "rc_bootstrap"

# atlas.html: its DUST string is a decorative list of basenames rendered as
# particles; it imports and runs nothing (tests/test_atlas_dust.py checks
# only its internal shape, never that a named file exists).
_DECORATIVE = frozenset({"atlas.html"})


def test_rc_bootstrap_stays_deleted() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. It spawned the supervisor and the watchdog "
        "on import, had no caller, and no hot-reload path may import it. "
        "Confirm a real caller before restoring it."
    )


def test_no_tracked_runnable_file_names_rc_bootstrap() -> None:
    """No runnable tracked file may import, run or schedule the module.

    Prose history (docs/, *.md) and tests/ (this guard names the file) are
    out of scope; data/ and web/data/ are bulk game data, not callers.
    *.xml covers the tracked scheduled-task definitions.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.vbs", "*.sh",
                "*.json", "*.yml", "*.yaml", "*.toml", "*.cfg", "*.ini",
                "*.js", "*.mjs", "*.html", "*.xml")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel or rel in _DECORATIVE:
            continue
        scanned += 1
        raw = path.read_bytes()
        # The tracked scheduled-task XMLs are UTF-16; decode them as such so
        # a reference inside one is not missed.
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        if _TOKEN in text:
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the deleted module: {offenders}"


def _safe_reload_modules() -> set[str]:
    """String members of the SAFE_RELOAD_MODULES literal, read by AST."""
    src = (REPO_ROOT / "ops" / "rc_dev_runtime.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SAFE_RELOAD_MODULES"
                        for t in node.targets)):
            return {
                c.value for c in ast.walk(node.value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            }
    return set()


def test_hot_reload_allowlist_cannot_import_it() -> None:
    """The one import-by-name runtime path stays closed to ops modules."""
    allowed = _safe_reload_modules()
    # Anchor: an unparsed or renamed allowlist would pass the check below
    # vacuously. core.theme has been a member since the initial commit.
    assert "core.theme" in allowed, f"SAFE_RELOAD_MODULES not found: {allowed}"
    assert not any(_TOKEN in m for m in allowed), allowed
