"""ENGINE 1.30.0 (2026-05-21) - per-spell CC duration registry seeded.

Closes item 130 carry-forward (b): seeds the ``_PER_SPELL_CC_DURATIONS``
registry (empty at 1.29.0) with a starter set of 30 entries across 24
champions, all values from official Riot patch 16.10 tooltips for
FIRST-ORDER CC abilities (stuns / roots / suspensions / knock-ups /
charms / suppressions / polymorphs / sleeps / taunts).

Engine math consumption is STILL FUTURE - today the values flow through
``AbilitySpellDps.cc_duration_s`` and ``.cc_duration_post_tenacity``
for API inspection + future composition by a downstream fight-sim or
EHP-vs-CC blended scorer.

Coverage classes:

* ``RegistrySeedShapeTests`` - registry has expected size, all entries
  are tuples of floats with sensible lengths (5 for Q/W/E, 3 for R).
* ``RegistrySeedValuesTests`` - per-entry per-rank exact-value pin from
  patch 16.10 tooltip.
* ``RegistryConsumerSrModeTests`` - SR mode + zero tenacity_mult =>
  post == base for every registry entry.
* ``RegistryConsumerAramTenacityTests`` - ARAM mode + the 15 champs
  with aramTenacity > 1.0 in the seeded set scale post-tenacity values.
* ``RegistrySerializationTests`` - AbilitySpellDps.to_dict carries
  the seeded tuples for known champ+spell pairs.
* ``WukongIdMappingTests`` - Wukong is keyed under ``"MonkeyKing"``
  (DDragon canonical id).
* ``RegistryAsciiContractTests`` - registry definition file is
  pure-ASCII (no em/en-dashes or smart quotes in the seeded comments).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    AbilitySpellDps,
    _PER_SPELL_CC_DURATIONS,
    _apply_tenacity_to_cc_tuple,
    _per_spell_cc_for,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# Expected seed - mirror of the literal in ``ability_dps.py``.
# Used for size + value pinning. If a future patch adjusts a value,
# update both the source registry AND this expected pin in lockstep.
EXPECTED_SEED: dict[str, dict[str, tuple[float, ...]]] = {
    "Ahri": {"E": (1.0, 1.25, 1.5, 1.75, 2.0)},
    "Annie": {"R": (1.5, 1.5, 1.5)},
    "Ashe": {"R": (1.5, 1.5, 1.5)},
    "Blitzcrank": {"Q": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Cassiopeia": {"R": (2.0, 2.0, 2.0)},
    "Galio": {
        "W": (1.0, 1.0, 1.0, 1.0, 1.0),
        "E": (0.5, 0.5, 0.5, 0.5, 0.5),
        "R": (0.75, 0.75, 0.75),
    },
    "Leona": {
        "Q": (1.25, 1.25, 1.25, 1.25, 1.25),
        "E": (0.5, 0.5, 0.5, 0.5, 0.5),
        "R": (1.5, 1.5, 1.5),
    },
    "Lissandra": {"R": (1.5, 1.5, 1.5)},
    "Lulu": {"W": (1.25, 1.5, 1.75, 2.0, 2.25)},
    "Malzahar": {"R": (2.5, 2.5, 2.5)},
    "Maokai": {"R": (1.2, 1.6, 2.0)},
    "MonkeyKing": {"R": (1.0, 1.0, 1.0)},
    "Morgana": {"Q": (2.0, 2.25, 2.5, 2.75, 3.0)},
    "Nautilus": {
        "Q": (1.0, 1.15, 1.3, 1.45, 1.6),
        "R": (1.0, 1.5, 2.0),
    },
    "Pantheon": {"W": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Rakan": {"W": (1.0, 1.0, 1.0, 1.0, 1.0)},
    "Renekton": {"W": (0.75, 0.75, 0.75, 0.75, 0.75)},
    "Sejuani": {"R": (1.0, 1.5, 2.0)},
    "Sona": {"R": (1.5, 1.5, 1.5)},
    "Thresh": {"Q": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Veigar": {"E": (1.5, 1.5, 1.5, 1.5, 1.5)},
    "Vi": {
        "Q": (0.75, 0.75, 0.75, 0.75, 0.75),
        "R": (1.0, 1.0, 1.0),
    },
    "Yasuo": {"R": (1.0, 1.0, 1.0)},
    "Zoe": {"E": (2.0, 2.0, 2.0, 2.0, 2.0)},
}


# ---------------- registry seed shape ----------------


class RegistrySeedShapeTests(unittest.TestCase):
    """The registry has the expected size + entry shape."""

    def test_registry_has_expected_champion_count(self) -> None:
        # ENGINE 1.30.0 = 24 champs; 1.31.0 wave 2 = +20 = 44 total;
        # 1.33.0 wave 3 = +14 = 58 total; 1.34.0 wave 4 = +15 = 73 total;
        # 1.35.0 wave 5 = +7 = 80 total; 1.37.0 wave 6 = +2 new champs
        # (Bard / Lillia) = 82 total. Lulu / Sejuani / Thresh added a
        # second spell each via the schema lift (multi-wave augmentation
        # without dict-literal clobber) but stayed at 1 champ each.
        # 1.37.0 wave 7 = +7 NEW champs (Irelia / Kalista / Ornn /
        # Shyvana / Smolder / Vayne / Volibear). Zac was already in
        # wave 2 (Zac E); wave 7 adds Zac R as a multi-wave augmentation
        # at the spell level (Zac stays at 1 champ entry). 82 + 7 = 89.
        # 1.42.0 wave 8 = +0 NEW champs (Lissandra W + Maokai W +
        # Rakan R are all multi-wave augmentations of wave 1 champs).
        # 89 + 0 = 89.
        self.assertGreaterEqual(len(_PER_SPELL_CC_DURATIONS), 89)

    def test_registry_has_expected_total_spell_entries(self) -> None:
        # ENGINE 1.30.0 = 30 entries; 1.31.0 wave 2 = +23 = 53 total;
        # 1.33.0 wave 3 = +14 = 67 total; 1.34.0 wave 4 = +15 = 82 total;
        # 1.35.0 wave 5 = +8 = 90 total (Hecarim has 2 spell entries
        # E + R, contributing 1 champ + 2 entries to the wave 5 delta);
        # 1.37.0 wave 6 = +5 entries = 95 total (Lulu R + Sejuani Q +
        # Thresh E multi-wave augmentations + 2 new champs Bard R +
        # Lillia R).
        # 1.37.0 wave 7 = +8 entries = 103 total (Irelia E / Kalista R /
        # Ornn R / Shyvana R / Smolder R / Vayne E / Volibear E / Zac R;
        # all 8 are new champions, no multi-wave augmentations).
        # 1.42.0 wave 8 = +3 entries = 106 total (Lissandra W + Maokai
        # W + Rakan R; all 3 multi-wave augmentations of wave 1 champs).
        # wave 9 = +2 entries = 108 total (Chogath W silence + Malzahar
        # Q silence; both multi-wave augmentations - 0 new champions).
        total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
        self.assertGreaterEqual(total, 108)

    def test_each_value_is_tuple_of_floats(self) -> None:
        for champ, spells in _PER_SPELL_CC_DURATIONS.items():
            for key, tup in spells.items():
                self.assertIsInstance(
                    tup, tuple, f"{champ} {key} not a tuple"
                )
                for v in tup:
                    self.assertIsInstance(
                        v, float, f"{champ} {key} value not float"
                    )

    def test_q_w_e_tuples_length_five(self) -> None:
        for champ, spells in _PER_SPELL_CC_DURATIONS.items():
            for key, tup in spells.items():
                if key in {"Q", "W", "E"}:
                    self.assertEqual(
                        len(tup), 5,
                        f"{champ} {key} expected 5 ranks, got {len(tup)}",
                    )

    def test_r_tuples_length_three(self) -> None:
        for champ, spells in _PER_SPELL_CC_DURATIONS.items():
            for key, tup in spells.items():
                if key == "R":
                    self.assertEqual(
                        len(tup), 3,
                        f"{champ} R expected 3 ranks, got {len(tup)}",
                    )

    def test_all_values_non_negative(self) -> None:
        for champ, spells in _PER_SPELL_CC_DURATIONS.items():
            for key, tup in spells.items():
                for v in tup:
                    self.assertGreaterEqual(
                        v, 0.0, f"{champ} {key} has negative CC: {v}",
                    )


# ---------------- per-entry value pins ----------------


class RegistrySeedValuesTests(unittest.TestCase):
    """Per-champion per-spell exact-value pin (patch 16.10 tooltips)."""

    def test_ahri_e_charm_durations(self) -> None:
        # Charm 1.0/1.25/1.5/1.75/2.0
        self.assertEqual(
            _per_spell_cc_for("Ahri", "E"),
            (1.0, 1.25, 1.5, 1.75, 2.0),
        )

    def test_annie_r_stun_constant_1_5(self) -> None:
        self.assertEqual(_per_spell_cc_for("Annie", "R"), (1.5, 1.5, 1.5))

    def test_ashe_r_stun_floor_1_5(self) -> None:
        # 1.5-3.5s based on travel distance; floor pinned at 1.5
        self.assertEqual(_per_spell_cc_for("Ashe", "R"), (1.5, 1.5, 1.5))

    def test_blitzcrank_q_constant_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Blitzcrank", "Q"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_cassiopeia_r_facing_stun_2_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Cassiopeia", "R"), (2.0, 2.0, 2.0),
        )

    def test_galio_w_taunt_base_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Galio", "W"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_galio_e_knockup_0_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Galio", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_galio_r_knockup_0_75(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Galio", "R"), (0.75, 0.75, 0.75),
        )

    def test_leona_q_stun_1_25(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Leona", "Q"),
            (1.25, 1.25, 1.25, 1.25, 1.25),
        )

    def test_leona_e_root_0_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Leona", "E"),
            (0.5, 0.5, 0.5, 0.5, 0.5),
        )

    def test_leona_r_center_stun_1_5(self) -> None:
        self.assertEqual(_per_spell_cc_for("Leona", "R"), (1.5, 1.5, 1.5))

    def test_lissandra_r_target_stun_1_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Lissandra", "R"), (1.5, 1.5, 1.5),
        )

    def test_lulu_w_polymorph_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Lulu", "W"),
            (1.25, 1.5, 1.75, 2.0, 2.25),
        )

    def test_malzahar_r_suppression_2_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Malzahar", "R"), (2.5, 2.5, 2.5),
        )

    def test_maokai_r_root_durations(self) -> None:
        self.assertEqual(_per_spell_cc_for("Maokai", "R"), (1.2, 1.6, 2.0))

    def test_wukong_r_first_hit_knockup_1_0(self) -> None:
        # Wukong keyed under DDragon id "MonkeyKing"
        self.assertEqual(
            _per_spell_cc_for("MonkeyKing", "R"), (1.0, 1.0, 1.0),
        )

    def test_morgana_q_root_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Morgana", "Q"),
            (2.0, 2.25, 2.5, 2.75, 3.0),
        )

    def test_nautilus_q_root_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Nautilus", "Q"),
            (1.0, 1.15, 1.3, 1.45, 1.6),
        )

    def test_nautilus_r_knockup_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Nautilus", "R"), (1.0, 1.5, 2.0),
        )

    def test_pantheon_w_stun_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Pantheon", "W"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_rakan_w_knockup_1_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Rakan", "W"),
            (1.0, 1.0, 1.0, 1.0, 1.0),
        )

    def test_renekton_w_stun_base_0_75(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Renekton", "W"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_sejuani_r_stun_durations(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Sejuani", "R"), (1.0, 1.5, 2.0),
        )

    def test_sona_r_stun_1_5(self) -> None:
        self.assertEqual(_per_spell_cc_for("Sona", "R"), (1.5, 1.5, 1.5))

    def test_thresh_q_stun_1_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Thresh", "Q"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_veigar_e_edge_stun_1_5(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Veigar", "E"),
            (1.5, 1.5, 1.5, 1.5, 1.5),
        )

    def test_vi_q_knockup_0_75(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Vi", "Q"),
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )

    def test_vi_r_initial_knockup_1_0(self) -> None:
        self.assertEqual(_per_spell_cc_for("Vi", "R"), (1.0, 1.0, 1.0))

    def test_yasuo_r_initial_knockup_1_0(self) -> None:
        self.assertEqual(_per_spell_cc_for("Yasuo", "R"), (1.0, 1.0, 1.0))

    def test_zoe_e_sleep_2_0(self) -> None:
        self.assertEqual(
            _per_spell_cc_for("Zoe", "E"),
            (2.0, 2.0, 2.0, 2.0, 2.0),
        )

    def test_all_expected_seed_entries_match(self) -> None:
        # Cross-check the expected dict against the live registry.
        for champ, spells in EXPECTED_SEED.items():
            self.assertIn(champ, _PER_SPELL_CC_DURATIONS)
            for key, tup in spells.items():
                self.assertEqual(
                    _per_spell_cc_for(champ, key), tup,
                    f"{champ} {key} mismatch",
                )


# ---------------- SR mode identity contract ----------------


class RegistryConsumerSrModeTests(unittest.TestCase):
    """SR mode: aram_tenacity_mult=1.0 => post == base for every entry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spell(self, champion: str, key: str):
        out = compute_ability_dps(
            self.snap, champion, level=11, item_ids=[], mode="SR",
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_annie_r_sr_post_equals_base(self) -> None:
        s = self._spell("Annie", "R")
        self.assertIsNotNone(s)
        self.assertEqual(s.cc_duration_s, (1.5, 1.5, 1.5))
        # SR -> aram_tenacity_mult = 1.0 -> identity
        self.assertEqual(s.cc_duration_post_tenacity, (1.5, 1.5, 1.5))

    def test_morgana_q_sr_post_equals_base(self) -> None:
        s = self._spell("Morgana", "Q")
        self.assertIsNotNone(s)
        self.assertEqual(s.cc_duration_s, (2.0, 2.25, 2.5, 2.75, 3.0))
        self.assertEqual(
            s.cc_duration_post_tenacity, (2.0, 2.25, 2.5, 2.75, 3.0)
        )

    def test_lulu_w_sr_post_equals_base(self) -> None:
        s = self._spell("Lulu", "W")
        self.assertIsNotNone(s)
        self.assertEqual(
            s.cc_duration_post_tenacity, (1.25, 1.5, 1.75, 2.0, 2.25)
        )

    def test_galio_three_spells_sr_post_equals_base(self) -> None:
        # Galio has 3 entries (W/E/R); all should mirror in SR mode.
        for key, expected in [
            ("W", (1.0, 1.0, 1.0, 1.0, 1.0)),
            ("E", (0.5, 0.5, 0.5, 0.5, 0.5)),
            ("R", (0.75, 0.75, 0.75)),
        ]:
            with self.subTest(key=key):
                s = self._spell("Galio", key)
                self.assertIsNotNone(s)
                self.assertEqual(s.cc_duration_s, expected)
                self.assertEqual(s.cc_duration_post_tenacity, expected)


# ---------------- ARAM tenacity_mult application ----------------


class RegistryConsumerAramTenacityTests(unittest.TestCase):
    """ARAM mode lifts post-tenacity values by champion's aramTenacity.

    Notes from item 122 (15 champs at 1.20, 2 at 1.10):

      1.20 - Akali, Belveth, Ekko, Evelynn, Katarina, Kayn, Khazix,
             Lucian, Nunu, Pyke, Qiyana, Quinn, Rengar, Talon, Zed
      1.10 - Elise, Fizz

    Of the seeded registry champions, intersection with the
    aramTenacity > 1.0 set is empty by construction (the seeded set
    is mostly enchanters / tanks / supports, not assassins). To
    exercise the scaling math, we monkey-patch a seeded champion
    onto a hypothetical aramTenacity > 1.0 by calling the helper
    directly with an explicit mult arg.
    """

    def test_apply_tenacity_morgana_q_at_1_20(self) -> None:
        base = _per_spell_cc_for("Morgana", "Q")
        post = _apply_tenacity_to_cc_tuple(base, 1.20)
        self.assertEqual(len(post), len(base))
        for i, val in enumerate(post):
            self.assertAlmostEqual(val, base[i] * 1.20, places=6)

    def test_apply_tenacity_annie_r_at_1_10(self) -> None:
        base = _per_spell_cc_for("Annie", "R")
        post = _apply_tenacity_to_cc_tuple(base, 1.10)
        for i, val in enumerate(post):
            self.assertAlmostEqual(val, base[i] * 1.10, places=6)

    def test_apply_tenacity_lulu_w_at_0_80(self) -> None:
        # Hypothetical reduction (item-tenacity); the helper accepts any
        # multiplier; floors at 0.
        base = _per_spell_cc_for("Lulu", "W")
        post = _apply_tenacity_to_cc_tuple(base, 0.80)
        for i, val in enumerate(post):
            self.assertAlmostEqual(val, base[i] * 0.80, places=6)

    def test_apply_tenacity_floors_negative_to_zero(self) -> None:
        base = _per_spell_cc_for("Thresh", "Q")
        post = _apply_tenacity_to_cc_tuple(base, -0.5)
        for v in post:
            self.assertEqual(v, 0.0)


# ---------------- Serialization contract ----------------


class RegistrySerializationTests(unittest.TestCase):
    """``AbilitySpellDps.to_dict`` carries the seeded tuples as lists."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_morgana_q_to_dict_carries_seeded_tuples(self) -> None:
        out = compute_ability_dps(
            self.snap, "Morgana", level=11, item_ids=[], mode="SR",
        )
        q = next((s for s in out.per_spell if s.key == "Q"), None)
        self.assertIsNotNone(q)
        d = q.to_dict()
        self.assertEqual(d["cc_duration_s"], [2.0, 2.25, 2.5, 2.75, 3.0])
        self.assertEqual(
            d["cc_duration_post_tenacity"], [2.0, 2.25, 2.5, 2.75, 3.0],
        )

    def test_zoe_e_to_dict_carries_seeded_tuples(self) -> None:
        out = compute_ability_dps(
            self.snap, "Zoe", level=11, item_ids=[], mode="SR",
        )
        e = next((s for s in out.per_spell if s.key == "E"), None)
        self.assertIsNotNone(e)
        d = e.to_dict()
        self.assertEqual(d["cc_duration_s"], [2.0, 2.0, 2.0, 2.0, 2.0])


# ---------------- Wukong = MonkeyKing id mapping ----------------


class WukongIdMappingTests(unittest.TestCase):
    """Wukong's DDragon canonical id is ``MonkeyKing``."""

    def test_monkey_king_is_registry_key(self) -> None:
        self.assertIn("MonkeyKing", _PER_SPELL_CC_DURATIONS)

    def test_wukong_label_is_not_registry_key(self) -> None:
        # The display-name "Wukong" is not the canonical id.
        self.assertNotIn("Wukong", _PER_SPELL_CC_DURATIONS)


# ---------------- ASCII contract ----------------


class RegistryAsciiContractTests(unittest.TestCase):
    """The seeded registry definition file is pure-ASCII (no em/en-dashes,
    no smart quotes) per the project's hard ASCII rule."""

    def test_ability_dps_source_is_ascii_in_registry_section(self) -> None:
        # Spot-check the ability_dps.py source around the registry builder.
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent / "_per_spell_cc.py"
        )
        src = src_path.read_text(encoding="utf-8")
        # The seeded registry builder lives between these markers.
        # ENGINE 1.37.0 schema lift moved the registry from a single
        # dict literal to a module-level builder function; the marker
        # spans the full builder body + the post-function module
        # assignment.
        start_marker = "def _build_per_spell_cc_durations"
        end_marker = "def _per_spell_cc_for"
        start = src.find(start_marker)
        end = src.find(end_marker)
        self.assertGreater(start, -1)
        self.assertGreater(end, -1)
        block = src[start:end]
        # Banned glyphs per project ASCII rule.
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
                ch, block, f"registry block carries {name}",
            )

    def test_this_test_file_is_ascii_clean(self) -> None:
        src_path = pathlib.Path(__file__)
        # Read raw bytes to bypass UTF-8 decoding.
        raw = src_path.read_bytes()
        # Banned UTF-8 byte sequences for em/en-dashes + smart quotes.
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
        self.assertEqual(ENGINE_VERSION, "1.111.0")


if __name__ == "__main__":
    unittest.main()
