"""Guard: the P1-L12 AS-cap regression lock cites dps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The
``test_attack_speed_must_be_capped_at_2_5`` docstring in
``agents/daemon_slayer/tests/test_engine_robustness_p1l12.py`` carried three
``dps.py`` line cites, all true at f749b9f91 (P1-L12, 2026-05-19):
- ``dps.py:436`` was ``eff_as = float(stats.get("as", 0.0))`` in
  ``_rotation_attack_dps``; at HEAD it is an unrelated
  ``LIGHTSHIELD_STRIKE_PROC_NAME`` check, and the line sits near 628.
- ``dps.py:708`` was the per-hit display ``eff_as`` read in
  ``compute_dps``; at HEAD it is ``_phase_rotations`` docstring prose, and
  the read sits near 1490.
- ``dps.py:441`` was ``crit = min(float(stats.get("crit", 0.0)), 1.0)`` in
  ``_rotation_attack_dps``; at HEAD it is a ``target_armor_for_physical``
  argument line in ``_lightshield_strike_per_proc_damage``.

The tests below pin each claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import dps, engine

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_engine_robustness_p1l12.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])dps\.py:\d")
_EFF_AS = 'eff_as = float(stats.get("as", 0.0))'


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("``agents/daemon_slayer/dps.py:436``")
    assert _LINE_CITE.search("again at ``dps.py:708``, with NO")
    for sample in (
        "``dps._rotation_attack_dps``",
        "an ability_dps.py:12 cite belongs to another guard",
        "a hps.py:7 cite belongs to another guard",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_dps_line_cite_left_in_p1l12():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_p1l12_names_each_symbol():
    src = _target()
    for symbol in (
        "``dps._rotation_attack_dps``",
        "``dps.compute_dps``",
        "``engine._combine_items``",
        "``engine.ATTACK_SPEED_CAP``",
    ):
        assert symbol in src, symbol


def test_cited_dps_reads_live_in_the_named_functions():
    rotation = inspect.getsource(dps._rotation_attack_dps)
    assert _EFF_AS in rotation
    assert 'crit = min(float(stats.get("crit", 0.0)), 1.0)' in rotation
    assert _EFF_AS in inspect.getsource(dps.compute_dps)


def test_combine_items_clamps_as_to_the_cap():
    assert engine.ATTACK_SPEED_CAP == 2.5
    src = inspect.getsource(engine._combine_items)
    assert 'if out.get("as", 0.0) > ATTACK_SPEED_CAP:' in src
    assert 'out["as"] = ATTACK_SPEED_CAP' in src
