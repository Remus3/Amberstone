"""ENGINE 1.31.0 (2026-05-21) - per-spell CC duration registry wave 2.

Closes item 134 carry-forward (h) data-side: extends the
``_PER_SPELL_CC_DURATIONS`` registry shipped 1.30.0 with 23 additional
first-order CC entries across 20 additional champions of patch 16.10.
Total registry now 53 entries across 44 champions (was 30 / 24 at
1.30.0).

Engine math consumption is STILL FUTURE (the engine-side fight-sim
consumer that reads the registry for math is queued per item 130 / 134
carry). Today the values flow through ``AbilitySpellDps.cc_duration_s``
and ``.cc_duration_post_tenacity`` for API inspection.

Coverage classes:

* ``WaveTwoNewEntryShapeTests`` - 20 new champs are present; total
  count matches 53; each new tuple has the expected length.
* ``WaveTwoValuePinsTests`` - per-champion + per-spell exact-value pin
  from patch 16.10 tooltips.
* ``WaveOnePreservedTests`` - the 30 entries / 24 champions from
  1.30.0 are still present (no edits to wave 1 surface).
* ``WaveTwoFloorContractTests`` - lower-bound floor pin so wave 3 + N
  additions do not break the test.
* ``WaveTwoNoDuplicatesTests`` - the wave 2 champion ids do not collide
  with the wave 1 set.
* ``WaveTwoAsciiContractTests`` - the registry comments + this test
  file are pure-ASCII.
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


WAVE_TWO_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Alistar": {
        "Q": (1.0, 1.0, 1.0, 1.0, 1.0),
        "W": (0.5, 0.5, 0.5, 0.5, 0.5),
    },
    "Amumu": {
        "Q": (1.0, 1.1, 1.2, 1.3, 1.4),
        "R": (1.5, 1.75, 2.0),
    },
    "Anivia": {"Q": (1.25, 1.25, 1.25, 1.25, 1.25)},
    "Braum": {"R": (1.0, 1.0, 1.0)},
    "Chogath": {"Q": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Fiddlesticks": {"Q": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Gnar": {"R": (0.75, 0.75, 0.75)},
    "Gragas": {"E": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Jhin": {"W": (0.75, 1.0, 1.25, 1.5, 1.75)},
    "Lux": {"Q": (2.0, 2.25, 2.5, 2.75, 3.0)},
    "Nami": {"Q": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Neeko": {
        "E": (0.75, 1.0, 1.25, 1.5, 1.75),
        "R": (1.25, 1.25, 1.25),
    },
    "Orianna": {"R": (1.0, 1.0, 1.0)},
    "Poppy": {"E": (0.5, 0.5, 0.5, 0.5, 0.5)},
    "Riven": {"W": (0.75, 0.75, 0.75, 0.75, 0.75)},
    "Singed": {"E": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Skarner": {"R": (1.75, 2.0, 2.25)},
    "Varus": {"R": (2.0, 2.0, 2.0)},
    "Xerath": {"E": (1.0, 1.25, 1.5, 1.75, 2.0)},
    "Zac": {"E": (1.0, 1.0, 1.0, 1.0, 1.0)},
}


# Wave 1 surface (do NOT edit; pin to detect accidental wave-1 deletions
# during a wave-2 merge).
WAVE_ONE_KEYS = {
    "Ahri", "Annie", "Ashe", "Blitzcrank", "Cassiopeia", "Galio",
    "Leona", "Lissandra", "Lulu", "Malzahar", "Maokai", "MonkeyKing",
    "Morgana", "Nautilus", "Pantheon", "Rakan", "Renekton", "Sejuani",
    "Sona", "Thresh", "Veigar", "Vi", "Yasuo", "Zoe",
}


# ---------------- wave 2 entry shape ----------------


class WaveTwoNewEntryShapeTests(unittest.TestCase):
    """The 22 new champion entries are present in the registry."""

    def test_wave_two_champ_count_20(self) -> None:
        self.assertEqual(len(WAVE_TWO_EXPECTED), 20)

    def test_wave_two_spell_entry_count_23(self) -> None:
        total = sum(len(s) for s in WAVE_TWO_EXPECTED.values())
        self.assertEqual(total, 23)

    def test_all_wave_two_champs_present_in_registry(self) -> None:
        for champ in WAVE_TWO_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 2 champ {champ} missing from registry",
            )

    def test_all_wave_two_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 2 {champ} {key} missing",
                )

    def test_each_wave_two_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for key, tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_TWO_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )


# ---------------- per-entry value pins ----------------


class WaveTwoValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10 tooltips)."""

    def test_alistar_q_pulverize_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Alistar", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_alistar_w_headbutt_0_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Alistar", "W"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_amumu_q_bandage_toss_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Amumu", "Q"),
            (1.0, 1.1, 1.2, 1.3, 1.4),
        )

    def test_amumu_r_curse_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Amumu", "R"), (1.5, 1.75, 2.0),
        )

    def test_anivia_q_flash_frost_1_25(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Anivia", "Q"),
            (1.25, 1.25, 1.25, 1.25, 1.25),
        )

    def test_braum_r_glacial_fissure_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Braum", "R"), (1.0, 1.0, 1.0),
        )

    def test_chogath_q_rupture_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Chogath", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_fiddlesticks_q_terrify_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Fiddlesticks", "Q"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_gnar_r_knockback_0_75(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Gnar", "R"), (0.75, 0.75, 0.75),
        )

    def test_gragas_e_body_slam_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Gragas", "E"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_jhin_w_deadly_flourish_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Jhin", "W"),
            (0.75, 1.0, 1.25, 1.5, 1.75),
        )

    def test_lux_q_light_binding_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Lux", "Q"),
            (2.0, 2.25, 2.5, 2.75, 3.0),
        )

    def test_nami_q_aqua_prison_1_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Nami", "Q"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_neeko_e_tangle_barbs_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Neeko", "E"),
            (0.75, 1.0, 1.25, 1.5, 1.75),
        )

    def test_neeko_r_pop_blossom_1_25(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Neeko", "R"), (1.25, 1.25, 1.25),
        )

    def test_orianna_r_shockwave_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Orianna", "R"), (1.0, 1.0, 1.0),
        )

    def test_poppy_e_heroic_charge_base_stun_0_5(self) -> None:
        # Base 0.5s stun always fires; the 1.5s wall-stun is
        # conditional on terrain contact and intentionally NOT modeled.
        self.assertEqual(
            _per_spell_cc_for("Poppy", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_riven_w_ki_burst_0_75(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Riven", "W"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_singed_e_fling_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Singed", "E"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_skarner_r_impale_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Skarner", "R"), (1.75, 2.0, 2.25),
        )

    def test_varus_r_chain_corruption_2_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Varus", "R"), (2.0, 2.0, 2.0),
        )

    def test_xerath_e_shocking_orb_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Xerath", "E"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_zac_e_slingshot_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Zac", "E"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_all_wave_two_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_TWO_EXPECTED.items():
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
                f"wave 1 champ {champ} missing post wave-2 merge",
            )

    def test_wukong_still_keyed_under_monkey_king(self) -> None:
        # Pre-existing wave-1 contract.
        self.assertIn("MonkeyKing", _PER_SPELL_CC_DURATIONS)
        self.assertNotIn("Wukong", _PER_SPELL_CC_DURATIONS)


