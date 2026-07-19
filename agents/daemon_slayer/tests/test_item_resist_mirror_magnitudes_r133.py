"""Every ``_item_resist_grants`` row pinned to its OWN DDragon text (R133).

Regression coverage for a DATA-CORRECTNESS defect: four mirror rows in
``_item_resist_grants`` were seeded with the note "base nominal", meaning the
SR / Arena BASE magnitude was copied onto the mode-mirror id. Presence in the
item index was verified when the registry was built; the MAGNITUDE was not.
Three of the four copies were wrong, because a mode mirror is a genuinely
RETUNED item, not a re-skin of its base:

  * Jak'Sho, The Protean - base 6665 "increase your bonus Armor and Magic Resist
    by 30%"; Arena mirror 226665 says 40%. The registry carried 30 -> the mirror
    UNDER-credited.
  * Force of Nature - base 4401 "Gain 70 Magic Resist" at 8 stacks; Arena mirror
    224401 "gain 50 Magic Resist" at 10 stacks. The registry carried 70 -> the
    mirror OVER-credited.
  * Cloak of Starry Night - map-30 443059 "Increase your Magic Resist by 20%";
    map-11 mirror 663059 says 10%. The registry carried 20 -> the mirror
    OVER-credited.
  * Shield of Molten Stone - 443058 and mirror 663058 BOTH say 20%, so that one
    "base nominal" copy happened to land on the right value. It is pinned here
    too so the coincidence is asserted rather than assumed.

The guard: each row's expected magnitude is parsed from THAT id's own
``description`` in the DS item index, never from its base. That makes a future
"base nominal" copy structurally impossible to land silently - the mirror's own
tooltip is the oracle, so copying the base value fails the moment the two
differ. Offline only (``DataSnapshot.load()`` reads the on-disk patch
directory); no live ``:8893``, no network.

Scope note: only the resist MAGNITUDE is corrected. The Arena Force of Nature
mirror is a DIFFERENT passive shape (Absorb / Dissipate, max 10 stacks,
immobilizing effects grant 2 extra, 7s stack duration) rather than the base's
8-stack Steadfast; the stack economics are deliberately NOT modelled, and both
rows keep the shared ``_ITEM_RESIST_STACK_PROB`` at-max-stacks midpoint.
"""
from __future__ import annotations

import re
import unittest

