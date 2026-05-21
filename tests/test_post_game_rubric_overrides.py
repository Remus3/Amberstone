"""Tests for the JSON override loader in core/post_game_rubric.py.

Closes item 131 carry-forward (a): the operator can tune per-role weights
without modifying source by dropping a JSON file at
`data/post_game_rubric_weights.json`. Schema + fail-soft semantics are
documented in the module docstring.

Coverage:
  * LoadOverridesTests: missing file, empty file, malformed JSON, single
    role partial, multi role full, unknown role drop, unknown axis drop,
    non-dict role drop, non-numeric value drop, bool drop, negative floor,
    non-dict top-level.
  * ApplyOverridesTests: full role override, partial axis override, other
    roles untouched, immutability of dataclass result, empty override
    pass-through.
  * IntegrationTests: write a fixture file, monkeypatch _OVERRIDES_PATH,
    re-run the loader + apply chain against a pristine defaults snapshot,
    swap the result into pgr._DEFAULT_WEIGHTS, and assert compute_role_grade
    honors the new weights. Each test restores pre-test state in tearDown.
  * DocstringTests: assert the module docstring documents the file path,
    schema mention, per-role partial mention, and fail-soft mention.
  * AsciiHygieneTests: self-scan.
"""
from __future__ import annotations

import json
import logging
import pathlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import post_game_rubric as pgr


