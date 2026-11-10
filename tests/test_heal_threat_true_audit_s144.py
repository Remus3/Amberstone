"""s144 true-audit of core/heal_threat.py - the anti-heal / Grievous-Wounds
callout fed by the Live Client item pools and the enemy roster.

H1: a NaN / inf float or a >4300-digit int item id raised out of every
    public entry point (ValueError / OverflowError from int() / str()),
    although the module promises "never raises".
H2: a non-integral float id was truncated into a real id (3072.9 counted as
    Bloodthirster, 3165.7 as an ally Morellonomicon); ids now follow the
    same vocabulary as dashboard/_liveclient._item_id.
H3: the callout line echoed the raw foreign champion string (markup,
    zero-width or non-ASCII letters, control characters, unbounded length);
    it now names the curated canonical display name only.

Tests whose names start with test_char_ are characterization tests that
passed before the fix too; they pin behaviour the rewrite must keep.
"""
from __future__ import annotations

import unittest

import core.heal_threat as ht
from dashboard import _liveclient as lc

_JUNK_NUMS = (float("nan"), float("inf"), float("-inf"), 10 ** 5000)
# Non-ASCII probes built with chr() so this file stays 7-bit ASCII.
_FULLWIDTH_3072 = "".join(chr(0xFF10 + int(d)) for d in "3072")
_ZERO_WIDTH = chr(0x200B)
_KELVIN = chr(0x212A)


class H1NeverRaisesTests(unittest.TestCase):
    def test_h1_junk_enemy_id_does_not_raise(self) -> None:
        for v in _JUNK_NUMS:
            with self.subTest(v=type(v).__name__):
                self.assertIsNone(ht.heal_threat_callout(["Jax"], [v], [], "sr"))

    def test_h1_junk_ally_id_does_not_raise(self) -> None:
        for v in _JUNK_NUMS:
            with self.subTest(v=type(v).__name__):
                out = ht.heal_threat_callout(["Soraka"], [], [v], "sr")
                self.assertIsNotNone(out)

    def test_h1_helpers_do_not_raise(self) -> None:
        for v in _JUNK_NUMS:
            with self.subTest(v=type(v).__name__):
                self.assertEqual(ht.count_heal_sources([], [v]), 0)
                self.assertFalse(ht.ally_has_antiheal([v]))

    def test_h1_good_entries_still_count_beside_junk(self) -> None:
        out = ht.heal_threat_callout(
            ["Jax"], [float("nan"), 3072, 10 ** 5000, "3074"], [], "sr")
        self.assertIsNotNone(out)
        self.assertIn("2 heal items", out["line"])
        self.assertIsNone(ht.heal_threat_callout(
            ["Soraka"], [], [float("inf"), 3165], "sr"))


class H2IdVocabularyTests(unittest.TestCase):
    def test_h2_fractional_float_is_not_an_enemy_heal_item(self) -> None:
        self.assertIsNone(
            ht.heal_threat_callout(["Jax"], [3072.9, 3074.2], [], "sr"))
        self.assertEqual(ht.count_heal_sources([], [3072.9]), 0)

    def test_h2_fractional_float_is_not_ally_antiheal(self) -> None:
        self.assertIsNotNone(
            ht.heal_threat_callout(["Soraka"], [], [3165.7], "sr"))
        self.assertFalse(ht.ally_has_antiheal([3165.7]))

    def test_h2_float_ids_refused_like_liveclient(self) -> None:
        self.assertFalse(ht.ally_has_antiheal([3165.0]))

    def test_h2_out_of_range_ints_refused(self) -> None:
        for v in (0, -3165, 10 ** 7 + 3165, 10 ** 30):
            with self.subTest(v=v):
                self.assertFalse(ht.ally_has_antiheal([v]))

    def test_h2_matches_liveclient_item_id_vocabulary(self) -> None:
        raws = [3072, "3072", " 3072 ", "03072", "+3072", "-3072", "3072.0",
                "3e3", _FULLWIDTH_3072, 3072.0, 3072.9, True, None,
                0, -7, 447111, 10 ** 7, 10 ** 7 - 1, "9" * 21, "9" * 5000,
                "", "  ",
                [3072], {"a": 1}, float("nan")]
        for raw in raws:
            with self.subTest(raw=repr(raw)[:30]):
                want = lc._item_id(raw)
                self.assertEqual(ht._id_strs([raw]), [want] if want else [])

    def test_char_int_and_str_ids_still_match(self) -> None:
        self.assertIsNone(ht.heal_threat_callout(["Soraka"], [], [3165], "sr"))
        self.assertIsNone(
            ht.heal_threat_callout(["Soraka"], [], [" 3165 "], "sr"))
        self.assertEqual(ht.count_heal_sources([], [447111, "2501"]), 2)


