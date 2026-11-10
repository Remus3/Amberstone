"""S144-D-203..204: the shipped cast-rate tables key every row by a live id.

``ult_rates.get_spell_casts_per_sec`` / ``get_ult_casts_per_sec`` index
``by_champ_mode`` with the caller's champion id verbatim (the canonical-key
seam is DEFAULT-OFF, and even when on, ``canonical_champion_id`` is
case-sensitive). A row whose key is not a roster id is unreachable: its
champion silently reads the file-level ``global_fallback`` instead of its own
measured median, with no error anywhere.

Measured 2026-11-09 (patch 16.22.1): both tables key Fiddlesticks as the
Match-V5 spelling ``FiddleSticks``; every other key is a live id. That one
row is PINNED below rather than fixed here, because re-keying it changes
served DS output for Fiddlesticks (Tier-2, a merger follow-up); the
generator itself is fixed by S144-D-202. When the data is re-keyed the pin
test fails on purpose, and the pin must be emptied in the same change.

S144-D-204 pins the shape the lookup relies on: both tables carry the same
key set (so the ult shim and the spell R lookup never disagree on whether a
champion is measured), every mode key is one the callers pass, and every rate
is a finite non-negative float.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.data_loader import DataSnapshot

_DATA = Path(__file__).resolve().parents[3] / "data" / "daemon_slayer"
_SPELL = _DATA / "spell_cast_rates.json"
_ULT = _DATA / "ult_cast_rates.json"

# shipped key -> the roster id it should be. Empty this when the rows are
# re-keyed (Tier-2: changes served output for the champion).
_PINNED_MISCASED: dict[str, str] = {"FiddleSticks": "Fiddlesticks"}

_MODES = frozenset({"SR", "ARAM", "ARENA", "global"})
_SPELL_KEYS = ("Q", "W", "E", "R")


def _table(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["by_champ_mode"]


class CastRateKeysAreLiveIdsTests(unittest.TestCase):
    """S144-D-203."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.roster = frozenset(DataSnapshot.load().champions)
        cls.tables = {"spell": _table(_SPELL), "ult": _table(_ULT)}

    def test_roster_and_tables_are_populated(self) -> None:
        # An empty enumeration must not pass the subset checks below.
        self.assertGreater(len(self.roster), 150)
        for name, t in self.tables.items():
            self.assertGreater(len(t), 150, name)

    def test_every_key_is_a_roster_id_or_pinned(self) -> None:
        for name, t in self.tables.items():
            stray = sorted(set(t) - self.roster - set(_PINNED_MISCASED))
            self.assertEqual(stray, [], f"{name}: unreachable rows {stray}")

    def test_pinned_set_is_exactly_the_live_offenders(self) -> None:
        for name, t in self.tables.items():
            offenders = sorted(set(t) - self.roster)
            self.assertEqual(
                offenders, sorted(_PINNED_MISCASED),
                f"{name}: pin is stale - re-keyed rows must leave the pin",
            )

    def test_each_pin_names_the_roster_id_it_shadows(self) -> None:
        by_fold = {c.casefold(): c for c in self.roster}
        for bad, good in _PINNED_MISCASED.items():
            self.assertIn(good, self.roster)
            self.assertEqual(by_fold.get(bad.casefold()), good)
            for name, t in self.tables.items():
                # No duplicate row: the roster id is not ALSO a key.
                self.assertNotIn(good, t, name)

    def test_a_pinned_champion_reads_the_fallback_today(self) -> None:
        """Documents the pinned miss through the real lookup, so the pin is
        evidence, not prose: the roster id reads global_fallback while the
        miscased key reads the measured row."""
        ult_rates.reset_cache()
        try:
            fb = json.loads(_SPELL.read_text(encoding="utf-8"))["global_fallback"]
            for bad, good in _PINNED_MISCASED.items():
                self.assertEqual(
                    ult_rates.get_spell_casts_per_sec(good, "W", "SR"),
                    float(fb["W"]),
                )
                self.assertNotEqual(
                    ult_rates.get_spell_casts_per_sec(bad, "W", "SR"),
                    float(fb["W"]),
                )
        finally:
            ult_rates.reset_cache()


class CastRateTableShapeTests(unittest.TestCase):
    """S144-D-204."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spell = _table(_SPELL)
        cls.ult = _table(_ULT)

    def test_both_tables_carry_the_same_champions(self) -> None:
        self.assertEqual(sorted(set(self.spell) ^ set(self.ult)), [])

    def test_every_mode_key_is_one_a_caller_passes(self) -> None:
        bad = sorted(
            f"{c}.{m}"
            for t in (self.spell, self.ult)
            for c, row in t.items()
            for m in row
            if m not in _MODES
        )
        self.assertEqual(bad, [])

    def test_every_rate_is_finite_and_non_negative(self) -> None:
        bad: list[str] = []
        for c, row in self.spell.items():
            for m, keyed in row.items():
                if not isinstance(keyed, dict) or tuple(sorted(keyed)) != tuple(sorted(_SPELL_KEYS)):
                    bad.append(f"spell {c}.{m}: keys {keyed!r}")
                    continue
                for k, v in keyed.items():
                    if isinstance(v, bool) or not isinstance(v, (int, float)) \
                            or not math.isfinite(v) or v < 0:
                        bad.append(f"spell {c}.{m}.{k}={v!r}")
        for c, row in self.ult.items():
            for m, v in row.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) \
                        or not math.isfinite(v) or v < 0:
                    bad.append(f"ult {c}.{m}={v!r}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
