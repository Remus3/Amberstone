"""RM-36 / RM-38 - the AD-axis ability term reaches the CARRY ranker.

The bruiser scorer has priced AD-axis ability damage since RM-39 / RM-43
(ENGINE 1.222.0 / 1.223.0, DEFAULT-OFF ``apply_ad_axis_ability_damage``).
The CARRY scorer never did, which is the modelling half of RM-36 (Ezreal) and
RM-38 (Corki): ``ds.dps`` is auto-attack-only, so an AD-CASTER whose damage
rides his Q is scored as though he were a sustained auto marksman.

The pool half of those two rows is already shipped and is NOT re-tested here -
``exempt_offclass_by_win`` and ``widen_carry_pool`` between them admit Trinity
Force 3078 and Spear of Shojin 3161, measured live at ENGINE 1.271.0 on
2026-08-04 (Ezreal both-flags: pool 113, Trinity #4, Shojin #42).

What these tests pin:

* the seam is DEFAULT-OFF and byte-identical when omitted;
* ON, it REORDERS an AD-caster (the term is champion-sensitive by
  construction - it sums that champion's own credited per-spell rows);
* ON, it is a provable NO-OP for a champion with no credited AD-axis ability
  rows, which is the control that keeps the seam from being a blanket rescale;
* the relocation of the term into ``_ad_axis_ability`` left exactly ONE
  definition - ``hybrid`` re-binds it rather than carrying a private copy.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import hybrid, rank
from agents.daemon_slayer._ad_axis_ability import (
    AD_AXIS_CREDITED_DAMAGE_TYPES,
    physical_ability_damage,
)
from agents.daemon_slayer.data_loader import DataSnapshot

SR = "SR"
LEVEL = 16
# Sweep-standard tanky target (docs/DS_SWEEP_TRACKER.md probe recipe).
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)


_SNAP = DataSnapshot.load()


def _rank(champion, **kwargs):
    return rank.rank_items(
        _SNAP,
        champion,
        level=LEVEL,
        current_item_ids=[],
        mode=SR,
        top_n=None,
        **TARGET,
        **kwargs,
    )


def _ad_term(champion: str) -> float:
    return physical_ability_damage(
        _SNAP, champion, LEVEL, (), SR,
        TARGET["target_armor"], TARGET["target_mr"],
        TARGET["target_max_hp"], TARGET["target_bonus_hp"], (),
    )


def _order(result):
    return [row.item_id for row in result.ranked]


class AdAxisCarryRelocationTest(unittest.TestCase):
    """The term has ONE definition; hybrid re-binds, it does not re-implement."""

    def test_hybrid_rebinds_the_relocated_term(self):
        self.assertIs(hybrid._physical_ability_damage, physical_ability_damage)
        self.assertIs(
            hybrid._AD_AXIS_CREDITED_DAMAGE_TYPES, AD_AXIS_CREDITED_DAMAGE_TYPES
        )

    def test_credited_damage_types_are_unchanged_by_the_move(self):
        # MAGIC is permanently excluded, MIXED is deliberately held (RM-39 L2).
        self.assertEqual(AD_AXIS_CREDITED_DAMAGE_TYPES, frozenset({"PHYSICAL", "TRUE"}))


class AdAxisCarrySeamTest(unittest.TestCase):
    def test_seam_defaults_off_and_is_byte_identical(self):
        off = _rank("Ezreal")
        explicit_off = _rank("Ezreal", apply_ad_axis_ability_damage=False)
        self.assertEqual(_order(off), _order(explicit_off))
        for a, b in zip(off.ranked, explicit_off.ranked):
            self.assertEqual(a.delta_dps, b.delta_dps)
            self.assertEqual(a.new_dps, b.new_dps)
        self.assertEqual(off.baseline_dps, explicit_off.baseline_dps)

    def test_ezreal_is_a_measured_no_op_the_ap_scaling_gate_blocks_him(self):
        """RM-36 is NOT closed by this seam, and this pins WHY.

        Measured 2026-08-04 at level 16 on the sweep-standard tanky target:
        Ezreal has exactly ONE PHYSICAL per-spell row (Q Mystic Shot, dps
        18.447) and its ``ap_pct_sum`` is 200.0, so the term's AP-SCALING
        EXCLUSION drops it and the sum is exactly 0.0. That exclusion is the
        deliberate RM-39 contract - an AD-axis term must not become an
        AP-pricing channel - and Ezreal's signature spell is precisely the
        dual-scaling shape it excludes (the same collateral the term's
        docstring already records for Vayne Q Tumble).

        So arming the seam is a provable NO-OP for him. Closing RM-36 needs a
        SPLIT credit for the AD PORTION of a dual-scaling row - a new design,
        mirroring the "honest 50 pct credit" the MIXED note describes - not a
        widen of this gate. Do not re-file RM-36 as "port the term to carry";
        that is done and it does not reach him.

        SHIPPED 2026-08-04 as ``apply_ad_axis_dual_scaling_split``
        (DEFAULT-OFF, ``tests/test_ad_axis_dual_scaling_split_rm36.py``). This
        test is unchanged and still true, because it exercises the DEFAULT
        path: without that second flag Ezreal's term is still exactly 0.0.
        """
        self.assertEqual(_ad_term("Ezreal"), 0.0)
        off = _rank("Ezreal")
        on = _rank("Ezreal", apply_ad_axis_ability_damage=True)
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(off.baseline_dps, on.baseline_dps)

    def test_corki_reorders_when_the_seam_is_armed(self):
        off = _rank("Corki")
        on = _rank("Corki", apply_ad_axis_ability_damage=True)
        self.assertNotEqual(_order(off), _order(on))

    def test_baseline_and_new_dps_stay_consistent_with_delta(self):
        on = _rank("Ezreal", apply_ad_axis_ability_damage=True)
        for row in on.ranked[:20]:
            self.assertAlmostEqual(
                row.delta_dps, row.new_dps - on.baseline_dps, places=6
            )

    def test_the_term_is_champion_sensitive_not_a_blanket_rescale(self):
        """A zero-credited-row champion must be untouched ON.

        This is what keeps the seam from being a blanket rescale, and it is
        the control that RM-40 / RM-44 / RM-48 lacked. Both champions here are
        zero for a MECHANICAL reason - the AP-scaling gate - not because they
        have no abilities, so a widen of that gate fails this test loudly
        rather than silently turning it vacuous.

        EZREAL WAS THE SOLE CONTROL AND NO LONGER CARRIES THE CLAIM ALONE.
        ``apply_ad_axis_dual_scaling_split`` (RM-36, 2026-08-04) exists
        precisely to make his term nonzero, so his zero here is now a
        statement about the DEFAULT path only. SEJUANI is the replacement and
        is a valid zero under BOTH flags: her W Winter's Wrath is PHYSICAL
        with a large dps (11.0029 at level 16 on this target, so the control
        is not vacuous), ``ap_pct_sum`` 800.0 so the all-or-nothing gate drops
        it, and ``ad_pct_sum`` 0.0 so its AD SHARE is exactly zero and the
        split cannot re-admit it either. See
        ``tests/test_ad_axis_dual_scaling_split_rm36.py``, which pins her
        against the armed seam.
        """
        for champ in ("Ezreal", "Sejuani"):
            self.assertEqual(_ad_term(champ), 0.0, champ)
            self.assertEqual(_order(_rank(champ)),
                             _order(_rank(champ, apply_ad_axis_ability_damage=True)))

    def test_corki_term_is_nonzero_so_the_reorder_test_is_not_vacuous(self):
        """The RM-38 half DOES reach its champion - measured, not assumed.

        Corki carries two PHYSICAL rows at ``ap_pct_sum`` 0.0 (dps 2.738 and
        5.551 at level 16 on the tanky target), so his credited sum is real
        and the reorder above is not an artifact of an empty term.
        """
        self.assertGreater(_ad_term("Corki"), 0.0)



class AdAxisCarryRoutePlumbTest(unittest.TestCase):
    """All THREE gates, per the RM-115 / RM-118 seam doctrine.

    A seam is only reachable when the engine kwarg, the route parse AND
    ``core/daemon_slayer_client`` all carry it - the client is the chokepoint
    every build table and coach tick passes through. Wiring only the first two
    ships a seam that is settable and arithmetically inert.
    """

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer import server

        server._CACHE.set(_SNAP)

    def test_route_rank_parses_and_forwards_the_flag(self):
        from agents.daemon_slayer import server

        seen = {}

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            raise _Stop

        class _Stop(Exception):
            pass

        real = server.rank_items
        server.rank_items = _spy
        try:
            with self.assertRaises(_Stop):
                server._route_rank(
                    {
                        "champion": "Corki",
                        "level": 16,
                        "mode": "SR",
                        "apply_ad_axis_ability_damage": True,
                    }
                )
        finally:
            server.rank_items = real
        self.assertTrue(seen.get("apply_ad_axis_ability_damage"))

    def test_route_rank_omits_the_flag_by_default(self):
        from agents.daemon_slayer import server

        seen = {}

        class _Stop(Exception):
            pass

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            raise _Stop

        real = server.rank_items
        server.rank_items = _spy
        try:
            with self.assertRaises(_Stop):
                server._route_rank({"champion": "Corki", "level": 16, "mode": "SR"})
        finally:
            server.rank_items = real
        self.assertFalse(seen.get("apply_ad_axis_ability_damage"))

    def test_client_puts_the_flag_on_the_wire_only_when_armed(self):
        import core.daemon_slayer_client as dsc

        bodies = []

        def _post(path, body, *a, **kw):
            bodies.append(body)
            return {"ranked": [], "baseline_dps": 0.0}

        real = dsc._post_json
        dsc._post_json = _post
        try:
            dsc.rank_for("Corki", level=16, item_ids=[], apply_ad_axis_ability_damage=True)
            dsc.rank_for("Corki", level=16, item_ids=[])
        finally:
            dsc._post_json = real
        self.assertTrue(bodies[0].get("apply_ad_axis_ability_damage"))
        self.assertNotIn("apply_ad_axis_ability_damage", bodies[1])


if __name__ == "__main__":
    unittest.main()
