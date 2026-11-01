"""RM-1295 (first family) - the polled_json resolver cites by symbol.

Two files explained the lane 8 cycle 24 read_json_dict fix (W1: a
non-UTF-8 file raised UnicodeDecodeError) and the cycle 22 scratch-name
fix by pointing at the sites that had compensated, by line:

  core/polled_json.py                      (_scratch_path docstring,
                                            read_json_dict W1 comment)
  tests/test_polled_json_lane8_cycle24.py  (module docstring, W1)

What the cites meant, in the tree they were written against (8bf931e29^,
the parent of the cycle 24 commit that wrote them):

  core/cost_tracker.py:490     -> CostTracker.note_match_boundary, its
                                  "Narrowed 2026-07-19" raise-surface comment
  coaches/_base_coach.py:502   -> BaseCoach._vision_loop, the LEFT BROAD
                                  comment on the gate_disabled("vision") gate
  coaches/_base_coach.py:539   -> BaseCoach._maybe_coach, the LEFT BROAD
                                  comment on the allow_call() budget gate
  coaches/sr_user_builds.py:513 -> _save, its "W6: a per-writer scratch
                                  name" comment

At HEAD each had drifted (note_match_boundary's comment by 13 lines, the
two coach gates by 12 and 13), and the sr_user_builds claim had gone
stale with it: _save no longer "carries this same fix" itself, because
RM-258 (7a45bb921) moved it onto core.polled_json.atomic_write_json.
This guard pins:

(a) no line cite into those three modules in the two citers;
(b) every named symbol still exists and still carries what the prose says;
(c) each citer names its symbols in a COMMENT or STRING token;
(d) at 8bf931e29^ every old cite landed inside the symbol named for it
    (skipped only when that commit is absent from the clone).

Other-family cites are out of scope on purpose. The compensating sites' own
cites into core/cost_tracker.py and core/polled_json.py are pinned by
tests/test_cost_tracker_compensating_cites_s144p52.py. The arena_coach /
aram_coach cites: their _base_coach.py family is pinned by
tests/test_base_coach_dclass_cites_s144p51.py, their coaching_timestamps.py /
augment_shadow.py family by tests/test_arena_coach_shadow_ts_cites_s144p51.py,
their vision_server/_inference.py family by
tests/test_inference_prompt_cites_s144p51.py.
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
WRITING_PARENT = "8bf931e29^"

_GATES = ("note_match_boundary", "_vision_loop", "_maybe_coach")

# Each citer and the symbol names its prose must carry.
CITERS = {
    "core/polled_json.py": _GATES + ("sr_user_builds", "_save"),
    "tests/test_polled_json_lane8_cycle24.py": _GATES,
}

BANNED = re.compile(
    r"\b(?:cost_tracker|_base_coach|sr_user_builds)\.py:\d"
    r"|(?:/|\band)\s+:\d")

# (file, qualified symbol, text its source must carry)
HOLDS = (
    ("core/cost_tracker.py", "CostTracker.note_match_boundary",
     "Narrowed 2026-07-19"),
    ("core/cost_tracker.py", "CostTracker.note_match_boundary",
     "UnicodeDecodeError"),
    ("coaches/_base_coach.py", "BaseCoach._vision_loop",
     'gate_disabled("vision")'),
    ("coaches/_base_coach.py", "BaseCoach._vision_loop",
     "UnicodeDecodeError"),
    ("coaches/_base_coach.py", "BaseCoach._maybe_coach", "allow_call()"),
    ("coaches/_base_coach.py", "BaseCoach._maybe_coach",
     "UnicodeDecodeError"),
    ("coaches/sr_user_builds.py", "_save", "atomic_write_json(_STORE_PATH"),
    ("core/polled_json.py", "read_json_dict", "except UnicodeDecodeError"),
)

# (file, old line, qualified symbol it sat in at 8bf931e29^, text on it)
OLD_CITES = (
    ("core/cost_tracker.py", 490, "CostTracker.note_match_boundary",
     "read_json_dict"),
    ("coaches/_base_coach.py", 502, "BaseCoach._vision_loop",
     "read_json_dict"),
    ("coaches/_base_coach.py", 539, "BaseCoach._maybe_coach",
     "read_json_dict"),
    ("coaches/sr_user_builds.py", 513, "_save", "per-writer scratch name"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _node(src: str, rel: str, qual: str) -> ast.AST:
    node: ast.AST = ast.parse(src)
    for part in qual.split("."):
        found = [c for c in ast.iter_child_nodes(node)
                 if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)) and c.name == part]
        if not found:
            raise AssertionError(f"{rel}: {qual} not found - the resolver "
                                 "prose names it (RM-1295)")
        node = found[0]
    return node


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def _have_parent() -> bool:
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{WRITING_PARENT}{{commit}}"],
        cwd=ROOT, capture_output=True)
    return probe.returncode == 0


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_resolver_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{rel} cites a compensating site by line again; cite the symbol "
        f"(RM-1295): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the resolver prose no longer names {missing} in a comment "
        "or docstring (RM-1295)")


@pytest.mark.parametrize(("rel", "qual", "text"), HOLDS,
                         ids=[f"{q}:{t[:20]}" for _, q, t in HOLDS])
def test_named_symbol_holds(rel, qual, text):
    src = _src(rel)
    seg = ast.get_source_segment(src, _node(src, rel, qual)) or ""
    assert text in seg, (
        f"{rel} {qual} no longer carries {text!r}; re-word the resolver "
        "prose that names it (RM-1295)")


def test_banned_pattern_still_bites():
    for sample in ("core/cost_tracker.py:490", "coaches/_base_coach.py:502",
                   "coaches/sr_user_builds.py:513", "x.py:502 / :539",
                   "x.py:502 and :539"):
        assert BANNED.search(sample), sample
    for other in ("core/cost_tracker.py", "coaches/_base_coach.py `_save`",
                  "body[:40]", "core/polled_json.py:139"):
        assert not BANNED.search(other), other


@pytest.mark.parametrize(("rel", "line", "qual", "text"), OLD_CITES,
                         ids=[f"{r.split('/')[-1]}:{n}" for r, n, _, _
                              in OLD_CITES])
def test_old_cite_meant_the_named_symbol(rel, line, qual, text):
    if not _have_parent():
        pytest.skip(f"{WRITING_PARENT} absent from this clone (shallow)")
    src = _git_show(f"{WRITING_PARENT}:{rel}")
    node = _node(src, rel, qual)
    assert node.lineno <= line <= node.end_lineno, (
        f"{rel}:{line} at {WRITING_PARENT} is outside {qual} "
        f"({node.lineno}-{node.end_lineno})")
    assert text in src.splitlines()[line - 1], (
        f"{rel}:{line} at {WRITING_PARENT} does not carry {text!r}")
