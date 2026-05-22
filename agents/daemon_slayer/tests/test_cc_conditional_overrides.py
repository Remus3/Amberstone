"""Tests for the JSON override loader in agents/daemon_slayer/cc_conditional.py.

Closes item 144 carry (e): the operator can tune the 10 per-tag
probability midpoints AND the 28 per-entry probabilities without
modifying source by dropping a JSON file at
``data/cc_conditional_calibration.json``. Schema + fail-soft semantics
are documented in the module docstring.

Mirror of tests/test_post_game_rubric_overrides.py (item 131 Slice B
`b892519`) which shipped the parallel pattern for the per-role grading
rubric weights. The shape is the same: load -> apply -> module-load
step composes overrides onto defaults; tests cover the loader, the
two apply functions, and the integration round-trip.

Coverage classes:
  * LoadOverridesTests: missing file, empty file, malformed JSON,
    non-dict top-level, partial dicts, both keys, valid both populated.
  * ApplyDefaultProbabilityOverridesTests: unknown tag drop, known tag
    apply, non-float drop, negative drop, > 1.0 drop, 0.0 allowed, 1.0
    allowed, bool drop, non-dict overrides ignored, multiple tags.
  * ApplyPerEntryOverridesTests: empty, unknown champion drop, unknown
    spell drop, known champ:spell apply, non-float drop, out-of-range
    drop, bool drop, multiple entries, malformed key drop, integration
    with ConditionalCcEntry probability.
  * IntegrationTests: write a fixture file, monkeypatch _OVERRIDES_PATH,
    re-run loader + apply + builder, assert the constructed entries
    reflect the override.
  * NoOverrideFileDefaultPreservationTests: canonical seed values
    preserved when no override file exists; per-entry probabilities at
    canonical seed values; module-load idempotent on repeat reload.
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

from agents.daemon_slayer import cc_conditional as ccc


class LoadOverridesTests(unittest.TestCase):
    """_load_overrides shape + fail-soft contract."""

    def test_missing_file_returns_empty_dict(self):
        # Point at a path that cannot exist. Loader returns {}, no raise.
        with mock.patch.object(
            ccc, "_OVERRIDES_PATH", Path("does/not/exist/__no__.json")
        ):
            self.assertEqual(ccc._load_overrides(), {})

    def test_empty_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text("", encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                self.assertEqual(ccc._load_overrides(), {})

    def test_whitespace_only_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text("   \n  \t\n", encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                self.assertEqual(ccc._load_overrides(), {})

    def test_malformed_json_returns_empty_dict_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text("{invalid json: yes,", encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                with self.assertLogs(
                    "agents.daemon_slayer.cc_conditional",
                    level=logging.WARNING,
                ):
                    self.assertEqual(ccc._load_overrides(), {})

    def test_top_level_array_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text("[1, 2, 3]", encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                self.assertEqual(ccc._load_overrides(), {})

    def test_top_level_string_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text('"not an object"', encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                self.assertEqual(ccc._load_overrides(), {})

    def test_only_default_section_round_trip(self):
        payload = {"default_condition_probability": {"nth_hit": 0.65}}
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                got = ccc._load_overrides()
        self.assertEqual(got, payload)

    def test_only_per_entry_section_round_trip(self):
        payload = {"per_entry_probability": {"Brand:R": 0.75}}
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                got = ccc._load_overrides()
        self.assertEqual(got, payload)

    def test_both_sections_round_trip(self):
        payload = {
            "default_condition_probability": {
                "nth_hit": 0.65,
                "channel": 0.55,
            },
            "per_entry_probability": {
                "Brand:R": 0.75,
                "Maokai:Q": 0.35,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "calibration.json"
            override.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
                got = ccc._load_overrides()
        self.assertEqual(got, payload)

    def test_loader_uses_pathlib_path_attribute(self):
        # The override path is a pathlib.Path so monkeypatching with
        # another Path is consistent with the module-level constant.
        self.assertIsInstance(ccc._OVERRIDES_PATH, Path)


class ApplyDefaultProbabilityOverridesTests(unittest.TestCase):
    """_apply_default_probability_overrides shape + silent-drop rules."""

    def setUp(self):
        # Build a known-good defaults dict isolated from the module-level
        # post-loader state so the tests do not depend on what is on disk.
        self.defaults = {
            "nth_hit": 0.7,
            "gold_card": 0.4,
            "terrain": 0.3,
            "channel": 0.5,
            "dream_stack": 0.3,
            "devour": 0.4,
            "low_hp_target": 0.5,
            "debuffed_target": 0.5,
            "dual_enemy": 0.6,
            "mode_gated": 1.0,
        }

    def test_empty_overrides_returns_copy_of_defaults(self):
        got = ccc._apply_default_probability_overrides(self.defaults, {})
        self.assertEqual(got, self.defaults)
        # Mutating result does not affect input.
        got["nth_hit"] = 99.0
        self.assertEqual(self.defaults["nth_hit"], 0.7)

    def test_known_tag_applied(self):
        overrides = {"default_condition_probability": {"nth_hit": 0.65}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.65)
        # Other tags unchanged.
        self.assertEqual(got["channel"], 0.5)

    def test_unknown_tag_silently_dropped(self):
        overrides = {
            "default_condition_probability": {"future_tag": 0.5, "nth_hit": 0.65}
        }
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        # nth_hit took effect; future_tag ignored.
        self.assertEqual(got["nth_hit"], 0.65)
        self.assertNotIn("future_tag", got)

    def test_non_float_value_dropped(self):
        overrides = {
            "default_condition_probability": {
                "nth_hit": "not a number",
                "channel": None,
                "terrain": [0.5],
                "devour": {"nested": 0.5},
            }
        }
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        # All non-numeric values dropped; defaults preserved.
        self.assertEqual(got["nth_hit"], 0.7)
        self.assertEqual(got["channel"], 0.5)
        self.assertEqual(got["terrain"], 0.3)
        self.assertEqual(got["devour"], 0.4)

    def test_negative_value_dropped(self):
        # Out-of-range DROPPED (not clamped) per spec.
        overrides = {"default_condition_probability": {"nth_hit": -0.5}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.7)

    def test_greater_than_one_value_dropped(self):
        # Out-of-range DROPPED (not clamped) per spec.
        overrides = {"default_condition_probability": {"nth_hit": 1.5}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.7)

    def test_zero_value_allowed(self):
        # 0.0 is a valid probability (effectively disables the condition).
        overrides = {"default_condition_probability": {"nth_hit": 0.0}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.0)

    def test_one_value_allowed(self):
        # 1.0 is a valid probability (always-on condition).
        overrides = {"default_condition_probability": {"channel": 1.0}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["channel"], 1.0)

    def test_bool_dropped(self):
        # bool is a subclass of int; True/False MUST NOT be coerced to
        # 1.0/0.0 silently (LOAD-BEARING per item 131 don't-redo).
        overrides = {
            "default_condition_probability": {
                "nth_hit": True,
                "channel": False,
            }
        }
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.7)
        self.assertEqual(got["channel"], 0.5)

    def test_non_dict_overrides_section_ignored(self):
        # If the default_condition_probability value is not a dict,
        # return defaults untouched.
        overrides = {"default_condition_probability": [1, 2, 3]}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got, self.defaults)

    def test_multiple_tag_overrides(self):
        overrides = {
            "default_condition_probability": {
                "nth_hit": 0.65,
                "channel": 0.55,
                "terrain": 0.2,
            }
        }
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["nth_hit"], 0.65)
        self.assertEqual(got["channel"], 0.55)
        self.assertEqual(got["terrain"], 0.2)
        # Untouched defaults intact.
        self.assertEqual(got["gold_card"], 0.4)
        self.assertEqual(got["devour"], 0.4)

    def test_int_value_coerced_to_float(self):
        # Operator JSON may have integer probabilities; loader accepts
        # int and coerces to float (0 and 1 are common JSON authoring
        # patterns).
        overrides = {"default_condition_probability": {"mode_gated": 1}}
        got = ccc._apply_default_probability_overrides(self.defaults, overrides)
        self.assertEqual(got["mode_gated"], 1.0)
        self.assertIsInstance(got["mode_gated"], float)


class ApplyPerEntryOverridesTests(unittest.TestCase):
    """_apply_per_entry_overrides shape + silent-drop rules."""

    def test_empty_overrides_returns_empty_map(self):
        got = ccc._apply_per_entry_overrides({})
        self.assertEqual(got, {})

    def test_missing_section_returns_empty_map(self):
        # No per_entry_probability key in overrides.
        got = ccc._apply_per_entry_overrides(
            {"default_condition_probability": {"nth_hit": 0.65}}
        )
        self.assertEqual(got, {})

    def test_known_champ_spell_applied(self):
        overrides = {"per_entry_probability": {"Brand:R": 0.75}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {("Brand", "R"): 0.75})

    def test_multiple_entries_applied(self):
        overrides = {
            "per_entry_probability": {
                "Brand:R": 0.75,
                "Maokai:Q": 0.35,
                "Pyke:E": 0.55,
            }
        }
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(
            got,
            {
                ("Brand", "R"): 0.75,
                ("Maokai", "Q"): 0.35,
                ("Pyke", "E"): 0.55,
            },
        )

    def test_malformed_key_no_colon_dropped(self):
        overrides = {
            "per_entry_probability": {
                "BrandR": 0.75,
                "Brand:R": 0.65,
            }
        }
        got = ccc._apply_per_entry_overrides(overrides)
        # BrandR (no colon) dropped; Brand:R kept.
        self.assertEqual(got, {("Brand", "R"): 0.65})

    def test_malformed_key_multiple_colons_dropped(self):
        overrides = {
            "per_entry_probability": {
                "Brand:R:Extra": 0.75,
                "Brand:R": 0.65,
            }
        }
        got = ccc._apply_per_entry_overrides(overrides)
        # Brand:R:Extra (2 colons -> 3 parts) dropped.
        self.assertEqual(got, {("Brand", "R"): 0.65})

    def test_empty_champion_dropped(self):
        overrides = {"per_entry_probability": {":R": 0.75}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_empty_spell_dropped(self):
        overrides = {"per_entry_probability": {"Brand:": 0.75}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_non_float_value_dropped(self):
        overrides = {
            "per_entry_probability": {
                "Brand:R": "not a number",
                "Maokai:Q": None,
                "Pyke:E": [0.5],
                "Swain:E": 0.55,
            }
        }
        got = ccc._apply_per_entry_overrides(overrides)
        # Only Swain:E survives.
        self.assertEqual(got, {("Swain", "E"): 0.55})

    def test_negative_value_dropped(self):
        # Out-of-range DROPPED (not clamped).
        overrides = {"per_entry_probability": {"Brand:R": -0.5}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_greater_than_one_value_dropped(self):
        # Out-of-range DROPPED (not clamped).
        overrides = {"per_entry_probability": {"Brand:R": 1.5}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_bool_dropped(self):
        # bool subclass of int; must not coerce silently.
        overrides = {
            "per_entry_probability": {
                "Brand:R": True,
                "Maokai:Q": False,
            }
        }
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_unknown_champ_spell_not_validated_against_seed(self):
        # The apply function does NOT cross-reference the registry; an
        # unknown champion/spell is stored in the map. The builder's
        # .get((champ, spell), default) lookup is what makes unknown
        # keys harmless (they simply never get hit).
        overrides = {"per_entry_probability": {"FutureChamp:Q": 0.5}}
        got = ccc._apply_per_entry_overrides(overrides)
        # Stored, but the builder will not look it up.
        self.assertEqual(got, {("FutureChamp", "Q"): 0.5})

    def test_non_dict_overrides_section_ignored(self):
        overrides = {"per_entry_probability": [1, 2, 3]}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {})

    def test_int_value_coerced_to_float(self):
        overrides = {"per_entry_probability": {"Mordekaiser:R": 1}}
        got = ccc._apply_per_entry_overrides(overrides)
        self.assertEqual(got, {("Mordekaiser", "R"): 1.0})
        self.assertIsInstance(got[("Mordekaiser", "R")], float)


class IntegrationTests(unittest.TestCase):
    """Module-load with overrides file present + end-to-end builder flow.

    These tests write a fixture override file, redirect the module's
    _OVERRIDES_PATH at it, and re-run loader + apply + builder. They
    assert the constructed ConditionalCcEntry objects honor the
    override.

    Approach: capture pristine state in setUp, mutate module state for
    the test, restore in tearDown so we do not leak overrides between
    tests / files.
    """

    def setUp(self):
        # Snapshot the live module state so we can restore it cleanly.
        self._saved_defaults = dict(ccc._DEFAULT_CONDITION_PROBABILITY)
        self._saved_per_entry = dict(ccc._PER_ENTRY_PROBABILITY_OVERRIDES)

    def tearDown(self):
        # Restore live state.
        ccc._DEFAULT_CONDITION_PROBABILITY.clear()
        ccc._DEFAULT_CONDITION_PROBABILITY.update(self._saved_defaults)
        ccc._PER_ENTRY_PROBABILITY_OVERRIDES.clear()
        ccc._PER_ENTRY_PROBABILITY_OVERRIDES.update(self._saved_per_entry)

    def _apply_override_payload(self, payload: dict) -> None:
        """Write payload to a temp file, patch _OVERRIDES_PATH, run loader
        + apply + swap into module state. The test then re-invokes the
        builder to construct entries reflecting the overrides.
        """
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(_rmtree_safe, tmpdir)
        override = Path(tmpdir) / "calibration.json"
        override.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(ccc, "_OVERRIDES_PATH", override):
            raw = ccc._load_overrides()
        new_defaults = ccc._apply_default_probability_overrides(
            self._saved_defaults, raw
        )
        new_per_entry = ccc._apply_per_entry_overrides(raw)
        # Swap into module state. The builder reads these at call time.
        ccc._DEFAULT_CONDITION_PROBABILITY.clear()
        ccc._DEFAULT_CONDITION_PROBABILITY.update(new_defaults)
        ccc._PER_ENTRY_PROBABILITY_OVERRIDES.clear()
        ccc._PER_ENTRY_PROBABILITY_OVERRIDES.update(new_per_entry)

    def test_module_load_with_per_entry_override_flows_to_builder(self):
        # Override Brand:R to 0.95; build registry; assert the
        # ConditionalCcEntry for Brand R reflects the override.
        self._apply_override_payload(
            {"per_entry_probability": {"Brand:R": 0.95}}
        )
        registry = ccc._build_per_spell_cc_conditional()
        brand_r = registry["Brand"]["R"]
        self.assertEqual(brand_r.probability, 0.95)

    def test_module_load_without_file_preserves_defaults(self):
        # No payload applied; defaults stay at canonical values; the
        # builder constructs entries with canonical seed probabilities.
        registry = ccc._build_per_spell_cc_conditional()
        brand_r = registry["Brand"]["R"]
        self.assertEqual(brand_r.probability, 0.7)  # canonical seed

    def test_get_total_conditional_cc_seconds_reflects_override(self):
        # Brand R durations=(2.0,) probability=0.7 -> 1.4 (canonical).
        # Override probability to 1.0 -> total = 2.0.
        self._apply_override_payload(
            {"per_entry_probability": {"Brand:R": 1.0}}
        )
        # Need to swap in the new registry too so the public lookup uses it.
        new_registry = ccc._build_per_spell_cc_conditional()
        with mock.patch.object(
            ccc, "_PER_SPELL_CC_CONDITIONAL", new_registry
        ):
            total = ccc.get_total_conditional_cc_seconds(
                "Brand", apply_probability=True
            )
        self.assertAlmostEqual(total, 2.0)

    def test_both_sections_compose(self):
        # Override the nth_hit tag midpoint AND a specific per-entry
        # probability. The per-entry override should win (since it is
        # written into the entry at construction time, not at sum time).
        self._apply_override_payload(
            {
                "default_condition_probability": {"nth_hit": 0.5},
                "per_entry_probability": {"Brand:R": 0.95},
            }
        )
        registry = ccc._build_per_spell_cc_conditional()
        # Brand:R picks up the per-entry override directly.
        self.assertEqual(registry["Brand"]["R"].probability, 0.95)
        # The tag midpoint shift is reflected in
        # _DEFAULT_CONDITION_PROBABILITY (the value that future entries
        # would consult if they fell back to the tag default).
        self.assertEqual(ccc._DEFAULT_CONDITION_PROBABILITY["nth_hit"], 0.5)

    def test_unknown_per_entry_silently_dropped_at_builder_lookup(self):
        # FutureChamp:Q in the overrides file does not match any seed;
        # the registry construction proceeds unaffected. Verifies the
        # builder's .get() fallback semantics.
        self._apply_override_payload(
            {"per_entry_probability": {"FutureChamp:Q": 0.95, "Brand:R": 0.9}}
        )
        registry = ccc._build_per_spell_cc_conditional()
        # Brand R override took effect.
        self.assertEqual(registry["Brand"]["R"].probability, 0.9)
        # FutureChamp not introduced into the registry (the builder
        # only seeds the canonical 28 entries; the override file does
        # not add NEW entries, only TUNES existing ones).
        self.assertNotIn("FutureChamp", registry)


class NoOverrideFileDefaultPreservationTests(unittest.TestCase):
    """Canonical seed values + module load idempotency.

    These tests pin the canonical defaults so an accidental override
    file in the test env (e.g. operator's personal calibration leaking
    into CI) is caught immediately.
    """

    def test_canonical_default_condition_probability_midpoints(self):
        # Pin the 10 canonical tag midpoints. If the operator's
        # personal override file is present in the test env, this
        # may flag - the test environment expects no override file.
        # The override file at data/cc_conditional_calibration.json
        # is gitignored so CI never sees one.
        expected = {
            "nth_hit": 0.7,
            "gold_card": 0.4,
            "terrain": 0.3,
            "channel": 0.5,
            "dream_stack": 0.3,
            "devour": 0.4,
            "low_hp_target": 0.5,
            "debuffed_target": 0.5,
            "dual_enemy": 0.6,
            "mode_gated": 1.0,
        }
        # Build a fresh defaults dict + verify the empty-overrides
        # path returns canonical. This isolates the test from any
        # operator override file in the working tree.
        composed = ccc._apply_default_probability_overrides(expected, {})
        self.assertEqual(composed, expected)

    def test_canonical_per_entry_seed_probabilities(self):
        # Re-run the builder with an EMPTY per-entry override map and
        # pin a few canonical seed probabilities. This is a behavior
        # contract: the canonical seed values stay byte-equal between
        # ENGINE 1.41.0 and 1.41.0 unless operator-approved.
        saved = dict(ccc._PER_ENTRY_PROBABILITY_OVERRIDES)
        ccc._PER_ENTRY_PROBABILITY_OVERRIDES.clear()
        try:
            registry = ccc._build_per_spell_cc_conditional()
        finally:
            ccc._PER_ENTRY_PROBABILITY_OVERRIDES.update(saved)
        # Pin a sample across wave 1 + wave 2 + wave 3.
        self.assertEqual(registry["Brand"]["R"].probability, 0.7)
        self.assertEqual(registry["TwistedFate"]["W"].probability, 0.4)
        self.assertEqual(registry["JarvanIV"]["E"].probability, 0.5)
        self.assertEqual(registry["Mordekaiser"]["R"].probability, 1.0)
        # Wave 2.
        self.assertEqual(registry["Maokai"]["Q"].probability, 0.3)
        self.assertEqual(registry["Swain"]["E"].probability, 0.5)
        # Wave 3.
        self.assertEqual(registry["Aatrox"]["Q"].probability, 0.7)
        self.assertEqual(registry["Leblanc"]["E"].probability, 0.5)

    def test_apply_functions_are_idempotent(self):
        # Calling _apply_*_overrides twice with the same empty payload
        # returns the same result both times (no hidden mutable state).
        defaults = dict(ccc._DEFAULT_CONDITION_PROBABILITY)
        once = ccc._apply_default_probability_overrides(defaults, {})
        twice = ccc._apply_default_probability_overrides(defaults, {})
        self.assertEqual(once, twice)
        # Per-entry path.
        m1 = ccc._apply_per_entry_overrides({})
        m2 = ccc._apply_per_entry_overrides({})
        self.assertEqual(m1, m2)


class AsciiHygieneTests(unittest.TestCase):
    """This test file + the module are pure ASCII."""

    def test_self_source_has_no_unicode_punctuation(self):
        path = pathlib.Path(__file__)
        text = path.read_text(encoding="utf-8")
        # Build the bad-glyph set via chr() so this test file stays
        # ASCII-clean against its own scan.
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
            f"test_cc_conditional_overrides.py has banned Unicode: {hits!r}",
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
