"""RM-1282: the RC main process scrubs DS engine logs even when the
dashboard fails to import.

RM-1280 installs ``core.log_scrub.ScrubFilter`` on every engine logger
from ``agents/daemon_slayer/server.py`` (:8860) and ``dashboard/__init__.py``
(:8888). In the RC main process the dashboard installer runs only through
``main.py``'s ``from web_dashboard import start_dashboard``, and that import
sits inside a ``try`` that only logs a warning on failure. Measured
2026-10-31: ``import coach_integration`` (main.py, module scope, NOT in a
try) loads the engine on its own - ``coach_integration/_sr_prompt.py``
imports ``core.cc_blended_ehp_context``, which imports
``agents.daemon_slayer.cc_pressure``, and the SR prompt builder calls those
context lines at runtime - yet installed no filter. So with the dashboard
import failing, engine records in the main process were raw: a newline
forged a log line and a 100k exception text was one 100k line.

Fix: ``coach_integration/__init__.py`` installs the same filter on every
name in ``agents/daemon_slayer/_log_names.py``. It already depends on core
(``core.anthropic_key``), so the engine stays core-free. The install is
idempotent, so the normal boot (dashboard plus coach_integration) attaches
one filter per logger, not two. main.py and app/_loop.py are frozen, so a
non-frozen package main.py imports unconditionally is the site.
Reverses if: main.py stops importing coach_integration unconditionally at
module scope (then the backstop needs a new site).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from tests.test_ds_engine_logger_scrub_s144d58 import _CTRL, _KNOWN, _PROBE

ROOT = Path(__file__).resolve().parent.parent
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Block the dashboard installer the way a failed import would, then run the
# D-58 probe with coach_integration as the only installer.
_DEGRADED = r"""
import sys
sys.modules["web_dashboard"] = None
sys.modules["dashboard"] = None
sys.modules["agents.daemon_slayer.server"] = None
try:
    import web_dashboard  # noqa: F401
except ImportError:
    pass
else:
    raise SystemExit("web_dashboard import was not blocked")
"""


def _degraded_probe() -> dict:
    code = _DEGRADED + _PROBE.replace(
        "print(json.dumps(out))",
        "out['__engine_loaded__'] = 'agents.daemon_slayer.cc_pressure' "
        "in sys.modules\nprint(json.dumps(out))")
    names = sorted(_KNOWN)
    proc = subprocess.run(
        [sys.executable, "-c", code, "coach_integration", json.dumps(names)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        encoding="utf-8", creationflags=_NO_WINDOW)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_OUT: dict = {}


def _out() -> dict:
    if not _OUT:
        _OUT.update(_degraded_probe())
    return _OUT


def test_coach_integration_alone_loads_the_engine():
    """The reason this site needs the backstop at all."""
    assert _out()["__engine_loaded__"] is True


def test_every_engine_logger_is_filtered_without_the_dashboard():
    out = {k: v for k, v in _out().items() if not k.startswith("__")}
    assert sorted(out) == sorted(_KNOWN)
    missing = sorted(n for n, r in out.items() if not r["filtered"])
    assert missing == [], missing


def test_a_record_cannot_forge_a_line_without_the_dashboard():
    out = {k: v for k, v in _out().items() if not k.startswith("__")}
    for name, r in out.items():
        msg, tb = r["texts"]
        assert "\n" not in msg and not ({*msg} & _CTRL), (name, repr(msg))
        assert "FORGED-LINE" in msg
        lines = tb.split("\n")
        assert any(line.startswith("Traceback") for line in lines), name
        assert not any(line.lstrip().startswith("FORGED") for line in lines)
        assert max(len(line) for line in lines) <= 4096 + 40, name


_COUNT = r"""
import json, logging
import dashboard, coach_integration  # noqa: F401
from core.log_scrub import ScrubFilter
from agents.daemon_slayer._log_names import LOGGER_NAMES
print(json.dumps({n: sum(isinstance(f, ScrubFilter)
                         for f in logging.getLogger(n).filters)
                  for n in LOGGER_NAMES}))
"""


def test_the_normal_boot_attaches_one_filter_per_logger():
    proc = subprocess.run([sys.executable, "-c", _COUNT], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=180,
                          creationflags=_NO_WINDOW)
    assert proc.returncode == 0, proc.stderr[-4000:]
    counts = json.loads(proc.stdout.strip().splitlines()[-1])
    assert counts and set(counts.values()) == {1}, counts


def test_main_imports_coach_integration_unconditionally_before_main():
    """Module scope, top level (not in a try / if / def), before def main."""
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    tops = [n.lineno for n in tree.body if isinstance(n, ast.Import)
            and any(a.name == "coach_integration" for a in n.names)]
    defs = [n.lineno for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert tops, "main.py no longer imports coach_integration at top level"
    assert len(defs) == 1 and min(tops) < defs[0], (tops, defs)


def test_the_installer_is_at_package_module_scope():
    tree = ast.parse((ROOT / "coach_integration" / "__init__.py")
                     .read_text(encoding="utf-8"))
    calls = [n for n in tree.body if isinstance(n, ast.Expr)
             and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name)
             and n.value.func.id == "_install_scrub_filter"]
    froms = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)}
    assert "core.log_scrub" in froms, froms
    assert "agents.daemon_slayer._log_names" in froms, froms
    assert calls, "no module-scope install call in coach_integration"
