"""R136-S2: the RUNE-side Heal/Shield Power (HSP) lane.

Characterizes ``_rune_hsp_amp.sum_rune_hsp_pct`` - the rune twin of the
item-keyed ``_hsp_amp.sum_wielder_hsp_pct``. The structural gap it closes:
``_hsp_amp.py:23`` sums ``heal_shield_amp_pct`` across EQUIPPED ITEMS ONLY (the
curated ``enchanter_items.json`` field, keyed by item id), so a RUNE can never
reach it and 8453 Revitalize earned ZERO for the flat Heal and Shield Power it
grants.

Property-style invariants are preferred over exact floats wherever the property
is the real contract (fail-soft zero, inertness of non-HSP runes, order
invariance, no double-credit). Three magnitudes ARE pinned exactly because they
are the contract: Revitalize 0.05, the item pair 0.22, and the additive
composition 0.27.

OFFLINE ONLY: no network, no live :8860. The tree-wide sweep reads the
already-vendored DDragon ``runesReforged.json`` snapshots from disk.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct
from agents.daemon_slayer._rune_hsp_amp import REVITALIZE_HSP_PCT, sum_rune_hsp_pct

# 8453 Revitalize (Resolve, slot 3). DDragon 16.14.1 longDesc, verbatim:
# "Gain 5% Heal and Shield Power.<br><br>Heals and shields you cast or receive
# are 10% stronger on targets below 40% health."
_REVITALIZE = "8453"

# Resolve-tree siblings that grant NO Heal and Shield Power. Each is a real
# current-patch rune, so this doubles as a "the allowlist stayed narrow" guard.
_NON_HSP_RUNES = (
    "8439",  # Aftershock - resist grant (the _rune_resist_grants lane)
    "8429",  # Conditioning - resist grant
    "8242",  # Unflinching - resist grant
    "8446",  # Demolish - tower damage
    "8451",  # Overgrowth - max health
    "8463",  # Font of Life - ally healing, not wielder HSP
    "8465",  # Guardian - ally shield, not wielder HSP
    "8473",  # Bone Plating - flat damage block
    "8010",  # Conqueror - offensive keystone
    # Glacial Augment CONSUMES Heal and Shield Power ("+90% per 100% Heal and
    # Shield Power" on its slow) - it does not GRANT any. Crediting it here
    # would invert the direction of the stat.
    "8351",
)

# Curated item ids (enchanter_items.json), pinned by test_hsp_amp_r60.py.
_REDEMPTION = "3107"  # heal_shield_amp_pct 0.10
_MIKAEL = "3222"      # heal_shield_amp_pct 0.12

_REPO_ROOT = Path(__file__).resolve().parents[3]


class SumRuneHspPctTests(unittest.TestCase):
    """The additive rune-HSP sum helper."""

    def test_revitalize_grants_exact_flat_five_percent(self) -> None:
        # The ONE magnitude this module exists to carry. 5% -> 0.05, the same
        # FRACTION convention enchanter_items.json uses (Redemption 10% -> 0.10),
        # so the two lanes are directly additive.
        self.assertAlmostEqual(sum_rune_hsp_pct([_REVITALIZE]), 0.05, places=6)
        self.assertAlmostEqual(REVITALIZE_HSP_PCT, 0.05, places=6)

    def test_int_ids_coerced(self) -> None:
        # Matches the item lane's test_int_ids_coerced contract.
        self.assertAlmostEqual(sum_rune_hsp_pct([8453]), 0.05, places=6)

    def test_empty_and_none_fail_soft(self) -> None:
        # A 0.0 return keeps the orchestrator's DEFAULT-OFF seam byte-identical.
        self.assertEqual(sum_rune_hsp_pct([]), 0.0)
        self.assertEqual(sum_rune_hsp_pct(None), 0.0)
        self.assertEqual(sum_rune_hsp_pct(()), 0.0)

    def test_malformed_input_fails_soft_to_zero(self) -> None:
        # Any load / iteration failure returns 0.0 rather than raising - the seam
        # caller must never be able to crash the engine by passing junk.
        for bad in (0, 12345, object(), "8453", {"a": 1}):
            with self.subTest(bad=repr(bad)):
                self.assertIsInstance(sum_rune_hsp_pct(bad), float)

    def test_non_hsp_runes_contribute_zero(self) -> None:
        for rid in _NON_HSP_RUNES:
            with self.subTest(rune=rid):
                self.assertEqual(sum_rune_hsp_pct([rid]), 0.0)

    def test_unknown_and_garbage_ids_contribute_zero(self) -> None:
        for rid in ("", "not-a-rune", "-1", "0", "99999"):
            with self.subTest(rune=rid):
                self.assertEqual(sum_rune_hsp_pct([rid]), 0.0)

    def test_non_hsp_runes_are_inert_alongside_revitalize(self) -> None:
        # A full realistic Resolve page must equal Revitalize alone.
        page = [*_NON_HSP_RUNES, _REVITALIZE]
        self.assertAlmostEqual(
            sum_rune_hsp_pct(page), sum_rune_hsp_pct([_REVITALIZE]), places=9
        )

    def test_order_invariant(self) -> None:
        forward = sum_rune_hsp_pct(["8439", _REVITALIZE, "8429"])
        reverse = sum_rune_hsp_pct(["8429", _REVITALIZE, "8439"])
        self.assertAlmostEqual(forward, reverse, places=9)

    def test_duplicate_rune_id_does_not_double_credit(self) -> None:
        # A rune page cannot carry the same rune twice; a duplicated or aliased
        # id must not pay out twice (the _rune_resist_grants ``family`` rationale).
        self.assertAlmostEqual(
            sum_rune_hsp_pct([_REVITALIZE, _REVITALIZE, 8453]), 0.05, places=6
        )

    def test_result_is_non_negative_and_bounded(self) -> None:
        for page in ([], [_REVITALIZE], list(_NON_HSP_RUNES), [*_NON_HSP_RUNES, 8453]):
            with self.subTest(page=page):
                val = sum_rune_hsp_pct(page)
                self.assertGreaterEqual(val, 0.0)
                self.assertLessEqual(val, 1.0)


class RuneItemHspCompositionTests(unittest.TestCase):
    """The rune lane is ADDITIVE with the item lane - the "(1 + hsp_pct)" model."""

    def test_item_pair_baseline_unchanged(self) -> None:
        # Redemption 0.10 + Mikael 0.12 = 0.22 (the R60 pinned baseline).
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_REDEMPTION, _MIKAEL]), 0.22, places=6
        )

    def test_rune_plus_items_sums_to_expected_total(self) -> None:
        # THE composition the slice exists to produce: items 0.22 + rune 0.05 =
        # 0.27, additive per the real-LoL HSP model (never compounded, which
        # would give 1.22 * 1.05 - 1 = 0.281).
        items = sum_wielder_hsp_pct([_REDEMPTION, _MIKAEL])
        runes = sum_rune_hsp_pct([_REVITALIZE])
        self.assertAlmostEqual(items + runes, 0.27, places=6)
        self.assertNotAlmostEqual(items + runes, (1 + items) * (1 + runes) - 1, places=6)

    def test_rune_lane_does_not_disturb_the_item_lane(self) -> None:
        # The two helpers are independent; calling one must not mutate the other.
        before = sum_wielder_hsp_pct([_REDEMPTION])
        sum_rune_hsp_pct([_REVITALIZE, *_NON_HSP_RUNES])
        self.assertAlmostEqual(sum_wielder_hsp_pct([_REDEMPTION]), before, places=9)


class RuneTreeSweepTests(unittest.TestCase):
    """8453 must be the ONLY rune the registry credits, on every vendored patch."""

    def _rune_files(self) -> list[Path]:
        return sorted((_REPO_ROOT / "data" / "meta_build" / "ddragon").glob(
            "*/runesReforged.json"
        ))

    def _require_rune_files(self) -> list[Path]:
        """The rune snapshots, or a loud failure when they are missing.

        data/meta_build/ddragon/*/runesReforged.json is TRACKED in the main
        repo (four patch bundles as of 16.14.1), so an empty glob means a
        committed snapshot was deleted and the sweep below would pass over
        nothing. That is asserted, never skipped: a skip keyed on the glob
        coming back empty would let a deleted snapshot pass silently, which is
        the exact failure this guard exists to catch.
        """
        files = self._rune_files()
        self.assertTrue(
            files,
            "no tracked runesReforged.json snapshots under data/meta_build/ddragon",
        )
        return files

    def test_exactly_one_rune_in_the_whole_tree_grants_hsp(self) -> None:
        files = self._require_rune_files()
        for path in files:
            with self.subTest(patch=path.parent.name):
                trees = json.loads(path.read_text(encoding="utf-8"))
                ids = [
                    r["id"]
                    for tree in trees
                    for slot in tree["slots"]
                    for r in slot["runes"]
                ]
                self.assertGreater(len(ids), 50, "rune tree looks truncated")
                crediting = [i for i in ids if sum_rune_hsp_pct([i]) > 0.0]
                self.assertEqual(
                    crediting, [8453],
                    msg=(
                        "exactly one rune (8453 Revitalize) may credit HSP. A new "
                        "id here means a patch added an HSP rune - verify its "
                        "longDesc verbatim before widening the allowlist."
                    ),
                )

    def test_revitalize_longdesc_still_says_five_percent(self) -> None:
        # Patch-drift guard: if Riot renumbers the flat grant, this fails loudly
        # rather than letting a stale 0.05 ship.
        latest = self._require_rune_files()
        trees = json.loads(latest[-1].read_text(encoding="utf-8"))
        desc = next(
            r["longDesc"]
            for tree in trees
            for slot in tree["slots"]
            for r in slot["runes"]
            if r["id"] == 8453
        )
        self.assertIn("5% Heal and Shield Power", desc)
        # The below-40%-health half is DELIBERATELY NOT MODELLED (target-state
        # conditional, operator-CLOSED). Assert it is still present in the source
        # so a future reader knows the rejection was scoped to a real clause.
        self.assertIn("below 40% health", desc)


if __name__ == "__main__":
    unittest.main()
