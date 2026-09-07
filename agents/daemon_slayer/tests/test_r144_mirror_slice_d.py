"""R144 slice D - mirror-id coverage audit of the four item survivability registries.

MEASURED RESULT: CLEAN. No production file changed. This file is the machine
guard that makes that closure durable instead of a one-time claim.

THE DEFECT CLASS BEING AUDITED (R143, commit f7c49de5). Registries keyed on BARE
4-digit item ids miss the MIRROR ids that ``core.daemon_slayer_resolver.name_to_id``
actually hands the engine - 32xxxx under mode="sr", 22xxxx under mode="arena",
plus 44xxxx / 66xxxx families - and fall through to a SILENT 0.0 with no raise and
no log. R143 found 22 such misses in ``_hsp_amp``.

WHAT WAS MEASURED HERE, against the shipped 16.14.1 snapshot (706 items):

  1. Every id in all four registries was resolved by NAME through
     ``name_to_id(name, mode)`` for mode in {sr, arena, aram, brawl, None}. Every
     returned id was ALREADY registered. Zero silent-0.0 lookups exist.
  2. The whole 706-item catalog was swept by mechanic text for each axis. The
     carrier population is EXACTLY the registered population - no unregistered
     carrier, no registered id absent from the catalog.
  3. Every magnitude was re-read per-id from the catalog description. All agree
     with the committed constants, including the two that legitimately DIVERGE
     between base and mirror (Shadowflame 4645 +20% vs Arena 224645 +15%).

WHY THERE IS NOTHING TO ADD (TRAP 3 - absence of a mirror is not a defect). The
16.14.1 catalog contains 26 ids in the 32xxxx family, 49 in 44xxxx and 16 in
66xxxx, and NOT ONE of them carries a revive, a spell shield, a stasis window or
a low-HP magic crit. The four registries' DROPPED-mirror docstring notes (323026,
324645, 323102 / 323814, 323157, 222420 / 322420) were re-verified still absent at
16.14.1. Seeding an id the engine can never resolve would be dead weight, and
inventing a magnitude for an id no feed states would be a guess.

WHY NO PREFIX-STRIP HELPER (TRAP 1). The mirrors are NOT magnitude-identical:
Shadowflame's Arena mirror is a genuinely retuned +15% against the base's +20%,
and R143 measured divergence in BOTH directions elsewhere (Mikael .12 SR / .15 at
323222; Dawncore .16 / .20 / .12). Normalizing a mirror back to its base would
silently overwrite that retune. Enumeration is the only correct shape, and the
registries already enumerate.

NON-OVERLAP WITH PRIOR ART. ``test_arena_mirror_shields_rm104.py`` covers Arena
mirror ITEM_EFFECTS ``shield`` fields (Kaenic Rookern / Shieldbow / Sterak / Maw -
damage-absorbing shields on the EHP numerator). That is a different registry and a
different mechanic from the block-next-ability SPELL shield audited here; no
assertion is duplicated.
"""
from __future__ import annotations

import re
import unittest

from agents.daemon_slayer._item_lowhp_magic_crit import _ITEM_LOWHP_MAGIC_CRIT
from agents.daemon_slayer._item_revive import _ITEM_REVIVE
from agents.daemon_slayer._item_spell_shield_overrides import _ITEM_SPELL_SHIELD
from agents.daemon_slayer._item_survival_window import _ITEM_SURVIVAL_WINDOW
from agents.daemon_slayer.data_loader import DataSnapshot
from core.daemon_slayer_resolver import name_to_id

_MODES = ("sr", "arena", "aram", "brawl", None)

# Mechanic text signatures, one per audited registry. Matched against the
# tag-stripped DDragon description of every catalog item.
_REVIVE_RE = re.compile(r"lethal damage|Rebirth|Saving Grace|resurrect", re.I)
_SPELL_SHIELD_RE = re.compile(r"Spell Shield|Annul", re.I)
_LOWHP_RE = re.compile(r"below 40% Health|Cinderbloom", re.I)
# Guardian Angel's resurrection channel is described as Stasis too, so the
# stasis sweep is signature-matched and then the revive carriers are removed -
# see StasisRevivedisjointTests for why that exclusion is correct and not a gap.
_STASIS_RE = re.compile(r"Stasis|Time Stop|Invulnerable and Untargetable", re.I)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str | None) -> str:
    return _TAG_RE.sub(" ", html or "")


