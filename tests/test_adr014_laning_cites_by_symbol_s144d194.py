"""Guard: ADR-014 and the overlay plan cite the laning table code by symbol (S144-D-194).

Measured 2026-11-09 at lane/ds HEAD f85597d8d. ADR-014 (written 2026-08-07)
carried eleven line cites into the laning-table code and its readers; ten had
drifted off their target:

- ``core/laning_scenario_precompute.py:856`` for the hard-coded
  ``"schema": "laning_scenarios/v4"`` emit - now inside ``generate_table``,
  about ninety lines lower.
- ``tests/test_laning_scenario_precompute.py:141,394`` for the only two
  ``patch=`` callers - ``:394`` is now one line past
  ``test_explicit_patch_pin_does_not_fall_back``'s call.
- ``dashboard/_state_builder.py:629`` (now an ASCII-fold helper; the call is
  in ``build_state``), ``dashboard/_deterministic_coaching.py:1647`` and
  ``:1691-1705`` (both now inside ``shadow_log_precomputed_choices``, about
  150 lines lower), ``core/precomputed_laning_coach.py:484,521`` (now
  ``resolve_enemy`` / ``_resolve_cell_ctx``), ``:333-342``
  (``_recall_outcome``), ``:441`` (``_build_choices``), ``:575``
  (``_resolve_rebranch``), ``core/hz_choice_shadow.py:79`` (a module
  comment; the read is ``precompute_source_tag``) and
  ``tools/replay_laning_verdict_validate.py:644`` (``_load_table``).
- ``core/precomputed_laning_coach.py:83-86`` for ``_RECALL_LABELS`` was still
  exact and is converted with the rest.

docs/OVERLAY_COMPLIANCE_PLAN.md cited ``core/laning_scenario_precompute.py:613-664``
for ``my_ult_cd_s``; ``def _my_ult_cd_s`` has moved down, so that range
now covers only its first few lines.

The tests ratchet ADR-014 to zero line cites, pin the overlay plan's laning
cite by symbol, and re-derive by AST every claim the new symbol cites carry.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ADR = "docs/adr/ADR-014-aram-laning-table-known-wrong-not-regenerated.md"
OVERLAY = "docs/OVERLAY_COMPLIANCE_PLAN.md"

_FILE_LINE = re.compile(r"[\w/.]+\.(?:py|js|css|json|md):\s?\d")
# A bare ``:441`` / ``(:333-342)`` back-reference to the file named just before.
_BARE_LINE = re.compile(r"(?<![\w.:])[`(]?:\d{2,4}\b")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _func(rel: str, name: str) -> ast.AST:
    tree = ast.parse(_read(rel))
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"{rel} has no def {name}")


def _func_src(rel: str, name: str) -> str:
    return ast.get_source_segment(_read(rel), _func(rel, name)) or ""


def test_line_cite_patterns_catch_the_old_forms():
    for old in (
        "`core/laning_scenario_precompute.py:856`",
        "`tests/test_laning_scenario_precompute.py:141,394`, both",
        "`dashboard/_deterministic_coaching.py:1691-1705` folds",
        "(`core/laning_scenario_precompute.py:613-664`) is the",
    ):
        assert _FILE_LINE.search(old), old
    for old in (
        "At `:441` the",
        "`_recall_outcome` (:333-342), the chip gate at",
        "  :441 and the rebranch read at :575.",
    ):
        assert _BARE_LINE.search(old), old
    for fine in ("patch 16.13.1", "-50.495 pct", "ADR-013", "L2 and L11"):
        assert _BARE_LINE.search(fine) is None, fine
        assert _FILE_LINE.search(fine) is None, fine


def test_adr014_carries_no_line_cites():
    text = _read(ADR)
    assert _FILE_LINE.findall(text) == [], "cite a symbol, not a line number"
    assert _BARE_LINE.findall(text) == [], "cite a symbol, not a line number"


def test_adr014_reader_table_has_a_symbol_column():
    text = _read(ADR)
    assert "| reader | symbol | what it does |" in text
    assert "| reader | line | what it does |" not in text
    # A bare line number put back into the reader table, e.g. ``| 629 |``.
    # Scoped to that table: the ADR's other tables hold real counts.
    start = text.index("| reader | symbol | what it does |")
    table = text[start:text.index("\n\n", start)]
    rows = table.splitlines()[2:]
    assert len(rows) >= 7, rows
    assert re.findall(r"\|\s*\d[\d, -]*\s*\|", table) == []


@pytest.mark.parametrize(
    "needle",
    [
        "`generate_table` in `core/laning_scenario_precompute.py`",
        "`test_load_missing_db_failsoft` and",
        "`test_explicit_patch_pin_does_not_fall_back`",
        "`_load_table` in `tools/replay_laning_verdict_validate.py`",
        "`build_state` in `dashboard/_state_builder.py`",
        "`_RECALL_LABELS` (`core/precomputed_laning_coach.py`)",
    ],
)
def test_adr014_symbol_cites_present(needle):
    flat = " ".join(_read(ADR).split())
    assert needle in flat, needle


def test_overlay_plan_cites_my_ult_cd_s_by_symbol():
    text = _read(OVERLAY)
    assert "laning_scenario_precompute.py:" not in text
    flat = " ".join(text.split())
    assert "(`_my_ult_cd_s` in `core/laning_scenario_precompute.py`)" in flat


# --- the claims the symbol cites carry, re-derived ---------------------------


def test_generate_table_hard_codes_the_v4_schema():
    src = _func_src("core/laning_scenario_precompute.py", "generate_table")
    assert '"schema": "laning_scenarios/v4"' in src
    assert "laning_scenarios/v3" not in src


@pytest.mark.parametrize(
    "rel, name, needle",
    [
        ("dashboard/_state_builder.py", "build_state",
         "shadow_log_precomputed_choices("),
        ("dashboard/_deterministic_coaching.py",
         "shadow_log_precomputed_choices", "load_laning_scenarios(lower)"),
        ("dashboard/_deterministic_coaching.py",
         "shadow_log_precomputed_choices", 'cell.get("cooldown_window")'),
        ("dashboard/_deterministic_coaching.py",
         "shadow_log_precomputed_choices", 'cell.get("spike_timing")'),
        ("core/precomputed_laning_coach.py", "resolve_enemy",
         "load_laning_scenarios(mode)"),
        ("core/precomputed_laning_coach.py", "_resolve_cell_ctx",
         "load_laning_scenarios(mode)"),
        ("core/precomputed_laning_coach.py", "_recall_outcome",
         'f"{gold_s} banked; next spike {spike}"'),
        ("core/precomputed_laning_coach.py", "_build_choices",
         "if recall in _RECALL_LABELS:"),
        ("core/precomputed_laning_coach.py", "_resolve_rebranch",
         "b_is_recall = "),
        ("core/hz_choice_shadow.py", "precompute_source_tag",
         "load_laning_scenarios(mode_key)"),
        ("tools/replay_laning_verdict_validate.py", "_load_table",
         "return load_laning_scenarios(mode)"),
        ("tests/test_laning_scenario_precompute.py",
         "test_load_missing_db_failsoft", 'patch="0.0.0"'),
        ("tests/test_laning_scenario_precompute.py",
         "test_explicit_patch_pin_does_not_fall_back", 'patch="16.14.1"'),
        ("core/laning_scenario_precompute.py", "_my_ult_cd_s", "def _my_ult_cd_s("),
    ],
)
def test_cited_symbol_does_what_the_adr_says(rel, name, needle):
    assert needle in _func_src(rel, name), (rel, name, needle)


def test_recall_labels_still_have_no_hold_key():
    tree = ast.parse(_read("core/precomputed_laning_coach.py"))
    for node in tree.body:
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "_RECALL_LABELS":
            keys = {k.value for k in node.value.keys}
            assert keys == {"recall_now", "back_soon"}
            return
    raise AssertionError("_RECALL_LABELS not found")


def test_only_tests_pin_a_patch_on_load_laning_scenarios():
    pinned = []
    calls = 0
    for rel in ("core", "dashboard", "tools", "agents", "modes", "lib"):
        root = REPO / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "load_laning_scenarios(" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", ""))
                    == "load_laning_scenarios"
                ):
                    calls += 1
                    if len(node.args) > 1 or any(k.arg == "patch" for k in node.keywords):
                        pinned.append(f"{path.relative_to(REPO)}")
    # The five non-test readers the ADR names; an empty walk must not pass.
    assert calls >= 5, calls
    assert pinned == [], pinned
