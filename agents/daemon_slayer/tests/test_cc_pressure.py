"""ENGINE 1.32.0 (2026-05-22) - cc_pressure aggregator.

First consumer of the ``_PER_SPELL_CC_DURATIONS`` registry seeded at
ENGINE 1.30.0 + extended at 1.31.0. Walks the registry, picks max-
rank base durations per registered spell, applies ARAM tenacity
through ``ehp.effective_cc_duration``, returns ``CcPressureResult``.

ENGINE 1.38.0 (2026-05-22) - dataclass gained 2 new fields for the
``cc_conditional`` consumer wire (``conditional_cc_seconds`` +
``conditional_entries``). The ``test_cc_pressure_result_field_names``
pin in ``ContractTests`` was extended in the same commit; behavior
tests in this file remain pinned at the unconditional axis (default
``include_conditional=False``). Consumer-wire behavior is pinned in
``test_cc_conditional_consumer_pressure.py``.

Test surface:
* ``ContractTests`` - dataclass shapes (frozen=True, field defaults,
  schema contract).
* ``ComputeCcPressureTests`` - known champion lookups (Annie / Galio /
  Vi / MonkeyKing canonical id), unknown / blank / None inputs, mode
  matrix (SR / ARAM / KIWI / unknown).
* ``TotalCcSecondsTests`` - sum of max-rank post-tenacity values.
* ``SpellOrderTests`` - canonical Q-W-E-R ordering over the registered
  subset.
* ``FailSoftTests`` - defensive paths (empty spells dict, etc.).
* ``TenacityIntegrationTests`` - SR mode identity; ARAM mode lift
  composed via ``ehp.effective_cc_duration``.
* ``AsciiHygieneTest`` - module is pure 7-bit ASCII.
* ``EngineVersionCurrentTests`` - pin ENGINE_VERSION 1.38.0.
"""

from __future__ import annotations

import pathlib
import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from unittest import mock

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_pressure
from agents.daemon_slayer.cc_pressure import (
    CcPressureResult,
    CcSpellEntry,
    _SPELL_ORDER,
    _is_aram_mode,
    compute_cc_pressure,
)
from agents.daemon_slayer.ehp import effective_cc_duration


class ContractTests(unittest.TestCase):
    """Dataclass shape contract."""

    def test_cc_spell_entry_is_frozen_dataclass(self) -> None:
        self.assertTrue(is_dataclass(CcSpellEntry))
        entry = CcSpellEntry(
            spell_key="R",
            base_durations_s=(1.5, 1.5, 1.5),
            max_rank_duration_s=1.5,
            duration_post_tenacity_s=1.5,
        )
        with self.assertRaises(FrozenInstanceError):
            entry.spell_key = "Q"  # type: ignore[misc]

    def test_cc_spell_entry_field_names(self) -> None:
        names = {f.name for f in fields(CcSpellEntry)}
        self.assertEqual(
            names,
            {
                "spell_key",
                "base_durations_s",
                "max_rank_duration_s",
                "duration_post_tenacity_s",
            },
        )

    def test_cc_pressure_result_is_frozen_dataclass(self) -> None:
        self.assertTrue(is_dataclass(CcPressureResult))
        result = compute_cc_pressure("Annie", "SR")
        with self.assertRaises(FrozenInstanceError):
            result.total_cc_seconds = 99.0  # type: ignore[misc]

    def test_cc_pressure_result_field_names(self) -> None:
        names = {f.name for f in fields(CcPressureResult)}
        self.assertEqual(
            names,
            {
                "champion",
                "mode",
                "total_cc_seconds",
                "spells",
                "tenacity_mult",
                # ENGINE 1.38.0 fields - new conditional CC axis
                "conditional_cc_seconds",
                "conditional_entries",
            },
        )

    def test_cc_pressure_result_spells_default_is_empty_tuple(self) -> None:
        result = CcPressureResult(
            champion="Foo",
            mode="SR",
            total_cc_seconds=0.0,
        )
        self.assertEqual(result.spells, ())
        self.assertEqual(result.tenacity_mult, 1.0)

    def test_spell_order_constant_is_qwer(self) -> None:
        self.assertEqual(_SPELL_ORDER, ("Q", "W", "E", "R"))


