"""R196 - the three kit-penetration tails from R190 (LEDGER 1040).

Three slices, one module:

  SLICE 2 (the schema lift the other two consume) - ``AntiTankEntry`` gains an
  ``axis`` field: ``"PHYSICAL"`` / ``"MAGICAL"`` / ``"BOTH"``, appended at the END
  of the dataclass with a ``"BOTH"`` default (the CLAUDE.md dataclass convention -
  a mid-class required field breaks every positional construction). ``SHRED`` and
  ``PERCENT_PEN`` are axis-agnostic kinds, so before R196 an armor-side row was
  indistinguishable from a magic-side one and the R190 magic guard had to carry an
  exemption dict for K'Sante R. The field is METADATA ONLY: it is read by no
  scoring path and is not serialized onto ``AntiTankSourceEntry.to_dict()``, so
  every ``compute_antitank`` output is byte-identical to the pre-R196 engine.

  SLICE 1 - Annie R is credited. Her ult states a STRUCTURED "Magic Penetration"
  block (15 / 17.5 / 20, units "%") and she was absent from the registry entirely,
  reading 0.0 on the anti-tank axis. Now ``PERCENT_PEN`` / ``MAGICAL`` /
  ``SUSTAINED`` / magnitude 0.7.

  SLICE 3 - Amumu P is REMOVED. It was registered ``SHRED`` 0.6, but the 16.14.1
  passive is "Cursed targets receive 10% bonus true damage from all incoming
  pre-mitigation magic damage" - a damage-vulnerability debuff that lowers NO
  resist. ``SHRED`` means "lowers the target's resists", so the row was factually
  wrong. No other Amumu slot belongs on the axis (Q / E / R are flat magic damage,
  W is a flat "Magic Damage Per Tick" toggle, E's only resist prose is his OWN
  physical damage reduction), so Amumu drops OFF the selective registry entirely
  and scores 0.0 - the correct answer for a selective axis, not a regression.

Every claim below is re-derived from the shipped
``data/daemon_slayer/<patch>/champion_abilities.json`` on every run, so a patch
that re-authors one of these tooltips goes RED instead of silently drifting.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import fields, replace
from pathlib import Path

from agents.daemon_slayer.antitank import (
    _ANTITANK_AXES,
    _ANTITANK_REGISTRY,
    AntiTankEntry,
    _mechanism_value,
    compute_antitank,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Kinds whose meaning is "this row lowers the target's resists". Only these
# rows carry a load-bearing axis; every other kind keeps the "BOTH" default.
_RESIST_LOWERING_KINDS = frozenset({"SHRED", "PERCENT_PEN"})


def _current_patch() -> str:
    return (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _abilities() -> dict:
    path = _PATCH_ROOT / _current_patch() / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _slot_prose(champion: str, slot: str) -> str:
    forms = (_abilities().get(champion) or {}).get(slot) or []
    return " | ".join(
        line
        for form in forms
        for line in (form.get("effects_descriptions") or [])
    )


def _resist_lowering_rows() -> tuple[tuple[str, AntiTankEntry], ...]:
    return tuple(
        (champion, row)
        for champion, rows in _ANTITANK_REGISTRY.items()
        for row in rows
        if row.kind in _RESIST_LOWERING_KINDS
    )


# --------------------------------------------------------------------------
# SLICE 2 - the axis schema lift
# --------------------------------------------------------------------------

class R196AxisSchemaTests(unittest.TestCase):
    """The field exists, defaults safely, and is appended at the END."""

    def test_axis_is_the_last_dataclass_field(self) -> None:
        # CLAUDE.md Python Conventions: a new dataclass field is APPENDED with
        # a default so no existing positional construction shifts.
        self.assertEqual(fields(AntiTankEntry)[-1].name, "axis")

    def test_axis_defaults_to_both(self) -> None:
        entry = AntiTankEntry("Q", "MAX_HP", "SUSTAINED", magnitude=0.5)
        self.assertEqual(entry.axis, "BOTH")

    def test_allowed_axis_values_are_exactly_three(self) -> None:
        self.assertEqual(_ANTITANK_AXES, frozenset({"PHYSICAL", "MAGICAL", "BOTH"}))

    def test_every_row_declares_a_legal_axis(self) -> None:
        for champion, rows in sorted(_ANTITANK_REGISTRY.items()):
            for row in rows:
                with self.subTest(champion=champion, source=row.source):
                    self.assertIn(row.axis, _ANTITANK_AXES)

    def test_every_resist_lowering_row_declares_an_axis(self) -> None:
        # The guard the R190 magic catalog now leans on: a SHRED /
        # PERCENT_PEN row without a legal axis makes that guard unsound.
        rows = _resist_lowering_rows()
        self.assertGreater(len(rows), 0)
        for champion, row in rows:
            with self.subTest(champion=champion, source=row.source):
                self.assertIn(row.axis, _ANTITANK_AXES)


class R196AxisIsMetadataOnlyTests(unittest.TestCase):
    """Nothing computed may read the axis - proven, not asserted by comment."""

    def test_mechanism_value_ignores_the_axis(self) -> None:
        base = AntiTankEntry("E", "PERCENT_PEN", "SUSTAINED", magnitude=0.7)
        expected = _mechanism_value(base)
        for axis in sorted(_ANTITANK_AXES):
            with self.subTest(axis=axis):
                self.assertEqual(_mechanism_value(replace(base, axis=axis)), expected)

    def test_every_shipped_row_scores_the_same_on_every_axis(self) -> None:
        # Stronger than the synthetic row above: flip the axis on each real
        # registry row (with and without injected stats / level) and assert
        # the mechanism value never moves.
        for champion, rows in sorted(_ANTITANK_REGISTRY.items()):
            for row in rows:
                for axis in sorted(_ANTITANK_AXES):
                    flipped = replace(row, axis=axis)
                    with self.subTest(champion=champion, source=row.source, axis=axis):
                        self.assertEqual(_mechanism_value(flipped), _mechanism_value(row))
                        self.assertEqual(
                            _mechanism_value(flipped, {"ap": 300.0, "ad": 120.0}, 9),
                            _mechanism_value(row, {"ap": 300.0, "ad": 120.0}, 9),
                        )

    def test_axis_is_not_serialized_onto_the_result(self) -> None:
        # The route payload is unchanged by the schema lift.
        payload = compute_antitank("Mordekaiser").to_dict()
        self.assertNotIn("axis", payload)
        for source in payload["sources"]:
            self.assertNotIn("axis", source)


class R196AxisAssignmentTests(unittest.TestCase):
    """Each shipped axis is re-derived from the 16.14.1 tooltip prose."""

    # (champion, slot) -> the expected axis, each backed by the verbatim
    # 16.14.1 mechanic. A row that lowers BOTH resists is BOTH; a
    # damage-vulnerability debuff takes the axis of the damage it amplifies.
    _EXPECTED = {
        ("Brand", "W"): "MAGICAL",
        ("Briar", "Q"): "BOTH",
        ("Corki", "E"): "BOTH",
        ("Darius", "E"): "PHYSICAL",
        ("Evelynn", "W"): "MAGICAL",
        ("Gangplank", "E"): "PHYSICAL",
        ("Garen", "E"): "PHYSICAL",
        ("JarvanIV", "Q"): "PHYSICAL",
        ("Jayce", "R"): "BOTH",
        ("KSante", "R"): "PHYSICAL",
        ("Karthus", "W"): "MAGICAL",
        ("Kayle", "Q"): "BOTH",
        ("KogMaw", "Q"): "BOTH",
        ("MonkeyKing", "Q"): "PHYSICAL",
        ("Mordekaiser", "E"): "MAGICAL",
        ("Mordekaiser", "R"): "BOTH",
        ("Nasus", "E"): "PHYSICAL",
        ("Nilah", "Q"): "PHYSICAL",
        ("Olaf", "Q"): "PHYSICAL",
        ("Rell", "P"): "BOTH",
        ("Renekton", "E"): "PHYSICAL",
        ("Rengar", "R"): "PHYSICAL",
        ("Rumble", "E"): "MAGICAL",
        ("Sion", "E"): "PHYSICAL",
        ("Trundle", "R"): "BOTH",
        ("Vi", "W"): "PHYSICAL",
        ("Vladimir", "R"): "BOTH",
        ("Yasuo", "R"): "PHYSICAL",
        ("Yorick", "E"): "PHYSICAL",
        ("Zoe", "E"): "MAGICAL",
        ("Annie", "R"): "MAGICAL",
    }

    def test_the_expected_map_covers_every_resist_lowering_row(self) -> None:
        shipped = {(champion, row.source) for champion, row in _resist_lowering_rows()}
        self.assertEqual(sorted(shipped - set(self._EXPECTED)), [])
        self.assertEqual(sorted(set(self._EXPECTED) - shipped), [])

    def test_each_resist_lowering_row_carries_its_derived_axis(self) -> None:
        for champion, row in _resist_lowering_rows():
            with self.subTest(champion=champion, source=row.source):
                self.assertEqual(row.axis, self._EXPECTED[(champion, row.source)])

    def test_magic_axis_rows_still_say_magic_in_the_shipped_prose(self) -> None:
        # Cheap drift catch: a row asserted MAGICAL whose tooltip stops
        # mentioning magic resist / magic pen is a re-authored ability.
        # Brand W is the one exception - it is a flat damage-vulnerability
        # amp on Brand's own MAGIC damage, so its prose says neither.
        for champion, row in _resist_lowering_rows():
            if row.axis != "MAGICAL" or (champion, row.source) == ("Brand", "W"):
                continue
            with self.subTest(champion=champion, source=row.source):
                prose = _slot_prose(champion, row.source).lower()
                self.assertTrue(
                    "magic resist" in prose or "magic pen" in prose,
                    f"{champion} {row.source} is axis MAGICAL but its 16.14.1"
                    " prose no longer mentions magic resist / magic pen",
                )

    def test_physical_axis_rows_never_claim_a_magic_side_grant(self) -> None:
        # The inverse guard. K'Sante R is the canonical case: his All Out
        # prose DOES say "magic resistance", but only about his OWN base
        # resists being cut - the penetration he gains is bonus-ARMOR.
        for champion, row in _resist_lowering_rows():
            if row.axis != "PHYSICAL":
                continue
            with self.subTest(champion=champion, source=row.source):
                prose = _slot_prose(champion, row.source).lower()
                self.assertNotIn("magic penetration", prose)


# --------------------------------------------------------------------------
# SLICE 3 - Amumu P is not a shred
# --------------------------------------------------------------------------

class R196AmumuIsNotAResistShredTests(unittest.TestCase):
    """The removed row, pinned so it cannot be re-added blind.

    ``add("Amumu", "P", "SHRED", "SUSTAINED", magnitude=0.6)`` claimed a
    resist shred. The 16.14.1 passive lowers no resist at all - it applies a
    damage-vulnerability debuff paid out as bonus TRUE damage, which is a
    different mechanic on a different axis. ``SHRED`` means "lowers the
    target's resists", so the row was factually wrong and is deleted.
    """

    def test_the_passive_prose_is_a_true_damage_vulnerability(self) -> None:
        prose = _slot_prose("Amumu", "P").lower()
        self.assertIn("bonus true damage", prose)
        self.assertIn("incoming pre-mitigation magic damage", prose)

    def test_the_passive_prose_states_no_resist_reduction(self) -> None:
        # If a future patch turns Curse back into an actual shred, this
        # goes RED and the row must be re-derived rather than re-guessed.
        prose = _slot_prose("Amumu", "P").lower()
        for marker in (
            "armor reduction",
            "magic resistance reduction",
            "reduces their armor",
            "reduce the target's armor",
            "armor penetration",
            "magic penetration",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, prose)

    def test_amumu_carries_no_resist_lowering_row(self) -> None:
        for row in _ANTITANK_REGISTRY.get("Amumu", ()):
            with self.subTest(source=row.source):
                self.assertNotIn(row.kind, _RESIST_LOWERING_KINDS)

    def test_no_other_amumu_slot_belongs_on_the_axis(self) -> None:
        # Re-verified, not assumed: W is a flat "Magic Damage Per Tick"
        # toggle (no %max-HP / %current-HP term) and Q / E / R are flat
        # magic damage, so nothing on the kit scales with the target's
        # health pool or resists. E's only resist prose is Amumu's OWN
        # physical damage reduction, a self-defensive term.
        slots = _abilities()["Amumu"]
        for slot in ("P", "Q", "W", "E", "R"):
            for form in slots.get(slot) or []:
                haystack = " | ".join(
                    (form.get("effects_descriptions") or [])
                    + [(b.get("attribute") or "") for b in (form.get("damage_blocks") or [])]
                ).lower()
                for marker in ("maximum health", "current health", "max health"):
                    with self.subTest(slot=slot, marker=marker):
                        self.assertNotIn(marker, haystack)

    def test_amumu_drops_off_the_selective_registry_entirely(self) -> None:
        # The correct answer for a SELECTIVE axis, not a regression: with
        # the one wrong row gone, Amumu owns no anti-tank mechanism.
        self.assertNotIn("Amumu", _ANTITANK_REGISTRY)
        result = compute_antitank("Amumu")
        self.assertEqual(result.antitank_score, 0.0)
        self.assertFalse(result.shreds_resist)
        self.assertEqual(result.top_kind, "")
        self.assertEqual(result.sources, ())


if __name__ == "__main__":
    unittest.main()
