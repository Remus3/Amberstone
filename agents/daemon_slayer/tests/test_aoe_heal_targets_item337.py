"""AOE heal per-target multiplicity registry - schema lift item 337 (2026-06-07).

A NEW sibling registry ``_AOE_HEAL_TARGETS`` capturing the per-cast TARGET
MULTIPLICITY of AOE / per-ally heals - the representative count of allied
champions a team-heal lands on. ``compute_ability_hps`` models only the
single-target heal amount (``heal_per_cast``) and hardwires the ally count to
1 in ``heal_per_sec``; the ``AbilitySpellHps`` schema has NO field for
multiplicity, so the TOTAL throughput of an AOE team-heal (Soraka R, Janna R,
Milio R, Seraphine W, Fiora R) is structurally inexpressible today. The flat
per-cast scalar can only hold the one-ally amount and discards the team-wide
total.

Verified from patch 16.11.1 ``data/daemon_slayer/16.11.1/
champion_abilities.json`` heal blocks + effects_descriptions (ground-truth
probed 2026-06-07):

* Soraka R (Wish): "healing herself and all allied champions" - global team
  heal -> assumed_targets 4.0.
* Milio R (Breath of Life): "healing ... himself and nearby allied
  champions" -> assumed_targets 4.0.
* Janna R (Monsoon): "healing herself and nearby allies every 0.25 seconds"
  -> assumed_targets 4.0.
* Seraphine W (Surround Sound): "healing herself and nearby allied champions,
  increased for each ally" - explicit per-ally scaling -> assumed_targets 3.0.
* Fiora R (Grand Challenge): "heals Fiora and all allies within the area"
  (a small Victory Zone) -> assumed_targets 2.0.

The ``assumed_targets`` VALUE follows the operator-tunable ``assumed_charges``
/ ``assumed_stacks`` convention (a representative teamfight ally count), NOT a
verbatim data field; what IS verbatim from the data file is that each seeded
spell is an AOE / per-ally heal (the per-ally heal block + the "all allied
champions" / "nearby allies" / "increased for each ally" effects text).

FORWARD-MARKER / BYTE-IDENTICAL contract: NOTHING consumes
``_AOE_HEAL_TARGETS`` at ship - it mirrors the way ``_PER_SPELL_CC_RANGE``
(item 336) and ``_PER_SPELL_CC_DURATIONS`` (item 130) shipped forward-marker
first. ``compute_ability_hps`` does not read it; ``heal_per_sec`` /
``total_heal_per_sec`` / both ``to_dict`` surfaces are byte-identical and
ENGINE_VERSION does NOT bump. A future EHP-vs-sustain / team-heal-throughput
consumer reads ``assumed_targets`` and multiplies ``heal_per_cast`` by it.

Coverage classes:
* ``AoeHealTargetsShapeTests`` - the 5 entries exist, each a positive float.
* ``AoeHealTargetsValuePinsTests`` - exact assumed_targets pin per seed.
* ``AoeHealTargetsAccessorTests`` - ``_aoe_heal_targets_for`` returns the
  float for a seeded champ+spell and ``None`` for an absent one.
* ``BuilderTests`` - the builder is exposed + its output matches the
  module-level registry.
* ``ByteIdenticalHpsSchemaTests`` - ``AbilitySpellHps`` carries NO
  multiplicity field and both ``to_dict`` surfaces keep their prior key sets
  (the registry did not touch the serialized schema).
* ``ForwardMarkerNoConsumerTests`` - no production module other than the
  definition + re-export module (``ability_hps.py``) references the registry -
  it is a pure forward-marker.
* ``EngineVersionUnchangedTests`` - ENGINE_VERSION stays >= 1.120.0
  (byte-identical, no bump).
* ``AsciiHygieneTests`` - the new registry block + this test file are
  pure-ASCII (no em/en-dash, no smart quotes per CLAUDE.md hard rule).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_hps import (
    AbilitySpellHps,
    _AOE_HEAL_TARGETS,
    _aoe_heal_targets_for,
    _build_aoe_heal_targets,
)


# ---------------- expected seed set ----------------


# item 337 AOE heal seeds: 5 AOE / per-ally heals, each confirmed an
# AOE team heal verbatim from 16.11.1 champion_abilities.json. The
# assumed_targets value follows the assumed_charges convention.
AOE_HEAL_TARGETS_EXPECTED: dict[str, dict[str, float]] = {
    "Soraka": {"R": 4.0},
    "Milio": {"R": 4.0},
    "Janna": {"R": 4.0},
    "Seraphine": {"W": 3.0},
    "Fiora": {"R": 2.0},
}


# ---------------- shape ----------------


class AoeHealTargetsShapeTests(unittest.TestCase):
    """The 5 AOE-heal entries exist as positive floats."""

    def test_all_seed_champs_present(self) -> None:
        for champ in AOE_HEAL_TARGETS_EXPECTED:
            self.assertIn(
                champ, _AOE_HEAL_TARGETS,
                f"aoe-heal seed champ {champ} missing from registry",
            )

    def test_all_seed_spells_present(self) -> None:
        for champ, spells in AOE_HEAL_TARGETS_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _AOE_HEAL_TARGETS[champ],
                    f"aoe-heal seed {champ} {key} missing",
                )

    def test_each_entry_is_float(self) -> None:
        for champ, spells in AOE_HEAL_TARGETS_EXPECTED.items():
            for key in spells:
                live = _AOE_HEAL_TARGETS[champ][key]
                self.assertIsInstance(
                    live, float, f"{champ} {key} assumed_targets not a float",
                )

    def test_each_entry_gt_one(self) -> None:
        # An AOE heal lands on more than one ally - a multiplicity of 1
        # would be the default single-target shape and worth nothing.
        for champ, spells in AOE_HEAL_TARGETS_EXPECTED.items():
            for key in spells:
                self.assertGreater(
                    _AOE_HEAL_TARGETS[champ][key], 1.0,
                    f"{champ} {key} multiplicity must exceed 1",
                )

    def test_at_least_five_seed_entries(self) -> None:
        total = sum(len(s) for s in _AOE_HEAL_TARGETS.values())
        self.assertGreaterEqual(
            total, 5, "expected at least the 5 item-337 AOE-heal seeds",
        )


# ---------------- value pins ----------------


class AoeHealTargetsValuePinsTests(unittest.TestCase):
    """Exact assumed_targets pin per seed (assumed_charges convention)."""

    def test_soraka_r_wish(self) -> None:
        # "healing herself and all allied champions" - global team heal
        self.assertEqual(_AOE_HEAL_TARGETS["Soraka"]["R"], 4.0)

    def test_milio_r_breath_of_life(self) -> None:
        # "healing ... himself and nearby allied champions"
        self.assertEqual(_AOE_HEAL_TARGETS["Milio"]["R"], 4.0)

    def test_janna_r_monsoon(self) -> None:
        # "healing herself and nearby allies every 0.25 seconds"
        self.assertEqual(_AOE_HEAL_TARGETS["Janna"]["R"], 4.0)

    def test_seraphine_w_surround_sound(self) -> None:
        # "healing herself and nearby allied champions, increased for each ally"
        self.assertEqual(_AOE_HEAL_TARGETS["Seraphine"]["W"], 3.0)

    def test_fiora_r_grand_challenge(self) -> None:
        # "heals Fiora and all allies within the area" - small Victory Zone
        self.assertEqual(_AOE_HEAL_TARGETS["Fiora"]["R"], 2.0)

    def test_all_seeds_match_expected(self) -> None:
        for champ, spells in AOE_HEAL_TARGETS_EXPECTED.items():
            for key, val in spells.items():
                self.assertEqual(
                    _AOE_HEAL_TARGETS[champ][key], val,
                    f"{champ} {key} mismatch",
                )


# ---------------- accessor ----------------


class AoeHealTargetsAccessorTests(unittest.TestCase):
    """``_aoe_heal_targets_for`` returns the float or ``None``."""

    def test_accessor_returns_seed_value(self) -> None:
        self.assertEqual(_aoe_heal_targets_for("Soraka", "R"), 4.0)
        self.assertEqual(_aoe_heal_targets_for("Seraphine", "W"), 3.0)

    def test_accessor_none_for_absent_champ(self) -> None:
        self.assertIsNone(_aoe_heal_targets_for("NotAChamp", "R"))

    def test_accessor_none_for_absent_spell(self) -> None:
        # Soraka has an AOE-heal multiplicity only on R, not Q.
        self.assertIsNone(_aoe_heal_targets_for("Soraka", "Q"))

    def test_accessor_none_when_champ_has_no_entry(self) -> None:
        # Lux heals nobody on a team-AOE; not in the registry.
        self.assertIsNone(_aoe_heal_targets_for("Lux", "R"))


# ---------------- builder ----------------


class BuilderTests(unittest.TestCase):
    """The AOE-heal builder is exposed + matches the module registry."""

    def test_builder_is_callable(self) -> None:
        self.assertTrue(callable(_build_aoe_heal_targets))

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_aoe_heal_targets()
        self.assertEqual(fresh, _AOE_HEAL_TARGETS)

    def test_builder_returns_fresh_dict(self) -> None:
        # Each call returns an independent dict (setdefault builder pattern).
        a = _build_aoe_heal_targets()
        b = _build_aoe_heal_targets()
        self.assertIsNot(a, b)
        self.assertEqual(a, b)


# ---------------- byte-identical HPS schema guard ----------------


class ByteIdenticalHpsSchemaTests(unittest.TestCase):
    """The serialized HPS schema is untouched by the multiplicity registry.

    Critical byte-identical guard: the new registry must NOT add a field to
    the returned ``AbilitySpellHps`` dataclass nor to its ``to_dict`` - any
    such change would alter ``/api/ds-preview`` output and break to_dict pins.
    """

    EXPECTED_FIELDS = (
        "key", "form_name", "form_index", "rank", "cooldown",
        "heal_per_cast", "shield_per_cast", "casts_per_sec",
        "casts_per_sec_source", "mana_uptime_factor", "heal_per_sec",
        "shield_per_sec", "notes",
    )

    def test_spell_hps_field_set_unchanged(self) -> None:
        self.assertEqual(
            tuple(AbilitySpellHps.__dataclass_fields__), self.EXPECTED_FIELDS,
        )

    def test_spell_hps_has_no_multiplicity_field(self) -> None:
        for banned in ("assumed_targets", "targets_per_cast", "targets"):
            self.assertNotIn(
                banned, AbilitySpellHps.__dataclass_fields__,
                f"{banned} leaked into the serialized AbilitySpellHps schema",
            )

    def test_spell_hps_to_dict_keys_unchanged(self) -> None:
        sample = AbilitySpellHps(
            key="R", form_name="Wish", form_index=0, rank=1, cooldown=120.0,
            heal_per_cast=200.0, shield_per_cast=0.0, casts_per_sec=0.0083,
            casts_per_sec_source="theoretical_cooldown", mana_uptime_factor=1.0,
            heal_per_sec=1.66, shield_per_sec=0.0,
        )
        self.assertEqual(tuple(sample.to_dict()), self.EXPECTED_FIELDS)


# ---------------- forward-marker (no consumer) ----------------


class ForwardMarkerNoConsumerTests(unittest.TestCase):
    """No production module consumes the AOE-heal registry yet.

    The registry is a pure forward-marker: only its definition module
    (``ability_hps.py``) may name it. Any other reference would mean a
    consumer branched on it - making the lift no longer byte-identical.
    """

    def test_no_unexpected_production_consumer(self) -> None:
        ds_dir = pathlib.Path(__file__).resolve().parent.parent
        allow = {"ability_hps.py"}
        offenders: list[str] = []
        for py in ds_dir.glob("*.py"):
            if py.name in allow:
                continue
            text = py.read_text(encoding="utf-8")
            if "_AOE_HEAL_TARGETS" in text or "_aoe_heal_targets_for" in text:
                offenders.append(py.name)
        self.assertEqual(
            offenders, [],
            f"aoe-heal registry unexpectedly consumed by: {offenders}",
        )


# ---------------- ENGINE version ----------------


class EngineVersionUnchangedTests(unittest.TestCase):
    """ENGINE_VERSION stays >= 1.120.0 - the lift is byte-identical.

    Because nothing consumes the registry, live DS output is unchanged, so
    this slice ships WITHOUT an ENGINE bump. The pin uses assertGreaterEqual
    (forward-compatible per the item 146 lesson).
    """

    def test_engine_version_at_least_1_120_0(self) -> None:
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 120, 0))


# ---------------- ASCII hygiene ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The new registry block + this test file are pure-ASCII."""

    def test_aoe_heal_registry_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "ability_hps.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start = src.find("_build_aoe_heal_targets")
        self.assertGreater(start, -1, "aoe-heal builder marker missing")
        block = src[start:]
        bad_glyphs = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left double smart quote",
            chr(0x201D): "right double smart quote",
            chr(0x2018): "left single smart quote",
            chr(0x2019): "right single smart quote",
        }
        for ch, name in bad_glyphs.items():
            self.assertNotIn(ch, block, f"aoe-heal block carries {name}")

    def test_this_test_file_is_ascii_clean(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        bad_seqs = [
            (b"\xe2\x80\x94", "em-dash"),
            (b"\xe2\x80\x93", "en-dash"),
            (b"\xe2\x80\x9c", "left double smart quote"),
            (b"\xe2\x80\x9d", "right double smart quote"),
            (b"\xe2\x80\x98", "left single smart quote"),
            (b"\xe2\x80\x99", "right single smart quote"),
        ]
        for seq, name in bad_seqs:
            self.assertNotIn(seq, raw, f"test file carries {name}")


if __name__ == "__main__":
    unittest.main()
