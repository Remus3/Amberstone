"""R144 slice B - mirror-id coverage guard for the three item-side DR / resist /
tenacity registries.

THE DEFECT CLASS (R143, generalized). ``core/daemon_slayer_resolver.name_to_id``
hands the engine MIRROR ids, not the bare 4-digit ids the registries are keyed
on: ``32xxxx`` / ``66xxxx`` under mode="sr", ``22xxxx`` / ``44xxxx`` under
mode="arena". A registry that holds only the bare id misses the lookup and falls
through to a SILENT 0.0 - no raise, no log, no fallback. R143 found and fixed
exactly that in ``_hsp_amp``; this file audits the same axis across
``_item_tenacity`` / ``_item_general_dr`` / ``_item_resist_grants``.

MEASURED RESULT OF THE AUDIT: the coverage axis came back essentially CLEAN.
Every mode-mirror the resolver can return for a registered item is ALREADY
registered, with ONE live-reachable exception (Crown of the Shattered Queen's
Arena mirror 444644), which is a DELIBERATE exclusion rather than an oversight -
see ``UnsourcedMirrorTests``. So this file's job is to LOCK the coverage in, not
to record a repair:

  * ``ResolverReachabilityTests`` is the structural guard. It walks every id in
    all three registries, resolves that item's display name back through the
    real ``name_to_id`` for sr / arena / aram, and asserts the id that comes
    back is either registered or on that registry's documented-exclusion
    allowlist. A future patch refresh that introduces a new mirror, or a new
    registry row added without its mirror, fails here instead of silently
    scoring 0.0 in a live game.

  * ``TenacityMirrorMagnitudeTests`` pins each of the 17 tenacity rows to ITS
    OWN ``description`` in ``items.json`` - never to its base. R133 established
    for ``_item_resist_grants`` that a mode mirror is a RETUNED item and that
    three of four "base nominal" copies were wrong; the tenacity registry has
    never carried that guard. Measured here: all 17 rows are correct, and the
    mirrors happen to be magnitude-IDENTICAL to their bases on this axis (unlike
    the resist and HSP registries, where they diverge in both directions). That
    coincidence is asserted rather than assumed, so a future retune cannot land
    silently and cannot be "fixed" by a prefix-strip.

  * ``ResistGrantsMirrorCoverageTests`` is a thin completeness regression over
    what R133 already proved item-by-item - it asserts no row ever loses its
    mirror partner. The magnitudes stay pinned by
    ``test_item_resist_mirror_magnitudes_r133.py``; this does not re-litigate
    them.

WHY NO NORMALIZATION HELPER. The obvious one-line fix for this whole class is to
strip the mirror prefix and look up the base. It is WRONG and is deliberately
not implemented anywhere here. Mirrors are retuned in BOTH directions and the
repo has measured instances: Mikael's 3222 is .12 on SR but .15 at 323222;
Dawncore 6621 is .16 SR / .20 at 326621 / .12 at Arena 226621 (R143); Jak'Sho
226665 is 40% against the base's 30% and Cloak of Starry Night 663059 is 10%
against the base's 20% (R133). Crown 444644 below is the extreme case at 90%
against a 40% base. Enumerate per id, read each magnitude from that id's own
tooltip.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from core.daemon_slayer_resolver import name_to_id

from agents.daemon_slayer._item_general_dr import (
    _GENERAL_DR_UNSOURCED_MIRRORS,
    _ITEM_GENERAL_DR,
    item_general_dr_multiplier,
)
from agents.daemon_slayer._item_resist_grants import (
    _ITEM_RESIST_GRANTS,
    _ITEM_RESIST_UNSOURCED_MIRRORS,
)
from agents.daemon_slayer._item_tenacity import _ITEM_TENACITY, item_tenacity

_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _ROOT / "data" / "daemon_slayer"

# Modes whose resolver index can hand a mirror id to the engine. "brawl" shares
# the SR item pool and returns the same ids as "sr"; it is included so a future
# Brawl-only mirror cannot slip past the guard.
_MODES = ("sr", "aram", "arena", "brawl")

_CATALOG: dict[str, dict] | None = None


def _catalog() -> dict[str, dict]:
    """The patch-current DDragon item catalog the engine actually ships."""
    global _CATALOG
    if _CATALOG is None:
        patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
        payload = json.loads(
            (_DS_DATA / patch / "items.json").read_text(encoding="utf-8")
        )
        _CATALOG = payload["data"]
    return _CATALOG


def _plain(text: str) -> str:
    """Strip DDragon markup tags and collapse the resulting whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _tenacity_from_own_tooltip(item_id: str) -> float:
    """Parse the flat tenacity PERCENT out of THIS id's own description.

    The oracle is deliberately the mirror's own text, never its base - the R133
    lesson. DDragon's structured ``stats`` block carries no tenacity key (see the
    ``_item_tenacity`` module docstring), so the stat line in the description is
    the only machine-readable source.
    """
    found = re.findall(
        r"(\d+(?:\.\d+)?)% Tenacity",
        _plain(_catalog()[item_id].get("description", "")),
    )
    if len(found) != 1:
        raise AssertionError(
            f"item {item_id} has {len(found)} tenacity stat lines, expected 1"
        )
    return float(found[0])


