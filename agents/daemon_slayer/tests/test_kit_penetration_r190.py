"""R190 slice A - CHAMPION-KIT-intrinsic PHYSICAL penetration, the axis the
damage math has never seen.

WHAT WAS MISSING. ``effects.effective_target_armor`` implements League's
four-stage resist pipeline (flat reduction -> percent reduction -> percent
penetration -> flat penetration) correctly, but it reads its magnitudes from
``ItemEffect`` objects and from NOTHING else. Penetration has no generic stat
path either: ``stats.ITEM_STAT_KEY_MAP`` carries no penetration key, DDragon's
structured ``stats`` block has no penetration entry, and the vendored Meraki
catalog has zero keys matching "enetration" or "ethality" across all 320 items,
so ``ITEM_EFFECTS`` is the SOLE item-side credit path. A champion whose OWN KIT
grants percent armor penetration - Darius E's 40 percent, Ambessa R's 30,
Pantheon R's 30 - has that penetration credited NOWHERE in the damage math. The
only place it appears at all is ``antitank._ANTITANK_REGISTRY``, a standalone
0..1 reliability heuristic on an opt-in scorer, which is not the damage
pipeline and never feeds it.

WHAT THIS SLICE SHIPS. ``_kit_penetration.py``: a hand-authored registry keyed
by champion, derived row-for-row from the shipped ``champion_abilities.json``,
plus a DEFAULT-OFF ``apply_kit_penetration`` seam that folds the creditable
rows into ``effective_target_armor`` through two new keyword arguments
(``kit_pen_pct`` / ``kit_pen_flat``) that both default to 0.0. Every existing
call site passes neither, so every existing result is byte-identical.

THREE KINDS, ONLY ONE OF WHICH IS CREDITABLE:

* ``PERCENT_ARMOR`` - percent of the target's TOTAL armor. This is exactly the
  quantity ``effective_target_armor`` models, so these rows fold straight into
  the percent-penetration stage, MULTIPLICATIVELY, alongside Lord Dominik's and
  Serylda's. Darius's own wiki notes say so verbatim: "The armor penetration
  stacks multiplicatively with other forms of percentage armor penetration."
* ``PERCENT_BONUS_ARMOR`` - percent of the target's BONUS armor only. The
  engine's target model carries a single scalar armor with NO base/bonus split,
  so there is no defensible way to credit these without inventing the split.
  They are registered with their verbatim magnitude and are deliberately NOT
  creditable - a documented FUTURE, not a silent omission. K'Sante's notes add
  a second independent reason: his row "stacks additively with other sources of
  percentage armor penetration", which is not the composition rule this seam
  implements.
* ``FLAT_LETHALITY`` - Aphelios only, and it is a PLAYER CHOICE rather than an
  automatic grant ("Aphelios may spend his skill points to gain bonus attack
  damage, bonus attack speed or lethality instead"), so it is registered
  conditional and pays nothing unless a caller explicitly opts in.

MAGIC PENETRATION IS OUT OF SCOPE HERE by construction. The structured sweep
below shows Annie R and Mordekaiser E carry ``Magic Penetration`` blocks; this
registry holds no magic rows and the population guard asserts the magic ids are
EXCLUDED, so a future magic row cannot leak in through this lane.

RANK CONVENTION: every rank-scaled row credits its MAX-RANK magnitude, the same
convention the DS build scorers use when they evaluate a completed build.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._kit_penetration import (
    CREDITABLE_KINDS,
    KIT_PENETRATION_REGISTRY,
    KitPenEntry,
    apply_kit_penetration,
    kit_penetration_rows,
    resolve_kit_penetration,
)
from agents.daemon_slayer.effects import effective_target_armor

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


def _abilities() -> dict:
    patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    raw = (_PATCH_ROOT / patch / "champion_abilities.json").read_text(
        encoding="utf-8"
    )
    return json.loads(raw)["data"]


# ---------------------------------------------------------------------------
# Re-derivation helpers. Every guard below re-runs these against the SHIPPED
# ability data on every test run, so a future champion authored the same way
# fails here instead of silently reading 0.0 penetration forever.
# ---------------------------------------------------------------------------

_PROSE_PATTERNS = {
    # "the damage dealt ignores 40% of the target's armor" - TOTAL armor.
    "IGNORE_TOTAL": re.compile(
        r"ignores?\s+(\d+(?:\.\d+)?)%\s+of the target's\s+armor", re.I
    ),
    # "ignores 60% of the target's bonus armor" - BONUS armor only.
    "IGNORE_BONUS": re.compile(
        r"ignores?\s+(\d+(?:\.\d+)?)%\s+of the target's\s+bonus armor", re.I
    ),
    # "he gains ... 50% bonus-armor penetration" - BONUS armor only.
    "BONUS_ARMOR_PEN": re.compile(
        r"(\d+(?:\.\d+)?)%\s+bonus-armor penetration", re.I
    ),
    # "0% : 33% (based on critical strike chance) armor penetration" - TOTAL.
    "CRIT_SCALED": re.compile(
        r"(\d+(?:\.\d+)?)%\s+\(based on critical strike chance\)"
        r"\s+armor penetration",
        re.I,
    ),
}


def _sweep_structured() -> dict:
    """(champion, slot) -> (attribute, max stated value, units).

    Sweeps every ``damage_blocks`` entry whose attribute names a penetration
    or lethality quantity. This is the machine-readable half of the ability
    feed and is where Ambessa / Darius / Pantheon / Aphelios state their
    magnitudes.
    """
    found = {}
    for champ, slots in _abilities().items():
        for slot, forms in slots.items():
            for form in forms:
                for block in form.get("damage_blocks") or []:
                    attribute = block.get("attribute") or ""
                    low = attribute.lower()
                    if "penetration" not in low and "lethality" not in low:
                        continue
                    values, units = [], set()
                    for mod in block.get("raw_modifiers") or []:
                        values.extend(float(v) for v in mod.get("values") or [])
                        units.update(mod.get("units") or [])
                    if values:
                        found[(champ, slot)] = (
                            attribute, max(values), tuple(sorted(units))
                        )
    return found


def _sweep_prose() -> dict:
    """(champion, slot) -> (pattern name, stated percent)."""
    found = {}
    for champ, slots in _abilities().items():
        for slot, forms in slots.items():
            for form in forms:
                for text in form.get("effects_descriptions") or []:
                    for name, pattern in _PROSE_PATTERNS.items():
                        match = pattern.search(text)
                        if match:
                            found[(champ, slot)] = (name, float(match.group(1)))
    return found


class R190RegistryShapeTests(unittest.TestCase):
    """The registry is well-formed and every row is typed."""

    def test_registry_is_champion_keyed_tuples_of_entries(self) -> None:
        self.assertIsInstance(KIT_PENETRATION_REGISTRY, dict)
        self.assertTrue(KIT_PENETRATION_REGISTRY)
        for champion, rows in KIT_PENETRATION_REGISTRY.items():
            self.assertIsInstance(champion, str)
            self.assertIsInstance(rows, tuple)
            self.assertTrue(rows, champion)
            for row in rows:
                self.assertIsInstance(row, KitPenEntry)
                self.assertEqual(row.champion, champion)

    def test_every_row_carries_a_verbatim_tooltip_and_a_known_kind(self) -> None:
        kinds = {"PERCENT_ARMOR", "PERCENT_BONUS_ARMOR", "FLAT_LETHALITY"}
        for rows in KIT_PENETRATION_REGISTRY.values():
            for row in rows:
                self.assertIn(row.kind, kinds, row)
                self.assertGreater(len(row.tooltip), 20, row)
                self.assertGreater(row.magnitude, 0.0, row)
                self.assertIn(row.slot, ("P", "Q", "W", "E", "R"), row)

    def test_percent_rows_are_fractions_and_flat_rows_are_not(self) -> None:
        for rows in KIT_PENETRATION_REGISTRY.values():
            for row in rows:
                if row.kind.startswith("PERCENT"):
                    self.assertLessEqual(row.magnitude, 1.0, row)
                else:
                    self.assertGreater(row.magnitude, 1.0, row)

    def test_only_total_armor_percent_rows_are_creditable(self) -> None:
        self.assertEqual(CREDITABLE_KINDS, ("PERCENT_ARMOR",))

    def test_registry_holds_no_magic_penetration_row(self) -> None:
        # Slice B owns the magic axis. Annie R / Mordekaiser E state magic pen
        # in the same structured feed; neither may appear here.
        self.assertNotIn("Annie", KIT_PENETRATION_REGISTRY)
        self.assertNotIn("Mordekaiser", KIT_PENETRATION_REGISTRY)

    def test_kit_penetration_rows_is_a_safe_lookup(self) -> None:
        self.assertEqual(kit_penetration_rows("Teemo"), ())
        self.assertEqual(kit_penetration_rows(None), ())
        self.assertEqual(
            kit_penetration_rows("Darius"), KIT_PENETRATION_REGISTRY["Darius"]
        )


class R190RegistryMagnitudeTests(unittest.TestCase):
    """Every row's magnitude, asserted against its cited tooltip figure."""

    def _row(self, champion: str, slot: str) -> KitPenEntry:
        for row in kit_penetration_rows(champion):
            if row.slot == slot:
                return row
        self.fail(f"no {champion} {slot} row")

    def test_ambessa_r_percent_armor_pen_max_rank_30(self) -> None:
        # "Passive: Ambessa gains armor penetration." + the structured
        # Armor Penetration block [10, 20, 30] percent.
        row = self._row("Ambessa", "R")
        self.assertEqual(row.kind, "PERCENT_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.30, places=6)
        self.assertFalse(row.conditional)

    def test_darius_e_percent_armor_pen_max_rank_40(self) -> None:
        # "Passive: Darius gains armor penetration." + [20, 25, 30, 35, 40]%.
        row = self._row("Darius", "E")
        self.assertEqual(row.kind, "PERCENT_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.40, places=6)
        self.assertFalse(row.conditional)

    def test_pantheon_r_percent_armor_pen_max_rank_30(self) -> None:
        # "Passive: Pantheon gains armor penetration." + [10, 20, 30]%.
        row = self._row("Pantheon", "R")
        self.assertEqual(row.kind, "PERCENT_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.30, places=6)
        self.assertFalse(row.conditional)

    def test_gangplank_e_percent_armor_pen_40_conditional(self) -> None:
        # "the damage dealt ignores 40% of the target's armor" - keg chain only.
        row = self._row("Gangplank", "E")
        self.assertEqual(row.kind, "PERCENT_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.40, places=6)
        self.assertTrue(row.conditional)

    def test_nilah_q_percent_armor_pen_is_crit_scaled_to_33(self) -> None:
        # "Nilah gains 0% : 33% (based on critical strike chance) armor
        # penetration" - the magnitude is the 100%-crit endpoint.
        row = self._row("Nilah", "Q")
        self.assertEqual(row.kind, "PERCENT_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.33, places=6)
        self.assertTrue(row.crit_scaled)

    def test_yasuo_r_is_bonus_armor_only_and_uncreditable(self) -> None:
        # "the damage dealt by Yasuo's critical strikes ignores 60% of the
        # target's bonus armor" - bonus armor, which the engine does not model.
        row = self._row("Yasuo", "R")
        self.assertEqual(row.kind, "PERCENT_BONUS_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.60, places=6)
        self.assertNotIn(row.kind, CREDITABLE_KINDS)

    def test_ksante_r_is_bonus_armor_only_and_uncreditable(self) -> None:
        # "he gains bonus attack speed, 50% bonus-armor penetration, and 20%
        # omnivamp" - plus the notes' "stacks additively" caveat.
        row = self._row("KSante", "R")
        self.assertEqual(row.kind, "PERCENT_BONUS_ARMOR")
        self.assertAlmostEqual(row.magnitude, 0.50, places=6)
        self.assertNotIn(row.kind, CREDITABLE_KINDS)

    def test_aphelios_p_lethality_is_flat_and_opt_in(self) -> None:
        # "Aphelios may spend his skill points to gain bonus attack damage,
        # bonus attack speed or lethality instead" - [5.5 .. 33], max rank 33.
        row = self._row("Aphelios", "P")
        self.assertEqual(row.kind, "FLAT_LETHALITY")
        self.assertAlmostEqual(row.magnitude, 33.0, places=6)
        self.assertTrue(row.conditional)


class R190CatalogDriftGuardTests(unittest.TestCase):
    """Re-derives the swept set from the SHIPPED ability data on every run."""

    def test_structured_pen_population_is_pinned(self) -> None:
        swept = _sweep_structured()
        self.assertEqual(
            sorted(swept),
            sorted(
                [
                    ("Ambessa", "R"),
                    ("Annie", "R"),
                    ("Aphelios", "P"),
                    ("Darius", "E"),
                    ("Mordekaiser", "E"),
                    ("Pantheon", "R"),
                ]
            ),
        )

    def test_prose_pen_population_is_pinned(self) -> None:
        self.assertEqual(
            sorted(_sweep_prose()),
            sorted(
                [
                    ("Gangplank", "E"),
                    ("KSante", "R"),
                    ("Nilah", "Q"),
                    ("Yasuo", "R"),
                ]
            ),
        )

    def test_every_physical_structured_row_is_registered_at_parity(self) -> None:
        """A new champion authored with an Armor Penetration block fails here."""
        for (champ, slot), (attribute, stated, units) in sorted(
            _sweep_structured().items()
        ):
            if "magic" in attribute.lower():
                continue  # slice B owns the magic axis
            rows = [r for r in kit_penetration_rows(champ) if r.slot == slot]
            self.assertEqual(len(rows), 1, (champ, slot, attribute))
            row = rows[0]
            expected = stated / 100.0 if "%" in units else stated
            self.assertAlmostEqual(row.magnitude, expected, places=6,
                                   msg=(champ, slot, attribute, stated))

    def test_every_prose_row_is_registered_at_parity(self) -> None:
        """A new champion authored with the same prose fails here."""
        expected_kind = {
            "IGNORE_TOTAL": "PERCENT_ARMOR",
            "CRIT_SCALED": "PERCENT_ARMOR",
            "IGNORE_BONUS": "PERCENT_BONUS_ARMOR",
            "BONUS_ARMOR_PEN": "PERCENT_BONUS_ARMOR",
        }
        for (champ, slot), (name, stated) in sorted(_sweep_prose().items()):
            rows = [r for r in kit_penetration_rows(champ) if r.slot == slot]
            self.assertEqual(len(rows), 1, (champ, slot, name))
            self.assertEqual(rows[0].kind, expected_kind[name], (champ, slot))
            self.assertAlmostEqual(rows[0].magnitude, stated / 100.0, places=6,
                                   msg=(champ, slot, name, stated))

    def test_registry_holds_no_row_the_ability_data_does_not_state(self) -> None:
        """No hand-invented row: every (champion, slot) is derivable."""
        derived = set(_sweep_prose()) | {
            key for key, (attribute, _v, _u) in _sweep_structured().items()
            if "magic" not in attribute.lower()
        }
        registered = {
            (champion, row.slot)
            for champion, rows in KIT_PENETRATION_REGISTRY.items()
            for row in rows
        }
        self.assertEqual(registered, derived)


class R190DefaultOffInvarianceTests(unittest.TestCase):
    """No kit argument -> byte-identical to the pre-R190 pipeline."""

    _SPREAD = (0.0, 1.0, 15.0, 30.0, 55.5, 100.0, 250.0, -50.0, -1.0)

    def _sample_effects(self):
        # Lord Dominik's Regards (percent pen), Black Cleaver (percent
        # reduction), Serylda's (percent pen + lethality). Any id absent from
        # the shipped catalog is skipped rather than asserted, so the
        # invariance sweep never depends on a specific item surviving a patch.
        return [ITEM_EFFECTS[iid] for iid in ("3036", "3071", "6694")
                if iid in ITEM_EFFECTS]

    def test_zero_kit_args_match_the_no_arg_call_exactly(self) -> None:
        effects = self._sample_effects()
        self.assertTrue(effects, "expected at least one pen/reduction item")
        for armor in self._SPREAD:
            for level in (None, 1, 11, 18):
                for eff in ([], effects, effects[:1]):
                    baseline = effective_target_armor(armor, eff, level)
                    self.assertEqual(
                        baseline,
                        effective_target_armor(
                            armor, eff, level, kit_pen_pct=0.0, kit_pen_flat=0.0
                        ),
                        (armor, level, len(eff)),
                    )

    def test_seam_disabled_is_the_plain_pipeline(self) -> None:
        effects = self._sample_effects()
        for champion in (None, "Darius", "Teemo", "Ambessa"):
            for armor in self._SPREAD:
                self.assertEqual(
                    effective_target_armor(armor, effects, 18),
                    apply_kit_penetration(
                        armor, effects, 18, champion=champion
                    ),
                    (champion, armor),
                )

    def test_unregistered_champion_is_inert_even_when_enabled(self) -> None:
        effects = self._sample_effects()
        for armor in self._SPREAD:
            self.assertEqual(
                effective_target_armor(armor, effects, 18),
                apply_kit_penetration(
                    armor, effects, 18, champion="Teemo", enabled=True
                ),
                armor,
            )


class R190CompositionTests(unittest.TestCase):
    """Kit percent pen composes MULTIPLICATIVELY, never additively."""

    def test_kit_pct_composes_multiplicatively_with_item_pct(self) -> None:
        # 35 percent item pen and 40 percent Darius pen keep 0.65 * 0.60 of
        # the armor, i.e. 61 percent effective pen - NOT the additive 75.
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(ldr.armor_pen_pct, 0.35, places=6)
        got = effective_target_armor(100.0, [ldr], None, kit_pen_pct=0.40)
        self.assertAlmostEqual(got, 100.0 * 0.65 * 0.60, places=6)
        self.assertNotAlmostEqual(got, 100.0 * 0.25, places=3)

    def test_kit_pct_alone_matches_the_single_factor(self) -> None:
        for pct in (0.30, 0.33, 0.40):
            self.assertAlmostEqual(
                effective_target_armor(200.0, [], None, kit_pen_pct=pct),
                200.0 * (1.0 - pct),
                places=6,
            )

    def test_two_kit_rows_compose_multiplicatively_in_the_resolver(self) -> None:
        # The resolver itself must compose, not sum: 0.30 and 0.40 give
        # 1 - 0.70*0.60 = 0.58, not 0.70.
        composed = resolve_kit_penetration(
            "Darius", extra_pct=(0.30,)
        )
        self.assertAlmostEqual(composed.pct, 1.0 - 0.70 * 0.60, places=6)

    def test_kit_pen_still_floors_at_zero(self) -> None:
        self.assertEqual(
            effective_target_armor(10.0, [], None, kit_pen_pct=0.40,
                                   kit_pen_flat=999.0),
            0.0,
        )
        self.assertGreaterEqual(
            effective_target_armor(5.0, [], None, kit_pen_pct=0.99), 0.0
        )

    def test_kit_pen_is_a_no_op_on_negative_armor(self) -> None:
        # Penetration never heals or amplifies an already-negative resist.
        self.assertEqual(
            effective_target_armor(-40.0, [], None, kit_pen_pct=0.40), -40.0
        )

    def test_kit_flat_folds_into_the_flat_pen_stage(self) -> None:
        self.assertAlmostEqual(
            effective_target_armor(100.0, [], None, kit_pen_flat=33.0),
            67.0,
            places=6,
        )


class R190ResolverTests(unittest.TestCase):
    """The DEFAULT-OFF resolver credits only what it is allowed to."""

    def test_unconditional_rows_only_by_default(self) -> None:
        self.assertAlmostEqual(
            resolve_kit_penetration("Darius").pct, 0.40, places=6
        )
        # Gangplank's row is conditional (keg chain), so it pays nothing.
        self.assertAlmostEqual(
            resolve_kit_penetration("Gangplank").pct, 0.0, places=6
        )
        self.assertAlmostEqual(
            resolve_kit_penetration(
                "Gangplank", include_conditional=True
            ).pct,
            0.40,
            places=6,
        )

    def test_bonus_armor_rows_never_pay_out(self) -> None:
        for champion in ("Yasuo", "KSante", "Sylas"):
            for flag in (False, True):
                got = resolve_kit_penetration(
                    champion, include_conditional=flag
                )
                self.assertAlmostEqual(got.pct, 0.0, places=6, msg=champion)
                self.assertAlmostEqual(got.flat, 0.0, places=6, msg=champion)

    def test_nilah_scales_with_crit_chance(self) -> None:
        self.assertAlmostEqual(
            resolve_kit_penetration("Nilah").pct, 0.0, places=6
        )
        self.assertAlmostEqual(
            resolve_kit_penetration("Nilah", crit_chance=0.5).pct,
            0.165,
            places=6,
        )
        self.assertAlmostEqual(
            resolve_kit_penetration("Nilah", crit_chance=1.0).pct,
            0.33,
            places=6,
        )
        # Over-cap crit chance clamps rather than over-penetrating.
        self.assertAlmostEqual(
            resolve_kit_penetration("Nilah", crit_chance=2.5).pct,
            0.33,
            places=6,
        )

    def test_aphelios_lethality_is_opt_in_only(self) -> None:
        self.assertAlmostEqual(
            resolve_kit_penetration("Aphelios").flat, 0.0, places=6
        )
        self.assertAlmostEqual(
            resolve_kit_penetration(
                "Aphelios", include_conditional=True
            ).flat,
            33.0,
            places=6,
        )

    def test_unknown_champion_resolves_to_zero(self) -> None:
        for champion in (None, "", "Teemo", "NotAChampion"):
            got = resolve_kit_penetration(champion)
            self.assertEqual((got.pct, got.flat), (0.0, 0.0), champion)

    def test_enabled_seam_penetrates_more_than_the_baseline(self) -> None:
        ldr = ITEM_EFFECTS["3036"]
        baseline = effective_target_armor(120.0, [ldr], 18)
        got = apply_kit_penetration(
            120.0, [ldr], 18, champion="Darius", enabled=True
        )
        self.assertLess(got, baseline)
        self.assertAlmostEqual(got, 120.0 * 0.65 * 0.60, places=6)


if __name__ == "__main__":
    unittest.main()
