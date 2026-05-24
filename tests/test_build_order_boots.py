"""Headless tests for boots-slot injection in core/build_order.py.

Pinned 2026-05-23 (item 164b - operator directive: boots in EVERY build
order on EVERY mode). Proves:

  1. Every plan_build_order call returns a result whose ``order``
     contains exactly one boots family entry (id in _BOOTS_IDS).
  2. The selected boots family matches the archetype + enemy AD/AP
     comp signal:
       - carry/dps + balanced comp -> Berserker's Greaves (3006)
       - mage + balanced comp      -> Sorcerer's Shoes   (3020)
       - tank + balanced comp      -> Plated Steelcaps   (3047)
       - assassin + balanced comp  -> Mobility Boots     (3117)
       - enchanter + balanced comp -> Ionian Boots       (3158)
       - high-armor enemy comp     -> Plated Steelcaps   (3047) for
                                       non-caster archetypes
       - high-MR enemy comp        -> Mercury's Treads   (3111) for
                                       non-dps archetypes
  3. Boots are NOT injected when the champion is in the bootsless-
     champion exception set (Yuumi, Cassiopeia).
  4. Boots are NOT re-injected when already present in owned_item_ids
     (operator manually purchased boots earlier).
  5. The injection sits at position 2 (after the first big item) when
     order has >=1 pick; at position 1 when order is shorter.
"""
from __future__ import annotations

import unittest

from core.build_order import (
    _BOOTS_IDS,
    _BOOTSLESS_CHAMPS,
    _select_boots,
    plan_build_order,
)


# Minimal fake engine - returns a single ranked row per call so the
# planner's iterative loop has something to pick. The picks don't matter
# for these tests; we only assert the boots injection happens after.
class _FakeRanker:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, champion, archetype, **kw):
        self.calls.append(dict(champion=champion, archetype=archetype, **kw))
        item_ids = list(kw.get("item_ids") or [])
        # Catalog of non-boots damage items so the planner has something
        # to pick at every slot. Each call returns a small ranked list;
        # the planner takes the top.
        catalog = [
            ("3094", "Rapid Firecannon",   60.0),
            ("6672", "Kraken Slayer",      55.0),
            ("3031", "Infinity Edge",      52.0),
            ("3036", "Lord Dominik's",     48.0),
            ("3072", "Bloodthirster",      45.0),
            ("3026", "Guardian Angel",     40.0),
            ("6676", "The Collector",      38.0),
            ("3046", "Phantom Dancer",     36.0),
        ]
        rows = []
        for iid, name, delta in catalog:
            if iid in item_ids:
                continue
            rows.append({
                "item_id": iid,
                "item_name": name,
                "delta": delta,
                "gold": 3000,
                "shares_dead_unique": False,
                "unique_passive_key": "",
            })
        return {"scorer": "dps", "ranked": rows}


class SelectBootsTests(unittest.TestCase):
    """Direct tests on the _select_boots helper."""

    def test_carry_balanced_comp_picks_berserkers(self):
        iid, _ = _select_boots("carry", 50.0, 30.0)
        self.assertEqual(iid, "3006")

    def test_mage_balanced_comp_picks_sorcerers(self):
        iid, _ = _select_boots("mage", 50.0, 30.0)
        self.assertEqual(iid, "3020")

    def test_tank_balanced_comp_picks_steelcaps(self):
        iid, _ = _select_boots("tank", 50.0, 30.0)
        self.assertEqual(iid, "3047")

    def test_assassin_balanced_comp_picks_mobility(self):
        iid, _ = _select_boots("assassin", 50.0, 30.0)
        self.assertEqual(iid, "3117")

    def test_enchanter_balanced_comp_picks_ionian(self):
        iid, _ = _select_boots("enchanter", 50.0, 30.0)
        self.assertEqual(iid, "3158")

    def test_high_armor_swaps_to_steelcaps_for_non_caster(self):
        # Bruiser facing 120 armor enemy comp -> Plated Steelcaps.
        iid, _ = _select_boots("bruiser", 120.0, 30.0)
        self.assertEqual(iid, "3047")

    def test_high_armor_keeps_sorcerers_for_mage(self):
        # Mage facing AD-heavy comp: CDR/penetration > armor.
        iid, _ = _select_boots("mage", 120.0, 30.0)
        self.assertEqual(iid, "3020")

    def test_high_mr_swaps_to_mercurys_for_non_dps(self):
        # Tank facing AP-heavy + CC comp -> Mercury's Treads.
        iid, _ = _select_boots("tank", 30.0, 70.0)
        self.assertEqual(iid, "3111")

    def test_high_mr_keeps_berserkers_for_dps(self):
        # ADC facing AP comp keeps Berserker's (AS loss hurts more).
        iid, _ = _select_boots("carry", 30.0, 70.0)
        self.assertEqual(iid, "3006")

    def test_unknown_archetype_falls_to_berserkers(self):
        iid, _ = _select_boots("totally-made-up", 0.0, 0.0)
        self.assertEqual(iid, "3006")