class ResolverReachabilityTests(unittest.TestCase):
    """Every id the live resolver can hand back is registered, or knowingly not.

    This is the guard that would have caught the R143 HSP defect before it
    shipped. It uses the REAL ``name_to_id``, so it exercises the same lookup
    the coach path does rather than a reconstruction of it.
    """

    def _assert_reachable(
        self,
        registry: dict,
        allowlist: frozenset[str],
        label: str,
    ) -> None:
        catalog = _catalog()
        for item_id in sorted(registry, key=lambda i: (len(i), i)):
            name = catalog[item_id]["name"]
            for mode in _MODES:
                resolved = name_to_id(name, mode=mode)
                with self.subTest(registry=label, item=name, mode=mode):
                    self.assertIsNotNone(
                        resolved,
                        f"{label}: {name!r} does not resolve at all under {mode}",
                    )
                    self.assertTrue(
                        resolved in registry or resolved in allowlist,
                        f"{label}: {name!r} resolves to {resolved} under mode="
                        f"{mode}, which is neither registered nor a documented "
                        f"exclusion - that id would score a SILENT 0.0",
                    )

    def test_tenacity_registry_covers_every_resolvable_mirror(self) -> None:
        self._assert_reachable(_ITEM_TENACITY, frozenset(), "tenacity")

    def test_general_dr_registry_covers_every_resolvable_mirror(self) -> None:
        self._assert_reachable(
            _ITEM_GENERAL_DR, _GENERAL_DR_UNSOURCED_MIRRORS, "general_dr"
        )

    def test_resist_grants_registry_covers_every_resolvable_mirror(self) -> None:
        self._assert_reachable(
            _ITEM_RESIST_GRANTS, _ITEM_RESIST_UNSOURCED_MIRRORS, "resist_grants"
        )

    def test_every_registered_id_exists_in_the_catalog(self) -> None:
        catalog = _catalog()
        for label, registry in (
            ("tenacity", _ITEM_TENACITY),
            ("general_dr", _ITEM_GENERAL_DR),
            ("resist_grants", _ITEM_RESIST_GRANTS),
        ):
            for item_id in registry:
                with self.subTest(registry=label, id=item_id):
                    self.assertIn(item_id, catalog)


