"""Guard: three DS test files cite the engine and their harnesses by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Three DS-adjacent test files carried
fifteen ``<file>.py:<n>`` cites over ten distinct targets. Every one was
exact when written (``engine.py:329`` named the first line of the
``mode_addends = (`` statement, two lines above its gate); eight of the ten
have since drifted:

- tests/test_rm172_mode_modifier_seam_characterization.py (written
  2026-08-06 at 08098b671), nine cites into agents/daemon_slayer/engine.py:
  ``engine.py:106`` (``_resolve_mode_addends``, now five lines lower),
  ``engine.py:329`` (the ``if apply_mode_modifiers`` gate inside
  ``build_champion``, then at 331, now about fifty lines lower),
  ``engine.py:225`` (``_apply_mode_modifiers``, now 28 lines lower),
  ``engine.py:450`` (the unconditional ``_apply_mode_modifiers(final, ...)``
  call, now 72 lines lower) and ``engine.py:458`` five times (the
  ``mode not in ("SR", "ARAM")`` not-plugged-in note, now 72 lines lower).
  Two of the 458 cites sit inside assertion MESSAGE strings, so this
  conversion changes those two message literals too; no assertion logic
  moves.
- tests/test_planner_snowball_ordering.py (written 2026-07-16):
  ``_effects_data.py:5344-5345`` (the Dark Seal ``"1082"`` ItemEffect row,
  now about 500 lines lower), ``core/archetype_mismatch.py:109`` (the
  ``"2033"`` Corrupting Potion consumable, now two lines lower) and
  ``core/build_planner/replan.py:569`` (the ``ReplanLoop.tick`` defaults,
  now about twenty lines lower).
- tests/test_c3_fed_counter_hint.py (written 2026-07-17):
  ``tests/test_build_plan_contract.py:46-124`` twice (the ``_Handler`` /
  ``_fake_seed_fn`` / ``_post`` harness, still in place) and
  ``tests/test_cc_threat.py:60`` (``AsciiHygieneTests``, still exact). Not
  drifted; converted with the rest so the file reaches zero.

The tests below ratchet the three files to zero line cites, pin the symbol
cites, and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

RM172 = "tests/test_rm172_mode_modifier_seam_characterization.py"
SNOW = "tests/test_planner_snowball_ordering.py"
C3 = "tests/test_c3_fed_counter_hint.py"
ENGINE = "agents/daemon_slayer/engine.py"

NEEDLES = {
    RM172: (
        "* ``engine._resolve_mode_addends`` - the ARENA/Swiftplay",
        "the ``if apply_mode_modifiers`` gate in ``engine.build_champion``).",
        "* ``engine._apply_mode_modifiers`` - the ARAM MULTIPLIER lane",
        "UNCONDITIONALLY from ``engine.build_champion`` and early-returns",
        "THE NOT-PLUGGED-IN NOTE IN ``engine.build_champion`` IS MISLEADING",
        "The OTHER half of the build_champion not-plugged-in note",
        "ARENA branch and the build_champion not-plugged-in note becomes \"",
        "The build_champion not-plugged-in note says the table is not",
        "the build_champion not-plugged-in note was corrected",
    ),
    SNOW: (
        "the ``\"1082\"`` row of ``ITEM_EFFECTS`` in\n"
        "agents/daemon_slayer/_effects_data.py",
        "the Consumables bucket of ``_NON_SIGNAL_ITEM_IDS`` in\n"
        "core/archetype_mismatch.py",
        "(the ``ReplanLoop.tick`` defaults in core/build_planner/replan.py)",
    ),
    C3: (
        "copies the tiny _Handler/_post harness (``_Handler``,\n"
        "``_fake_seed_fn``, ``_post``) from tests/test_build_plan_contract.py",
        "# Route half - harness copied from ``_Handler`` / ``_post`` in\n"
        "# tests/test_build_plan_contract.py.",
        "# ASCII hygiene (repo hard rule) - mirrors ``AsciiHygieneTests`` in\n"
        "# tests/test_cc_threat.py.",
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


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "* ``engine._resolve_mode_addends`` (engine.py:106) - the ARENA/Swiftplay",
        "THE ENGINE NOTE AT engine.py:458 IS MISLEADING, AND IT IS WHY THIS ROW EXISTS.",
        "16.14.1), agents/daemon_slayer/_effects_data.py:5344-5345 (\"1082\":",
        "core/archetype_mismatch.py:109 (2033 listed in the curated Consumables",
        "tests/test_build_plan_contract.py:46-124 so this slice touches no shared test",
        "# ASCII hygiene (repo hard rule) - mirrors tests/test_cc_threat.py:60.",
    ):
        assert _PY_LINE.search(sample), sample
    for sample in (
        "the ``if apply_mode_modifiers`` gate in ``engine.build_champion``).",
        "(the ``ReplanLoop.tick`` defaults in core/build_planner/replan.py)",
        "ENGINE 1.290.0 / patch 16.15.1",
        "docs/specs/2026-07-17-ds-c3-fed-counter-hint-design.md",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _PROSE_LINE.search(sample), sample


def test_targets_cite_by_symbol():
    assert len(NEEDLES) == 3
    for rel, needles in NEEDLES.items():
        text = _text(rel)
        hits = [
            i for i, line in enumerate(text.splitlines(), 1)
            if _PY_LINE.search(line) or _PROSE_LINE.search(line)
        ]
        assert hits == [], (rel, hits)
        for needle in needles:
            assert needle in text, (rel, needle)


def test_build_champion_holds_both_mode_lanes_and_the_note():
    _top(ENGINE, "_resolve_mode_addends")
    _top(ENGINE, "_apply_mode_modifiers")
    body = ast.unparse(_top(ENGINE, "build_champion"))
    assert (
        "_resolve_mode_addends(snapshot, champion_id, mode) "
        "if apply_mode_modifiers else None"
    ) in body
    assert "final, mode_notes = _apply_mode_modifiers(final, raw_base, mode, champ)" in body
    assert "if mode not in ('SR', 'ARAM'):" in body
    assert "modifier table not plugged in for this mode" in body


def test_apply_mode_modifiers_early_returns_off_aram():
    func = _top(ENGINE, "_apply_mode_modifiers")
    guards = [
        n for n in ast.walk(func)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "mode != 'ARAM'"
    ]
    assert len(guards) == 1
    assert isinstance(guards[0].body[0], ast.Return)


def test_dark_seal_and_corrupting_potion_ids():
    import agents.daemon_slayer._effects_data as effects
    import core.archetype_mismatch as mismatch

    assert effects.ITEM_EFFECTS["1082"].name == "Dark Seal"
    assert "2033" in mismatch._NON_SIGNAL_ITEM_IDS


def test_replan_tick_defaults_are_six_by_six():
    cls = _top("core/build_planner/replan.py", "ReplanLoop")
    tick = _method(cls, "tick")
    defaults = {
        a.arg: ast.literal_eval(d)
        for a, d in zip(tick.args.kwonlyargs, tick.args.kw_defaults)
        if d is not None and a.arg in ("beam_width", "depth")
    }
    assert defaults == {"beam_width": 6, "depth": 6}


def test_build_plan_contract_harness_and_cc_threat_hygiene():
    for name in ("_Handler", "_fake_seed_fn", "_post"):
        _top("tests/test_build_plan_contract.py", name)
    _top("tests/test_cc_threat.py", "AsciiHygieneTests")
