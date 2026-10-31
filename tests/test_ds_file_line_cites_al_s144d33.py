"""Guard: the build-order coverage tool and its guard cite by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. tools/build_order_coverage.py and
tests/test_build_order_coverage_guard.py carried eight ``<file>.py:<n>``
cites, written 2026-07-30, and seven of the eight had drifted:

- ``core/next_buy_fallback.py:67`` / ``:66`` for "TFT and brawl have no build
  tables" (those lines are imports now; the exclusion is ``_SUPPORTED_STEMS``).
- ``core/build_order_precompute.py:303`` for "an empty order is what a producer
  emits when DS is down" (that line is a section comment after ``split_bias``
  now; the contract is the ``compute_cell`` docstring).
- The four fail-soft consumers: ``next_buy_fallback.py:171``,
  ``_deterministic_coaching.py:225`` and ``laning_verdicts.py:194`` had
  drifted (now cited as ``fallback_build_ids`` and two functions named
  ``_next_build_item``); ``precomputed_build_coach.py:172`` still landed on
  ``if not rec:`` in ``build_choices`` and is converted with the rest.
- ``tests/test_build_order_variants.py:445`` for the on-disk shape loop.

The guard's docstring also quoted ``for champ, variants in bo.items()`` as
the loop in tests/test_build_order_precompute.py. It never was: that file
iterates ``for champ, classes in bo.items()`` (also at the authoring commit);
the ``variants`` loop is the one in tests/test_build_order_variants.py.

The tests below ratchet both files to zero line cites, pin the symbol cites,
and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

TOOL = "tools/build_order_coverage.py"
GUARD = "tests/test_build_order_coverage_guard.py"

NEEDLES = {
    TOOL: (
        "(``_SUPPORTED_STEMS`` in\ncore/next_buy_fallback.py)",
        "(the ``compute_cell`` docstring in\n"
        "core/build_order_precompute.py)",
    ),
    GUARD: (
        "core/precomputed_build_coach.py      ``build_choices``: "
        "`if not rec: return []`",
        "core/next_buy_fallback.py           ``fallback_build_ids``: total, "
        "[] on any miss",
        "dashboard/_deterministic_coaching.py ``_next_build_item`` -> None",
        "core/laning_verdicts.py             ``_next_build_item`` -> "
        "`return None`",
        "`for champ, classes in bo.items()`",
        "`for champ, variants in bo.items()`",
        "(``_SUPPORTED_STEMS`` in\ncore/next_buy_fallback.py)",
    ),
}


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_text(rel))


def _top(rel: str, name: str) -> ast.AST:
    for node in _tree(rel).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{cls.name}.{name} not defined")


def _returns(func: ast.AST, src: str) -> int:
    return sum(
        1 for n in ast.walk(func)
        if isinstance(n, ast.Return) and n.value is not None
        and ast.unparse(n.value) == src
    )


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "excluded (``core/next_buy_fallback.py:67``).",
        "plan (``core/build_order_precompute.py:303``), so",
        "    core/precomputed_build_coach.py:172   `if not rec`",
        "`bo.items()`, tests/test_build_order_variants.py:445,",
        "by design (core/next_buy_fallback.py:66).",
    ):
        assert _PY_LINE.search(sample), sample
    for sample in (
        "tests/test_build_order_precompute.py::SeedTableTests",
        "``core.next_buy_fallback``",
        "ENGINE 1.290.0",
        "4671 of 4671 cells",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _PROSE_LINE.search(sample), sample


def test_targets_cite_by_symbol():
    assert len(NEEDLES) == 2
    for rel, needles in NEEDLES.items():
        text = _text(rel)
        hits = [
            i for i, line in enumerate(text.splitlines(), 1)
            if _PY_LINE.search(line) or _PROSE_LINE.search(line)
        ]
        assert hits == [], (rel, hits)
        for needle in needles:
            assert needle in text, (rel, needle)


def test_supported_stems_exclude_tft_and_brawl():
    tree = _tree("core/next_buy_fallback.py")
    stems = [
        n.value for n in tree.body if isinstance(n, ast.Assign)
        and [ast.unparse(t) for t in n.targets] == ["_SUPPORTED_STEMS"]
    ]
    assert len(stems) == 1
    value = stems[0]
    assert isinstance(value, ast.Call) and ast.unparse(value.func) == "frozenset"
    members = ast.literal_eval(value.args[0])
    assert members == {"sr", "aram", "arena"}
    assert "tft" not in members and "brawl" not in members


def test_compute_cell_documents_the_empty_order():
    func = _top("core/build_order_precompute.py", "compute_cell")
    doc = " ".join((ast.get_docstring(func) or "").split())
    assert "down / has nothing to plan yields ``order=[]``" in doc
    assert "else []" in ast.unparse(func)


def test_fail_soft_consumers():
    coach = _top("core/precomputed_build_coach.py", "build_choices")
    assert any(
        isinstance(n, ast.If) and ast.unparse(n.test) == "not rec"
        and isinstance(n.body[0], ast.Return)
        and ast.unparse(n.body[0].value) == "[]"
        for n in ast.walk(coach)
    )
    fallback = _top("core/next_buy_fallback.py", "fallback_build_ids")
    assert _returns(fallback, "[]") >= 2
    assert any(isinstance(n, ast.ExceptHandler) for n in ast.walk(fallback))
    for rel in ("dashboard/_deterministic_coaching.py", "core/laning_verdicts.py"):
        assert _returns(_top(rel, "_next_build_item"), "None") >= 1, rel


def test_on_disk_shape_loops():
    for rel, loop in (
        ("tests/test_build_order_precompute.py",
         "for champ, classes in bo.items():"),
        ("tests/test_build_order_variants.py",
         "for champ, variants in bo.items():"),
    ):
        seed = _method(_top(rel, "SeedTableTests"),
                       "test_committed_sr_seed_is_wellformed")
        assert loop in ast.unparse(seed), rel
    assert (REPO / "tests/test_hz_precompute_canonical_keyspace.py").is_file()
    precompute = _text("tests/test_build_order_precompute.py")
    assert "for champ, variants in bo.items()" not in precompute
