"""R144 slice A - mirror-id coverage for the three item-side HP/ally registries.

``core.daemon_slayer_resolver.name_to_id(name, mode)`` hands the engine MIRROR
ids (32xxxx under mode="sr", 22xxxx under mode="arena", plus 44xxxx families).
A registry keyed on BARE 4-digit ids misses those lookups and falls through to a
SILENT 0.0 - no raise, no log. This file pins the audit of that defect class over
``_item_ally_grant`` / ``_item_bonus_hp_amp`` / ``_item_health_stack``.

MEASURED RESULT (16.14.1):
  * ``_item_bonus_hp_amp``  - CLEAN, no change. Warmog's has no 22xxxx / 32xxxx
    mirror at all, and the one 44xxxx Arena mirror (443083) does not carry the
    "Warmog's Vitality" passive - RM-102 already removed it for exactly that
    reason. Absence of a mirror is NOT a defect (nothing to add).
  * ``_item_health_stack`` - CLEAN, no change. Heartsteel's only mirror (223084)
    was already registered.
  * ``_item_ally_grant``   - ONE REAL GAP, fixed here. The R143 pass added the
    mode-mirror rows to ``enchanter_items.json`` but wrote their per-proc fields
    as 0.0 on purpose ("proc and ally-buff fields intentionally 0.0, not measured
    this pass"), so every mirror priced 0.0 while its base priced hundreds of HP.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer._item_ally_grant import (
    _ALLY_GRANT_EXCLUDED_ITEM_IDS,
    _ALLY_GRANT_MIRROR_SOURCE,
    ally_grant_hp,
)
from agents.daemon_slayer._item_bonus_hp_amp import _ITEM_BONUS_HP_AMP_PCT
from agents.daemon_slayer._item_health_stack import _ITEM_HEALTH_STACK_PCT

_ROOT = Path(__file__).resolve().parents[3]
_PATCH = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text().strip()


def _catalog() -> dict:
    path = _ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("data") or doc


def _mirror_ids(catalog: dict, base_id: str) -> list[str]:
    """Every catalog id sharing ``base_id``'s display NAME, excluding the base.

    Audited by NAME here only to ENUMERATE candidates; every magnitude decision
    below is then made per-id off that id's own description text. Auditing this
    family by name alone has produced a false map-30 report in this repo before
    (see the RM-102 note in ``_item_bonus_hp_amp``).
    """
    name = catalog[base_id]["name"]
    return sorted(
        (i for i, r in catalog.items() if r.get("name") == name and i != base_id),
        key=lambda x: (len(x), x),
    )


# Mirror id -> the exact magnitude substring that MUST appear in both the mirror's
# own catalog description and its source row's. This is the provenance guard for
# the fix: the mirrors are priced off the source formula ONLY because their own
# catalog text carries the identical magnitude. A patch that retunes one side
# fails here rather than silently mispricing an ally grant.
_MIRROR_MAGNITUDE_TEXT = {
    "323107": "150 - 350 Health",
    "323190": "290 - 360 Shield",
    "323222": "100 - 250 Health",
    # Helia states no number on EITHER side (base included - the snapshot's
    # 40 + 1.76/level came from a curated source, not this description), so the
    # guard pins the shared passive sentence that defines the model instead.
    "326620": "Gain 30% of pre-mitigation damage dealt to champions as Soul Charges",
}

# Arena mirrors that carry the ally grant in prose but state NO magnitude anywhere
# in the catalog. Deliberately NOT priced - see the HELD block in the module.
_HELD_ARENA_MIRRORS = ("223107", "223190", "223222", "226620")


class AllyGrantMirrorCoverageTests(unittest.TestCase):
    """The R144 headline gap: SR-mode mirror ids priced 0.0."""

    def test_name_to_id_sr_now_hands_back_the_base_not_a_mirror(self):
        """The reachability half of R144 is CLOSED at the resolver.

        Both 6620 and its 326620 mirror are map-11 legal, so the resolver's old
        first-write-wins rule resolved lexicographically and handed SR the
        mirror - that was the live-reachable defect this slice was filed on. The
        rule is now lowest-numeric-id-wins (mirrors are always base + an offset),
        so the canonical row wins. Fixed 2026-07-30 alongside the 16.15.1 refresh,
        where the same bug reached ARAM once Riot flagged the Arena mirror
        223084 map-12 legal beside the 900 HP Heartsteel base.

        The pricing guards below are deliberately KEPT: they are defense in depth
        for any other route that puts a mirror id in front of the pricer, which
        the resolver fix does not cover.
        """
        from core.daemon_slayer_resolver import name_to_id

        self.assertEqual(name_to_id("Echoes of Helia", mode="sr"), "6620")

    def test_sr_mirrors_price_equal_to_their_base(self):
        for mirror, base in sorted(_ALLY_GRANT_MIRROR_SOURCE.items()):
            with self.subTest(mirror=mirror):
                base_hp = ally_grant_hp(base, 13)
                self.assertGreater(base_hp, 0.0, "base row must be non-zero")
                self.assertAlmostEqual(ally_grant_hp(mirror, 13), base_hp, places=6)

    def test_mirror_grant_scales_with_level_like_its_base(self):
        for mirror, base in sorted(_ALLY_GRANT_MIRROR_SOURCE.items()):
            for lvl in (1, 6, 11, 18):
                with self.subTest(mirror=mirror, level=lvl):
                    self.assertAlmostEqual(
                        ally_grant_hp(mirror, lvl), ally_grant_hp(base, lvl), places=6
                    )

    def test_every_mirror_source_pair_is_magnitude_identical_in_the_catalog(self):
        catalog = _catalog()
        self.assertEqual(
            sorted(_ALLY_GRANT_MIRROR_SOURCE), sorted(_MIRROR_MAGNITUDE_TEXT)
        )
        for mirror, base in sorted(_ALLY_GRANT_MIRROR_SOURCE.items()):
            with self.subTest(mirror=mirror):
                needle = _MIRROR_MAGNITUDE_TEXT[mirror]
                self.assertIn(needle, catalog[base]["description"])
                self.assertIn(needle, catalog[mirror]["description"])
                self.assertEqual(catalog[mirror]["name"], catalog[base]["name"])

    def test_held_arena_mirrors_stay_unpriced(self):
        """Arena mirrors state the grant but never its magnitude - HELD, not guessed."""
        catalog = _catalog()
        for mid in _HELD_ARENA_MIRRORS:
            with self.subTest(mirror=mid):
                self.assertIn(mid, catalog)
                self.assertNotIn(mid, _ALLY_GRANT_MIRROR_SOURCE)
                self.assertEqual(ally_grant_hp(mid, 13), 0.0)

    def test_arena_mirrors_are_demonstrably_retuned(self):
        """The evidence that inheriting a base magnitude here would be a guess."""
        catalog = _catalog()
        for base, mirror in (("3190", "223190"), ("3222", "223222"), ("6620", "226620")):
            with self.subTest(mirror=mirror):
                self.assertNotEqual(
                    catalog[base]["stats"].get("FlatHPPoolMod"),
                    catalog[mirror]["stats"].get("FlatHPPoolMod"),
                )


class AllyGrantExclusionMirrorTests(unittest.TestCase):
    """Documented exclusions must survive the mirror sweep, id for id."""

    def test_documented_base_exclusions_are_intact(self):
        for base in ("3109", "3050", "2524", "3876"):
            with self.subTest(base=base):
                self.assertIn(base, _ALLY_GRANT_EXCLUDED_ITEM_IDS)
                self.assertEqual(ally_grant_hp(base, 13), 0.0)

    def test_every_catalog_mirror_of_an_excluded_family_is_also_excluded(self):
        catalog = _catalog()
        for base in ("3109", "3050", "2524"):
            for mid in _mirror_ids(catalog, base):
                with self.subTest(base=base, mirror=mid):
                    self.assertIn(mid, _ALLY_GRANT_EXCLUDED_ITEM_IDS)
                    self.assertEqual(ally_grant_hp(mid, 13), 0.0)

    def test_solstice_sleigh_has_no_mirror_so_none_was_invented(self):
        """TRAP 3: absence of a mirror in the catalog is correct as-is."""
        catalog = _catalog()
        self.assertEqual(_mirror_ids(catalog, "3876"), [])
        for pre in ("22", "32", "44"):
            self.assertNotIn(pre + "3876", _ALLY_GRANT_EXCLUDED_ITEM_IDS)

    def test_no_excluded_id_was_invented(self):
        catalog = _catalog()
        for iid in _ALLY_GRANT_EXCLUDED_ITEM_IDS:
            with self.subTest(item_id=iid):
                self.assertIn(iid, catalog)

    def test_exclusion_beats_the_mirror_table(self):
        self.assertFalse(
            set(_ALLY_GRANT_EXCLUDED_ITEM_IDS) & set(_ALLY_GRANT_MIRROR_SOURCE)
        )


class BonusHpAmpMirrorAuditTests(unittest.TestCase):
    """CLEAN result - Warmog's Vitality has no mirror to add."""

    def test_registry_is_exactly_the_bare_id(self):
        self.assertEqual(sorted(_ITEM_BONUS_HP_AMP_PCT), ["3083"])

    def test_only_mirror_is_443083_and_it_lacks_the_passive(self):
        catalog = _catalog()
        self.assertEqual(_mirror_ids(catalog, "3083"), ["443083"])
        self.assertIn("Warmog's Vitality", catalog["3083"]["description"])
        self.assertNotIn("Warmog's Vitality", catalog["443083"]["description"])

    def test_no_sr_or_arena_prefix_mirror_exists(self):
        catalog = _catalog()
        for mid in ("223083", "323083"):
            self.assertNotIn(mid, catalog)


class HealthStackMirrorAuditTests(unittest.TestCase):
    """CLEAN result - Heartsteel's only mirror was already registered."""

    def test_registry_covers_every_catalog_id_of_the_family(self):
        catalog = _catalog()
        expected = sorted(["3084", *_mirror_ids(catalog, "3084")])
        self.assertEqual(sorted(_ITEM_HEALTH_STACK_PCT), expected)

    def test_no_sr_or_legendary_prefix_mirror_exists(self):
        catalog = _catalog()
        for mid in ("323084", "443084"):
            self.assertNotIn(mid, catalog)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
