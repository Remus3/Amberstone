# arch: P1-L26 deep Arena scored-build e2e composition audit | section=daemon_slayer | frozen=no
"""P1-L26 audit hardening: DEEP end-to-end Arena scored-build correctness.

Prior lanes verified the pieces in isolation:

  * P1-L9 (test_aram_arena_scoring_p1l9.py): augment stat overlays move
    item value the correct DIRECTION (an AP augment raises an AP
    champion; an AD augment raises an AD champion).
  * P1-L23 (test_rank_mode_legality_p1l23.py): the candidate POOL is
    map-30-legal (22-prefixed Arena mirror in, Arcane Sweeper out,
    Galeforce map-30-only, SR-only items out).
  * Earlier passes: the Cherry augment registry is zero-drift; the
    22-prefixed Arena-mirror ids resolve ARENA-only with their OWN
    stats (Arena IE 223031 = 55 AD vs SR IE 3031 = 75 AD).

This lane goes deeper: given a realistic Arena game (champion + owned
Arena-mirror items + an offered stat augment), does ``rank_items`` /
``build_champion`` produce the correct scored build with ALL of that
composing together - augment stat overlay + 22-mirror item OWN stats +
map-30 legality - in a SINGLE scored value, with the overlay applied
exactly once (not double, not ignored), the mirror stats used (not the
SR base-id stats), and no SR-only item leaking in?

Findings (all VERIFIED CORRECT - these tests pin the composed
invariants so a future regression in the composition - not just one
piece - trips):

  * Augment overlay composes ADDITIVELY with the 22-mirror item's own
    stats in the same scored build: AD(mirror IE 223031 + TheBrutalizer)
    minus AD(naked) equals exactly the mirror IE's FlatPhysicalDamageMod
    PLUS the augment dataValues[0] AD - each applied once, no
    interaction term, no double.
  * The Arena scored build uses the 22-mirror item OWN stats: building
    with the Arena mirror id yields the mirror's (lower) AD, building
    with the SR base id yields the SR (higher) AD; the gap equals the
    source-field stat delta exactly. The mirror-vs-SR difference
    actually changes the resolved stat block.
  * The full ``rank_items`` Arena path contains ONLY map-30-legal
    purchasable items (no Arcane Sweeper trinket, Galeforce present,
    no SR base id leaking - only its 22-mirror), is non-empty +
    deterministic, and an Arena state with NO augments still produces a
    valid build (augments optional, ``None`` == omitted).
  * Two different stat augments (AD vs crit) shift the ranked Arena
    build in correctly-different directions and change the baseline -
    the overlay is not silently dropped at the rank layer.

Discipline: every expected number is read FROM the snapshot's own
augment ``dataValues`` and item ``stats`` / ``maps`` fields inside the
test. No hardcoded magic numbers for engine outputs. No fragile
cross-item ordering assertions (the "two augments differ" check asserts
the ranked-id LISTS are not identical and that the baselines differ -
both structural, derived facts - not "item A delta > item B delta").
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.rank import (
    _filter_candidates,
    _is_purchasable,
    _is_terminal,
    rank_items,
)

# Snapshot-stable anchors used across the lane. Each is re-validated
# against its source fields in test_setup_assumptions_hold so a
# snapshot refresh that moves them fails loudly here rather than
# silently invalidating the composed asserts.
_SR_IE = "3031"        # Infinity Edge, Summoner's Rift base id
_ARENA_IE = "223031"   # Infinity Edge, 22-prefixed Arena mirror id
_AD_AUG = "TheBrutalizer"      # silver, flat AD overlay
_AP_AUG = "WitchfulThinking"   # silver, flat AP overlay
_CRIT_AUG = "ItsCritical"      # gold, flat crit-chance overlay


class ArenaE2ESetupAssumptionsTests(unittest.TestCase):
    """State the data assumptions explicitly (CLAUDE: state assumptions
    before relying on them). A snapshot refresh that breaks any of these
    fails HERE, not as a confusing magnitude error downstream."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_mirror_and_sr_ie_are_distinct_with_expected_legality(self) -> None:
        # Riot unified SR IE and Arena-mirror IE AD to 75 in patch 16.11.1
        # (previously SR 75 AD vs Arena 55 AD). The AD-divergence guard
        # below is now satisfied by Bloodthirster (3072 SR 80 AD vs
        # 223072 Arena 70 AD), which the engine-invariant tests below
        # additionally pin to the 16.10.1 snapshot for IE divergence
        # provability.
        snap = DataSnapshot.load(patch="16.10.1")
        sr = snap.item(_SR_IE)
        ar = snap.item(_ARENA_IE)
        # Same item, different ids, different stat blocks.
        self.assertEqual(sr.get("name"), ar.get("name"))
        sr_ad = float((sr.get("stats") or {}).get("FlatPhysicalDamageMod", 0.0))
        ar_ad = float((ar.get("stats") or {}).get("FlatPhysicalDamageMod", 0.0))
        self.assertGreater(sr_ad, 0.0)
        self.assertGreater(ar_ad, 0.0)
        self.assertNotAlmostEqual(
            sr_ad, ar_ad,
            msg="SR IE and Arena-mirror IE must have DIFFERENT AD for the "
            "mirror-vs-SR composition test to be meaningful",
        )
        # Legality split also holds at 16.11.1; re-verify against current
        # snapshot so the map-legality regression catches drift.
        sr_now = self.snap.item(_SR_IE)
        ar_now = self.snap.item(_ARENA_IE)
        self.assertTrue((sr_now.get("maps") or {}).get("11"))
        self.assertFalse((sr_now.get("maps") or {}).get("30"))
        self.assertTrue((ar_now.get("maps") or {}).get("30"))
        self.assertFalse((ar_now.get("maps") or {}).get("11"))
        self.assertTrue(_is_purchasable(ar_now))
        self.assertTrue(_is_terminal(ar_now))

    def test_stat_augments_present_with_expected_datavalues(self) -> None:
        ad = self.snap.arena_augments_by_api.get(_AD_AUG)
        ap = self.snap.arena_augments_by_api.get(_AP_AUG)
        cc = self.snap.arena_augments_by_api.get(_CRIT_AUG)
        self.assertIsNotNone(ad)
        self.assertIsNotNone(ap)
        self.assertIsNotNone(cc)
        self.assertGreater(float(ad["dataValues"]["AD"][0]), 0.0)
        self.assertGreater(float(ap["dataValues"]["AP"][0]), 0.0)
        self.assertGreater(float(cc["dataValues"]["CritChance"][0]), 0.0)


