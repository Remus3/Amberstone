"""RM-1295 (fourth family) - the arena / aram B-01b TIERED_FIELDS notes
cite the relay prompt and the arena consumer by symbol, not by line.

Both coaches declare `is_augment_select` in their tiered field list and
explain why in a "B-01b re-home" comment block. Both blocks were written by
dbfe693c7 and both cited by line:

  coaches/arena_coach.py   "(vision_server/_inference.py:36)" and
                           "the consumed `augment_select` at :606"
  coaches/aram_coach.py    "(vision_server/_inference.py:36)"

What they meant at dbfe693c7 (the writing commit; the cites name the tree
they were written into):

  vision_server/_inference.py:36 -> the `"is_augment_select":false` line of
      the _VISION_PROMPT string, the TFT prompt the relay answers every
      mode with
  :606 (a self-cite into coaches/arena_coach.py) -> Coach._run_vision, the
      `state.get("augment_select")` gate that consumes the aliased flag

At HEAD both are stale: _inference.py:36 is one line past the key (an
import line was added above the prompt), and arena_coach.py:606 is no longer in _run_vision
(the gate is ~19 lines lower). aram_coach.py already names
`vision_server/_inference.py _VISION_PROMPT` further down; the B-01b blocks
now do the same.

This guard pins:

(a) no `_inference.py:<n>` line cite in either coach;
(b) each B-01b block carries no `:<n>` line cite and names its symbols
    (_VISION_PROMPT, modes/shared_vision._postprocess, and for arena
    Coach._run_vision);
(c) the named symbols still say what the prose says: _VISION_PROMPT is a
    module-level string that emits `"is_augment_select"`, _postprocess
    aliases it into `augment_select`, and arena Coach._run_vision gates on
    `state.get("augment_select")`;
(d) at dbfe693c7 each old cite landed on the text named for it inside the
    symbol named for it (a commit absent from the clone FAILS:
    tests/test_ci_checkout_history_depth.py keeps these on full clones, and a
    shallow skip would hide on every CI run).

Out of scope on purpose: the last three RM-1295 cites (core/feature_policy.py
is_allowed and the two into aram_coach.py itself) are pinned by
tests/test_aram_coach_cites_s144p51.py.
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
WRITING = "dbfe693c7"

ARENA = "coaches/arena_coach.py"
ARAM = "coaches/aram_coach.py"
INFERENCE = "vision_server/_inference.py"
SHARED = "modes/shared_vision.py"

BANNED_INFERENCE = re.compile(r"_inference\.py:\d")
LINE_CITE = re.compile(r"(?:\.py)?:\d+\b")

# (citer, symbols its B-01b block must name)
BLOCKS = (
    (ARENA, ("vision_server/_inference.py _VISION_PROMPT",
             "modes/shared_vision._postprocess", "Coach._run_vision")),
    (ARAM, ("vision_server/_inference.py _VISION_PROMPT",
            "modes/shared_vision._postprocess")),
)

# (module, old line at WRITING, class or None, symbol, text on that line)
OLD_CITES = (
    (INFERENCE, 36, None, "_VISION_PROMPT", '"is_augment_select":false'),
    (ARENA, 606, "Coach", "_run_vision", 'state.get("augment_select")'),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _b01b_block(src: str) -> str:
    """The whitespace-collapsed comment run that starts with 'B-01b re-home'."""
    rows: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            rows[tok.start[0]] = tok.string.lstrip("#")
    starts = [r for r, t in rows.items() if "B-01b re-home" in t]
    assert len(starts) == 1, f"expected one B-01b re-home block, got {starts}"
    row, parts = starts[0], []
    while row in rows:
        parts.append(rows[row])
        row += 1
    return " ".join(" ".join(parts).split())


def _symbol(src: str, cls: str | None, name: str) -> ast.AST:
    body = ast.parse(src).body
    if cls is not None:
        owner = [n for n in body if isinstance(n, ast.ClassDef) and n.name == cls]
        assert owner, f"class {cls} not found (RM-1295)"
        body = owner[0].body
    for node in body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node
    raise AssertionError(f"{name} not found - the B-01b prose names it "
                         "(RM-1295)")


def _have(rev: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"],
                           cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


@pytest.mark.parametrize("rel", (ARENA, ARAM))
def test_no_inference_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED_INFERENCE.search(line)]
    assert not hits, (
        f"{rel} cites vision_server/_inference.py by line again; cite "
        f"_VISION_PROMPT (RM-1295): {hits}")


@pytest.mark.parametrize(("rel", "names"), BLOCKS,
                         ids=[r.rsplit("/", 1)[-1] for r, _ in BLOCKS])
def test_b01b_block_cites_by_symbol(rel, names):
    block = _b01b_block(_src(rel))
    cites = LINE_CITE.findall(block)
    assert not cites, f"{rel} B-01b block carries line cites {cites} (RM-1295)"
    missing = [n for n in names if n not in block]
    assert not missing, f"{rel} B-01b block no longer names {missing} (RM-1295)"


def test_vision_prompt_still_emits_the_flag():
    node = _symbol(_src(INFERENCE), None, "_VISION_PROMPT")
    assert isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
    assert '"is_augment_select":' in node.value.value, (
        f"{INFERENCE} _VISION_PROMPT no longer emits is_augment_select; the "
        "arena / aram B-01b prose that relies on it must be re-checked")


def test_postprocess_still_aliases_the_flag():
    seg = ast.get_source_segment(
        _src(SHARED), _symbol_any(_src(SHARED), "_postprocess"))
    assert 'd["augment_select"] = d["is_augment_select"]' in seg, (
        f"{SHARED} _postprocess no longer aliases is_augment_select")


def test_arena_run_vision_still_gates_on_the_flag():
    src = _src(ARENA)
    seg = ast.get_source_segment(src, _symbol(src, "Coach", "_run_vision"))
    assert 'state.get("augment_select")' in seg, (
        f"{ARENA} Coach._run_vision no longer gates on augment_select; the "
        "B-01b prose names it as the consumer (RM-1295)")


def _symbol_any(src: str, name: str) -> ast.FunctionDef:
    hits = [n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(hits) == 1, f"expected one {name}, got {len(hits)}"
    return hits[0]


def test_banned_patterns_still_bite():
    for sample in ("(vision_server/_inference.py:36)", "_inference.py:142"):
        assert BANNED_INFERENCE.search(sample), sample
    for sample in ("at :606, so", "(aram_coach.py:614)"):
        assert LINE_CITE.search(sample), sample
    for other in ("vision_server/_inference.py _VISION_PROMPT",
                  "modes/shared_vision._postprocess", "Coach._run_vision",
                  "RM-868", "2026-07-12"):
        assert not BANNED_INFERENCE.search(other), other
        assert not LINE_CITE.search(other), other


@pytest.mark.parametrize(("rel", "line", "cls", "name", "text"), OLD_CITES,
                         ids=[f"{r.rsplit('/', 1)[-1]}:{n}"
                              for r, n, _, _, _ in OLD_CITES])
def test_old_cite_meant_the_named_symbol(rel, line, cls, name, text):
    assert _have(WRITING), f"{WRITING} absent from this clone"
    src = _git_show(f"{WRITING}:{rel}")
    node = _symbol(src, cls, name)
    assert node.lineno <= line <= node.end_lineno, (
        f"{rel}:{line} at {WRITING} is outside {name} "
        f"({node.lineno}-{node.end_lineno})")
    assert text in src.splitlines()[line - 1], (
        f"{rel}:{line} at {WRITING} does not carry {text!r}")
