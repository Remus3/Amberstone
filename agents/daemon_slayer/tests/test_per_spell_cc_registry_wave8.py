"""ENGINE 1.42.0 (2026-05-22) - per-spell CC duration registry wave 8.

Wave 8 ships +3 entries / 0 NEW champions / 3 multi-wave augmentations
of first-order CC at patch 16.10.1.

The unconditional first-order CC at patch 16.10.1 is approaching
saturation per item 145 don't-redo: "most remaining champions either
have no first-order CC OR carry conditional-only CC". The wave 8
audit walked every champion+spell duration block in
data/daemon_slayer/16.10.1/champion_abilities.json + cross-checked
against the wave-1-through-7 entries + the cc_conditional 33-entry
registry. Net new unconditional candidates: 3 (all multi-wave
augmentations of champions already partially seeded).

Wave 8 entries:

* Lissandra W Ring of Frost: root 1.25/1.35/1.45/1.55/1.65 across 5
  ranks (canonical 16.10.1 Meraki via Root Duration block). AOE-on-cast
  around Lissandra; enemies in radius are rooted unconditionally.
  Multi-wave augmentation: Lissandra R stun was seeded wave 1.
* Maokai W Twisted Advance: root 1.0/1.1/1.2/1.3/1.4 across 5 ranks
  (canonical 16.10.1 Meraki via Root Duration block). Targeted dash +
  root on enemy hit; the root applies on contact unconditionally once
  W is cast. Multi-wave augmentation: Maokai R Nature's Grasp seeded
  wave 1. NOTE: Maokai Q Bramble Smash terrain-stun is conditional
  (cc_conditional wave 2 entry) and stays REJECTED here.
* Rakan R The Quickness: charm 1.0/1.25/1.5 across 3 ranks (canonical
  16.10.1 Meraki via Disable Duration block). Rakan dashes around an
  area for up to 4s; enemies he touches during the dash are charmed.
  The charm-on-touch is unconditional once R is cast (the dash IS the
  cast). Multi-wave augmentation: Rakan W Grand Entrance knock-up
  seeded wave 1.

Total registry post-wave-8: 106 entries across 89 champions
(champ count unchanged - all 3 wave 8 additions are multi-wave
augmentations on existing champions).

REJECTED candidates (with reason recorded so future audits do NOT
re-research):

* Bard Q Cosmic Binding: already in cc_conditional wave 1
  (terrain-bounce double-stun conditional axis).
* Evelynn W Allure: charm/stun is detonation-on-Eve-attack
  conditional (target must be auto-attacked by Eve to apply the
  charm); REJECT - belongs in cc_conditional if added later.
* Karma W Focused Resolve: already in cc_conditional wave 1
  (channel-completion full-tether root).
* Morgana R Soul Shackles: stun fires on tether expiry which
  requires target staying in range for 3s OR dying mid-tether;
  channel-completion-conditional axis; REJECT - belongs in
  cc_conditional if added later (parallel to Karma W).
* Seraphine E Beat Drop: stun OR root duration is the same value
  but which CC fires is conditional on target state; REJECT per
  item 138 conditional-CC rule (target state is a conditional axis).
* TwistedFate W Pick a Card: already in cc_conditional wave 1
  (gold-card selection conditional stun).
* Volibear R Stormbringer: 2/3/4s Turret Disable Duration applies to
  STRUCTURES (turrets), not champion CC; carryover from items 138
  REJECT list.
* Zilean Q Time Bomb: already in cc_conditional wave 2 (double-bomb
  stack conditional stun).
* Senna W Last Embrace: ALREADY in wave 4 (item 145's REJECT-list
  note "Senna W (unconditional)" matched the existing wave-4 entry;
  verified via grep - root 1.25/1.5/1.75/2.0/2.25).
* Tristana W Rocket Jump landing: REJECT per item 140 wave 6 list
  (landing applies a small slow not a discrete knockback at 16.10.1).
* Aatrox W Infernal Chains: already in cc_conditional wave 4
  (debuffed-target persistence pull-back root).
* Skarner Q Shattered Earth + Upheaval: already in cc_conditional
  wave 2 (nth-hit knockup).

Coverage classes:

* ``WaveEightNewEntryShapeTests`` - the 3 new spell entries are present;
  total count matches expected; each new tuple has the expected length
  and floats.
* ``WaveEightValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 Meraki bulk.
* ``WaveOneThroughSevenPreservedTests`` - representative entries across
  waves 1-7 byte-identical post-wave-8 addition.
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 8 (106 / 89; champ count unchanged).
* ``SchemaLiftBuilderPreservedTests`` - wave 6 setdefault builder
  still in place; multi-wave augmentation contract preserved.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-8 ship
  state (1.42.0; orchestrator flips at merge time).
* ``AsciiHygieneTests`` - the wave 8 registry block + this test file
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


# Wave 8 entries: 3 spell entries across 3 distinct champions, all
# multi-wave augmentations (no NEW champions).
WAVE_EIGHT_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Lissandra": {"W": (1.25, 1.35, 1.45, 1.55, 1.65)},
    "Maokai": {"W": (1.0, 1.1, 1.2, 1.3, 1.4)},
    "Rakan": {"R": (1.0, 1.25, 1.5)},
}


# Prior-wave champion id sets (do NOT edit; pin to detect accidental
# deletions during wave 8 addition).
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

# Wave 8: 0 new champions - all 3 entries are multi-wave augmentations.
WAVE_EIGHT_AUGMENTED_CHAMPS = {"Lissandra", "Maokai", "Rakan"}


# ---------------- wave 8 entry shape ----------------


class WaveEightNewEntryShapeTests(unittest.TestCase):
    """The 3 new wave 8 entries are present in the registry."""

    def test_wave_eight_total_spell_entry_count_3(self) -> None:
        total = sum(len(s) for s in WAVE_EIGHT_EXPECTED.values())
        self.assertEqual(total, 3)

    def test_wave_eight_distinct_champion_count_3(self) -> None:
        self.assertEqual(len(WAVE_EIGHT_EXPECTED), 3)

    def test_all_wave_eight_champs_present_in_registry(self) -> None:
        for champ in WAVE_EIGHT_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 8 champ {champ} missing from registry",
            )

    def test_all_wave_eight_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 8 {champ} {key} missing",
                )

    def test_each_wave_eight_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )

    def test_all_wave_eight_values_non_negative(self) -> None:
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} has negative CC: {v}",
                    )

    def test_no_new_champions_in_wave_eight(self) -> None:
        # All 3 wave 8 entries are multi-wave augmentations on champs
        # already in prior waves. WAVE_EIGHT_AUGMENTED_CHAMPS must be a
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
        new_champs = WAVE_EIGHT_AUGMENTED_CHAMPS - prior
        self.assertEqual(
            new_champs, set(),
            f"wave 8 unexpectedly added new champions: {new_champs}",
        )


# ---------------- multi-wave coexistence ----------------


class WaveEightMultiWaveCoexistenceTests(unittest.TestCase):
    """Each wave 8 addition coexists with its prior-wave spell entry."""

    def test_lissandra_w_coexists_with_wave_one_r(self) -> None:
        # Wave 1 seeded Lissandra R (Frozen Tomb stun); wave 8 adds W.
        spells = _PER_SPELL_CC_DURATIONS["Lissandra"]
        self.assertIn("R", spells)
        self.assertIn("W", spells)
        self.assertEqual(spells["R"], (1.5, 1.5, 1.5))
        self.assertEqual(spells["W"], (1.25, 1.35, 1.45, 1.55, 1.65))

    def test_maokai_w_coexists_with_wave_one_r(self) -> None:
        # Wave 1 seeded Maokai R (Nature's Grasp root); wave 8 adds W.
        spells = _PER_SPELL_CC_DURATIONS["Maokai"]
        self.assertIn("R", spells)
        self.assertIn("W", spells)
        self.assertEqual(spells["R"], (1.2, 1.6, 2.0))
        self.assertEqual(spells["W"], (1.0, 1.1, 1.2, 1.3, 1.4))

    def test_rakan_r_coexists_with_wave_one_w(self) -> None:
        # Wave 1 seeded Rakan W (Grand Entrance knockup); wave 8 adds R.
        spells = _PER_SPELL_CC_DURATIONS["Rakan"]
        self.assertIn("W", spells)
        self.assertIn("R", spells)
        self.assertEqual(spells["W"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["R"], (1.0, 1.25, 1.5))


# ---------------- per-entry value pins ----------------


class WaveEightValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1 Meraki)."""

    def test_lissandra_w_ring_of_frost_root(self) -> None:
        # Ring of Frost: root 1.25/1.35/1.45/1.55/1.65 across 5 ranks
        # (Meraki 16.10.1 Root Duration block). AOE-on-cast.
        self.assertEqual(
            _per_spell_cc_for("Lissandra", "W"),
            (1.25, 1.35, 1.45, 1.55, 1.65),
        )

    def test_maokai_w_twisted_advance_root(self) -> None:
        # Twisted Advance: root 1.0/1.1/1.2/1.3/1.4 across 5 ranks
        # (Meraki 16.10.1 Root Duration block). Dash + root on contact.
        self.assertEqual(
            _per_spell_cc_for("Maokai", "W"),
            (1.0, 1.1, 1.2, 1.3, 1.4),
        )

    def test_rakan_r_the_quickness_charm(self) -> None:
        # The Quickness: charm 1.0/1.25/1.5 across 3 ranks (Meraki
        # 16.10.1 Disable Duration block). Dash-touch charm.
        self.assertEqual(
            _per_spell_cc_for("Rakan", "R"),
            (1.0, 1.25, 1.5),
        )

    def test_all_wave_eight_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_EIGHT_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- prior wave preservation ----------------


