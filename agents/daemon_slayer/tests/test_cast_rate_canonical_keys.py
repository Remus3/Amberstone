"""Cast-rate lookups keyed by DISPLAY name against an id-keyed dataset.

``data/daemon_slayer/spell_cast_rates.json`` and ``ult_cast_rates.json``
are keyed by canonical DDragon **id** ("KogMaw", "Khazix", "MonkeyKing").
Both lookups in ``ult_rates.py`` take a ``champion_name`` and index the
file with it raw, and every production caller passes
``resolved.champion_name`` - which ``engine.py`` sets to the DDragon
**display** name ("Kog'Maw", "Kha'Zix", "Wukong").

The 21 champions whose display name differs from their id therefore miss
their measured row entirely and silently take ``global_fallback``, while
``casts_per_sec_source`` still reports ``"measured"``. Four call sites are
affected: ``ability_dps`` (spell + ult), ``dps`` (ult), ``ability_hps``
(spell).

Correcting the key is NOT byte-identical - ``global_fallback`` is a
per-spell vector, so the correction is a per-spell REWEIGHT rather than a
uniform scale, and champion item orderings move. The fix therefore ships
behind ``apply_canonical_cast_rate_keys``, DEFAULT-OFF.

Coverage:

* ``CanonicalKeyResolutionTests`` - the resolver seam itself (off = raw
  passthrough, on = canonical id, fail-soft on garbage).
* ``SpellRateCanonicalKeyTests`` / ``UltRateCanonicalKeyTests`` - one
  call site per public function, asserting against values read live from
  the JSON rather than hardcoded numbers.
* ``ByteIdenticalDefaultTests`` - the full 173-champion x Q/W/E/R sweep
  proving flag-OFF reproduces the pre-fix raw-key lookup exactly.
* ``EndToEndCallSiteTests`` - the seam actually reaches
  ``compute_ability_dps`` without touching that caller.
"""
from __future__ import annotations

import json
import unittest
from contextlib import contextmanager

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.ult_rates import (
    _SPELL_RATE_FILE,
    _ULT_RATE_FILE,
    get_spell_casts_per_sec,
    get_ult_casts_per_sec,
)

# Two of the 21 display-name != DDragon-id champions.
_KOG_DISPLAY, _KOG_CANON = "Kog'Maw", "KogMaw"
_KHA_DISPLAY, _KHA_CANON = "Kha'Zix", "Khazix"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def _canonical_keys(enabled: bool):
    """Flip the module-level seam for the duration of the block."""
    prev = ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS
    ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS = enabled
    try:
        yield
    finally:
        ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS = prev


class CanonicalKeyResolutionTests(unittest.TestCase):
    """The resolver chokepoint - both public functions route through it."""

    def test_flag_off_is_raw_passthrough(self) -> None:
        with _canonical_keys(False):
            self.assertEqual(ult_rates._resolve_champ_key(_KOG_DISPLAY), _KOG_DISPLAY)
            self.assertEqual(ult_rates._resolve_champ_key(_KHA_DISPLAY), _KHA_DISPLAY)

    def test_flag_on_resolves_display_to_canonical_id(self) -> None:
        with _canonical_keys(True):
            self.assertEqual(ult_rates._resolve_champ_key(_KOG_DISPLAY), _KOG_CANON)
            self.assertEqual(ult_rates._resolve_champ_key(_KHA_DISPLAY), _KHA_CANON)

    def test_flag_on_handles_the_three_non_punctuation_aliases(self) -> None:
        # These cannot be reconciled by punctuation-stripping alone.
        with _canonical_keys(True):
            self.assertEqual(ult_rates._resolve_champ_key("Wukong"), "MonkeyKing")
            self.assertEqual(ult_rates._resolve_champ_key("Nunu & Willump"), "Nunu")
            self.assertEqual(ult_rates._resolve_champ_key("Renata Glasc"), "Renata")

    def test_flag_on_is_idempotent_on_canonical_ids(self) -> None:
        with _canonical_keys(True):
            self.assertEqual(ult_rates._resolve_champ_key(_KOG_CANON), _KOG_CANON)
            self.assertEqual(ult_rates._resolve_champ_key("Veigar"), "Veigar")

    def test_flag_on_fail_soft_on_garbage(self) -> None:
        # Unknown input must pass through unchanged, never raise.
        with _canonical_keys(True):
            for junk in ("", "   ", "NotAChampion", "?!?", "123"):
                self.assertEqual(ult_rates._resolve_champ_key(junk), junk)

    def test_per_call_override_beats_module_default(self) -> None:
        with _canonical_keys(False):
            self.assertEqual(
                ult_rates._resolve_champ_key(_KOG_DISPLAY, True), _KOG_CANON
            )
        with _canonical_keys(True):
            self.assertEqual(
                ult_rates._resolve_champ_key(_KOG_DISPLAY, False), _KOG_DISPLAY
            )


