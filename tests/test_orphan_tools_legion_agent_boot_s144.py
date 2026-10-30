"""S144-P (RM-1116 (a)) drift guard: tools/legion_agent_boot.ps1 stays retired.

tools/legion_agent_boot.ps1 was the per-session copy-out launcher of the
Legion-local agents. It curled lcu_agent.py, liveclient_relay.py,
hotkey_listener.py and screen_agent.py from the dashboard's unauthenticated
/agent/ route into a fixed folder on the system drive and started the copies
from there. It was removed in session 144 because it was broken AND unowned:

  1. BROKEN. It copied no package (`$SUPPORT_SCRIPTS = @()`), but
     tools/lcu_agent.py imports `lcu.*` and tools/hotkey_listener.py imports
     `core.polled_json` at module top level, with no fallback. From a folder
     with no repo above it both copies die at import with ModuleNotFoundError
     (probed by the s144 research lane with `python -I`); hotkey_listener was
     launched with pythonw, so its death was silent.
  2. UNOWNED. Logon persistence and launch belong to the RC-LCUAgent,
     RC-LiveClientRelay and RC-HotkeyListener ONLOGON tasks, which run the
     IN-REPO tools/<agent>.py (ADR-011; read-only `schtasks /Query /XML`).
     No tracked .py / .ps1 / .bat / .json / .yml / .xml file launched it; its
     only consumer was its own `_AGENT_ALLOWED` entry in
     dashboard/routes_static.py, which served it. No Desktop or Startup
     shortcut targeted it at removal time, and the copy folder did not exist.

The whole file is recoverable from git history. The remaining guard below is
the class, not the instance: no tracked launcher under tools/ or ops/ may
fetch an /agent/-served .py that needs a repo package, because a copy of such
a file cannot import outside the checkout. If you find yourself adding the
boot script back, launch the in-repo files instead of copies.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "tools/legion_agent_boot.ps1"
_TOKEN = "legion_agent_boot"


def _agent_allowlist() -> set[str]:
    """String members of dashboard.routes_static._AGENT_ALLOWED, by AST."""
    src = (REPO_ROOT / "dashboard" / "routes_static.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_AGENT_ALLOWED"
                        for t in node.targets)):
            return {c.value for c in ast.walk(node.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    raise AssertionError("_AGENT_ALLOWED not found in dashboard/routes_static.py")


def _repo_packages() -> set[str]:
    """Top-level directories of the checkout that are importable packages."""
    return {p.name for p in REPO_ROOT.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()}


def _imports_repo_package(rel: str, packages: set[str]) -> bool:
    """True when the file imports any repo package (absolute imports only)."""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        if any(n.split(".")[0] in packages for n in names):
            return True
    return False


def test_legion_agent_boot_stays_deleted() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. Its copies of lcu_agent.py and "
        "hotkey_listener.py cannot import lcu/core outside the checkout, and "
        "the RC-* ONLOGON tasks own the launch. Launch the in-repo files."
    )


def test_agent_route_no_longer_serves_it() -> None:
    allowed = _agent_allowlist()
    # Anchor: a renamed or unparsed allowlist would pass the check vacuously.
    assert "liveclient_relay.py" in allowed, allowed
    assert "legion_agent_boot.ps1" not in allowed, allowed


def test_no_tracked_runnable_file_names_the_boot_script() -> None:
    """No runnable tracked file may fetch, run or schedule the boot script.

    Prose history (docs/, *.md) and tests/ are out of scope (this guard and
    the PKG bundle exclusion list name it); data/ and web/data/ are bulk game
    data, not callers. *.xml covers the tracked scheduled-task definitions.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.vbs", "*.sh",
                "*.json", "*.yml", "*.yaml", "*.toml", "*.cfg", "*.ini",
                "*.js", "*.mjs", "*.html", "*.xml", "*.lnk")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel:
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
    assert offenders == [], f"live references to the retired boot script: {offenders}"


def test_no_launcher_copies_out_an_agent_that_needs_the_repo() -> None:
    """A copy of a repo-importing agent cannot run outside the checkout.

    Every /agent/-served .py that imports a repo package is copy-hostile; no
    tracked .ps1 / .bat / .cmd under tools/ or ops/ may fetch one from the
    route (the shape the retired boot script used).
    """
    packages = _repo_packages()
    assert {"core", "lcu"} <= packages, packages
    served_py = sorted(n for n in _agent_allowlist() if n.endswith(".py"))
    hostile = {n for n in served_py
               if _imports_repo_package(f"tools/{n}", packages)}
    # Positive and negative controls: the two agents the boot script broke
    # import repo packages; phase_watcher.py is standalone by design (it is
    # served to a folder with no repo above it, see its installer).
    assert {"lcu_agent.py", "hotkey_listener.py"} <= hostile, hostile
    assert "phase_watcher.py" not in hostile, hostile
    # Deliberately coarse: a URL can be built from a variable base
    # ("$LegionAgentBase/x.py", tools/phase_watcher_install.ps1) or a
    # variable name ("/agent/$s", the retired boot script), so no regex over
    # the URL shape is sound. A launcher that mentions the /agent route at
    # all may not name a copy-hostile agent anywhere in its text.
    route = re.compile(r"/agent\b")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, ("*.ps1", "*.bat", "*.cmd")):
        rel = relative_posix(path)
        if not rel.startswith(("tools/", "ops/")):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if route.search(text):
            offenders.extend(f"{rel}: {h}" for h in sorted(hostile) if h in text)
    assert scanned > 20, f"walk saw only {scanned} launchers - the scan is broken"
    assert offenders == [], (
        f"launchers that copy out an agent needing the repo: {offenders}")


def test_hotkey_listener_deploy_recipe_points_at_the_task() -> None:
    """Its docstring no longer tells the operator to run a copy-out."""
    text = (REPO_ROOT / "tools" / "hotkey_listener.py").read_text(encoding="utf-8")
    assert "RC-Agent" not in text
    assert "/agent/hotkey_listener.py" not in text
    assert "RC-HotkeyListener" in text
