"""R144 slice C - mirror-id coverage guard for the three item-passive registries.

``core/daemon_slayer_resolver.name_to_id`` hands the engine MIRROR ids, not the
bare 4-digit catalog id: ``22xxxx`` under mode="arena", and ``32xxxx`` /
``44xxxx`` / ``66xxxx`` families exist in the index for other item lines. A
registry keyed only on bare ids misses those lookups and falls through to a
SILENT 0.0 - no raise, no log, no fallback (the R135 zero-stat fallthrough
class, swept for the enchanter HSP registry in R143 / f7c49de5).

This file is the standing guard for the three lanes in slice C:

  * ``_item_mana_health._ITEM_MANA_HEALTH_PCT``      (Awe mana -> bonus max HP)
  * ``_item_omnivamp._ITEM_OMNIVAMP``                (Riftmaker Void Corruption)
  * ``_item_proc_heal._ITEM_PROC_HEAL_BONUS_HP_SCALING`` (Anguish self-heal)

MEASURED RESULT AT 16.14.1: all three registries were already COMPLETE - every
id ``name_to_id`` can emit was present before this file existed, so these tests
passed on their first run. That is the CLEAN outcome, not an untested one: the
assertions are catalog-driven, so they fail the moment a patch bump introduces
a new mirror, retires an old one, or a future edit drops a row. Absence of a
mirror is asserted as a POSITIVE fact (Riftmaker and Unending Despair have no
``32xxxx`` twin) rather than left implicit, so "the ARAM mirror is missing"
cannot be silently re-filed as a defect later.

The magnitudes below are enumerated PER ID, deliberately not derived by
stripping a mirror prefix back to its base. Mirrors are genuinely retuned items
and diverge in both directions elsewhere in the engine (R143 measured Mikael
3222 at .12 SR but .15 at 323222; Dawncore 6621 at .16 SR / .20 at 326621 /
.12 at Arena 226621; R133 caught four "base nominal" resist copies of which
three were wrong). These three lanes happen to be uniform across their mirrors,
which is asserted here as a measured coincidence rather than assumed by
construction.

Offline only - reads the on-disk patch directory via ``DataSnapshot.load()``.
No live ``:8860``, no network.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._item_mana_health import (
    _ITEM_MANA_HEALTH_PCT,
    item_mana_health_hp,
)
from agents.daemon_slayer._item_omnivamp import _ITEM_OMNIVAMP, item_omnivamp_fraction
from agents.daemon_slayer._item_proc_heal import (
    _ITEM_PROC_HEAL_BONUS_HP_SCALING,
    item_proc_heal_hp,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from core.daemon_slayer_resolver import name_to_id

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _catalog_ids_named(display_name: str) -> set[str]:
    """Every id in the DS item index carrying ``display_name``.

    This is the oracle for the registry key set: the resolver can only ever
    hand back an id that exists in this index under the item's display name,
    so a registry covering exactly this set cannot fall through to 0.0.
    """
    return {
        iid
        for iid, rec in _snap().items.items()
        if rec.get("name") == display_name
    }


# The modes ``name_to_id`` accepts, plus the ``None`` legacy-index path.
_MODES: tuple[str | None, ...] = ("sr", "aram", "arena", "brawl", None)

# lane label -> (registry, display names it must cover)
_LANES: tuple[tuple[str, dict, tuple[str, ...]], ...] = (
    (
        "mana_health",
        _ITEM_MANA_HEALTH_PCT,
        ("Winter's Approach", "Fimbulwinter"),
    ),
    ("omnivamp", _ITEM_OMNIVAMP, ("Riftmaker",)),
    ("proc_heal", _ITEM_PROC_HEAL_BONUS_HP_SCALING, ("Unending Despair",)),
)

# Ids measured ABSENT from the 16.14.1 index. Their absence is the reason the
# corresponding registry row does not exist; asserting it keeps a later pass
# from "fixing" a gap that the catalog does not have. Compare R143's Forbidden
# Idol 3114, which correctly gained no mirror.
_MEASURED_ABSENT: tuple[tuple[str, str], ...] = (
    ("324633", "Riftmaker has no ARAM mirror; base 4633 is the ARAM item"),
    ("322502", "Unending Despair has no ARAM mirror; base 2502 is the ARAM item"),
    ("124633", "no 12xxxx Riftmaker line exists in the index"),
    ("443119", "no 44xxxx Winter's Approach line exists in the index"),
    ("663119", "no 66xxxx Winter's Approach line exists in the index"),
)


class ResolverEmittedIdCoverageTests(unittest.TestCase):
    """Every id ``name_to_id`` can hand the engine must be a registry key."""

    def test_every_resolved_id_is_registered(self) -> None:
        for lane, registry, names in _LANES:
            for name in names:
                for mode in _MODES:
                    resolved = name_to_id(name, mode)
                    with self.subTest(lane=lane, item=name, mode=mode):
                        self.assertIsNotNone(
                            resolved,
                            msg=f"{name} unresolvable under mode={mode!r}",
                        )
                        self.assertIn(
                            resolved,
                            registry,
                            msg=(
                                f"{lane}: name_to_id({name!r}, {mode!r}) -> "
                                f"{resolved!r} is absent from the registry and "
                                "would score a silent 0.0"
                            ),
                        )

    def test_arena_resolves_to_a_22_mirror(self) -> None:
        """Pins the defect's shape - Arena really does emit a mirror id."""
        for lane, _registry, names in _LANES:
            for name in names:
                with self.subTest(lane=lane, item=name):
                    self.assertTrue(
                        str(name_to_id(name, "arena")).startswith("22"),
                        msg=f"{name}: expected a 22xxxx Arena mirror",
                    )