class SpellRateCanonicalKeyTests(unittest.TestCase):
    """Call site: ``get_spell_casts_per_sec`` (ability_dps + ability_hps)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = _load(_SPELL_RATE_FILE)
        cls.by_champ = cls.raw["by_champ_mode"]
        cls.fallback = cls.raw["global_fallback"]

    def test_dataset_is_id_keyed_not_display_keyed(self) -> None:
        # Pins the premise of the whole fix.
        self.assertIn(_KOG_CANON, self.by_champ)
        self.assertNotIn(_KOG_DISPLAY, self.by_champ)

    def test_flag_off_display_name_falls_back_to_global(self) -> None:
        with _canonical_keys(False):
            for key in ("Q", "W", "E", "R"):
                self.assertAlmostEqual(
                    get_spell_casts_per_sec(_KOG_DISPLAY, key, "SR"),
                    float(self.fallback[key]),
                    places=12,
                    msg=f"{key}: expected the global_fallback vector",
                )

    def test_flag_on_display_name_hits_measured_row(self) -> None:
        expected = self.by_champ[_KOG_CANON]["SR"]
        with _canonical_keys(True):
            for key in ("Q", "W", "E", "R"):
                self.assertAlmostEqual(
                    get_spell_casts_per_sec(_KOG_DISPLAY, key, "SR"),
                    float(expected[key]),
                    places=12,
                    msg=f"{key}: expected the measured SR row",
                )

    def test_flag_on_changes_the_answer(self) -> None:
        # Guards against a fix that resolves the key but reads the same
        # number anyway (which would mean the test proves nothing).
        with _canonical_keys(False):
            off = get_spell_casts_per_sec(_KHA_DISPLAY, "R", "SR")
        with _canonical_keys(True):
            on = get_spell_casts_per_sec(_KHA_DISPLAY, "R", "SR")
        self.assertNotAlmostEqual(off, on, places=6)

    def test_flag_on_is_a_per_spell_reweight_not_a_uniform_scale(self) -> None:
        # The headline reason this cannot ship default-ON.
        ratios = []
        for key in ("Q", "W", "E", "R"):
            with _canonical_keys(False):
                off = get_spell_casts_per_sec(_KHA_DISPLAY, key, "SR")
            with _canonical_keys(True):
                on = get_spell_casts_per_sec(_KHA_DISPLAY, key, "SR")
            ratios.append(on / off)
        self.assertGreater(max(ratios) - min(ratios), 0.1)

    def test_matched_champion_is_unaffected_either_way(self) -> None:
        # Veigar's display name IS its id - the flag must be a no-op.
        expected = self.by_champ["Veigar"]["SR"]["Q"]
        with _canonical_keys(False):
            off = get_spell_casts_per_sec("Veigar", "Q", "SR")
        with _canonical_keys(True):
            on = get_spell_casts_per_sec("Veigar", "Q", "SR")
        self.assertAlmostEqual(off, float(expected), places=12)
        self.assertAlmostEqual(on, float(expected), places=12)

    def test_flag_on_garbage_champion_does_not_raise(self) -> None:
        with _canonical_keys(True):
            val = get_spell_casts_per_sec("NotAChampion", "Q", "SR")
        self.assertAlmostEqual(val, float(self.fallback["Q"]), places=12)

    def test_bad_spell_key_still_raises_under_the_flag(self) -> None:
        with _canonical_keys(True):
            with self.assertRaises(ValueError):
                get_spell_casts_per_sec(_KOG_DISPLAY, "P", "SR")


class UltRateCanonicalKeyTests(unittest.TestCase):
    """Call site: ``get_ult_casts_per_sec`` (ability_dps + dps/Malignance)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = _load(_ULT_RATE_FILE)
        cls.by_champ = cls.raw["by_champ_mode"]
        cls.fallback = float(cls.raw["global_fallback"])

    def test_dataset_is_id_keyed_not_display_keyed(self) -> None:
        self.assertIn(_KOG_CANON, self.by_champ)
        self.assertNotIn(_KOG_DISPLAY, self.by_champ)

    def test_flag_off_display_name_falls_back_to_global(self) -> None:
        with _canonical_keys(False):
            self.assertAlmostEqual(
                get_ult_casts_per_sec(_KOG_DISPLAY, "SR"), self.fallback, places=12
            )

    def test_flag_on_display_name_hits_measured_row(self) -> None:
        expected = float(self.by_champ[_KOG_CANON]["SR"])
        with _canonical_keys(True):
            self.assertAlmostEqual(
                get_ult_casts_per_sec(_KOG_DISPLAY, "SR"), expected, places=12
            )

    def test_flag_on_falls_through_to_champion_global_for_unknown_mode(self) -> None:
        expected = float(self.by_champ[_KHA_CANON]["global"])
        with _canonical_keys(True):
            self.assertAlmostEqual(
                get_ult_casts_per_sec(_KHA_DISPLAY, "NEXUSBLITZ"), expected, places=12
            )

    def test_flag_on_garbage_champion_does_not_raise(self) -> None:
        with _canonical_keys(True):
            self.assertAlmostEqual(
                get_ult_casts_per_sec("NotAChampion", "SR"), self.fallback, places=12
            )