class H3CanonicalNameTests(unittest.TestCase):
    def _line(self, name: str) -> str:
        out = ht.heal_threat_callout([name], [], [], "sr")
        self.assertIsNotNone(out)
        return out["line"]

    def test_h3_markup_not_echoed(self) -> None:
        line = self._line("<>Soraka</>")
        self.assertIn("(Soraka)", line)
        self.assertNotIn("<", line)

    def test_h3_zero_width_and_compat_letters_not_echoed(self) -> None:
        self.assertIn("(Soraka)", self._line("Sor" + _ZERO_WIDTH + "aka"))
        line = self._line(_KELVIN + "ayn")  # KELVIN SIGN lowercases to "k"
        self.assertTrue(line.isascii())
        self.assertIn("(Kayn)", line)

    def test_h3_control_chars_not_echoed(self) -> None:
        self.assertIn("(Dr. Mundo)", self._line("Dr.\nMundo"))
        self.assertIn("(Soraka)", self._line("Soraka\t\t\t."))

    def test_h3_overlong_name_is_not_a_match(self) -> None:
        name = "S" + "." * 500 + "oraka"
        self.assertIsNone(ht.heal_threat_callout([name], [], [], "sr"))
        self.assertEqual(ht.count_heal_sources([name], []), 0)

    def test_h3_name_length_boundary(self) -> None:
        self.assertIsNotNone(
            ht.heal_threat_callout(["Soraka" + " " * 58], [], [], "sr"))
        self.assertIsNone(
            ht.heal_threat_callout(["Soraka" + " " * 59], [], [], "sr"))

    def test_h3_every_display_name_is_ascii_and_round_trips(self) -> None:
        for key, display in ht._SUSTAIN_DISPLAY.items():
            with self.subTest(key=key):
                self.assertTrue(display.isascii())
                self.assertEqual(ht._norm_champ(display), key)
        self.assertEqual(ht._HEAVY_SUSTAIN_CHAMPIONS,
                         frozenset(ht._SUSTAIN_DISPLAY))

    def test_h3_full_roster_line_ascii_and_bounded(self) -> None:
        names = [ht._SUSTAIN_DISPLAY[k] for k in sorted(ht._SUSTAIN_DISPLAY)]
        out = ht.heal_threat_callout(names, [], [], "sr")
        self.assertIsNotNone(out)
        self.assertTrue(out["line"].isascii())
        self.assertLessEqual(len(out["line"]), 120)
        self.assertIn(f"+{len(names) - 2}", out["line"])

    def test_char_curated_roster_unchanged(self) -> None:
        self.assertEqual(ht._HEAVY_SUSTAIN_CHAMPIONS, frozenset({
            "aatrox", "briar", "drmundo", "fiddlesticks", "illaoi", "kayn",
            "maokai", "mordekaiser", "nilah", "renekton", "sett", "soraka",
            "swain", "sylas", "trundle", "tryndamere", "vladimir", "volibear",
            "warwick", "yuumi", "zac"}))


if __name__ == "__main__":
    unittest.main()
