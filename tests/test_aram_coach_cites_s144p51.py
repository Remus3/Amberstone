"""RM-1295 (fifth family, closes the row) - the last aram_coach line cites
name the symbol, not the line.

Three cites were left after the first four families:

  coaches/aram_coach.py, the Coach._run_vision feature-policy note:
      "is_allowed (core/feature_policy.py:305-350)"    written by 649c35d4d
  coaches/aram_coach.py, the item-interaction note in Coach._run_coach (a
      self-cite): "the _USER_TMPL fill site, coaches/aram_coach.py:839"
                                                        written by 179721af8
  tests/test_aram_vision_cadence_fastpoll.py docstring (a cite INTO
      aram_coach.py, not a self-cite):
      "`_VISION_INTERVAL` = 25.0s (coaches/aram_coach.py:552)"
                                                        written by b34b99b53

What they meant:

  core/feature_policy.py:305-350 -> exactly the span of def is_allowed at
      649c35d4d (that commit did not touch core/feature_policy.py)
  aram_coach.py:839 -> the `enemies` field of the _USER_TMPL.format call in
      Coach._run_coach, which reads state["enemy_comp"], at 179721af8^ (the
      commit itself added 57 lines above it, so the cite was already stale
      when it landed)
  aram_coach.py:552 -> the class attribute Coach._VISION_INTERVAL = 25.0 at
      b34b99b53^ (the commit added two lines above it)

At HEAD all three are stale (is_allowed is ~32 lines lower, the fill site
~300, the interval ~86). The prose now names core.feature_policy.is_allowed,
the _USER_TMPL.format fill in Coach._run_coach, and Coach._VISION_INTERVAL.

This guard pins:

(a) no `feature_policy.py:<n>` and no `aram_coach.py:<n>` line cite in
    coaches/aram_coach.py or tests/test_aram_vision_cadence_fastpoll.py;
(b) each rewritten note names its symbols;
(c) the named symbols still say what the prose says: is_allowed is a
    module-level function that calls _check_reload, Coach._run_coach fills
    _USER_TMPL with `enemies` from state["enemy_comp"], and
    Coach._VISION_INTERVAL is still 25.0;
(d) at the writing tree each old cite landed inside the symbol named for it
    (a commit absent from the clone FAILS: tests/test_ci_checkout_history_depth.py
    keeps these on full clones, and a shallow skip would hide on every CI run).

Other cite families in aram_coach.py (BACKLOG.md, web/js item_build.js and
items_index.js) are not RM-1295 and are out of scope on purpose.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

ARAM = "coaches/aram_coach.py"
FASTPOLL = "tests/test_aram_vision_cadence_fastpoll.py"
POLICY = "core/feature_policy.py"

BANNED = re.compile(r"(?:feature_policy|aram_coach)\.py:\d")

# (citing file, anchor text that opens the note, symbols the note must name)
NOTES = (
    (ARAM, "is total by construction",
     ("core.feature_policy.is_allowed", "_check_reload")),
    (ARAM, "enemy roster source",
     ("_USER_TMPL.format", "Coach._run_coach", "enemies")),
    (FASTPOLL, "polls\nvision every",
     ("coaches/aram_coach.py Coach._VISION_INTERVAL",)),
)

# (module, writing tree, old first line, old last line, class or None, symbol,
#  text on the first line or None)
OLD_CITES = (
    (POLICY, "649c35d4d", 305, 350, None, "is_allowed", "def is_allowed("),
    (ARAM, "179721af8^", 839, 839, "Coach", "_run_coach",
     'enemies     = ", ".join(state.get("enemy_comp", []))'),
    (ARAM, "b34b99b53^", 552, 552, "Coach", "_VISION_INTERVAL",
     "_VISION_INTERVAL    = 25.0"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _note(src: str, anchor: str) -> str:
    """The whitespace-collapsed paragraph that starts on the anchor's line:
    a comment run ends at the first non-comment line, a docstring paragraph
    at the first blank line."""
    i = src.find(anchor)
    assert i >= 0, f"note anchor {anchor!r} not found (RM-1295)"
    assert src.find(anchor, i + 1) < 0, f"anchor {anchor!r} is not unique"
    lines = src[src.rfind("\n", 0, i) + 1:].splitlines()
    comment = lines[0].lstrip().startswith("#")
    rows = []
    for line in lines:
        text = line.strip()
        if not text or (comment and not text.startswith("#")):
            break
        rows.append(text.lstrip("#").strip())
    return " ".join(" ".join(rows).split())


def _symbol(src: str, cls: str | None, name: str) -> ast.AST:
    body = ast.parse(src).body
    if cls is not None:
        owner = [n for n in body if isinstance(n, ast.ClassDef) and n.name == cls]
        assert owner, f"class {cls} not found (RM-1295)"
        body = owner[0].body
    for node in body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name):
            return node
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node
    raise AssertionError(f"{name} not found - the aram note names it "
                         "(RM-1295)")


def _have(rev: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"],
                           cwd=ROOT, capture_output=True, check=False)
    return probe.returncode == 0


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


@pytest.mark.parametrize("rel", [ARAM, FASTPOLL])
def test_no_line_cite_into_policy_or_aram(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{rel} cites core/feature_policy.py or coaches/aram_coach.py by line "
        f"again; cite the symbol (RM-1295): {hits}")


@pytest.mark.parametrize(("rel", "anchor", "names"), NOTES,
                         ids=["policy-note", "fill-site-note", "fastpoll-doc"])
def test_note_names_its_symbols(rel, anchor, names):
    note = _note(_src(rel), anchor)
    missing = [n for n in names if n not in note]
    assert not missing, f"{rel} note {anchor!r} no longer names {missing}: {note!r}"


def test_is_allowed_still_reloads():
    src = _src(POLICY)
    seg = ast.get_source_segment(src, _symbol(src, None, "is_allowed"))
    assert "_check_reload()" in seg, (
        f"{POLICY} is_allowed no longer calls _check_reload; the aram "
        "Coach._run_vision note relies on it (RM-1295)")


def test_run_coach_still_fills_enemies_from_enemy_comp():
    src = _src(ARAM)
    fn = _symbol(src, "Coach", "_run_coach")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "format"
             and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "_USER_TMPL"]
    assert len(calls) == 1, f"expected one _USER_TMPL.format in _run_coach, got {len(calls)}"
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "enemies" in kw, "_USER_TMPL.format no longer fills enemies"
    assert '"enemy_comp"' in ast.get_source_segment(src, kw["enemies"]), (
        "the enemies field no longer reads state['enemy_comp'] (RM-1295)")


def test_vision_interval_still_25s():
    node = _symbol(_src(ARAM), "Coach", "_VISION_INTERVAL")
    assert isinstance(node.value, ast.Constant) and node.value.value == 25.0, (
        "Coach._VISION_INTERVAL is no longer 25.0; the fast-poll docstring "
        "states 25.0s (RM-1295)")


def test_banned_pattern_still_bites():
    for sample in ("(core/feature_policy.py:305-350)", "aram_coach.py:839",
                   "(coaches/aram_coach.py:552)"):
        assert BANNED.search(sample), sample
    for other in ("core.feature_policy.is_allowed", "Coach._run_coach",
                  "coaches/aram_coach.py Coach._VISION_INTERVAL",
                  "core/feature_policy.py _DEFAULT_OFF_FEATURES",
                  "BACKLOG.md:59"):
        assert not BANNED.search(other), other


@pytest.mark.parametrize(("rel", "rev", "lo", "hi", "cls", "name", "text"),
                         OLD_CITES,
                         ids=[f"{r.rsplit('/', 1)[-1]}:{lo}"
                              for r, _, lo, _, _, _, _ in OLD_CITES])
def test_old_cite_meant_the_named_symbol(rel, rev, lo, hi, cls, name, text):
    assert _have(rev), f"{rev} absent from this clone"
    src = _git_show(f"{rev}:{rel}")
    node = _symbol(src, cls, name)
    assert node.lineno <= lo <= hi <= node.end_lineno, (
        f"{rel}:{lo}-{hi} at {rev} is outside {name} "
        f"({node.lineno}-{node.end_lineno})")
    if lo != hi:
        assert (node.lineno, node.end_lineno) == (lo, hi), (
            f"{rel}:{lo}-{hi} at {rev} is not exactly {name}")
    assert text in src.splitlines()[lo - 1], (
        f"{rel}:{lo} at {rev} does not carry {text!r}")
