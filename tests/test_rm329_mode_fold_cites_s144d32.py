"""Guard: the RM-329 S6 mode-fold prose cites by symbol and stays true (RM-1052).

Measured 2026-10-28 at ENGINE 1.290.0, in
``agents/daemon_slayer/tests/test_mode_provenance_notes_rm329.py``:

* Two comments cited ``burst.py:2032`` for the ``mode = canonical_mode(mode)``
  fold in ``rank_items_by_burst``. At the landing commit (416f369dd) that fold
  sat on :2033 and :2032 held its ``# RM-325: fold once at the public entry``
  comment, so the cite was one line off when written, and later inserts above
  it moved the fold further still.
* The S6 comment said ``canonical_mode`` "does not appear in hybrid.py,
  _rank_mage.py or onhit_dps.py at all". The same commit 416f369dd imported it
  into all three for their ``mode_filter_note(canonical_mode(mode))`` lines, so
  the parenthetical was false at landing. The behavioural claim it was meant to
  back - those three rankers never fold ``mode`` itself - is still true, and is
  what this guard pins (by AST, inside the named function, not by substring).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
RM329 = DS / "tests" / "test_mode_provenance_notes_rm329.py"

_LINE_CITE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*\.py:\d")

# (module, ranker) pairs the S6 comment describes.
_FOLDING = ("burst.py", "rank_items_by_burst")
_NON_FOLDING = (
    ("hybrid.py", "rank_items_by_hybrid"),
    ("_rank_mage.py", "rank_items_by_ability_dps"),
    ("onhit_dps.py", "rank_items_by_onhit"),
)


def _function(fname: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((DS / fname).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{fname}: def {name} not found")


def _is_canonical_mode_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "canonical_mode"
    )


def _folds_mode(fn: ast.FunctionDef) -> bool:
    """True when the body rebinds ``mode`` to a ``canonical_mode(...)`` call."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and _is_canonical_mode_call(node.value)
                and any(isinstance(t, ast.Name) and t.id == "mode" for t in node.targets)):
            return True
    return False


def _canonical_mode_calls_outside_note(fn: ast.FunctionDef) -> list[int]:
    """Lines of ``canonical_mode`` calls NOT nested in ``mode_filter_note(...)``."""
    inside = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "mode_filter_note"
        ):
            inside.update(id(a) for a in node.args if _is_canonical_mode_call(a))
    return [
        node.lineno
        for node in ast.walk(fn)
        if _is_canonical_mode_call(node) and id(node) not in inside
    ]


def test_pattern_matches_the_rotted_shape():
    for sample in ("at burst.py:2032,", "(burst.py:2032)", "_rank_mage.py:430"):
        assert _LINE_CITE.search(sample), sample
    for sample in ("burst.py", "burst.rank_items_by_burst", "onhit_dps.py at"):
        assert not _LINE_CITE.search(sample), sample


def test_rm329_has_no_line_number_cites():
    text = RM329.read_text(encoding="utf-8")
    hits = [
        f"{RM329.name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm329_drops_the_false_does_not_appear_claim():
    text = RM329.read_text(encoding="utf-8")
    assert "does not appear in hybrid.py" not in text, (
        "canonical_mode DOES appear in hybrid.py / _rank_mage.py / onhit_dps.py"
    )


def test_burst_ranker_folds_mode_in_its_own_body():
    assert _folds_mode(_function(*_FOLDING)), (
        "rank_items_by_burst no longer folds mode; the rm329 S6 prose is stale"
    )


def test_other_three_rankers_never_fold_mode():
    for fname, name in _NON_FOLDING:
        fn = _function(fname, name)
        assert not _folds_mode(fn), f"{fname} {name} now folds mode"
        assert not _canonical_mode_calls_outside_note(fn), (
            f"{fname} {name}: canonical_mode used outside mode_filter_note"
        )


def test_other_three_rankers_read_canonical_mode_for_the_note():
    for fname, name in _NON_FOLDING:
        src = ast.get_source_segment(
            (DS / fname).read_text(encoding="utf-8"), _function(fname, name)
        )
        assert "mode_filter_note(canonical_mode(mode))" in src, fname
