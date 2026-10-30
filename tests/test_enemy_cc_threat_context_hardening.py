"""Hardening pins for core.enemy_cc_threat_context (s144 true-audit cycle 72).

Every coach feeds ``enemy_cc_threat_line`` the Live Client roster, whose
``championName`` is a DISPLAY name ("Wukong", "Cho'Gath", "Jarvan IV"),
while the DS CC registry and the kind-hint table key on canonical DDragon
ids ("MonkeyKing", "Chogath", "JarvanIV"). Before this cycle:

  F1 a display name that differs from its id rendered NOTHING (Wukong
     and Cho'Gath are the registered CC champions this hits today);
  F2 the kind-hint table claimed to "mirror the registry exactly" but held
     53 of the registry's slots, so every newer slot rendered a generic
     "CC" word instead of its kind;
  F3 a non-int ``limit`` (1.5, "3") raised TypeError out of the prompt
     build;
  F4 a repeated champion (or a display name plus its id) rendered twice;
  F5 a NaN / inf duration reached the prompt as "nans" / "infs" or broke
     the sort;
  F6 a bare string roster was iterated character by character, and a
     non-str entry was handed to the engine.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from core import enemy_cc_threat_context as mod
from core.enemy_cc_threat_context import enemy_cc_threat_line

_PATCH_TARGET = "core.enemy_cc_threat_context.compute_cc_pressure"


@dataclass(frozen=True)
class _Spell:
    spell_key: str
    duration_post_tenacity_s: float


@dataclass(frozen=True)
class _Result:
    total_cc_seconds: float
    spells: tuple


def _one(key: str, dur: float, total: float | None = None) -> _Result:
    return _Result(
        total_cc_seconds=dur if total is None else total,
        spells=(_Spell(key, dur),),
    )


class _Recorder:
    """compute_cc_pressure stand-in keyed by canonical id; records calls."""

    def __init__(self, table: dict[str, _Result]):
        self.table = table
        self.calls: list[object] = []

    def __call__(self, champion, mode="SR"):
        self.calls.append(champion)
        return self.table.get(champion, _Result(0.0, ()))


class DisplayNameTests(unittest.TestCase):
    """F1: live display names are canonicalized before the engine read."""

    def test_engine_receives_canonical_id_and_line_keeps_display_name(self):
        rec = _Recorder({"MonkeyKing": _one("R", 1.0)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Wukong"], "SR")
        self.assertEqual(rec.calls, ["MonkeyKing"])
        self.assertEqual(line, "Enemy CC threats: Wukong 1.0s knockup (R)")

    def test_real_engine_cho_gath_and_wukong_render(self):
        line = enemy_cc_threat_line(["Wukong", "Cho'Gath"], "SR")
        self.assertIn("Cho'Gath ", line)
        self.assertIn("Wukong ", line)
        self.assertIn("silence (W)", line)
        self.assertIn("knockup (R)", line)

    def test_padded_display_name_is_stripped(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line([" Morgana "], "SR")
        self.assertEqual(rec.calls, ["Morgana"])
        self.assertEqual(line, "Enemy CC threats: Morgana 3.0s root (Q)")


class KindTableCoverageTests(unittest.TestCase):
    """F2: every registry slot the engine can return carries a kind hint."""

    _VOCAB = frozenset({
        "stun", "root", "charm", "suppress", "fear", "silence", "knockup",
        "knockback", "sleep", "polymorph", "taunt", "stasis", "pull",
    })

    def test_every_registry_slot_has_a_hint(self):
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        slots = {
            (champ, key)
            for champ, spells in _PER_SPELL_CC_DURATIONS.items()
            for key in spells
        }
        missing = sorted(slots - set(mod._CC_KIND_HINTS))
        self.assertEqual(missing, [])

    def test_no_hint_for_a_slot_the_registry_lacks(self):
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        slots = {
            (champ, key)
            for champ, spells in _PER_SPELL_CC_DURATIONS.items()
            for key in spells
        }
        self.assertEqual(sorted(set(mod._CC_KIND_HINTS) - slots), [])

    def test_hint_words_are_from_the_documented_vocabulary(self):
        bad = {k: v for k, v in mod._CC_KIND_HINTS.items() if v not in self._VOCAB}
        self.assertEqual(bad, {})

    def test_spot_checks_from_the_registry_comments(self):
        h = mod._CC_KIND_HINTS
        self.assertEqual(h[("Chogath", "W")], "silence")
        self.assertEqual(h[("Bard", "R")], "stasis")
        self.assertEqual(h[("Caitlyn", "W")], "root")
        self.assertEqual(h[("Hecarim", "R")], "fear")
        self.assertEqual(h[("Rakan", "R")], "charm")
        self.assertEqual(h[("Mordekaiser", "E")], "pull")
        self.assertEqual(h[("Sejuani", "Q")], "stun")


class LimitValidationTests(unittest.TestCase):
    """F3: a malformed limit degrades to "" instead of raising."""

    def test_non_int_limits_return_empty_without_raising(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            for bad in (1.5, "3", True, float("nan"), [1]):
                with self.subTest(limit=bad):
                    self.assertEqual(
                        enemy_cc_threat_line(["Morgana"], "SR", limit=bad), ""
                    )

    def test_int_limit_still_works(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0), "Annie": _one("R", 1.5)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Annie", "Morgana"], "SR", limit=1)
        self.assertEqual(line, "Enemy CC threats: Morgana 3.0s root (Q)")


class DuplicateTests(unittest.TestCase):
    """F4: one champion renders once, however many times it is listed."""

    def test_repeated_name_renders_once(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Morgana", "Morgana"], "SR")
        self.assertEqual(line, "Enemy CC threats: Morgana 3.0s root (Q)")

    def test_display_name_and_id_collapse(self):
        rec = _Recorder({"MonkeyKing": _one("R", 1.0)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Wukong", "MonkeyKing"], "SR")
        self.assertEqual(line.count("knockup"), 1)


class NonFiniteTests(unittest.TestCase):
    """F5: NaN / inf never reach the prompt or the sort."""

    def test_non_finite_total_is_skipped(self):
        for bad in (math.nan, math.inf):
            with self.subTest(total=bad):
                rec = _Recorder({
                    "Morgana": _one("Q", 3.0, total=bad),
                    "Annie": _one("R", 1.5),
                })
                with patch(_PATCH_TARGET, rec):
                    line = enemy_cc_threat_line(["Morgana", "Annie"], "SR")
                self.assertEqual(line, "Enemy CC threats: Annie 1.5s stun (R)")

    def test_non_finite_spell_duration_is_skipped(self):
        rec = _Recorder({
            "Morgana": _Result(3.0, (_Spell("Q", math.inf),)),
            "Annie": _one("R", 1.5),
        })
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Morgana", "Annie"], "SR")
        self.assertNotIn("inf", line)
        self.assertEqual(line, "Enemy CC threats: Annie 1.5s stun (R)")

    def test_nan_spell_does_not_hide_a_finite_sibling(self):
        rec = _Recorder({
            "Galio": _Result(2.0, (_Spell("W", math.nan), _Spell("E", 0.75))),
        })
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line(["Galio"], "SR")
        self.assertEqual(line, "Enemy CC threats: Galio 0.8s knockup (E)")


class RosterShapeTests(unittest.TestCase):
    """F6: a malformed roster or entry never reaches the engine."""

    def test_bare_string_roster_is_not_iterated(self):
        rec = _Recorder({"M": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            self.assertEqual(enemy_cc_threat_line("Morgana", "SR"), "")
        self.assertEqual(rec.calls, [])

    def test_dict_roster_is_rejected(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            self.assertEqual(enemy_cc_threat_line({"Morgana": 1}, "SR"), "")
        self.assertEqual(rec.calls, [])

    def test_non_str_entries_are_skipped_before_the_engine(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            line = enemy_cc_threat_line([5, {"a": 1}, b"Morgana", "Morgana"], "SR")
        self.assertEqual(rec.calls, ["Morgana"])
        self.assertEqual(line, "Enemy CC threats: Morgana 3.0s root (Q)")

    def test_non_str_mode_returns_empty(self):
        rec = _Recorder({"Morgana": _one("Q", 3.0)})
        with patch(_PATCH_TARGET, rec):
            self.assertEqual(enemy_cc_threat_line(["Morgana"], 5), "")
        self.assertEqual(rec.calls, [])


if __name__ == "__main__":
    unittest.main()
