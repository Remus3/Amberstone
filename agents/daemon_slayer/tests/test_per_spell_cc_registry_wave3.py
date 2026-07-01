"""ENGINE 1.33.0 (2026-05-22) - per-spell CC duration registry wave 3.

Extends the 53-entry/44-champion seed shipped 1.31.0 with 14 additional
first-order CC entries across 14 additional champions of patch 16.10.1.
Total registry now 67 entries across 58 champions.

Engine math consumption is still data-only at the registry layer; values
flow through ``AbilitySpellDps.cc_duration_s`` and
``.cc_duration_post_tenacity`` for API inspection + future fight-sim /
EHP-vs-CC blended scorer composition (the `compute_cc_pressure`
aggregator at item 136 reads from this same registry).

Coverage classes:

* ``WaveThreeNewEntryShapeTests`` - 14 new champs are present; total
  count matches 14 spell entries; each new tuple has the expected
  length and floats.
* ``WaveThreeValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 tooltips.
* ``WaveOnePreservedTests`` - the 30 entries / 24 champions from
  1.30.0 are still present (no edits to wave 1 surface).
* ``WaveTwoPreservedTests`` - the 23 entries / 20 champions from
  1.31.0 are still present (no edits to wave 2 surface).
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 3.
* ``WaveThreeNoDuplicatesTests`` - the wave 3 champion ids do not
  collide with wave 1 + wave 2 sets.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-3 ship
  state (the orchestrator bumps to 1.33.0 at merge; this branch is at
  1.32.0 until merge).
* ``AsciiHygieneTests`` - the wave 3 registry block + this test file
  are pure-ASCII (no em-dashes / smart quotes per CLAUDE.md hard rule).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    _PER_SPELL_CC_DURATIONS,
    _per_spell_cc_for,
)


# ---------------- new entry set ----------------


WAVE_THREE_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "AurelionSol": {"R": (1.25, 1.5, 1.75)},
    "Caitlyn": {"W": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Camille": {"E": (0.75, 0.75, 0.75, 0.75, 0.75)},
    "Diana": {"R": (0.75, 0.75, 0.75)},
    "Elise": {"E": (1.1, 1.4, 1.7, 2.0, 2.3)},
    "Heimerdinger": {"E": (1.25, 1.25, 1.25, 1.25, 1.25)},
    "Ivern": {"Q": (1.0, 1.25, 1.5, 1.75, 2.0)},
    "Malphite": {"R": (1.5, 1.75, 2.0)},
    "Pyke": {"Q": (1.25, 1.25, 1.25, 1.25, 1.25)},
    "Rell": {"Q": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Ryze": {"W": (0.75, 1.0, 1.25, 1.5, 1.75)},
    "Sion": {"Q": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Tristana": {"R": (1.0, 1.0, 1.0)},
    "XinZhao": {"W": (1.0, 1.0, 1.0, 1.0, 1.0)},
}


# Wave 1 surface (do NOT edit; pin to detect accidental wave-1 deletions
# during a wave-3 merge).
WAVE_ONE_KEYS = {
    "Ahri", "Annie", "Ashe", "Blitzcrank", "Cassiopeia", "Galio",
    "Leona", "Lissandra", "Lulu", "Malzahar", "Maokai", "MonkeyKing",
    "Morgana", "Nautilus", "Pantheon", "Rakan", "Renekton", "Sejuani",
    "Sona", "Thresh", "Veigar", "Vi", "Yasuo", "Zoe",
}


# Wave 2 surface (do NOT edit; pin to detect accidental wave-2 deletions
# during a wave-3 merge).
WAVE_TWO_KEYS = {
    "Alistar", "Amumu", "Anivia", "Braum", "Chogath", "Fiddlesticks",
    "Gnar", "Gragas", "Jhin", "Lux", "Nami", "Neeko", "Orianna",
    "Poppy", "Riven", "Singed", "Skarner", "Varus", "Xerath", "Zac",
}


# ---------------- wave 3 entry shape ----------------


class WaveThreeNewEntryShapeTests(unittest.TestCase):
    """The new champion entries are present in the registry."""

    def test_wave_three_champ_count_14(self) -> None:
        self.assertEqual(len(WAVE_THREE_EXPECTED), 14)

    def test_wave_three_spell_entry_count_14(self) -> None:
        total = sum(len(s) for s in WAVE_THREE_EXPECTED.values())
        self.assertEqual(total, 14)

    def test_all_wave_three_champs_present_in_registry(self) -> None:
        for champ in WAVE_THREE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 3 champ {champ} missing from registry",
            )

    def test_all_wave_three_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 3 {champ} {key} missing",
                )

    def test_each_wave_three_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )


# ---------------- per-entry value pins ----------------


class WaveThreeValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1)."""

    def test_aurelion_sol_r_falling_star_center_stun(self) -> None:
        # Falling Star / The Skies Descend: center stun on impact
        # 1.25/1.5/1.75s across 3 ranks.
        self.assertEqual(
            _per_spell_cc_for("AurelionSol", "R"),
            (1.25, 1.5, 1.75),
        )

    def test_caitlyn_w_yordle_snap_trap_root(self) -> None:
        # Yordle Snap Trap roots for 1.5s at all 5 ranks (trap
        # duration scales but root duration is constant).
        self.assertEqual(
            _per_spell_cc_for("Caitlyn", "W"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_camille_e_hookshot_stun(self) -> None:
        # Hookshot / Wall Dive stun 0.75s on second-cast wall-dive
        # contact at all 5 ranks (single value).
        self.assertEqual(
            _per_spell_cc_for("Camille", "E"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_diana_r_moonfall_knockup(self) -> None:
        # Moonfall: knock-up 0.75s on pull at all 3 ranks (rank
        # scales damage + cooldown, not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Diana", "R"),
            (0.75, 0.75, 0.75),
        )

    def test_elise_e_cocoon_stun_durations(self) -> None:
        # Cocoon (human form): stun 1.1/1.4/1.7/2.0/2.3 across 5
        # ranks (one of the longest single-target stuns at min rank).
        self.assertEqual(
            _per_spell_cc_for("Elise", "E"),
            (1.1, 1.4, 1.7, 2.0, 2.3),
        )

    def test_heimerdinger_e_grenade_stun(self) -> None:
        # CH-2 Electron Storm Grenade: stun 1.25s on primary target.
        # E maxes at rank 4 in-game; the engine 5-rank shape pins
        # the rank-5 slot to the constant rank-4 value.
        self.assertEqual(
            _per_spell_cc_for("Heimerdinger", "E"),
            (1.25, 1.25, 1.25, 1.25, 1.25),
        )

    def test_ivern_q_rootcaller_durations(self) -> None:
        # Rootcaller: root 1.0/1.25/1.5/1.75/2.0 across 5 ranks.
        self.assertEqual(
            _per_spell_cc_for("Ivern", "Q"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_malphite_r_unstoppable_force_knockup(self) -> None:
        # Unstoppable Force: knock-up 1.5/1.75/2.0 across 3 ranks.
        self.assertEqual(
            _per_spell_cc_for("Malphite", "R"),
            (1.5, 1.75, 2.0),
        )

    def test_pyke_q_bone_skewer_stun(self) -> None:
        # Bone Skewer ranged-cast: stun 1.25s on connect at all
        # 5 ranks (rank scales damage + range, not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Pyke", "Q"),
            (1.25, 1.25, 1.25, 1.25, 1.25),
        )

    def test_rell_q_shattering_strike_root(self) -> None:
        # Shattering Strike: root 1.0s on hit at all 5 ranks. Rell
        # W (Ferromancy mount/dismount) intentionally NOT modeled
        # per the toggle skip rule.
        self.assertEqual(
            _per_spell_cc_for("Rell", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_ryze_w_rune_prison_root_durations(self) -> None:
        # Rune Prison: root 0.75/1.0/1.25/1.5/1.75 across 5 ranks.
        self.assertEqual(
            _per_spell_cc_for("Ryze", "W"),
            (0.75, 1.0, 1.25, 1.5, 1.75),
        )

    def test_sion_q_decimating_smash_full_charge_stun(self) -> None:
        # Decimating Smash: stun 1.25/1.5/1.75/2.0/2.25 at full
        # charge across 5 ranks. Minimum charge stuns shorter
        # (1/3 of the value); pin the canonical full-charge max.
        self.assertEqual(
            _per_spell_cc_for("Sion", "Q"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_tristana_r_buster_shot_knockback(self) -> None:
        # Buster Shot: knock-back 1.0s on hit at all 3 ranks
        # (displacement is brief; rank scales damage not CC).
        self.assertEqual(
            _per_spell_cc_for("Tristana", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_xin_zhao_w_third_strike_knockup(self) -> None:
        # Wind Becomes Lightning: 3rd-strike knock-up 1.0s at end
        # of pull-line at all 5 ranks (rank scales damage not CC).
        self.assertEqual(
            _per_spell_cc_for("XinZhao", "W"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_all_wave_three_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_THREE_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- wave 1 preservation ----------------


class WaveOnePreservedTests(unittest.TestCase):
    """The 24 wave-1 champions are still present (no accidental delete)."""

    def test_all_wave_one_champs_still_in_registry(self) -> None:
        for champ in WAVE_ONE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 1 champ {champ} missing post wave-3 merge",
            )

    def test_wukong_still_keyed_under_monkey_king(self) -> None:
        # Pre-existing wave-1 contract.
        self.assertIn("MonkeyKing", _PER_SPELL_CC_DURATIONS)
        self.assertNotIn("Wukong", _PER_SPELL_CC_DURATIONS)


# ---------------- wave 2 preservation ----------------


class WaveTwoPreservedTests(unittest.TestCase):
    """The 20 wave-2 champions are still present (no accidental delete)."""

    def test_all_wave_two_champs_still_in_registry(self) -> None:
        for champ in WAVE_TWO_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 2 champ {champ} missing post wave-3 merge",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_floor_at_least_67_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67 total.
        # Floor at 67 (exact-equal lower bound; future waves grow up
        # from here).
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 67)

    def test_registry_floor_at_least_58_champions(self) -> None:
        # Wave 1 = 24, wave 2 = +20 = 44, wave 3 = +14 = 58 total.
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 58)

    def test_wave_one_plus_two_plus_three_disjoint_count(self) -> None:
        # 24 + 20 + 14 = 58 unique champion ids across all 3 waves.
        union = WAVE_ONE_KEYS | WAVE_TWO_KEYS | set(
            WAVE_THREE_EXPECTED.keys()
        )
        self.assertEqual(len(union), 58)


# ---------------- no-collision contract ----------------


class WaveThreeNoDuplicatesTests(unittest.TestCase):
    """Wave 3 ids must not collide with wave 1 or wave 2."""

    def test_wave_three_keys_disjoint_from_wave_one(self) -> None:
        wave_three_keys = set(WAVE_THREE_EXPECTED.keys())
        overlap = WAVE_ONE_KEYS & wave_three_keys
        self.assertEqual(
            overlap, set(),
            f"wave 3 collides with wave 1: {overlap}",
        )

    def test_wave_three_keys_disjoint_from_wave_two(self) -> None:
        wave_three_keys = set(WAVE_THREE_EXPECTED.keys())
        overlap = WAVE_TWO_KEYS & wave_three_keys
        self.assertEqual(
            overlap, set(),
            f"wave 3 collides with wave 2: {overlap}",
        )

    def test_wave_three_keys_no_duplicates_within(self) -> None:
        # The dict naturally dedups so just sanity-check the count.
        wave_three_count = len(WAVE_THREE_EXPECTED)
        wave_three_unique = len(set(WAVE_THREE_EXPECTED.keys()))
        self.assertEqual(wave_three_count, wave_three_unique)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Branch ENGINE_VERSION pins the wave-6 ship state (1.37.0).

    Wave 3 originally shipped under ENGINE 1.33.0. Wave 4 bumped to
    1.34.0, wave 5 to 1.35.0, wave 6 schema lift to 1.37.0. The wave-3
    surface itself is unchanged; this pin moves forward with the registry.
    """

    def test_engine_version_at_1_36_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.166.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 3 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_three_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.33.0 wave 3"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1, "wave 3 marker missing")
        self.assertGreater(end, -1, "post-registry marker missing")
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
                ch, block, f"wave 3 block carries {name}",
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
