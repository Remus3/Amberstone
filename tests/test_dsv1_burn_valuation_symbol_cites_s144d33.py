"""Guard: the DSV1 burn-valuation test cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_dsv1_ability_burn_valuation.py`` said
``compute_ability_dps`` mirrors ``compute_dps``'s item AMP + PEN handling at
``ability_dps.py:950-965``. That was true at dc4d1de69 (DSV1, 2026-06-15):
the range was the "Mirror the AP cross-derivations + damage amps" comment
heading the AP-amp chain (``collect_effects`` at line 966). At HEAD that
chain sits near line 1238, so the range named unrelated code.

The tests below pin the claim by symbol instead.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_dsv1_ability_burn_valuation.py"
ABILITY_DPS = DS / "ability_dps.py"
_LINE_CITE = re.compile(r"(?<![\w.])ability_dps\.py:\d")

# The item AMP + PEN helpers the docstring says the ability scorer mirrors.
_AMP_PEN = frozenset({
    "collect_effects",
    "total_ap_amp_multiplier",
    "total_damage_amp_multiplier",
    "total_magic_amp_multiplier",
    "effective_target_armor",
    "effective_target_mr",
})


def _called_names(path: Path, name: str) -> set[str]:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
    raise AssertionError(f"{path.name} has no def {name}")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("handling (ability_dps.py:950-965) but")
    for sample in (
        "``ability_dps.compute_ability_dps``",
        "a dps.py:34 cite belongs to another guard",
        "a _ability_dps.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_dsv1_burn_test():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_dsv1_burn_test_names_the_symbol():
    text = TARGET.read_text(encoding="utf-8")
    assert "``ability_dps.compute_ability_dps``" in text
    assert "``collect_effects``" in text


def test_ability_scorer_still_calls_the_amp_and_pen_helpers():
    called = _called_names(ABILITY_DPS, "compute_ability_dps")
    assert _AMP_PEN <= called, sorted(_AMP_PEN - called)
