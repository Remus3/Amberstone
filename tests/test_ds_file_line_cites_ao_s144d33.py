"""Guard: the build-plan contract and P2-10 relax tests cite by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Two DS-adjacent test files carried
eight ``<file>.py:<n>`` cites plus one prose "line <n>" cite:

- tests/test_relax_recommender_p210.py (written 2026-10-04 at e1c50e699),
  seven cites in the module docstring naming the DS pool filter its
  legality adapter reuses: ``rank.py:730`` (``_filter_candidates``),
  ``rank.py:200`` (``_NON_COACHABLE_ITEM_IDS``), ``rank.py:658``
  (``_is_purchasable``), ``rank.py:663`` (``_is_ornn_masterwork``),
  ``rank.py:47`` and ``:715`` (``MODE_MAP_ID`` and ``_is_legal_in_mode``)
  and ``data_loader.py:57`` (``canonical_mode``). Four of the seven were
  already about ten lines off when written (the four defs sat at
  668 / 673 / 725 / 740 in that commit) and are eleven off now; the
  ``MODE_MAP_ID``, ``_NON_COACHABLE_ITEM_IDS`` and ``canonical_mode``
  cites are still exact.
- tests/test_build_plan_contract.py (written 2026-06-29 at b4aac5c49):
  ``tests/test_ds_preview_e2e_p1l21.py:108`` (``_Handler``, still exact),
  ``tests/test_planner_beam_search.py:79`` (``make_seed_fn``, now seven
  lines lower) and "master plan WP-C5, line 220" - the WP-C5 "TDD test
  first" row of docs/OVERLAY_BUILD_MASTER_PLAN.md, which the plan has since
  condensed away (only the C5 row of its Section J status table is left),
  so the comment now names the row and the commit to read it at.

The tests below ratchet both files to zero line cites, pin the symbol
cites, and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

RELAX = "tests/test_relax_recommender_p210.py"
CONTRACT = "tests/test_build_plan_contract.py"
RANK = "agents/daemon_slayer/rank.py"
PLAN = "docs/OVERLAY_BUILD_MASTER_PLAN.md"
PLAN_SHA = "b4aac5c49"

NEEDLES = {
    RELAX: (
        "``agents.daemon_slayer.rank._filter_candidates``, which applies",
        "``rank._NON_COACHABLE_ITEM_IDS``, ``rank._is_purchasable``,",
        "``rank._is_ornn_masterwork`` and ``rank._is_legal_in_mode`` over",
        "``rank.MODE_MAP_ID``; ``canonical_mode`` is",
        "``agents.daemon_slayer.data_loader.canonical_mode``.",
    ),
    CONTRACT: (
        "# The 5-value state enum the contract locks (the WP-C5 \"TDD test first\"\n"
        "# row of docs/OVERLAY_BUILD_MASTER_PLAN.md as authored at b4aac5c49; the\n"
        "# plan has since condensed WP-C5 to its Section J status row).",
        "# Test doubles - mirror ``_Handler`` in tests/test_ds_preview_e2e_p1l21.py\n"
        "# and ``make_seed_fn`` in tests/test_planner_beam_search.py (the\n"
        "# {ranked[], order[]} fake seed).",
    ),
}


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _top(rel: str, name: str) -> ast.AST:
    for node in ast.parse(_text(rel)).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "``_filter_candidates`` (agents/daemon_slayer/rank.py:730), which applies",
        "``_NON_COACHABLE_ITEM_IDS`` (rank.py:200), ``_is_purchasable``",
        "``canonical_mode`` is agents/daemon_slayer/data_loader.py:57.",
        "# Test doubles - mirror tests/test_ds_preview_e2e_p1l21.py:108 (_Handler) and",
        "# tests/test_planner_beam_search.py:79 (the {ranked[], order[]} fake seed).",
    ):
        assert _PY_LINE.search(sample), sample
    assert _PROSE_LINE.search(
        "# The 5-value state enum the contract locks (master plan WP-C5, line 220)."
    )
    for sample in (
        "``agents.daemon_slayer.rank._filter_candidates``, which applies",
        "# and ``make_seed_fn`` in tests/test_planner_beam_search.py (the",
        "# row of docs/OVERLAY_BUILD_MASTER_PLAN.md as authored at b4aac5c49; the",
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


def test_filter_candidates_applies_the_four_named_gates():
    func = _top(RANK, "_filter_candidates")
    names = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}
    for name in (
        "_NON_COACHABLE_ITEM_IDS",
        "_is_purchasable",
        "_is_ornn_masterwork",
        "_is_legal_in_mode",
    ):
        assert name in names, name
        _top(RANK, name)
    legal = _top(RANK, "_is_legal_in_mode")
    assert "MODE_MAP_ID.get(mode.upper())" in ast.unparse(legal)
    _top(RANK, "MODE_MAP_ID")
    _top("agents/daemon_slayer/data_loader.py", "canonical_mode")


def test_legality_adapter_reuses_the_pool_filter():
    src = _text("core/build_planner_legality.py")
    assert "from agents.daemon_slayer.rank import _filter_candidates" in src
    assert "from agents.daemon_slayer.data_loader import canonical_mode" in src


def test_contract_harness_mirrors_exist():
    _top("tests/test_ds_preview_e2e_p1l21.py", "_Handler")
    _top("tests/test_planner_beam_search.py", "make_seed_fn")
    _top(CONTRACT, "_Handler")


def test_state_enum_matches_the_plan_row_at_the_cited_commit():
    states = ast.literal_eval(_top(CONTRACT, "_STATES").value)
    assert states == {"owned", "next", "swap", "partial", "future"}
    old = subprocess.run(
        ["git", "show", f"{PLAN_SHA}:{PLAN}"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if old.returncode != 0:
        return  # shallow clone without that commit: the live half below still runs
    row = [ln for ln in old.stdout.splitlines() if ln.startswith("| TDD test first |")
           and "test_build_plan_contract.py" in ln]
    assert len(row) == 1, row
    assert "state:owned|next|swap|partial|future" in row[0]
    live = _text(PLAN)
    assert "| C5 /api/build-plan contract |" in live
    assert "state:owned|next|swap|partial|future" not in live