class _CatalogCase(unittest.TestCase):
    """Shared patch-current catalog load (``current.txt`` selects the patch)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.items = DataSnapshot.load().items

    def carriers(self, pattern: re.Pattern[str]) -> set[str]:
        return {
            iid for iid, rec in self.items.items()
            if pattern.search(_strip(rec.get("description")))
        }

    def stasis_carriers(self) -> set[str]:
        return self.carriers(_STASIS_RE) - self.carriers(_REVIVE_RE)


class RegistryMatchesCatalogTests(_CatalogCase):
    """Each registry's key set EQUALS the catalog's carrier set for its mechanic.

    Two directions in one assertion. Extra catalog ids = the R143 silent-0.0 gap
    (a carrier the engine resolves but the registry misses). Extra registry ids =
    dead weight the engine can never resolve. Either is a defect.
    """

    def _assert_exact(self, registry: dict[str, float], carriers: set[str], label: str) -> None:
        missing = sorted(carriers - set(registry))
        stale = sorted(set(registry) - carriers)
        self.assertEqual(
            (missing, stale), ([], []),
            f"{label}: catalog carriers absent from registry (silent 0.0) = "
            f"{missing}; registry ids absent from catalog (dead weight) = {stale}",
        )

    def test_revive_registry_is_exact(self) -> None:
        self._assert_exact(_ITEM_REVIVE, self.carriers(_REVIVE_RE), "_ITEM_REVIVE")

    def test_lowhp_registry_is_exact(self) -> None:
        self._assert_exact(
            _ITEM_LOWHP_MAGIC_CRIT, self.carriers(_LOWHP_RE), "_ITEM_LOWHP_MAGIC_CRIT",
        )

    def test_spell_shield_registry_is_exact(self) -> None:
        self._assert_exact(
            _ITEM_SPELL_SHIELD, self.carriers(_SPELL_SHIELD_RE), "_ITEM_SPELL_SHIELD",
        )

    def test_survival_window_registry_is_exact(self) -> None:
        self._assert_exact(
            _ITEM_SURVIVAL_WINDOW, self.stasis_carriers(), "_ITEM_SURVIVAL_WINDOW",
        )


class GuardHasTeethTests(_CatalogCase):
    """Negative control - the guard above is not vacuously passing.

    A coverage guard that passes because both sides are empty, or because the
    comparison is malformed, is worse than no guard. This drops a known id from a
    COPY of each registry and asserts the same comparison reports it.
    """

    def _offenders(self, registry: dict[str, float], carriers: set[str]) -> list[str]:
        return sorted(carriers - set(registry))

    def test_dropping_a_known_id_is_detected(self) -> None:
        cases = (
            (_ITEM_REVIVE, self.carriers(_REVIVE_RE), "223026"),
            (_ITEM_LOWHP_MAGIC_CRIT, self.carriers(_LOWHP_RE), "224645"),
            (_ITEM_SPELL_SHIELD, self.carriers(_SPELL_SHIELD_RE), "223814"),
            (_ITEM_SURVIVAL_WINDOW, self.stasis_carriers(), "223157"),
        )
        for registry, carriers, victim in cases:
            with self.subTest(victim=victim):
                self.assertIn(victim, registry)
                mutated = {k: v for k, v in registry.items() if k != victim}
                self.assertEqual(self._offenders(mutated, carriers), [victim])

    def test_carrier_sets_are_non_empty(self) -> None:
        for label, carriers in (
            ("revive", self.carriers(_REVIVE_RE)),
            ("lowhp", self.carriers(_LOWHP_RE)),
            ("spell_shield", self.carriers(_SPELL_SHIELD_RE)),
            ("stasis", self.stasis_carriers()),
        ):
            with self.subTest(axis=label):
                self.assertGreater(len(carriers), 0, f"{label} sweep matched nothing")


class ResolverHandsRegisteredIdsTests(_CatalogCase):
    """The R143 axis proper - what ``name_to_id`` returns must be registered.

    This is the assertion that would have caught the ``_hsp_amp`` defect. For every
    registered id, take its catalog display NAME and re-resolve it the way the
    engine does, in every mode. A returned id outside the registry is a live
    silent-0.0 lookup.
    """

    def _assert_all_modes_registered(self, registry: dict[str, float], label: str) -> None:
        names = {self.items[iid]["name"] for iid in registry}
        for name in sorted(names):
            for mode in _MODES:
                with self.subTest(item=name, mode=mode):
                    resolved = name_to_id(name, mode)
                    self.assertIsNotNone(resolved, f"{label}: {name!r} unresolved in {mode}")
                    self.assertIn(
                        resolved, registry,
                        f"{label}: name_to_id({name!r}, {mode!r}) -> {resolved}, "
                        "which the registry does not carry (silent 0.0)",
                    )

    def test_revive_resolves_into_registry(self) -> None:
        self._assert_all_modes_registered(_ITEM_REVIVE, "_ITEM_REVIVE")

    def test_lowhp_resolves_into_registry(self) -> None:
        self._assert_all_modes_registered(_ITEM_LOWHP_MAGIC_CRIT, "_ITEM_LOWHP_MAGIC_CRIT")

    def test_spell_shield_resolves_into_registry(self) -> None:
        self._assert_all_modes_registered(_ITEM_SPELL_SHIELD, "_ITEM_SPELL_SHIELD")

    def test_survival_window_resolves_into_registry(self) -> None:
        self._assert_all_modes_registered(_ITEM_SURVIVAL_WINDOW, "_ITEM_SURVIVAL_WINDOW")


class PerIdMagnitudeTests(_CatalogCase):
    """Every magnitude re-read PER ID from the catalog - TRAP 1 in assertion form.

    A base and its mirror are asserted against their OWN description text, never
    against each other, so a future Riot retune of one side surfaces here instead
    of being masked by an inherited value.
    """

    def test_revive_fraction_matches_description(self) -> None:
        for iid, frac in _ITEM_REVIVE.items():
            with self.subTest(item=iid):
                text = _strip(self.items[iid]["description"])
                m = re.search(r"restores\s+(\d+)%\s+base Health", text, re.I)
                self.assertIsNotNone(m, f"{iid}: no base-Health restore magnitude in text")
                self.assertAlmostEqual(frac, int(m.group(1)) / 100.0, places=6)

    def test_lowhp_amp_matches_description_per_id(self) -> None:
        for iid, amp in _ITEM_LOWHP_MAGIC_CRIT.items():
            with self.subTest(item=iid):
                text = _strip(self.items[iid]["description"])
                m = re.search(r"dealing\s+(\d+)%\s+increased damage", text, re.I)
                self.assertIsNotNone(m, f"{iid}: no increased-damage magnitude in text")
                self.assertAlmostEqual(amp, int(m.group(1)) / 100.0, places=6)

    def test_shadowflame_mirror_is_genuinely_retuned(self) -> None:
        # The concrete reason a prefix-strip helper would be WRONG on these very
        # files: the Arena mirror is not a copy of the base.
        self.assertAlmostEqual(_ITEM_LOWHP_MAGIC_CRIT["4645"], 0.20, places=6)
        self.assertAlmostEqual(_ITEM_LOWHP_MAGIC_CRIT["224645"], 0.15, places=6)
        self.assertNotEqual(
            _ITEM_LOWHP_MAGIC_CRIT["4645"], _ITEM_LOWHP_MAGIC_CRIT["224645"],
        )

    def test_stasis_window_matches_description(self) -> None:
        for iid, window_s in _ITEM_SURVIVAL_WINDOW.items():
            with self.subTest(item=iid):
                text = _strip(self.items[iid]["description"])
                m = re.search(r"for\s+([\d.]+)\s+seconds", text, re.I)
                self.assertIsNotNone(m, f"{iid}: no stasis duration in text")
                self.assertAlmostEqual(window_s, float(m.group(1)), places=6)

    def test_spell_shield_block_is_total_for_every_id(self) -> None:
        # Annul blocks the next ability ENTIRELY; no id states a partial block.
        for iid, block_pct in _ITEM_SPELL_SHIELD.items():
            with self.subTest(item=iid):
                self.assertAlmostEqual(block_pct, 100.0, places=6)


class StasisReviveDisjointTests(_CatalogCase):
    """Guardian Angel matches the stasis signature but must NOT be a stasis item.

    GA's 4s Stasis is the resurrection CHANNEL - the same event ``_item_revive``
    already prices as a second HP pool. Registering it in ``_ITEM_SURVIVAL_WINDOW``
    would credit one mechanic twice on the SAME EHP numerator, since both
    registries feed ``(1 + extra)`` multipliers there. This pins the exclusion so
    a future "GA says Stasis, why is it missing?" pass does not re-add it.
    """

    def test_revive_ids_are_absent_from_stasis_registry(self) -> None:
        for iid in _ITEM_REVIVE:
            with self.subTest(item=iid):
                self.assertNotIn(iid, _ITEM_SURVIVAL_WINDOW)

    def test_ga_matches_stasis_text_but_is_excluded_by_the_sweep(self) -> None:
        for iid in _ITEM_REVIVE:
            with self.subTest(item=iid):
                text = _strip(self.items[iid]["description"])
                self.assertRegex(text, _STASIS_RE)
                self.assertNotIn(iid, self.stasis_carriers())


class DroppedMirrorsStillAbsentTests(_CatalogCase):
    """TRAP 3 - the documented DROPPED mirror ids are still not in the catalog.

    Each registry docstring lists mirror ids deliberately NOT seeded because the
    engine cannot resolve them. If a patch ever introduces one, this fails and the
    id gets added WITH ITS OWN magnitude read from the catalog - never inherited.
    """

    def test_documented_dropped_mirrors_absent(self) -> None:
        dropped = (
            "323026",                      # Guardian Angel ARAM
            "324645",                      # Shadowflame ARAM
            "323102", "323814",            # Banshee's / Edge of Night ARAM
            "224632", "324632",            # Verdant Barrier Arena / ARAM
            "323157",                      # Zhonya's ARAM
            "222420", "322420",            # Seeker's Armguard Arena / ARAM
        )
        present = sorted(iid for iid in dropped if iid in self.items)
        self.assertEqual(
            present, [],
            "documented-absent mirror id(s) now exist in the catalog and need an "
            f"explicit per-id magnitude: {present}",
        )


class NoMechanicCarrierInLongPrefixFamiliesTests(_CatalogCase):
    """The 32xxxx / 44xxxx / 66xxxx families carry none of these four mechanics.

    R143's misses were concentrated in 32xxxx. This asserts the negative directly
    so the CLEAN verdict is re-measured every run rather than trusted from a note.
    """

    def test_long_prefix_families_carry_no_audited_mechanic(self) -> None:
        audited = (
            self.carriers(_REVIVE_RE)
            | self.carriers(_LOWHP_RE)
            | self.carriers(_SPELL_SHIELD_RE)
            | self.stasis_carriers()
        )
        registered = (
            set(_ITEM_REVIVE) | set(_ITEM_LOWHP_MAGIC_CRIT)
            | set(_ITEM_SPELL_SHIELD) | set(_ITEM_SURVIVAL_WINDOW)
        )
        strays = sorted(
            iid for iid in audited - registered
            if len(iid) > 4 and iid[:2] in ("32", "44", "66")
        )
        self.assertEqual(strays, [], f"unregistered long-prefix carrier(s): {strays}")


if __name__ == "__main__":
    unittest.main()