class RegistryMatchesCatalogTests(unittest.TestCase):
    """Registry key set == the catalog id set for the covered display names."""

    def test_no_catalog_id_is_unregistered(self) -> None:
        for lane, registry, names in _LANES:
            expected: set[str] = set()
            for name in names:
                expected |= _catalog_ids_named(name)
            with self.subTest(lane=lane):
                self.assertTrue(expected, msg=f"{lane}: catalog lookup found nothing")
                self.assertEqual(
                    expected - set(registry),
                    set(),
                    msg=f"{lane}: catalog ids missing from the registry",
                )

    def test_no_registered_id_is_absent_from_the_catalog(self) -> None:
        for lane, registry, names in _LANES:
            expected: set[str] = set()
            for name in names:
                expected |= _catalog_ids_named(name)
            with self.subTest(lane=lane):
                self.assertEqual(
                    set(registry) - expected,
                    set(),
                    msg=f"{lane}: registry rows the catalog does not carry",
                )

    def test_measured_absent_ids_stay_absent(self) -> None:
        registered: set[str] = set()
        for _lane, registry, _names in _LANES:
            registered |= set(registry)
        for iid, reason in _MEASURED_ABSENT:
            with self.subTest(item_id=iid):
                self.assertNotIn(iid, _snap().items, msg=f"{iid}: {reason}")
                self.assertNotIn(iid, registered, msg=f"{iid}: {reason}")


class PerIdMagnitudeTests(unittest.TestCase):
    """Each id's credited magnitude, enumerated - never prefix-derived."""

    # Awe grants bonus health equal to 15% BONUS mana on every id in the
    # family (Meraki 3119 / 3121 "Grants bonus health equal to 15% bonus
    # mana."; the mirrors carry the same passive name and the DDragon copies
    # strip the numeral, so the base nominal is carried).
    MANA_HEALTH_TRUTH = {
        "3119": 0.15,
        "3121": 0.15,
        "223119": 0.15,
        "223121": 0.15,
        "323119": 0.15,
        "323121": 0.15,
    }

    # Void Corruption at maximum stacks: 10% melee / 6% ranged omnivamp.
    OMNIVAMP_TRUTH = {
        "4633": (0.10, 0.06),
        "224633": (0.10, 0.06),
    }

    # Anguish: 250% of 3% bonus health, PRE-mitigation -> 0.075.
    PROC_HEAL_TRUTH = {
        "2502": 0.075,
        "222502": 0.075,
    }

    def test_mana_health_per_id(self) -> None:
        self.assertEqual(_ITEM_MANA_HEALTH_PCT, self.MANA_HEALTH_TRUTH)
        for iid, pct in self.MANA_HEALTH_TRUTH.items():
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    item_mana_health_hp([iid], 1000.0), pct * 1000.0, places=6
                )

    def test_omnivamp_per_id(self) -> None:
        self.assertEqual(_ITEM_OMNIVAMP, self.OMNIVAMP_TRUTH)
        for iid, (melee, ranged) in self.OMNIVAMP_TRUTH.items():
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    item_omnivamp_fraction([iid], False), melee, places=6
                )
                self.assertAlmostEqual(
                    item_omnivamp_fraction([iid], True), ranged, places=6
                )

    def test_proc_heal_per_id(self) -> None:
        self.assertEqual(
            _ITEM_PROC_HEAL_BONUS_HP_SCALING, self.PROC_HEAL_TRUTH
        )
        for iid, coeff in self.PROC_HEAL_TRUTH.items():
            with self.subTest(item_id=iid):
                # target_mr=0 isolates the registry coefficient from the
                # module's assumed-MR mitigation step.
                self.assertAlmostEqual(
                    item_proc_heal_hp(
                        [iid],
                        1000.0,
                        assume_item_proc_heal=True,
                        target_mr=0.0,
                    ),
                    coeff * 1000.0,
                    places=6,
                )

    def test_unregistered_id_scores_zero(self) -> None:
        """The silent-0.0 fallthrough itself - pinned as the defect's signature."""
        self.assertEqual(item_mana_health_hp(["999999"], 1000.0), 0.0)
        self.assertEqual(item_omnivamp_fraction(["999999"], False), 0.0)
        self.assertEqual(
            item_proc_heal_hp(
                ["999999"], 1000.0, assume_item_proc_heal=True, target_mr=0.0
            ),
            0.0,
        )


class DefaultOffPostureTests(unittest.TestCase):
    """The mirror rows must not disturb the DEFAULT-OFF gating of each lane."""

    def test_proc_heal_flag_still_gates_mirrors(self) -> None:
        for iid in _ITEM_PROC_HEAL_BONUS_HP_SCALING:
            with self.subTest(item_id=iid):
                self.assertEqual(item_proc_heal_hp([iid], 1000.0), 0.0)

    def test_mana_health_zero_bonus_mana_is_inert(self) -> None:
        for iid in _ITEM_MANA_HEALTH_PCT:
            with self.subTest(item_id=iid):
                self.assertEqual(item_mana_health_hp([iid], 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