class TenacityMirrorMagnitudeTests(unittest.TestCase):
    """Each of the 17 rows pinned to its OWN tooltip (the R133 oracle shape)."""

    def test_every_row_matches_its_own_description(self) -> None:
        for item_id, registered in sorted(
            _ITEM_TENACITY.items(), key=lambda kv: (len(kv[0]), kv[0])
        ):
            with self.subTest(id=item_id, name=_catalog()[item_id]["name"]):
                self.assertAlmostEqual(
                    registered, _tenacity_from_own_tooltip(item_id), places=6
                )
                self.assertAlmostEqual(
                    item_tenacity(item_id), registered, places=6
                )

    def test_mirror_pairs_are_magnitude_identical_on_this_axis(self) -> None:
        """Measured coincidence, asserted so a future retune cannot hide.

        Unlike the resist (R133) and HSP (R143) registries, no tenacity mirror
        currently diverges from its base. The pairs are enumerated rather than
        derived so that a divergence shows up as a FAILURE demanding a per-id
        magnitude, not as a silently-inherited value.
        """
        pairs = (
            ("2517", "222517"),
            ("2525", "222525"),
            ("3053", "223053"),
            ("3091", "223091"),
            ("3111", "223111"),
            ("223172", "663172"),
        )
        for base, mirror in pairs:
            with self.subTest(base=base, mirror=mirror):
                self.assertAlmostEqual(
                    _tenacity_from_own_tooltip(base),
                    _tenacity_from_own_tooltip(mirror),
                    places=6,
                )
                self.assertAlmostEqual(
                    item_tenacity(base), item_tenacity(mirror), places=6
                )

    def test_zephyr_prefix_strip_would_hit_a_DIFFERENT_item(self) -> None:
        """The hardest available evidence against a normalization helper.

        Zephyr ships ONLY as mirrors - 223172 (map 30) and 663172 (map 11) - and
        there is no bare "Zephyr" row. But a bare 3172 DOES exist and it is
        ``Gunmetal Greaves``, an unrelated boot with NO tenacity at all. So a
        prefix-strip fallback (663172 -> 3172) would not merely inherit a stale
        magnitude the way R133 and R143 warned about; it would silently resolve
        to a DIFFERENT ITEM. The mirror prefix is not a namespace over a shared
        base id, and this row proves it.
        """
        catalog = _catalog()
        self.assertEqual(catalog["223172"]["name"], "Zephyr")
        self.assertEqual(catalog["663172"]["name"], "Zephyr")
        self.assertEqual(catalog["3172"]["name"], "Gunmetal Greaves")
        self.assertNotIn(
            "Tenacity", _plain(catalog["3172"].get("description", ""))
        )
        self.assertNotIn("3172", _ITEM_TENACITY)
        self.assertIn("223172", _ITEM_TENACITY)
        self.assertIn("663172", _ITEM_TENACITY)

    def test_unregistered_ids_contribute_zero(self) -> None:
        self.assertAlmostEqual(item_tenacity("9999999"), 0.0, places=6)