class ComputeCcPressureTests(unittest.TestCase):
    """Behavior on real registry entries."""

    def test_annie_sr_r_15s(self) -> None:
        # Annie R = (1.5, 1.5, 1.5); SR identity tenacity
        result = compute_cc_pressure("Annie", "SR")
        self.assertEqual(result.champion, "Annie")
        self.assertEqual(result.mode, "SR")
        self.assertEqual(result.tenacity_mult, 1.0)
        self.assertEqual(len(result.spells), 1)
        spell = result.spells[0]
        self.assertEqual(spell.spell_key, "R")
        self.assertEqual(spell.base_durations_s, (1.5, 1.5, 1.5))
        self.assertEqual(spell.max_rank_duration_s, 1.5)
        self.assertEqual(spell.duration_post_tenacity_s, 1.5)
        self.assertEqual(result.total_cc_seconds, 1.5)

    def test_galio_sr_three_spells_2_25_total(self) -> None:
        # Galio W=1.0, E=0.5, R=0.75 -> total 2.25
        result = compute_cc_pressure("Galio", "SR")
        self.assertEqual(len(result.spells), 3)
        keys = [s.spell_key for s in result.spells]
        self.assertEqual(keys, ["W", "E", "R"])
        self.assertAlmostEqual(result.total_cc_seconds, 2.25, places=6)

    def test_vi_sr_two_spells_q_r(self) -> None:
        # Vi Q=0.75, R=1.0
        result = compute_cc_pressure("Vi", "SR")
        self.assertEqual(len(result.spells), 2)
        keys = [s.spell_key for s in result.spells]
        self.assertEqual(keys, ["Q", "R"])
        self.assertAlmostEqual(result.total_cc_seconds, 1.75, places=6)

    def test_monkeyking_canonical_id_not_wukong(self) -> None:
        # Canonical DDragon id is MonkeyKing not Wukong
        result = compute_cc_pressure("MonkeyKing", "SR")
        self.assertEqual(result.champion, "MonkeyKing")
        self.assertEqual(len(result.spells), 1)
        self.assertEqual(result.spells[0].spell_key, "R")
        wukong = compute_cc_pressure("Wukong", "SR")
        # Wukong (non-canonical) is not in the registry
        self.assertEqual(wukong.spells, ())
        self.assertEqual(wukong.total_cc_seconds, 0.0)

    def test_unknown_champion_returns_empty_result(self) -> None:
        result = compute_cc_pressure("NotAChamp", "SR")
        self.assertEqual(result.champion, "NotAChamp")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.tenacity_mult, 1.0)

    def test_blank_champion_returns_empty_result(self) -> None:
        result = compute_cc_pressure("", "SR")
        self.assertEqual(result.champion, "")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.tenacity_mult, 1.0)

    def test_none_champion_returns_empty_result(self) -> None:
        result = compute_cc_pressure(None, "SR")  # type: ignore[arg-type]
        self.assertEqual(result.champion, "")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())

    def test_default_mode_is_sr(self) -> None:
        # mode kwarg defaults to "SR"
        result = compute_cc_pressure("Annie")
        self.assertEqual(result.mode, "SR")
        self.assertEqual(result.tenacity_mult, 1.0)

    def test_unknown_mode_is_identity(self) -> None:
        # Non-ARAM modes degenerate to 1.0 tenacity
        result = compute_cc_pressure("Annie", "CHERRY")
        self.assertEqual(result.tenacity_mult, 1.0)
        result = compute_cc_pressure("Annie", "UNKNOWN")
        self.assertEqual(result.tenacity_mult, 1.0)

    def test_none_mode_falls_back_to_sr(self) -> None:
        # None mode -> "SR" by safe_mode default
        result = compute_cc_pressure("Annie", None)  # type: ignore[arg-type]
        self.assertEqual(result.mode, "SR")
        self.assertEqual(result.tenacity_mult, 1.0)


