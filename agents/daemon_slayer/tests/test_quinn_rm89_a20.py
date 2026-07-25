"""A-20 / RM-89 Quinn - the two slices the row's thesis needs.

FILED SYMPTOM (docs/DS_SWEEP_TRACKER.md, batch19 Quinn entry): the production
carry / ``ds.dps`` route leads Blade of the Ruined King #1, Runaan's Hurricane
#2, Kraken Slayer #3 for a champion whose real builds are ~85-90 pct lethality
burst and **~0 pct on-hit**, while her lethality core (Collector / Voltaic /
Youmuu's / Edge of Night / Serylda's / Hubris) sits #12 and below. Two
independent causes, and BOTH must be fixed or the row is not discharged:

  * RC-1 kit blindness (RM-86 L1). The engine credits attack speed and on-hit at
    face value, but Harrier - her only empowered attack - sits on a STATIC
    cooldown (``champion_abilities.json`` 16.14.1 Quinn P: ``cooldown``
    ``[8.0, 8.0, 8.0]``), so purchased attack speed does not raise its proc rate
    at all. Measured 2026-07-25 in the main thread: ``_KIT_CONVERSION`` held
    exactly 8 champions and **Quinn was not one**, so the L1 lever returned
    ``_IDENTITY`` and was exactly inert for her (0 of 104 rows moved at
    ``kit_conversion_strength`` 0.0 -> 1.0, against 116 of 134 for Naafiri).
    The filed claim that L1 already suppressed her bad leads was FALSE.

  * RC-2 pool exclusion. Profane Hydra (6698, her second-most-picked item at
    ~12k games) and Umbral Glaive (3179) are not merely low-ranked, they are not
    in the candidate pool: both names sit in
    ``rank.OFFCLASS_MARKSMAN_ITEM_NAMES`` behind ``_is_ranged_marksman``, and
    Quinn (Marksman tag, 525 attackrange) trips that gate. ``widen_carry_pool``
    (shipped 1.242.0) does NOT reach them - its four-name set is Black Cleaver /
    Spear of Shojin / Stridebreaker / Sterak's Gage. The narrow fix is a
    per-champion ``marksman_offclass_exempt.json`` entry, not a class-wide
    widen: no other ranged marksman should be handed a bruiser hydra.

L1 CAN ONLY DEMOTE (``kit_conversion.conversion_factor`` never returns above
1.0), so the acceptance below is that her BAD LEADS FALL, never that a good item
rises on its own merit. And pool-widening alone was measured to change ZERO
top-8 entries - asserted here as a fact, not hoped away.

BOTH seams stay DEFAULT-OFF. The L1 lever is gated on
``kit_conversion_strength > 0.0``; the exemption table is gated on
``rank_items(exempt_offclass_by_win=True)`` (``rank.py:1146``). Byte-identical
defaults are asserted first because everything else is worthless without them.
"""

import json
import unittest

from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.kit_conversion import kit_conversion, registry_champion_ids
from agents.daemon_slayer.rank import rank_items

BOTRK = "3153"
RUNAANS = "3085"
KRAKEN = "6672"
PROFANE_HYDRA = "6698"
UMBRAL_GLAIVE = "3179"

# Her real lethality core (tracker: Profane Hydra or Hubris -> boots ->
# Collector -> Edge of Night -> Lord Dominik's -> Infinity Edge).
COLLECTOR = "6676"
VOLTAIC = "6699"
EDGE_OF_NIGHT = "3814"
SERYLDAS = "6694"
HUBRIS = "6697"

# Non-empty build + non-zero target stats: both DS probe traps. A rank measured
# at an empty item list has manufactured five false headlines to date.
BUILD = ["3142", "3158"]  # Youmuu's Ghostblade + Ionian Boots of Lucidity
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)


class QuinnHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _carry(self, champ="Quinn", **kw):
        res = rank_items(
            self.snap, champ, 13, current_item_ids=BUILD, mode="SR",
            top_n=200, **TARGET, **kw
        )
        return [r.item_id for r in res.ranked]

    def _assassin(self, champ="Quinn", **kw):
        res = rank_items_by_burst(
            self.snap, champ, 13, current_item_ids=BUILD, mode="SR",
            top_n=200, **TARGET, **kw
        )
        return [r.item_id for r in res.ranked]

    def _rank_of(self, ids, item_id):
        return ids.index(item_id) + 1 if item_id in ids else None


