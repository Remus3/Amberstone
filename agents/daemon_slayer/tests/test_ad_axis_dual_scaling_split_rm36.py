"""RM-36 - the AD PORTION of a dual-scaling row reaches the AD-axis term.

The RM-39 / RM-43 AD-axis ability term drops any row whose ``ap_pct_sum`` is
nonzero. That AP-SCALING EXCLUSION is deliberate and stays, but it is
all-or-nothing, so a row that scales with BOTH AD and AP contributes exactly
nothing. Measured 2026-08-04 at level 16 on the sweep-standard tanky target,
Ezreal's only PHYSICAL row is Q Mystic Shot (dps 18.4472) and its
``ap_pct_sum`` is 200.0, so his credited sum is exactly 0.0 - the AD-caster
the CARRY-ranker port (RM-36 / RM-38) was built for is the one champion it
cannot reach.

``apply_ad_axis_dual_scaling_split`` (DEFAULT-OFF) ships the AD half of such a
row: a credit of ``dps * ad_pct_sum / (ad_pct_sum + ap_pct_sum)``. That mirrors
the honest-50-pct treatment the term's docstring already describes for MIXED,
where ``_mitigation_factor`` splits the row 50/50 across armor and MR
(``ability_dps.py:385``); the difference is that a dual-SCALING row carries its
own split ratio in its blocks, so the share is read rather than assumed.

THE SPLIT IS PHYSICAL-ONLY, AND THAT IS THE GUARD, NOT AN OVERSIGHT.
Roster-wide there is exactly ONE dual-scaling TRUE row - Belveth R Endless
Banquet, ``ap_pct_sum`` 300.0 against ``ad_pct_sum`` 36.0 - and it is the row
the AP-scaling exclusion was written to stop (with Chogath R Feast, which
carries ``ap_pct_sum`` 150.0 and ZERO AD scaling). A ratio split applied to
TRUE would re-admit Belveth R at a 10.7 pct share. The TRUE arm therefore
keeps its all-or-nothing gate and only PHYSICAL rows split. MAGIC stays
permanently excluded either way.

MEASURED POPULATION (level 16, tanky target, empty build): 24 PHYSICAL
dual-scaling rows across 22 champions. The largest are Pantheon Q (share
0.7931), Ezreal Q (0.7647) and Kalista E (0.7143).

VAYNE Q TUMBLE IS NOW CREDITED - a decision, and the one the term's docstring
flagged as "MEASURED COLLATERAL". She is PHYSICAL with ``total_ad_pct``
75..115 and ``ap_pct`` 50.0 per rank (sums 475.0 AD / 250.0 AP), so she takes
a 0.6552 share of her 3.7884 dps. Her TRUE W Silver Bolts row is untouched -
it carries no AP scaling and was already credited in full.
"""

from __future__ import annotations

import dataclasses
import unittest

from agents.daemon_slayer import rank
from agents.daemon_slayer._ad_axis_ability import physical_ability_damage
from agents.daemon_slayer.ability_dps import (
    AbilitySpellDps,
    compute_ability_dps,
    _form_ad_pct_sum,
)
from agents.daemon_slayer.data_loader import DataSnapshot

SR = "SR"
LEVEL = 16
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)

_SNAP = DataSnapshot.load()

# Rabadon's Deathcap - the item the MAGIC exclusion is pinned on (RM-39 L2:
# crediting MAGIC climbs it 55 places for Udyr).
_RABADONS = "3089"


def _ability(champion: str):
    return compute_ability_dps(
        _SNAP, champion_id=champion, level=LEVEL, item_ids=[], mode=SR, **TARGET
    )


def _row(champion: str, key: str):
    return next(r for r in _ability(champion).per_spell if r.key == key)


def _term(champion: str, **kwargs) -> float:
    return physical_ability_damage(
        _SNAP, champion, LEVEL, (), SR,
        TARGET["target_armor"], TARGET["target_mr"],
        TARGET["target_max_hp"], TARGET["target_bonus_hp"], (),
        **kwargs,
    )


