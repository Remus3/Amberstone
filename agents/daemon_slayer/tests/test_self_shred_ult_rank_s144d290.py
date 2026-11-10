"""S144-D-290 - ``compute_self_shred_uplift`` ranks an ultimate shred on the R schedule.

``self_shred._rank_at_level`` is the basic-ability "1 rank per 2 levels, cap
rank 5" heuristic, and it was applied to every key, R included. Its docstring
said ult shreds are clamped "separately by length", but ``_shred_at_rank``
only clamps the INDEX to the list, so Rengar R (3 ranks) was:

- credited at levels 1-5, before an ultimate can be learned;
- read at rank 3 (its largest value) from level 5 on, where the engine's one R
  schedule (``ability_dps.rank_at_level("R", ...)``: ranks at 6 / 11 / 16)
  gives rank 1 at 6-10 and rank 2 at 11-15;
- labelled "at rank 5" in its note from level 9 on, a rank R does not have.

The fix reads an R shred at the R schedule, skips it before level 6 with a
note that says so, and leaves every basic key's magnitude byte-identical.
The stub tests use synthetic champion ids; the live tests read the shipped
abilities snapshot and take the expected magnitudes from it, never a literal.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.daemon_slayer import self_shred as ss
from agents.daemon_slayer.ability_dps import rank_at_level


class _Snap:
    def __init__(self, result: Any) -> None:
        self._result = result

    def get_abilities(self, champion: str) -> Any:
        return self._result


def _shred(values: tuple = (10, 20, 30, 40, 50), attribute: str = "Armor Reduction") -> tuple:
    blk = SimpleNamespace(
        attribute=attribute, attribute_kind="modifier",
        raw_modifiers=({"values": list(values), "units": [""]},),
    )
    return (SimpleNamespace(damage_blocks=(blk,), damage_type="PHYSICAL"),)


ULT = (5, 10, 15)


def _expected_ult_flat(level: int) -> float:
    idx = rank_at_level("R", level)
    return 0.0 if idx < 0 else float(ULT[idx])


# ---- the R schedule --------------------------------------------------------

@pytest.mark.parametrize("level", range(1, 19))
def test_ult_rank_helper_is_the_engine_r_schedule(level: int) -> None:
    assert ss._ult_rank_at_level(level) == rank_at_level("R", level)


@pytest.mark.parametrize(("level", "expected"), [(0, -1), (-7, -1), (19, 2), (10**9, 2)])
def test_ult_rank_helper_clamps_out_of_range_levels_and_never_raises(level: int, expected: int) -> None:
    assert ss._ult_rank_at_level(level) == expected


@pytest.mark.parametrize("level", range(1, 19))
def test_ult_shred_magnitude_follows_the_r_schedule(level: int) -> None:
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, 100.0, snapshot=_Snap({"R": _shred(ULT)}))
    assert r.flat_shred == _expected_ult_flat(level)


@pytest.mark.parametrize("level", [1, 3, 5])
def test_ult_shred_before_level_six_is_a_zero_result_that_says_why(level: int) -> None:
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, 100.0, snapshot=_Snap({"R": _shred(ULT)}))
    assert r.shred_source == ""
    assert (r.dps_uplift_pct, r.dps_uplift_abs) == (0.0, 0.0)
    assert "unlocks at level 6" in r.notes
    assert "has no armor/MR target_shred ability" not in r.notes


@pytest.mark.parametrize(("level", "label"), [(6, "rank 1"), (10, "rank 1"), (11, "rank 2"), (16, "rank 3"), (18, "rank 3")])
def test_ult_note_names_the_ult_rank(level: int, label: str) -> None:
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, 100.0, snapshot=_Snap({"R": _shred(ULT)}))
    assert f"at {label}:" in r.notes
    assert "rank 4" not in r.notes
    assert "rank 5" not in r.notes


def test_level_far_above_eighteen_reads_the_last_ult_rank() -> None:
    r = ss.compute_self_shred_uplift("Synth", 10**9, 100.0, 50.0, 100.0, snapshot=_Snap({"R": _shred(ULT)}))
    assert r.flat_shred == 15.0


# ---- basic keys are untouched ----------------------------------------------

@pytest.mark.parametrize("key", ["Q", "W", "E"])
@pytest.mark.parametrize("level", range(1, 19))
def test_basic_key_magnitude_keeps_the_basic_schedule(key: str, level: int) -> None:
    values = (10, 20, 30, 40, 50)
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, 100.0, snapshot=_Snap({key: _shred(values)}))
    assert r.flat_shred == float(values[min(4, (level - 1) // 2)])
    assert f"at rank {min(4, (level - 1) // 2) + 1}:" in r.notes


def test_a_basic_shred_still_resolves_while_the_ult_is_locked() -> None:
    forms = {"E": _shred((1, 2, 3, 4, 5)), "R": _shred((90, 90, 90))}
    r = ss.compute_self_shred_uplift("Synth", 5, 100.0, 50.0, 100.0, snapshot=_Snap(forms))
    assert r.shred_source == "Synth:E"
    assert r.flat_shred == 3.0


def test_the_larger_ult_shred_wins_once_learned() -> None:
    forms = {"E": _shred((1, 2, 3, 4, 5)), "R": _shred((90, 90, 90))}
    r = ss.compute_self_shred_uplift("Synth", 6, 100.0, 50.0, 100.0, snapshot=_Snap(forms))
    assert r.shred_source == "Synth:R"
    assert r.flat_shred == 90.0


def test_candidate_shreds_without_ult_rank_keeps_its_old_contract() -> None:
    # The pre-existing call shape (no ult_rank) reads R at the given rank,
    # as the S144-D-90 candidate tests expect.
    assert ss._candidate_shreds({"R": _shred(ULT)}, None, 1) == [("R", 10.0, 0.0, ss.RESIST_ARMOR)]


def test_candidate_shreds_skips_a_locked_ult() -> None:
    assert ss._candidate_shreds({"R": _shred(ULT)}, None, 4, ult_rank=-1) == []
    assert ss._candidate_shreds({"R": _shred(ULT)}, None, 4, ult_rank=0) == [("R", 5.0, 0.0, ss.RESIST_ARMOR)]


def test_rank_helper_docstring_no_longer_claims_a_length_clamp_for_ults() -> None:
    doc = ss._rank_at_level.__doc__ or ""
    assert "separately by length" not in doc
    assert "_ult_rank_at_level" in doc


# ---- S144-D-292: the basic heuristic is the engine's max-first table -------

@pytest.mark.parametrize("key", ["Q", "W", "E"])
@pytest.mark.parametrize("level", range(1, 19))
def test_basic_rank_heuristic_equals_the_engine_max_first_table(key: str, level: int) -> None:
    assert ss._rank_at_level(level) == rank_at_level(key, level, max_priority=(key,))


def test_rank_helper_docstring_names_the_max_first_table() -> None:
    doc = " ".join((ss._rank_at_level.__doc__ or "").split())
    assert "rank_at_level(key, level, max_priority=(key,))" in doc
    assert "maxed first" in doc


# ---- S144-D-291: the dead AbilityForm import is gone -----------------------

def test_self_shred_no_longer_imports_ability_form() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ss.__file__).read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "AbilityForm" not in names
    assert "AbilityForm" not in vars(ss)


# ---- live snapshot: Rengar R, the one R-key armor shred --------------------

def _live_rengar_r_values() -> list:
    from agents.daemon_slayer.abilities import load_default

    snap = load_default()
    out = []
    for form in snap.get_abilities("Rengar")["R"]:
        for b in form.damage_blocks:
            if b.attribute_kind == "modifier" and ss.classify_modifier_kind(b.attribute) == "target_shred":
                out.append([float(v) for v in b.raw_modifiers[0]["values"]])
    return out


def test_live_rengar_r_is_a_three_rank_flat_shred() -> None:
    vals = _live_rengar_r_values()
    assert len(vals) == 1
    assert len(vals[0]) == 3


@pytest.mark.parametrize("level", [6, 10, 11, 15, 16, 18])
def test_live_rengar_r_reads_the_rank_its_level_supports(level: int) -> None:
    (vals,) = _live_rengar_r_values()
    r = ss.compute_self_shred_uplift("Rengar", level, 100.0, 60.0, 100.0, 0.0)
    assert r.shred_source == "Rengar:R"
    assert r.flat_shred == vals[rank_at_level("R", level)]
    assert f"at rank {rank_at_level('R', level) + 1}:" in r.notes


@pytest.mark.parametrize("level", [1, 3, 5])
def test_live_rengar_has_no_shred_before_level_six(level: int) -> None:
    r = ss.compute_self_shred_uplift("Rengar", level, 100.0, 60.0, 100.0, 0.0)
    assert r.shred_source == ""
    assert r.dps_uplift_pct == 0.0
    assert "unlocks at level 6" in r.notes


def test_every_live_r_key_shred_is_scheduled_by_the_r_table() -> None:
    # Sibling sweep: any champion whose winning shred is an R key reads it at
    # the R schedule, at every level, across the whole live snapshot.
    from agents.daemon_slayer.abilities import load_default

    snap = load_default()
    seen = 0
    for champ in sorted(snap.champions):
        forms = snap.get_abilities(champ)
        if "R" not in forms or not ss._candidate_shreds({"R": forms["R"]}, None, 0):
            continue
        seen += 1
        for level in range(1, 6):
            r = ss.compute_self_shred_uplift(champ, level, 100.0, 60.0, 100.0, 100.0)
            assert not r.shred_source.endswith(":R"), (champ, level)
    assert seen >= 1
