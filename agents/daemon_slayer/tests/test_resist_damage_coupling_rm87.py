"""RM-87 / row A-18: the champion resist -> damage coupling seam (DEFAULT-OFF).

WHAT THE ROW ORIGINALLY CLAIMED, AND WHY IT WAS WRONG
-----------------------------------------------------
The filing read "resists pay twice while the objective counts them once", i.e. a
DOUBLE-COUNT. Source-read refutes that: ``ehp.py`` accumulates each resist
EXACTLY ONCE into ``eff_armor`` / ``eff_mr``, puts it in the per-type EHP
denominator once, and blends once. There is no second credit anywhere.

The real defect is the INVERSE - a single-count UNDER-credit. ``ehp.py`` imports
no abilities module and reads zero ``damage_blocks``, so a champion whose KIT
converts its own resists into DAMAGE (Rammus P: bonus AD equal to 15 percent
total armor + 15 percent total MR; Ornn E: 40 percent bonus armor + 40 percent
bonus MR as physical damage) has that second, real payment credited NOWHERE. The
tank route therefore ranks a pure-HP roller (Warmog's / Heartsteel) above a
resist roller (Thornmail / Frozen Heart / Kaenic Rookern) by a wider margin than
the champion's own kit justifies.

WHAT THIS SEAM DOES
-------------------
``rank_items_by_ehp(apply_resist_damage_coupling=True, resist_coupling_strength=X)``
folds a normalized, sort-ONLY credit into ``_base_key``, following the existing
``_conv_key`` precedent: no row VALUE is ever mutated, only the ordering view.
DEFAULT-OFF and byte-identical when off.

THE FIVE GUARDS HERE
--------------------
1. OFF is byte-identical - the full ranked order (and every row value) for Ornn
   with the flag absent equals the run with the flag explicitly False.
2. ON moves the resist rollers UP and the pure-HP rollers DOWN, for BOTH seeded
   champions (Ornn = ``pct_base="bonus"``, Rammus = ``pct_base="total"``).
3. Poppy is the NEGATIVE CONTROL. Poppy W "Stubborn to a Fault" increases her own
   total armor and total MR by 12 percent - a resist -> RESIST amplification, NOT
   a resist -> damage conversion - so she is deliberately absent from the
   registry and the seam must be a no-op for her even with the flag ON.
4. A spy on the registry accessor proves the new code path (not some incidental
   float drift) is what produced the reorder, and that OFF never consults it.
5. A mutation check perturbs the registry magnitude and asserts the order
   actually moves, so guard 2's pins are not vacuous.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from agents.daemon_slayer import ehp as ehp_mod
from agents.daemon_slayer._resist_damage_coupling import (
    _CHAMPION_RESIST_DAMAGE_COUPLING,
    ResistDamageCouplingEntry,
    coupled_resist_points,
    resist_damage_coupling,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# Probe hygiene (reference_ds_probe_empty_build_artifact): NEVER an empty item
# list - an empty build under-ranks amp / complementary items and manufactures
# artifacts. Two real early-tank items on both champions.
_ORNN_BUILD = ("3068", "3047")     # Sunfire Aegis + Plated Steelcaps
_RAMMUS_BUILD = ("3068", "3047")
_POPPY_BUILD = ("3068", "3047")

# NO truncation. reference_ds_probe_depth_top40_truncation is the shallow half of
# this trap; the other half bit this test during authoring - a finite top_n is
# applied AFTER the sort, so a reorder changes WHICH rows survive the cut and the
# OFF/ON row SETS stop being comparable. top_n=None ranks the whole legal pool.
_TOP_N = None

# Operator-tunable lever magnitude. The seam is DEFAULT-OFF at strength 0.0;
# these runs engage it deliberately.
#
# Two values, and the gap is a real property of the normalization rather than a
# fudge: the credit divides by the BASELINE resist pool on the basis the entry
# names. Ornn reads ``pct_base="bonus"``, so his pool excludes his base armor/MR
# block and is small; Rammus reads ``pct_base="total"``, so his pool includes it
# and is roughly triple. The same operator strength therefore buys a visibly
# smaller reorder on a total-basis champion, and the measured floor for the full
# up/down pin on Rammus is 6.0 (at 3.0 Warmog's holds rank 1).
_STRENGTH = 3.0
_STRENGTH_TOTAL_BASIS = 6.0

# Resist rollers - the under-credited cohort this seam exists for.
_RESIST_ROLLERS = ("3075", "3110", "2504")   # Thornmail / Frozen Heart / Kaenic Rookern
# Pure-HP rollers - correct on the raw-EHP axis, over-ranked for a kit that
# converts resists into damage.
_HP_ROLLERS = ("3083", "3084")               # Warmog's Armor / Heartsteel


def _rank(champion: str, build: tuple[str, ...], **kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=champion,
        level=13,
        current_item_ids=list(build),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.4,
        top_n=_TOP_N,
        **kwargs,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _rows(result) -> tuple[tuple, ...]:
    return tuple(
        (
            r.item_id,
            r.delta_ehp,
            r.new_ehp,
            r.ehp_per_1k_gold,
            r.delta_cc_blended_ehp,
            r.delta_team_blended_ehp,
            r.survivability_score,
        )
        for r in result.ranked
    )


def _positions(result, ids) -> dict[str, int]:
    order = _order(result)
    return {i: order.index(i) for i in ids if i in order}


class RegistryProvenanceTests(unittest.TestCase):
    """The registry only carries entries sourced from on-disk data / in-repo overrides."""

    def test_seeded_champions_and_their_shapes(self) -> None:
        for champ in ("Rammus", "Ornn", "Rell", "Malphite", "Taric", "Galio"):
            with self.subTest(champ=champ):
                entry = resist_damage_coupling(champ)
                self.assertIsNotNone(entry, msg=f"{champ} must be seeded")
                self.assertIn(entry.pct_base, ("total", "bonus"))
                self.assertGreater(entry.armor_pct + entry.mr_pct, 0.0)
                self.assertGreater(entry.conditional_probability, 0.0)
                self.assertLessEqual(entry.conditional_probability, 1.0)
                self.assertTrue(entry.note, msg=f"{champ} needs a sourced note")

    def test_documented_rejects_stay_out(self) -> None:
        # K'Sante P All Out Bonus is a documented reject at
        # _passive_damage_overrides.py:840-843 (bilinear caster-resist * target
        # max HP AND gated on the R-empowered All Out state). Skarner carries no
        # resist-scaling ability text at all at 16.14.1. Poppy's only resist
        # passive is resist -> resist, not resist -> damage.
        for champ in ("KSante", "Skarner", "Poppy"):
            with self.subTest(champ=champ):
                self.assertIsNone(resist_damage_coupling(champ))

    def test_coupled_points_are_linear_and_floor_at_zero(self) -> None:
        entry = ResistDamageCouplingEntry(armor_pct=40.0, mr_pct=40.0, pct_base="bonus")
        self.assertAlmostEqual(coupled_resist_points(entry, 100.0, 50.0), 60.0)
        # A negative resist delta must never manufacture a negative credit.
        self.assertAlmostEqual(coupled_resist_points(entry, -100.0, -50.0), 0.0)


class SignatureConventionTests(unittest.TestCase):
    """Appended at the END of both signatures, DEFAULT-OFF."""

    def test_kwargs_are_the_signature_tail_and_default_off(self) -> None:
        for fn in (compute_ehp, rank_items_by_ehp):
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                names = tuple(params)
                self.assertEqual(
                    names[-2:],
                    ("apply_resist_damage_coupling", "resist_coupling_strength"),
                )
                self.assertIs(params["apply_resist_damage_coupling"].default, False)
                self.assertEqual(params["resist_coupling_strength"].default, 0.0)

    def test_observability_fields_are_appended_at_the_end_with_defaults(self) -> None:
        import dataclasses

        names = [f.name for f in dataclasses.fields(ehp_mod.EhpRankedItem)]
        self.assertEqual(names[-2:], ["delta_armor", "delta_mr"])
        for f in dataclasses.fields(ehp_mod.EhpRankedItem):
            if f.name in ("delta_armor", "delta_mr"):
                self.assertEqual(f.default, 0.0)


class OffIsByteIdenticalTests(unittest.TestCase):

    def test_flag_absent_equals_flag_explicitly_false_for_ornn(self) -> None:
        absent = _rank("Ornn", _ORNN_BUILD)
        explicit = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=False,
            resist_coupling_strength=0.0,
        )
        self.assertEqual(_order(absent), _order(explicit))
        self.assertEqual(_rows(absent), _rows(explicit))

    def test_flag_on_at_zero_strength_is_still_byte_identical(self) -> None:
        # The lever is the STRENGTH; a flag with no magnitude must not reorder.
        absent = _rank("Ornn", _ORNN_BUILD)
        armed_zero = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=0.0,
        )
        self.assertEqual(_order(absent), _order(armed_zero))
        self.assertEqual(_rows(absent), _rows(armed_zero))

    def test_off_leaves_the_observability_fields_at_identity(self) -> None:
        off = _rank("Ornn", _ORNN_BUILD)
        for row in off.ranked:
            self.assertEqual(row.delta_armor, 0.0, msg=row.item_id)
            self.assertEqual(row.delta_mr, 0.0, msg=row.item_id)


class OnReordersSeededChampionsTests(unittest.TestCase):

    def _assert_reorder(
        self, champ: str, build: tuple[str, ...], strength: float
    ) -> None:
        off = _rank(champ, build)
        on = _rank(
            champ, build,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=strength,
        )
        # The seam is sort-only: the row VALUES are untouched, so the SET of
        # ranked items and their deltas are unchanged - only the order moves.
        self.assertEqual(
            {r.item_id: r.delta_ehp for r in off.ranked},
            {r.item_id: r.delta_ehp for r in on.ranked},
            msg=f"{champ}: sort-only seam must not mutate row values",
        )
        self.assertNotEqual(_order(off), _order(on), msg=f"{champ}: ON must reorder")

        off_pos = _positions(off, _RESIST_ROLLERS + _HP_ROLLERS)
        on_pos = _positions(on, _RESIST_ROLLERS + _HP_ROLLERS)
        for item in _RESIST_ROLLERS:
            if item not in off_pos:
                continue
            with self.subTest(champ=champ, resist_roller=item):
                self.assertLess(
                    on_pos[item], off_pos[item],
                    msg=f"{champ}: resist roller {item} must move UP",
                )
        for item in _HP_ROLLERS:
            if item not in off_pos:
                continue
            with self.subTest(champ=champ, hp_roller=item):
                self.assertGreater(
                    on_pos[item], off_pos[item],
                    msg=f"{champ}: pure-HP roller {item} must move DOWN",
                )

    def test_ornn_bonus_basis_reorders(self) -> None:
        self._assert_reorder("Ornn", _ORNN_BUILD, _STRENGTH)

    def test_rammus_total_basis_reorders(self) -> None:
        self._assert_reorder("Rammus", _RAMMUS_BUILD, _STRENGTH_TOTAL_BASIS)

    def test_on_populates_the_observability_fields(self) -> None:
        on = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=_STRENGTH,
        )
        by_id = {r.item_id: r for r in on.ranked}
        thornmail = by_id.get("3075")
        self.assertIsNotNone(thornmail)
        self.assertGreater(thornmail.delta_armor, 0.0)
        warmogs = by_id.get("3083")
        self.assertIsNotNone(warmogs)
        # Warmog's grants no resists - the observability fields prove WHY it
        # takes no credit.
        self.assertAlmostEqual(warmogs.delta_armor, 0.0, places=6)
        self.assertAlmostEqual(warmogs.delta_mr, 0.0, places=6)


class PoppyNegativeControlTests(unittest.TestCase):

    def test_unregistered_champion_is_byte_identical_on_and_off(self) -> None:
        off = _rank("Poppy", _POPPY_BUILD)
        on = _rank(
            "Poppy", _POPPY_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=_STRENGTH,
        )
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(_rows(off), _rows(on))
        for row in on.ranked:
            self.assertEqual(row.delta_armor, 0.0, msg=row.item_id)
            self.assertEqual(row.delta_mr, 0.0, msg=row.item_id)


class CodePathProvenanceTests(unittest.TestCase):
    """Prove the NEW code path produced the delta - not incidental float drift."""

    def test_off_never_consults_the_registry(self) -> None:
        with mock.patch.object(
            ehp_mod, "resist_damage_coupling", wraps=resist_damage_coupling
        ) as spy:
            _rank("Ornn", _ORNN_BUILD)
        spy.assert_not_called()

    def test_on_consults_the_registry_with_the_champion_id(self) -> None:
        with mock.patch.object(
            ehp_mod, "resist_damage_coupling", wraps=resist_damage_coupling
        ) as spy:
            _rank(
                "Ornn", _ORNN_BUILD,
                apply_resist_damage_coupling=True,
                resist_coupling_strength=_STRENGTH,
            )
        spy.assert_called_once_with("Ornn")

    def test_a_none_registry_lookup_collapses_the_seam_to_a_no_op(self) -> None:
        # If the accessor returns None the ON order must equal the OFF order -
        # the registry, not the flag, is what carries the magnitude.
        off = _rank("Ornn", _ORNN_BUILD)
        with mock.patch.object(ehp_mod, "resist_damage_coupling", return_value=None):
            on = _rank(
                "Ornn", _ORNN_BUILD,
                apply_resist_damage_coupling=True,
                resist_coupling_strength=_STRENGTH,
            )
        self.assertEqual(_order(off), _order(on))


class MutationCheckTests(unittest.TestCase):
    """The pins above must be sensitive to the registry MAGNITUDE, not vacuous."""

    def test_perturbing_the_ornn_magnitude_changes_the_order(self) -> None:
        shipped = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=_STRENGTH,
        )
        shipped_entry = _CHAMPION_RESIST_DAMAGE_COUPLING["Ornn"]
        # A deliberately tiny magnitude: same code path, same flag, 1/40th the
        # conversion. If the order is identical the credit is not actually being
        # read from the registry - which is exactly the bug this check caught on
        # its first run, when the credit was normalized by the PERCENT-WEIGHTED
        # baseline and the percents cancelled out of the ratio entirely.
        tiny = ResistDamageCouplingEntry(
            armor_pct=1.0,
            mr_pct=1.0,
            pct_base=shipped_entry.pct_base,
            conditional_probability=shipped_entry.conditional_probability,
            attribute=shipped_entry.attribute,
            note="mutation-check stub",
        )
        with mock.patch.dict(
            _CHAMPION_RESIST_DAMAGE_COUPLING, {"Ornn": tiny}, clear=False
        ):
            mutated = _rank(
                "Ornn", _ORNN_BUILD,
                apply_resist_damage_coupling=True,
                resist_coupling_strength=_STRENGTH,
            )
        self.assertNotEqual(
            _order(shipped), _order(mutated),
            msg="the order must depend on the registry magnitude",
        )

    def test_strength_scales_monotonically_toward_the_resist_rollers(self) -> None:
        weak = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=0.25,
        )
        strong = _rank(
            "Ornn", _ORNN_BUILD,
            apply_resist_damage_coupling=True,
            resist_coupling_strength=6.0,
        )
        weak_pos = _positions(weak, _RESIST_ROLLERS)
        strong_pos = _positions(strong, _RESIST_ROLLERS)
        moved = [i for i in weak_pos if strong_pos.get(i, 99) < weak_pos[i]]
        self.assertTrue(
            moved,
            msg="a larger strength must float at least one resist roller higher",
        )


if __name__ == "__main__":
    unittest.main()
