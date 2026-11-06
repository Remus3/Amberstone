"""Guard: _item_resist_grants.py cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The Terminus "3302" decision comment
carried four line cites and every one had drifted (cited -> line before this
edit): ``_ITEM_RESIST_STACK_PROB = 0.5`` "at line 123" -> 154, the Dark pen
fields ``_effects_data.py:633-634`` -> 641-642, their note
``_effects_data.py:620-623`` -> 617-631, and the pen pin
``tests/test_pen_pct_catalog_r160.py:105`` -> 138. That last one, and two more
backticked test paths in the module (the R133 magnitude guard and the R144
slice-B coverage guard), named ``tests/...`` while the files live under
agents/daemon_slayer/tests.

The tests below pin the claims the comment leans on, so a refactor that breaks
one turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

from agents.daemon_slayer import _item_resist_grants as grants
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "_item_resist_grants.py"
# ``_effects_data.py:633-634`` and ``at line 123 of``. Not the port shape
# ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")
_TEST_PATH = re.compile(r"``((?:[\w.]+/)*test_\w+\.py)``")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``_ITEM_RESIST_STACK_PROB = 0.5`` at line 123 of",
        "``_effects_data.py:633-634`` sets ``armor_pen_pct=0.30`` /",
        '3124 4-stack 0.32 cond-AS)". ``tests/test_pen_pct_catalog_r160.py:105``',
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        '``ITEM_EFFECTS["3302"].armor_pen_pct`` in ``_effects_data.py``',
        '``_STACKING_FULL_STACK["3302"]`` pins it',
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(_source(TARGET).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_every_backticked_test_path_exists():
    paths = _TEST_PATH.findall(_source(TARGET))
    assert len(paths) >= 3, paths
    missing = [p for p in paths if not (REPO / p).is_file()]
    assert not missing, f"cited test paths not on disk: {missing}"


def test_registry_default_is_the_stack_prob_and_terminus_overrides_it():
    assert grants._ITEM_RESIST_STACK_PROB == 0.5
    fields = {f.name: f for f in dataclasses.fields(grants.ItemResistEntry)}
    default = fields["conditional_probability"].default
    assert default == grants._ITEM_RESIST_STACK_PROB
    assert grants._ITEM_RESIST_GRANTS["3302"].conditional_probability == 1.0


def test_dark_half_is_credited_at_full_stacks_with_the_quoted_note():
    row = ITEM_EFFECTS["3302"]
    assert row.armor_pen_pct == 0.30
    assert row.magic_pen_pct == 0.30
    # The note is a ``#`` comment block, so drop each line's marker first.
    text = " ".join(
        line.strip().lstrip("#").strip()
        for line in _source(DS / "_effects_data.py").splitlines()
    )
    assert (
        "the full-stack sustained-DPS convention (Black Cleaver 3071 5-stack "
        "0.30 shred, Guinsoo 3124 4-stack 0.32 cond-AS)"
    ) in text


def test_pen_catalog_pins_the_terminus_full_stack():
    path = DS / "tests" / "test_pen_pct_catalog_r160.py"
    tree = ast.parse(_source(path))
    node = next(
        n for n in tree.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_STACKING_FULL_STACK"
            for t in n.targets
        )
    )
    assert ast.literal_eval(node.value)["3302"] == (10.0, 0.30)
