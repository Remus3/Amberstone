"""ENGINE 1.34.0 (2026-05-22) - per-spell CC duration registry wave 4.

Extends the 67-entry / 58-champion registry shipped 1.33.0 with 15
additional first-order CC entries across 15 additional champions of
patch 16.10.1. Total registry now 82 entries across 73 champions.

Engine math consumption is still data-only at the registry layer; values
flow through ``AbilitySpellDps.cc_duration_s`` and
``.cc_duration_post_tenacity`` for API inspection + the cc_pressure
aggregator (item 136 Slice A) + the EHP-vs-CC blended scorer (item 137
Slice A) read from this same registry.

Coverage classes:

* ``WaveFourNewEntryShapeTests`` - 15 new champs are present; total
  count matches 15 spell entries; each new tuple has the expected
  length and floats.
* ``WaveFourValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 tooltips and the canonical
  ``champion_abilities.json`` Disable/Stun/Root/Fear/Taunt duration
  blocks where present.
* ``WaveOnePreservedTests`` - the 30 entries / 24 champions from
  1.30.0 are still present.
* ``WaveTwoPreservedTests`` - the 23 entries / 20 champions from
  1.31.0 are still present.
* ``WaveThreePreservedTests`` - the 14 entries / 14 champions from
  1.33.0 are still present.
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 4.
* ``WaveFourNoDuplicatesTests`` - the wave 4 champion ids do not
  collide with wave 1 + wave 2 + wave 3 sets.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-4 ship
  state (1.34.0).
* ``AsciiHygieneTests`` - the wave 4 registry block + this test file
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


WAVE_FOUR_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Draven": {"E": (0.5, 0.5, 0.5, 0.5, 0.5)},
    "Ekko": {"W": (2.25, 2.25, 2.25, 2.25, 2.25)},
    "Janna": {"Q": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Jax": {"E": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Jinx": {"E": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Mel": {"E": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Nocturne": {"E": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Quinn": {"E": (0.75, 0.75, 0.75, 0.75, 0.75)},
    "Rammus": {"E": (1.2, 1.4, 1.6, 1.8, 2.0)},
    "Senna": {"W": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Seraphine": {"R": (1.25, 1.5, 1.75)},
    "Shaco": {"W": (0.5, 0.75, 1.0, 1.25, 1.5)},
    "Shen": {"E": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Soraka": {"E": (1.0, 1.25, 1.5, 1.75, 2.0)},
    "Zyra": {"E": (1.0, 1.25, 1.5, 1.75, 2.0)},
}


# Wave 1 surface (do NOT edit; pin to detect accidental wave-1 deletions
# during a wave-4 merge).
WAVE_ONE_KEYS = {
    "Ahri", "Annie", "Ashe", "Blitzcrank", "Cassiopeia", "Galio",
    "Leona", "Lissandra", "Lulu", "Malzahar", "Maokai", "MonkeyKing",
    "Morgana", "Nautilus", "Pantheon", "Rakan", "Renekton", "Sejuani",
    "Sona", "Thresh", "Veigar", "Vi", "Yasuo", "Zoe",
}


# Wave 2 surface (do NOT edit; pin to detect accidental wave-2 deletions
# during a wave-4 merge).
WAVE_TWO_KEYS = {
    "Alistar", "Amumu", "Anivia", "Braum", "Chogath", "Fiddlesticks",
    "Gnar", "Gragas", "Jhin", "Lux", "Nami", "Neeko", "Orianna",
    "Poppy", "Riven", "Singed", "Skarner", "Varus", "Xerath", "Zac",
}


# Wave 3 surface (do NOT edit; pin to detect accidental wave-3 deletions
# during a wave-4 merge).
WAVE_THREE_KEYS = {
    "AurelionSol", "Caitlyn", "Camille", "Diana", "Elise",
    "Heimerdinger", "Ivern", "Malphite", "Pyke", "Rell", "Ryze",
    "Sion", "Tristana", "XinZhao",
}


# ---------------- wave 4 entry shape ----------------


class WaveFourNewEntryShapeTests(unittest.TestCase):
    """The new champion entries are present in the registry."""

    def test_wave_four_champ_count_15(self) -> None:
        self.assertEqual(len(WAVE_FOUR_EXPECTED), 15)

    def test_wave_four_spell_entry_count_15(self) -> None:
        total = sum(len(s) for s in WAVE_FOUR_EXPECTED.values())
        self.assertEqual(total, 15)

    def test_all_wave_four_champs_present_in_registry(self) -> None:
        for champ in WAVE_FOUR_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 4 champ {champ} missing from registry",
            )

    def test_all_wave_four_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 4 {champ} {key} missing",
                )

    def test_each_wave_four_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_FOUR_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )


# ---------------- per-entry value pins ----------------


class WaveFourValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1)."""

    def test_draven_e_stand_aside_knockback(self) -> None:
        # Stand Aside knockback 0.5s on contact at all 5 ranks (brief
        # displacement; rank scales damage + slow magnitude, not CC).
        self.assertEqual(
            _per_spell_cc_for("Draven", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_ekko_w_parallel_convergence_stun(self) -> None:
        # Parallel Convergence: stun 2.25s on enemies inside the
        # anomaly at expiry (single value across 5 ranks; rank
        # scales shield strength + slow magnitude, not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Ekko", "W"),
            (2.25, 2.25, 2.25, 2.25, 2.25),
        )

    def test_janna_q_howling_gale_knockup(self) -> None:
        # Howling Gale: knock-up 1.0s at full charge (single value
        # across 5 ranks; rank scales damage, the knock-up duration
        # scales with the tornado's charge time NOT with rank).
        self.assertEqual(
            _per_spell_cc_for("Janna", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_jax_e_counter_strike_stun(self) -> None:
        # Counter Strike AOE stun 1.0s on counterattack at all 5
        # ranks (rank scales damage not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Jax", "E"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_jinx_e_flame_chompers_root(self) -> None:
        # Flame Chompers root 1.5s on triggered chomper at all 5
        # ranks (rank scales damage + cooldown).
        self.assertEqual(
            _per_spell_cc_for("Jinx", "E"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_mel_e_solar_snare_root(self) -> None:
        # Solar Snare orb root 1.25/1.5/1.75/2.0/2.25 across 5 ranks
        # (canonical Orb Root Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Mel", "E"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_nocturne_e_unspeakable_horror_fear(self) -> None:
        # Unspeakable Horror fear 1.25/1.5/1.75/2.0/2.25 across 5
        # ranks (canonical Disable Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Nocturne", "E"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_quinn_e_vault_knockback(self) -> None:
        # Vault knockback 0.75s on dash hit at all 5 ranks (brief
        # displacement; rank scales damage not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Quinn", "E"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_rammus_e_frenzying_taunt(self) -> None:
        # Frenzying Taunt 1.2/1.4/1.6/1.8/2.0 across 5 ranks
        # (canonical Taunt Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Rammus", "E"),
            (1.2, 1.4, 1.6, 1.8, 2.0),
        )

    def test_senna_w_last_embrace_root(self) -> None:
        # Last Embrace root 1.25/1.5/1.75/2.0/2.25 across 5 ranks
        # (canonical Root Duration block from data; delayed root
        # mirrors the Nautilus Q + Caitlyn W expiry-trigger
        # universal-timer pattern).
        self.assertEqual(
            _per_spell_cc_for("Senna", "W"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_seraphine_r_encore_stun(self) -> None:
        # Encore primary AOE stun 1.25/1.5/1.75 across 3 ranks
        # (canonical Disable Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Seraphine", "R"),
            (1.25, 1.5, 1.75),
        )

    def test_shaco_w_jack_in_the_box_fear(self) -> None:
        # Jack in the Box fear 0.5/0.75/1.0/1.25/1.5 on box trigger
        # across 5 ranks (canonical Fear Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Shaco", "W"),
            (0.5, 0.75, 1.0, 1.25, 1.5),
        )

    def test_shen_e_shadow_dash_taunt(self) -> None:
        # Shadow Dash taunt 1.5s on dash hit at all 5 ranks
        # (canonical post-rework value; rank scales damage + energy
        # restore, not CC duration; cdragon description "dashing
        # in a direction, taunting enemies in his path").
        self.assertEqual(
            _per_spell_cc_for("Shen", "E"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_soraka_e_equinox_root(self) -> None:
        # Equinox root 1.0/1.25/1.5/1.75/2.0 on zone expiry across
        # 5 ranks (canonical Root Duration block from data; universal
        # zone-expiry pattern mirroring Ekko W).
        self.assertEqual(
            _per_spell_cc_for("Soraka", "E"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_zyra_e_grasping_roots(self) -> None:
        # Grasping Roots line root 1.0/1.25/1.5/1.75/2.0 across 5
        # ranks (canonical Root Duration block from data).
        self.assertEqual(
            _per_spell_cc_for("Zyra", "E"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_all_wave_four_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_FOUR_EXPECTED.items():
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
                f"wave 1 champ {champ} missing post wave-4 merge",
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
                f"wave 2 champ {champ} missing post wave-4 merge",
            )


# ---------------- wave 3 preservation ----------------


class WaveThreePreservedTests(unittest.TestCase):
    """The 14 wave-3 champions are still present (no accidental delete)."""

    def test_all_wave_three_champs_still_in_registry(self) -> None:
        for champ in WAVE_THREE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 3 champ {champ} missing post wave-4 merge",
            )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_floor_at_least_82_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82 total.
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 82)

    def test_registry_floor_at_least_73_champions(self) -> None:
        # Wave 1 = 24, wave 2 = +20 = 44, wave 3 = +14 = 58,
        # wave 4 = +15 = 73 total.
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 73)

    def test_wave_one_plus_two_plus_three_plus_four_disjoint_count(
        self,
    ) -> None:
        # 24 + 20 + 14 + 15 = 73 unique champion ids across all 4 waves.
        union = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | set(WAVE_FOUR_EXPECTED.keys())
        )
        self.assertEqual(len(union), 73)


# ---------------- no-collision contract ----------------


class WaveFourNoDuplicatesTests(unittest.TestCase):
    """Wave 4 ids must not collide with wave 1, wave 2, or wave 3."""

    def test_wave_four_keys_disjoint_from_wave_one(self) -> None:
        wave_four_keys = set(WAVE_FOUR_EXPECTED.keys())
        overlap = WAVE_ONE_KEYS & wave_four_keys
        self.assertEqual(
            overlap, set(),
            f"wave 4 collides with wave 1: {overlap}",
        )

    def test_wave_four_keys_disjoint_from_wave_two(self) -> None:
        wave_four_keys = set(WAVE_FOUR_EXPECTED.keys())
        overlap = WAVE_TWO_KEYS & wave_four_keys
        self.assertEqual(
            overlap, set(),
            f"wave 4 collides with wave 2: {overlap}",
        )

    def test_wave_four_keys_disjoint_from_wave_three(self) -> None:
        wave_four_keys = set(WAVE_FOUR_EXPECTED.keys())
        overlap = WAVE_THREE_KEYS & wave_four_keys
        self.assertEqual(
            overlap, set(),
            f"wave 4 collides with wave 3: {overlap}",
        )

    def test_wave_four_keys_no_duplicates_within(self) -> None:
        wave_four_count = len(WAVE_FOUR_EXPECTED)
        wave_four_unique = len(set(WAVE_FOUR_EXPECTED.keys()))
        self.assertEqual(wave_four_count, wave_four_unique)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin at wave-6 ship state (1.37.0).

    Wave 4 originally shipped under ENGINE 1.34.0. Wave 5 bumped to
    1.35.0, wave 6 schema lift to 1.37.0. The wave-4 surface itself
    is unchanged; this pin moves forward with the registry.
    """

    def test_engine_version_at_1_36_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.100.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 4 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_four_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.34.0 wave 4"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1, "wave 4 marker missing")
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
                ch, block, f"wave 4 block carries {name}",
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
