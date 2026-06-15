"""Headless tests for boots-slot injection in core/build_order.py.

Pinned 2026-05-23 (item 164b - operator directive: boots in EVERY build
order on EVERY mode). Refreshed 2026-06-15 (P6 G4 - lolmath-parity boots
pool: DDragon 16.12.1 added SR-only tier-3 upgraded boots, and Mobility
Boots / Symbiotic Soles left the store). Proves:

  1. Every plan_build_order call returns a result whose ``order``
     contains exactly one boots family entry (id in _BOOTS_IDS).
  2. The selected boots family matches the archetype + enemy AD/AP comp
     signal, and on Summoner's Rift it is the tier-3 UPGRADE:
       SR (map 11, the tier-3 end-state form lolmath shows):
         - carry/dps + balanced comp -> Gunmetal Greaves    (3172)
         - mage + balanced comp      -> Spellslinger's Shoes (3175)
         - tank + balanced comp      -> Armored Advance      (3174)
         - assassin/enchanter        -> Crimson Lucidity     (3171)
         - high-armor enemy comp     -> Armored Advance      (3174)
         - high-MR enemy comp        -> Chainlaced Crushers  (3173)
       ARAM (map 12) / Arena (map 30) - no tier-3, keep tier-2:
         - carry -> Berserker's (3006), mage -> Sorcerer's (3020), ...
  3. Boots are NOT injected when the champion is in the bootsless-
     champion exception set (Yuumi, Cassiopeia).
  4. Boots are NOT re-injected when already present in owned_item_ids.
  5. The injection sits at position 2 (after the first big item).
  6. Mobility Boots (3117, out of store 16.x) is never a selection target.
"""
from __future__ import annotations

import unittest

