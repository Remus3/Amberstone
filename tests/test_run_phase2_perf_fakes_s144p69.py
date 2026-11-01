"""RM-1309 - the perf probe's fakes carry no stub for a method nobody calls.

tools/run_phase2_perf.py builds a TftWorker around `_FakeLive`. Two leftovers
of removed objects sat in it (measured 2026-11-01, every tracked .py):

  - `_FakeLive.set_ai_bar`: the AI status bar chain was removed from
    TftLiveAnalysis (tests/test_tft_live_analysis_ai_bar_removed_s144p66.py),
    and TftWorker has called nothing like it since the lane 8 s134 audit.
  - `_FakeProxy` (set_scanning / set_done / set_interval /
    notify_scan_scheduled): defined, instantiated nowhere. No other file names
    it either.

A fake is only worth its stubs while a real caller exists, so the guard ties
the fake to the worker: every method `_FakeLive` defines is a method
core/tft_worker.py really calls on its `live` object.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT

PROBE = REPO_ROOT / "tools" / "run_phase2_perf.py"
WORKER = REPO_ROOT / "core" / "tft_worker.py"


def _parse(path):
    return ast.parse(path.read_bytes().decode("utf-8"))


def _class_methods(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return None


def _live_calls_in_worker():
    """Method names the worker calls on a local named `live`."""
    out = set()
    for node in ast.walk(_parse(WORKER)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "live"):
            out.add(node.func.attr)
    return out


def test_the_unused_proxy_fake_is_gone():
    tree = _parse(PROBE)
    assert _class_methods(tree, "_FakeProxy") is None
    assert not re.search(rb"\b_FakeProxy\b", PROBE.read_bytes())


def test_the_fake_live_stubs_are_exactly_what_the_worker_calls():
    fake = _class_methods(_parse(PROBE), "_FakeLive")
    assert fake is not None, "_FakeLive anchor lost"
    called = _live_calls_in_worker()
    # Anchor: an empty call scan would make the subset check pass anyway.
    assert {"start", "shutdown", "notify_coach_state", "notify_round"} <= called
    assert "set_ai_bar" not in fake
    assert fake <= called, sorted(fake - called)
