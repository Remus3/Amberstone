"""
Lane 8 (Headless-True-Audit) - RM-286 regression corpus for
`tft/tft_pbe_engine.py` config adoption.

RM-286 says: TftPbeCoachEngine.__init__ adopts `config/coach_settings.json`
VERBATIM with no type or range check (tft/tft_pbe_engine.py:355-362), so a
string `debounce_seconds` is stored as a string and then raises TypeError out
of `submit()` at tft/tft_pbe_engine.py:387, where it computes
`(now - self._last_call) < self._debounce_s`. The exception escapes into the
TFT poll loop. The twin engine `tft/tft_coach_engine.py` already ships the
guard as `_apply_config` (tft/tft_coach_engine.py:625); the PBE engine does
not, so the two siblings disagree about the same file.

MEASURED RED AT HEAD (506f81e8): 45 failed, 3 passed. Red in two independent
ways, which is deliberate:

  * Every test that calls `_apply_config` fails with AttributeError, because
    the method does not exist on TftPbeCoachEngine yet. That only documents
    the ABSENCE of the fix.
  * TestUnderlyingDefect calls NO new method at all. It builds the engine
    against a hostile on-disk config and drives the real `submit()` path, and
    it fails with the production fault verbatim:
        tft/tft_pbe_engine.py:387: TypeError: '<' not supported between
        instances of 'float' and 'str'
    That documents the BUG, not the missing API, and it stays meaningful even
    if the fix is named something else.

The 3 that were GREEN at HEAD are CHARACTERIZATION tests, not evidence for
the fix. Do not cite them as such. They are:

  * TestConstructorDefaults::test_defaults_are_the_documented_pbe_values -
    pins the baseline the rejection tests measure against.
  * TestUnderlyingDefect::test_non_object_disk_config_keeps_defaults - green
    only by ACCIDENT at HEAD: `["a"].get` raises AttributeError and the bare
    `except Exception: pass` at tft/tft_pbe_engine.py:362-363 swallows it, so
    the defaults survive. The right outcome for the wrong reason. It pins
    that the fix must reach the same outcome deliberately.
  * TestValidConfigIsAdopted::test_a_valid_config_is_adopted_from_disk_at_
    construction - green at HEAD because verbatim adoption happens to be
    correct for a VALID config (22 == 22.0). It pins that __init__ still
    routes the on-disk config into the engine after the guard lands, which is
    the one thing a too-eager fix could break.

The contract pinned here mirrors tft/tft_coach_engine.py:625 exactly, with the
PBE engine's own defaults from tft/tft_pbe_engine.py:351-354 (model
"claude-haiku-4-5-20251001", debounce 15.0, timeout 20, max_tokens 700):

  - a non-dict config warns and keeps every default
  - "model" is adopted only when it is a non-empty string
  - "debounce_seconds" must be a real number in [0, 3600], adopted as float
  - "timeout" must be a real number in [1, 600], adopted as float
  - "max_tokens" must be a real number in [1, 8192], adopted as int
  - bool is REJECTED everywhere a number is required, because bool subclasses
    int and would otherwise be silently accepted as 1 / 0
  - an absent key leaves the current value untouched
  - every rejection logs a WARNING on logger "rc.tft.pbe"

TestValidConfigIsAdopted exists so tests 1-5 cannot pass vacuously: a
validator that refused every input would satisfy all the rejection tests and
still be wrong.

The engine helpers below force the no-config-on-disk case
(`patch.object(Path, "exists", ...)`) so the asserted defaults are the CODE
defaults, not whatever gitignored `config/coach_settings.json` happens to sit
on the box running the suite.
"""

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tft.tft_pbe_engine import TftPbeCoachEngine

# tft/tft_pbe_engine.py:351-354 - the PBE engine's own defaults.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_DEBOUNCE = 15.0
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_TOKENS = 700

LOGGER_NAME = "rc.tft.pbe"


def _engine(tmp: Path) -> TftPbeCoachEngine:
    """Build an engine without touching the real key file or the real config.

    `Path.exists` is forced False so `cfg_path.exists()` in __init__ is False
    and the engine keeps its code defaults. `_read_key_file` is patched out,
    so the only other Path.exists caller in the construction path is gone.
    """
    with patch.object(TftPbeCoachEngine, "_read_key_file", return_value=""), \
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False), \
            patch.object(Path, "exists", return_value=False):
        return TftPbeCoachEngine(tmp / "tft_pbe_coaching_data.json")