def _rank(champion: str, **kwargs):
    return rank.rank_items(
        _SNAP, champion, level=LEVEL, current_item_ids=[], mode=SR,
        top_n=None, **TARGET, **kwargs,
    )


def _order(result):
    return [r.item_id for r in result.ranked]


def _raw_ad_pct_sum(champion_id: str, key: str, form_index: int = 0) -> float:
    """Independent re-derivation of a form's AD-scaling sum from raw blocks.

    Deliberately NOT a call into ``_form_ad_pct_sum`` - importing the engine's
    own extractor to check the engine's own field would be tautological. This
    mirrors ``_ap_pct_sum_for`` in ``test_kit_axis_ap_scaling_guard``.
    """
    from agents.daemon_slayer.abilities import load_default

    forms = load_default().get_abilities(champion_id).get(key, ())
    if not forms or form_index >= len(forms):
        return 0.0
    total = 0.0
    for block in forms[form_index].damage_blocks:
        if block.attribute_kind != "damage":
            continue
        if block.total_ad_pct:
            total += sum(block.total_ad_pct)
        if block.bonus_ad_pct:
            total += sum(block.bonus_ad_pct)
    return total


class AdPctSumFieldTests(unittest.TestCase):
    """The row must carry its OWN AD scaling, the mirror of ``ap_pct_sum``."""

    def test_field_exists_and_defaults_to_zero(self):
        row = AbilitySpellDps(
            key="Q", form_name="f", form_index=0, rank=1, cooldown=1.0,
            cost=0.0, damage_type="PHYSICAL", resource=None,
            raw_damage_per_cast=0.0, post_mode_damage_per_cast=0.0,
            post_mitigation_damage_per_cast=0.0, casts_per_sec=0.0,
            casts_per_sec_source="missing", mana_uptime_factor=1.0, dps=0.0,
        )
        self.assertEqual(row.ad_pct_sum, 0.0)

    def test_field_is_appended_at_the_end_of_the_dataclass(self):
        fields = list(dataclasses.fields(AbilitySpellDps))
        names = [f.name for f in fields]
        self.assertIn("ad_pct_sum", names)
        first_defaulted = next(
            i for i, f in enumerate(fields)
            if f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING
        )
        self.assertGreater(names.index("ad_pct_sum"), first_defaulted)

    def test_field_is_serialized(self):
        self.assertIn("ad_pct_sum", _row("Ezreal", "Q").to_dict())

    def test_ezreal_q_carries_its_ad_scaling(self):
        row = _row("Ezreal", "Q")
        self.assertAlmostEqual(row.ad_pct_sum, _raw_ad_pct_sum("Ezreal", "Q"))
        self.assertAlmostEqual(row.ad_pct_sum, 650.0)
        self.assertAlmostEqual(row.ap_pct_sum, 200.0)

    def test_vayne_q_carries_its_ad_scaling(self):
        row = _row("Vayne", "Q")
        self.assertAlmostEqual(row.ad_pct_sum, _raw_ad_pct_sum("Vayne", "Q"))
        self.assertAlmostEqual(row.ad_pct_sum, 475.0)

    def test_pure_ap_row_carries_zero_ad_scaling(self):
        self.assertEqual(_row("Chogath", "R").ad_pct_sum, 0.0)

    def test_extractor_reads_damage_blocks_only(self):
        """An AD-scaling HEAL does not make the spell's DAMAGE AD-scaling."""
        from agents.daemon_slayer.abilities import DamageBlock

        class _Form:
            damage_blocks = (
                DamageBlock(attribute="a", attribute_kind="damage",
                            total_ad_pct=(50.0, 50.0)),
                DamageBlock(attribute="b", attribute_kind="damage",
                            bonus_ad_pct=(10.0,)),
                DamageBlock(attribute="c", attribute_kind="heal",
                            total_ad_pct=(900.0,)),
            )

        self.assertAlmostEqual(_form_ad_pct_sum(_Form()), 110.0)


