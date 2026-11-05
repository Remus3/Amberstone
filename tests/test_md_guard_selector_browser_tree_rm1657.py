"""RM-1657 - a browser module the docs-guards selection names can still be collected there.

tests/snapshot_panels/conftest.py imported playwright at collection, and the
docs-guards job does not install it. Run 42003344148 selected two modules from
that folder because they read a tracked doc, and the whole job died on the
conftest's ImportError, so no guard in the selection ran. A docs-only push must
still reach their doc assertions (tests/test_ci_docs_guard_coverage.py), so the
modules stay selected: the conftest imports playwright optionally, and only a test
that asks for the browser skips.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.md_guard_selector import select_md_guard_modules

ROOT = Path(__file__).resolve().parent.parent
_BLOCK = ("import sys; sys.modules['playwright'] = None; "
          "sys.modules['playwright.sync_api'] = None; import pytest; ")


def _no_browser_pytest(*args: str) -> subprocess.CompletedProcess:
    code = _BLOCK + f"raise SystemExit(pytest.main({list(args)!r}))"
    kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                          text=True, timeout=300, **kwargs)


def test_every_selected_browser_module_collects_without_playwright():
    browser = [p for p in select_md_guard_modules() if p.startswith("tests/snapshot_panels/")]
    assert browser, "no selected browser module: this guard has nothing left to read"
    proc = _no_browser_pytest("--collect-only", "-q", "-p", "no:cacheprovider", *browser)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]


def test_a_test_that_asks_for_the_browser_skips_and_a_doc_test_still_runs():
    proc = _no_browser_pytest(
        "-q", "-p", "no:cacheprovider", "-rs",
        "tests/snapshot_panels/test_overlay_hotkey_hints.py"
        "::test_no_surface_promises_the_panel_cycle_key_reaches_a_panel",
        "tests/snapshot_panels/test_overlay_hotkey_hints.py"
        "::test_launcher_menu_lists_the_bindings")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1500:]
    assert "1 passed, 1 skipped" in out, out[-1500:]
