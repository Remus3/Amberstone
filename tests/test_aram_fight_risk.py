"""Contract tests for ``core.aram_fight_risk`` (Stage 1 deterministic ARAM coach).

Pure projection (NOT prediction) of the single most dangerous enemy
ability into two short coach strings. Grounded on the enemy CC/threat
ranking shape produced by
``core.enemy_cc_threat_context.enemy_cc_threat_line`` (see
``core/enemy_cc_threat_context.py:149-231``): enemies are ranked
descending by ``total_cc_seconds`` and each renders as
``{champion} {duration:.1f}s {kind} ({spell_key})``. The top (first)
entry is the threat to respect.

The functions under test accept that ranked input in either form:

  * the pre-formatted ``enemy_cc_threat_line`` string
    ("Enemy CC threats: Ashe 3.0s stun (R), ..."), OR
  * a ranked iterable of entries, each a dict or object exposing a
    champion name, a duration, a CC-kind word, and a spell key.

Both functions are fail-soft: empty / malformed / None input returns
"" and NEVER raises.
"""
from __future__ import annotations

import unittest


def _entry(champion, duration, kind, spell_key):
    """A plain-dict threat entry in the grounded shape."""
    return {
        "champion": champion,
        "duration_s": duration,
        "kind": kind,
        "spell_key": spell_key,
    }


def _label(value):
    """Serialization-safe subTest label for an arbitrary hostile value.

    MEASURED 2026-07-26 under ``pytest -n 8``: pytest 9's
    ``_pytest/unittest.py:436`` addSubTest stuffs the RAW ``subTest``
    kwargs into ``SubtestContext(msg=..., kwargs=dict(test.params))``
    and emits a report for EVERY subtest, passing ones included. Under
    xdist that report crosses the execnet channel, and execnet's
    serializer only handles builtin primitives - a bare ``object()``
    raises ``execnet.gateway_base.DumpError: can't serialize <class
    'object'>`` from inside ``subTest.__exit__``, failing the parent
    test. Serially there is no channel, so the same matrix passes.
    Labelling by repr keeps the hostile inputs below byte-identical -
    only the reported label changes.
    """
    return repr(value)


class FightRuleTests(unittest.TestCase):
    """fight_rule -> <=12-word engage condition naming the top threat."""

    def test_normal_top_threat_dict_list(self) -> None:
        from core.aram_fight_risk import fight_rule

        threats = [
            _entry("Ashe", 3.0, "stun", "R"),
            _entry("Annie", 1.5, "stun", "R"),
        ]
        out = fight_rule(threats)
        self.assertIsInstance(out, str)
        self.assertTrue(out)                       # non-empty
        self.assertIn("Ashe", out)                 # names the top threat
        self.assertIn("R", out)                    # names the spell
        self.assertLessEqual(len(out.split()), 12)  # <=12 words

    def test_normal_top_threat_from_formatted_string(self) -> None:
        from core.aram_fight_risk import fight_rule

        line = "Enemy CC threats: Ashe 3.0s stun (R), Annie 1.5s stun (R)"
        out = fight_rule(line)
        self.assertIn("Ashe", out)
        self.assertLessEqual(len(out.split()), 12)

    def test_empty_input_returns_blank(self) -> None:
        from core.aram_fight_risk import fight_rule

        self.assertEqual(fight_rule([]), "")
        self.assertEqual(fight_rule(None), "")
        self.assertEqual(fight_rule(""), "")

    def test_malformed_input_returns_blank_no_raise(self) -> None:
        from core.aram_fight_risk import fight_rule

        for bad in (123, object(), [{"nope": 1}], [None], {"x": "y"}):
            with self.subTest(bad=_label(bad)):
                self.assertEqual(fight_rule(bad), "")


class RiskTests(unittest.TestCase):
    """risk -> <=10-word string naming the single most dangerous ability."""

    def test_normal_top_threat_dict_list(self) -> None:
        from core.aram_fight_risk import risk

        threats = [
            _entry("Ashe", 3.0, "stun", "R"),
            _entry("Malzahar", 2.5, "suppress", "R"),
        ]
        out = risk(threats)
        self.assertIsInstance(out, str)
        self.assertTrue(out)
        self.assertIn("Ashe", out)                 # the single worst
        self.assertNotIn("Malzahar", out)          # only the top one
        self.assertLessEqual(len(out.split()), 10)  # <=10 words

    def test_normal_top_threat_from_formatted_string(self) -> None:
        from core.aram_fight_risk import risk

        line = "Enemy CC threats: Malzahar 2.5s suppress (R), Ashe 3.0s stun (R)"
        out = risk(line)
        # First chunk of the (already-ranked) line is the top threat.
        self.assertIn("Malzahar", out)
        self.assertLessEqual(len(out.split()), 10)

    def test_empty_input_returns_blank(self) -> None:
        from core.aram_fight_risk import risk

        self.assertEqual(risk([]), "")
        self.assertEqual(risk(None), "")
        self.assertEqual(risk(""), "")

    def test_malformed_input_returns_blank_no_raise(self) -> None:
        from core.aram_fight_risk import risk

        for bad in (123, object(), [{"nope": 1}], [None], 3.14):
            with self.subTest(bad=_label(bad)):
                self.assertEqual(risk(bad), "")


class NeverRaisesTests(unittest.TestCase):
    """Belt-and-suspenders: neither function raises on hostile input."""

    def test_no_raise_matrix(self) -> None:
        from core.aram_fight_risk import fight_rule, risk

        hostile = [
            None, "", [], {}, 0, 1.0, object(), [object()],
            [{"champion": None}], "Enemy CC threats: ",
            ["raw string entry"], [["nested"]],
        ]
        for h in hostile:
            with self.subTest(h=_label(h)):
                self.assertIsInstance(fight_rule(h), str)
                self.assertIsInstance(risk(h), str)


if __name__ == "__main__":
    unittest.main()
