"""RM-1657 - a browser module the docs-guards selection names can still be collected there.

tests/snapshot_panels/conftest.py imported playwright at collection, and the
docs-guards job does not install it. Run 42003344148 selected two modules from
that folder because they read a tracked doc, and the whole job died on the
conftest's ImportError, so no guard in the selection ran. A docs-only push must
still reach their doc assertions (tests/test_ci_docs_guard_coverage.py), so the
modules stay selected: the conftest imports playwright optionally, a test that asks
for the browser skips in that one job, and anywhere else a missing playwright stays
an error, so it can never turn the browser tests into a green skip.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tools.md_guard_selector import select_md_guard_modules

ROOT = Path(__file__).resolve().parent.parent
_BLOCK = ("import sys; sys.modules['playwright'] = None; "
          "sys.modules['playwright.sync_api'] = None; import pytest; ")
_DOC_TEST = ("tests/snapshot_panels/test_overlay_hotkey_hints.py"
             "::test_no_surface_promises_the_panel_cycle_key_reaches_a_panel")
_BROWSER_TEST = ("tests/snapshot_panels/test_overlay_hotkey_hints.py"
                 "::test_launcher_menu_lists_the_bindings")


def _no_browser_pytest(*args: str, job: str = "") -> subprocess.CompletedProcess:
    code = _BLOCK + f"raise SystemExit(pytest.main({list(args)!r}))"
    kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_JOB"}
    if job:
        env["GITHUB_JOB"] = job
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                          text=True, timeout=300, env=env, **kwargs)


_SUMMARY = re.compile(r"^=*\s*((?:\d+ [a-z]+, )*\d+ [a-z]+) in \d+(?:\.\d+)?s\b", re.MULTILINE)
_PLURAL = {"errors": "error", "warning": "warnings"}


def _outcomes(stdout: str) -> dict[str, int]:
    """Every count on the inner run's LAST summary line, the warnings count dropped.

    pytest prints "warnings" BETWEEN "passed" and "error", so a plugin that starts
    warning (RM-1974e: pytest 9.2 renamed CallSpec2 under anyio 4.13, and Python 3.14
    deprecated the AbstractEventLoopPolicy pytest-asyncio 1.3 imports) split the old
    "1 passed, 1 error" substring. Warnings are the only count left out: any other
    outcome, a skip or an xfail included, stays in the dict and fails the compare.
    """
    found = _SUMMARY.findall(stdout)
    if not found:
        return {}
    counts: dict[str, int] = {}
    for num, raw_label in re.findall(r"(\d+) ([a-z]+)", found[-1]):
        label = _PLURAL.get(raw_label, raw_label)
        counts[label] = counts.get(label, 0) + int(num)
    counts.pop("warnings", None)
    return counts


def _doc_ran_browser_skipped(stdout: str) -> bool:
    """The docs-guards job's verdict: exactly one doc test passed and one browser test
    skipped (RM-2034). Counts parsed from the last summary line, never a substring."""
    return _outcomes(stdout) == {"passed": 1, "skipped": 1}


def test_the_skip_verdict_reads_counts_not_a_substring():
    """RM-2034: "11 passed, 1 skipped" holds the substring "1 passed, 1 skipped"."""
    assert _doc_ran_browser_skipped("1 passed, 1 skipped in 2.10s")
    assert _doc_ran_browser_skipped("1 passed, 1 skipped, 3 warnings in 2.10s")
    assert not _doc_ran_browser_skipped("11 passed, 1 skipped in 2.10s")
    assert not _doc_ran_browser_skipped("1 passed, 1 skipped, 1 error in 2.10s")


def test_every_selected_browser_module_collects_without_playwright():
    browser = [p for p in select_md_guard_modules() if p.startswith("tests/snapshot_panels/")]
    assert browser, "no selected browser module: this guard has nothing left to read"
    proc = _no_browser_pytest("--collect-only", "-q", "-p", "no:cacheprovider", *browser,
                              job="md-guards")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]


def test_in_the_docs_guards_job_a_browser_test_skips_and_a_doc_test_still_runs():
    proc = _no_browser_pytest("-q", "-p", "no:cacheprovider", _DOC_TEST, _BROWSER_TEST,
                              job="md-guards")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1500:]
    assert _doc_ran_browser_skipped(proc.stdout), out[-1500:]


def test_anywhere_else_a_missing_playwright_is_an_error_not_a_green_skip():
    proc = _no_browser_pytest("-q", "-p", "no:cacheprovider", _DOC_TEST, _BROWSER_TEST)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out[-1500:]
    assert _outcomes(proc.stdout) == {"passed": 1, "error": 1}, out[-1500:]


def test_the_job_id_the_conftest_names_is_the_workflows():
    """The skip is keyed on GitHub's job id: a renamed job would turn it into an error."""
    workflow = (ROOT / ".github" / "workflows" / "docs-guards.yml").read_text(encoding="utf-8")
    assert "\n  md-guards:\n" in workflow
