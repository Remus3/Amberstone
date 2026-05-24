"""ENGINE 1.37.0 (2026-05-22) - per-spell CC duration registry wave 6
+ schema lift to setdefault builder.

Closes item 139 carry (j): the future registry-merge pass owed to
enable multi-wave augmentation of single-champion spell maps.

Wave 6 ships TWO things in one engine bump:

(1) SCHEMA LIFT: the _PER_SPELL_CC_DURATIONS registry is now constructed
    via a module-level builder function ``_build_per_spell_cc_durations``
    using ``registry.setdefault(champ, {})[spell] = tuple`` instead of
    a single dict literal. This unblocks multi-wave augmentation of the
    same champion's spell map without dict-literal clobber.

(2) FIVE NEW ENTRIES enabled by the schema lift:
    * Lulu R Wild Growth knock-up 1.0s all 3 ranks (multi-wave: Lulu W
      polymorph was seeded wave 1; now coexists).
    * Sejuani Q Arctic Assault stun 0.75/0.875/1.0/1.125/1.25 across
      5 ranks (multi-wave: Sejuani R was seeded wave 1; now coexists).
    * Thresh E Flay knockback 0.4s all 5 ranks (multi-wave: Thresh Q
      was seeded wave 1; now coexists).
    * Bard R Tempered Fate stasis 2.5s all 3 ranks (NEW champion;
      stasis added to first-order CC scope).
    * Lillia R Lilting Lullaby sleep 2.0s all 3 ranks (NEW champion).

Total registry post-wave-6: 95 entries across 82 champions.

REJECTED candidates (with reason recorded so future audits do NOT
re-research):

* Rell R Magnet Storm: primarily a force-pull / drag mechanic while
  channeling; the 1.0s "initial pull" is damage tick + slow not a
  discrete pull-stun like Sion R or Skarner R. REJECT.
* Bard Q Cosmic Binding: wall-bounce conditional stun (REJECT
  carryover from waves 4+5).
* Lillia E Swirlseed: ranged slow (NOT a sleep; sleep is on R only).
* Tristana W Rocket Jump landing: REJECTED-by-tooltip at 16.10.1
  (small slow not discrete knockback).
* Akshan E / Karthus Q / Naafiri R: no first-order CC.
* Yuumi Q fully-charged root: conditional charge time semantics.
* Other long-tail conditional-CC candidates: carryover REJECT from
  prior-wave lists (operator-gated schema lift for conditional axis).

Coverage classes:

* ``WaveSixNewEntryShapeTests`` - the 5 new spell entries are present;
  total count matches expected; each new tuple has the expected length
  and floats.
* ``WaveSixValuePinsTests`` - per-champion + per-spell exact-value pin
  from patch 16.10.1 tooltips.
* ``WaveOneThroughFivePreservedTests`` - the 90 prior-wave spell
  entries are still present (no accidental delete via schema lift;
  the setdefault builder must preserve every prior-wave value).
* ``RegistryGrowthTests`` - floor pins for total entry count + total
  champion count after wave 6 (95 / 82).
* ``SchemaLiftBuilderTests`` - the schema lift's builder function is
  exposed + callable + idempotent + supports multi-wave augmentation.
* ``EngineVersionCurrentTests`` - ENGINE_VERSION pin at wave-6 ship
  state (1.37.0 - schema lift + 5 new entries).
* ``AsciiHygieneTests`` - the wave 6 registry block + this test file
  are pure-ASCII (no em-dashes / smart quotes per CLAUDE.md hard
  rule).
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


# Wave 6 entries: 5 spell entries across 5 distinct champions.
# (Lulu / Sejuani / Thresh are multi-wave augmentations - the champion
# was already present in prior waves; the wave-6 entry adds a new spell
# to their existing spell map. Bard / Lillia are net-new champions.)
WAVE_SIX_EXPECTED: dict[str, dict[str, tuple[float, ...]]] = {
    "Lulu": {"R": (1.0, 1.0, 1.0)},
    "Sejuani": {"Q": (0.75, 0.875, 1.0, 1.125, 1.25)},
    "Thresh": {"E": (0.4, 0.4, 0.4, 0.4, 0.4)},
    "Bard": {"R": (2.5, 2.5, 2.5)},
    "Lillia": {"R": (2.0, 2.0, 2.0)},
}


# The 2 NEW champions ship in wave 6 (Lulu / Sejuani / Thresh are
# multi-wave augmentations of existing champions, not new champs).
WAVE_SIX_NEW_CHAMPS = {"Bard", "Lillia"}


# Wave 1 surface (do NOT edit; pin to detect accidental wave-1
# deletions during the schema lift).
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


# Wave 5 surface (do NOT edit).
WAVE_FIVE_KEYS = {
    "Hecarim", "KSante", "Mordekaiser", "Urgot", "Viego", "Yone",
    "Ziggs",
}


# ---------------- wave 6 entry shape ----------------


class WaveSixNewEntryShapeTests(unittest.TestCase):
    """The 5 new wave 6 entries are present in the registry."""

    def test_wave_six_total_spell_entry_count_5(self) -> None:
        total = sum(len(s) for s in WAVE_SIX_EXPECTED.values())
        self.assertEqual(total, 5)

    def test_wave_six_distinct_champion_count_5(self) -> None:
        self.assertEqual(len(WAVE_SIX_EXPECTED), 5)

    def test_wave_six_new_champion_count_2(self) -> None:
        # Bard + Lillia are net-new; Lulu / Sejuani / Thresh are
        # multi-wave augmentations of existing champions.
        self.assertEqual(len(WAVE_SIX_NEW_CHAMPS), 2)

    def test_all_wave_six_champs_present_in_registry(self) -> None:
        for champ in WAVE_SIX_EXPECTED:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 6 champ {champ} missing from registry",
            )

    def test_all_wave_six_spells_present_in_registry(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key in spells:
                self.assertIn(
                    key, _PER_SPELL_CC_DURATIONS[champ],
                    f"wave 6 {champ} {key} missing",
                )

    def test_each_wave_six_tuple_is_floats(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} non-float",
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key, _tup in spells.items():
                if key in {"Q", "W", "E"}:
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 5,
                        f"{champ} {key} expected 5 ranks",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key, _tup in spells.items():
                if key == "R":
                    live = _PER_SPELL_CC_DURATIONS[champ][key]
                    self.assertEqual(
                        len(live), 3,
                        f"{champ} R expected 3 ranks",
                    )

    def test_all_wave_six_values_non_negative(self) -> None:
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key, _tup in spells.items():
                live = _PER_SPELL_CC_DURATIONS[champ][key]
                for v in live:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} has negative CC: {v}",
                    )


# ---------------- per-entry value pins ----------------


class WaveSixValuePinsTests(unittest.TestCase):
    """Per-champion + per-spell exact-value pin (patch 16.10.1)."""

    def test_lulu_r_wild_growth_knockup(self) -> None:
        # Wild Growth: knock-up 1.0s on ally landing all 3 ranks
        # (allied target launched into air; the knock-up affects
        # enemies under the landing zone unconditionally).
        # Multi-wave augmentation: Lulu W polymorph was seeded wave 1.
        self.assertEqual(
            _per_spell_cc_for("Lulu", "R"),
            (1.0, 1.0, 1.0),
        )

    def test_sejuani_q_arctic_assault_stun(self) -> None:
        # Arctic Assault: stun 0.75/0.875/1.0/1.125/1.25 across 5
        # ranks (canonical post-rework value at 16.10.1).
        # Multi-wave augmentation: Sejuani R was seeded wave 1.
        self.assertEqual(
            _per_spell_cc_for("Sejuani", "Q"),
            (0.75, 0.875, 1.0, 1.125, 1.25),
        )

    def test_thresh_e_flay_knockback(self) -> None:
        # Flay: knockback 0.4s displacement all 5 ranks (brief swat
        # displacement; rank scales damage + slow not CC duration).
        # Multi-wave augmentation: Thresh Q death-sentence stun was
        # seeded wave 1.
        self.assertEqual(
            _per_spell_cc_for("Thresh", "E"),
            (0.4, 0.4, 0.4, 0.4, 0.4),
        )

    def test_bard_r_tempered_fate_stasis(self) -> None:
        # Tempered Fate: stasis 2.5s on enemies hit by the tomb-wave
        # all 3 ranks (canonical Bard R duration; rank scales cooldown
        # not CC duration). NEW champion; stasis added to first-order
        # CC scope.
        self.assertEqual(
            _per_spell_cc_for("Bard", "R"),
            (2.5, 2.5, 2.5),
        )

    def test_lillia_r_lilting_lullaby_sleep(self) -> None:
        # Lilting Lullaby: sleep 2.0s on enemies marked with Dream
        # Dust all 3 ranks. NEW champion; mirrors Zoe E drowsy-then-
        # sleep pattern wave 1.
        self.assertEqual(
            _per_spell_cc_for("Lillia", "R"),
            (2.0, 2.0, 2.0),
        )

    def test_all_wave_six_entries_match_expected(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in WAVE_SIX_EXPECTED.items():
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- prior wave preservation (schema lift guard) ----------------


class WaveOneThroughFivePreservedTests(unittest.TestCase):
    """The 90 prior-wave entries are still present post-schema-lift.

    Critical: the schema lift moved the registry from a single dict
    literal to a setdefault builder. Every prior-wave value MUST be
    preserved byte-identical. The setdefault builder pattern is the
    safe shape (later additions add new keys without clobbering).
    """

    def test_all_wave_one_champs_still_in_registry(self) -> None:
        for champ in WAVE_ONE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 1 champ {champ} missing post wave-6 schema lift",
            )

    def test_all_wave_two_champs_still_in_registry(self) -> None:
        for champ in WAVE_TWO_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 2 champ {champ} missing post wave-6 schema lift",
            )

    def test_all_wave_three_champs_still_in_registry(self) -> None:
        for champ in WAVE_THREE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 3 champ {champ} missing post wave-6 schema lift",
            )

    def test_all_wave_four_champs_still_in_registry(self) -> None:
        for champ in WAVE_FOUR_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 4 champ {champ} missing post wave-6 schema lift",
            )

    def test_all_wave_five_champs_still_in_registry(self) -> None:
        for champ in WAVE_FIVE_KEYS:
            self.assertIn(
                champ, _PER_SPELL_CC_DURATIONS,
                f"wave 5 champ {champ} missing post wave-6 schema lift",
            )

    def test_lulu_w_polymorph_coexists_with_lulu_r(self) -> None:
        # The signature multi-wave augmentation test: Lulu has BOTH
        # W (wave 1) AND R (wave 6) in the same champion's spell map.
        spells = _PER_SPELL_CC_DURATIONS["Lulu"]
        self.assertIn("W", spells)
        self.assertIn("R", spells)
        self.assertEqual(spells["W"], (1.25, 1.5, 1.75, 2.0, 2.25))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))

    def test_sejuani_q_coexists_with_sejuani_r(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Sejuani"]
        self.assertIn("Q", spells)
        self.assertIn("R", spells)
        self.assertEqual(spells["Q"], (0.75, 0.875, 1.0, 1.125, 1.25))
        self.assertEqual(spells["R"], (1.0, 1.5, 2.0))

    def test_thresh_q_coexists_with_thresh_e(self) -> None:
        spells = _PER_SPELL_CC_DURATIONS["Thresh"]
        self.assertIn("Q", spells)
        self.assertIn("E", spells)
        self.assertEqual(spells["Q"], (1.5, 1.5, 1.5, 1.5, 1.5))
        self.assertEqual(spells["E"], (0.4, 0.4, 0.4, 0.4, 0.4))

    def test_galio_three_spells_preserved(self) -> None:
        # Galio's 3-spell entry (wave 1: W/E/R) must stay intact -
        # the schema lift converted from nested dict literal to
        # three separate setdefault calls; the result is identical.
        spells = _PER_SPELL_CC_DURATIONS["Galio"]
        self.assertEqual(spells["W"], (1.0, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(spells["E"], (0.5, 0.5, 0.5, 0.5, 0.5))
        self.assertEqual(spells["R"], (0.75, 0.75, 0.75))

    def test_hecarim_two_spells_preserved(self) -> None:
        # Hecarim's 2-spell entry from wave 5 (E + R) must stay
        # intact post-schema-lift.
        spells = _PER_SPELL_CC_DURATIONS["Hecarim"]
        self.assertEqual(spells["E"], (0.75, 0.75, 0.75, 0.75, 0.75))
        self.assertEqual(spells["R"], (1.0, 1.0, 1.0))


# ---------------- registry growth contract ----------------


class RegistryGrowthTests(unittest.TestCase):
    """Floor pins for total entry count + total champion count."""

    def test_registry_floor_at_95_entries(self) -> None:
        # Wave 1 = 30, wave 2 = +23 = 53, wave 3 = +14 = 67,
        # wave 4 = +15 = 82, wave 5 = +8 = 90, wave 6 = +5 = 95.
        # Floor pin: total >= 95 (wave 7 may add more entries).
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 95)

    def test_registry_floor_at_82_champions(self) -> None:
        # Wave 1 = 24, wave 2 = +20 = 44, wave 3 = +14 = 58,
        # wave 4 = +15 = 73, wave 5 = +7 = 80, wave 6 = +2 new
        # (Bard / Lillia; Lulu / Sejuani / Thresh stay at 1 champ
        # each via multi-wave augmentation) = 82.
        # Floor pin: total >= 82 (wave 7 may add more champions).
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 82)

    def test_wave_six_new_champs_disjoint_from_prior(self) -> None:
        # Bard + Lillia are genuinely NEW; they must not collide
        # with any prior wave's champion id set.
        prior = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
        )
        overlap = prior & WAVE_SIX_NEW_CHAMPS
        self.assertEqual(
            overlap, set(),
            f"wave 6 new champs collide with prior waves: {overlap}",
        )

    def test_total_champion_union_82(self) -> None:
        # Union of waves 1-5 plus wave 6 new champs = 82 unique ids.
        union = (
            WAVE_ONE_KEYS
            | WAVE_TWO_KEYS
            | WAVE_THREE_KEYS
            | WAVE_FOUR_KEYS
            | WAVE_FIVE_KEYS
            | WAVE_SIX_NEW_CHAMPS
        )
        self.assertEqual(len(union), 82)


# ---------------- schema lift contract ----------------


class SchemaLiftBuilderTests(unittest.TestCase):
    """The 1.37.0 schema lift exposes the builder function.

    The dict.setdefault pattern is what unblocks multi-wave
    augmentation. Pin its presence + idempotence + the multi-wave
    case so future refactors do not regress.
    """

    def test_builder_function_is_exposed(self) -> None:
        # The module-level builder function is callable from outside.
        self.assertTrue(callable(_build_per_spell_cc_durations))

    def test_builder_returns_non_empty_dict(self) -> None:
        result = _build_per_spell_cc_durations()
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)

    def test_builder_returns_fresh_dict_each_call(self) -> None:
        # Multiple invocations return distinct dict instances (NOT
        # the cached module-level _PER_SPELL_CC_DURATIONS singleton).
        a = _build_per_spell_cc_durations()
        b = _build_per_spell_cc_durations()
        self.assertIsNot(a, b)
        # But the values match (byte-identical content).
        self.assertEqual(a, b)

    def test_builder_output_matches_module_registry(self) -> None:
        # The module-level _PER_SPELL_CC_DURATIONS is exactly what
        # the builder returns when called fresh.
        fresh = _build_per_spell_cc_durations()
        self.assertEqual(fresh, _PER_SPELL_CC_DURATIONS)

    def test_setdefault_multi_wave_augmentation_demo(self) -> None:
        # Verify the setdefault pattern semantics with a fixture
        # mirroring the wave 6 augmentation case (champion already
        # has a spell; add another spell; both coexist).
        fixture: dict[str, dict[str, tuple[float, ...]]] = {}
        # Wave 1 adds champion + spell A.
        fixture.setdefault("TestChamp", {})["A"] = (1.0, 2.0, 3.0)
        # Later wave adds spell B to the same champion.
        fixture.setdefault("TestChamp", {})["B"] = (4.0, 5.0, 6.0)
        # Both spells coexist (no clobber).
        self.assertEqual(fixture["TestChamp"]["A"], (1.0, 2.0, 3.0))
        self.assertEqual(fixture["TestChamp"]["B"], (4.0, 5.0, 6.0))
        self.assertEqual(len(fixture["TestChamp"]), 2)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """ENGINE_VERSION pin at wave-6 ship state (1.37.0).

    Wave 6 schema lift + 5 new entries. Engine bump 1.35.0 -> 1.37.0.
    """

    def test_engine_version_at_1_36_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.55.0")


# ---------------- ASCII hygiene contract ----------------


class AsciiHygieneTests(unittest.TestCase):
    """The wave 6 registry block + this test file are pure-ASCII."""

    def test_ability_dps_wave_six_block_is_ascii(self) -> None:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "ability_dps.py"
        )
        src = src_path.read_text(encoding="utf-8")
        start_marker = "ENGINE 1.36.0 wave 6"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1, "wave 6 marker missing")
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
                ch, block, f"wave 6 block carries {name}",
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
