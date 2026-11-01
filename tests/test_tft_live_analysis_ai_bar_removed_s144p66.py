"""RM-1308 - the AI status bar notification chain in TftLiveAnalysis is gone.

Why it was removed (measured 2026-11-01, every tracked surface, docs/_archive
and the append-only history files excluded and then re-checked):

  - `TftAiStatusBar`, the only thing that `set_ai_bar()` was ever meant to
    receive, is defined nowhere in the repo (core/tft_worker.py dropped its
    `wire_ai_bar()` in the lane 8 s134 audit, pinned by
    tests/test_tft_worker_true_audit_s134.py::
    test_w6_dead_ai_bar_and_force_scan_api_is_gone).
  - `set_ai_bar` has no caller in app code, JS, PowerShell, JSON or docs; the
    only other hit is a no-op stub on a perf-probe fake
    (tools/run_phase2_perf.py `_FakeLive`), which is not a consumer.
  - So `_ai_bar` was permanently None: `_notify_scanning`, `_notify_done` and
    `_notify_next_scan` never did anything, and the `_next = ... 12.0` literal
    in `_loop` (a leftover of the removed mid-round scan) only fed them.

If you find yourself adding any of these back, first confirm a real consumer
(a defined status-bar class that is actually wired) exists.
"""
from __future__ import annotations

import ast
import inspect

from tft import tft_live_analysis as tla

REMOVED_METHODS = ("set_ai_bar", "_notify_scanning", "_notify_done",
                   "_notify_next_scan")


def _source() -> str:
    return inspect.getsource(tla)


def test_the_ai_bar_methods_are_gone():
    for name in REMOVED_METHODS:
        assert not hasattr(tla.TftLiveAnalysis, name), name


def test_no_ai_bar_name_is_read_or_written_in_the_module():
    """No attribute, name or call spells the dead chain any more (a comment
    explaining the removal is allowed; the AST ignores comments)."""
    tree = ast.parse(_source())
    spelled = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            spelled.add(node.attr)
        elif isinstance(node, ast.Name):
            spelled.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spelled.add(node.name)
    dead = spelled & (set(REMOVED_METHODS) | {"_ai_bar"})
    assert dead == set()


def test_the_module_is_still_the_one_that_owns_the_scan_loop():
    """Anchor: an empty / wrong module would pass the absence checks."""
    assert hasattr(tla.TftLiveAnalysis, "_loop")
    assert hasattr(tla.TftLiveAnalysis, "_run_cycle")
    assert hasattr(tla.TftLiveAnalysis, "force_scan")


def test_the_removed_mid_round_scan_cadence_literal_is_gone():
    """`_loop` once computed a next-scan time with a 12.0 s branch for the
    removed mid-round scan; with the notify chain gone that arithmetic has no
    reader."""
    assert "_scanned_planning else 12.0" not in _source()