class DefaultOffTests(QuinnHarness):
    """Neither slice may move anything at the shipped defaults."""

    def test_l1_omitted_equals_explicit_zero_on_both_routes(self):
        self.assertEqual(self._carry(), self._carry(kit_conversion_strength=0.0))
        self.assertEqual(self._assassin(), self._assassin(kit_conversion_strength=0.0))

    def test_l1_zero_does_not_mutate_any_row_field(self):
        off = rank_items(self.snap, "Quinn", 13, current_item_ids=BUILD,
                         mode="SR", top_n=200, **TARGET)
        zero = rank_items(self.snap, "Quinn", 13, current_item_ids=BUILD,
                          mode="SR", top_n=200, kit_conversion_strength=0.0, **TARGET)
        self.assertEqual(
            [r.to_dict() for r in off.ranked], [r.to_dict() for r in zero.ranked]
        )

    def test_exemption_table_is_default_off_for_quinn(self):
        # The seam is gated: with it OFF, the two items stay out of the pool
        # even though the table now names them.
        pool = self._carry()
        self.assertNotIn(PROFANE_HYDRA, pool)
        self.assertNotIn(UMBRAL_GLAIVE, pool)


class NegativeControlTests(QuinnHarness):
    """Neither slice may touch a champion it does not name."""

    def test_unseeded_marksmen_are_byte_identical_under_l1(self):
        for champ in ("Jinx", "Caitlyn"):
            with self.subTest(champion=champ):
                self.assertNotIn(champ, registry_champion_ids())
                self.assertEqual(
                    self._carry(champ), self._carry(champ, kit_conversion_strength=1.0)
                )

    def test_untabled_marksmen_are_byte_identical_under_the_exemption_seam(self):
        for champ in ("Jinx", "Caitlyn"):
            with self.subTest(champion=champ):
                self.assertEqual(
                    self._carry(champ),
                    self._carry(champ, exempt_offclass_by_win=True),
                )

    def test_pre_existing_tabled_champion_still_diverges(self):
        # Ezreal is the DSP2 anchor. Adding Quinn must not disturb him.
        self.assertNotEqual(
            self._carry("Ezreal"),
            self._carry("Ezreal", exempt_offclass_by_win=True),
        )