class BootsInjectionTests(unittest.TestCase):
    """plan_build_order integration tests - the injection happens AFTER
    the engine's iterative selection completes."""

    def test_carry_jinx_gets_berserkers_at_slot_2(self):
        ranker = _FakeRanker()
        out = plan_build_order(
            "Jinx", "carry",
            level=11,
            owned_item_ids=[],
            target_armor=50.0,
            target_mr=30.0,
            slots=6,
            rank_fn=ranker,
        )
        self.assertIsNotNone(out)
        boots_steps = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots_steps), 1, "exactly 1 boots step expected")
        self.assertEqual(boots_steps[0].item_id, "3006",
                         "carry archetype -> Berserker's Greaves")
        self.assertEqual(boots_steps[0].slot, 2,
                         "boots pinned at position 2 (after slot 1 big item)")
        # Note documents the injection.
        self.assertTrue(any("boots slot pinned" in n for n in out.notes))

    def test_mage_lux_gets_sorcerers(self):
        ranker = _FakeRanker()
        out = plan_build_order(
            "Lux", "mage",
            level=11,
            owned_item_ids=[],
            target_armor=50.0,
            target_mr=30.0,
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 1)
        self.assertEqual(boots[0].item_id, "3020")

    def test_tank_vs_ap_comp_picks_mercurys(self):
        ranker = _FakeRanker()
        out = plan_build_order(
            "Malphite", "tank",
            level=11,
            owned_item_ids=[],
            target_armor=30.0,
            target_mr=80.0,  # AP-heavy enemy
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 1)
        self.assertEqual(boots[0].item_id, "3111",
                         "tank vs AP comp -> Mercury's Treads")

    def test_yuumi_skips_boots(self):
        ranker = _FakeRanker()
        out = plan_build_order(
            "Yuumi", "enchanter",
            level=11,
            owned_item_ids=[],
            target_armor=50.0,
            target_mr=30.0,
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 0, "Yuumi is bootsless-exception")
        self.assertTrue(any("boots slot skipped" in n for n in out.notes))

    def test_cassiopeia_skips_boots(self):
        ranker = _FakeRanker()
        out = plan_build_order(
            "Cassiopeia", "mage",
            level=11,
            owned_item_ids=[],
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 0, "Cassiopeia is bootsless-exception")

    def test_owned_boots_not_re_injected(self):
        # Operator already bought Sorcerer's; planner must not stack a
        # second boots family on top.
        ranker = _FakeRanker()
        out = plan_build_order(
            "Lux", "mage",
            level=11,
            owned_item_ids=["3020"],
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        # The owned Sorcerer's is in `owned`, NOT in `order` (order =
        # NEW picks only). Injection should NOT re-add because the
        # owned-side scan sees 3020 in _BOOTS_IDS.
        self.assertEqual(len(boots), 0, "owned boots already cover this")

    def test_bootsless_set_pin(self):
        # Sanity-pin the exception set so adds/removals get a code-review
        # signal via test diff.
        self.assertEqual(
            sorted(_BOOTSLESS_CHAMPS),
            ["Cassiopeia", "Yuumi"],
        )

    def test_bootless_ids_pin(self):
        # Sanity-pin the boots family set.
        self.assertEqual(
            sorted(_BOOTS_IDS),
            ["3006", "3009", "3010", "3020", "3047", "3111", "3117", "3158"],
        )

    def test_aram_mode_still_injects_boots(self):
        # Per operator: boots in EVERY mode. ARAM still pins.
        ranker = _FakeRanker()
        out = plan_build_order(
            "Jinx", "carry",
            level=11,
            owned_item_ids=[],
            mode="ARAM",
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 1)

    def test_arena_mode_still_injects_boots(self):
        # Per operator: boots in EVERY mode. Arena/CHERRY still pins
        # despite the augment-economy meta where boots are often skipped.
        ranker = _FakeRanker()
        out = plan_build_order(
            "Jinx", "carry",
            level=11,
            owned_item_ids=[],
            mode="CHERRY",
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 1)


if __name__ == "__main__":
    unittest.main()