class ByteIdenticalDefaultTests(unittest.TestCase):
    """Flag-OFF must reproduce the pre-fix raw-key lookup for EVERY
    champion, in both name-forms, across all four spell keys."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spells = _load(_SPELL_RATE_FILE)
        cls.ults = _load(_ULT_RATE_FILE)
        champs = json.loads(
            (
                _SPELL_RATE_FILE.parent.parent / "meta" / "ddragon_champions.json"
            ).read_text(encoding="utf-8")
        )
        data = champs.get("data", champs)
        cls.names = sorted(
            {str(e["name"]) for e in data.values() if isinstance(e, dict)}
            | {str(e["id"]) for e in data.values() if isinstance(e, dict)}
        )

    def _prefix_spell(self, name: str, key: str, mode: str) -> float:
        """Verbatim re-implementation of the pre-fix lookup chain."""
        data = self.spells
        champ_data = data.get("by_champ_mode", {}).get(name, {})
        by_mode = champ_data.get(mode)
        if isinstance(by_mode, dict) and key in by_mode:
            v = by_mode.get(key)
            if v is not None:
                return float(v)
        by_global = champ_data.get("global")
        if isinstance(by_global, dict) and key in by_global:
            v = by_global.get(key)
            if v is not None:
                return float(v)
        fb = data.get("global_fallback")
        if isinstance(fb, dict):
            v = fb.get(key)
            if v is not None:
                return float(v)
        return 0.0

    def _prefix_ult(self, name: str, mode: str) -> float:
        data = self.ults
        champ_data = data.get("by_champ_mode", {}).get(name, {})
        rate = champ_data.get(mode)
        if rate is not None:
            return float(rate)
        rate = champ_data.get("global")
        if rate is not None:
            return float(rate)
        fb = data.get("global_fallback", ult_rates._LEGACY_GLOBAL_FALLBACK)
        if isinstance(fb, dict):
            return float(fb.get("R", ult_rates._LEGACY_GLOBAL_FALLBACK))
        return float(fb)

    def test_module_default_is_off(self) -> None:
        self.assertFalse(ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS)

    def test_spell_rates_byte_identical_with_flag_off(self) -> None:
        with _canonical_keys(False):
            for name in self.names:
                for mode in ("SR", "ARAM"):
                    for key in ("Q", "W", "E", "R"):
                        self.assertEqual(
                            get_spell_casts_per_sec(name, key, mode),
                            self._prefix_spell(name, key, mode),
                            msg=f"drift at {name}/{mode}/{key}",
                        )

    def test_ult_rates_byte_identical_with_flag_off(self) -> None:
        with _canonical_keys(False):
            for name in self.names:
                for mode in ("SR", "ARAM", "ARENA"):
                    self.assertEqual(
                        get_ult_casts_per_sec(name, mode),
                        self._prefix_ult(name, mode),
                        msg=f"drift at {name}/{mode}",
                    )


class EndToEndCallSiteTests(unittest.TestCase):
    """The seam reaches ``compute_ability_dps`` from ult_rates alone - the
    caller passes no flag and was not modified."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot

        cls.snap = DataSnapshot.load()
        cls.raw = _load(_SPELL_RATE_FILE)

    def _q_rate(self, champion: str) -> float:
        from agents.daemon_slayer.ability_dps import compute_ability_dps

        out = compute_ability_dps(
            self.snap, champion, level=11, item_ids=[], mode="SR",
        )
        q = next((s for s in out.per_spell if s.key == "Q"), None)
        self.assertIsNotNone(q)
        return q.casts_per_sec

    def test_mismatched_champion_flips_with_the_module_flag(self) -> None:
        fallback = float(self.raw["global_fallback"]["Q"])
        measured = float(self.raw["by_champ_mode"][_KHA_CANON]["SR"]["Q"])

        with _canonical_keys(False):
            off = self._q_rate(_KHA_CANON)
        with _canonical_keys(True):
            on = self._q_rate(_KHA_CANON)

        # compute_ability_dps re-resolves to the DISPLAY name internally,
        # so even passing the canonical id hits the bug today.
        self.assertAlmostEqual(off, fallback, places=12)
        self.assertAlmostEqual(on, measured, places=12)


if __name__ == "__main__":
    unittest.main()