class TotalCcSecondsTests(unittest.TestCase):
    """Sum-of-max-rank-post-tenacity contract."""

    def test_annie_total_equals_single_max_rank(self) -> None:
        result = compute_cc_pressure("Annie", "SR")
        self.assertEqual(result.total_cc_seconds, 1.5)

    def test_galio_total_is_w_plus_e_plus_r(self) -> None:
        result = compute_cc_pressure("Galio", "SR")
        spell_durations = {s.spell_key: s.duration_post_tenacity_s for s in result.spells}
        expected = sum(spell_durations.values())
        self.assertAlmostEqual(result.total_cc_seconds, expected, places=6)
        self.assertAlmostEqual(result.total_cc_seconds, 2.25, places=6)

    def test_total_with_aram_lift_when_in_both_maps(self) -> None:
        # No real champ is in BOTH registry + tenacity map at 1.32.0
        # (registry covers tanks / mages; tenacity covers assassins).
        # Synthesize a champ in both via monkey-patch.
        fake_registry = {
            "FauxAssassin": {"Q": (0.5, 0.75, 1.0, 1.25, 1.5)},
        }
        fake_tenacity = {"FauxAssassin": 1.20}
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
                # SR: identity
                sr = compute_cc_pressure("FauxAssassin", "SR")
                self.assertEqual(sr.tenacity_mult, 1.0)
                self.assertEqual(sr.total_cc_seconds, 1.5)
                # ARAM: 1.20x lift
                aram = compute_cc_pressure("FauxAssassin", "ARAM")
                self.assertEqual(aram.tenacity_mult, 1.20)
                self.assertAlmostEqual(aram.total_cc_seconds, 1.8, places=6)
                # Worked example matches effective_cc_duration
                self.assertAlmostEqual(
                    aram.spells[0].duration_post_tenacity_s,
                    effective_cc_duration(1.5, 1.20),
                    places=6,
                )

    def test_zero_spells_yields_zero_total(self) -> None:
        result = compute_cc_pressure("Aatrox", "SR")
        self.assertEqual(result.total_cc_seconds, 0.0)
        self.assertEqual(result.spells, ())


class SpellOrderTests(unittest.TestCase):
    """Canonical Q-W-E-R ordering even when registry stores out of order."""

    def test_returned_spells_in_canonical_order(self) -> None:
        # Patch registry with out-of-order keys
        fake_registry = {
            "Foo": {
                "R": (1.0,),
                "E": (0.5,),
                "Q": (0.75,),
                "W": (0.25,),
            },
        }
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            result = compute_cc_pressure("Foo", "SR")
        keys = [s.spell_key for s in result.spells]
        self.assertEqual(keys, ["Q", "W", "E", "R"])

    def test_subset_preserves_canonical_order(self) -> None:
        # Galio W/E/R - registered out of order in source? Already W,E,R
        # which is canonical; test pin guards against future drift.
        result = compute_cc_pressure("Galio", "SR")
        keys = [s.spell_key for s in result.spells]
        self.assertEqual(keys, ["W", "E", "R"])

    def test_single_spell_returns_single_entry(self) -> None:
        result = compute_cc_pressure("Annie", "SR")
        self.assertEqual([s.spell_key for s in result.spells], ["R"])

    def test_extra_spell_keys_dropped_silently(self) -> None:
        # Future-defense: if registry grows a non-QWER key (e.g. "P"
        # for passive), the aggregator silently drops it.
        fake_registry = {"Foo": {"Q": (0.5,), "P": (1.0,), "R": (1.5,)}}
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            result = compute_cc_pressure("Foo", "SR")
        keys = [s.spell_key for s in result.spells]
        self.assertEqual(keys, ["Q", "R"])
        self.assertAlmostEqual(result.total_cc_seconds, 2.0, places=6)


class FailSoftTests(unittest.TestCase):
    """Defensive paths - never raise on degenerate inputs."""

    def test_empty_spell_dict_for_known_champion(self) -> None:
        fake_registry = {"EmptyChamp": {}}
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            result = compute_cc_pressure("EmptyChamp", "SR")
        self.assertEqual(result.champion, "EmptyChamp")
        self.assertEqual(result.spells, ())
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_none_spell_tuple_is_skipped(self) -> None:
        fake_registry = {"Foo": {"Q": None, "R": (1.0,)}}
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            result = compute_cc_pressure("Foo", "SR")
        self.assertEqual([s.spell_key for s in result.spells], ["R"])

    def test_empty_spell_tuple_is_skipped(self) -> None:
        fake_registry = {"Foo": {"Q": (), "R": (1.0,)}}
        with mock.patch.object(cc_pressure, "_PER_SPELL_CC_DURATIONS", fake_registry):
            result = compute_cc_pressure("Foo", "SR")
        self.assertEqual([s.spell_key for s in result.spells], ["R"])

    def test_does_not_raise_on_unknown_champion(self) -> None:
        # Just smoke - already implicit, but explicit pin
        try:
            compute_cc_pressure("CompletelyUnknown", "SR")
        except Exception as exc:
            self.fail(f"compute_cc_pressure raised on unknown: {exc!r}")

    def test_does_not_raise_on_unknown_mode(self) -> None:
        try:
            compute_cc_pressure("Annie", "TFT")
        except Exception as exc:
            self.fail(f"compute_cc_pressure raised on unknown mode: {exc!r}")

    def test_missing_tenacity_map_degenerates_to_identity(self) -> None:
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", {}):
            result = compute_cc_pressure("Annie", "ARAM")
        # Empty map -> Annie not in map -> 1.0 tenacity -> identity
        self.assertEqual(result.tenacity_mult, 1.0)