class DualScalingSplitTermTests(unittest.TestCase):
    """The term itself - RED before the seam exists."""

    def test_seam_defaults_off_ezreal_stays_zero(self):
        self.assertEqual(_term("Ezreal"), 0.0)
        self.assertEqual(
            _term("Ezreal", apply_dual_scaling_split=False), 0.0
        )

    def test_ezreal_q_is_credited_at_its_ad_share_when_armed(self):
        row = _row("Ezreal", "Q")
        share = row.ad_pct_sum / (row.ad_pct_sum + row.ap_pct_sum)
        armed = _term("Ezreal", apply_dual_scaling_split=True)
        self.assertGreater(armed, 0.0)
        self.assertAlmostEqual(armed, row.dps * share, places=9)
        # Pinned literals from the 2026-08-04 measurement.
        self.assertAlmostEqual(share, 0.7647, places=4)
        self.assertAlmostEqual(armed, 14.1067, places=3)

    def test_vayne_q_tumble_is_credited_and_her_true_row_is_unchanged(self):
        """The stated collateral of the AP gate, now repaired (a decision)."""
        off = _term("Vayne")
        on = _term("Vayne", apply_dual_scaling_split=True)
        q = _row("Vayne", "Q")
        share = q.ad_pct_sum / (q.ad_pct_sum + q.ap_pct_sum)
        self.assertAlmostEqual(on - off, q.dps * share, places=9)
        self.assertAlmostEqual(share, 0.6552, places=4)
        # W Silver Bolts is TRUE with zero AP scaling - already fully credited
        # OFF, so it is inside ``off`` and the split adds nothing for it.
        w = _row("Vayne", "W")
        self.assertEqual(w.ap_pct_sum, 0.0)
        self.assertGreaterEqual(off, w.dps)

    def test_belveth_r_stays_excluded_the_split_is_physical_only(self):
        """The ONLY dual-scaling TRUE row on the roster must not re-enter.

        A ratio split applied to TRUE would credit it at 36/(36+300) = 10.7
        pct. The AP-scaling exclusion exists for exactly this row, so the TRUE
        arm keeps its all-or-nothing gate.
        """
        r = _row("Belveth", "R")
        self.assertEqual((r.damage_type or "").upper(), "TRUE")
        self.assertGreater(r.ap_pct_sum, 0.0)
        self.assertGreater(r.ad_pct_sum, 0.0)   # dual-scaling, not AP-pure
        self.assertGreater(r.dps, 0.0)          # non-vacuous
        self.assertEqual(
            _term("Belveth"), _term("Belveth", apply_dual_scaling_split=True)
        )

    def test_chogath_r_stays_excluded_and_his_term_stays_zero(self):
        r = _row("Chogath", "R")
        self.assertEqual((r.damage_type or "").upper(), "TRUE")
        self.assertGreater(r.ap_pct_sum, 0.0)
        self.assertEqual(_term("Chogath"), 0.0)
        self.assertEqual(_term("Chogath", apply_dual_scaling_split=True), 0.0)

    def test_zero_dual_row_champions_are_byte_identical(self):
        """Aatrox and Corki carry NO dual-scaling row - they must not move."""
        for champ in ("Aatrox", "Corki"):
            with self.subTest(champion=champ):
                self.assertGreater(_term(champ), 0.0)
                self.assertEqual(
                    _term(champ),
                    _term(champ, apply_dual_scaling_split=True),
                )

    def test_udyr_is_untouched_so_the_magic_exclusion_still_holds(self):
        """Udyr's Q is PHYSICAL at ``ap_pct_sum`` 0.0 and his R is MAGIC.

        Neither is a dual-scaling PHYSICAL row, so the split cannot move him -
        which is what keeps the RM-39 Rabadon's-55-places result intact.
        """
        self.assertEqual(_row("Udyr", "Q").ap_pct_sum, 0.0)
        self.assertEqual((_row("Udyr", "R").damage_type or "").upper(), "MAGIC")
        self.assertEqual(
            _term("Udyr"), _term("Udyr", apply_dual_scaling_split=True)
        )


