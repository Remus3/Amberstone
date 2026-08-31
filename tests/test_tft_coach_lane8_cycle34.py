"""Lane 8 Headless-True-Audit cycle 34 - guards for coaches/tft_coach.py.

Target selected on four risk criteria at once:
  1. it parses text produced by a model it does not author,
  2. it is secret-adjacent - `_read_api_key` reads API-Key-Claude.txt,
  4. it is live-reachable (core/coach_registry.py:5 maps "_tft_mode" to
     coaches.tft_coach:Coach, and app/_game_lifecycle.py:116 importlib-loads
     and constructs it on game start) yet carried NO dedicated test file.

The defects pinned here were each proven by measurement before being fixed,
never by reading the code.

W1  coaches/_base_coach.py:81 `safe_write` NEVER RAISES and returns None on
    success and on every failure path alike, so no caller can tell the two
    apart. `Coach.reset_state` therefore wrapped it in `except Exception:
    pass` - a handler that can never fire - and then logged "TFT state reset
    - data files cleared" unconditionally. On a locked or unwritable data
    file the dashboard keeps rendering the previous game's board while the
    log reports a successful clear.

W2  `_ensure_data_files` and `reset_state` each hardcoded a default payload
    for the SAME tft_live_data.json, and the two copies disagreed: 9 keys
    against 19. Two divergent copies of one contract is the shape that
    `feedback_majority_copy_is_not_the_current_copy` exists to catch.

W3  `_coach_board_to_placement` assigned TWO UNITS THE SAME HEX once a class
    held more members than its hardcoded column list - measured, e.g. three
    mages returned "Anivia D4, Swain D4" and six tanks returned both
    "Delta A7" and "Foxtrot A7" while also running non-monotonically
    (A7 then A6). TFT allows one unit per hex, so the advice was actionably
    wrong. The pre-existing smoke test in
    tests/phase2_smoke/test_coach_state_parsing.py could never catch it: it
    only ever passes "Jinx Caitlyn Lulu", which is exactly two ranged units,
    the one arity at which no collision occurs.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from coaches import _base_coach  # noqa: E402
from coaches.tft_coach import Coach, _coach_board_to_placement  # noqa: E402


def _hexes(placement: str) -> list[str]:
    """The hex label of every unit in a placement string, in order."""
    out = []
    for chunk in placement.split(","):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk.rsplit(" ", 1)[-1])
    return out


class TestSafeWriteReportsOutcome(unittest.TestCase):
    """W1 root cause: the writer must tell its caller whether it wrote."""

    def test_returns_true_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "ok.json"
            self.assertIs(_base_coach.safe_write(target, {"a": 1}), True)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})

    def test_returns_false_when_the_payload_is_not_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bad.json"
            self.assertIs(_base_coach.safe_write(target, {"a": object()}), False)

    def test_returns_false_when_the_directory_does_not_exist(self):
        missing = Path(tempfile.gettempdir()) / "rc-cycle34-absent-dir" / "x.json"
        self.assertIs(_base_coach.safe_write(missing, {"a": 1}), False)


class TestResetStateDetectsWriteFailure(unittest.TestCase):
    """W1 consumer: a failed clear must not be logged as a successful one."""

    def _coach(self, td: str) -> Coach:
        return Coach(Path(td) / "tft_coaching_data.json")

    def test_reset_state_returns_false_and_logs_when_writes_fail(self):
        with tempfile.TemporaryDirectory() as td:
            coach = self._coach(td)
            original = _base_coach.safe_write
            try:
                _base_coach.safe_write = lambda *_a, **_k: False
                import coaches.tft_coach as mod

                mod.safe_write = lambda *_a, **_k: False
                with self.assertLogs("rc.coaches.tft", level=logging.WARNING) as cap:
                    ok = coach.reset_state()
            finally:
                _base_coach.safe_write = original
                import coaches.tft_coach as mod

                mod.safe_write = original
            self.assertIs(ok, False)
            joined = " ".join(cap.output).lower()
            self.assertNotIn("data files cleared", joined)

    def test_reset_state_returns_true_when_writes_succeed(self):
        with tempfile.TemporaryDirectory() as td:
            coach = self._coach(td)
            self.assertIs(coach.reset_state(), True)

    def test_reset_state_recreates_a_data_dir_that_vanished(self):
        """The live route to the old false success.

        Only `_ensure_data_files` created the parent directory, so a reset
        against a missing data/ wrote nothing while still logging that the
        files had been cleared.
        """
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "data"
            coach = Coach(nested / "tft_coaching_data.json")
            for child in nested.iterdir():
                child.unlink()
            nested.rmdir()
            self.assertFalse(nested.exists())

            self.assertIs(coach.reset_state(), True)
            self.assertTrue((nested / "tft_live_data.json").exists())


class TestDefaultPayloadsDoNotDiverge(unittest.TestCase):
    """W2: one file, one contract - not two hardcoded copies that disagree."""

    def test_ensure_and_reset_write_the_same_live_default_keys(self):
        with tempfile.TemporaryDirectory() as td:
            coach = Coach(Path(td) / "tft_coaching_data.json")
            live = Path(td) / "tft_live_data.json"

            after_reset = set(json.loads(live.read_text(encoding="utf-8")))
            live.unlink()
            coach._ensure_data_files()
            after_ensure = set(json.loads(live.read_text(encoding="utf-8")))

            self.assertEqual(after_ensure, after_reset)

    def test_live_default_retains_the_richer_shape(self):
        with tempfile.TemporaryDirectory() as td:
            Coach(Path(td) / "tft_coaching_data.json")
            live = json.loads(
                (Path(td) / "tft_live_data.json").read_text(encoding="utf-8")
            )
            for key in (
                "stage_round",
                "level",
                "hp",
                "board_units",
                "bench_units",
                "shop_units",
                "traits_active",
                "augments",
                "unit_placement",
                "unit_swap",
            ):
                self.assertIn(key, live)


class TestPlacementAssignsUniqueHexes(unittest.TestCase):
    """W3: one unit per hex. Measured collisions, one test per arity."""

    def test_three_mages_do_not_share_a_hex(self):
        got = _hexes(_coach_board_to_placement("Lissandra Anivia Swain"))
        self.assertEqual(len(got), len(set(got)), got)

    def test_three_ranged_do_not_share_a_hex(self):
        got = _hexes(_coach_board_to_placement("Ashe Jinx Caitlyn"))
        self.assertEqual(len(got), len(set(got)), got)

    def test_six_tanks_do_not_share_a_hex(self):
        got = _hexes(
            _coach_board_to_placement("Alpha Bravo Charlie Delta Echo Foxtrot")
        )
        self.assertEqual(len(got), len(set(got)), got)

    def test_a_full_mixed_board_never_collides(self):
        got = _hexes(
            _coach_board_to_placement(
                "Alpha Bravo Charlie Delta Echo Foxtrot "
                "Lissandra Anivia Swain Brand "
                "Ashe Jinx Caitlyn Vayne"
            )
        )
        self.assertEqual(len(got), len(set(got)), got)

    def test_overflowing_a_class_preference_list_still_never_collides(self):
        """Exercises the board-wide fallback, not just the preference lists.

        Each class has a preferred column list (14 hexes for tanks); a 15th
        tank has to fall through to the whole-board scan. A mutation removing
        the occupancy check on THAT loop survived until this test existed,
        because every other fixture stopped short of the fallback.
        """
        names = " ".join(f"Tank{chr(65 + i)}unit" for i in range(18))
        got = _hexes(_coach_board_to_placement(names))
        self.assertEqual(len(got), len(set(got)), got)
        self.assertGreaterEqual(len(got), 15)

    def test_a_board_larger_than_the_grid_drops_units_rather_than_stacking(self):
        names = " ".join(f"Tank{i:03d}aaa" for i in range(40))
        got = _hexes(_coach_board_to_placement(names))
        self.assertEqual(len(got), len(set(got)), got)
        self.assertLessEqual(len(got), 28)

    def test_every_named_unit_still_appears(self):
        out = _coach_board_to_placement("Lissandra Anivia Swain")
        for name in ("Lissandra", "Anivia", "Swain"):
            self.assertIn(name, out)

    def test_hex_columns_stay_within_the_seven_wide_board(self):
        placement = _coach_board_to_placement(
            "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel"
        )
        for hexid in _hexes(placement):
            self.assertRegex(hexid, r"^[A-D][1-7]$")


class TestPlacementInputValidation(unittest.TestCase):
    """4f: what happens on merely WRONG input, not just abusive input.

    board_text originates in a model response, so a wrong-typed value is a
    realistic upstream shape change rather than a hypothetical.
    """

    def test_none_and_empty_return_empty_string(self):
        for value in (None, "", "\u2014"):
            self.assertEqual(_coach_board_to_placement(value), "")

    def test_wrong_typed_input_returns_empty_rather_than_raising(self):
        for value in ({"a": 1}, ["Jinx"], 5, b"Jinx", 3.5):
            self.assertEqual(_coach_board_to_placement(value), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
