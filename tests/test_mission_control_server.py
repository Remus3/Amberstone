# arch: tests for the Mission Control standalone server | section=tests | frozen=no
"""Guards for the S10 decoupling.

The load-bearing one is test_loop_routes_do_not_import_dispatch: it is the
only thing standing between "Mission Control is a separate process" and
"Mission Control is a separate process that still dies with dashboard schema
code". It runs in a SUBPROCESS because an in-process check can be masked by
an earlier test having already imported pydantic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _import_probe(module: str, forbidden: list[str]) -> tuple[int, str]:
    """Import `module` in a clean interpreter; report any forbidden module
    that ended up in sys.modules. Returns (returncode, stdout+stderr)."""
    code = (
        f"import sys; import importlib; importlib.import_module({module!r}); "
        f"bad=[m for m in {forbidden!r} if m in sys.modules]; "
        "print('LEAKED:'+','.join(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_matchers_module_is_stdlib_only():
    """dashboard._matchers must not drag in pydantic or api_schema."""
    rc, out = _import_probe(
        "dashboard._matchers",
        ["pydantic", "dashboard.api_schema", "dashboard._dispatch"],
    )
    assert rc == 0, out


def test_loop_routes_do_not_import_dispatch():
    """Importing either loop route must not reach _dispatch/pydantic."""
    for mod in ("dashboard.routes_loop_status", "dashboard.routes_loop_control"):
        rc, out = _import_probe(
            mod, ["pydantic", "dashboard.api_schema", "dashboard._dispatch"]
        )
        assert rc == 0, f"{mod}: {out}"


def test_dispatch_still_exports_matchers():
    """40-plus route modules import equals/prefix from _dispatch. The
    re-export keeps them working, so this asserts identity, not equality."""
    from dashboard import _dispatch, _matchers
    assert _dispatch.equals is _matchers.equals
    assert _dispatch.prefix is _matchers.prefix
