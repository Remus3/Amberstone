"""Guard: the R5 missing-HP heal-amp test cites ability_hps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_hps_ability_missing_hp_amp_passthrough.py``
carried two ``ability_hps.py`` line cites, both true at 3f2557286 (R5 seam,
2026-06-27) and both one line off at HEAD:
- ``ability_hps.py:689-690`` was the ``caster_missing_hp_pct`` /
  ``assume_missing_hp_heal_amp`` parameters of ``compute_ability_hps``; at
  HEAD they sit at 690-691 and line 689 is ``target_missing_hp_pct``.
- ``ability_hps.py:455-458`` was the MasterYi / Lissandra / Sylas / Briar
  rows of ``_build_missing_hp_heal_amp``; at HEAD they sit at 456-459 and
  line 455 is ``registry: dict[...] = {}``.

The tests below pin the claims by symbol instead.
"""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path

from agents.daemon_slayer import ability_hps, hps

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_hps_ability_missing_hp_amp_passthrough.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])ability_hps\.py:\d")
_SEAM = ("assume_missing_hp_heal_amp", "caster_missing_hp_pct")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _forwarded_kwargs(func, callee: str) -> list[dict[str, str]]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee
        ):
            calls.append({
                kw.arg: kw.value.id
                for kw in node.keywords
                if kw.arg in _SEAM and isinstance(kw.value, ast.Name)
            })
    return calls


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("assume_missing_hp_heal_amp - ability_hps.py:689-690.")
    for sample in (
        "``ability_hps.compute_ability_hps``",
        "a hps.py:871 cite belongs to another guard",
        "a _ability_hps.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_ability_hps_line_cite_left():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_the_symbols():
    text = _target()
    assert "heal_amp - `ability_hps.compute_ability_hps`." in text
    assert "Briar P - `ability_hps._build_missing_hp_heal_amp`." in text


def test_compute_ability_hps_still_takes_the_seam_default_off():
    params = inspect.signature(ability_hps.compute_ability_hps).parameters
    assert params["assume_missing_hp_heal_amp"].default is False
    assert params["caster_missing_hp_pct"].default == 0.0


def test_registry_is_still_the_four_cited_rows():
    rows = {
        (champ, key)
        for champ, spells in ability_hps._MISSING_HP_HEAL_AMP.items()
        for key in spells
    }
    assert rows == {
        ("MasterYi", "W"), ("Lissandra", "R"), ("Sylas", "W"), ("Briar", "P"),
    }
    assert ability_hps._build_missing_hp_heal_amp() == ability_hps._MISSING_HP_HEAL_AMP


def test_hps_still_forwards_the_seam():
    seam = {name: name for name in _SEAM}
    for func, callee in (
        (hps.compute_hps, "compute_ability_hps"),
        (hps.rank_items_by_hps, "compute_hps"),
    ):
        calls = _forwarded_kwargs(func, callee)
        assert calls, f"{func.__name__} no longer calls {callee}"
        assert all(call == seam for call in calls), (func.__name__, calls)