class DualScalingSplitZeroControlTests(unittest.TestCase):
    """SEJUANI is the replacement zero-term control (RM-36, 2026-08-04).

    Ezreal was the seam's zero-term control and the split destroys it - his
    term is the whole point of this change. Sejuani replaces him and is
    STRICTLY SHARPER, because her zero survives the split for a MECHANICAL
    reason that a careless future widen would break loudly:

    * her W Winter's Wrath is PHYSICAL and carries a LARGE dps (11.0029 at
      level 16 on the tanky target - bigger than Ezreal's whole Q), so the
      control is not vacuous;
    * it carries ``ap_pct_sum`` 800.0, so the all-or-nothing AP gate drops it;
    * and it carries ``ad_pct_sum`` 0.0, so its AD SHARE is exactly zero and
      the split cannot re-admit it either.

    That covers BOTH surviving exclusion arms at once. MUTATION-PROVEN
    2026-08-04: dropping the ``ad_pct_sum > 0`` guard and returning a flat
    share turns her term from 0.0 into a large number and fails the two
    Sejuani tests below. (Keeping that guard while flattening the ratio moves
    Ezreal and Vayne instead, and is caught there - between them the two
    controls pin the share formula from both sides.) Chogath is carried
    alongside as the TRUE-arm half of the same control.
    """

    def test_sejuani_w_is_the_mechanical_zero_and_is_not_vacuous(self):
        w = _row("Sejuani", "W")
        self.assertEqual((w.damage_type or "").upper(), "PHYSICAL")
        self.assertGreater(w.dps, 10.0)
        self.assertGreater(w.ap_pct_sum, 0.0)
        self.assertEqual(w.ad_pct_sum, 0.0)

    def test_sejuani_term_is_zero_off_and_on(self):
        self.assertEqual(_term("Sejuani"), 0.0)
        self.assertEqual(_term("Sejuani", apply_dual_scaling_split=True), 0.0)

    def test_sejuani_rank_order_is_untouched_by_the_armed_seam(self):
        off = _rank("Sejuani")
        on = _rank(
            "Sejuani",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=True,
        )
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(off.baseline_dps, on.baseline_dps)


class DualScalingSplitRankerTests(unittest.TestCase):
    """The CARRY ranker - the RM-36 acceptance criterion."""

    def test_ranker_defaults_off_and_is_byte_identical(self):
        base = _rank("Ezreal", apply_ad_axis_ability_damage=True)
        explicit = _rank(
            "Ezreal",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=False,
        )
        self.assertEqual(_order(base), _order(explicit))
        self.assertEqual(base.baseline_dps, explicit.baseline_dps)

    def test_the_split_is_inert_without_the_parent_flag(self):
        """The split is a MODIFIER of the AD-axis term, not a second term."""
        off = _rank("Ezreal")
        split_only = _rank("Ezreal", apply_ad_axis_dual_scaling_split=True)
        self.assertEqual(_order(off), _order(split_only))
        self.assertEqual(off.baseline_dps, split_only.baseline_dps)

    def test_ezreal_reorders_when_both_flags_are_armed(self):
        off = _rank("Ezreal")
        on = _rank(
            "Ezreal",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=True,
        )
        self.assertNotEqual(_order(off), _order(on))

    def test_ezreal_baseline_lifts_by_exactly_the_split_credit(self):
        off = _rank("Ezreal", apply_ad_axis_ability_damage=True)
        on = _rank(
            "Ezreal",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=True,
        )
        self.assertAlmostEqual(
            on.baseline_dps - off.baseline_dps,
            _term("Ezreal", apply_dual_scaling_split=True),
            places=6,
        )

    def test_delta_stays_consistent_with_new_dps(self):
        on = _rank(
            "Ezreal",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=True,
        )
        for row in on.ranked[:20]:
            self.assertAlmostEqual(
                row.delta_dps, row.new_dps - on.baseline_dps, places=6
            )

    def test_rabadons_does_not_move_for_udyr(self):
        """The MAGIC-exclusion result must survive this change."""
        off = _order(_rank("Udyr", apply_ad_axis_ability_damage=True))
        on = _order(_rank(
            "Udyr",
            apply_ad_axis_ability_damage=True,
            apply_ad_axis_dual_scaling_split=True,
        ))
        self.assertIn(_RABADONS, off)
        self.assertEqual(off.index(_RABADONS), on.index(_RABADONS))
        self.assertEqual(off, on)


