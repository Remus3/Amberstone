"""Guard: the RM-176 extra-shot crit test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. test_extra_shot_effect_crit_rm176.py
cited six line numbers and none still pointed at its claim:
``dps.py:1577`` (now an ``if raw_attack_dps > 0.0`` line; the ``can_crit``
branch sits about 90 lines lower), ``dps.py:1148`` (a bare ``#``),
``dps.py:1390`` (an import), ``dps.py:1589`` (a ``notes.append``),
``dps.py:958`` (``aa_empower_amp = 1.0``) and ``_effects_data.py:1263``
(a comment inside the Yun Tal row). A cite that resolves today rots on the
next insert above it, so they go.

The tests below pin the claims instead, each inside ``dps.compute_dps`` or on
the ``ITEM_EFFECTS`` row it names.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import dps
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "agents" / "daemon_slayer" / "tests" / "test_extra_shot_effect_crit_rm176.py"
# ``dps.py:1577``. Not the port shape ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _compute_dps() -> str:
    return inspect.getsource(dps.compute_dps)


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("credits the shot (``dps.py:1577``). That term")
    for sample in (
        "the ``extra_shot_entry_.can_crit`` branch in ``dps.compute_dps``",
        "no live :8860, no network",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_each_symbol():
    src = _target()
    for symbol in (
        "``extra_shot_entry_.can_crit``",
        "``min(raw_crit + crit_from_effects, 1.0)``",
        "``crit = crit_total``",
        '``"3032"`` row',
        "``per_attack_on_hit_damage += passive_aa_per_hit``",
    ):
        assert symbol in src, symbol


def test_shot_crit_branch_reads_crit_total():
    src = _compute_dps()
    branch = src.index("if extra_shot_entry_ is not None and extra_shot_entry_.can_crit:")
    tail = src[branch:]
    assert "_shot_crit = crit_total" in tail
    assert tail.index("_shot_crit = crit_total") < tail.index("passive_aa_per_hit *= 1.0 + _shot_crit * crit_bonus")


def test_crit_total_folds_effect_crit():
    assert "crit_total = min(raw_crit + crit_from_effects, 1.0)" in _compute_dps()


def test_base_auto_resolves_against_crit_total():
    src = _compute_dps()
    alias = src.index("crit = crit_total")
    assert src.index("avg_attack_dmg = ad * (1 + crit * crit_bonus)") > alias
    assert src.index("raw_attack_dps = ad * eff_as * (1 + crit * crit_bonus)") > alias


def test_routed_passive_joins_per_attack_on_hit_damage():
    src = _compute_dps()
    shot = src.index("passive_aa_per_hit *= 1.0 + _shot_crit * crit_bonus")
    assert src.index("per_attack_on_hit_damage += passive_aa_per_hit") > shot


def test_crit_bonus_binding_matches_the_helper():
    assert "crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)" in _compute_dps()


def test_yun_tal_row_carries_the_effect_crit():
    assert ITEM_EFFECTS["3032"].crit_chance_bonus_flat == 0.25
