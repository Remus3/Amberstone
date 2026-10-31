"""RM-1247 - the loop STOP-writer rationale cites by symbol, not by line.

The RM-250 atomic-write rationale (lane 8 cycles 21 and 48, commits 07cafc869
and 57b76141a) explains why the control-file writers need a bounded
PermissionError retry and a per-writer scratch name: STOP has two writers and
three pollers. It cited every writer and poller by line, in four files:

  ops/loop/loop_controller.py      (the polled_json comment, awrite docstring)
  ops/loop/adjudicator.py          (the polled_json bind comment, _atomic_write)
  dashboard/routes_loop_control.py (the _awrite docstring)
  tests/test_loop_control_sibling_writers_lane8_cycle48.py (module docstring
                                    and the absolute-path test docstring)

What the cites meant, in the tree each was written against:

  `STOP (:174)` / `awrite(:174)`       -> loop_controller stop()
  `loop_controller.py:772/786`         -> the STOP polls in wait_for / wait_gone
  `routes_loop_control.py:344,587`     -> the STOP writes in _queue_intent
                                          (halt_save) and apply_action (stop)
  `routes_loop_status.py:450`          -> build_loop_status
  `claude_gui_bridge.ahk:299`          -> the bridge main Loop FileExist(STOPF)
  `_writers.py:29-36`                  -> the atomic_write_json comment
  `loop_controller.py:594`             -> _supervisor() injecting awrite
  `loop_controller.py:41` / `:36`      -> the _ADJ_MODNAME bind by file path and
                                          the comment above it

At HEAD (lane/repo, 2026-10-31) the .ahk cite and loop_controller `:36` /
`:41` still hold; every other cite has drifted (onto other code, or for
routes_loop_status `:450` a blank line). Each cite now names its symbol, so
the three that still hold cannot drift either. This guard pins:

(a) no line cite of those modules (and no bare `(:<line>)` or `:<n>/:<n>`
    cite) in the four citer files;
(b) every symbol the rationale names still exists and still does what the
    rationale says it does (writes or polls STOP, injects awrite, binds the
    adjudicator by file path);
(c) each citer names its symbols in a COMMENT or STRING token, so a code
    reference to the same name cannot satisfy the check (the RM-1246 guard
    limit).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

LOOP_CONTROLLER = "ops/loop/loop_controller.py"
ADJUDICATOR = "ops/loop/adjudicator.py"
ROUTES_CONTROL = "dashboard/routes_loop_control.py"
ROUTES_STATUS = "dashboard/routes_loop_status.py"
BRIDGE_AHK = "ops/loop/claude_gui_bridge.ahk"
WRITERS = "dashboard/_writers.py"
SIBLING_TEST = "tests/test_loop_control_sibling_writers_lane8_cycle48.py"

# Each citer and the symbols its rationale must name (in prose, not code).
CITERS = {
    LOOP_CONTROLLER: ("stop()", "wait_for", "wait_gone", "FileExist(STOPF)",
                      "build_loop_status", "_queue_intent", "apply_action"),
    ADJUDICATOR: ("_ADJ_MODNAME", "_supervisor()"),
    ROUTES_CONTROL: ("wait_for", "wait_gone", "FileExist(STOPF)",
                     "build_loop_status", "atomic_write_json"),
    SIBLING_TEST: ("stop()", "wait_for", "wait_gone", "FileExist(STOPF)",
                   "build_loop_status", "_queue_intent", "apply_action",
                   "_ADJ_MODNAME"),
}

BANNED = (
    re.compile(r"\b(?:loop_controller|routes_loop_control|routes_loop_status"
               r"|_writers)\.py:\d"),
    re.compile(r"claude_gui_bridge\.ahk:\d"),
    re.compile(r"\(:\d+(?:[,/]:?\d+)*\)"),
    re.compile(r"(?<![\w.]):\d{2,4}/:?\d{2,4}\b"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    """Every COMMENT and STRING token of a .py file, joined."""
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _func(rel: str, name: str) -> str:
    src = _src(rel)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{rel}: def {name} not found - the rationale names it")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_line_cite(rel):
    # The `# arch:` header is skipped: its `(:8895)` is a port, not a line.
    # BANNED[2] would also hit any other parenthesised port in a citer file;
    # none exists today - name a port without the parentheses.
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if not line.startswith("# arch:")
            for pat in BANNED if pat.search(line)]
    assert not hits, (
        f"{rel} cites the STOP writers / pollers by line again; cite the "
        f"symbol (RM-1247): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = _prose(rel)
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the rationale no longer names {missing} in a comment or "
        "docstring (RM-1247)")


def test_loop_controller_stop_writer_and_pollers_hold():
    assert 'awrite(CTL / "STOP"' in _func(LOOP_CONTROLLER, "stop")
    for poller in ("wait_for", "wait_gone"):
        assert '(CTL / "STOP").exists()' in _func(LOOP_CONTROLLER, poller), poller


def test_loop_controller_supervisor_injects_awrite():
    body = _func(LOOP_CONTROLLER, "_supervisor")
    assert re.search(r"adjudicator\.Adjudicator\(\s*CFG,\s*CTL,\s*log,\s*awrite\b",
                     body), body


def test_loop_controller_binds_adjudicator_by_file_path():
    src = _src(LOOP_CONTROLLER)
    assert "loaded by absolute file path (launcher + tests)" in src
    assert re.search(r"spec_from_file_location\(\s*_ADJ_MODNAME,", src)


def test_dashboard_stop_writers_hold():
    for fn in ("_queue_intent", "apply_action"):
        assert '_awrite(CONTROL_DIR / "STOP"' in _func(ROUTES_CONTROL, fn), fn


def test_loop_status_reads_stop():
    assert '_read_text(CONTROL_DIR / "STOP")' in _func(ROUTES_STATUS,
                                                       "build_loop_status")


def test_bridge_main_loop_polls_stop():
    src = _src(BRIDGE_AHK)
    loop_at = src.find("\nLoop {")
    assert loop_at != -1, "claude_gui_bridge.ahk has no main `Loop {`"
    assert "if FileExist(STOPF)" in src[loop_at:loop_at + 400]


def test_writers_atomic_write_json_records_the_share_lock():
    assert "PermissionError (WinError 5)" in _func(WRITERS, "atomic_write_json")


def test_banned_patterns_still_bite():
    """Anti-vacuity: each BANNED pattern matches a cite of the shape it bans."""
    samples = ("loop_controller.py:772/786", "claude_gui_bridge.ahk:299",
               "STOP (:174)", "module at :772/:786 every 5 s")
    for sample, pat in zip(samples, BANNED):
        assert pat.search(sample), (sample, pat.pattern)
