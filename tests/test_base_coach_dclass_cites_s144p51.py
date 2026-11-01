"""RM-1295 (second family) - the arena / aram coach cites into
coaches/_base_coach.py name the symbol, not the line.

Two coach modules and the aram fast-poll test explained a D-class handler
(a broad except the callees already make unreachable), a reset hook, the
vision cadence and the overlay default by pointing into
coaches/_base_coach.py by line:

  coaches/arena_coach.py  three D-class handlers in the augment reco persist
                          and _reconcile_augment_hud
  coaches/aram_coach.py   _reset_extra, _update_vision_cadence, the my_team
                          D-class handler and the ai_bar LEFT BROAD comment
  tests/test_aram_vision_cadence_fastpoll.py
                          the module docstring, _LOOP_SLEEP_S, _make_coach,
                          _simulate_scans and LatchLifecycleTests

What the cites meant, in the tree each was written against:

  at 7797264e2^ (parent of the silent no-op handler program, which wrote
  the D-class and LEFT BROAD comments):
    coaches/_base_coach.py:66-68   -> load_json, its except + return {}
    coaches/_base_coach.py:100-102 -> safe_write, its except + return
    coaches/_base_coach.py:297     -> BaseCoach.__init__, self._overlay = {}
  at 29d39c2fc5^ (that commit, the bounded fast vision poll, wrote the
  aram cadence comments and the fast-poll test and did not touch
  _base_coach.py):
    coaches/_base_coach.py:306     -> BaseCoach.__init__, self._last_vision
                                      = 0.0
    coaches/_base_coach.py:312     -> BaseCoach.__init__, its
                                      self._init_extra() call
    coaches/_base_coach.py:361     -> BaseCoach.reset_state, its
                                      self._reset_extra() call
    coaches/_base_coach.py:462     -> BaseCoach._vision_loop, its
                                      self._VISION_INTERVAL check
    coaches/_base_coach.py:491     -> BaseCoach._vision_loop, its
                                      asyncio.sleep(3.0)

At HEAD every one had drifted (load_json by 3 lines, safe_write by 16,
the __init__ lines by 36 to 40, reset_state by 36, the _vision_loop lines
by 36 to 37), and the safe_write claim "returns" had grown a value: it now
returns False after logging.

This guard pins:

(a) no _base_coach.py line cite, and no bare ":<n>-<n>" shorthand cite,
    in the three citers;
(b) every named symbol still exists and still carries what the prose says,
    and load_json / safe_write hold no raise statement;
(c) each citer names its symbols in a COMMENT or STRING token;
(d) at the writing parent every old cite landed inside the symbol named
    for it (skipped only when that commit is absent from the clone).

Other-family cites in the same three files are out of scope on purpose.
The arena_coach cites into core/coaching_timestamps.py and
core/augment_shadow.py are pinned by
tests/test_arena_coach_shadow_ts_cites_s144p51.py and the
vision_server/_inference.py cites by
tests/test_inference_prompt_cites_s144p51.py; still open:
core/feature_policy.py:305-350, and the
aram_coach.py self-cites :839 (in aram_coach.py) and :552 (in the fast-poll
test).
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASE = "coaches/_base_coach.py"
DCLASS_PARENT = "7797264e2^"
CADENCE_PARENT = "29d39c2fc5^"

# Each citer and the symbol names its prose must carry.
CITERS = {
    "coaches/arena_coach.py": ("load_json", "safe_write"),
    "coaches/aram_coach.py": ("load_json", "safe_write",
                              "BaseCoach.reset_state",
                              "BaseCoach._vision_loop",
                              "BaseCoach.__init__"),
    "tests/test_aram_vision_cadence_fastpoll.py": ("BaseCoach._vision_loop",
                                                   "BaseCoach.__init__",
                                                   "reset_state"),
}

# A _base_coach.py line cite, or a bare ":<n>-<n>" range shorthand that
# leans on the previous cite's file. A cite into another module keeps its
# own "<name>.py:" prefix, so the lookbehind leaves it alone.
BANNED = re.compile(r"\b_base_coach\.py:\d|(?<![\w\]]):\d+-\d+")

# (qualified symbol in coaches/_base_coach.py, text its source must carry;
# whitespace is collapsed on both sides before the compare)
HOLDS = (
    ("load_json", "except Exception"),
    ("load_json", "return {}"),
    ("safe_write", "NEVER RAISES"),
    ("safe_write", "except Exception"),
    ("safe_write", "return False"),
    ("BaseCoach.__init__", "self._overlay: dict = {}"),
    ("BaseCoach.__init__", "self._last_vision: float = 0.0"),
    ("BaseCoach.__init__", "self._init_extra()"),
    ("BaseCoach.reset_state", "self._reset_extra()"),
    ("BaseCoach._vision_loop", "self._VISION_INTERVAL"),
    ("BaseCoach._vision_loop", "asyncio.sleep(3.0)"),
)

# (writing parent, old line, qualified symbol it sat in, text on that line)
OLD_CITES = (
    (DCLASS_PARENT, 66, "load_json", "except Exception"),
    (DCLASS_PARENT, 68, "load_json", "return {}"),
    (DCLASS_PARENT, 100, "safe_write", "except Exception"),
    (DCLASS_PARENT, 102, "safe_write", "return"),
    (DCLASS_PARENT, 297, "BaseCoach.__init__", "self._overlay"),
    (CADENCE_PARENT, 306, "BaseCoach.__init__", "self._last_vision"),
    (CADENCE_PARENT, 312, "BaseCoach.__init__", "self._init_extra()"),
    (CADENCE_PARENT, 361, "BaseCoach.reset_state", "self._reset_extra()"),
    (CADENCE_PARENT, 462, "BaseCoach._vision_loop", "self._VISION_INTERVAL"),
    (CADENCE_PARENT, 491, "BaseCoach._vision_loop", "asyncio.sleep(3.0)"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _node(src: str, qual: str) -> ast.AST:
    node: ast.AST = ast.parse(src)
    for part in qual.split("."):
        found = [c for c in ast.iter_child_nodes(node)
                 if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)) and c.name == part]
        if not found:
            raise AssertionError(f"{BASE}: {qual} not found - the coach "
                                 "prose names it (RM-1295)")
        node = found[0]
    return node


def _have(rev: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", f"{rev}{{commit}}"],
                           cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_base_coach_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{rel} cites coaches/_base_coach.py by line again; cite the symbol "
        f"(RM-1295): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the coach prose no longer names {missing} in a comment or "
        "docstring (RM-1295)")


@pytest.mark.parametrize(("qual", "text"), HOLDS,
                         ids=[f"{q}:{t[:20]}" for q, t in HOLDS])
def test_named_symbol_holds(qual, text):
    src = _src(BASE)
    seg = ast.get_source_segment(src, _node(src, qual)) or ""
    assert " ".join(text.split()) in " ".join(seg.split()), (
        f"{BASE} {qual} no longer carries {text!r}; re-word the coach prose "
        "that names it (RM-1295)")


@pytest.mark.parametrize("qual", ("load_json", "safe_write"))
def test_swallowing_callee_has_no_raise(qual):
    # The D-class prose says no exception from these two can reach the
    # caller's handler; a raise statement in either body would make it wrong
    # even while the text checks above still match.
    src = _src(BASE)
    raises = [n.lineno for n in ast.walk(_node(src, qual))
              if isinstance(n, ast.Raise)]
    assert not raises, (
        f"{BASE} {qual} now raises (lines {raises}); the arena / aram D-class "
        "prose that relies on it swallowing must be re-checked (RM-1295)")


def test_banned_pattern_still_bites():
    for sample in ("coaches/_base_coach.py:66-68", "(_base_coach.py:361)",
                   "load_json -> {}, :100-102 safe_write",
                   "safe_write (:100-102) returns"):
        assert BANNED.search(sample), sample
    for other in ("core/coaching_timestamps.py:73-74",
                  "core/augment_shadow.py:112-113",
                  "vision_server/_inference.py:36", "(:8889 with",
                  "coaches/_base_coach.py load_json", "x[1:3]", "1:55-2:00"):
        assert not BANNED.search(other), other


@pytest.mark.parametrize(("rev", "line", "qual", "text"), OLD_CITES,
                         ids=[f"{r}:{n}" for r, n, _, _ in OLD_CITES])
def test_old_cite_meant_the_named_symbol(rev, line, qual, text):
    if not _have(rev):
        pytest.skip(f"{rev} absent from this clone (shallow)")
    src = _git_show(f"{rev}:{BASE}")
    node = _node(src, qual)
    assert node.lineno <= line <= node.end_lineno, (
        f"{BASE}:{line} at {rev} is outside {qual} "
        f"({node.lineno}-{node.end_lineno})")
    assert text in src.splitlines()[line - 1], (
        f"{BASE}:{line} at {rev} does not carry {text!r}")
