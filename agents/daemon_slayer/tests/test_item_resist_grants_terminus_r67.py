"""R67 tail - Terminus "Juxtaposition" LIGHT-side caster resists (item-keyed).

The Dark half of the Juxtaposition clause has been credited since R67 / R161
(``_effects_data`` 3302 ``armor_pen_pct=0.30`` / ``magic_pen_pct=0.30``, Arena
223302 at 0.24). The LIGHT half - the caster-side bonus armor + bonus MR - was
filed as FUTURE with the blocker "no item-keyed resist-grant path exists
(_passive_resist_overrides.py is champion-keyed only)". That blocker is STALE:
``_item_resist_grants`` IS that item-keyed lane (landed 2026-07-11, R106, ENGINE
1.199.0) and its ``apply_item_resist_grants`` seam is already threaded through
``compute_ehp``. This slice credits the SR Light half there.

FEED (Meraki ``data/daemon_slayer/16.14.1/items_meraki.json`` items.3302 passives
"Juxtaposition", verbatim): "''Light'' hits grant {{pp|6 to 8 for 3|1;11;14|type=
level}} {{as|'''bonus''' armor}} and {{as|'''bonus''' magic resistance}} while
''Dark'' hits grant 10% ... for a total of {{pp|6*3 to 8*3 for 3|1;11;14}}
'''bonus''' resistances and 30% resistances penetration at maximum stacks of
each." -> per-stack 6 / 7 / 8 at level breakpoints 1 / 11 / 14, cap 3 stacks, so
the at-max-stacks total is 18 / 21 / 24 bonus armor AND bonus MR.

DOCTRINE B (R161): a mode mirror credits ITS OWN feed, never the SR twin's. The
Arena mirror 223302's only on-disk text (``items.json`` DDragon 16.14.1) is
"<keywordMajor>Light</keywordMajor> Attacks grant <scaleArmor>Armor</scaleArmor>
and <scaleMR>Magic Resist</scaleMR> for 5s." - NO magnitude, and
``items_meraki.json`` carries ZERO ``*3302`` mirror rows. There is therefore no
Arena Light magnitude ON DISK in any feed. Deriving one from the Dark 8%-vs-10%
pen ratio would be inheritance by arithmetic, which is exactly what doctrine B
forbids, so 223302 is deliberately ABSENT from ``_ITEM_RESIST_GRANTS`` and is
enumerated machine-readably in ``_ITEM_RESIST_UNSOURCED_MIRRORS`` (the
``_item_general_dr._GENERAL_DR_UNSOURCED_MIRRORS`` precedent) so the R144
coverage guard can tell a knowing exclusion from the silent-0.0 defect class.

SIBLING SUFFIX SWEEP: only ``3302`` (maps 11 / 12 / 21 / 35) and ``223302``
(map 30) exist in the item index. Map 21 is Nexus Blitz and is not wired, so the
ONE SR row covers SR + ARAM + Brawl.

DEFAULT-OFF: ``apply_item_resist_grants`` still defaults False, so every EHP
field is byte-identical with the seam off - asserted here per level breakpoint.
"""
from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._item_resist_grants import (
    _ITEM_RESIST_GRANTS,
    _ITEM_RESIST_UNSOURCED_MIRRORS,
    ItemResistEntry,
    item_resist_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _ROOT / "data" / "daemon_slayer"

# The at-max-stacks (3) Light total per the Meraki level breakpoints 1 / 11 / 14.
_EXPECTED_BY_LEVEL: tuple[tuple[int, float], ...] = (
    (1, 18.0), (2, 18.0), (5, 18.0), (10, 18.0),
    (11, 21.0), (12, 21.0), (13, 21.0),
    (14, 24.0), (15, 24.0), (17, 24.0), (18, 24.0),
)

_RESISTS = {
    "total_armor": 100.0,
    "total_mr": 80.0,
    "base_armor": 30.0,
    "base_mr": 32.0,
}

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _meraki_items() -> dict:
    payload = json.loads(
        (_DS_DATA / _patch() / "items_meraki.json").read_text(encoding="utf-8")
    )
    return payload.get("items", payload)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


class MerakiFeedTruthTests(unittest.TestCase):
    """The SR magnitude is READ from the feed, not carried as a bare constant."""

    def test_juxtaposition_light_states_six_to_eight_per_stack(self) -> None:
        passives = _meraki_items()["3302"]["passives"]
        juxta = next(
            (p for p in passives if p.get("name") == "Juxtaposition"), None
        )
        self.assertIsNotNone(juxta, "Meraki 3302 has no 'Juxtaposition' passive")
        effects = juxta["effects"]
        # Per-stack Light grant with its level breakpoints.
        self.assertIn("6 to 8 for 3|1;11;14", effects)
        self.assertIn("type=level", effects)
        # And the tooltip's OWN at-max-stacks total, which is what we credit.
        self.assertIn("6*3 to 8*3 for 3|1;11;14", effects)
        self.assertIn("bonus", effects)

    def test_feed_breakpoints_lerp_to_the_registered_totals(self) -> None:
        # 6 / 7 / 8 per stack at levels 1 / 11 / 14, times the cap of 3.
        per_stack = {1: 6.0, 11: 7.0, 14: 8.0}
        for level, per in per_stack.items():
            expected = per * 3.0
            armor, mr = item_resist_grants(
                ["3302"], level=level, **_RESISTS
            )
            self.assertAlmostEqual(armor, expected, places=9, msg=str(level))
            self.assertAlmostEqual(mr, expected, places=9, msg=str(level))


class RegistryShapeTests(unittest.TestCase):
    def test_sr_row_is_registered(self) -> None:
        self.assertIn("3302", _ITEM_RESIST_GRANTS)

    def test_row_is_level_scaled_with_an_explicit_eighteen_tuple(self) -> None:
        entry = _ITEM_RESIST_GRANTS["3302"]
        self.assertTrue(entry.level_scaled)
        for field in ("armor", "mr"):
            val = getattr(entry, field)
            self.assertIsInstance(val, tuple, msg=field)
            self.assertEqual(len(val), 18, msg=field)
            self.assertEqual(
                val,
                (18.0,) * 10 + (21.0,) * 3 + (24.0,) * 5,
                msg=field,
            )

    def test_row_carries_no_percent_half(self) -> None:
        entry = _ITEM_RESIST_GRANTS["3302"]
        self.assertEqual(entry.armor_pct, 0.0)
        self.assertEqual(entry.mr_pct, 0.0)

    def test_family_tag_is_terminus(self) -> None:
        self.assertEqual(_ITEM_RESIST_GRANTS["3302"].family, "terminus")

    def test_conditional_probability_is_full_matching_the_dark_half(self) -> None:
        # See the row's inline note: the Dark half of the SAME tooltip clause is
        # credited at the FULL 3-stack steady state unamortized
        # (_effects_data.py:633-634 armor_pen_pct=0.30 == 10%/stack x 3), so the
        # Light half of the same accrual gets prob 1.0 rather than the registry
        # ramping default of 0.5 (_item_resist_grants.py:123).
        self.assertAlmostEqual(
            _ITEM_RESIST_GRANTS["3302"].conditional_probability, 1.0, places=9
        )


class LevelBreakpointCreditTests(unittest.TestCase):
    """18 at L1-10, 21 at L11-13, 24 at L14-18 - every breakpoint asserted."""

    def test_every_level_credits_its_breakpoint_total(self) -> None:
        for level, expected in _EXPECTED_BY_LEVEL:
            armor, mr = item_resist_grants(["3302"], level=level, **_RESISTS)
            with self.subTest(level=level):
                self.assertAlmostEqual(armor, expected, places=9)
                self.assertAlmostEqual(mr, expected, places=9)

    def test_all_eighteen_levels_are_covered_monotonically(self) -> None:
        prev = 0.0
        for level in range(1, 19):
            armor, mr = item_resist_grants(["3302"], level=level, **_RESISTS)
            with self.subTest(level=level):
                self.assertAlmostEqual(armor, mr, places=9)
                self.assertGreaterEqual(armor, prev)
            prev = armor
        self.assertAlmostEqual(prev, 24.0, places=9)

    def test_level_is_clamped_outside_one_to_eighteen(self) -> None:
        low, _ = item_resist_grants(["3302"], level=-5, **_RESISTS)
        high, _ = item_resist_grants(["3302"], level=99, **_RESISTS)
        self.assertAlmostEqual(low, 18.0, places=9)
        self.assertAlmostEqual(high, 24.0, places=9)

    def test_default_level_is_one(self) -> None:
        armor, mr = item_resist_grants(["3302"], **_RESISTS)
        self.assertAlmostEqual(armor, 18.0, places=9)
        self.assertAlmostEqual(mr, 18.0, places=9)

    def test_terminus_sums_with_a_different_family(self) -> None:
        # Juxtaposition and Steadfast are DIFFERENT unique passives -> sum.
        t = item_resist_grants(["3302"], level=14, **_RESISTS)
        f = item_resist_grants(["4401"], level=14, **_RESISTS)
        both = item_resist_grants(["3302", "4401"], level=14, **_RESISTS)
        self.assertAlmostEqual(both[0], t[0] + f[0], places=9)
        self.assertAlmostEqual(both[1], t[1] + f[1], places=9)

    def test_pre_existing_rows_are_level_invariant(self) -> None:
        # The new ``level`` kwarg must not perturb the flat / percent rows.
        for iid in ("6665", "226665", "4401", "224401", "443058", "443059"):
            baseline = item_resist_grants([iid], **_RESISTS)
            for level in (1, 11, 14, 18):
                with self.subTest(id=iid, level=level):
                    self.assertEqual(
                        item_resist_grants([iid], level=level, **_RESISTS),
                        baseline,
                    )


class ArenaMirrorIsDoctrineBAbsentTests(unittest.TestCase):
    """223302 must NOT be registered: no on-disk feed carries its Light value.

    Doctrine B (R161) forbids inheriting a mirror magnitude from its SR twin. The
    Arena tooltip names the Light grant but states NO number, and Meraki has no
    ``*3302`` mirror row at all, so the only way to produce a value would be to
    scale the SR 18/21/24 by the Dark pen ratio (8/10) - inheritance by
    arithmetic. The id is instead enumerated as a documented exclusion.
    """

    def test_arena_mirror_absent_from_the_registry(self) -> None:
        self.assertNotIn("223302", _ITEM_RESIST_GRANTS)

    def test_arena_mirror_is_a_documented_exclusion(self) -> None:
        self.assertIn("223302", _ITEM_RESIST_UNSOURCED_MIRRORS)

    def test_arena_mirror_scores_the_identity_zero(self) -> None:
        for level in (1, 11, 14, 18):
            with self.subTest(level=level):
                self.assertEqual(
                    item_resist_grants(["223302"], level=level, **_RESISTS),
                    (0.0, 0.0),
                )

    def test_arena_tooltip_states_no_light_magnitude(self) -> None:
        desc = _plain(_snap().items["223302"]["description"])
        self.assertIn("Light", desc)
        # The Light clause runs from "Light Attacks grant" to the Dark clause. Its
        # ONLY number is the 5s buff DURATION - no resist magnitude, unlike the
        # sibling Dark clause which states "8%".
        light = re.search(r"Light Attacks grant(.*?)(?:Dark Attacks|$)", desc)
        self.assertIsNotNone(light, desc)
        clause = light.group(1)
        self.assertNotIn("%", clause)
        stripped = re.sub(r"\d+(?:\.\d+)?s\b", "", clause)  # drop "5s"
        self.assertFalse(
            re.search(r"\d", stripped),
            "Arena 223302 Light clause unexpectedly carries a magnitude: "
            + repr(clause),
        )
        # And the Dark clause DOES carry one, so the check above is discriminating.
        dark = re.search(r"Dark Attacks grant(.*)$", desc)
        self.assertIsNotNone(dark, desc)
        self.assertIn("8%", dark.group(1))

    def test_meraki_has_no_terminus_mirror_row_at_all(self) -> None:
        items = _meraki_items()
        self.assertIn("3302", items)
        self.assertEqual(
            [k for k in items if k.endswith("3302")], ["3302"]
        )

    def test_only_two_terminus_ids_exist_in_the_item_index(self) -> None:
        ids = sorted(k for k in _snap().items if k.endswith("3302"))
        self.assertEqual(ids, ["223302", "3302"])
        # Map coverage: the SR row serves SR (11) + ARAM (12) + Brawl (35);
        # map 21 (Nexus Blitz) is not wired. 223302 is Arena-only (30).
        sr_maps = {m for m, on in (_snap().items["3302"].get("maps") or {}).items() if on}
        self.assertEqual(sr_maps, {"11", "12", "21", "35"})
        arena_maps = {
            m for m, on in (_snap().items["223302"].get("maps") or {}).items() if on
        }
        self.assertEqual(arena_maps, {"30"})


class ComputeEhpSeamTests(unittest.TestCase):
    """The credit reaches eff_armor / eff_mr and lifts both EHP axes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _pair(self, level: int):
        kwargs = dict(
            champion_id="Aatrox",
            level=level,
            item_ids=["3302"],
            mode="SR",
        )
        off = compute_ehp(self.snap, **kwargs)
        on = compute_ehp(self.snap, apply_item_resist_grants=True, **kwargs)
        return off, on

    def test_off_is_byte_identical_at_every_breakpoint(self) -> None:
        for level in (1, 10, 11, 13, 14, 18):
            off, _on = self._pair(level)
            with self.subTest(level=level):
                self.assertEqual(off.item_resist_armor, 0.0)
                self.assertEqual(off.item_resist_mr, 0.0)
                # And the whole payload matches a no-Terminus reference run's
                # shape: OFF must equal a second OFF call exactly.
                again = compute_ehp(
                    self.snap,
                    champion_id="Aatrox",
                    level=level,
                    item_ids=["3302"],
                    mode="SR",
                )
                self.assertEqual(off.to_dict(), again.to_dict())

    def test_on_credits_the_breakpoint_total_to_the_denominator(self) -> None:
        for level, expected in ((1, 18.0), (10, 18.0), (11, 21.0),
                                (13, 21.0), (14, 24.0), (18, 24.0)):
            _off, on = self._pair(level)
            with self.subTest(level=level):
                self.assertAlmostEqual(on.item_resist_armor, expected, places=9)
                self.assertAlmostEqual(on.item_resist_mr, expected, places=9)

    def test_credit_lands_on_the_eff_armor_eff_mr_denominator(self) -> None:
        """Positional proof: the credit is indistinguishable from ext_armor/ext_mr.

        ``eff_armor`` / ``eff_mr`` are locals in ``compute_ehp``
        (``ehp.py:1927-1928``: ``eff_armor = armor + bonus_armor + ext_armor +
        item_resist_armor + rune_resist_armor``), not surfaced fields. The
        equivalent observable assertion is that arming the seam produces the SAME
        EHP as feeding the identical magnitude through ``external_resist_armor`` /
        ``external_resist_mr`` - the sibling denominator term on that very line. A
        numerator (HP-side) credit could not satisfy this.
        """
        for level, expected in ((1, 18.0), (11, 21.0), (14, 24.0)):
            on = compute_ehp(
                self.snap, champion_id="Aatrox", level=level,
                item_ids=["3302"], mode="SR",
                apply_item_resist_grants=True,
            )
            via_denominator = compute_ehp(
                self.snap, champion_id="Aatrox", level=level,
                item_ids=["3302"], mode="SR",
                external_resist_armor=expected, external_resist_mr=expected,
            )
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    on.physical_ehp, via_denominator.physical_ehp, places=6
                )
                self.assertAlmostEqual(
                    on.magical_ehp, via_denominator.magical_ehp, places=6
                )
                # True EHP has no resist denominator, so it must NOT move.
                off = compute_ehp(
                    self.snap, champion_id="Aatrox", level=level,
                    item_ids=["3302"], mode="SR",
                )
                self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=6)

    def test_on_raises_physical_and_magical_ehp(self) -> None:
        for level in (1, 11, 14):
            off, on = self._pair(level)
            with self.subTest(level=level):
                self.assertGreater(on.physical_ehp, off.physical_ehp)
                self.assertGreater(on.magical_ehp, off.magical_ehp)

    def test_arena_mirror_on_is_still_byte_identical(self) -> None:
        # Doctrine B: the Arena Light half is uncredited, so arming the seam on
        # an Arena Terminus build changes nothing.
        kwargs = dict(
            champion_id="Aatrox", level=14, item_ids=["223302"], mode="ARENA"
        )
        off = compute_ehp(self.snap, **kwargs)
        on = compute_ehp(self.snap, apply_item_resist_grants=True, **kwargs)
        self.assertEqual(off.item_resist_armor, on.item_resist_armor)
        self.assertEqual(off.item_resist_mr, on.item_resist_mr)
        self.assertEqual(off.to_dict(), on.to_dict())


class MutationChecksTests(unittest.TestCase):
    """The pins are not vacuous: perturbing the tuple must break real asserts."""

    def _swap(self, armor, mr):
        entry = _ITEM_RESIST_GRANTS["3302"]
        return dataclasses.replace(entry, armor=armor, mr=mr)

    def test_perturbed_tuple_changes_the_credited_totals(self) -> None:
        original = _ITEM_RESIST_GRANTS["3302"]
        # Flip the L14+ tail from 24 to 23 - the L14 pin MUST notice.
        bad = (18.0,) * 10 + (21.0,) * 3 + (23.0,) * 5
        _ITEM_RESIST_GRANTS["3302"] = self._swap(bad, bad)
        try:
            armor, mr = item_resist_grants(["3302"], level=14, **_RESISTS)
            self.assertNotAlmostEqual(armor, 24.0, places=9)
            self.assertNotAlmostEqual(mr, 24.0, places=9)
            self.assertAlmostEqual(armor, 23.0, places=9)
        finally:
            _ITEM_RESIST_GRANTS["3302"] = original
        # Restored.
        armor, mr = item_resist_grants(["3302"], level=14, **_RESISTS)
        self.assertAlmostEqual(armor, 24.0, places=9)
        self.assertAlmostEqual(mr, 24.0, places=9)

    def test_dropping_level_scaled_breaks_the_breakpoints(self) -> None:
        # Without level_scaled the resolver falls back to the tuple's FIRST
        # element, so L14 would silently read 18 instead of 24.
        original = _ITEM_RESIST_GRANTS["3302"]
        _ITEM_RESIST_GRANTS["3302"] = dataclasses.replace(
            original, level_scaled=False
        )
        try:
            armor, _mr = item_resist_grants(["3302"], level=14, **_RESISTS)
            self.assertAlmostEqual(armor, 18.0, places=9)
            self.assertNotAlmostEqual(armor, 24.0, places=9)
        finally:
            _ITEM_RESIST_GRANTS["3302"] = original

    def test_removing_the_row_zeroes_the_credit(self) -> None:
        original = _ITEM_RESIST_GRANTS.pop("3302")
        try:
            self.assertEqual(
                item_resist_grants(["3302"], level=14, **_RESISTS), (0.0, 0.0)
            )
        finally:
            _ITEM_RESIST_GRANTS["3302"] = original

    def test_halving_the_probability_halves_the_credit(self) -> None:
        original = _ITEM_RESIST_GRANTS["3302"]
        _ITEM_RESIST_GRANTS["3302"] = dataclasses.replace(
            original, conditional_probability=0.5
        )
        try:
            armor, mr = item_resist_grants(["3302"], level=14, **_RESISTS)
            self.assertAlmostEqual(armor, 12.0, places=9)
            self.assertAlmostEqual(mr, 12.0, places=9)
        finally:
            _ITEM_RESIST_GRANTS["3302"] = original

    def test_entry_type_is_the_shared_dataclass(self) -> None:
        self.assertIsInstance(_ITEM_RESIST_GRANTS["3302"], ItemResistEntry)


if __name__ == "__main__":
    unittest.main()
