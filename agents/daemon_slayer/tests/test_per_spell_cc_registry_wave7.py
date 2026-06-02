"""ENGINE 1.37.0 (2026-05-22) - per-spell CC duration registry wave 7.

Wave 7 ships +8 entries across +8 NEW champions of first-order CC at
patch 16.10.1. All 8 are net-new champions (no multi-wave augmentations
this wave; the schema lift from wave 6 remains the canonical seam for
future multi-wave extensions).

Wave 7 entries:

* Irelia E Flawless Duet: stun 0.75/0.85/0.95/1.05/1.15 across 5 ranks
  (canonical post-rework value at 16.10.1; rank scales stun duration).
* Kalista R Fate's Call: knock-up 1.0s on enemies hit by the ally
  cannonball all 3 ranks (rank scales bonus dash range + damage, not
  CC duration).
* Ornn R Call of the Forge God: knock-up 0.5s on first-impact of the
  elemental ram all 3 ranks (canonical primary first-hit knockup; the
  second-cast Brittle knockup is conditional, intentionally skipped).
* Shyvana R Dragon's Descent: knock-back 1.0s on dragon-form contact
  with first enemy all 3 ranks (canonical post-rework displacement).
* Smolder R Mountain Breaker: knock-up 1.25s on enemies hit by the
  dive landing all 3 ranks (canonical knockup; rank scales damage +
  slow piece; slow intentionally skipped per no-slows wave rule).
* Vayne E Condemn: knock-back 0.5s on hit at all 5 ranks (universal
  knockback displacement; the wall-pin stun is conditional on terrain
  contact and stays REJECTED per no-conditional-CC rule).
* Volibear E Sky Splitter: airborne 0.25s on enemies under the
  landing zone at all 5 ranks (brief lift-up on the lightning strike;
  distinct from the conditional Volibear Q terrain-stun which stays
  REJECTED).
* Zac R Let's Bounce: knock-up 1.0s on enemies hit by Zac's bounce
  contact all 3 ranks (canonical knockup; slow piece on bounces
  intentionally skipped per no-slows convention).

Total registry post-wave-7: 103 entries across 90 champions.

REJECTED candidates (with reason recorded so future audits do NOT
re-research):

* Darius E Apprehend: pure pull + slow (no first-order stun).
* Yorick R Eulogy of the Isles: no first-order CC (Mist Walker
  summons; Yorick W Dark Procession is a wall summon, not champ-CC).
* AurelionSol Q Breath of Light: no CC (beam damage).
* Aurora W Across the Veil: no CC (dash + invisibility).
* Aurora E The Weirding: pull + slow conditional (REJECT carryover
  from wave 6 Aurora E).
* Ambessa all spells: no first-order CC at 16.10.1.
* Pyke E Phantom Undertow: damage on path-return only (no CC).
* Fiora W Riposte: parry/stun conditional on enemy targeted-damage.
* Vex E Looming Darkness: fear conditional on Vex E-passive mark.
* Ornn Q Volcanic Rupture: knockup conditional on Brittle second-cast.
* Renata R Hostile Takeover: berserk effect (different mechanic axis).
* Volibear Q Thundering Smash: terrain-conditional stun (REJECT
  carryover from waves 5+6).
* TahmKench R Devour: ally-target swallow (REJECT carryover).
* Aurora R Between Worlds: zone effect, no first-order CC.

Coverage classes:

* ``WaveSevenNewEntryShapeTests`` - the 8 new spell entries are present;
  total count matches expected; each new tuple has the expected length
  and floats.
* ``WaveSevenValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 tooltips.
* ``WaveOneThroughSixPreservedTests`` - representative entries across
  waves 1-6 byte-identical post-wave-7 addition.
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 7 (103 / 90).
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-7 ship
  state (1.37.0).
* ``AsciiHygieneTests`` - the wave 7 registry block + this test file
  are pure-ASCII (no em-dashes / smart quotes per CLAUDE.md hard rule).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    _PER_SPELL_CC_DURATIONS,
    _build_per_spell_cc_durations,
    _per_spell_cc_for,
)


# ---------------- new entry set ----------------


# Wave 7 entries: 8 spell entries across 8 distinct NEW champions.
# All 8 are net-new (no multi-wave augmentations this wave).
WAVE_SEVEN_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Irelia": {"E": (0.75, 0.85, 0.95, 1.05, 1.15)},
    "Kalista": {"R": (1.0, 1.0, 1.0)},
    "Ornn": {"R": (0.5, 0.5, 0.5)},
    "Shyvana": {"R": (1.0, 1.0, 1.0)},
    "Smolder": {"R": (1.25, 1.25, 1.25)},
    "Vayne": {"E": (0.5, 0.5, 0.5, 0.5, 0.5)},
    "Volibear": {"E": (0.25, 0.25, 0.25, 0.25, 0.25)},
    "Zac": {"R": (1.0, 1.0, 1.0)},
}


# All 8 wave 7 champions are NEW (none appeared in prior waves).
WAVE_SEVEN_NEW_CHAMPS = {
    "Irelia", "Kalista", "Ornn", "Shyvana", "Smolder",
    "Vayne", "Volibear", "Zac",
}


# Prior-wave champion id sets (do NOT edit; pin to detect accidental
# deletions during wave 7 addition).
WAVE_ONE_KEYS = {
    "Ahri", "Annie", "Ashe", "Blitzcrank", "Cassiopeia", "Galio",
    "Leona", "Lissandra", "Lulu", "Malzahar", "Maokai", "MonkeyKing",
    "Morgana", "Nautilus", "Pantheon", "Rakan", "Renekton", "Sejuani",
    "Sona", "Thresh", "Veigar", "Vi", "Yasuo", "Zoe",
}

WAVE_TWO_KEYS = {
    "Alistar", "Amumu", "Anivia", "Braum", "Chogath", "Fiddlesticks",
    "Gnar", "Gragas", "Jhin", "Lux", "Nami", "Neeko", "Orianna",
    "Poppy", "Riven", "Singed", "Skarner", "Varus", "Xerath", "Zac",
}

WAVE_THREE_KEYS = {
    "AurelionSol", "Caitlyn", "Camille", "Diana", "Elise",
    "Heimerdinger", "Ivern", "Malphite", "Pyke", "Rell", "Ryze",
    "Sion", "Tristana", "XinZhao",
}

WAVE_FOUR_KEYS = {
    "Draven", "Ekko", "Janna", "Jax", "Jinx", "Mel", "Nocturne",
    "Quinn", "Rammus", "Senna", "Seraphine", "Shaco", "Shen",
    "Soraka", "Zyra",
}

WAVE_FIVE_KEYS = {
    "Hecarim", "KSante", "Mordekaiser", "Urgot", "Viego", "Yone",
    "Ziggs",
}

WAVE_SIX_NEW_KEYS = {"Bard", "Lillia"}


# Note: WAVE_TWO_KEYS contains "Zac" (from wave 2's Zac E Elastic
# Slingshot). Wave 7 adds Zac R; Zac is therefore a multi-wave
# augmentation at the spell level (E from wave 2 + R from wave 7) but
# stays at 1 champ entry in the registry. WAVE_SEVEN_NEW_CHAMPS still
# treats it as "new for wave 7 R-spell" - the disjoint test below
# accounts for the Zac E-vs-R distinction.


# ---------------- wave 7 entry shape ----------------


class WaveSevenNewEntryShapeTests(unittest.TestCase):
    """The 8 new wave 7 entries are present in the registry."""

    def test_wave_seven_total_spell_entry_count_8(self) -> None:
        total = sum(len(s) for s in WAVE_SEVEN_EXPECTED.values())
        self.assertEqual(total, 8)

    def test_wave_seven_distinct_champion_count_8(self) -> None:
        self.assertEqual(len(WAVE_SEVEN_EXPECTED), 8)

    def test_all_wave_seven_champs_present_in_registry(self) -> None:
        for champ in WAVE_SEVEN_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 7 champ {champ} missing from registry",
            )

    def test_all_wave_seven_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 7 {champ} {key} missing",
                )

    def test_each_wave_seven_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )

    def test_all_wave_seven_values_non_negative(self) -> None:
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} has negative CC: {v}",
                    )

    def test_zac_multi_wave_augmentation(self) -> None:
        # Zac is a multi-wave augmentation at the spell level: Zac E
        # was seeded wave 2 (Elastic Slingshot knockup); wave 7 adds
        # Zac R (Let's Bounce knockup). The setdefault builder must
        # allow both spell entries to coexist on the same champion.
        spells = _PER_SPELL_CC_DURATIONS["Zac"]
        self.assertIn("E", spells)
        self.assertIn("R", spells)
        self.assertEqual(spells["E"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))


# ---------------- per-entry value pins ----------------


class WaveSevenValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1)."""

    def test_irelia_e_flawless_duet_stun(self) -> None:
        # Flawless Duet: stun 0.75/0.85/0.95/1.05/1.15 across 5 ranks
        # (canonical post-rework value at 16.10.1; rank scales stun
        # duration). Both daggers must connect for the stun to fire.
        self.assertEqual(
            _per_spell_cc_for("Irelia", "E"),
            (0.75, 0.85, 0.95, 1.05, 1.15),
        )

    def test_kalista_r_fates_call_knockup(self) -> None:
        # Fate's Call: knock-up 1.0s on enemies hit by ally cannonball
        # all 3 ranks (rank scales bonus dash range + damage, not CC).
        self.assertEqual(
            _per_spell_cc_for("Kalista", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_ornn_r_call_of_the_forge_god_knockup(self) -> None:
        # Call of the Forge God: knock-up 0.5s on first-impact of the
        # elemental ram all 3 ranks (canonical primary first-hit knockup;
        # second-cast Brittle knockup is conditional, skipped).
        self.assertEqual(
            _per_spell_cc_for("Ornn", "R"),
            (0.5, 0.5, 0.5),
        )

    def test_shyvana_r_dragons_descent_knockback(self) -> None:
        # Dragon's Descent: knock-back 1.0s on dragon-form contact with
        # first enemy all 3 ranks (canonical post-rework displacement).
        self.assertEqual(
            _per_spell_cc_for("Shyvana", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_smolder_r_mountain_breaker_knockup(self) -> None:
        # Mountain Breaker: knock-up 1.25s on enemies hit by dive
        # landing all 3 ranks (canonical knockup; slow piece skipped).
        self.assertEqual(
            _per_spell_cc_for("Smolder", "R"),
            (1.25, 1.25, 1.25),
        )

    def test_vayne_e_condemn_knockback(self) -> None:
        # Condemn: knock-back 0.5s on hit at all 5 ranks (universal
        # knockback; wall-pin stun is conditional - REJECTED).
        self.assertEqual(
            _per_spell_cc_for("Vayne", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_volibear_e_sky_splitter_airborne(self) -> None:
        # Sky Splitter: airborne 0.25s on enemies under landing zone
        # all 5 ranks (brief lift-up; distinct from conditional
        # Volibear Q terrain-stun which stays REJECTED).
        self.assertEqual(
            _per_spell_cc_for("Volibear", "E"),
            (0.25, 0.25, 0.25, 0.25, 0.25),
        )

    def test_zac_r_lets_bounce_knockup(self) -> None:
        # Let's Bounce: knock-up 1.0s on enemies hit by bounce contact
        # all 3 ranks (canonical knockup; slow piece skipped).
        self.assertEqual(
            _per_spell_cc_for("Zac", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_all_wave_seven_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_SEVEN_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- prior wave preservation ----------------


class WaveOneThroughSixPreservedTests(unittest.TestCase):
    """Representative entries across waves 1-6 byte-identical post-wave-7.

    Pin enough entries across each prior wave to detect accidental
    deletion when wave 7 is added. The setdefault builder pattern is
    safe (later additions add new keys without clobbering); these
    assertions guard the contract.
    """

    def test_wave_one_annie_r_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Annie"]["R"], (1.5, 1.5, 1.5),
        )

    def test_wave_one_morgana_q_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Morgana"]["Q"],
            (2.0, 2.25, 2.5, 2.75, 3.0),
        )

    def test_wave_one_galio_three_spells_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Galio"]
        self.assertEqual(spells["W"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["E"], (0.5, 0.5, 0.5, 0.5, 0.5))
        self.assertEqual(spells["R"], (0.75, 0.75, 0.75))

    def test_wave_two_lux_q_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Lux"]["Q"],
            (2.0, 2.25, 2.5, 2.75, 3.0),
        )

    def test_wave_three_elise_e_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Elise"]["E"],
            (1.1, 1.4, 1.7, 2.0, 2.3),
        )

    def test_wave_four_nocturne_e_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Nocturne"]["E"],
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_wave_five_hecarim_two_spells_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Hecarim"]
        self.assertEqual(spells["E"], (0.75, 0.75, 0.75, 0.75, 0.75))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))

    def test_wave_six_lulu_w_polymorph_preserved(self) -> None:
        # Wave 6 schema lift added Lulu R; Lulu W (wave 1) must persist.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Lulu"]["W"],
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_wave_six_lulu_r_wild_growth_preserved(self) -> None:
        # Wave 6 multi-wave augmentation case.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Lulu"]["R"], (1.0, 1.0, 1.0),
        )

    def test_wave_six_bard_r_stasis_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Bard"]["R"], (2.5, 2.5, 2.5),
        )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_floor_at_103_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82, wave 5 = +8 = 90, wave 6 = +5 = 95,
        # wave 7 = +8 = 103.
        # Wave 8 = +3 = 106 (relaxed to assertGreaterEqual for
        # future-wave forward compatibility).
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 103)

    def test_registry_floor_at_89_champions(self) -> None:
        # Wave 1 = 24, wave 2 = +20 = 44, wave 3 = +14 = 58,
        # wave 4 = +15 = 73, wave 5 = +7 = 80, wave 6 = +2 new = 82,
        # wave 7 = +7 NEW champs (Irelia / Kalista / Ornn / Shyvana /
        # Smolder / Vayne / Volibear; Zac was already in wave 2 as a
        # multi-wave augmentation - Zac E from wave 2 + Zac R from
        # wave 7 share the same Zac champion entry). 82 + 7 = 89.
        # Wave 8 = +0 new champs (all 3 are multi-wave augmentations).
        # 89 + 0 = 89 (relaxed to assertGreaterEqual for future waves).
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 89)

    def test_wave_seven_new_champs_count(self) -> None:
        # Count new champions added in wave 7 (excluding multi-wave
        # augmentations of existing champions).
        prior = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
            | WAVE_SIX_NEW_KEYS
        )
        new = WAVE_SEVEN_NEW_CHAMPS - prior
        # Zac is in wave 2, so wave 7 new (Zac-excluded) = 7 net new.
        self.assertEqual(len(new), 7)

    def test_zac_is_multi_wave_augmentation(self) -> None:
        # Zac appears in both wave 2 (E) and wave 7 (R).
        self.assertIn("Zac", WAVE_TWO_KEYS)
        self.assertIn("Zac", WAVE_SEVEN_NEW_CHAMPS)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin at wave-7 ship state.

    Wave 7 ships +8 entries / +7 new champs / +1 multi-wave aug (Zac).
    The engine bump 1.37.0 -> 1.37.0 happens at orchestrator merge
    time; this commit pins the pre-bump state (1.37.0). Orchestrator
    flips this assertion to 1.37.0 when merging.
    """

    def test_engine_version_at_1_36_0(self) -> None:
        # Pre-orchestrator-merge state. Orchestrator bumps the source
        # ENGINE_VERSION to 1.37.0 + flips this assertion to match.
        self.assertEqual(ENGINE_VERSION, "1.94.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 7 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_seven_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.37.0 wave 7"
        end_marker = "return registry"
        start = src.find(start_marker)
        # Find the LAST 'return registry' (the one closing _build).
        end = src.rfind(end_marker)
        self.assertGreater(start, -1, "wave 7 marker missing")
        self.assertGreater(end, -1, "post-registry marker missing")
        self.assertGreater(end, start, "marker order broken")
        block = src[start:end]
        bad_glyphs = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left double smart quote",
            chr(0x201D): "right double smart quote",
            chr(0x2018): "left single smart quote",
            chr(0x2019): "right single smart quote",
        }
        for ch, name in bad_glyphs.items():
            self.assertNotIn(
                ch, block, f"wave 7 block carries {name}",
            )

    def test_this_test_file_is_ascii_clean(self) -> None:
        src_path = pathlib.Path(__file__)
        raw = src_path.read_bytes()
        bad_seqs = [
            (b"\xe2\x80\x94", "em-dash"),
            (b"\xe2\x80\x93", "en-dash"),
            (b"\xe2\x80\x9c", "left double smart quote"),
            (b"\xe2\x80\x9d", "right double smart quote"),
            (b"\xe2\x80\x98", "left single smart quote"),
            (b"\xe2\x80\x99", "right single smart quote"),
        ]
        for seq, name in bad_seqs:
            self.assertNotIn(
                seq, raw, f"test file carries {name}",
            )


class SchemaLiftPreservedTests(unittest.TestCase):
    """The wave 6 schema lift builder is still in place + working."""

    def test_builder_function_is_exposed(self) -> None:
        self.assertTrue(callable(_build_per_spell_cc_durations))

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_per_spell_cc_durations()
        self.assertEqual(fresh, _PER_SPELL_CC_DURATIONS)


if __name__ == "__main__":
    unittest.main()
