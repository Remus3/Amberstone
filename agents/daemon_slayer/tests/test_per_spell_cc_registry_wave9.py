"""per-spell CC duration registry wave 9 (2026-05-22).

Wave 9 ships +2 entries / 0 NEW champions / 2 multi-wave augmentations
of first-order CC at patch 16.10.1.

Per item 146 carry (j): "wave 9+ likely thin pool (saturation for
net-new champions). The unconditional first-order CC at 16.10.1 is
genuinely saturated for net-new champions, future waves either coexist
on already-registered champs OR need new schema." Wave 9 delivers
exactly that - both wave 9 entries are multi-wave coexistence on
already-registered champions.

The wave 9 audit walked every UNREGISTERED spell of every already-
registered champion in data/daemon_slayer/16.10.1/champion_abilities.json
for explicit Stun/Root/Silence/Charm/Fear/Taunt/Sleep/Suppression/
Knockup/Knockback/Airborne/Stasis Duration blocks. Result: 6 candidates
surfaced from the abilities-data grep, of which 2 are genuine
unconditional first-order CC and 4 are already-known conditional /
out-of-scope rejects (see REJECTED list below).

Wave 9 entries:

* Chogath W Feral Scream: silence 1.6/1.7/1.8/1.9/2.0 across 5 ranks
  (canonical 16.10.1 Meraki via Silence Duration block). Cone-shaped
  magic damage + silence on cast; enemies in the cone are silenced
  unconditionally once W is cast. Multi-wave augmentation: Chogath Q
  Rupture knockup seeded wave 2.
* Malzahar Q Call of the Void: silence 1.0/1.25/1.5/1.75/2.0 across
  5 ranks (canonical 16.10.1 Meraki via Silence Duration block). Two
  void zones AOE location-cast; enemies caught in the path between
  zones are silenced unconditionally on contact. Multi-wave
  augmentation: Malzahar R Nether Grasp suppression seeded wave 1.

Total registry post-wave-9: 108 entries across 89 champions
(champ count unchanged - both wave 9 additions are multi-wave
augmentations on existing champions).

Silence is added to the first-order CC scope in this wave per the
same precedent as wave 6 stasis (Bard R Tempered Fate) - hard-disable
types that fit cleanly alongside stun / root / suspension /
suppression. The cc_conditional registry remains the schema home for
state-gated silence variants if any surface later.

REJECTED candidates (with reason recorded so future audits do NOT
re-research):

* Bard Q Cosmic Binding: already in cc_conditional wave 1
  (terrain-bounce double-stun conditional axis). The unconditional
  first-stun-on-direct-hit piece fires on every cast but the double-
  stun-on-bounce semantics are conditional; cc_conditional handles.
* Morgana R Soul Shackles: stun 1.5/1.75/2.0 across 3 ranks IS in
  the Stun Duration block - BUT the stun fires only on tether expiry
  which requires target staying in range for ~3s OR dying mid-tether.
  Channel-completion-conditional axis; explicitly REJECTED in item 146
  wave 8 - belongs in cc_conditional if added later (parallel to
  Karma W in cc_conditional wave 1).
* Seraphine E Beat Drop: stun OR root duration 1.1/1.2/1.3/1.4/1.5
  across 5 ranks. Already REJECTED in waves 4 + 8 - target state
  determines which CC fires (still target gets root, moving/slowed
  target gets stun). Conditional axis per item 138 rule.
* Volibear R Stormbringer: 2/3/4s Turret Disable Duration - the
  disable is on STRUCTURES (turrets), not champion CC. Carryover
  REJECT from items 138 + 142 + 146.
* Janna R Monsoon: initial knockup on cast + heal channel; the
  initial knockup duration is not exposed in damage_blocks (only
  Heal Per Tick + Total Heal). The knockup is brief (~0.5s) and the
  channel itself is a slow-pulse-with-heal not a hard CC. Operator-
  tunable channel-knockup deferred to cc_conditional with a channel-
  completion gate.
* Lulu E Help, Pix!: shield/damage only, no CC.

Coverage classes:

* ``WaveNineNewEntryShapeTests`` - the 2 new spell entries are present;
  total count matches expected; each new tuple has the expected length
  and floats.
* ``WaveNineValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 Meraki bulk.
* ``WaveNineCoexistenceWithPriorWavesTests`` - each wave 9 entry
  coexists with its prior-wave sibling on the same champion's spell
  map without clobbering.
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 9 (>=108 / >=89; champ count unchanged
  because both wave 9 additions are multi-wave augmentations).
* ``SchemaLiftBuilderPreservedTests`` - wave 6 setdefault builder
  still in place; multi-wave augmentation contract preserved for
  the wave 9 additions.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin uses
  assertGreaterEqual forward-compatible per item 146 wave 5 lesson.
* ``AsciiHygieneTests`` - the wave 9 registry block + this test file
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


# Wave 9 entries: 2 spell entries across 2 distinct champions, both
# multi-wave augmentations (no NEW champions).
WAVE_NINE_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Chogath": {"W": (1.6, 1.7, 1.8, 1.9, 2.0)},
    "Malzahar": {"Q": (1.0, 1.25, 1.5, 1.75, 2.0)},
}


# Prior-wave champion id sets (pin to detect accidental deletions
# during wave 9 addition; sourced from test_per_spell_cc_registry_wave8).
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

WAVE_SEVEN_NEW_KEYS = {
    "Irelia", "Kalista", "Ornn", "Shyvana", "Smolder",
    "Vayne", "Volibear",
}

# Wave 8: 0 new champions (Lissandra / Maokai / Rakan all in wave 1).
WAVE_EIGHT_AUGMENTED_CHAMPS = {"Lissandra", "Maokai", "Rakan"}

# Wave 9: 0 new champions - both entries are multi-wave augmentations.
# Chogath was seeded wave 2 (Q Rupture); Malzahar was seeded wave 1
# (R Nether Grasp).
WAVE_NINE_AUGMENTED_CHAMPS = {"Chogath", "Malzahar"}


# ---------------- wave 9 entry shape ----------------


class WaveNineNewEntryShapeTests(unittest.TestCase):
    """The 2 new wave 9 entries are present in the registry."""

    def test_wave_nine_total_spell_entry_count_2(self) -> None:
        total = sum(len(s) for s in WAVE_NINE_EXPECTED.values())
        self.assertEqual(total, 2)

    def test_wave_nine_distinct_champion_count_2(self) -> None:
        self.assertEqual(len(WAVE_NINE_EXPECTED), 2)

    def test_all_wave_nine_champs_present_in_registry(self) -> None:
        for champ in WAVE_NINE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 9 champ {champ} missing from registry",
            )

    def test_all_wave_nine_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_NINE_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 9 {champ} {key} missing",
                )

    def test_each_wave_nine_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_NINE_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_tuples_length_five(self) -> None:
        # Both wave 9 entries are Q or W; both must be 5-rank tuples.
        for champ, spells in WAVE_NINE_EXPECTED.items():
            for key, _tup in spells.items():
                self.assertIn(key, {"Q", "W"}, f"{champ} {key} unexpected key")
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                self.assertEqual(
                    len(live), 5,
                    f"{champ} {key} expected 5 ranks",
                )

    def test_all_wave_nine_values_non_negative(self) -> None:
        for champ, spells in WAVE_NINE_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} has negative CC: {v}",
                    )

    def test_no_new_champions_in_wave_nine(self) -> None:
        # All 2 wave 9 entries are multi-wave augmentations on champs
        # already in prior waves. WAVE_NINE_AUGMENTED_CHAMPS must be a
        # subset of the union of prior-wave champion sets.
        prior = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
            | WAVE_SIX_NEW_KEYS
            | WAVE_SEVEN_NEW_KEYS
        )
        new_champs = WAVE_NINE_AUGMENTED_CHAMPS - prior
        self.assertEqual(
            new_champs, set(),
            f"wave 9 unexpectedly added new champions: {new_champs}",
        )


# ---------------- multi-wave coexistence ----------------


class WaveNineCoexistenceWithPriorWavesTests(unittest.TestCase):
    """Each wave 9 addition coexists with its prior-wave spell entry."""

    def test_chogath_w_coexists_with_wave_two_q(self) -> None:
        # Wave 2 seeded Chogath Q (Rupture knockup); wave 9 adds W.
        spells = _PER_SPELL_CC_DURATIONS["Chogath"]
        self.assertIn("Q", spells)
        self.assertIn("W", spells)
        self.assertEqual(spells["Q"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["W"], (1.6, 1.7, 1.8, 1.9, 2.0))

    def test_malzahar_q_coexists_with_wave_one_r(self) -> None:
        # Wave 1 seeded Malzahar R (Nether Grasp suppression); wave 9
        # adds Q (silence).
        spells = _PER_SPELL_CC_DURATIONS["Malzahar"]
        self.assertIn("R", spells)
        self.assertIn("Q", spells)
        self.assertEqual(spells["R"], (2.5, 2.5, 2.5))
        self.assertEqual(spells["Q"], (1.0, 1.25, 1.5, 1.75, 2.0))


# ---------------- per-entry value pins ----------------


class WaveNineValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1 Meraki)."""

    def test_chogath_w_feral_scream_silence(self) -> None:
        # Feral Scream: silence 1.6/1.7/1.8/1.9/2.0 across 5 ranks
        # (Meraki 16.10.1 Silence Duration block). Cone-shaped silence
        # on cast, unconditional once W is cast.
        self.assertEqual(
            _per_spell_cc_for("Chogath", "W"),
            (1.6, 1.7, 1.8, 1.9, 2.0),
        )

    def test_malzahar_q_call_of_the_void_silence(self) -> None:
        # Call of the Void: silence 1.0/1.25/1.5/1.75/2.0 across 5
        # ranks (Meraki 16.10.1 Silence Duration block). Void-zones
        # AOE silence on contact, unconditional.
        self.assertEqual(
            _per_spell_cc_for("Malzahar", "Q"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_all_wave_nine_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_NINE_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- prior wave preservation ----------------


class WaveOneThroughEightPreservedTests(unittest.TestCase):
    """Representative entries across waves 1-8 byte-identical post-wave-9.

    Pin enough entries across each prior wave to detect accidental
    deletion when wave 9 is added. The setdefault builder pattern is
    safe (later additions add new keys without clobbering); these
    assertions guard the contract.
    """

    def test_wave_one_annie_r_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Annie"]["R"], (1.5, 1.5, 1.5),
        )

    def test_wave_one_malzahar_r_preserved_after_q_added(self) -> None:
        # Multi-wave coexistence: wave 1 Malzahar R + wave 9 Malzahar Q.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Malzahar"]["R"], (2.5, 2.5, 2.5),
        )

    def test_wave_two_chogath_q_preserved_after_w_added(self) -> None:
        # Multi-wave coexistence: wave 2 Chogath Q + wave 9 Chogath W.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Chogath"]["Q"],
            (1.0, 1.0, 1.0, 1.0, 1.0),
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

    def test_wave_four_senna_w_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Senna"]["W"],
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_wave_five_hecarim_two_spells_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Hecarim"]
        self.assertEqual(spells["E"], (0.75, 0.75, 0.75, 0.75, 0.75))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))

    def test_wave_six_bard_r_stasis_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Bard"]["R"], (2.5, 2.5, 2.5),
        )

    def test_wave_seven_irelia_e_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Irelia"]["E"],
            (0.75, 0.85, 0.95, 1.05, 1.15),
        )

    def test_wave_seven_zac_two_spells_preserved(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Zac"]
        self.assertEqual(spells["E"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))

    def test_wave_eight_lissandra_w_preserved(self) -> None:
        # Wave 8 multi-wave augmentation; Lissandra R was wave 1.
        spells = _PER_SPELL_CC_DURATIONS["Lissandra"]
        self.assertEqual(spells["R"], (1.5, 1.5, 1.5))
        self.assertEqual(spells["W"], (1.25, 1.35, 1.45, 1.55, 1.65))

    def test_wave_eight_maokai_w_preserved(self) -> None:
        # Wave 8 multi-wave augmentation; Maokai R was wave 1.
        spells = _PER_SPELL_CC_DURATIONS["Maokai"]
        self.assertEqual(spells["R"], (1.2, 1.6, 2.0))
        self.assertEqual(spells["W"], (1.0, 1.1, 1.2, 1.3, 1.4))

    def test_wave_eight_rakan_r_preserved(self) -> None:
        # Wave 8 multi-wave augmentation; Rakan W was wave 1.
        spells = _PER_SPELL_CC_DURATIONS["Rakan"]
        self.assertEqual(spells["W"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["R"], (1.0, 1.25, 1.5))


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_total_at_least_108_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82, wave 5 = +8 = 90, wave 6 = +5 = 95,
        # wave 7 = +8 = 103, wave 8 = +3 = 106, wave 9 = +2 = 108.
        # Uses assertGreaterEqual for forward-compatibility per item
        # 146 wave 5 lesson.
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 108)

    def test_registry_at_least_89_champions(self) -> None:
        # Champion count unchanged at wave 9: both wave 9 entries are
        # multi-wave augmentations on existing champions (Chogath was
        # seeded wave 2; Malzahar was seeded wave 1). Forward-compatible
        # floor pin per item 146 lesson.
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 89)

    def test_wave_nine_zero_new_champs(self) -> None:
        # Wave 9 added 0 net new champions.
        prior = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
            | WAVE_SIX_NEW_KEYS
            | WAVE_SEVEN_NEW_KEYS
        )
        new = WAVE_NINE_AUGMENTED_CHAMPS - prior
        self.assertEqual(len(new), 0)

    def test_wave_nine_two_multi_wave_augmentations(self) -> None:
        # Wave 9 champion set: Chogath in wave 2; Malzahar in wave 1.
        self.assertIn("Chogath", WAVE_TWO_KEYS)
        self.assertIn("Malzahar", WAVE_ONE_KEYS)