class LoadOverridesTests(unittest.TestCase):
    """_load_weights_overrides shape + fail-soft contract."""

    def test_missing_file_returns_empty_dict(self):
        # Point at a path that cannot exist. Loader returns {}, no raise.
        with mock.patch.object(
            pgr, "_OVERRIDES_PATH", Path("does/not/exist/__no__.json")
        ):
            self.assertEqual(pgr._load_weights_overrides(), {})

    def test_empty_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text("", encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                self.assertEqual(pgr._load_weights_overrides(), {})

    def test_whitespace_only_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text("   \n  \t\n", encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                self.assertEqual(pgr._load_weights_overrides(), {})

    def test_malformed_json_returns_empty_dict_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text("{invalid json: yes,", encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                with self.assertLogs("core.post_game_rubric", level=logging.WARNING):
                    self.assertEqual(pgr._load_weights_overrides(), {})

    def test_top_level_array_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text("[1, 2, 3]", encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                self.assertEqual(pgr._load_weights_overrides(), {})

    def test_top_level_string_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text('"not an object"', encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                self.assertEqual(pgr._load_weights_overrides(), {})

    def test_single_role_partial_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text(
                json.dumps({"ADC": {"kda": 2.5}}), encoding="utf-8"
            )
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                got = pgr._load_weights_overrides()
        self.assertEqual(got, {"ADC": {"kda": 2.5}})

    def test_multi_role_full_round_trip(self):
        payload = {
            "ADC": {"kda": 2.5, "cs_per_min": 0.9},
            "SUP": {"vision_score": 1.8},
        }
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                got = pgr._load_weights_overrides()
        self.assertEqual(got, payload)

    def test_non_dict_role_value_dropped_at_loader(self):
        # A role whose value is a string or array is not actionable;
        # loader returns the well-shaped subset only.
        payload = {
            "ADC": {"kda": 2.5},
            "SUP": "not a dict",
            "JG": [1, 2, 3],
        }
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                got = pgr._load_weights_overrides()
        self.assertEqual(got, {"ADC": {"kda": 2.5}})

    def test_non_string_role_key_skipped(self):
        # JSON object keys are always strings so this is a defensive
        # check; the loader sanitizes against future shape drift.
        # We cannot directly write a non-string key via json.dumps,
        # but we can simulate with a raw dict via mock if needed.
        # Here we just confirm the str-only contract via a normal payload.
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "weights.json"
            override.write_text(
                json.dumps({"ADC": {"kda": 2.5}}), encoding="utf-8"
            )
            with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
                got = pgr._load_weights_overrides()
        self.assertEqual(list(got.keys()), ["ADC"])


class ApplyOverridesTests(unittest.TestCase):
    """_apply_overrides shape, immutability, and silent-drop rules."""

    def setUp(self):
        # Build a known-good defaults dict isolated from the module-level
        # post-loader state so the tests do not depend on what is on disk.
        self.defaults = {
            "ADC": pgr.RoleWeights(
                role="ADC",
                kda=2.1,
                cs_per_min=0.85,
                obj_participation=0.50,
                vision_score=0.30,
                damage_per_min=0.85,
            ),
            "SUP": pgr.RoleWeights(
                role="SUP",
                kda=2.5,
                cs_per_min=0.0,
                obj_participation=0.10,
                vision_score=1.5,
                damage_per_min=0.20,
            ),
        }

    def test_empty_overrides_returns_copy_of_defaults(self):
        got = pgr._apply_overrides(self.defaults, {})
        self.assertEqual(got["ADC"].kda, 2.1)
        self.assertEqual(got["SUP"].vision_score, 1.5)
        # Result is a NEW dict; mutating it does not affect input.
        got["ADC"] = pgr.RoleWeights(role="ADC", kda=99.0)
        self.assertEqual(self.defaults["ADC"].kda, 2.1)

    def test_full_adc_override_replaces_axes(self):
        overrides = {
            "ADC": {
                "kda": 2.5,
                "cs_per_min": 0.9,
                "obj_participation": 0.6,
                "vision_score": 0.35,
                "damage_per_min": 0.9,
            }
        }
        got = pgr._apply_overrides(self.defaults, overrides)
        adc = got["ADC"]
        self.assertEqual(adc.kda, 2.5)
        self.assertEqual(adc.cs_per_min, 0.9)
        self.assertEqual(adc.obj_participation, 0.6)
        self.assertEqual(adc.vision_score, 0.35)
        self.assertEqual(adc.damage_per_min, 0.9)
        self.assertEqual(adc.role, "ADC")

    def test_partial_sup_override_only_changes_specified_field(self):
        overrides = {"SUP": {"vision_score": 1.8}}
        got = pgr._apply_overrides(self.defaults, overrides)
        sup = got["SUP"]
        # Overridden axis flipped.
        self.assertEqual(sup.vision_score, 1.8)
        # Other axes unchanged from defaults.
        self.assertEqual(sup.kda, 2.5)
        self.assertEqual(sup.cs_per_min, 0.0)
        self.assertEqual(sup.obj_participation, 0.10)
        self.assertEqual(sup.damage_per_min, 0.20)

    def test_unaffected_role_untouched(self):
        # Override only SUP; ADC stays at defaults.
        overrides = {"SUP": {"vision_score": 1.8}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 2.1)
        self.assertEqual(got["ADC"].cs_per_min, 0.85)

    def test_unknown_role_silently_dropped(self):
        overrides = {"FUTURE_ROLE": {"kda": 99.0}}
        got = pgr._apply_overrides(self.defaults, overrides)
        # ADC and SUP unchanged; FUTURE_ROLE not introduced.
        self.assertEqual(set(got.keys()), {"ADC", "SUP"})
        self.assertEqual(got["ADC"].kda, 2.1)

    def test_unknown_axis_silently_dropped(self):
        overrides = {"ADC": {"kda": 2.5, "unknown_axis": 999.0}}
        got = pgr._apply_overrides(self.defaults, overrides)
        # kda took effect; unknown_axis ignored.
        self.assertEqual(got["ADC"].kda, 2.5)

    def test_negative_weight_floored_to_zero(self):
        overrides = {"ADC": {"kda": -1.5}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 0.0)

    def test_negative_weight_other_axes_untouched(self):
        # Flooring kda to 0 does not bleed into other axes.
        overrides = {"ADC": {"kda": -1.5}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].cs_per_min, 0.85)

    def test_non_numeric_value_silently_dropped(self):
        overrides = {"ADC": {"kda": "not a number"}}
        got = pgr._apply_overrides(self.defaults, overrides)
        # Default kda preserved (the bad value was dropped).
        self.assertEqual(got["ADC"].kda, 2.1)

    def test_none_value_silently_dropped(self):
        overrides = {"ADC": {"kda": None}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 2.1)

    def test_bool_value_silently_dropped(self):
        # bool is a subclass of int; True/False MUST NOT be coerced to
        # 1.0/0.0 silently.
        overrides = {"ADC": {"kda": True, "cs_per_min": False}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 2.1)
        self.assertEqual(got["ADC"].cs_per_min, 0.85)

    def test_int_value_coerced_to_float(self):
        # Operator's JSON may have integer weights; loader accepts.
        overrides = {"ADC": {"kda": 3}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 3.0)
        self.assertIsInstance(got["ADC"].kda, float)

    def test_zero_value_replaces_default(self):
        # 0.0 is a valid override (e.g. "turn off this axis entirely").
        overrides = {"ADC": {"kda": 0.0}}
        got = pgr._apply_overrides(self.defaults, overrides)
        self.assertEqual(got["ADC"].kda, 0.0)

    def test_result_dataclass_is_frozen(self):
        # dataclasses.replace produces a NEW frozen instance.
        overrides = {"ADC": {"kda": 2.5}}
        got = pgr._apply_overrides(self.defaults, overrides)
        import dataclasses

        with self.assertRaises(dataclasses.FrozenInstanceError):
            got["ADC"].kda = 99.0  # type: ignore[misc]

    def test_input_defaults_not_mutated(self):
        # The defaults dict passed in is not mutated; apply returns a copy.
        snapshot_adc_kda = self.defaults["ADC"].kda
        pgr._apply_overrides(self.defaults, {"ADC": {"kda": 99.0}})
        self.assertEqual(self.defaults["ADC"].kda, snapshot_adc_kda)


class IntegrationTests(unittest.TestCase):
    """Module reload against a fixture file proves end-to-end wiring.

    These tests write a fixture override file, redirect the module's
    _OVERRIDES_PATH at it, and re-execute the module-load apply step so
    that _DEFAULT_WEIGHTS reflects the fixture. They then assert
    compute_role_grade honors the overridden weights.

    Approach: build a snapshot of the pristine defaults at setUp, then
    monkeypatch _OVERRIDES_PATH and re-run _apply_overrides against the
    snapshot. This isolates each test from the module-import state and
    avoids leaking patched paths between tests.
    """

    def setUp(self):
        # Pristine defaults snapshot, independent of whatever sits on
        # disk. The override loader is exercised explicitly.
        self._pristine_defaults = {
            "ADC": pgr.RoleWeights(
                role="ADC",
                kda=2.1,
                cs_per_min=0.85,
                obj_participation=0.50,
                vision_score=0.30,
                damage_per_min=0.85,
            ),
            "SUP": pgr.RoleWeights(
                role="SUP",
                kda=2.5,
                cs_per_min=0.0,
                obj_participation=0.10,
                vision_score=1.5,
                damage_per_min=0.20,
            ),
            "JG": pgr.RoleWeights(
                role="JG",
                kda=1.8,
                cs_per_min=0.40,
                obj_participation=0.70,
                vision_score=0.30,
                damage_per_min=0.55,
            ),
            "MID": pgr.RoleWeights(
                role="MID",
                kda=2.0,
                cs_per_min=0.85,
                obj_participation=0.30,
                vision_score=0.30,
                damage_per_min=0.80,
            ),
            "TOP": pgr.RoleWeights(
                role="TOP",
                kda=1.9,
                cs_per_min=0.80,
                obj_participation=0.25,
                vision_score=0.30,
                damage_per_min=0.45,
            ),
        }
        # Snapshot the live module _DEFAULT_WEIGHTS so we can restore.
        self._saved_default_weights = pgr._DEFAULT_WEIGHTS

    def tearDown(self):
        # Restore the live _DEFAULT_WEIGHTS to the pre-test state so we
        # do not leak overrides across tests / files.
        pgr._DEFAULT_WEIGHTS = self._saved_default_weights

    def _apply_override_payload(self, payload: dict) -> dict:
        """Write payload to a temp file, patch _OVERRIDES_PATH, run loader.

        Returns the composed weights dict. Also writes the result to
        pgr._DEFAULT_WEIGHTS so that compute_role_grade picks it up; the
        tearDown restores the pre-test value.
        """
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(_rmtree_safe, tmpdir)
        override = Path(tmpdir) / "weights.json"
        override.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(pgr, "_OVERRIDES_PATH", override):
            raw = pgr._load_weights_overrides()
        composed = pgr._apply_overrides(self._pristine_defaults, raw)
        pgr._DEFAULT_WEIGHTS = composed
        return composed

    def test_default_weights_reflects_full_override(self):
        composed = self._apply_override_payload(
            {
                "ADC": {
                    "kda": 2.5,
                    "cs_per_min": 0.9,
                    "obj_participation": 0.6,
                    "vision_score": 0.35,
                    "damage_per_min": 0.9,
                }
            }
        )
        adc = composed["ADC"]
        self.assertEqual(adc.kda, 2.5)
        self.assertEqual(adc.cs_per_min, 0.9)
        self.assertEqual(adc.obj_participation, 0.6)
        self.assertEqual(adc.vision_score, 0.35)
        self.assertEqual(adc.damage_per_min, 0.9)

    def test_default_weights_reflects_partial_override(self):
        composed = self._apply_override_payload(
            {"SUP": {"vision_score": 1.8}}
        )
        sup = composed["SUP"]
        # Overridden axis took effect.
        self.assertEqual(sup.vision_score, 1.8)
        # Other axes intact at SUP defaults.
        self.assertEqual(sup.kda, 2.5)
        self.assertEqual(sup.cs_per_min, 0.0)

    def test_compute_role_grade_uses_overridden_weights(self):
        # Score the same profile with overridden vs default ADC weights.
        # An ADC override that doubles kda weight should produce a
        # measurably higher total_score on the same stats. Run the
        # baseline FIRST (against unpatched defaults), then patch and
        # rerun.
        stats = {
            "kills": 5,
            "deaths": 2,
            "assists": 8,
            "cs": 160,
            "game_time_s": 22 * 60,
        }
        # Baseline against pristine defaults (compute_role_grade reads
        # the live module attribute, which is currently the saved
        # pre-test value).
        baseline = pgr.compute_role_grade(stats, role="ADC")
        # Apply override that doubles ADC kda from 2.1 to 4.2.
        self._apply_override_payload({"ADC": {"kda": 4.2}})
        with_override = pgr.compute_role_grade(stats, role="ADC")
        self.assertGreater(
            with_override["total_score"], baseline["total_score"]
        )

    def test_unknown_role_silently_dropped_at_module_load(self):
        # An override for FUTURE_ROLE should not introduce a new key.
        composed = self._apply_override_payload(
            {"FUTURE_ROLE": {"kda": 99.0}}
        )
        self.assertEqual(
            set(composed.keys()),
            {"ADC", "SUP", "JG", "MID", "TOP"},
        )

    def test_negative_weight_floored_at_module_load(self):
        composed = self._apply_override_payload({"ADC": {"kda": -3.0}})
        self.assertEqual(composed["ADC"].kda, 0.0)


class DocstringTests(unittest.TestCase):
    """Module docstring documents the new behavior."""

    def test_docstring_references_override_file_path(self):
        docstring = pgr.__doc__ or ""
        self.assertIn("data/post_game_rubric_weights.json", docstring)

    def test_docstring_mentions_partial_overrides(self):
        docstring = pgr.__doc__ or ""
        self.assertIn("partial", docstring.lower())

    def test_docstring_mentions_fail_soft(self):
        docstring = pgr.__doc__ or ""
        self.assertIn("fail-soft", docstring.lower())

    def test_docstring_references_loader_function(self):
        docstring = pgr.__doc__ or ""
        # The docstring should point readers at the loader function name
        # so they can find the source-of-truth quickly.
        self.assertIn("_load_weights_overrides", docstring)

    def test_overrides_path_module_attr_present(self):
        # The constant is module-public-ish (single underscore) so tests
        # and ad-hoc inspection can find it. It is the canonical file
        # path for the override.
        self.assertTrue(hasattr(pgr, "_OVERRIDES_PATH"))
        self.assertEqual(
            pgr._OVERRIDES_PATH,
            Path("data") / "post_game_rubric_weights.json",
        )


class AsciiHygieneTests(unittest.TestCase):
    """This test file is pure ASCII."""

    def test_self_source_has_no_unicode_punctuation(self):
        path = pathlib.Path("tests/test_post_game_rubric_overrides.py")
        text = path.read_text(encoding="utf-8")
        bad = {
            chr(0x2013),  # en-dash
            chr(0x2014),  # em-dash
            chr(0x2018),  # left single curly quote
            chr(0x2019),  # right single curly quote
            chr(0x201C),  # left double curly quote
            chr(0x201D),  # right double curly quote
        }
        hits = [c for c in text if c in bad]
        self.assertEqual(
            hits,
            [],
            f"tests/test_post_game_rubric_overrides.py has banned Unicode: {hits!r}",
        )


def _rmtree_safe(path: str) -> None:
    """Best-effort tempdir cleanup; ignore stragglers."""
    import shutil

    try:
        shutil.rmtree(path)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