def _engine_with_disk_config(tmp: Path, payload) -> TftPbeCoachEngine:
    """Build an engine as if `config/coach_settings.json` held `payload`.

    This drives the REAL construction path at tft/tft_pbe_engine.py:355-362 -
    no test-only entry point - so it exercises the defect as shipped.
    """
    with patch.object(TftPbeCoachEngine, "_read_key_file", return_value=""), \
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False), \
            patch.object(Path, "exists", return_value=True), \
            patch.object(Path, "read_text", return_value=json.dumps(payload)):
        return TftPbeCoachEngine(tmp / "tft_pbe_coaching_data.json")


class _EngineCase(unittest.TestCase):
    """Shared per-test tempdir so nothing is written into the repo."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def engine(self) -> TftPbeCoachEngine:
        return _engine(self.tmp)


class TestConstructorDefaults(_EngineCase):
    """Pins the baseline every rejection test asserts against. If these drift,
    the rejection tests below are measuring the wrong numbers."""

    def test_defaults_are_the_documented_pbe_values(self):
        eng = self.engine()
        self.assertEqual(eng._model, DEFAULT_MODEL)
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)


class TestUnderlyingDefect(_EngineCase):
    """RM-286 itself, with NO reference to the fix's API.

    These call only shipped methods. They are RED at HEAD because the
    production code is wrong, not because a method is missing.
    """

    def test_hostile_disk_config_does_not_break_submit(self):
        # A string debounce reaches `(now - self._last_call) < self._debounce_s`
        # at tft/tft_pbe_engine.py:387 and raises TypeError into the poll loop.
        eng = _engine_with_disk_config(self.tmp, {"debounce_seconds": "45"})
        eng._client = object()
        eng._last_round = (2, 1)   # not a new round, so the debounce branch runs
        with patch.object(threading, "Thread"):
            try:
                eng.submit({"stage": 2, "round": 1, "health": 80})
            except TypeError as exc:
                self.fail(
                    f"submit() raised TypeError on a hostile config "
                    f"(RM-286): {exc}")

    def test_hostile_disk_config_leaves_a_usable_debounce(self):
        eng = _engine_with_disk_config(self.tmp, {"debounce_seconds": "45"})
        self.assertIsInstance(eng._debounce_s, (int, float))
        self.assertNotIsInstance(eng._debounce_s, bool)

    def test_hostile_disk_config_leaves_a_usable_max_tokens(self):
        eng = _engine_with_disk_config(self.tmp, {"max_tokens": "lots"})
        self.assertIsInstance(eng._max_tokens, int)
        self.assertGreaterEqual(eng._max_tokens, 1)

    def test_hostile_disk_config_leaves_a_usable_model(self):
        eng = _engine_with_disk_config(self.tmp, {"model": 12345})
        self.assertIsInstance(eng._model, str)
        self.assertTrue(eng._model.strip())

    def test_non_object_disk_config_keeps_defaults(self):
        # A JSON array parses fine, then `.get` blows up or the values are
        # never adopted at all. Either way the engine must stay usable.
        eng = _engine_with_disk_config(self.tmp, ["not", "an", "object"])
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertEqual(eng._model, DEFAULT_MODEL)


class TestDebounceValidation(_EngineCase):

    def test_non_numeric_debounce_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": "not-a-number"})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertIsInstance(eng._debounce_s, (int, float))

    def test_none_debounce_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": None})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)

    def test_negative_debounce_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": -5})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertGreaterEqual(eng._debounce_s, 0)

    def test_debounce_above_the_maximum_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": 3601})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)

    def test_bool_debounce_is_rejected(self):
        # bool subclasses int, so an isinstance(val, (int, float)) check that
        # does not exclude bool accepts True as a 1.0 second debounce - the
        # engine would then call the API once per second.
        eng = self.engine()
        eng._apply_config({"debounce_seconds": True})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertNotIsInstance(eng._debounce_s, bool)

    def test_bool_false_debounce_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": False})
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)

    def test_boundary_debounce_values_are_accepted(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": 0})
        self.assertEqual(eng._debounce_s, 0.0)
        eng._apply_config({"debounce_seconds": 3600})
        self.assertEqual(eng._debounce_s, 3600.0)


class TestModelValidation(_EngineCase):

    def test_non_string_model_is_rejected(self):
        eng = self.engine()
        before = eng._model
        eng._apply_config({"model": 12345})
        self.assertEqual(eng._model, before)

    def test_empty_string_model_is_rejected(self):
        eng = self.engine()
        before = eng._model
        eng._apply_config({"model": ""})
        self.assertEqual(eng._model, before)

    def test_whitespace_only_model_is_rejected(self):
        eng = self.engine()
        before = eng._model
        eng._apply_config({"model": "   "})
        self.assertEqual(eng._model, before)

    def test_none_model_is_rejected(self):
        eng = self.engine()
        before = eng._model
        eng._apply_config({"model": None})
        self.assertEqual(eng._model, before)

    def test_a_previously_adopted_model_survives_a_later_bad_value(self):
        # "keep the CURRENT value", not "reset to the constructor default".
        eng = self.engine()
        eng._apply_config({"model": "claude-sonnet-4-5-20250929"})
        eng._apply_config({"model": 0})
        self.assertEqual(eng._model, "claude-sonnet-4-5-20250929")


class TestTimeoutValidation(_EngineCase):

    def test_non_numeric_timeout_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"timeout": "y"})
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)

    def test_timeout_below_the_minimum_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"timeout": 0})
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)

    def test_timeout_above_the_maximum_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"timeout": 601})
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)

    def test_bool_timeout_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"timeout": True})
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)
        self.assertNotIsInstance(eng._timeout, bool)


class TestMaxTokensValidation(_EngineCase):

    def test_non_numeric_max_tokens_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": "lots"})
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_max_tokens_below_the_minimum_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": 0})
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_negative_max_tokens_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": -1})
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_max_tokens_above_the_maximum_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": 8193})
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_bool_max_tokens_is_rejected(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": True})
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)
        self.assertNotIsInstance(eng._max_tokens, bool)


class TestValidConfigIsAdopted(_EngineCase):
    """Without these, every rejection test above passes vacuously against a
    validator that simply refuses all input."""

    def test_a_fully_valid_config_is_adopted(self):
        eng = self.engine()
        eng._apply_config({
            "model": "claude-sonnet-4-5-20250929",
            "debounce_seconds": 30,
            "timeout": 45,
            "max_tokens": 900,
        })
        self.assertEqual(eng._model, "claude-sonnet-4-5-20250929")
        self.assertEqual(eng._debounce_s, 30.0)
        self.assertEqual(eng._timeout, 45.0)
        self.assertEqual(eng._max_tokens, 900)

    def test_debounce_is_cast_to_float(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": 30})
        self.assertIsInstance(eng._debounce_s, float)

    def test_timeout_is_cast_to_float(self):
        eng = self.engine()
        eng._apply_config({"timeout": 45})
        self.assertIsInstance(eng._timeout, float)

    def test_max_tokens_is_cast_to_int(self):
        eng = self.engine()
        eng._apply_config({"max_tokens": 900.0})
        self.assertIsInstance(eng._max_tokens, int)
        self.assertEqual(eng._max_tokens, 900)

    def test_a_bad_key_does_not_discard_its_good_siblings(self):
        """Per-key independence - the property the whole corpus missed.

        RM-286's rejection tests all pass single-key dicts and the hostile-config
        test passes an all-bad dict, so an all-or-nothing validator (validate
        every key, warn, then commit only if NOTHING was rejected) passes all of
        them. Measured 2026-09-04 by mutation: that naive variant survived the
        entire 48-test corpus. It is not an equivalent mutant - under it the two
        good keys below fall back to defaults.

        This is the only test in the module with a MIXED good-and-bad config,
        which is what makes it the one that can tell the two apart.
        """
        eng = self.engine()
        eng._apply_config({
            "debounce_seconds": "not-a-number",   # rejected
            "timeout": [],                        # rejected
            "max_tokens": 1234,                   # valid, must survive
            "model": "claude-sonnet-4-5-20250929",  # valid, must survive
        })
        self.assertEqual(eng._max_tokens, 1234)
        self.assertEqual(eng._model, "claude-sonnet-4-5-20250929")
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)

    def test_a_valid_config_is_adopted_from_disk_at_construction(self):
        # The guard is worthless if __init__ never routes through it.
        eng = _engine_with_disk_config(self.tmp, {
            "model": "claude-sonnet-4-5-20250929",
            "debounce_seconds": 22,
            "timeout": 33,
            "max_tokens": 444,
        })
        self.assertEqual(eng._model, "claude-sonnet-4-5-20250929")
        self.assertEqual(eng._debounce_s, 22.0)
        self.assertEqual(eng._timeout, 33.0)
        self.assertEqual(eng._max_tokens, 444)

    def test_a_valid_config_logs_no_warning(self):
        eng = self.engine()
        with self.assertNoLogs(LOGGER_NAME, level="WARNING"):
            eng._apply_config({
                "model": "claude-sonnet-4-5-20250929",
                "debounce_seconds": 30,
                "timeout": 45,
                "max_tokens": 900,
            })


class TestAbsentKeysAndNonDict(_EngineCase):

    def test_an_empty_config_changes_nothing(self):
        eng = self.engine()
        eng._apply_config({})
        self.assertEqual(eng._model, DEFAULT_MODEL)
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_an_absent_key_does_not_reset_an_adopted_value(self):
        eng = self.engine()
        eng._apply_config({"debounce_seconds": 30})
        eng._apply_config({"timeout": 45})
        self.assertEqual(eng._debounce_s, 30.0)
        self.assertEqual(eng._timeout, 45.0)

    def test_an_absent_key_logs_no_warning(self):
        eng = self.engine()
        with self.assertNoLogs(LOGGER_NAME, level="WARNING"):
            eng._apply_config({})

    def test_a_list_config_keeps_every_default(self):
        eng = self.engine()
        eng._apply_config(["debounce_seconds", 30])
        self.assertEqual(eng._model, DEFAULT_MODEL)
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)
        self.assertEqual(eng._timeout, DEFAULT_TIMEOUT)
        self.assertEqual(eng._max_tokens, DEFAULT_MAX_TOKENS)

    def test_a_none_config_keeps_every_default(self):
        eng = self.engine()
        eng._apply_config(None)
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)

    def test_a_string_config_keeps_every_default(self):
        eng = self.engine()
        eng._apply_config("debounce_seconds")
        self.assertEqual(eng._debounce_s, DEFAULT_DEBOUNCE)


class TestRejectionsAreLoud(_EngineCase):
    """A silent degrade is how a mis-typed config survives for months."""

    def test_bad_debounce_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING") as cm:
            eng._apply_config({"debounce_seconds": "x"})
        self.assertTrue(any("debounce" in line.lower() for line in cm.output),
                        cm.output)

    def test_bool_debounce_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING"):
            eng._apply_config({"debounce_seconds": True})

    def test_out_of_range_debounce_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING"):
            eng._apply_config({"debounce_seconds": -5})

    def test_bad_model_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING") as cm:
            eng._apply_config({"model": 12345})
        self.assertTrue(any("model" in line.lower() for line in cm.output),
                        cm.output)

    def test_bad_timeout_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING") as cm:
            eng._apply_config({"timeout": 601})
        self.assertTrue(any("timeout" in line.lower() for line in cm.output),
                        cm.output)

    def test_bad_max_tokens_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING") as cm:
            eng._apply_config({"max_tokens": -1})
        self.assertTrue(any("max_tokens" in line.lower() for line in cm.output),
                        cm.output)

    def test_a_non_dict_config_warns(self):
        eng = self.engine()
        with self.assertLogs(LOGGER_NAME, level="WARNING"):
            eng._apply_config(["not", "an", "object"])


class TestSubmitSurvivesHostileConfig(_EngineCase):
    """The consumer-side proof: the guard has to keep the ONE call site that
    RM-286 names (tft/tft_pbe_engine.py:387) arithmetic."""

    def test_submit_survives_a_hostile_config(self):
        eng = self.engine()
        eng._client = object()
        eng._apply_config({"debounce_seconds": "x", "max_tokens": -1,
                           "timeout": "y"})
        eng._last_round = (2, 1)
        with patch.object(threading, "Thread"):
            eng.submit({"stage": 2, "round": 1, "health": 80})

    def test_submit_still_debounces_after_a_hostile_config(self):
        # Degrading to the default must not degrade to "no debounce at all".
        eng = self.engine()
        eng._client = object()
        eng._apply_config({"debounce_seconds": "x"})
        with patch.object(threading, "Thread") as spawn:
            eng.submit({"stage": 2, "round": 1, "health": 80})   # new round
            eng.submit({"stage": 2, "round": 1, "health": 80})   # debounced
        self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