from core.build_order import (
    _BOOTS_IDS,
    _BOOTS_SR_UPGRADE,
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


class SelectBootsSRTests(unittest.TestCase):
    """Direct tests on _select_boots - SR upgrades to tier-3 (default mode)."""

    def test_carry_balanced_comp_picks_gunmetal_greaves(self):
        # Berserker's (3006) -> Gunmetal Greaves (3172) on SR.
        iid, _ = _select_boots("carry", 50.0, 30.0)
        self.assertEqual(iid, "3172")

    def test_mage_balanced_comp_picks_spellslingers(self):
        # Sorcerer's (3020) -> Spellslinger's Shoes (3175) on SR.
        iid, _ = _select_boots("mage", 50.0, 30.0)
        self.assertEqual(iid, "3175")

    def test_tank_balanced_comp_picks_armored_advance(self):
        # Plated Steelcaps (3047) -> Armored Advance (3174) on SR.
        iid, _ = _select_boots("tank", 50.0, 30.0)
        self.assertEqual(iid, "3174")

    def test_assassin_balanced_comp_picks_crimson_lucidity(self):
        # No longer Mobility Boots (out of store): Ionian (3158) ->
        # Crimson Lucidity (3171) on SR.
        iid, _ = _select_boots("assassin", 50.0, 30.0)
        self.assertEqual(iid, "3171")

    def test_enchanter_balanced_comp_picks_crimson_lucidity(self):
        iid, _ = _select_boots("enchanter", 50.0, 30.0)
        self.assertEqual(iid, "3171")

    def test_high_armor_swaps_to_armored_advance_for_non_caster(self):
        iid, _ = _select_boots("bruiser", 120.0, 30.0)
        self.assertEqual(iid, "3174")

    def test_high_armor_keeps_spellslingers_for_mage(self):
        # Mage facing AD-heavy comp: CDR/penetration > armor.
        iid, _ = _select_boots("mage", 120.0, 30.0)
        self.assertEqual(iid, "3175")

    def test_high_mr_swaps_to_chainlaced_for_non_dps(self):
        # Tank facing AP-heavy + CC comp -> Mercury's -> Chainlaced Crushers.
        iid, _ = _select_boots("tank", 30.0, 70.0)
        self.assertEqual(iid, "3173")

    def test_high_mr_keeps_gunmetal_for_dps(self):
        # ADC facing AP comp keeps Berserker's -> Gunmetal Greaves.
        iid, _ = _select_boots("carry", 30.0, 70.0)
        self.assertEqual(iid, "3172")

    def test_unknown_archetype_falls_to_gunmetal(self):
        iid, _ = _select_boots("totally-made-up", 0.0, 0.0)
        self.assertEqual(iid, "3172")

    def test_sr_never_returns_mobility_boots(self):
        # 3117 is out of store - no archetype/comp path may select it.
        for arch in ("carry", "mage", "tank", "assassin", "enchanter",
                     "bruiser", "hps", "ability", "support", "burst"):
            for armor, mr in ((50.0, 30.0), (120.0, 30.0), (30.0, 70.0)):
                iid, _ = _select_boots(arch, armor, mr)
                self.assertNotEqual(iid, "3117", f"{arch} a={armor} mr={mr}")


class SelectBootsNonSRTests(unittest.TestCase):
    """ARAM (map 12) / Arena (map 30) keep the tier-2 boot (no tier-3)."""

    def test_aram_carry_keeps_berserkers(self):
        iid, _ = _select_boots("carry", 50.0, 30.0, mode="ARAM")
        self.assertEqual(iid, "3006")

    def test_aram_mage_keeps_sorcerers(self):
        iid, _ = _select_boots("mage", 50.0, 30.0, mode="ARAM")
        self.assertEqual(iid, "3020")

    def test_aram_assassin_keeps_ionian_not_mobility(self):
        # Assassin default moved off the out-of-store Mobility Boots to
        # Ionian even on non-SR maps.
        iid, _ = _select_boots("assassin", 50.0, 30.0, mode="ARAM")
        self.assertEqual(iid, "3158")

    def test_arena_tank_vs_ad_keeps_steelcaps(self):
        iid, _ = _select_boots("tank", 120.0, 30.0, mode="ARENA")
        self.assertEqual(iid, "3047")

    def test_cherry_mode_is_non_sr(self):
        iid, _ = _select_boots("mage", 50.0, 30.0, mode="CHERRY")
        self.assertEqual(iid, "3020")

    def test_classic_mode_is_sr(self):
        # Riot's gameMode for SR is CLASSIC - still upgrades.
        iid, _ = _select_boots("mage", 50.0, 30.0, mode="CLASSIC")
        self.assertEqual(iid, "3175")


class BootsInjectionTests(unittest.TestCase):
    """plan_build_order integration tests - the injection happens AFTER
    the engine's iterative selection completes. Default mode is SR."""

    def test_carry_jinx_gets_gunmetal_at_slot_2(self):
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
        self.assertEqual(boots_steps[0].item_id, "3172",
                         "carry archetype -> Gunmetal Greaves (SR tier-3)")
        self.assertEqual(boots_steps[0].slot, 2,
                         "boots pinned at position 2 (after slot 1 big item)")
        self.assertTrue(any("boots slot pinned" in n for n in out.notes))

    def test_mage_lux_gets_spellslingers(self):
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
        self.assertEqual(boots[0].item_id, "3175")

    def test_tank_vs_ap_comp_picks_chainlaced(self):
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
        self.assertEqual(boots[0].item_id, "3173",
                         "tank vs AP comp -> Chainlaced Crushers (SR tier-3)")

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
        self.assertEqual(len(boots), 0, "owned boots already cover this")

    def test_owned_tier3_boots_not_re_injected(self):
        # A player who already upgraded to Spellslinger's must be detected
        # as boots-owned (tier-3 ids are in _BOOTS_IDS).
        ranker = _FakeRanker()
        out = plan_build_order(
            "Lux", "mage",
            level=14,
            owned_item_ids=["3175"],
            slots=6,
            rank_fn=ranker,
        )
        boots = [s for s in out.order if s.item_id in _BOOTS_IDS]
        self.assertEqual(len(boots), 0, "owned tier-3 boots already cover this")

    def test_bootsless_set_pin(self):
        self.assertEqual(
            sorted(_BOOTSLESS_CHAMPS),
            ["Cassiopeia", "Yuumi"],
        )

    def test_boots_ids_pin(self):
        # Sanity-pin the boots family set (tier-2 base + SR tier-3/4).
        self.assertEqual(
            sorted(_BOOTS_IDS),
            ["3006", "3009", "3010", "3013", "3020", "3047", "3111",
             "3117", "3158", "3168", "3170", "3171", "3172", "3173",
             "3174", "3175", "3176"],
        )

    def test_sr_upgrade_map_targets_are_known(self):
        # Every tier-3 upgrade target is a recognized boots id.
        for tier3 in _BOOTS_SR_UPGRADE.values():
            self.assertIn(tier3, _BOOTS_IDS)

    def test_aram_mode_injects_tier2_boots(self):
        # Per operator: boots in EVERY mode. ARAM still pins, but tier-2.
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
        self.assertEqual(boots[0].item_id, "3006",
                         "ARAM has no tier-3 - carry keeps Berserker's")

    def test_arena_mode_injects_tier2_boots(self):
        # Arena/CHERRY still pins one boot; no tier-3 upgrade on map 30.
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
        self.assertEqual(boots[0].item_id, "3006")


if __name__ == "__main__":
    unittest.main()
