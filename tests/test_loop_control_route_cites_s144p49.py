"""RM-1248 part 1 - the loop-control route rationale cites by symbol.

Four files explained a behaviour of dashboard/routes_loop_control.py by
citing it by line:

  dashboard/_arm_confirm.py              (module docstring, WHAT IS GATED)
  ops/loop/steer.py                      (the polled_json bind comment)
  tests/test_arm_confirm_server_gate.py  (module docstring, idempotency seam
                                          comment, steer test docstring)
  docs/API.md                            (the arm-then-confirm 409 paragraph)

What the cites meant, in the tree each was written against (f9b4a07c1 for
_arm_confirm.py, the gate test and docs/API.md; 57b76141a for steer.py):

  `routes_loop_control.py:353-357`  -> the _steer docstring, "GUIDANCE, NOT
                                       A COMMAND"
  `routes_loop_control.py:415`      -> the _interrupt_preview docstring,
                                       "Kills nothing, writes nothing"
  `routes_loop_control.py:482-565`  -> _apply_idempotent, the replay table
  `routes_loop_control.py:363`      -> the `except ModuleNotFoundError` of
                                       _steer's steer-module import
  `routes_loop_control.py:671-680`  -> the 409 branch of route_action

The gate test's module docstring also carried a bare `(:482-565)` after
`routes_loop_control._apply_idempotent`. At HEAD (lane/repo, 2026-10-31) all
five had drifted: :353-357 and :363 now sit in _fire_lane, :415 in the _steer
docstring, :482-565 runs from _interrupt_preview into _apply_idempotent, and
:671-680 spans apply_action and _handle_arm. Each cite now names its symbol.
This guard pins:

(a) no `routes_loop_control.py:<n>` cite, and no route symbol cite
    trailed by a bare `(:<n>)` range, in the four citer files;
(b) every named symbol still exists and still says or does what the
    rationale says it does;
(c) each .py citer names its symbols in a COMMENT or STRING token, so a code
    reference to the same name cannot satisfy the check (the .md citer is
    all prose).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

ROUTE = "dashboard/routes_loop_control.py"

# Each citer and the symbol names its rationale must carry (in prose).
CITERS = {
    "dashboard/_arm_confirm.py": ("_steer", "_interrupt_preview"),
    "ops/loop/steer.py": ("_steer",),
    "tests/test_arm_confirm_server_gate.py": ("_apply_idempotent", "_steer"),
    # API.md already names route_action elsewhere, so pin the phrase.
    "docs/API.md": ("409 branch of `route_action`",),
}

BANNED = (
    re.compile(r"\broutes_loop_control\.py:\d"),
    # a symbol cite trailed by a bare line range, e.g.
    # `routes_loop_control._apply_idempotent` (`:482-565`)
    re.compile(r"\broutes_loop_control[.\w]*`?\s*\(`?:\d"),
)

# (function in ROUTE, the text its source must carry)
HOLDS = (
    ("_steer", "GUIDANCE, NOT A COMMAND"),
    ("_steer", "except ModuleNotFoundError"),
    ("_steer", "importlib.import_module(_STEER_MODULE)"),
    ("_interrupt_preview", "Kills nothing, writes nothing"),
    ("_apply_idempotent", 'payload["replayed"] = True'),
    ("route_action", "return 409,"),
    ("route_action", "this is a STATE conflict, not a"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    """Every COMMENT and STRING token of a .py file; a .md file whole."""
    if not rel.endswith(".py"):
        return _src(rel)
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _func(name: str) -> str:
    """Top-level def `name` in ROUTE: a nested helper of that name is not it."""
    src = _src(ROUTE)
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{ROUTE}: def {name} not found - the rationale "
                         "names it")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_route_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            for pat in BANNED if pat.search(line)]
    assert not hits, (
        f"{rel} cites dashboard/routes_loop_control.py by line again; cite "
        f"the symbol (RM-1248): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())  # a re-wrap must not matter
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the rationale no longer names {missing} in a comment, "
        "docstring or doc prose (RM-1248)")


@pytest.mark.parametrize(("name", "text"), HOLDS,
                         ids=[f"{n}:{t[:24]}" for n, t in HOLDS])
def test_named_symbol_holds(name, text):
    assert text in _func(name), (
        f"{ROUTE} {name} no longer carries {text!r}; re-word the citers "
        "that name it (RM-1248)")


def test_steer_catches_only_module_not_found_on_import():
    """ops/loop/steer.py re-raises an OSError as ModuleNotFoundError BECAUSE
    _steer's import handler catches only that; a widened handler makes the
    steer.py comment false."""
    body = _func("_steer")
    head = body.split("importlib.import_module(_STEER_MODULE)", 1)[1]
    handler = head.split("\n", 2)[1]
    assert handler.strip() == "except ModuleNotFoundError as exc:", handler


def test_banned_pattern_still_bites():
    """Anti-vacuity: each pattern matches the cite shapes it replaced."""
    samples = (("dashboard/routes_loop_control.py:353-357",
                "routes_loop_control.py:482-565", "routes_loop_control.py:415"),
               ("`dashboard/routes_loop_control._apply_idempotent` (`:482-565`)",))
    for pat, group in zip(BANNED, samples, strict=True):
        for sample in group:
            assert pat.search(sample), (sample, pat.pattern)