# ---------------- floor contract ----------------


class WaveTwoFloorContractTests(unittest.TestCase):
    """Lower-bound floor pin so future waves do not break this test."""

    def test_registry_floor_at_least_39_entries(self) -> None:
        # 39 floor (well below the 53 total at wave 2) gives 14+ entries
        # of headroom for future waves to grow without rewriting this
        # contract. Wave 1 = 30, wave 2 = +23 = 53 total today.
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 39)

    def test_registry_floor_at_least_30_champions(self) -> None:
        # 30 champ floor (below the 45 total at wave 2).
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 30)


# ---------------- no-collision contract ----------------


class WaveTwoNoDuplicatesTests(unittest.TestCase):
    """Wave 2 ids must not collide with wave 1."""

    def test_wave_two_keys_disjoint_from_wave_one(self) -> None:
        wave_two_keys = set(WAVE_TWO_EXPECTED.keys())
        overlap = WAVE_ONE_KEYS & wave_two_keys
        self.assertEqual(
            overlap, set(),
            f"wave 2 collides with wave 1: {overlap}",
        )

    def test_wave_two_keys_no_duplicates_within(self) -> None:
        # The dict naturally dedups so just sanity-check the count.
        wave_two_count = len(WAVE_TWO_EXPECTED)
        wave_two_unique = len(set(WAVE_TWO_EXPECTED.keys()))
        self.assertEqual(wave_two_count, wave_two_unique)


# ---------------- ASCII contract ----------------


class WaveTwoAsciiContractTests(unittest.TestCase):
    """The wave 2 entries + this test file are pure-ASCII."""

    def test_ability_dps_wave_two_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.31.0 wave 2"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1)
        self.assertGreater(end, -1)
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
                ch, block, f"wave 2 block carries {name}",
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


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_1_36_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.177.0")


if __name__ == "__main__":
    unittest.main()
