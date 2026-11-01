"""RM-1281: the RC main process needs no extra install site for the DS
engine's log-scrub backstop - pinned so it stays that way.

RM-1280 attaches ``core.log_scrub.ScrubFilter`` to every engine logger
from two installers, ``agents/daemon_slayer/server.py`` (:8860) and
``dashboard/__init__.py`` (:8888). Its verifier asked whether the RC main
process logs engine records before ``main.py`` imports ``web_dashboard``
(``core/damage_mix.py`` and ``core/focus_board_live.py`` import the engine
on their own). Measured 2026-10-31: no. A logger filter lives on the
logger OBJECT, so it applies to every record created after it is attached,
whichever module imported the engine first; ``main.py`` imports
``web_dashboard`` at module scope before ``def main`` (``web_dashboard``
imports the ``dashboard`` package at module scope, which installs the
filters); and none of the engine modules logs anything while it is being
imported. So the only unfiltered window is engine records emitted during
import, and there are none. This file pins all three facts.

Rejected alternative (recorded): installing from ``core/__init__.py`` (empty
today). It would make every ``import core.<x>`` in every process pull in
``logging``, ``http.server`` (and so ``socket``) and the engine package, a
package-wide side effect for a gap measured empty. Accepted residual:
standalone CLI runs (``tools/ds_*``, ``ops/audit/ds_*``,
``core/build_order_precompute.py``) that never import either installer log
engine records unfiltered to their own console; those records carry local
snapshot text, not request text. Reverses if: an engine module logs at
import time, or ``main.py`` stops importing ``web_dashboard`` at boot.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "agents" / "daemon_slayer"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _engine_modules() -> list[str]:
    """Every non-test engine module (the git index via tests/_repo_walk,
    ADR-015); ``__main__`` is the CLI entry point, not an import."""
    from tests._repo_walk import repo_files
    out = []
    for p in repo_files(PKG, ("*.py",)):
        rel = p.relative_to(ROOT).with_suffix("")
        if "tests" in rel.parts or rel.name == "__main__":
            continue
        parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
        out.append(".".join(parts))
    return out


def _run(code: str, *args: str) -> dict:
    proc = subprocess.run([sys.executable, "-c", code, *args],
                          cwd=str(ROOT), capture_output=True, text=True,
                          timeout=120, creationflags=_NO_WINDOW)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_IMPORT_PROBE = r'''
import importlib, json, logging, sys
recs = []

class Cap(logging.Handler):
    def emit(self, record):
        recs.append([record.name, record.levelname,
                     record.getMessage()[:200]])

root = logging.getLogger()
root.addHandler(Cap(level=logging.DEBUG))
root.setLevel(logging.DEBUG)
fails = []
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except Exception as exc:
        fails.append([name, type(exc).__name__, str(exc)[:200]])
during = list(recs)
logging.getLogger("agents.daemon_slayer.effects").warning("control")
print(json.dumps({"during": during, "fails": fails,
                  "control": recs[len(during):]}))
'''


def test_no_engine_module_logs_while_it_is_imported():
    mods = _engine_modules()
    # A floor: an empty or shrunken walk can never read as "nothing logs".
    assert len(mods) >= 100, len(mods)
    assert "agents.daemon_slayer.effects" in mods
    out = _run(_IMPORT_PROBE, json.dumps(mods))
    assert out["fails"] == [], out["fails"]
    # Positive control: the capture really sees an engine record.
    assert out["control"] == [["agents.daemon_slayer.effects", "WARNING",
                               "control"]], out["control"]
    assert out["during"] == [], out["during"]


def _module_scope(tree: ast.Module):
    """Statements that run at import: the module body, descending into
    if / try / with blocks but never into a def or a class body's defs."""
    todo = list(tree.body)
    while todo:
        node = todo.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda)):
            continue
        yield node
        for field in ("body", "orelse", "finalbody", "handlers"):
            todo.extend(getattr(node, field, None) or [])


def _imports(tree: ast.Module, module: str) -> list[int]:
    return [n.lineno for n in _module_scope(tree)
            if isinstance(n, ast.ImportFrom) and n.module
            and (n.module == module or n.module.startswith(module + "."))]


def test_main_imports_web_dashboard_at_boot_before_main():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    lines = _imports(tree, "web_dashboard")
    defs = [n.lineno for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert lines, "main.py no longer imports web_dashboard at module scope"
    assert len(defs) == 1, defs
    assert min(lines) < defs[0], (lines, defs)


def test_web_dashboard_imports_the_dashboard_package_at_module_scope():
    tree = ast.parse((ROOT / "web_dashboard.py").read_text(encoding="utf-8"))
    assert _imports(tree, "dashboard"), (
        "web_dashboard.py no longer imports the dashboard package at "
        "module scope, so the RM-1280 installer may never run in RC")


def test_the_scope_walker_is_not_vacuous():
    src = ("try:\n    from web_dashboard import x\nexcept Exception:\n"
           "    pass\ndef main():\n    from web_dashboard import y\n")
    tree = ast.parse(src)
    assert _imports(tree, "web_dashboard") == [2]
    assert _imports(ast.parse("def f():\n    from dashboard import a\n"),
                    "dashboard") == []


_ORDER_PROBE = r'''
import json, logging
import agents.daemon_slayer.effects
lg = logging.getLogger("agents.daemon_slayer.effects")
texts = []

class Cap(logging.Handler):
    def emit(self, record):
        texts.append(logging.Formatter("%(message)s").format(record))

lg.addHandler(Cap(level=logging.DEBUG))
lg.setLevel(logging.DEBUG)
lg.propagate = False
evil = "bad " + chr(0x1B) + "[31mX\r\nFORGED-LINE"
lg.warning("%s", evil)
before = texts.pop()
import dashboard  # the installer arrives AFTER the engine module
lg.warning("%s", evil)
print(json.dumps({"before": before, "after": texts.pop()}))
'''


def test_an_installer_imported_after_the_engine_still_scrubs():
    out = _run(_ORDER_PROBE)
    # Control: the same record is raw before any installer runs.
    assert chr(0x1B) in out["before"] and "\n" in out["before"], out
    assert chr(0x1B) not in out["after"], out
    assert "\r" not in out["after"] and "\n" not in out["after"], out
    assert "FORGED-LINE" in out["after"], out
