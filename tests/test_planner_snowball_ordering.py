"""Slice A.1 (2026-07-16) - planner must not hoist Mejai's Soulstealer /
Dark Seal to the build-plan FRONT slot.

Symptom: Slice A routed 7 AP assassins to the ds.burst scorer, surfacing a
pre-existing planner bug - POST /api/build-plan for Akali (and the other 6 AP
assassins) LEADS with Mejai's Soulstealer, a snowball item nobody blind-first-
buys, even though the value-rank (/api/ds-preview) correctly places it #4-8
behind Void Staff / Rabadon's Deathcap / Lich Bane.

Root cause (confirmed - see .superpowers/sdd/task-A1-report.md step 2 for the
full ScoreTerms breakdown evidence gathered via a pre-fix diagnostic probe):
core/build_planner/scoring.py's ``_gold_term`` rewards average delta_dps-per-
1k-gold. Mejai's Soulstealer (3041, 1500g) and Dark Seal (1082, 350g) are
cheap enough that their per-gold ratio is inflated far above the value-rank
leaders even though their raw delta_dps and kit-cohesion
(core.build_planner.kit_synergy.synergy_score) are both LOWER - so the gold
term alone can outweigh the dps+cohesion deficit and hoist a snowball-first
prefix to the top of the beam. The spike term (scoring.py:_spike_term) was
CONFIRMED NOT to be a material hoister - it is a constant (terminal-fraction *
stage-decay) across single-item builds regardless of gold cost, so it does
not need the same fix (see task-A1-report.md for the probe output; not
re-encoded as a committed test here - see the NOTE above
GoldTermSkipMechanismTests for why).

CORRECTION vs the original task brief: Dark Seal's item id is 1082, NOT 2033.
2033 is Corrupting Potion (a starting consumable) - confirmed against THREE
independent sources in this repo: data/meta/ddragon_items.json (patch
16.14.1), agents/daemon_slayer/_effects_data.py:5344-5345 ("1082":
ItemEffect(item_id="1082", name="Dark Seal", ...)), and
core/archetype_mismatch.py:109 (2033 listed in the curated Consumables
bucket). This file (and the scoring.py fix) use the verified id 1082.

Fixture note: delta_dps / dps_per_1k_gold values below are a controlled,
calibrated SEED FIXTURE (mirrors tests/test_planner_beam_search.py -
synthetic magnitudes standing in for a live DS response), not live DS output -
the planner never recomputes DPS (split-brain guard), it only reads whatever
the seed_fn hands it. Calibration is verified empirically (the pre-fix probe
in task-A1-report.md) rather than assumed.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import unittest

from core.build_planner.planner import plan_build

_MEJAI = "3041"
_DARK_SEAL = "1082"
_SNOWBALL_IDS = (_MEJAI, _DARK_SEAL)

_AP_ASSASSINS = ("Akali", "Ekko", "Evelynn", "Fizz", "Katarina", "LeBlanc", "Diana")

# id -> (name, delta_dps, gold, dps_per_1k_gold). Calibrated so the snowball
# ids' cheap cost inflates dps_per_1k_gold far above the value-rank leaders
# (Void Staff / Rabadon's Deathcap / Lich Bane) even though their raw
# delta_dps is the LOWEST in the pool - mirrors the real /api/ds-preview shape
# where Mejai's/Dark Seal rank #4-8 on value but (pre-fix) hoist to the plan
# FRONT. unique_passive_key is empty for all rows (no family-collision noise -
# that mechanic is out of scope here).
_CATALOG: dict[str, tuple[str, float, int, float]] = {
    _MEJAI:     ("Mejai's Soulstealer", 45.0, 1500, 42.0),
    _DARK_SEAL: ("Dark Seal",           30.0,  350, 60.0),
    "3135":     ("Void Staff",          90.0, 3600, 25.0),
    "3089":     ("Rabadon's Deathcap", 100.0, 4000, 25.0),
    "3100":     ("Lich Bane",           85.0, 3300, 26.0),
}

# A second, disjoint AD-crit catalog (mirrors tests/test_planner_beam_search.py
# _FAKE_CATALOG) that never includes the 2 snowball ids at all - used for the
# Qiyana control so "unaffected by the fix" is proven by construction (the
# skip-list code path in _gold_term is unreachable when neither id is in the
# pool), not by a numeric coincidence.
_AD_CATALOG: dict[str, tuple[str, float, int, float]] = {
    "3031": ("Infinity Edge", 95.0, 3450, 27.5),
    "6672": ("Kraken Slayer", 85.0, 3000, 28.3),
    "3036": ("Lord Dominik's", 62.0, 3000, 20.7),
}


def _rows_from(catalog, extra=None):
    rows = [
        {"item_id": iid, "item_name": n, "delta_dps": d, "gold": g,
         "dps_per_1k_gold": p, "unique_passive_key": "", "is_terminal": True}
        for iid, (n, d, g, p) in catalog.items()
    ]
    if extra:
        rows.extend(extra)
    return rows


def make_seed_fn(catalog=_CATALOG, extra_rows=None):
    """Deterministic seed_fn(champion, owned_ids, **kw) -> {ranked[], order[]}.

    Mirrors tests/test_planner_beam_search.py:make_seed_fn - the /api/ds-preview
    {ranked[], order[]} envelope shape. ``owned_ids`` filters ranked (matches
    the real ds-preview + the planner's own re-filter).
    """
    def seed_fn(champion, owned_ids=None, **kw):
        owned = {str(i) for i in (owned_ids or ())}
        ranked = [r for r in _rows_from(catalog, extra_rows)
                  if r["item_id"] not in owned]
        ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
        return {"ok": True, "ranked": ranked, "order": []}
    return seed_fn


# --------------------------------------------------------------------------- #
# NOTE on the step-2 CONFIRM evidence (root-cause-fix loop): the diagnostic
# "compute score_build's term breakdown for Mejai's-first vs Void-Staff-first
# and subtract each term in turn" comparison that CONFIRMED the gold term (not
# spike) as the dominant hoister was run PRE-FIX, against the then-unmodified
# score_build - see .superpowers/sdd/task-A1-report.md for the full numbers.
# It is intentionally NOT re-encoded as a committed test here: once the fix
# lands, score_build's own ``gold`` field for a snowball id IS the post-fix
# (already-corrected) value, so a same-shaped "subtract the term and compare"
# assertion against the CURRENT score_build would either be vacuous (gold is
# already 0) or silently test something other than what it claims. The
# mechanism the fix actually changed is pinned directly below instead
# (GoldTermSkipMechanismTests), which stays meaningful regardless of future
# score_build changes.
# --------------------------------------------------------------------------- #
# White-box: the fix mechanism itself (core.build_planner.scoring._gold_term +
# _SNOWBALL_ITEM_IDS, added by this change). Imported LOCALLY inside each test
# (not at module level) so this file can still be collected + the symptom-
# level tests below can run RED before the fix exists.
# --------------------------------------------------------------------------- #
class GoldTermSkipMechanismTests(unittest.TestCase):
    def test_snowball_ids_constant_contains_both_curated_items(self):
        from core.build_planner.scoring import _SNOWBALL_ITEM_IDS
        self.assertEqual(set(_SNOWBALL_ITEM_IDS), {_MEJAI, _DARK_SEAL})

    def test_gold_term_zero_for_snowball_only_build(self):
        from core.build_planner.scoring import _gold_term, _row_index
        rows_by_id = _row_index(_rows_from(_CATALOG))
        self.assertEqual(_gold_term([_MEJAI], rows_by_id), 0.0)
        self.assertEqual(_gold_term([_DARK_SEAL], rows_by_id), 0.0)

    def test_gold_term_unaffected_for_non_snowball_cheap_item(self):
        # Control: a cheap NON-snowball item (real, cheap boots) keeps its
        # FULL per-gold credit - the fix must not blanket-nerf every cheap
        # item, only the 2 curated snowball ids.
        from core.build_planner.scoring import _gold_term, _row_index
        boots_row = {"item_id": "3020", "item_name": "Sorcerer's Shoes",
                     "delta_dps": 20.0, "gold": 1100, "dps_per_1k_gold": 35.0,
                     "unique_passive_key": "", "is_terminal": True}
        rows_by_id = _row_index(_rows_from(_CATALOG, [boots_row]))
        self.assertAlmostEqual(_gold_term(["3020"], rows_by_id), 35.0 / 30.0)

    def test_gold_term_mixed_build_averages_only_non_snowball(self):
        # A build containing BOTH a snowball id and a merit id averages the
        # per-gold ratio over ONLY the non-snowball row (3041 excluded from
        # the average, not zeroed-and-included) - proving snowball items stay
        # rankable later in a build without dragging the whole average to 0.
        from core.build_planner.scoring import _gold_term, _row_index
        rows_by_id = _row_index(_rows_from(_CATALOG))
        mixed = _gold_term([_MEJAI, "3135"], rows_by_id)
        void_only = _gold_term(["3135"], rows_by_id)
        self.assertAlmostEqual(mixed, void_only)


# --------------------------------------------------------------------------- #
# The reported symptom, at the planner level (plan_build - the real beam
# search /api/build-plan runs). First planned item must never be a snowball
# id, for every AP assassin, at every game stage.
# --------------------------------------------------------------------------- #
class PlannerFrontSlotTests(unittest.TestCase):
    def test_ap_assassin_front_slot_is_not_a_snowball_item_early(self):
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                plan = plan_build(champion=champ, seed_fn=make_seed_fn(),
                                  beam_width=6, depth=1, clock_s=300.0)
                self.assertEqual(plan.stage, "early")
                self.assertTrue(plan.items, f"{champ}: empty plan")
                self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS,
                                 f"{champ}: front slot is a snowball item "
                                 f"{plan.items[0].item_id!r}")

    def test_ap_assassin_front_slot_is_not_a_snowball_item_mid(self):
        # Dummy owned ids (never present in the pool) push owned_count -> 2
        # without removing any real candidate row - isolates the stage shift.
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                plan = plan_build(champion=champ, seed_fn=make_seed_fn(),
                                  owned_item_ids=["9001", "9002"],
                                  beam_width=6, depth=1, clock_s=900.0)
                self.assertEqual(plan.stage, "mid")
                self.assertTrue(plan.items, f"{champ}: empty plan")
                self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS,
                                 f"{champ}: mid-stage front slot is a snowball "
                                 f"item {plan.items[0].item_id!r}")

    def test_ap_assassin_front_slot_is_not_a_snowball_item_late(self):
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                plan = plan_build(champion=champ, seed_fn=make_seed_fn(),
                                  owned_item_ids=["9001", "9002", "9003", "9004"],
                                  beam_width=6, depth=1, clock_s=1400.0)
                self.assertEqual(plan.stage, "late")
                self.assertTrue(plan.items, f"{champ}: empty plan")
                self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS,
                                 f"{champ}: late-stage front slot is a snowball "
                                 f"item {plan.items[0].item_id!r}")

    def test_dark_seal_specifically_does_not_lead_akali(self):
        # Named-symptom regression: Dark Seal (the sibling), not just Mejai's.
        plan = plan_build(champion="Akali", seed_fn=make_seed_fn(),
                          beam_width=6, depth=1, clock_s=300.0)
        self.assertNotEqual(plan.items[0].item_id, _DARK_SEAL)

    def test_mejai_specifically_does_not_lead_akali(self):
        # Isolate Mejai's alone (Dark Seal removed from the pool) so this
        # test cannot pass merely because Dark Seal out-competes Mejai's.
        seed_fn = make_seed_fn({k: v for k, v in _CATALOG.items() if k != _DARK_SEAL})
        plan = plan_build(champion="Akali", seed_fn=seed_fn, beam_width=6, depth=1,
                          clock_s=300.0)
        self.assertNotEqual(plan.items[0].item_id, _MEJAI)

    def test_ap_assassin_front_slot_not_snowball_at_production_depth(self):
        # PRODUCTION FIDELITY: the earlier front-slot tests run depth=1, which
        # degenerates the beam to "single best item" and does NOT exercise the
        # depth the bug was actually observed at. The live re-plan loop drives
        # the planner at beam_width=6, depth=6 (core/build_planner/replan.py:569
        # ReplanLoop.tick defaults). This test pins the fix at those exact
        # production settings for every AP assassin - the front slot must not
        # be a snowball item, and (as a bonus assertion of the intended
        # behavior) the snowball ids must still appear LATER in the full 6-deep
        # order, proving they were de-prioritized out of the front, not
        # excluded from the plan. If the _gold_term snowball skip is reverted,
        # this test goes RED (the beam hoists a snowball id back to slot 0) -
        # verified during the task-A1 review pass.
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                plan = plan_build(champion=champ, seed_fn=make_seed_fn(),
                                  beam_width=6, depth=6, clock_s=300.0)
                self.assertTrue(plan.items, f"{champ}: empty plan")
                self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS,
                                 f"{champ}: production-depth front slot is a "
                                 f"snowball item {plan.items[0].item_id!r}")
                # Intended behavior sanity: with a 5-item pool searched 6 deep,
                # both snowball ids are still in the plan - just not at slot 0.
                all_ids = {pi.item_id for pi in plan.items}
                self.assertTrue(set(_SNOWBALL_IDS) <= all_ids,
                                f"{champ}: snowball ids must remain in the plan "
                                f"tail (got order {[p.item_id for p in plan.items]})")

    def test_snowball_items_still_reachable_later_in_the_build(self):
        # The fix must NOT exclude the snowball ids from the candidate pool -
        # they must remain rankable at a later slot. A 5-item pool searched to
        # depth 5 has nowhere else to go but to include both eventually; if a
        # wrong fix had excluded them from the pool instead of just the gold
        # term, the beam would exhaust at 3 items and never reach them.
        plan = plan_build(champion="Akali", seed_fn=make_seed_fn(),
                          beam_width=8, depth=5, clock_s=300.0)
        all_ids = {pi.item_id for pi in plan.items}
        self.assertTrue(set(_SNOWBALL_IDS) <= all_ids,
                        f"snowball items must still be reachable later in the "
                        f"5-deep plan (got {all_ids!r}) - not excluded from "
                        f"the pool entirely")


# --------------------------------------------------------------------------- #
# Controls that must NOT regress (the anti-narrow sibling sweep).
# --------------------------------------------------------------------------- #
class ControlTests(unittest.TestCase):
    def test_cheap_efficient_non_snowball_item_still_leads_by_merit(self):
        # A cheap, genuinely gold-efficient NON-snowball item (real boots)
        # must still be able to win the front slot on merit - the fix only
        # demotes the 2 curated snowball ids, not "cheap" items in general.
        cheap_efficient = {"item_id": "3020", "item_name": "Sorcerer's Shoes",
                           "delta_dps": 30.0, "gold": 1100, "dps_per_1k_gold": 40.0,
                           "unique_passive_key": "", "is_terminal": True}
        weak_expensive = {"item_id": "3157", "item_name": "Zhonya's Hourglass",
                          "delta_dps": 20.0, "gold": 3250, "dps_per_1k_gold": 6.0,
                          "unique_passive_key": "", "is_terminal": True}
        seed_fn = make_seed_fn({}, extra_rows=[cheap_efficient, weak_expensive])
        plan = plan_build(champion="Akali", seed_fn=seed_fn, beam_width=6, depth=1,
                          clock_s=300.0)
        self.assertEqual(plan.items[0].item_id, "3020",
                         "a legitimately efficient cheap item must still lead")

    def test_mage_front_slot_unaffected_by_the_fix(self):
        # Syndra (mage): her candidate pool here never contains the 2
        # snowball ids, so the fix's skip-list branch is UNREACHABLE for this
        # call - her front slot is provably unchanged by the fix (not a
        # numeric coincidence). Asserting the CONCRETE expected first id (Lich
        # Bane, 3100 - the highest dps+cohesion AP row for Syndra in this pool)
        # rather than a mere "not a snowball" tautology, so a future model
        # regression that reshuffles the mage front slot is actually caught.
        ap_only_catalog = {k: v for k, v in _CATALOG.items() if k not in _SNOWBALL_IDS}
        plan = plan_build(champion="Syndra", seed_fn=make_seed_fn(ap_only_catalog),
                          beam_width=6, depth=1, clock_s=300.0)
        self.assertTrue(plan.items)
        self.assertEqual(plan.items[0].item_id, "3100",
                         "Syndra's mage front slot should be Lich Bane (3100) - "
                         "a shift means the scoring model moved, not this fix")
        self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS)

    def test_ad_assassin_front_slot_unaffected_by_the_fix(self):
        # Qiyana (AD assassin): a disjoint AD-crit pool that never contains
        # the 2 snowball ids at all - same "provably unreachable code path"
        # argument as the mage control above. Concrete expected first id
        # (Infinity Edge, 3031 - the top AD-crit row for Qiyana here) gives
        # the control real teeth against a future front-slot regression.
        plan = plan_build(champion="Qiyana", seed_fn=make_seed_fn(_AD_CATALOG),
                          beam_width=6, depth=1, clock_s=300.0)
        self.assertTrue(plan.items)
        self.assertEqual(plan.items[0].item_id, "3031",
                         "Qiyana's AD front slot should be Infinity Edge (3031) - "
                         "a shift means the scoring model moved, not this fix")
        self.assertNotIn(plan.items[0].item_id, _SNOWBALL_IDS)


if __name__ == "__main__":
    unittest.main()