class TenacityIntegrationTests(unittest.TestCase):
    """Per-mode tenacity application via ehp.effective_cc_duration."""

    def test_sr_mode_always_identity(self) -> None:
        # Even for a tenacity-modified champion, SR mode uses 1.0
        fake_tenacity = {"Annie": 1.20}
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
            result = compute_cc_pressure("Annie", "SR")
        self.assertEqual(result.tenacity_mult, 1.0)
        self.assertEqual(result.total_cc_seconds, 1.5)

    def test_aram_mode_applies_tenacity_via_effective_cc_duration(self) -> None:
        fake_tenacity = {"Annie": 1.20}
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
            result = compute_cc_pressure("Annie", "ARAM")
        self.assertEqual(result.tenacity_mult, 1.20)
        # 1.5 * 1.20 = 1.8 - composed via the same helper
        self.assertAlmostEqual(result.total_cc_seconds, 1.8, places=6)
        self.assertAlmostEqual(
            result.spells[0].duration_post_tenacity_s,
            effective_cc_duration(1.5, 1.20),
            places=6,
        )
        # Base unchanged - pre-tenacity transparency
        self.assertEqual(result.spells[0].max_rank_duration_s, 1.5)
        self.assertEqual(result.spells[0].base_durations_s, (1.5, 1.5, 1.5))

    def test_kiwi_mode_also_applies_tenacity(self) -> None:
        # ARAM Mayhem reports queueId 2400 -> gameMode "KIWI"
        fake_tenacity = {"Annie": 1.20}
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
            result = compute_cc_pressure("Annie", "KIWI")
        self.assertEqual(result.tenacity_mult, 1.20)
        self.assertAlmostEqual(result.total_cc_seconds, 1.8, places=6)

    def test_aram_mode_no_registry_entry_yields_empty(self) -> None:
        # Aatrox has neither registry nor tenacity entry
        result = compute_cc_pressure("Aatrox", "ARAM")
        self.assertEqual(result.tenacity_mult, 1.0)
        self.assertEqual(result.spells, ())
        self.assertEqual(result.total_cc_seconds, 0.0)

    def test_lowercase_aram_mode_token_works(self) -> None:
        fake_tenacity = {"Annie": 1.10}
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
            result = compute_cc_pressure("Annie", "aram")
        self.assertEqual(result.tenacity_mult, 1.10)

    def test_aram_5v5_mode_token_works(self) -> None:
        fake_tenacity = {"Annie": 1.10}
        with mock.patch.object(cc_pressure, "_TENACITY_MAP", fake_tenacity):
            result = compute_cc_pressure("Annie", "ARAM_5V5")
        self.assertEqual(result.tenacity_mult, 1.10)


class IsAramModeTests(unittest.TestCase):
    """Mode-membership helper - mirrors aram_tenacity_context contract."""

    def test_aram_recognized(self) -> None:
        self.assertTrue(_is_aram_mode("ARAM"))
        self.assertTrue(_is_aram_mode("aram"))

    def test_kiwi_recognized(self) -> None:
        self.assertTrue(_is_aram_mode("KIWI"))

    def test_aram_5v5_recognized(self) -> None:
        self.assertTrue(_is_aram_mode("ARAM_5V5"))
        self.assertTrue(_is_aram_mode("ARAM_MAYHEM"))

    def test_sr_not_aram(self) -> None:
        self.assertFalse(_is_aram_mode("SR"))
        self.assertFalse(_is_aram_mode("CLASSIC"))

    def test_cherry_not_aram(self) -> None:
        self.assertFalse(_is_aram_mode("CHERRY"))
        self.assertFalse(_is_aram_mode("ARENA"))

    def test_empty_or_none_not_aram(self) -> None:
        self.assertFalse(_is_aram_mode(None))
        self.assertFalse(_is_aram_mode(""))


class AsciiHygieneTest(unittest.TestCase):
    """Module is pure 7-bit ASCII (no em-dashes, smart quotes, etc.)."""

    def test_module_is_pure_ascii(self) -> None:
        path = (
            pathlib.Path(__file__).resolve().parent.parent / "cc_pressure.py"
        )
        raw = path.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertEqual(
            non_ascii,
            [],
            f"non-ASCII bytes found in cc_pressure.py: {non_ascii[:5]}",
        )


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at 1.38.0 for the cc_conditional consumer wire slice."""

    def test_engine_version_is_1_38_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.82.0")


if __name__ == "__main__":
    unittest.main()