from agents.daemon_slayer._item_resist_grants import (
    _ITEM_RESIST_GRANTS,
    _ITEM_RESIST_STACK_PROB,
    item_resist_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _norm(text: str) -> str:
    """Strip DDragon markup tags and collapse the resulting whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


# item_id -> (registry fields that must equal the parsed magnitude, regex that
# captures that magnitude from the item's OWN DDragon description). Each regex
# is anchored on passive-specific wording so it cannot match the leading flat
# stat block (Force of Nature's "55 Magic Resist" stat line vs its "Gain 70
# Magic Resist" passive), and each is asserted to match EXACTLY once.
_MAGNITUDE_SPECS: dict[str, tuple[tuple[str, ...], str]] = {
    # Voidborn Resilience: percent of BONUS armor + MR at max stacks.
    "6665": (("armor_pct", "mr_pct"), r"by (\d+(?:\.\d+)?)% until end of combat"),
    "226665": (("armor_pct", "mr_pct"), r"by (\d+(?:\.\d+)?)% until end of combat"),
    # Steadfast / Dissipate: FLAT bonus magic resist at max stacks.
    "4401": (("mr",), r"[Gg]ain (\d+(?:\.\d+)?) Magic Resist"),
    "224401": (("mr",), r"[Gg]ain (\d+(?:\.\d+)?) Magic Resist"),
    # Immovable as the Earth: percent of TOTAL armor, always on.
    "443058": (("armor_pct",), r"[Ii]ncrease your armor by (\d+(?:\.\d+)?)%"),
    "663058": (("armor_pct",), r"[Ii]ncrease your armor by (\d+(?:\.\d+)?)%"),
    # Limitless as the Stars: percent of TOTAL magic resist, always on.
    "443059": (("mr_pct",), r"[Ii]ncrease your Magic Resist by (\d+(?:\.\d+)?)%"),
    "663059": (("mr_pct",), r"[Ii]ncrease your Magic Resist by (\d+(?:\.\d+)?)%"),
}

# family -> (base id, mode-mirror id). The mirror is the row historically seeded
# "base nominal".
_BASE_TO_MIRROR: dict[str, tuple[str, str]] = {
    "jaksho": ("6665", "226665"),
    "fon": ("4401", "224401"),
    "molten_stone": ("443058", "663058"),
    "starry_night": ("443059", "663059"),
}


def _ddragon_magnitude(item_id: str) -> float:
    """Return the credited magnitude parsed from ``item_id``'s own tooltip."""
    _fields, pattern = _MAGNITUDE_SPECS[item_id]
    found = re.findall(pattern, _norm(_snap().items[item_id]["description"]))
    if len(found) != 1:
        raise AssertionError(
            "expected exactly one magnitude match for item "
            + item_id
            + ", got "
            + repr(found)
        )
    return float(found[0])


class RegistryMatchesOwnDDragonTextTests(unittest.TestCase):
    """The anti-"base nominal" guard: every row is pinned to its own tooltip."""

    def test_every_spec_id_resolves_in_the_item_index(self) -> None:
        for item_id in _MAGNITUDE_SPECS:
            self.assertIn(item_id, _snap().items, msg=item_id)
            self.assertIn(item_id, _ITEM_RESIST_GRANTS, msg=item_id)

    def test_every_registry_magnitude_matches_its_own_ddragon_text(self) -> None:
        # Reads the expected value from the item index rather than carrying a
        # second copy of the constant, so a mirror seeded from its BASE fails
        # here the moment the two tooltips disagree.
        for item_id, (fields, _pattern) in _MAGNITUDE_SPECS.items():
            expected = _ddragon_magnitude(item_id)
            entry = _ITEM_RESIST_GRANTS[item_id]
            for field in fields:
                self.assertAlmostEqual(
                    getattr(entry, field),
                    expected,
                    places=9,
                    msg=item_id + "." + field,
                )

    def test_untouched_registry_fields_stay_zero(self) -> None:
        # Force of Nature is magic resist ONLY; the prismatic pair is single
        # axis each. A magnitude fix must not smear onto the other axis.
        self.assertEqual(_ITEM_RESIST_GRANTS["224401"].armor, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["224401"].armor_pct, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["224401"].mr_pct, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["226665"].armor, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["226665"].mr, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["663059"].armor_pct, 0.0)
        self.assertEqual(_ITEM_RESIST_GRANTS["663058"].mr_pct, 0.0)


class MirrorIsNotABaseNominalCopyTests(unittest.TestCase):
    """Mirrors whose tooltip differs from their base must not share its value."""

    def test_retuned_mirrors_differ_from_their_base_in_ddragon(self) -> None:
        # Ground truth first: these three families ARE retuned across the mirror
        # boundary. If a patch ever unifies them this test tells us before the
        # magnitude assertions start looking arbitrary.
        for family in ("jaksho", "fon", "starry_night"):
            base_id, mirror_id = _BASE_TO_MIRROR[family]
            self.assertNotEqual(
                _ddragon_magnitude(base_id),
                _ddragon_magnitude(mirror_id),
                msg=family,
            )

    def test_retuned_mirrors_do_not_reuse_the_base_registry_value(self) -> None:
        for family in ("jaksho", "fon", "starry_night"):
            base_id, mirror_id = _BASE_TO_MIRROR[family]
            fields, _pattern = _MAGNITUDE_SPECS[mirror_id]
            for field in fields:
                self.assertNotEqual(
                    getattr(_ITEM_RESIST_GRANTS[mirror_id], field),
                    getattr(_ITEM_RESIST_GRANTS[base_id], field),
                    msg=family + "." + field,
                )

    def test_molten_stone_mirror_legitimately_matches_its_base(self) -> None:
        # The one "base nominal" copy that landed on the right number: both
        # 443058 and 663058 say 20%. Pinned so the coincidence is asserted.
        base_id, mirror_id = _BASE_TO_MIRROR["molten_stone"]
        self.assertAlmostEqual(
            _ddragon_magnitude(base_id), _ddragon_magnitude(mirror_id), places=9
        )
        self.assertAlmostEqual(
            _ITEM_RESIST_GRANTS[mirror_id].armor_pct,
            _ITEM_RESIST_GRANTS[base_id].armor_pct,
            places=9,
        )


class CorrectedMirrorGrantTests(unittest.TestCase):
    """The corrected magnitudes as they reach ``item_resist_grants``."""

    _RESISTS = {
        "total_armor": 100.0,
        "total_mr": 80.0,
        "base_armor": 30.0,
        "base_mr": 32.0,
    }

    def test_jaksho_arena_mirror_credits_forty_percent_of_bonus(self) -> None:
        # 226665 tooltip: 40% (base 6665 is 30%). Percent of BONUS resist.
        armor, mr = item_resist_grants(["226665"], **self._RESISTS)
        bonus_armor = self._RESISTS["total_armor"] - self._RESISTS["base_armor"]
        bonus_mr = self._RESISTS["total_mr"] - self._RESISTS["base_mr"]
        pct = _ddragon_magnitude("226665") / 100.0
        self.assertAlmostEqual(
            armor, bonus_armor * pct * _ITEM_RESIST_STACK_PROB, places=9
        )
        self.assertAlmostEqual(
            mr, bonus_mr * pct * _ITEM_RESIST_STACK_PROB, places=9
        )

    def test_jaksho_arena_mirror_credits_more_than_the_base(self) -> None:
        # Direction check: the Arena mirror trades flat resists (35/35 vs 45/45)
        # for a BIGGER percent, so at equal resolved resists it must credit MORE.
        base = item_resist_grants(["6665"], **self._RESISTS)
        mirror = item_resist_grants(["226665"], **self._RESISTS)
        self.assertGreater(mirror[0], base[0])
        self.assertGreater(mirror[1], base[1])

    def test_fon_arena_mirror_credits_fifty_flat_mr(self) -> None:
        # 224401 Dissipate: 50 flat magic resist (base 4401 Steadfast is 70).
        armor, mr = item_resist_grants(["224401"], **self._RESISTS)
        self.assertAlmostEqual(armor, 0.0, places=9)
        self.assertAlmostEqual(
            mr, _ddragon_magnitude("224401") * _ITEM_RESIST_STACK_PROB, places=9
        )

    def test_fon_arena_mirror_credits_less_than_the_base(self) -> None:
        base = item_resist_grants(["4401"], **self._RESISTS)
        mirror = item_resist_grants(["224401"], **self._RESISTS)
        self.assertLess(mirror[1], base[1])
        self.assertAlmostEqual(mirror[0], base[0], places=9)  # both armor-free

    def test_starry_night_mirror_credits_ten_percent_of_total_mr(self) -> None:
        # 663059 tooltip: 10% (map-30 443059 is 20%). Percent of TOTAL, always on.
        armor, mr = item_resist_grants(["663059"], **self._RESISTS)
        pct = _ddragon_magnitude("663059") / 100.0
        self.assertAlmostEqual(armor, 0.0, places=9)
        self.assertAlmostEqual(mr, self._RESISTS["total_mr"] * pct, places=9)

    def test_starry_night_mirror_credits_half_of_its_map30_base(self) -> None:
        base = item_resist_grants(["443059"], **self._RESISTS)
        mirror = item_resist_grants(["663059"], **self._RESISTS)
        self.assertAlmostEqual(mirror[1], base[1] / 2.0, places=9)

    def test_molten_stone_mirror_still_credits_twenty_percent(self) -> None:
        armor, mr = item_resist_grants(["663058"], **self._RESISTS)
        pct = _ddragon_magnitude("663058") / 100.0
        self.assertAlmostEqual(armor, self._RESISTS["total_armor"] * pct, places=9)
        self.assertAlmostEqual(mr, 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