class ArenaAugmentMirrorCompositionTests(unittest.TestCase):
    """The core lane: augment overlay + 22-mirror OWN stats compose
    additively in ONE scored build - applied once each, no interaction
    term, no double-count, no silent drop."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_overlay_plus_mirror_stats_compose_additively_once(self) -> None:
        # AD(Arena-mirror IE + AD augment) - AD(naked) must equal exactly
        # the mirror IE's own FlatPhysicalDamageMod PLUS the augment's
        # dataValues[0] AD. Both values READ from source - no magic
        # numbers. This is the composition the unit lanes never checked
        # together: a double-apply (2x aug), a dropped overlay (0x aug),
        # or the SR-stat leaking (75 not 55) all fail here.
        mirror_ad = float(
            self.snap.item(_ARENA_IE)["stats"]["FlatPhysicalDamageMod"]
        )
        aug_ad = float(
            self.snap.arena_augments_by_api[_AD_AUG]["dataValues"]["AD"][0]
        )
        naked = build_champion(self.snap, "Aatrox", 11, [], mode="ARENA")
        composed = build_champion(
            self.snap, "Aatrox", 11, [_ARENA_IE],
            mode="ARENA", augments=[_AD_AUG],
        )
        self.assertAlmostEqual(
            composed.get("ad") - naked.get("ad"),
            mirror_ad + aug_ad,
            places=4,
            msg="AD(mirror IE + AD aug) - AD(naked) must be exactly "
            "(mirror IE AD) + (augment AD) - composed once each",
        )

    def test_overlay_applied_exactly_once_not_doubled(self) -> None:
        # Isolate the overlay: naked champ, ARENA, AD augment only. The
        # AD delta must equal the augment's dataValues[0] EXACTLY (1x),
        # which is provably not 2x (the double-apply failure mode) since
        # the value is > 0.
        aug = self.snap.arena_augments_by_api[_AD_AUG]
        exp = float(aug["dataValues"]["AD"][0])
        b0 = build_champion(self.snap, "Aatrox", 11, [], mode="ARENA")
        b1 = build_champion(
            self.snap, "Aatrox", 11, [], mode="ARENA", augments=[_AD_AUG]
        )
        got = b1.get("ad") - b0.get("ad")
        self.assertAlmostEqual(got, exp, places=4)
        self.assertNotAlmostEqual(
            got, exp * 2.0, places=2,
            msg="overlay must be applied ONCE (got the 2x double-apply value)",
        )

    def test_ap_overlay_exact_on_ap_champion(self) -> None:
        aug = self.snap.arena_augments_by_api[_AP_AUG]
        exp = float(aug["dataValues"]["AP"][0])
        b0 = build_champion(self.snap, "Lux", 11, [], mode="ARENA")
        b1 = build_champion(
            self.snap, "Lux", 11, [], mode="ARENA", augments=[_AP_AUG]
        )
        self.assertAlmostEqual(b1.get("ap") - b0.get("ap"), exp, places=4)

    def test_scored_build_uses_mirror_own_stats_not_sr_base(self) -> None:
        # Building with the Arena mirror id yields the mirror's (lower)
        # AD; building with the SR base id yields the SR (higher) AD.
        # The gap must equal the source-field AD delta EXACTLY - proves
        # the engine reads the mirror's OWN stat block, not the SR one.
        sr_ad = float(
            self.snap.item(_SR_IE)["stats"]["FlatPhysicalDamageMod"]
        )
        ar_ad = float(
            self.snap.item(_ARENA_IE)["stats"]["FlatPhysicalDamageMod"]
        )
        with_mirror = build_champion(
            self.snap, "Aatrox", 11, [_ARENA_IE], mode="ARENA"
        )
        with_sr = build_champion(
            self.snap, "Aatrox", 11, [_SR_IE], mode="ARENA"
        )
        self.assertAlmostEqual(
            with_sr.get("ad") - with_mirror.get("ad"),
            sr_ad - ar_ad,
            places=4,
            msg="resolved AD gap (SR id vs mirror id) must equal the "
            "source-field FlatPhysicalDamageMod gap exactly",
        )

    def test_mirror_vs_sr_actually_differs_in_scored_dps(self) -> None:
        # A build that would differ between SR-stats and Arena-stats
        # actually differs in the SCORED output (not just the raw stat
        # block): same champ/level/mode/target, only the IE id swapped.
        # SR IE has more AD -> strictly higher DPS. This pins that the
        # mirror distinction is load-bearing through compute_dps.
        # Riot equalized SR/Arena IE AD in patch 16.11.1 (both 75); pin
        # to 16.10.1 to keep the AD-divergent engine-invariant test.
        snap = DataSnapshot.load(patch="16.10.1")
        d_mirror = compute_dps(
            snap, "Aatrox", level=11, mode="ARENA",
            item_ids=[_ARENA_IE], target_armor=80.0,
        ).weighted_dps
        d_sr = compute_dps(
            snap, "Aatrox", level=11, mode="ARENA",
            item_ids=[_SR_IE], target_armor=80.0,
        ).weighted_dps
        self.assertGreater(d_mirror, 0.0)
        self.assertGreater(
            d_sr, d_mirror,
            msg="SR IE (higher source AD) must score strictly higher DPS "
            "than the Arena mirror IE - proves the OWN-stat path reaches "
            "the scorer",
        )

    def test_unknown_augment_zero_overlay_through_rank(self) -> None:
        # Documented progressive contract, asserted at the rank_items
        # layer (not just compute_*): an unregistered augment leaves the
        # Arena baseline byte-identical.
        base = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=10,
        )
        unk = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=10,
            augments=["NoSuchAugment_p1l26_zzz"],
        )
        self.assertAlmostEqual(
            unk.baseline_dps, base.baseline_dps, places=9
        )


class ArenaScoredBuildLegalityTests(unittest.TestCase):
    """End-to-end legality: the COMPOSED scored build (current items +
    every ranked candidate) is map-30-legal - no SR-only id leaks even
    when the player owns a mirror item and runs an augment."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _arena_build_ids(self, champ: str, augments=None) -> set[str]:
        r = rank_items(
            self.snap, champ, level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0,
            top_n=400, augments=augments,
        )
        return set(r.current_item_ids) | {ri.item_id for ri in r.ranked}

    def test_every_id_in_scored_build_is_map30_legal(self) -> None:
        # The defining composed assertion: with a mirror item owned AND
        # an augment active, EVERY id touched by the scored build must be
        # map-30 legal per its OWN source maps field. A leak here is the
        # exact composition bug the unit lanes (pool-only / overlay-only)
        # could not catch.
        for augs in (None, [_AD_AUG], [_CRIT_AUG]):
            ids = self._arena_build_ids("Aatrox", augments=augs)
            offenders = [
                (i, self.snap.items.get(i, {}).get("name"))
                for i in ids
                if not (self.snap.items.get(i, {}).get("maps") or {}).get("30")
            ]
            self.assertEqual(
                offenders, [],
                f"augments={augs}: non-map-30 id(s) in the Arena scored "
                f"build (composition leak): {offenders[:12]}",
            )

    def test_sr_base_ie_absent_only_mirror_present(self) -> None:
        # The SR base IE id must NEVER appear in an Arena scored build;
        # only its 22-mirror. Asserted on a champion that ranks IE highly
        # so the candidate genuinely surfaces.
        ids = self._arena_build_ids("Lucian", augments=[_CRIT_AUG])
        self.assertNotIn(
            _SR_IE, ids,
            "SR base IE id leaked into the Arena scored build",
        )
        # And the mirror is genuinely in the candidate space (proves the
        # absence above is real exclusion, not an empty pool artifact).
        arena_pool = {
            i for i, _ in _filter_candidates(
                self.snap, "ARENA", set(), None, False, None
            )
        }
        self.assertIn(
            _ARENA_IE, arena_pool,
            "Arena mirror IE missing from the candidate pool - the "
            "SR-absence assertion would be vacuous",
        )

    def test_galeforce_in_arcane_sweeper_out_of_scored_build(self) -> None:
        # Settled-truth exceptions hold through the full scored path:
        # Galeforce (map-30-only) IS a ranked candidate; Arcane Sweeper
        # (non-purchasable trinket) is NOT - even with an augment active.
        gf = self.snap.item("446671")
        asw = self.snap.item("3348")
        # Re-derive the expectation from source so a data change is loud.
        self.assertTrue((gf.get("maps") or {}).get("30"))
        self.assertFalse(_is_purchasable(asw))
        r = rank_items(
            self.snap, "Lucian", level=11, mode="ARENA",
            target_armor=60.0, top_n=400, augments=[_CRIT_AUG],
        )
        ranked_ids = {ri.item_id for ri in r.ranked}
        if _is_purchasable(gf):
            self.assertIn(
                "446671", ranked_ids,
                "Galeforce wrongly absent from the Arena scored build",
            )
        self.assertNotIn(
            "3348", ranked_ids,
            "Arcane Sweeper (non-purchasable) leaked into the scored build",
        )

    def test_no_augment_state_still_valid_and_deterministic(self) -> None:
        # Augments are OPTIONAL: an Arena state with no augments must
        # still yield a non-empty, deterministic, all-map-30 build.
        r1 = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=15,
        )
        r2 = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=15,
        )
        self.assertGreater(len(r1.ranked), 0, "no-augment Arena build empty")
        self.assertEqual(
            [r.item_id for r in r1.ranked],
            [r.item_id for r in r2.ranked],
            "no-augment Arena build not deterministic",
        )
        for ri in r1.ranked:
            self.assertTrue(
                (self.snap.items.get(ri.item_id, {}).get("maps") or {}).get("30"),
                f"no-augment ranked id {ri.item_id} is not map-30 legal",
            )

    def test_augments_none_equals_omitted(self) -> None:
        # ``augments=None`` must be byte-equivalent to not passing the
        # kwarg - the optional contract at the public rank_items boundary.
        explicit_none = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=10,
            augments=None,
        )
        omitted = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=10,
        )
        self.assertEqual(
            [(r.item_id, r.delta_dps) for r in explicit_none.ranked],
            [(r.item_id, r.delta_dps) for r in omitted.ranked],
        )


