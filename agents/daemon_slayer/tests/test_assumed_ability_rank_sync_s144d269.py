"""S144-D-269 - the two ``_ASSUMED_ABILITY_RANK`` constants stay in sync.

WHY. ``_passive_mitigation_overrides._ASSUMED_ABILITY_RANK`` says it is "the
analog of the flat registry's ``_passive_flat_mitigation_overrides.
_ASSUMED_ABILITY_RANK`` (kept in sync)", and nothing kept it in sync: the
percent-DR snapshot fold and the flat-DR registry both read a per-rank tuple at
``rank - 1`` clamped to the tuple, so moving one constant (the gated lane's
G4-06 retune proposes 4 -> 5 "in both modules") silently splits the two EHP
seams onto different ability ranks. Both readers also coerce the constant
through an index, so a 0, a negative or a float would read the first element
or raise, never a mid-game rank.

Pinned here: the two constants are equal ints in [1, 5] (an ability rank;
basic abilities top out at 5), and each reader reads element
``min(rank - 1, len - 1)`` - on a 3-rank ult tuple (Alistar R, the only R
tuple the 16.22.1 percent-DR snapshot fold reads) rank 4 clamps to the ult's
MAX rank 3, which the percent module's comment now says. The checker flags a
planted desync. The value itself is NOT pinned, so a both-module retune passes.

MEASURED 2026-11-09 (patch 16.22.1): both constants 4; flat rank_scaled rows
Amumu E (5, 7, 9, 11, 13) and Leona W (8, 12, 16, 20, 24) read 11 and 20;
snapshot percent-DR tuples 8 five-long (W x5, E x3) and 1 three-long (Alistar
R, read at 75). A guard plus a comment; no behaviour change.
"""

from __future__ import annotations

import pytest

from agents.daemon_slayer import _passive_flat_mitigation_overrides as flat_mod
from agents.daemon_slayer import _passive_mitigation_overrides as pct_mod
from agents.daemon_slayer.data_loader import DataSnapshot


def check_rank_sync(flat_rank: object, pct_rank: object) -> list[str]:
    out: list[str] = []
    for name, value in (("flat", flat_rank), ("percent", pct_rank)):
        if not isinstance(value, int) or isinstance(value, bool):
            out.append(f"{name} _ASSUMED_ABILITY_RANK {value!r} is not an int")
        elif not 1 <= value <= 5:
            out.append(f"{name} _ASSUMED_ABILITY_RANK {value} is not an ability rank")
    if flat_rank != pct_rank:
        out.append(f"flat {flat_rank!r} != percent {pct_rank!r}")
    return out


def test_s144d269_assumed_ability_ranks_are_equal_ability_ranks() -> None:
    assert check_rank_sync(flat_mod._ASSUMED_ABILITY_RANK, pct_mod._ASSUMED_ABILITY_RANK) == []


@pytest.mark.parametrize(
    ("flat_rank", "pct_rank"),
    [(4, 5), (0, 0), (6, 6), (4.0, 4.0), (True, True), (-1, -1)],
)
def test_s144d269_checker_flags_planted_desync(flat_rank: object, pct_rank: object) -> None:
    assert check_rank_sync(flat_rank, pct_rank)


def test_s144d269_flat_reader_reads_rank_minus_one_clamped() -> None:
    rank = flat_mod._ASSUMED_ABILITY_RANK
    rows = [e for e in flat_mod._PASSIVE_FLAT_MITIGATION_OVERRIDES.values() if e.rank_scaled]
    assert len(rows) >= 2, "rank_scaled flat walk went empty"
    for entry in rows:
        for flat, _dtype in entry.terms:
            assert isinstance(flat, tuple)
            got = flat_mod._value_at_level(flat, 11, True)
            assert got == flat[min(rank - 1, len(flat) - 1)]
    three = (55.0, 65.0, 75.0)
    assert flat_mod._value_at_level(three, 11, True) == three[min(rank - 1, 2)]


SNAPSHOT_DR_CHAMPS = ("Alistar", "Belveth", "Braum", "Galio", "Garen", "Gragas", "MasterYi", "Warwick")


def test_s144d269_percent_snapshot_fold_reads_rank_minus_one_clamped() -> None:
    snap = DataSnapshot.load()
    rank = pct_mod._ASSUMED_ABILITY_RANK
    checked: list[int] = []
    for champ in SNAPSHOT_DR_CHAMPS:
        if champ in pct_mod._HAND_AUTHORED_DR_CHAMPS:
            continue
        blocks = [
            per_rank
            for slot in ("Q", "W", "E", "R")
            for label, per_rank in (snap.spell_damage_reduction_pct(champ, slot) or {}).items()
            if pct_mod._classify_dr_axis(label) == pct_mod.ANY
        ]
        if len(blocks) != 1:
            continue
        per_rank = blocks[0]
        pct = per_rank[min(rank - 1, len(per_rank) - 1)]
        mult = 1.0 - max(0.0, min(1.0, pct / 100.0 * pct_mod._ACTIVE_DR_PROB))
        got = pct_mod.mitigation_multipliers(champ, 11, True, snap)
        assert got == pytest.approx((mult, mult, mult)), champ
        checked.append(len(per_rank))
    assert len(checked) >= 4, "snapshot percent-DR walk went empty"
    assert 3 in checked, "no 3-rank tuple left to exercise the clamp"
