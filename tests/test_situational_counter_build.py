"""RED-phase tests for WP-C3 - core/build_planner/situational.py.

Proves the situational_fit counter-build scorer that fills the WP-C3 stub at
core/build_planner/scoring.py:321. The module under test does NOT exist yet -
these tests are written FIRST (TDD RED phase) and are expected to fail with
ModuleNotFoundError until the GREEN implementation lands.

Surface exercised (LOCKED API):
  - classify_item(item_id) -> ItemProps  (data/tag/name-driven, patch-stable)
  - situational_fit(build_ids, enemy_profile, ally_state=None, *, stage="mid")
    covering the 7 acceptance criteria C1-C7 (resist-vs-split, antiheal de-dup,
    fed override, HP+resist vs penetration, pen-type from kill-target, tenacity
    vs CC, operator-deviation re-anchor) plus normalization / stub preservation.
  - reanchor_plan(planned_ids, observed_ids) -> ReanchorResult
  - score_build(..., enemy_profile=, ally_state=) wiring - None keeps the term 0.0.

All criterion assertions are STRICT ORDINAL relations / margins, never absolute
float values (data-fragile). "~no reward" means within a tiny eps of the same
build minus the criterion item.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core.build_planner.situational import (
    AllyState,
    CounterHint,
    EnemyProfile,
    ItemProps,
    classify_item,
    counter_build_hints,
    reanchor_plan,
    situational_fit,
)
from core.build_planner.scoring import ScoreTerms, score_build

_ROOT = Path(__file__).resolve().parent.parent
_EPS = 1e-9

# Helper item ids - all VERIFIED present in data/meta/ddragon_items.json.
ARMOR = "3075"          # Thornmail   (also Health via flats - non-disjoint)
ARMOR2 = "3047"         # Plated Steelcaps (pure armor, no hp)
MR = "3102"             # Banshee's Veil (mr only, no hp)
HP = "3083"             # Warmog's Armor
LETHALITY = "3142"      # Youmuu's Ghostblade
PCT_ARMOR = "3036"      # Lord Dominik's Regards
PCT_ARMOR2 = "6694"     # Serylda's Grudge
PCT_MAGIC = "3135"      # Void Staff
TENACITY = "3111"       # Mercury's Treads
ANTIHEAL = "3123"       # Executioner's Calling
ANTIHEAL2 = "3916"      # Oblivion Orb
PLAIN = "3031"          # Infinity Edge (no counter-flag)


# --------------------------------------------------------------------------- #
# classify_item - data / tag / name driven, patch-stable across 22-prefix
# --------------------------------------------------------------------------- #
class ClassifyItemTests(unittest.TestCase):

    def test_classify_armor_mr_health_from_flats(self):
        for iid in ("3075", "223075"):
            p = classify_item(iid)
            self.assertTrue(p.is_armor, iid)
            self.assertGreater(p.armor, 0.0, iid)
            self.assertFalse(p.is_magic_resist, iid)
        # 22-prefixed twin classifies identically on the categorical flags.
        a, b = classify_item("3075"), classify_item("223075")
        self.assertEqual(
            (a.is_armor, a.is_magic_resist, a.is_health),
            (b.is_armor, b.is_magic_resist, b.is_health),
        )
        mr = classify_item("3102")
        self.assertTrue(mr.is_magic_resist)
        self.assertGreater(mr.mr, 0.0)
        hp = classify_item("3083")
        self.assertTrue(hp.is_health)
        self.assertGreater(hp.hp, 0.0)

    def test_classify_int_id_equals_str_id(self):
        self.assertEqual(classify_item(3075), classify_item("3075"))

    def test_classify_antiheal_by_name_both_keyspaces(self):
        for iid in ("3033", "223033"):
            self.assertTrue(classify_item(iid).is_antiheal, iid)
        self.assertTrue(classify_item("3123").is_antiheal)
        self.assertTrue(classify_item("3916").is_antiheal)
        self.assertFalse(classify_item("3031").is_antiheal)

    def test_classify_mortal_reminder_is_both_flags(self):
        p = classify_item("3033")
        self.assertTrue(p.is_antiheal)
        self.assertTrue(p.is_percent_armor_pen)

    def test_classify_lethality_vs_percent_armor_pen_split(self):
        for iid in ("3036", "6694"):
            p = classify_item(iid)
            self.assertTrue(p.is_percent_armor_pen, iid)
            self.assertFalse(p.is_lethality, iid)
        for iid in ("3142", "3071", "3814"):
            p = classify_item(iid)
            self.assertTrue(p.is_lethality, iid)
            self.assertFalse(p.is_percent_armor_pen, iid)
        # Black Cleaver / Edge of Night carry hp flats too (non-disjoint).
        self.assertTrue(classify_item("3071").is_health)
        self.assertTrue(classify_item("3814").is_health)

    def test_classify_percent_magic_pen(self):
        for iid in ("3135", "3137"):
            p = classify_item(iid)
            self.assertTrue(p.is_percent_magic_pen, iid)
            self.assertFalse(p.is_percent_armor_pen, iid)

    def test_classify_tenacity_tag(self):
        for iid in ("3111", "223111", "6035", "3053"):
            self.assertTrue(classify_item(iid).is_tenacity, iid)
        self.assertFalse(classify_item("3031").is_tenacity)

    def test_classify_unknown_id_all_false(self):
        p = classify_item("999999")
        self.assertIsInstance(p, ItemProps)
        for flag in ("is_armor", "is_magic_resist", "is_health", "is_antiheal",
                     "is_lethality", "is_percent_armor_pen",
                     "is_percent_magic_pen", "is_tenacity"):
            self.assertFalse(getattr(p, flag), flag)
        self.assertEqual((p.armor, p.mr, p.hp), (0.0, 0.0, 0.0))


# --------------------------------------------------------------------------- #
# situational_fit - acceptance criteria C1-C6
# --------------------------------------------------------------------------- #
class SituationalFitTests(unittest.TestCase):

    # ---- C1 resist vs enemy damage split ---- #
    def test_c1_armor_rewarded_vs_ad_comp(self):
        ep = EnemyProfile(ad_share=1.0, ap_share=0.0)
        self.assertGreater(situational_fit([ARMOR], ep),
                           situational_fit([MR], ep))
        self.assertLessEqual(situational_fit([MR], ep),
                             situational_fit([], ep) + _EPS)

    def test_c1_mr_rewarded_vs_ap_comp(self):
        ep = EnemyProfile(ap_share=1.0, ad_share=0.0)
        self.assertGreater(situational_fit([MR], ep),
                           situational_fit([ARMOR], ep))
        self.assertLessEqual(situational_fit([ARMOR], ep),
                             situational_fit([], ep) + _EPS)

    def test_c1_both_shares_zero_no_resist_reward(self):
        ep = EnemyProfile(ad_share=0.0, ap_share=0.0)
        self.assertEqual(situational_fit([ARMOR], ep), 0.0)
        self.assertEqual(situational_fit([], ep), 0.0)

    # ---- C2 antiheal ---- #
    def test_c2_antiheal_rewarded_when_warranted(self):
        ep = EnemyProfile(heal_sources=2)
        self.assertGreater(situational_fit([ANTIHEAL, PLAIN], ep),
                           situational_fit([PLAIN], ep))

    def test_c2_antiheal_deduped_when_ally_has_it(self):
        ep = EnemyProfile(heal_sources=2)
        ally = AllyState(has_antiheal=True)
        self.assertLessEqual(
            situational_fit([ANTIHEAL, PLAIN], ep, ally),
            situational_fit([PLAIN], ep, ally) + _EPS)

    def test_c2_antiheal_not_warranted_low_heal(self):
        ep = EnemyProfile(heal_sources=1)
        self.assertLessEqual(situational_fit([ANTIHEAL, PLAIN], ep),
                             situational_fit([PLAIN], ep) + _EPS)

    def test_c2_second_antiheal_redundant(self):
        ep = EnemyProfile(heal_sources=2)
        self.assertEqual(situational_fit([ANTIHEAL, ANTIHEAL2], ep),
                         situational_fit([ANTIHEAL], ep))

    # ---- C3 fed override ---- #
    def test_c3_fed_override_widens_resist_margin(self):
        base = dict(ad_share=1.0, ap_share=0.0)
        ep_fed = EnemyProfile(fed=True, **base)
        ep_unfed = EnemyProfile(fed=False, **base)
        margin_fed = (situational_fit([ARMOR], ep_fed)
                      - situational_fit([PLAIN], ep_fed))
        margin_unfed = (situational_fit([ARMOR], ep_unfed)
                        - situational_fit([PLAIN], ep_unfed))
        self.assertGreater(margin_fed, margin_unfed)

    def test_c3_fed_no_reward_for_pure_damage(self):
        ep_fed = EnemyProfile(fed=True)
        ep_unfed = EnemyProfile(fed=False)
        self.assertEqual(situational_fit([PLAIN], ep_fed),
                         situational_fit([PLAIN], ep_unfed))

    # ---- C4 HP + resist vs penetration ---- #
    def test_c4_hp_resist_beats_pure_resist_under_pen(self):
        ep = EnemyProfile(enemy_pen=0.9, ad_share=1.0)
        self.assertGreater(situational_fit([HP, ARMOR], ep),
                           situational_fit([ARMOR, ARMOR2], ep))

    def test_c4_mix_collapses_at_zero_pen(self):
        ep = EnemyProfile(enemy_pen=0.0, ad_share=1.0)
        self.assertAlmostEqual(situational_fit([HP, ARMOR], ep),
                               situational_fit([ARMOR, ARMOR2], ep),
                               places=7)

    # ---- C5 pen TYPE from kill-target armor ---- #
    def test_c5_lethality_for_low_kill_target_armor(self):
        ep = EnemyProfile(kill_target_armor=40)
        self.assertGreater(situational_fit([LETHALITY], ep),
                           situational_fit([PCT_ARMOR], ep))
        self.assertLessEqual(situational_fit([PCT_ARMOR], ep),
                             situational_fit([], ep) + _EPS)

    def test_c5_percent_pen_for_high_kill_target_armor(self):
        ep = EnemyProfile(kill_target_armor=180)
        self.assertGreater(situational_fit([PCT_ARMOR], ep),
                           situational_fit([LETHALITY], ep))
        self.assertLessEqual(situational_fit([LETHALITY], ep),
                             situational_fit([], ep) + _EPS)

    def test_c5_second_percent_pen_redundant(self):
        ep = EnemyProfile(kill_target_armor=180)
        self.assertEqual(situational_fit([PCT_ARMOR, PCT_ARMOR2], ep),
                         situational_fit([PCT_ARMOR], ep))

    def test_c5_magic_pen_from_kill_target_mr(self):
        hi = EnemyProfile(kill_target_mr=180)
        lo = EnemyProfile(kill_target_mr=20)
        self.assertGreater(situational_fit([PCT_MAGIC], hi),
                           situational_fit([], hi))
        self.assertLessEqual(situational_fit([PCT_MAGIC], lo),
                             situational_fit([], lo) + _EPS)

    # ---- C6 tenacity vs CC ---- #
    def test_c6_tenacity_rewarded_high_cc_only(self):
        hi = EnemyProfile(cc_score=8)
        lo = EnemyProfile(cc_score=1)
        self.assertGreater(situational_fit([TENACITY], hi),
                           situational_fit([PLAIN], hi))
        self.assertLessEqual(situational_fit([TENACITY], lo),
                             situational_fit([PLAIN], lo) + _EPS)


# --------------------------------------------------------------------------- #
# Normalization / edge contracts
# --------------------------------------------------------------------------- #
class NormalizationTests(unittest.TestCase):

    def test_fit_zero_when_no_signal(self):
        self.assertEqual(situational_fit([], EnemyProfile()), 0.0)
        self.assertEqual(situational_fit([ARMOR], EnemyProfile()), 0.0)

    def test_fit_stays_in_unit_band(self):
        ep = EnemyProfile(
            ad_share=0.6, ap_share=0.4, kill_target_armor=180,
            kill_target_mr=180, enemy_pen=0.9, heal_sources=3,
            cc_score=10, burst_threat=10, tank_pressure=10, fed=True,
        )
        build = [ARMOR, MR, HP, PCT_ARMOR, PCT_MAGIC, ANTIHEAL, TENACITY]
        val = situational_fit(build, ep)
        self.assertGreater(val, 0.0)
        self.assertLess(val, 1.0)

    def test_empty_and_unknown_build_degrade_to_zero(self):
        ep = EnemyProfile(ad_share=1.0, kill_target_armor=40, heal_sources=3,
                          cc_score=10, fed=True)
        self.assertEqual(situational_fit(["999999999"], ep), 0.0)


# --------------------------------------------------------------------------- #
# reanchor_plan - C7 operator-deviation re-anchor
# --------------------------------------------------------------------------- #
class ReanchorTests(unittest.TestCase):

    def test_reanchor_no_deviation_prefix_match(self):
        r = reanchor_plan(["a", "b", "c", "d"], ["a", "b"])
        self.assertFalse(r.deviated)
        self.assertEqual(list(r.anchored_ids), ["a", "b", "c", "d"])

    def test_reanchor_empty_observed(self):
        r = reanchor_plan(["a", "b", "c"], [])
        self.assertFalse(r.deviated)
        self.assertEqual(list(r.anchored_ids), ["a", "b", "c"])

    def test_reanchor_detects_reorder(self):
        r = reanchor_plan(["a", "b", "c"], ["c", "a"])
        self.assertTrue(r.deviated)
        self.assertEqual(list(r.anchored_ids), ["c", "a", "b"])

    def test_reanchor_offplan_item_kept(self):
        r = reanchor_plan(["a", "b"], ["z"])
        self.assertTrue(r.deviated)
        self.assertEqual(list(r.anchored_ids), ["z", "a", "b"])

    def test_reanchor_int_str_coercion(self):
        r = reanchor_plan([1, 2], [1])
        self.assertFalse(r.deviated)
        self.assertEqual(list(r.anchored_ids), ["1", "2"])


# --------------------------------------------------------------------------- #
# scoring.py wiring - stub preservation + live wiring
# --------------------------------------------------------------------------- #
class ScoreBuildWiringTests(unittest.TestCase):

    @staticmethod
    def _seed_rows():
        # Mirror the existing stub test - reuse the beam-search fake seed.
        from tests.test_planner_beam_search import _CHAMP, make_seed_fn
        return _CHAMP, list(make_seed_fn()(_CHAMP).get("ranked"))

    def test_score_build_situational_zero_when_no_profile(self):
        champ, rows = self._seed_rows()
        t1 = score_build(["3031"], champ, rows)
        self.assertIsInstance(t1, ScoreTerms)
        self.assertEqual(t1.situational_fit, 0.0)
        t2 = score_build(["3031"], champ, rows, enemy_profile=None)
        self.assertEqual(t2.situational_fit, 0.0)

    def test_score_build_situational_positive_with_counter_profile(self):
        champ, rows = self._seed_rows()
        t = score_build([ARMOR], champ, rows,
                        enemy_profile=EnemyProfile(ad_share=1.0))
        self.assertGreater(t.situational_fit, 0.0)


# --------------------------------------------------------------------------- #
# Structural - module exists + imports clean (split-brain + family-literal
# guards live in tests/test_planner_beam_search.py via _SOURCES).
# --------------------------------------------------------------------------- #
class ModulePresenceTests(unittest.TestCase):

    def test_situational_module_file_exists_and_imports_clean(self):
        path = _ROOT / "core" / "build_planner" / "situational.py"
        self.assertTrue(path.exists(), str(path))
        import importlib
        mod = importlib.import_module("core.build_planner.situational")
        self.assertTrue(hasattr(mod, "situational_fit"))
        self.assertTrue(hasattr(mod, "classify_item"))
        self.assertTrue(hasattr(mod, "reanchor_plan"))


# --------------------------------------------------------------------------- #
# counter_build_hints - the per-criterion C1-C7 projection for the overlay
# (R102). Mirrors the situational_fit gates exactly; UI transport only.
# --------------------------------------------------------------------------- #
_ALLOWED_CRITERIA = {"resist", "antiheal", "fed", "hp_vs_pen", "pen_type",
                     "tenacity"}


class CounterBuildHintsTests(unittest.TestCase):

    def _by_crit(self, hints, criterion):
        return [h for h in hints if h.criterion == criterion]

    # ---- honest no-data ---- #
    def test_all_zero_profile_returns_empty_tuple(self):
        hints = counter_build_hints([ARMOR, MR, HP], EnemyProfile())
        self.assertIsInstance(hints, tuple)
        self.assertEqual(hints, ())

    # ---- C1 resist ---- #
    def test_resist_hint_armor_for_ad_comp(self):
        ep = EnemyProfile(ad_share=0.8)
        empty = counter_build_hints([], ep)
        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0].criterion, "resist")
        self.assertEqual(empty[0].suggest_class, "armor")
        self.assertEqual(empty[0].severity, "high")  # dominant share >= 0.70
        self.assertFalse(empty[0].satisfied)         # empty build owns no armor
        witharmor = self._by_crit(counter_build_hints([ARMOR], ep), "resist")
        self.assertEqual(len(witharmor), 1)
        self.assertTrue(witharmor[0].satisfied)      # Thornmail owns the counter

    def test_resist_hint_mr_for_ap_comp(self):
        ep = EnemyProfile(ap_share=0.8)
        r = self._by_crit(counter_build_hints([], ep), "resist")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].suggest_class, "mr")
        self.assertFalse(r[0].satisfied)
        self.assertTrue(self._by_crit(counter_build_hints([MR], ep),
                                      "resist")[0].satisfied)

    def test_resist_not_warranted_below_cut(self):
        ep = EnemyProfile(ad_share=0.52)  # below RESIST_HINT_CUT (0.55)
        self.assertEqual(self._by_crit(counter_build_hints([ARMOR], ep),
                                       "resist"), [])

    # ---- C2 antiheal ---- #
    def test_antiheal_hint_warranted_and_dedup(self):
        ep = EnemyProfile(heal_sources=2)
        ah = self._by_crit(counter_build_hints([ANTIHEAL], ep), "antiheal")
        self.assertEqual(len(ah), 1)
        self.assertTrue(ah[0].satisfied)
        self.assertEqual(ah[0].suggest_class, "antiheal")
        plain = self._by_crit(counter_build_hints([PLAIN], ep), "antiheal")
        self.assertEqual(len(plain), 1)
        self.assertFalse(plain[0].satisfied)
        # An ally already owning antiheal de-dups the criterion away entirely.
        deduped = counter_build_hints([PLAIN], ep, AllyState(has_antiheal=True))
        self.assertEqual(self._by_crit(deduped, "antiheal"), [])

    # ---- C3 fed ---- #
    def test_fed_hint_satisfied_reflects_survival(self):
        ep = EnemyProfile(fed=True)
        pure = self._by_crit(counter_build_hints([PLAIN], ep), "fed")
        self.assertEqual(len(pure), 1)
        self.assertFalse(pure[0].satisfied)
        surv = self._by_crit(counter_build_hints([ARMOR], ep), "fed")
        self.assertEqual(len(surv), 1)
        self.assertTrue(surv[0].satisfied)

    # ---- C4 HP vs penetration ---- #
    def test_hp_vs_pen_hint_and_floor(self):
        ep = EnemyProfile(enemy_pen=0.9)
        # Resist present + enemy stacks pen -> the hint fires.
        armor = self._by_crit(counter_build_hints([ARMOR], ep), "hp_vs_pen")
        self.assertEqual(len(armor), 1)
        self.assertEqual(armor[0].suggest_class, "hp")
        # Resist but below the HP floor (Banshee = 0 hp) -> not satisfied.
        lo = self._by_crit(counter_build_hints([MR], ep), "hp_vs_pen")
        self.assertEqual(len(lo), 1)
        self.assertFalse(lo[0].satisfied)
        # Resist + Warmog (1000 hp) clears HP_HINT_FLOOR -> satisfied.
        hi = self._by_crit(counter_build_hints([MR, HP], ep), "hp_vs_pen")
        self.assertEqual(len(hi), 1)
        self.assertTrue(hi[0].satisfied)
        # No resist in the build -> the C4 gate is not warranted at all.
        self.assertEqual(self._by_crit(counter_build_hints([HP], ep),
                                       "hp_vs_pen"), [])

    # ---- C5 pen TYPE from the kill target ---- #
    def test_pen_type_armor_pct_for_tanky_kill_target(self):
        ep = EnemyProfile(kill_target_armor=180)
        pt = self._by_crit(counter_build_hints([], ep), "pen_type")
        self.assertEqual(len(pt), 1)
        self.assertEqual(pt[0].suggest_class, "pct_armor_pen")
        self.assertFalse(pt[0].satisfied)
        self.assertTrue(self._by_crit(counter_build_hints([PCT_ARMOR], ep),
                                      "pen_type")[0].satisfied)

    def test_pen_type_lethality_for_squishy_kill_target(self):
        ep = EnemyProfile(kill_target_armor=40)
        pt = self._by_crit(counter_build_hints([], ep), "pen_type")
        self.assertEqual(len(pt), 1)
        self.assertEqual(pt[0].suggest_class, "lethality")
        self.assertTrue(self._by_crit(counter_build_hints([LETHALITY], ep),
                                      "pen_type")[0].satisfied)

    def test_pen_type_armor_unknown_emits_nothing(self):
        ep = EnemyProfile(kill_target_armor=0)  # unknown -> honest no-data
        self.assertEqual(self._by_crit(counter_build_hints([], ep),
                                       "pen_type"), [])

    def test_pen_type_magic_pct_for_tanky_mr_kill_target(self):
        ep = EnemyProfile(kill_target_mr=180)
        pt = self._by_crit(counter_build_hints([], ep), "pen_type")
        self.assertEqual(len(pt), 1)
        self.assertEqual(pt[0].suggest_class, "pct_magic_pen")
        self.assertTrue(self._by_crit(counter_build_hints([PCT_MAGIC], ep),
                                      "pen_type")[0].satisfied)

    # ---- C6 tenacity ---- #
    def test_tenacity_hint_high_cc(self):
        ep = EnemyProfile(cc_score=8)
        t = self._by_crit(counter_build_hints([], ep), "tenacity")
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0].suggest_class, "tenacity")
        self.assertFalse(t[0].satisfied)
        self.assertTrue(self._by_crit(counter_build_hints([TENACITY], ep),
                                      "tenacity")[0].satisfied)

    # ---- invariants across a saturated profile ---- #
    def test_every_hint_is_ascii_and_well_formed(self):
        ep = EnemyProfile(ad_share=0.8, heal_sources=3, fed=True, enemy_pen=0.9,
                          kill_target_armor=180, kill_target_mr=180, cc_score=9)
        build = [ARMOR, MR, HP, PCT_ARMOR, PCT_MAGIC, ANTIHEAL, TENACITY]
        hints = counter_build_hints(build, ep)
        self.assertIsInstance(hints, tuple)
        self.assertTrue(hints)
        seen_med = False
        for h in hints:
            self.assertIsInstance(h, CounterHint)
            self.assertIn(h.criterion, _ALLOWED_CRITERIA)
            self.assertIn(h.severity, {"high", "med"})
            for s in (h.label, h.detail, h.suggest_class):
                self.assertTrue(s.isascii(), repr(s))
                self.assertTrue(s)  # non-empty
            # Ordering contract: all high-severity hints precede all med ones.
            if h.severity == "med":
                seen_med = True
            elif seen_med:
                self.fail("a high-severity hint followed a med-severity hint")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
