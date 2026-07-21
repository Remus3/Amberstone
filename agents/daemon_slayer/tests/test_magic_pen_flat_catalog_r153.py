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
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.effects import effective_target_mr

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The full 706-item DDragon catalog. The Share handoff package ships the
# per-patch vendored copy but not data/meta, so resolve either layout -
# both files were verified to yield an identical swept set.
_META_CATALOG = _REPO_ROOT / "data" / "meta" / "ddragon_items.json"
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Flat pen only. A percent source renders as "<attention>40%</attention>"
# and cannot match, because the digits must be followed directly by the
# closing tag.
_FLAT_MAGIC_PEN_RE = re.compile(
    r"<attention>\s*(\d+(?:\.\d+)?)\s*</attention>\s*Magic Penetration"
)

# Arena mirrors whose DDragon magnitude diverges from the credited one.
# Out of R153 scope and escalated separately: they collide with the
# standing "Arena mirrors inherit SR coefficients" doctrine, exactly like
# the 7 rows R152 held back. Pinned below so a fix cannot land silently.
#   item_id -> (DDragon 16.14.1 value, currently credited value)
_ARENA_DRIFT_HOLDOUT = {
    "223020": (20.0, 12.0),   # Sorcerer's Shoes (Arena) vs SR 3020 = 12
    "224645": (10.0, 15.0),   # Shadowflame (Arena)      vs SR 4645 = 15
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
        for iid, (name, stated) in sorted(self.swept.items()):
            if iid in _ARENA_DRIFT_HOLDOUT:
                continue
            with self.subTest(item_id=iid, name=name):
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].magic_pen_flat, stated, places=3
                )

    def test_arena_drift_holdout_still_diverges(self) -> None:
        # Fails the day someone reconciles one of these, forcing the
        # Arena-inheritance question to be answered deliberately rather
        # than absorbed into an unrelated sweep.
        for iid, (ddragon, credited) in _ARENA_DRIFT_HOLDOUT.items():
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(self.swept[iid][1], ddragon, places=3)
                self.assertAlmostEqual(
                    ITEM_EFFECTS[iid].magic_pen_flat, credited, places=3
                )

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