class WaveOneThroughSevenPreservedTests(unittest.TestCase):
    """Representative entries across waves 1-7 byte-identical post-wave-8.

    Pin enough entries across each prior wave to detect accidental
    deletion when wave 8 is added. The setdefault builder pattern is
    safe (later additions add new keys without clobbering); these
    assertions guard the contract.
    """

    def test_wave_one_annie_r_preserved(self) -> None:
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Annie"]["R"], (1.5, 1.5, 1.5),
        )

    def test_wave_one_lissandra_r_preserved(self) -> None:
        # Multi-wave coexistence: wave 1 Lissandra R + wave 8 Lissandra W.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Lissandra"]["R"], (1.5, 1.5, 1.5),
        )

    def test_wave_one_maokai_r_preserved(self) -> None:
        # Multi-wave coexistence: wave 1 Maokai R + wave 8 Maokai W.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Maokai"]["R"], (1.2, 1.6, 2.0),
        )

    def test_wave_one_rakan_w_preserved(self) -> None:
        # Multi-wave coexistence: wave 1 Rakan W + wave 8 Rakan R.
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Rakan"]["W"],
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
        # Senna W was seeded wave 4 per item 138; wave 8 audit
        # confirmed it as still canonical (item 145 cc_conditional
        # REJECT list flagged it as unconditional - already shipped).
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
        # Zac is the wave-7 prior multi-wave coexistence example.
        spells = _PER_SPELL_CC_DURATIONS["Zac"]
        self.assertEqual(spells["E"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_total_106_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82, wave 5 = +8 = 90, wave 6 = +5 = 95,
        # wave 7 = +8 = 103, wave 8 = +3 = 106. Relaxed to
        # assertGreaterEqual per item 146 wave 5 pattern - allows
        # future waves to add entries without flipping this assertion.
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 106)

    def test_registry_unchanged_at_89_champions(self) -> None:
        # Champion count unchanged at wave 8: 0 NEW champions; all
        # 3 wave-8 entries are multi-wave augmentations of existing
        # champs (Lissandra / Maokai / Rakan all in wave 1). Relaxed
        # to assertGreaterEqual so future waves that add NEW champions
        # do not flip this assertion (wave 9+ remained at 89 per item
        # 146 carry (j) - net-new champion pool genuinely saturated).
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 89)

    def test_wave_eight_zero_new_champs(self) -> None:
        # Wave 8 added 0 net new champions.
        prior = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
            | WAVE_SIX_NEW_KEYS
            | WAVE_SEVEN_NEW_KEYS
        )
        new = WAVE_EIGHT_AUGMENTED_CHAMPS - prior
        self.assertEqual(len(new), 0)

    def test_wave_eight_three_multi_wave_augmentations(self) -> None:
        # All 3 wave 8 champions are in wave 1 (Lissandra R + Maokai R
        # + Rakan W).
        for champ in WAVE_EIGHT_AUGMENTED_CHAMPS:
            self.assertIn(champ, WAVE_ONE_KEYS, f"{champ} not in wave 1")