class Slice1KitConversionTests(QuinnHarness):
    """RC-1: seed Quinn so the L1 lever stops being inert for her."""

    def test_quinn_is_seeded(self):
        self.assertIn("Quinn", registry_champion_ids())

    def test_vector_shape_matches_the_prose(self):
        conv = kit_conversion("Quinn")
        self.assertTrue(conv.note.strip(), "every seed needs prose evidence")
        # Harrier is static-cooldown and does not crit; her real builds are
        # ~0 pct on-hit. All three offensive channels must be BELOW face value.
        self.assertLess(conv.attack_speed, 1.0)
        self.assertLess(conv.on_hit, 1.0)
        self.assertLess(conv.crit, 1.0)
        for channel in ("attack_speed", "crit", "on_hit", "off_axis_stat"):
            value = getattr(conv, channel)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_off_axis_channel_is_left_at_face_value(self):
        # Deliberate over-fire guard, the Blackfire shape from RM-86. Edge of
        # Night (3814) carries 350 HP and IS a real Quinn core item; an
        # off_axis_stat below 1.0 penalises it at 0.05x and demotes her own
        # build. HP converting to zero DPS is true of EVERY AD carry, so it is
        # a class-wide statement, not Quinn kit signal.
        self.assertEqual(kit_conversion("Quinn").off_axis_stat, 1.0)

    def test_botrk_leaves_top1_on_the_carry_route(self):
        self.assertEqual(self._carry()[0], BOTRK)
        after = self._carry(kit_conversion_strength=1.0)
        self.assertNotEqual(after[0], BOTRK)
        self.assertGreater(self._rank_of(after, BOTRK), 20)

    def test_the_on_hit_head_leaves_the_top_ten(self):
        before = self._carry()
        after = self._carry(kit_conversion_strength=1.0)
        for item in (BOTRK, RUNAANS, KRAKEN):
            with self.subTest(item=item):
                self.assertLessEqual(self._rank_of(before, item), 3)
                self.assertGreater(self._rank_of(after, item), 10)

    def test_lethality_core_rises(self):
        before = self._carry()
        after = self._carry(kit_conversion_strength=1.0)
        for item in (COLLECTOR, VOLTAIC, EDGE_OF_NIGHT, SERYLDAS, HUBRIS):
            with self.subTest(item=item):
                self.assertLess(
                    self._rank_of(after, item), self._rank_of(before, item)
                )

    def test_botrk_leaves_top1_on_the_assassin_route(self):
        # The tracker records that no reroute rescues her - assassin, onhit and
        # bruiser all still lead BotRK. The seed must fix the champion, not one
        # route.
        self.assertEqual(self._assassin()[0], BOTRK)
        self.assertNotEqual(self._assassin(kit_conversion_strength=1.0)[0], BOTRK)

    def test_gate_never_improves_a_penalised_item(self):
        ranks = [
            self._rank_of(self._carry(kit_conversion_strength=s), BOTRK)
            for s in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        for weaker, stronger in zip(ranks, ranks[1:]):
            self.assertGreaterEqual(stronger, weaker, f"rank improved: {ranks}")


class Slice2PoolTests(QuinnHarness):
    """RC-2: the two signature items must be able to enter the pool at all."""

    def test_quinn_trips_the_offclass_gate(self):
        # If this ever goes False the exemption entry is dead weight.
        self.assertTrue(rank_mod._is_ranged_marksman(self.snap.champions["Quinn"]))

    def test_table_names_are_actually_denied_names(self):
        # An exemption for a name the deny-set never strips is a silent no-op.
        exempt = rank_mod._offclass_win_exemptions(
            "Quinn", self.snap.champions["Quinn"]
        )
        self.assertEqual(exempt, frozenset({"Profane Hydra", "Umbral Glaive"}))
        for name in exempt:
            self.assertIn(name, rank_mod.OFFCLASS_MARKSMAN_ITEM_NAMES, name)

    def test_table_file_stays_ascii_and_parses(self):
        raw = rank_mod._OFFCLASS_EXEMPT_PATH.read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])
        data = json.loads(raw.decode("ascii"))
        self.assertIn("Quinn", data["champions"])

    def test_seam_on_admits_exactly_the_two_items(self):
        off = self._carry()
        on = self._carry(exempt_offclass_by_win=True)
        self.assertIn(PROFANE_HYDRA, on)
        self.assertIn(UMBRAL_GLAIVE, on)
        self.assertEqual(
            set(on) - set(off), {PROFANE_HYDRA, UMBRAL_GLAIVE}
        )
        self.assertEqual(set(off) - set(on), set())

    def test_widen_carry_pool_does_not_reach_them(self):
        # The measured reason this slice is needed at all: the shipped
        # class-wide widen names four other items.
        widened = self._carry(widen_carry_pool=True)
        self.assertNotIn(PROFANE_HYDRA, widened)
        self.assertNotIn(UMBRAL_GLAIVE, widened)

    def test_pool_widening_alone_does_not_move_the_head(self):
        # Measured, and asserted rather than wished away: slice 2 on its own
        # changes ZERO top-8 entries. This is why both slices are required.
        self.assertEqual(
            self._carry()[:8], self._carry(exempt_offclass_by_win=True)[:8]
        )


class CombinedThesisTests(QuinnHarness):
    """The row is only discharged when both slices are on together."""

    def test_both_slices_together(self):
        both = self._carry(exempt_offclass_by_win=True, kit_conversion_strength=1.0)
        # bad leads gone from the head
        self.assertNotIn(both[0], (BOTRK, RUNAANS, KRAKEN))
        for item in (BOTRK, RUNAANS, KRAKEN):
            self.assertGreater(self._rank_of(both, item), 10, item)
        # signature items present and inside the top 20
        for item in (PROFANE_HYDRA, UMBRAL_GLAIVE):
            self.assertIsNotNone(self._rank_of(both, item), item)
            self.assertLessEqual(self._rank_of(both, item), 20, item)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