# ---------------- schema lift preserved ----------------


class SchemaLiftBuilderPreservedTests(unittest.TestCase):
    """The wave 6 setdefault builder is still in place + working.

    The builder pattern is what enables wave 9's 2 multi-wave
    augmentations to coexist with their prior-wave entries on the
    same champion's spell map. Without setdefault, the wave 9
    dict-literal additions would clobber the prior entries.
    """

    def test_builder_function_is_exposed(self) -> None:
        self.assertTrue(callable(_build_per_spell_cc_durations))

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_per_spell_cc_durations()
        self.assertEqual(fresh, _PER_SPELL_CC_DURATIONS)

    def test_multi_wave_augmentations_did_not_clobber(self) -> None:
        # Re-pin both wave 9 augmentations + their prior-wave siblings
        # to prove the setdefault contract works for wave 9 additions.
        chogath = _PER_SPELL_CC_DURATIONS["Chogath"]
        self.assertEqual(len(chogath), 2)  # Q (wave 2) + W (wave 9)
        malzahar = _PER_SPELL_CC_DURATIONS["Malzahar"]
        self.assertEqual(len(malzahar), 2)  # R (wave 1) + Q (wave 9)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin uses assertGreaterEqual for forward-compat.

    Wave 9 ships +2 entries / 0 new champs / 2 multi-wave augs. The
    engine bump 1.42.0 -> 1.43.0 happens at orchestrator merge time;
    using assertGreaterEqual per item 146 wave 5 lesson means this
    assertion does NOT require orchestrator to flip when ENGINE_VERSION
    is bumped - the test passes at any version >= 1.42.0.
    """

    def test_engine_version_at_least_1_42_0(self) -> None:
        # Forward-compatible pin: passes at the wave-9 SHIP version
        # 1.42.0 AND any subsequent orchestrator bump (1.43.0, etc.).
        # Saves orchestrator effort per item 146 lesson.
        parts = tuple(int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual(parts, (1, 42, 0))


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 9 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_nine_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "ability_dps.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE wave 9 (2026-05-22)"
        end_marker = "return registry"
        start = src.find(start_marker)
        # Find the LAST 'return registry' (the one closing _build).
        end = src.rfind(end_marker)
        self.assertGreater(start, -1, "wave 9 marker missing")
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
                ch, block, f"wave 9 block carries {name}",
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


if __name__ == "__main__":
    unittest.main()
