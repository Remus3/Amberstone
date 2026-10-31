"""RM-1247 remainder - the spawn-chain fake rationale cites by symbol.

RM-801 (20fb4d9ed) scoped every process fake to the spawn chain's OWN
`subprocess` names and explained, in four test docstrings, which call in
each chain module the fake has to reach. It cited every call by line:

  tests/test_kit_v10_spawn_routes.py         (the _bind_chain docstring)
  tests/test_headless_route_spawn_paths.py   (the _chain docstring)
  tests/test_fleet_route.py                  (the _bind_chain docstring)
  tests/test_supervisor_ephemeral_auth_env.py (the _spawn_run docstring)

What the cites meant, in the tree they were written against (20fb4d9ed):

  `ops/loop/executor.py:945/977 git`         -> _git_out / _git_is_ancestor
  `tools/ci_watchdog.py:459`                 -> ci_watchdog _run
  `ops/loop/drain_waves_2_3.py:180`          -> drain_waves_2_3 _git
  `ops/fleet_kit/fleet_headless.py:1734 Popen` -> the kit's _run
  `git :1613` / `taskkill :1703 run`         -> the kit's _git / _kill_tree

At HEAD (lane/repo, 2026-10-31) every one of the seven has drifted onto other
code (an executor docstring, a ci_watchdog fr.spawn call, a blank line in
drain_waves_2_3, a kit CLAUDE.md read). Each cite now names its symbol. The
kit is cited, never edited (FLEET-COMMON item 11). This guard pins:

(a) no line cite of those modules, and no bare `git :<n>` / `Popen :<n>` /
    `taskkill :<n>` / `:<n>/<n>` cite, in the four citer files;
(b) every named symbol still exists and still makes the subprocess call the
    rationale says it makes;
(c) each citer names its symbols in a COMMENT or STRING token, so a code
    reference to the same name cannot satisfy the check.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXECUTOR = "ops/loop/executor.py"
CI_WATCHDOG = "tools/ci_watchdog.py"
DRAIN = "ops/loop/drain_waves_2_3.py"
KIT = "ops/fleet_kit/fleet_headless.py"
KIT_V10_TEST = "tests/test_kit_v10_spawn_routes.py"
ROUTE_PATHS_TEST = "tests/test_headless_route_spawn_paths.py"
FLEET_ROUTE_TEST = "tests/test_fleet_route.py"
SUP_AUTH_TEST = "tests/test_supervisor_ephemeral_auth_env.py"

_KIT_NAMES = ("fleet_headless.py _run", "_git", "_kill_tree")

# Each citer and the symbol phrases its rationale must carry (in prose).
CITERS = {
    KIT_V10_TEST: ("_git_out", "_git_is_ancestor", *_KIT_NAMES),
    ROUTE_PATHS_TEST: ("_git_out", "_git_is_ancestor", "ci_watchdog.py _run",
                       "drain_waves_2_3.py _git", *_KIT_NAMES),
    FLEET_ROUTE_TEST: _KIT_NAMES,
    SUP_AUTH_TEST: ("fleet_headless.py _git",),
}

BANNED = (
    re.compile(r"\b(?:executor|ci_watchdog|drain_waves_2_3|fleet_headless)"
               r"\.py:\d"),
    re.compile(r"\b(?:git|Popen|taskkill|probe)\s+:\d"),
    re.compile(r":\d{2,4}/\d{2,4}\b"),
)

# (module, function, the call its body must make)
HOLDS = (
    (EXECUTOR, "_git_out", 'subprocess.run(["git"'),
    (EXECUTOR, "_git_is_ancestor", '"merge-base", "--is-ancestor"'),
    (CI_WATCHDOG, "_run", "subprocess.run("),
    (DRAIN, "_git", 'subprocess.run(["git"'),
    (KIT, "_run", "subprocess.Popen("),
    (KIT, "_git", '"--no-replace-objects"'),
    (KIT, "_kill_tree", '"/T", "/F", "/PID"'),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    """Every COMMENT and STRING token of a .py file, joined."""
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _func(rel: str, name: str) -> str:
    """Top-level def `name` only: a nested helper of the same name is not it."""
    src = _src(rel)
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{rel}: def {name} not found - the rationale names it")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            for pat in BANNED if pat.search(line)]
    assert not hits, (
        f"{rel} cites the spawn-chain subprocess calls by line again; cite "
        f"the symbol (RM-1247): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = _prose(rel)
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the rationale no longer names {missing} in a comment or "
        "docstring (RM-1247)")


@pytest.mark.parametrize(("rel", "name", "call"), HOLDS,
                         ids=[f"{r}:{n}" for r, n, _ in HOLDS])
def test_named_symbol_makes_the_call(rel, name, call):
    body = _func(rel, name)
    assert "subprocess." in body and call in body, (
        f"{rel} {name} no longer makes the subprocess call the RM-801 "
        f"rationale names ({call!r}); re-word the citer docstrings")


def test_banned_patterns_still_bite():
    """Anti-vacuity: each BANNED pattern matches a cite of the shape it bans."""
    samples = ("ops/loop/executor.py:945", "its git probe :1613",
               "executor.py:945/977 git")
    for sample, pat in zip(samples, BANNED, strict=True):
        assert pat.search(sample), (sample, pat.pattern)
