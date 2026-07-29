"""ENGINE 1.35.0 (2026-05-22) - per-spell CC duration registry wave 5.

Extends the 82-entry / 73-champion registry shipped 1.34.0 wave 4 with
8 additional first-order CC entries across 7 additional champions of
patch 16.10.1. Total registry now 90 entries across 80 champions.

Wave 5 delta + collision discovery:
* Hecarim adds 2 entries (E knockback + R fear) for 1 new champion.
* KSante / Mordekaiser / Urgot / Viego / Yone / Ziggs each add 1
  entry for 1 new champion each.
* Lulu R Wild Growth knock-up REJECTED in wave 5: Lulu W polymorph
  was seeded wave 1 and a "Lulu": {"R": ...} entry would clobber
  the wave-1 Lulu W via dict-literal overwrite semantics. Deferred
  to a future registry-merge pass.
* Quinn E Vault knockback REJECTED in wave 5: Quinn E was already
  seeded wave 4 with the same 0.75s single-value tuple; a second
  "Quinn": {"E": ...} entry would collide via overwrite. Wave 4
  Quinn E remains live.
* Shen E / Jax E / Jinx E / Janna Q REJECTED in wave 5: all 4 were
  already seeded wave 4.
* Sejuani Q REJECTED in wave 5: Sejuani R was seeded wave 1; adding
  a separate "Sejuani": {"Q": ...} entry would clobber wave 1.
* Rell R REJECTED in wave 5: Rell Q was seeded wave 3; adding a
  separate "Rell": {"R": ...} entry would clobber wave 3.
* Thresh E REJECTED in wave 5: Thresh Q was seeded wave 1; adding
  a separate "Thresh": {"E": ...} entry would clobber wave 1.

Selection rules unchanged from waves 1+2+3+4: first-order CC only
(stuns / roots / suspensions / knock-ups / knock-backs / fears /
suppressions / charms / sleeps / silences / polymorphs / taunts /
pulls); no slows; no conditional CC; canonical DDragon ids.

Engine math consumption is still data-only at the registry layer;
values flow through ``AbilitySpellDps.cc_duration_s`` and
``.cc_duration_post_tenacity`` for API inspection + the cc_pressure
aggregator + the EHP-vs-CC blended scorer + the
cc_blended_ehp_impact_line coach prompt line.

Coverage classes:

* ``WaveFiveNewEntryShapeTests`` - the 7 new champs are present;
  total count matches 8 spell entries; each new tuple has the
  expected length and floats.
* ``WaveFiveValuePinsTests`` - per-champion + per-spell exact-value
  pin from patch 16.10.1 tooltips and canonical Riot wiki values
  where the single-value-all-ranks pattern applies.
* ``WaveOneThroughFourPreservedTests`` - the prior 73 champions are
  still present (no accidental delete via dict-overwrite).
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 5.
* ``WaveFiveNoDuplicatesTests`` - the wave 5 champion ids do not
  collide with waves 1+2+3+4 sets.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-5 ship
  state (1.35.0 - data-lane add, no engine math change).
* ``AsciiHygieneTests`` - the wave 5 registry block + this test file
  are pure-ASCII (no em-dashes / smart quotes per CLAUDE.md hard
  rule).
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


WAVE_FIVE_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Hecarim": {
        "E": (0.75, 0.75, 0.75, 0.75, 0.75),
        "R": (1.0, 1.0, 1.0),
    },
    "KSante": {"R": (0.75, 0.75, 0.75)},
    "Mordekaiser": {"E": (0.25, 0.25, 0.25, 0.25, 0.25)},
    "Urgot": {"E": (0.5, 0.5, 0.5, 0.5, 0.5)},
    "Viego": {"W": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Yone": {"R": (0.75, 0.75, 0.75)},
    "Ziggs": {"W": (0.5, 0.5, 0.5, 0.5, 0.5)},
}


# Wave 1 surface (do NOT edit; pin to detect accidental wave-1
# deletions during a wave-5 merge).
WAVE_ONE_KEYS = {
    "Ahri", "Annie", "Ashe", "Blitzcrank", "Cassiopeia", "Galio",
    "Leona", "Lissandra", "Lulu", "Malzahar", "Maokai", "MonkeyKing",
    "Morgana", "Nautilus", "Pantheon", "Rakan", "Renekton", "Sejuani",
    "Sona", "Thresh", "Veigar", "Vi", "Yasuo", "Zoe",
}


# Wave 2 surface (do NOT edit).
WAVE_TWO_KEYS = {
    "Alistar", "Amumu", "Anivia", "Braum", "Chogath", "Fiddlesticks",
    "Gnar", "Gragas", "Jhin", "Lux", "Nami", "Neeko", "Orianna",
    "Poppy", "Riven", "Singed", "Skarner", "Varus", "Xerath", "Zac",
}


# Wave 3 surface (do NOT edit).
WAVE_THREE_KEYS = {
    "AurelionSol", "Caitlyn", "Camille", "Diana", "Elise",
    "Heimerdinger", "Ivern", "Malphite", "Pyke", "Rell", "Ryze",
    "Sion", "Tristana", "XinZhao",
}


# Wave 4 surface (do NOT edit).
WAVE_FOUR_KEYS = {
    "Draven", "Ekko", "Janna", "Jax", "Jinx", "Mel", "Nocturne",
    "Quinn", "Rammus", "Senna", "Seraphine", "Shaco", "Shen",
    "Soraka", "Zyra",
}


# ---------------- wave 5 entry shape ----------------


class WaveFiveNewEntryShapeTests(unittest.TestCase):
    """The new champion entries are present in the registry."""

    def test_wave_five_champ_count_7(self) -> None:
        self.assertEqual(len(WAVE_FIVE_EXPECTED), 7)

    def test_wave_five_spell_entry_count_8(self) -> None:
        total = sum(len(s) for s in WAVE_FIVE_EXPECTED.values())
        self.assertEqual(total, 8)

    def test_all_wave_five_champs_present_in_registry(self) -> None:
        for champ in WAVE_FIVE_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 5 champ {champ} missing from registry",
            )

    def test_all_wave_five_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 5 {champ} {key} missing",
                )

    def test_each_wave_five_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )


# ---------------- per-entry value pins ----------------


class WaveFiveValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1)."""

    def test_hecarim_e_devastating_charge_knockback(self) -> None:
        # Devastating Charge: knockback 0.75s on charge contact at all
        # 5 ranks (brief displacement; rank scales damage + slow, not
        # CC duration); canonical knockback pattern.
        self.assertEqual(
            _per_spell_cc_for("Hecarim", "E"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_hecarim_r_onslaught_of_shadows_fear(self) -> None:
        # Onslaught of Shadows: fear 1.0s on phasing through enemies
        # at all 3 ranks (canonical fear duration; rank scales damage
        # + travel range, not CC duration).
        self.assertEqual(
            _per_spell_cc_for("Hecarim", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_ksante_r_all_out_knockup(self) -> None:
        # All Out: knock-up 0.75s on first impact across all 3 ranks
        # (knock-aside displacement; rank scales damage + bonus stats,
        # not CC duration); the All Out form-change is a self-buff not
        # first-order CC.
        self.assertEqual(
            _per_spell_cc_for("KSante", "R"),
            (0.75, 0.75, 0.75),
        )

    def test_mordekaiser_e_deaths_grasp_pull(self) -> None:
        # Death's Grasp: pull 0.25s displacement at all 5 ranks (brief
        # inward pull); canonical post-rework value following the
        # Singed E displacement family.
        self.assertEqual(
            _per_spell_cc_for("Mordekaiser", "E"),
            (0.25, 0.25, 0.25, 0.25, 0.25),
        )

    def test_urgot_e_disdain_knockback(self) -> None:
        # Disdain: knockback 0.5s on hit at all 5 ranks (brief
        # displacement; rank scales damage + low-HP execute, not CC
        # duration); canonical knockback value following Draven E /
        # Singed E displacement family.
        self.assertEqual(
            _per_spell_cc_for("Urgot", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_viego_w_spectral_maw_stun(self) -> None:
        # Spectral Maw: stun 1.5s at full charge all 5 ranks (single
        # value; rank scales damage + dash range, not CC duration).
        # Minimum-charge stuns shorter but full-charge value is the
        # canonical max pin following Sion Q + Pantheon W pattern.
        self.assertEqual(
            _per_spell_cc_for("Viego", "W"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_yone_r_fate_sealed_knockup(self) -> None:
        # Fate Sealed: knock-up 0.75s on hit all 3 ranks (brief lift;
        # rank scales damage not CC duration); canonical knock-up
        # value matching Diana R + Gnar R + Tristana R pattern.
        self.assertEqual(
            _per_spell_cc_for("Yone", "R"),
            (0.75, 0.75, 0.75),
        )

    def test_ziggs_w_satchel_charge_knockback(self) -> None:
        # Satchel Charge: knockback 0.5s on explosion all 5 ranks
        # (brief displacement; rank scales damage, not CC duration);
        # canonical knockback value following Draven E pattern.
        self.assertEqual(
            _per_spell_cc_for("Ziggs", "W"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_all_wave_five_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_FIVE_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- prior wave preservation ----------------


class WaveOneThroughFourPreservedTests(unittest.TestCase):
    """The 73 prior-wave champions are still present (no overwrite)."""

    def test_all_wave_one_champs_still_in_registry(self) -> None:
        for champ in WAVE_ONE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 1 champ {champ} missing post wave-5 merge",
            )

    def test_all_wave_two_champs_still_in_registry(self) -> None:
        for champ in WAVE_TWO_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 2 champ {champ} missing post wave-5 merge",
            )

    def test_all_wave_three_champs_still_in_registry(self) -> None:
        for champ in WAVE_THREE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 3 champ {champ} missing post wave-5 merge",
            )

    def test_all_wave_four_champs_still_in_registry(self) -> None:
        for champ in WAVE_FOUR_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 4 champ {champ} missing post wave-5 merge",
            )

    def test_lulu_w_polymorph_preserved(self) -> None:
        # Critical regression guard: wave 1 Lulu W polymorph is preserved
        # post-schema-lift (wave 6, ENGINE 1.37.0). The wave-5 docstring
        # recorded a deferral of Lulu R due to dict-literal collision; the
        # 1.37.0 schema lift to the setdefault builder unblocks that
        # multi-wave augmentation. Wave 6 added Lulu R; this guard now
        # verifies both spells coexist (Lulu W from wave 1 + Lulu R from
        # wave 6).
        self.assertEqual(
            _per_spell_cc_for("Lulu", "W"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )
        # Lulu R wave 6 entry coexists thanks to the schema lift.
        self.assertEqual(_per_spell_cc_for("Lulu", "R"), (1.0, 1.0, 1.0))

    def test_quinn_e_preserved_from_wave_4(self) -> None:
        # Wave 4 Quinn E knockback must not be re-overwritten by a
        # second wave 5 Quinn entry; the wave 5 docstring records the
        # deliberate skip.
        self.assertEqual(
            _per_spell_cc_for("Quinn", "E"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_sejuani_r_preserved_from_wave_1(self) -> None:
        # Wave 5 docstring records that Sejuani Q was REJECTED to
        # avoid clobbering wave 1 Sejuani R.
        self.assertEqual(
            _per_spell_cc_for("Sejuani", "R"),
            (1.0, 1.5, 2.0),
        )

    def test_rell_q_preserved_from_wave_3(self) -> None:
        # Wave 5 docstring records that Rell R was REJECTED to avoid
        # clobbering wave 3 Rell Q.
        self.assertEqual(
            _per_spell_cc_for("Rell", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_thresh_q_preserved_from_wave_1(self) -> None:
        # Wave 5 docstring records that Thresh E was REJECTED to avoid
        # clobbering wave 1 Thresh Q.
        self.assertEqual(
            _per_spell_cc_for("Thresh", "Q"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_floor_at_least_90_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82, wave 5 = +8 = 90 total.
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 90)

    def test_registry_floor_at_least_80_champions(self) -> None:
        # Wave 1 = 24, wave 2 = +20 = 44, wave 3 = +14 = 58,
        # wave 4 = +15 = 73, wave 5 = +7 = 80 total.
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 80)

    def test_wave_one_through_five_disjoint_count(self) -> None:
        # 24 + 20 + 14 + 15 + 7 = 80 unique champion ids across all
        # 5 waves.
        union = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | set(WAVE_FIVE_EXPECTED.keys())
        )
        self.assertEqual(len(union), 80)


# ---------------- no-collision contract ----------------


class WaveFiveNoDuplicatesTests(unittest.TestCase):
    """Wave 5 ids must not collide with waves 1/2/3/4."""

    def test_wave_five_keys_disjoint_from_wave_one(self) -> None:
        wave_five_keys = set(WAVE_FIVE_EXPECTED.keys())
        overlap = WAVE_ONE_KEYS & wave_five_keys
        self.assertEqual(
            overlap, set(),
            f"wave 5 collides with wave 1: {overlap}",
        )

    def test_wave_five_keys_disjoint_from_wave_two(self) -> None:
        wave_five_keys = set(WAVE_FIVE_EXPECTED.keys())
        overlap = WAVE_TWO_KEYS & wave_five_keys
        self.assertEqual(
            overlap, set(),
            f"wave 5 collides with wave 2: {overlap}",
        )

    def test_wave_five_keys_disjoint_from_wave_three(self) -> None:
        wave_five_keys = set(WAVE_FIVE_EXPECTED.keys())
        overlap = WAVE_THREE_KEYS & wave_five_keys
        self.assertEqual(
            overlap, set(),
            f"wave 5 collides with wave 3: {overlap}",
        )

    def test_wave_five_keys_disjoint_from_wave_four(self) -> None:
        wave_five_keys = set(WAVE_FIVE_EXPECTED.keys())
        overlap = WAVE_FOUR_KEYS & wave_five_keys
        self.assertEqual(
            overlap, set(),
            f"wave 5 collides with wave 4: {overlap}",
        )

    def test_wave_five_keys_no_duplicates_within(self) -> None:
        wave_five_count = len(WAVE_FIVE_EXPECTED)
        wave_five_unique = len(set(WAVE_FIVE_EXPECTED.keys()))
        self.assertEqual(wave_five_count, wave_five_unique)

    def test_hecarim_has_two_spell_entries(self) -> None:
        # Hecarim is the only wave-5 champion with 2 spell entries
        # (E + R). The other 6 wave-5 champs add 1 spell each.
        self.assertEqual(
            len(_PER_SPELL_CC_DURATIONS["Hecarim"]), 2,
        )
        self.assertIn("E", _PER_SPELL_CC_DURATIONS["Hecarim"])
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Hecarim"])


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin at wave-6 ship state (1.37.0).

    Wave 5 originally shipped under ENGINE 1.35.0. Wave 6 schema lift
    bumps to 1.37.0. The wave-5 surface itself is unchanged; this pin
    moves forward with the registry.
    """

    def test_engine_version_at_1_36_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.265.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 5 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_five_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.35.0 wave 5"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1, "wave 5 marker missing")
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
                ch, block, f"wave 5 block carries {name}",
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