class DualScalingSplitRoutePlumbTests(unittest.TestCase):
    """All THREE gates - engine kwarg, route parse, client body."""

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer import server

        server._CACHE.set(_SNAP)

    def _spy_route(self, route_name: str, body: dict) -> dict:
        from agents.daemon_slayer import server

        seen: dict = {}

        class _Stop(Exception):
            pass

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            raise _Stop

        target = "rank_items" if route_name == "rank" else "rank_items_by_hybrid"
        real = getattr(server, target)
        setattr(server, target, _spy)
        try:
            route = getattr(server, f"_route_{route_name}")
            with self.assertRaises(_Stop):
                route(body)
        finally:
            setattr(server, target, real)
        return seen

    def test_route_rank_parses_and_forwards_the_flag(self):
        seen = self._spy_route("rank", {
            "champion": "Ezreal", "level": 16, "mode": "SR",
            "apply_ad_axis_ability_damage": True,
            "apply_ad_axis_dual_scaling_split": True,
        })
        self.assertTrue(seen.get("apply_ad_axis_dual_scaling_split"))

    def test_route_rank_omits_the_flag_by_default(self):
        seen = self._spy_route(
            "rank", {"champion": "Ezreal", "level": 16, "mode": "SR"}
        )
        self.assertFalse(seen.get("apply_ad_axis_dual_scaling_split"))

    def test_route_rank_bruiser_parses_and_forwards_the_flag(self):
        seen = self._spy_route("rank_bruiser", {
            "champion": "Pantheon", "level": 16, "mode": "SR",
            "apply_ad_axis_ability_damage": True,
            "apply_ad_axis_dual_scaling_split": True,
        })
        self.assertTrue(seen.get("apply_ad_axis_dual_scaling_split"))

    def test_client_puts_the_flag_on_the_wire_only_when_armed(self):
        import core.daemon_slayer_client as dsc

        bodies: list = []

        def _post(path, body, *a, **kw):
            bodies.append(body)
            return {"ranked": [], "baseline_dps": 0.0}

        real = dsc._post_json
        dsc._post_json = _post
        try:
            dsc.rank_for(
                "Ezreal", level=16, item_ids=[],
                apply_ad_axis_ability_damage=True,
                apply_ad_axis_dual_scaling_split=True,
            )
            dsc.rank_for("Ezreal", level=16, item_ids=[])
        finally:
            dsc._post_json = real
        self.assertTrue(bodies[0].get("apply_ad_axis_dual_scaling_split"))
        self.assertNotIn("apply_ad_axis_dual_scaling_split", bodies[1])

    def test_bruiser_client_puts_the_flag_on_the_wire_only_when_armed(self):
        import core.daemon_slayer_client as dsc

        bodies: list = []

        def _post(path, body, *a, **kw):
            bodies.append(body)
            return {"ranked": [], "baseline_score": 0.0}

        real = dsc._post_json
        dsc._post_json = _post
        try:
            dsc.rank_bruiser_for(
                "Pantheon", level=16, item_ids=[],
                apply_ad_axis_ability_damage=True,
                apply_ad_axis_dual_scaling_split=True,
            )
            dsc.rank_bruiser_for("Pantheon", level=16, item_ids=[])
        finally:
            dsc._post_json = real
        self.assertTrue(bodies[0].get("apply_ad_axis_dual_scaling_split"))
        self.assertNotIn("apply_ad_axis_dual_scaling_split", bodies[1])


if __name__ == "__main__":
    unittest.main()
