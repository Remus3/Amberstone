"""B4 (OVERLAY_BUILD_MASTER_PLAN WP-B4): MF SR deterministic fixture oracle.

The fixture web/js/test/fixtures/mf_sr_build.json encodes the operator-brief ADC
Miss Fortune SR example as a deterministic render + scoring acceptance oracle for
the in-game build module (B2 3-row scaffold + B3 owned-greying) and the C2 scoring
model (core/build_planner/scoring).

There is NO JS test runner (the page code has no jsdom/node harness), so this
PYTHON test is the fixture's consumer - mirroring the grep-style
tests/test_overlay_b3_row_item_semantics. It validates:
  * the fixture loads + is well-formed + 7-bit ASCII (repo hard rule);
  * the META row matches the captured marksman-correct MF carry order;
  * the archetype-routing signature the operator flagged - MF DEFAULT resolves
    assassin, so archetype=carry must be explicit, and the two builds differ;
  * the owned-greying oracle: a faithful Python mirror of the JS
    _bmPartitionOwned (owned-first, stable) + the first-non-owned "next" rule
    reproduces every snapshot's expected greyed-set + next-buy (incl a non-prefix
    owned snapshot that genuinely exercises sort-left);
  * the C2 scoring oracle: score_build ranks the marksman build above an
    off-archetype AP build for MissFortune (real synergy + DPS deltas, robust
    margin - NOT fixture-shaped);
  * the live-deviation antiheal linkage (Executioner's component -> Mortal Reminder).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "web" / "js" / "test" / "fixtures" / "mf_sr_build.json"

# Captured marksman-correct MF carry order (live /api/build-order, patch 16.13.1).
_EXPECTED_META_IDS = ["3153", "3172", "3085", "3036", "3032", "3031"]


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _partition_owned(order_ids, owned_set):
    """Faithful Python mirror of active_match.js _bmPartitionOwned (owned-first,
    stable - NOT a re-sort) + the first-non-owned "next" rule. Returns
    (partitioned_ids, next_id)."""
    owned = [i for i in order_ids if i in owned_set]
    rest = [i for i in order_ids if i not in owned_set]
    return owned + rest, (rest[0] if rest else None)


class FixturePresence(unittest.TestCase):
    def test_fixture_exists(self):
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")

    def test_fixture_valid_json(self):
        self.assertIsInstance(_load(), dict)

    def test_required_keys(self):
        fx = _load()
        for k in ("champion", "mode", "meta_build", "alt_assassin_build",
                  "owned_snapshots", "live_deviation", "scoring_oracle",
                  "knob_defaults"):
            self.assertIn(k, fx, f"fixture missing top-level key {k}")

    def test_champion_and_mode(self):
        fx = _load()
        self.assertEqual(fx["champion"], "MissFortune")
        self.assertEqual(fx["mode"], "SR")


class FixtureAscii(unittest.TestCase):
    """Repo hard rule: authored artifacts are 7-bit ASCII (no smart quotes/dashes)."""

    def test_ascii_only(self):
        raw = FIXTURE.read_bytes()
        nonascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(nonascii, [], f"non-ASCII bytes in fixture: {nonascii[:5]}")


class MetaBuildShape(unittest.TestCase):
    def setUp(self):
        self.meta = _load()["meta_build"]

    def test_carry_archetype(self):
        self.assertEqual(self.meta["archetype"], "carry")

    def test_six_items(self):
        self.assertEqual(len(self.meta["order"]), 6)

    def test_order_matches_captured_marksman_path(self):
        ids = [r["item_id"] for r in self.meta["order"]]
        self.assertEqual(ids, _EXPECTED_META_IDS)

    def test_each_row_shape(self):
        for r in self.meta["order"]:
            for f in ("slot", "item_id", "item_name", "gold"):
                self.assertIn(f, r, f"row {r} missing {f}")
            self.assertIsInstance(r["item_id"], str)  # engine item ids are strings

    def test_boots_pinned_slot2(self):
        boots = self.meta["order"][1]
        self.assertTrue(boots.get("boots"))
        self.assertEqual(boots["item_id"], "3172")


class ArchetypeRoutingSignature(unittest.TestCase):
    """The operator-brief gotcha: MF default resolves assassin; archetype=carry is
    explicit. The two builds carry distinct archetype signatures."""

    def setUp(self):
        fx = _load()
        self.carry_ids = [r["item_id"] for r in fx["meta_build"]["order"]]
        self.assassin_ids = [r["item_id"] for r in fx["alt_assassin_build"]["order"]]

    def test_carry_marksman_tells(self):
        # Runaan's (3085) + Yun Tal crit (3032) + carry boots (3172) = marksman.
        for iid in ("3085", "3032", "3172"):
            self.assertIn(iid, self.carry_ids)

    def test_assassin_default_tells(self):
        # Lethality boots (3173) + Essence Reaver (3508) = the default/assassin path.
        for iid in ("3173", "3508"):
            self.assertIn(iid, self.assassin_ids)

    def test_builds_differ(self):
        self.assertNotEqual(set(self.carry_ids), set(self.assassin_ids))

    def test_assassin_default_is_not_the_marksman_path(self):
        # The default build lacks the carry boots + Yun Tal -> why explicit carry.
        self.assertNotIn("3172", self.assassin_ids)
        self.assertNotIn("3032", self.assassin_ids)


class OwnedGreyingOracle(unittest.TestCase):
    """Mirror the JS _bmPartitionOwned + first-non-owned "next" over each snapshot."""

    def setUp(self):
        self.fx = _load()
        self.order_ids = [r["item_id"] for r in self.fx["meta_build"]["order"]]
        self.id2name = {r["item_id"]: r["item_name"]
                        for r in self.fx["meta_build"]["order"]}

    def test_snapshots_present(self):
        self.assertGreaterEqual(len(self.fx["owned_snapshots"]), 4)

    def test_each_snapshot_greying(self):
        for snap in self.fx["owned_snapshots"]:
            owned = set(snap["owned_item_ids"])
            # No phantom owned: every owned id is in the meta order.
            self.assertTrue(owned.issubset(set(self.order_ids)), snap["label"])
            partitioned, nxt = _partition_owned(self.order_ids, owned)
            # greyed = the owned members (which the partition floats to the front).
            greyed = [i for i in partitioned if i in owned]
            self.assertEqual(set(greyed), set(snap["expected_greyed"]), snap["label"])
            self.assertEqual(partitioned[:len(owned)], greyed, snap["label"])  # sort-left
            # next-buy cross-checked against an independent first-non-owned scan.
            indep_next = next((i for i in self.order_ids if i not in owned), None)
            self.assertEqual(nxt, indep_next, snap["label"])
            self.assertEqual(nxt, snap["expected_next_id"], snap["label"])

    def test_next_name_matches_catalog(self):
        for snap in self.fx["owned_snapshots"]:
            nid = snap["expected_next_id"]
            if nid:
                self.assertEqual(self.id2name.get(nid),
                                 snap["expected_next_name"], snap["label"])

    def test_sort_left_snapshot_is_non_prefix(self):
        # At least one snapshot owns a NON-prefix item (so the partition actually
        # reorders) - otherwise sort-left is never exercised.
        order = self.order_ids
        found = False
        for snap in self.fx["owned_snapshots"]:
            owned = snap["owned_item_ids"]
            if owned and owned != order[:len(owned)]:
                found = True
        self.assertTrue(found, "no non-prefix owned snapshot exercises sort-left")


class ScoringOracle(unittest.TestCase):
    """C2 score_build ranks the MF marksman build above an off-archetype AP build."""

    def setUp(self):
        self.oracle = _load()["scoring_oracle"]

    def test_marksman_beats_offclass_ap(self):
        from core.build_planner.scoring import score_build
        seed = self.oracle["seed_rows"]
        champ = self.oracle["champ"]
        oc = self.oracle["owned_count"]
        mk = score_build(self.oracle["marksman_build_ids"], champ, seed, owned_count=oc)
        ap = score_build(self.oracle["offclass_ap_build_ids"], champ, seed, owned_count=oc)
        self.assertGreater(
            mk.total, ap.total,
            f"marksman {mk.total:.3f} must outrank AP {ap.total:.3f} for {champ}")

    def test_seed_carries_a_dps_signal(self):
        # The seed table must carry a real DPS signal for the marksman core, else
        # the comparison would collapse to cohesion-only.
        seed_ids = {r["item_id"] for r in self.oracle["seed_rows"]}
        self.assertIn("3153", seed_ids)  # Blade of The Ruined King
        self.assertGreater(sum(r["delta_dps"] for r in self.oracle["seed_rows"]), 0.0)

    def test_build_ids_are_strings(self):
        for key in ("marksman_build_ids", "offclass_ap_build_ids"):
            for iid in self.oracle[key]:
                self.assertIsInstance(iid, str, f"{key} id {iid!r} not a string")


class LiveDeviation(unittest.TestCase):
    """The antiheal deviation: Executioner's component builds into Mortal Reminder."""

    def setUp(self):
        self.dev = _load()["live_deviation"]

    def test_antiheal_vs_heal_enemy(self):
        self.assertGreaterEqual(self.dev["enemy_heal_sources"], 2)

    def test_component_builds_into_target(self):
        # Documented linkage 3123 -> 3033 (verified vs /api/dictionary/items).
        self.assertEqual(self.dev["inserted_component"]["item_id"], "3123")
        self.assertEqual(self.dev["completed_swap_target"]["item_id"], "3033")


if __name__ == "__main__":
    unittest.main()