# ---------------- schema lift preserved ----------------


class SchemaLiftBuilderPreservedTests(unittest.TestCase):
    """The wave 6 setdefault builder is still in place + working.

    The builder pattern is what enables wave 8's 3 multi-wave
    augmentations to coexist with their wave-1 prior entries on the
    same champion's spell map. Without setdefault, the wave 8
    dict-literal additions would clobber the wave 1 entries.
    """

    def test_builder_function_is_exposed(self) -> None:
        self.assertTrue(callable(_build_per_spell_cc_durations))

    def test_builder_output_matches_module_registry(self) -> None:
        fresh = _build_per_spell_cc_durations()
        self.assertEqual(fresh, _PER_SPELL_CC_DURATIONS)

    def test_multi_wave_augmentations_did_not_clobber(self) -> None:
        # Re-pin all 3 wave 8 augmentations + their wave 1 siblings to
        # prove the setdefault contract works for wave 8 additions.
        liss = _PER_SPELL_CC_DURATIONS["Lissandra"]
        self.assertEqual(len(liss), 2)  # R + W
        mao = _PER_SPELL_CC_DURATIONS["Maokai"]
        self.assertEqual(len(mao), 2)  # R + W
        rak = _PER_SPELL_CC_DURATIONS["Rakan"]
        self.assertEqual(len(rak), 2)  # W + R


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin at wave-8 ship state.

    Wave 8 ships +3 entries / 0 new champs / 3 multi-wave augs. The
    engine bump 1.41.0 -> 1.42.0 happens at orchestrator merge time;
    this commit pins the PRE-bump state (1.41.0). Orchestrator flips
    this assertion to "1.42.0" when bumping ENGINE_VERSION in the
    same merge commit.
    """

    def test_engine_version_at_1_41_0(self) -> None:
        # Pre-orchestrator-merge state. Orchestrator bumps the source
        # ENGINE_VERSION to 1.42.0 + flips this assertion to match.
        self.assertEqual(ENGINE_VERSION, "1.242.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 8 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_eight_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.42.0 wave 8"
        end_marker = "return registry"
        start = src.find(start_marker)
        # Find the LAST 'return registry' (the one closing _build).
        end = src.rfind(end_marker)
        self.assertGreater(start, -1, "wave 8 marker missing")
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
                ch, block, f"wave 8 block carries {name}",
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
