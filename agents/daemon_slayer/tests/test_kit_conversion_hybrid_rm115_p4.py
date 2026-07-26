"""RM-115 p4: the RM-86 L1 kit-conversion gate reaches the BRUISER scorer.

``hybrid.py`` carried ZERO occurrences of ``kit_conversion_strength`` until
ENGINE 1.252.0, so the four bruiser entries in ``kit_conversion._KIT_CONVERSION``
- Olaf, Pantheon, RekSai, Riven - were stranded at GATE 1, before any route or
client question arose. ``rank_items_by_hybrid`` is the only target: it is the
one entry point in the module that SORTS, and the RM-86 transform is a sort-key
transform (``kit_conversion.py:16-18``: the module supplies the vector, each
ranker scales its own sort key). ``compute_hybrid`` scores a single resolved
build and has no sort key, so the kwarg would be inert there.

THE OBJECTIVE STRING IS THE LOAD-BEARING DECISION HERE
------------------------------------------------------
``conversion_factor`` consults the objective ONLY through ``_OFF_AXIS_KEYS``,
i.e. only through the ``off_axis_stat`` channel. ds.hybrid scores
``alpha*dps + beta*ehp``, so a stat is off-axis for it only when it is off-axis
for BOTH terms - the INTERSECTION of the damage set and the ``"ehp"`` set.

Passing the bare damage axis (``"ad"`` / ``"ap"``) instead would be INERT for
all four bruiser entries, because their ``off_axis_stat`` is 1.00 and a
zero shortfall skips the channel entirely. It is emphatically NOT inert for the
two registry entries whose ``off_axis_stat`` is 0.00 - Naafiri and Orianna - and
``/rank-bruiser`` accepts any champion. Measured at strength 1.0, the bare axis
multiplies Warmog's, Randuin's, Thornmail, Dead Man's Plate and Sterak's Gage by
EXACTLY 0.0 for both of them: total suppression of every tank item, on a scorer
whose beta term IS effective HP. ``test_hybrid_objective_protects_ehp_stats``
pins that, so the cheaper option cannot be quietly substituted later.

ANCHOR CHOICE
-------------
Control is **Darius** - a tabled bruiser ABSENT from ``_KIT_CONVERSION``, so
``kit_conversion`` returns the identity and every channel factor is exactly 1.0.
He must not move at any strength.

Do NOT anchor on Stridebreaker: ``kit_conversion.py:54-58`` records that Olaf's
Stridebreaker rising is not reachable at any setting and is filed as L2
objective-coverage work. Measured here at #34 -> #34, consistent with that note.

OFFLINE: loads the DataSnapshot, no server, no network.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.kit_conversion import (
    _OFF_AXIS_KEYS,
    conversion_factor,
    kit_conversion,
)

_BOTRK = "3153"
_TRINITY = "3078"
_STRIDEBREAKER = "6631"

# HP / resist items: off-axis under a bare damage objective, ON-axis for the
# blended one because they are precisely what the beta term scores.
_EHP_ITEMS = ("3083", "3143", "3075", "3742", "3053")


def _rank(snap, champion, **extra):
    res = rank_items_by_hybrid(
        snap,
        champion_id=champion,
        level=11,
        current_item_ids=["3071", "3111"],
        mode="SR",
        target_armor=60.0,
        target_mr=50.0,
        target_max_hp=2200.0,
        target_bonus_hp=1000.0,
        top_n=300,
        **extra,
    )
    return [r.item_id for r in res.ranked]


class KitConversionHybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ------------------------------------------------------ the default is inert
    def test_zero_strength_is_byte_identical_to_omitting_the_kwarg(self) -> None:
        for champ in ("Olaf", "Riven", "Pantheon", "RekSai", "Darius"):
            self.assertEqual(
                _rank(self.snap, champ),
                _rank(self.snap, champ, kit_conversion_strength=0.0),
                f"{champ}: strength 0.0 must not differ from omitting the kwarg",
            )

    def test_unregistered_champion_is_byte_identical_at_full_strength(self) -> None:
        """Darius - the named control. Identity conversion, so nothing moves."""
        conv = kit_conversion("Darius", self.snap.champions.get("Darius"))
        for channel in ("attack_speed", "crit", "on_hit", "off_axis_stat"):
            self.assertEqual(
                getattr(conv, channel), 1.0,
                "Darius must resolve to the identity conversion, or he is not a "
                "valid control for this seam",
            )
        self.assertEqual(
            _rank(self.snap, "Darius"),
            _rank(self.snap, "Darius", kit_conversion_strength=1.0),
            "Darius is absent from _KIT_CONVERSION and must not move at any "
            "strength",
        )

    # ------------------------------------------------------------- the ship
    def test_olaf_head_changes_at_full_strength(self) -> None:
        off = _rank(self.snap, "Olaf")
        on = _rank(self.snap, "Olaf", kit_conversion_strength=1.0)
        self.assertEqual(off[0], _BOTRK, "fixture drift: Olaf no longer leads BotRK")
        self.assertNotEqual(
            on[0], _BOTRK,
            "Blade of the Ruined King must not survive as Olaf's #1 once his "
            "kit is told it already supplies attack speed",
        )
        self.assertEqual(
            on[0], _TRINITY,
            "Trinity Force should take the head - its attack-speed exposure is "
            "the smallest among Olaf's former top candidates",
        )

    def test_all_four_registry_bruisers_move(self) -> None:
        for champ in ("Olaf", "Riven", "Pantheon", "RekSai"):
            self.assertNotEqual(
                _rank(self.snap, champ),
                _rank(self.snap, champ, kit_conversion_strength=1.0),
                f"{champ} is in _KIT_CONVERSION but the bruiser ranking did not "
                "respond to the gate",
            )

    def test_botrk_rank_is_monotone_in_strength(self) -> None:
        seen = []
        for s in (0.0, 0.25, 0.5, 0.75, 1.0):
            order = _rank(self.snap, "Olaf", kit_conversion_strength=s)
            seen.append(order.index(_BOTRK))
        for earlier, later in zip(seen, seen[1:]):
            self.assertLessEqual(
                earlier, later,
                f"BotRK's index must not improve as the gate strengthens: {seen}",
            )
        self.assertLess(seen[0], seen[-1], f"no movement across the sweep: {seen}")

    def test_stridebreaker_is_not_an_anchor(self) -> None:
        """Guard the documented negative (kit_conversion.py:54-58)."""
        off = _rank(self.snap, "Olaf")
        on = _rank(self.snap, "Olaf", kit_conversion_strength=1.0)
        self.assertEqual(
            off.index(_STRIDEBREAKER), on.index(_STRIDEBREAKER),
            "Stridebreaker is recorded as unreachable at any setting; if it "
            "moved, the objective-coverage note needs revisiting rather than "
            "this assertion being relaxed",
        )

    # ------------------------------------------- why the objective is blended
    def test_hybrid_off_axis_sets_are_the_measured_intersection(self) -> None:
        self.assertEqual(
            _OFF_AXIS_KEYS["hybrid_ad"], _OFF_AXIS_KEYS["ad"] & _OFF_AXIS_KEYS["ehp"]
        )
        self.assertEqual(
            _OFF_AXIS_KEYS["hybrid_ap"], _OFF_AXIS_KEYS["ap"] & _OFF_AXIS_KEYS["ehp"]
        )

    def test_hybrid_objective_protects_ehp_stats(self) -> None:
        """The reason the bare damage axis was REJECTED for this scorer.

        Naafiri and Orianna are the two registry entries with
        ``off_axis_stat == 0.00``. Under a bare damage objective every tank item
        collapses to a factor of exactly 0.0 for them; under the blended one it
        stays 1.0, because health and resists are what the beta term scores.
        """
        for champ, axis in (("Naafiri", "ad"), ("Orianna", "ap")):
            conv = kit_conversion(champ, self.snap.champions.get(champ))
            self.assertEqual(
                conv.off_axis_stat, 0.0,
                f"{champ} is only a meaningful witness while her off_axis_stat "
                "is 0.00",
            )
            for iid in _EHP_ITEMS:
                rec = self.snap.items.get(iid) or {}
                bare = conversion_factor(conv, iid, rec, 1.0, axis)
                blended = conversion_factor(conv, iid, rec, 1.0, f"hybrid_{axis}")
                self.assertEqual(
                    bare, 0.0,
                    f"{champ}/{iid}: the bare {axis} objective is supposed to "
                    "annihilate this item - if it no longer does, the rationale "
                    "for the blended objective has changed",
                )
                self.assertEqual(
                    blended, 1.0,
                    f"{champ}/{iid}: the blended objective must leave an "
                    "EHP-scoring item untouched",
                )

    def test_blended_objective_is_inert_for_the_four_bruisers(self) -> None:
        """Their off_axis_stat is 1.00, so the channel is skipped entirely."""
        for champ in ("Olaf", "Riven", "Pantheon", "RekSai"):
            conv = kit_conversion(champ, self.snap.champions.get(champ))
            self.assertEqual(conv.off_axis_stat, 1.0, champ)
            for iid in _EHP_ITEMS:
                rec = self.snap.items.get(iid) or {}
                self.assertEqual(
                    conversion_factor(conv, iid, rec, 1.0, "ad"),
                    conversion_factor(conv, iid, rec, 1.0, "hybrid_ad"),
                    f"{champ}/{iid}: the objective choice must not matter for a "
                    "champion whose off_axis_stat is 1.00",
                )


if __name__ == "__main__":
    unittest.main()