class UnsourcedMirrorTests(unittest.TestCase):
    """Crown of the Shattered Queen's Arena mirror stays OUT, verifiably.

    444644 is the one live-reachable id in these three registries that the
    resolver can hand back without a registry hit. It is excluded because its
    magnitude is UNRESOLVABLE headless, and this test re-derives that conflict
    from the shipped feeds rather than trusting the prose note - so if a future
    patch refresh makes the two feeds agree, this test FAILS and the exclusion
    gets revisited on evidence.
    """

    def test_ddragon_and_meraki_still_disagree_on_444644(self) -> None:
        ddragon = _plain(_catalog()["444644"].get("description", ""))
        match = re.search(r"incoming champion damage by (\d+)%", ddragon)
        self.assertIsNotNone(match, "DDragon 444644 lost its Safeguard stat line")
        assert match is not None  # narrow for the type checker
        ddragon_pct = int(match.group(1))

        patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
        meraki = json.loads(
            (_DS_DATA / patch / "items_meraki.json").read_text(encoding="utf-8")
        )["items"]
        passives = " ".join(
            _plain(p.get("effects") or "") for p in (meraki["444644"]["passives"] or [])
        )
        m2 = re.search(r"incoming champion damage by (\d+)%", passives)
        self.assertIsNotNone(m2, "Meraki 444644 lost its Safeguard passive")
        assert m2 is not None  # narrow for the type checker
        meraki_pct = int(m2.group(1))

        self.assertEqual(ddragon_pct, 90)
        self.assertEqual(meraki_pct, 50)
        self.assertNotEqual(
            ddragon_pct,
            meraki_pct,
            "the feeds now AGREE on Crown's Arena magnitude - the R144 exclusion"
            " reason is gone, so seed 444644 with the agreed value",
        )

    def test_excluded_mirrors_score_the_identity_multiplier(self) -> None:
        for item_id in sorted(_GENERAL_DR_UNSOURCED_MIRRORS):
            for is_melee in (True, False):
                with self.subTest(id=item_id, melee=is_melee):
                    self.assertAlmostEqual(
                        item_general_dr_multiplier(
                            [item_id], is_melee, assume_item_general_dr=True
                        ),
                        1.0,
                        places=6,
                    )

    def test_the_sr_crown_row_still_scores(self) -> None:
        """The exclusion is scoped to the mirrors - the registered row works."""
        self.assertLess(
            item_general_dr_multiplier(
                ["664644"], True, assume_item_general_dr=True
            ),
            1.0,
        )

    def test_never_equippable_mirrors_are_flagged_not_registered(self) -> None:
        """4644 / 224644 carry a real 40% but no live map flag on any mode."""
        for item_id in ("4644", "224644"):
            with self.subTest(id=item_id):
                maps = _catalog()[item_id].get("maps") or {}
                self.assertFalse(
                    any(maps.values()),
                    f"{item_id} gained a live map flag - re-evaluate the exclusion",
                )
                self.assertIn(item_id, _GENERAL_DR_UNSOURCED_MIRRORS)
                self.assertNotIn(item_id, _ITEM_GENERAL_DR)

    def test_default_off_seam_is_still_byte_identical(self) -> None:
        """Nothing in R144 arms the seam - OFF stays the identity everywhere."""
        for item_id in sorted(set(_ITEM_GENERAL_DR) | _GENERAL_DR_UNSOURCED_MIRRORS):
            with self.subTest(id=item_id):
                self.assertAlmostEqual(
                    item_general_dr_multiplier([item_id], True), 1.0, places=6
                )


class ResistGrantsMirrorCoverageTests(unittest.TestCase):
    """R133 proved the magnitudes; this only guards that no pair loses a half."""

    def test_every_family_keeps_both_of_its_ids(self) -> None:
        # "terminus" is deliberately a ONE-id family: the Arena mirror 223302 has
        # no on-disk Light magnitude in any feed, so doctrine B (R161) forbids a
        # row for it. It lives in _ITEM_RESIST_UNSOURCED_MIRRORS instead.
        families: dict[str, set[str]] = {}
        for item_id, entry in _ITEM_RESIST_GRANTS.items():
            families.setdefault(entry.family, set()).add(item_id)
        self.assertEqual(
            {family: sorted(ids) for family, ids in sorted(families.items())},
            {
                "fon": ["224401", "4401"],
                "jaksho": ["226665", "6665"],
                "molten_stone": ["443058", "663058"],
                "starry_night": ["443059", "663059"],
                "terminus": ["3302"],
            },
        )

    def test_no_registered_id_shares_a_name_with_an_unregistered_sibling(self) -> None:
        catalog = _catalog()
        registered_names = {
            catalog[item_id]["name"] for item_id in _ITEM_RESIST_GRANTS
        }
        for item_id, record in catalog.items():
            if record.get("name") not in registered_names:
                continue
            if not any((record.get("maps") or {}).values()):
                continue  # never equippable - correctly absent
            if item_id in _ITEM_RESIST_UNSOURCED_MIRRORS:
                continue  # documented exclusion, not a silent 0.0
            with self.subTest(id=item_id, name=record.get("name")):
                self.assertIn(item_id, _ITEM_RESIST_GRANTS)


if __name__ == "__main__":
    unittest.main()