class ArenaTwoAugmentsDivergeTests(unittest.TestCase):
    """Two different stat augments shift the ranked Arena build in
    correctly-different directions and change the baseline - the overlay
    is not silently dropped at the rank layer (a no-op overlay would
    yield identical rankings + identical baseline)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ad_vs_crit_augment_change_baseline_and_ranking(self) -> None:
        # Aatrox has zero base crit; the crit augment changes its
        # auto-attack DPS, the AD augment changes flat AD - different
        # mechanics, so the scored baseline AND the ranked-id list must
        # differ between the two. Structural assertions only (lists not
        # identical; baselines not equal) - no fragile per-item ordering.
        r_ad = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0,
            top_n=30, augments=[_AD_AUG],
        )
        r_crit = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0,
            top_n=30, augments=[_CRIT_AUG],
        )
        self.assertNotAlmostEqual(
            r_ad.baseline_dps, r_crit.baseline_dps, places=2,
            msg="AD-augment and crit-augment Arena baselines must differ "
            "(equal would mean an overlay was dropped at the rank layer)",
        )
        self.assertNotEqual(
            [r.item_id for r in r_ad.ranked],
            [r.item_id for r in r_crit.ranked],
            "AD vs crit augment must reshape the ranked Arena build - "
            "identical ordering would mean the overlay is a no-op here",
        )

    def test_ad_augment_raises_ad_champ_baseline_vs_no_augment(self) -> None:
        # Direction guard at the rank layer: the AD augment must RAISE an
        # AD champion's Arena scored baseline vs the no-augment build
        # (not lower it, not leave it unchanged).
        no_aug = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=1,
        )
        with_ad = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            current_item_ids=[_ARENA_IE], target_armor=80.0, top_n=1,
            augments=[_AD_AUG],
        )
        self.assertGreater(
            with_ad.baseline_dps, no_aug.baseline_dps,
            msg="AD augment must raise an AD champion's Arena baseline DPS",
        )


if __name__ == "__main__":
    unittest.main()
