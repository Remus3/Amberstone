"""R153 - flat magic-penetration stat-block parity, plus a permanent
catalog guard.

Same class of catalog defect as the R152 lethality slice. DDragon's
structured ``stats`` block has NO flat-magic-pen key, so the magnitude
survives only inside the ``<stats>`` HTML of ``description``:

    <attention>12</attention> Magic Penetration

``ITEM_EFFECTS[...].magic_pen_flat`` is therefore the ONLY source of
flat magic pen in the engine, consumed by
``effects.effective_target_mr`` (flat pen subtracts last, after MR
reduction and percent pen). An id absent from ``ITEM_EFFECTS``, or
present with ``magic_pen_flat`` unset, silently reads 0.0.

R153 credits item 1111 ("Jarvan I's", the ARAM augment-gated all-boots
prismatic), the ONE swept id that had no ``ITEM_EFFECTS`` entry at all
even though DS already registered its 10 ability haste and 30 tenacity
in the sibling registries.

The sweep test below is the durable half: it re-derives the swept set
from the shipped catalog on every run, so any FUTURE item authored the
same way - pen stated in prose, omitted from ``stats`` - fails here
immediately instead of quietly costing an item its penetration.

R161 - THE ARENA-DRIFT ESCALATION IS RESOLVED AS DOCTRINE B, AND THIS
SWEEP IS NOW EXEMPTION-FREE ON THIS AXIS. R153 shipped with a two-row
holdout (``223020`` stated 20 while crediting SR 3020's 12, ``224645``
stated 10 while crediting SR 4645's 15) because reconciling them
collided with the standing "Arena mirrors inherit SR coefficients"
doctrine. The director answered it: when a DDragon Arena mirror states
its OWN explicit stat line that differs from its SR twin, THE ARENA
FEED VALUE WINS. Both rows now credit their stated magnitude, so the
plain stated-equals-credited assertion covers every swept id with no
skip list - which is the whole point of the doctrine call. SR parents
are untouched (3020 stays 12, 4645 stays 15).

RM-222 - THE LAYOUT-AGREEMENT GUARD THE FLAT AXIS NEVER HAD. R160 grew
``test_both_catalog_layouts_agree`` for the PERCENT axis when that axis
broke. The flat axis stayed quiet and unguarded while carrying the only
live divergence in either sweep: item 3175 states 20 in live
``data/meta`` and 18 in the pinned 16.15.1 snapshot, carried forward by
RM-190. Nothing in the repo compared the two layouts on this axis, so a
SECOND such move would have landed silently. The guard below closes that,
with its own ``_PINNED_CARRY_FORWARD`` allowlist.

The flat regex is deliberately NOT folded into R160's pattern tuple. The
two sweeps are disjoint by MAGNITUDE by design - the percent pattern
requires a "%" this one forbids - and merging them would re-open the
cross-fold that R160's
``test_one_item_states_both_flat_and_percent_magic_pen`` exists to pin.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.effects import effective_target_mr

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The full 706-item DDragon catalog. Two layouts carry it - the live
# data/meta copy and the per-patch vendored snapshot - so resolve either;
# both files were verified to yield an identical swept set.
_META_CATALOG = _REPO_ROOT / "data" / "meta" / "ddragon_items.json"
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


# Is the LIVE DDragon catalog present? ``data/meta/ddragon_items.json`` tracks
# live DDragon; the per-patch snapshot under ``data/daemon_slayer/<patch>/``
# is PINNED (16.15.1 today) and the registry deliberately runs AHEAD of it.
# RM-190 carried item 3175 ``magic_pen_flat`` 18 -> 20 out of the 16.16.1
# mirror while leaving the DS snapshot pinned, and 16.17.1 carried 226694
# ``armor_pen_pct`` 0.40 -> 0.45 the same way. So a magnitude-parity assertion
# is only meaningful against the LIVE catalog. Comparing the registry against
# the pinned snapshot instead measures it against a catalog it no longer
# describes and manufactures a FALSE failure. The swept SET is stable across
# the two layouts, so the population sweeps keep the fallback; magnitude
# parity demands the live catalog.


def _require_live_catalog(case: "unittest.TestCase") -> None:
    """Require the live catalog before a magnitude-parity assertion.

    FAILS rather than skips on absence. ``data/meta/ddragon_items.json`` is
    TRACKED, so its absence is a deleted committed file - a DEFECT that must
    fail loudly - and a skip keyed on it would be an always-passing guard
    (tests/test_skip_condition_hygiene.py, docs/SKIPIF_AUDIT_2026-07-27.md).
    """
    case.assertTrue(
        _META_CATALOG.is_file(), f"tracked {_META_CATALOG} is missing"
    )

# Flat pen only. A percent source renders as "<attention>40%</attention>"
# and cannot match, because the digits must be followed directly by the
# closing tag.
_FLAT_MAGIC_PEN_RE = re.compile(
    r"<attention>\s*(\d+(?:\.\d+)?)\s*</attention>\s*Magic Penetration"
)

# Ids where the LIVE data/meta catalog and the PINNED per-patch snapshot
# legitimately state a different flat magic pen, because Riot moved the
# magnitude after the DS snapshot was pinned and the registry carried the NEW
# value forward (a1 posture: carry the magnitude, do not bump the snapshot).
# ITEM_EFFECTS credits the LIVE value.
#
# item_id -> (live stated, pinned stated). FLAT, not keyed by regex source the
# way R160's twin is: this module sweeps exactly ONE pattern, so a per-pattern
# key would be a constant lookup dressed up as a dimension.
_PINNED_CARRY_FORWARD = {
    # RM-190 carried 3175 Spellslinger's Shoes 18 -> 20 out of the 16.16.1
    # mirror while leaving the snapshot at 16.15.1, which still states 18.
    "3175": ("20", "18"),
}


def _catalog() -> dict:
    if _META_CATALOG.is_file():
        raw = _META_CATALOG.read_text(encoding="utf-8")
    else:
        patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        raw = (_PATCH_ROOT / patch / "items.json").read_text(encoding="utf-8")
    return json.loads(raw)["data"]


def _swept_flat_magic_pen() -> dict:
    """item_id -> (name, flat magic pen stated in the description prose)."""
    found = {}
    for iid, entry in _catalog().items():
        match = _FLAT_MAGIC_PEN_RE.search(entry.get("description", ""))
        if match:
            found[iid] = (entry.get("name", ""), float(match.group(1)))
    return found


def _sweep_stated(catalog: dict) -> dict:
    """item_id -> flat magic pen as the RAW string the catalog prints.

    Compared as strings on purpose. This guard is about the two catalog
    LAYOUTS agreeing on what they state, so an authoring change from "20" to
    "20.0" is a real difference and ``float()`` would launder it away.
    """
    return {
        iid: _FLAT_MAGIC_PEN_RE.search(entry["description"]).group(1)
        for iid, entry in catalog.items()
        if _FLAT_MAGIC_PEN_RE.search(entry.get("description", ""))
    }


def _layout_divergences(live: dict, pinned: dict) -> dict:
    """item_id -> (live stated, pinned stated) for every id the two disagree on.

    A free function taking BOTH sides as arguments so the detector can be
    driven with a perturbed input - the same reason R160 factors
    ``_parity_mismatches`` out. A guard that cannot fail is worse than no
    guard.
    """
    return {
        iid: (live.get(iid), pinned.get(iid))
        for iid in sorted(set(live) | set(pinned))
        if live.get(iid) != pinned.get(iid)
    }


class R153JarvanOnesFlatMagicPenTests(unittest.TestCase):
    """Item 1111 - the single registration gap R153 closes."""

    def test_jarvan_ones_entry_exists_and_credits_twelve(self) -> None:
        effect = ITEM_EFFECTS.get("1111")
        self.assertIsNotNone(effect, "1111 (Jarvan I's) missing from ITEM_EFFECTS")
        self.assertEqual(effect.name, "Jarvan I's")
        self.assertAlmostEqual(effect.magic_pen_flat, 12.0, places=3)

    def test_credit_reaches_the_mr_consumer(self) -> None:
        # A field with no consumer is inert, so pin the consumer too:
        # flat pen subtracts 1:1 off post-reduction MR.
        self.assertAlmostEqual(
            effective_target_mr(100.0, [ITEM_EFFECTS["1111"]]),
            88.0,
            places=3,
        )

    def test_registration_is_consistent_with_sibling_registries(self) -> None:
        # DS already knew this item on its other two stat axes; the pen
        # credit is what restored parity across all three.
        from agents.daemon_slayer._item_ability_haste import item_ability_haste
        from agents.daemon_slayer._item_tenacity import item_tenacity

        self.assertAlmostEqual(item_ability_haste("1111"), 10.0, places=3)
        self.assertAlmostEqual(item_tenacity("1111"), 30.0, places=3)


class R153FlatMagicPenCatalogSweepTests(unittest.TestCase):
    """Permanent guard - re-derived from the shipped catalog each run."""

    def setUp(self) -> None:
        self.swept = _swept_flat_magic_pen()

    def test_sweep_finds_the_known_population(self) -> None:
        # Pinned so a catalog change that DROPS a pen item is as loud as
        # one that adds an uncredited one.
        self.assertEqual(
            sorted(self.swept),
            sorted(
                [
                    "1111", "223020", "224645", "224646", "3020",
                    "3175", "447113", "4645", "4646", "667101",
                ]
            ),
        )

    def test_every_swept_item_is_registered(self) -> None:
        for iid, (name, stated) in sorted(self.swept.items()):
            with self.subTest(item_id=iid, name=name):
                effect = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(
                    effect, f"{iid} ({name}) states {stated} flat magic pen but has no ITEM_EFFECTS entry"
                )
                self.assertGreater(
                    effect.magic_pen_flat,
                    0.0,
                    f"{iid} ({name}) states {stated} flat magic pen but credits 0.0",
                )

    def test_registered_magnitude_matches_the_stated_value(self) -> None:
        _require_live_catalog(self)
        # R161 doctrine B: no exemptions. Every swept id, Arena mirror or
        # not, credits exactly the magnitude its own description states.
        for iid, (name, stated) in sorted(self.swept.items()):
            with self.subTest(item_id=iid, name=name):
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].magic_pen_flat, stated, places=3
                )

    def test_arena_mirrors_credit_their_own_feed_not_their_sr_twin(self) -> None:
        # The two rows R153 held back. Asserted as a DIVERGENCE so a
        # regression that re-inherits the SR magnitude fails loudly here
        # rather than only inside the generic parity loop above.
        for arena, sr in (("223020", "3020"), ("224645", "4645")):
            with self.subTest(item_id=arena):
                arena_credit = ITEM_EFFECTS[arena].magic_pen_flat
                self.assertAlmostEqual(
                    arena_credit, self.swept[arena][1], places=3
                )
                self.assertAlmostEqual(
                    ITEM_EFFECTS[sr].magic_pen_flat, self.swept[sr][1], places=3
                )
                self.assertNotAlmostEqual(
                    arena_credit, ITEM_EFFECTS[sr].magic_pen_flat, places=3
                )

    def _both_layouts(self) -> tuple:
        """(live, pinned) stated-magnitude maps.

        Asserts on a missing catalog, never skips: both catalogs are TRACKED,
        so keying a skip on absence would let a deleted committed catalog
        silently SKIP, which is one of the two failures this guard exists to
        catch.
        """
        patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
        patch_file = _PATCH_ROOT / patch / "items.json"
        self.assertTrue(
            _META_CATALOG.is_file(), f"tracked {_META_CATALOG} is missing"
        )
        self.assertTrue(patch_file.is_file(), f"tracked {patch_file} is missing")
        return (
            _sweep_stated(
                json.loads(_META_CATALOG.read_text(encoding="utf-8"))["data"]
            ),
            _sweep_stated(
                json.loads(patch_file.read_text(encoding="utf-8"))["data"]
            ),
        )

    def test_both_catalog_layouts_agree(self) -> None:
        # RM-222. The two layouts - the pinned per-patch snapshot and the live
        # data/meta catalog - stated the same magnitudes until the DS
        # snapshot fell behind live DDragon: the snapshot is PINNED at 16.15.1
        # while data/meta tracks live, so a magnitude Riot moves in between
        # shows up in ONE layout only. That is EXPECTED under the a1 posture,
        # so this guard does not demand equality - it demands that every
        # divergence is a DOCUMENTED carry-forward. An undocumented divergence
        # is real drift and goes red, and a carry-forward that DISAPPEARS (a
        # snapshot bump realigning the layouts) goes red too, so the list
        # cannot rot silently.
        live, pinned = self._both_layouts()
        self.assertEqual(
            _layout_divergences(live, pinned),
            _PINNED_CARRY_FORWARD,
            "live data/meta vs the pinned DS snapshot diverged on a flat "
            "magic pen id that is not a documented carry-forward. Either a "
            "new patch moved a magnitude (carry it into ITEM_EFFECTS and "
            "record it in _PINNED_CARRY_FORWARD), or the DS snapshot was "
            "bumped and the entry is now stale.",
        )

    def test_layout_detector_reports_a_new_divergence(self) -> None:
        # Drive the detector with a perturbed live side and prove it names
        # exactly the perturbed id ON TOP of the documented carry-forward.
        # Without this, the assertion above could pass because
        # _layout_divergences never returns anything at all.
        live, pinned = self._both_layouts()
        self.assertIn("3020", live)
        perturbed = dict(live)
        perturbed["3020"] = str(int(perturbed["3020"]) + 1)
        self.assertEqual(
            sorted(_layout_divergences(perturbed, pinned)),
            sorted(set(_PINNED_CARRY_FORWARD) | {"3020"}),
        )

    def test_layout_detector_reports_a_vanished_divergence(self) -> None:
        # The other direction, which is the half a plain "no new drift" check
        # misses: realign 3175 and the documented carry-forward must stop
        # being reported, so a stale allowlist entry surviving a snapshot bump
        # fails the assertion above instead of passing quietly.
        live, pinned = self._both_layouts()
        realigned = dict(live)
        realigned["3175"] = pinned["3175"]
        self.assertNotIn("3175", _layout_divergences(realigned, pinned))

    def test_placeholder_stat_item_is_not_swept(self) -> None:
        # 443064 Talisman of Ascension renders every stat line as a
        # literal "?" ("? || ?%" Magic Penetration) over an EMPTY stats
        # block - it is an adaptive item with no static magnitude to
        # credit. No digits means the sweep cannot pick it up, which is
        # the correct outcome and not an oversight.
        self.assertNotIn("443064", self.swept)
        self.assertEqual(_catalog()["443064"]["stats"], {})
        self.assertAlmostEqual(ITEM_EFFECTS["443064"].magic_pen_flat, 0.0, places=3)

    def test_percent_pen_sources_are_not_swept_as_flat(self) -> None:
        # Void Staff / Cryptbloom carry percent pen only; folding a
        # percent magnitude into the flat term would be a real bug.
        for iid in ("3135", "3137"):
            with self.subTest(item_id=iid):
                self.assertNotIn(iid, self.swept)
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].magic_pen_flat, 0.0, places=3
                )


if __name__ == "__main__":
    unittest.main()
