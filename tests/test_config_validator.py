"""Deep-audit suite for `core/config_validator.py` (lane 8, cycle 8).

The module had ZERO test references before this file: measured by scanning
every `tests/**/*.py` for the stem `config_validator`. It runs at import time
from `main.py` (frozen) inside a bare `try/except`, its return value is
DISCARDED, and it is explicitly non-fatal. That shape matters for what is
worth testing: the module's entire product is the log line it emits, so a
defect that mangles the log line is a defect in the only thing it does.

Four behaviours were measured on the pre-fix module and are pinned here:

  D1  A config file whose top-level JSON value is not an object (a string,
      a list, a number) did not report a bad file - it raised TypeError out
      of `_validate_config`. `validate_all` caught it and attributed the
      failure to the literal file name `<unknown>`, so the operator lost the
      name of the broken file in exactly the case the module exists to
      diagnose. A top-level JSON string was the sharp edge: `key not in data`
      is a SUBSTRING test against a string, so the required-key loop silently
      passed before `data[key]` raised.

  D2  `_load_json` bound the underlying exception and discarded it, so
      "file is not readable" and "file is not valid JSON" produced one
      identical, detail-free message.

  D3  `_check_type` returned True for a type spec it did not recognise, so a
      typo in a `field_types` value silently disabled validation for that
      field with no signal, permanently.

  D4  Empty required values passed. `python_exe: ""` and `app_cmd: []` are
      what the supervisor uses to launch RC; both validated clean.

A fifth issue is pinned as a diagnostic-quality guard rather than a bug:
`config/coach_settings.json` is a REQUIRED config that .gitignore:40 excludes,
so the validator hard-ERRORs on every fresh clone and every CI run for a file
that is absent by design. The tracked `coach_settings.example.json` makes that
actionable, and `test_absent_required_file_points_at_its_example` holds the
validator to naming it.

Every case builds its own temporary APP_DIR rather than pointing at the real
repo, so an assertion cannot pass because of whatever happens to be checked
out. The deliberate exception is `LiveConfigTests`, which exists to prove the
hardening did not start failing RC's real startup - and which is scoped to
the configs that exist wherever the suite runs, so it cannot pass on Legion
and fail in CI.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core import config_validator as cv  # noqa: E402


class _TmpAppDirCase(unittest.TestCase):
    """A disposable APP_DIR carrying an `ops/` and a `config/` subtree."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_cfgval_audit_")
        self.app_dir = Path(self._tmp.name)
        (self.app_dir / "ops").mkdir(parents=True, exist_ok=True)
        (self.app_dir / "config").mkdir(parents=True, exist_ok=True)
        self._orig_app_dir = cv.APP_DIR
        cv.APP_DIR = self.app_dir
        # validate_all() logs at ERROR for a bad config; keep the suite quiet.
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)
        cv.APP_DIR = self._orig_app_dir
        self._tmp.cleanup()

    # - helpers -----------------------------------------------------------

    def write(self, rel_path: str, text: str) -> Path:
        path = self.app_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, rel_path: str, obj: object) -> Path:
        return self.write(rel_path, json.dumps(obj))

    def valid_rc_config(self) -> dict:
        return {
            "project_root": r"C:\Riot Commander",
            "runtime_dir": "ops/runtime",
            "python_exe": "python.exe",
            "app_cmd": ["python.exe", "main.py"],
            "health_file": "ops/runtime/health.json",
            "admin_bridge_enabled": True,
        }

    def write_all_valid(self) -> None:
        """Write a clean, minimal instance of every REQUIRED config file."""
        self.write_json("ops/rc_config.json", self.valid_rc_config())
        self.write_json("config/coach_settings.json", {
            "model": "claude-haiku-4-5-20251001",
            "debounce_seconds": 2.0,
            "timeout": 30,
            "max_tokens": 1024,
        })
        self.write_json("config/self_monitor_profile.json", {
            "enabled": True,
            "auto_retry": True,
            "remediation_ladder": ["hot_reload", "restart"],
        })

    def result_for(self, results, rel_path):
        for r in results:
            if r.file == rel_path:
                return r
        self.fail(
            f"no ValidationResult for {rel_path!r} - got "
            f"{[r.file for r in results]!r}"
        )


# =========================================================================
# D1 - a non-object top-level JSON value must be REPORTED, not raised
# =========================================================================

class NonObjectTopLevelTests(_TmpAppDirCase):

    def _assert_reported(self, payload_text: str, label: str) -> None:
        self.write_all_valid()
        self.write("ops/rc_config.json", payload_text)
        try:
            result = cv._validate_rc_config()
        except Exception as exc:  # noqa: BLE001
            self.fail(
                f"{label} must be reported as a result, but raised "
                f"{type(exc).__name__}: {exc}"
            )
        self.assertEqual(result.status, "ERROR", label)
        self.assertEqual(result.file, "ops/rc_config.json", label)
        self.assertTrue(result.issues, f"{label} must carry an issue string")

    def test_top_level_string_is_reported(self):
        # The sharp edge: `key not in data` is a SUBSTRING test on a string,
        # so every required key "exists" and the loop reaches data[key].
        self._assert_reported(
            json.dumps(
                "project_root runtime_dir python_exe app_cmd "
                "health_file admin_bridge_enabled"
            ),
            "top-level JSON string",
        )

    def test_top_level_list_is_reported(self):
        self._assert_reported(json.dumps(["project_root"]), "top-level JSON list")

    def test_top_level_number_is_reported(self):
        self._assert_reported("17", "top-level JSON number")

    def test_top_level_bool_is_reported(self):
        self._assert_reported("true", "top-level JSON bool")

    def test_message_names_the_offending_type(self):
        self.write_all_valid()
        self.write("ops/rc_config.json", json.dumps(["a"]))
        result = cv._validate_rc_config()
        blob = (result.message + " " + " ".join(result.issues)).lower()
        self.assertIn("object", blob)
        self.assertIn("list", blob)

    def test_feature_flags_non_object_is_reported(self):
        self.write_all_valid()
        self.write("config/feature_flags.json", json.dumps(["sr"]))
        result = cv._validate_feature_flags()
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.file, "config/feature_flags.json")


# =========================================================================
# D1b - validate_all must never lose the file name
# =========================================================================

class CrashAttributionTests(_TmpAppDirCase):

    def test_no_result_is_attributed_to_unknown(self):
        for rel in (
            "ops/rc_config.json",
            "config/coach_settings.json",
            "config/self_monitor_profile.json",
            "config/feature_flags.json",
        ):
            self.write(rel, json.dumps("not an object"))
        results = cv.validate_all()
        offenders = [r.file for r in results if r.file == "<unknown>"]
        self.assertEqual(
            offenders, [],
            "validate_all attributed a failure to <unknown>; the operator "
            "cannot tell which config is broken",
        )

    def test_every_config_is_named_exactly_once(self):
        self.write_all_valid()
        results = cv.validate_all()
        names = [r.file for r in results]
        self.assertEqual(sorted(names), sorted(set(names)), "duplicate file rows")
        for rel in (
            "ops/rc_config.json",
            "config/coach_settings.json",
            "config/self_monitor_profile.json",
            "config/feature_flags.json",
        ):
            self.assertIn(rel, names)

    def test_a_raising_validator_is_named_not_unknown(self):
        """Directly pin the handler: a validator that blows up keeps its name."""
        self.write_all_valid()

        def _boom():
            raise RuntimeError("synthetic validator explosion")

        original = cv._VALIDATORS
        try:
            cv._VALIDATORS = [("ops/rc_config.json", _boom)]
            results = cv.validate_all()
        finally:
            cv._VALIDATORS = original
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file, "ops/rc_config.json")
        self.assertEqual(results[0].status, "ERROR")
        self.assertIn("synthetic validator explosion", " ".join(results[0].issues))

    def test_validate_all_never_raises_on_garbage(self):
        for rel in (
            "ops/rc_config.json",
            "config/coach_settings.json",
            "config/self_monitor_profile.json",
            "config/feature_flags.json",
        ):
            self.write(rel, "{ this is not json at all ]]")
        try:
            results = cv.validate_all()
        except Exception as exc:  # noqa: BLE001
            self.fail(f"validate_all raised {type(exc).__name__}: {exc}")
        self.assertTrue(all(r.status == "ERROR" for r in results))


# =========================================================================
# D2 - unreadable vs unparseable vs non-object must be distinguishable
# =========================================================================

class LoadDiagnosticTests(_TmpAppDirCase):

    def test_parse_error_message_carries_detail(self):
        self.write_all_valid()
        self.write("ops/rc_config.json", "{ nope")
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")
        blob = " ".join(result.issues) + result.message
        # The raw json error text must survive, not be flattened away.
        self.assertRegex(blob.lower(), r"line \d+|column \d+|expecting")

    def _unreadable_result(self):
        """A directory where the file should be: path exists, read fails."""
        target = self.app_dir / "ops" / "rc_config.json"
        target.unlink()
        target.mkdir()
        try:
            return cv._validate_rc_config()
        finally:
            target.rmdir()

    def test_unreadable_file_preserves_the_os_detail(self):
        self.write_all_valid()
        result = self._unreadable_result()
        self.assertEqual(result.status, "ERROR")
        # `message` is the raw diagnostic with no rel_path prefix added, so
        # finding the file name in it proves the OS error text survived
        # rather than being flattened into a generic sentence.
        self.assertIn("rc_config.json", result.message)
        self.assertNotIn("expecting", result.message.lower())

    def test_unreadable_and_invalid_json_do_not_share_a_message(self):
        """The two failures have different fixes and must read differently."""
        self.write_all_valid()
        unreadable = self._unreadable_result()
        self.write("ops/rc_config.json", "{ nope")
        unparseable = cv._validate_rc_config()
        self.assertEqual(unreadable.status, "ERROR")
        self.assertEqual(unparseable.status, "ERROR")
        self.assertNotEqual(
            unreadable.message, unparseable.message,
            "an unreadable file and an invalid one collapsed to one message",
        )

    def test_literal_null_is_not_called_a_parse_error(self):
        """`null` parses fine - calling it a parse error misdirects the reader."""
        self.write_all_valid()
        self.write("ops/rc_config.json", "null")
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")
        blob = (result.message + " " + " ".join(result.issues)).lower()
        self.assertNotIn("parse error", blob)


# =========================================================================
# D3 - an unrecognised type spec must be loud, not silently permissive
# =========================================================================

class TypeSpecTests(_TmpAppDirCase):

    def test_shipped_specs_use_only_known_type_names(self):
        """A typo in any shipped field_types map fails here, not in silence."""
        for spec in cv._CONFIG_SPECS:
            for key, type_name in spec.field_types.items():
                self.assertIn(
                    type_name, cv._PYTHON_TYPE_MAP,
                    f"{spec.rel_path}: key {key!r} declares unknown "
                    f"type spec {type_name!r}",
                )

    def test_unknown_type_spec_is_reported(self):
        self.write_all_valid()
        result = cv._validate_config(
            rel_path="ops/rc_config.json",
            required_keys=["project_root"],
            optional_keys=[],
            field_types={"project_root": "sting"},   # deliberate typo
        )
        self.assertEqual(result.status, "ERROR")
        self.assertTrue(
            any("sting" in i for i in result.issues),
            f"unknown type spec was silently accepted: {result.issues!r}",
        )

    def test_known_specs_still_accept_and_reject_correctly(self):
        self.assertTrue(cv._check_type("x", "string"))
        self.assertTrue(cv._check_type(1, "integer"))
        self.assertTrue(cv._check_type(1.5, "number"))
        self.assertTrue(cv._check_type([], "array"))
        self.assertTrue(cv._check_type({}, "object"))
        self.assertTrue(cv._check_type(True, "boolean"))
        self.assertFalse(cv._check_type(1, "string"))
        self.assertFalse(cv._check_type("1", "integer"))

    def test_bool_is_never_a_number(self):
        """Characterization: bool subclasses int and must stay rejected."""
        self.assertFalse(cv._check_type(True, "integer"))
        self.assertFalse(cv._check_type(True, "number"))
        self.assertFalse(cv._check_type(False, "integer"))
        self.assertFalse(cv._check_type(False, "number"))


# =========================================================================
# D4 - empty required values are not valid configuration
# =========================================================================

class EmptyValueTests(_TmpAppDirCase):

    def test_empty_required_string_is_rejected(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["python_exe"] = ""
        self.write_json("ops/rc_config.json", cfg)
        result = cv._validate_rc_config()
        self.assertEqual(
            result.status, "ERROR",
            "an empty python_exe cannot launch RC but validated clean",
        )
        self.assertTrue(any("python_exe" in i for i in result.issues))

    def test_empty_required_array_is_rejected(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["app_cmd"] = []
        self.write_json("ops/rc_config.json", cfg)
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")
        self.assertTrue(any("app_cmd" in i for i in result.issues))

    def test_whitespace_only_required_string_is_rejected(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["project_root"] = "   "
        self.write_json("ops/rc_config.json", cfg)
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")

    def test_false_and_zero_are_still_valid_values(self):
        """Emptiness is not falsiness - `False` and `0` are real settings."""
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["admin_bridge_enabled"] = False
        self.write_json("ops/rc_config.json", cfg)
        self.assertEqual(cv._validate_rc_config().status, "OK")

    def test_empty_optional_value_is_not_an_error(self):
        """Only REQUIRED keys carry the non-empty contract."""
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["deploy_script"] = ""
        self.write_json("ops/rc_config.json", cfg)
        self.assertNotEqual(cv._validate_rc_config().status, "ERROR")


# =========================================================================
# Characterization - the pre-existing contract must survive the hardening
# =========================================================================

class PreservedBehaviourTests(_TmpAppDirCase):

    def test_all_valid_is_ok(self):
        self.write_all_valid()
        self.assertEqual(cv._validate_rc_config().status, "OK")
        self.assertEqual(cv._validate_coach_settings().status, "OK")
        self.assertEqual(cv._validate_self_monitor_profile().status, "OK")

    def test_missing_required_key_is_error(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        del cfg["health_file"]
        self.write_json("ops/rc_config.json", cfg)
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")
        self.assertTrue(any("health_file" in i for i in result.issues))

    def test_wrong_required_type_is_error(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["app_cmd"] = "python main.py"      # string, must be array
        self.write_json("ops/rc_config.json", cfg)
        self.assertEqual(cv._validate_rc_config().status, "ERROR")

    def test_wrong_optional_type_is_warning_not_error(self):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg["max_restart_attempts"] = "three"   # string, must be integer
        self.write_json("ops/rc_config.json", cfg)
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "WARNING")
        self.assertTrue(any("max_restart_attempts" in i for i in result.issues))

    def test_missing_required_file_is_error(self):
        self.write_all_valid()
        (self.app_dir / "ops" / "rc_config.json").unlink()
        result = cv._validate_rc_config()
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.file, "ops/rc_config.json")

    def test_missing_optional_file_is_skip(self):
        self.write_all_valid()
        result = cv._validate_feature_flags()
        self.assertEqual(result.status, "SKIP")
        self.assertEqual(result.issues, [])

    def test_utf8_bom_is_tolerated(self):
        self.write_all_valid()
        (self.app_dir / "ops" / "rc_config.json").write_text(
            json.dumps(self.valid_rc_config()), encoding="utf-8-sig"
        )
        self.assertEqual(cv._validate_rc_config().status, "OK")

    def test_feature_flags_invalid_decision_is_error(self):
        self.write_all_valid()
        self.write_json("config/feature_flags.json",
                        {"sr": {"live_coaching": "maybe"}})
        result = cv._validate_feature_flags()
        self.assertEqual(result.status, "ERROR")

    def test_feature_flags_unknown_mode_is_warning(self):
        self.write_all_valid()
        self.write_json("config/feature_flags.json",
                        {"urf": {"live_coaching": "allow"}})
        self.assertEqual(cv._validate_feature_flags().status, "WARNING")

    def test_feature_flags_underscore_keys_are_metadata(self):
        self.write_all_valid()
        self.write_json("config/feature_flags.json",
                        {"_comment": "notes", "sr": {"live_coaching": "allow"}})
        self.assertEqual(cv._validate_feature_flags().status, "OK")

    def test_feature_flags_non_object_mode_block_is_error(self):
        self.write_all_valid()
        self.write_json("config/feature_flags.json", {"sr": ["live_coaching"]})
        self.assertEqual(cv._validate_feature_flags().status, "ERROR")

    def test_result_shape_is_stable(self):
        self.write_all_valid()
        for r in cv.validate_all():
            self.assertIsInstance(r, cv.ValidationResult)
            self.assertIn(r.status, {"OK", "WARNING", "ERROR", "SKIP"})
            self.assertIsInstance(r.file, str)
            self.assertIsInstance(r.message, str)
            self.assertIsInstance(r.issues, list)

    def test_print_results_never_raises(self):
        self.write_all_valid()
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cv.print_results(cv.validate_all())
        self.assertIn("Amberstone", buf.getvalue())


# =========================================================================
# The shipped configs must still pass - this is the "did I break RC" gate
# =========================================================================

class LiveConfigTests(unittest.TestCase):
    """Guards against the hardening breaking RC's real startup.

    `config/coach_settings.json` is gitignored (.gitignore:40), so it is
    absent by design in CI and in any fresh clone while present on Legion.
    Asserting a blanket "zero ERROR" would therefore pass on the live box
    and fail everywhere else, so the gate is scoped to the files that
    actually exist wherever this suite happens to run.
    """

    def test_shipped_configs_that_exist_validate_clean(self):
        logging.disable(logging.CRITICAL)
        try:
            results = cv.validate_all()
        finally:
            logging.disable(logging.NOTSET)
        bad = [
            (r.file, r.status, r.issues)
            for r in results
            if r.status == "ERROR" and (cv.APP_DIR / r.file).is_file()
        ]
        self.assertEqual(
            bad, [],
            "the hardening made RC's real startup config validation fail",
        )

    def test_at_least_one_shipped_config_is_present_and_ok(self):
        """Stops the test above from passing vacuously if nothing exists."""
        logging.disable(logging.CRITICAL)
        try:
            results = cv.validate_all()
        finally:
            logging.disable(logging.NOTSET)
        present_ok = [
            r.file for r in results
            if r.status == "OK" and (cv.APP_DIR / r.file).is_file()
        ]
        self.assertTrue(present_ok, "no shipped config validated OK")

    def test_absent_required_file_points_at_its_example(self):
        """A gitignored required config must say how to create it."""
        logging.disable(logging.CRITICAL)
        try:
            results = cv.validate_all()
        finally:
            logging.disable(logging.NOTSET)
        for r in results:
            if r.status != "ERROR" or (cv.APP_DIR / r.file).exists():
                continue
            example = cv.APP_DIR / r.file.replace(".json", ".example.json")
            if not example.is_file():
                continue
            blob = r.message + " " + " ".join(r.issues)
            self.assertIn(
                ".example.json", blob,
                f"{r.file} is missing and has an example file, but the "
                f"operator is not told to copy it",
            )

    def test_app_dir_points_at_the_repo_root(self):
        self.assertTrue((cv.APP_DIR / "main.py").is_file())
        self.assertTrue((cv.APP_DIR / "ops" / "rc_config.json").is_file())


# =========================================================================
# RM-161 - a typed knob is not a bounded knob
# =========================================================================

class RangeSpecCase(_TmpAppDirCase):
    """`incident_log_retention_days` was typed `integer` and never ranged.

    `ops/rc_supervisor.py:1442` (FROZEN) reads it straight out of
    `config/self_monitor_profile.json` and hands it to
    `ops/rc_incident_log.IncidentLog`, whose `_purge_old_locked` keeps only
    entries newer than `now - timedelta(days=retention_days)`. At a value of
    0 or less that window is empty or inverted, so the purge that exists to
    bound the incident log erases every entry in it - including the incidents
    the operator is reading it to diagnose. `0` passes `"integer"`, so the
    validator waved it through, and because the supervisor is frozen the
    validator is the non-frozen place to reject the profile before the
    supervisor ever reads it.

    Range violations are ERROR and never WARNING even on an OPTIONAL key,
    unlike a wrong type. The range table is deliberately curated to knobs
    whose bad value is DESTRUCTIVE rather than merely wrong, so a warning the
    operator can scroll past is the wrong severity for it.
    """

    SELF_MONITOR = "config/self_monitor_profile.json"

    def _profile(self, **over) -> dict:
        base = {
            "enabled": True,
            "auto_retry": True,
            "remediation_ladder": ["hot_reload", "restart"],
        }
        base.update(over)
        return base

    def _self_monitor_result(self, **over):
        self.write_all_valid()
        self.write_json(self.SELF_MONITOR, self._profile(**over))
        return self.result_for(cv.validate_all(), self.SELF_MONITOR)

    # - the defect ---------------------------------------------------------

    def test_zero_retention_is_rejected(self):
        result = self._self_monitor_result(incident_log_retention_days=0)
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(
            any("incident_log_retention_days" in i and "ERROR" in i
                for i in result.issues),
            f"a zero retention window was accepted: {result.issues!r}",
        )

    def test_negative_retention_is_rejected(self):
        result = self._self_monitor_result(incident_log_retention_days=-7)
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(
            any("incident_log_retention_days" in i for i in result.issues),
            f"a negative retention window was accepted: {result.issues!r}",
        )

    def test_the_supervisors_own_default_still_passes(self):
        """`ops/rc_supervisor.py:1442` defaults to 7 and `ops/rc_self_monitor.py:44`
        ships 7. A range that rejected the live value would be a regression,
        not a hardening."""
        result = self._self_monitor_result(incident_log_retention_days=7)
        self.assertIn(result.status, ("OK", "WARNING"), result.issues)
        self.assertFalse(
            any("incident_log_retention_days" in i for i in result.issues),
            f"the shipped default was flagged: {result.issues!r}",
        )

    def test_the_smallest_legal_value_passes(self):
        result = self._self_monitor_result(incident_log_retention_days=1)
        self.assertFalse(
            any("incident_log_retention_days" in i for i in result.issues),
            f"the boundary value 1 was flagged: {result.issues!r}",
        )

    def test_absent_optional_key_is_not_range_checked(self):
        """The key is OPTIONAL. A range check that fired on its absence would
        break every profile that never set it - which is all of them."""
        result = self._self_monitor_result()
        self.assertFalse(
            any("incident_log_retention_days" in i for i in result.issues),
            f"an absent optional key was range-checked: {result.issues!r}",
        )

    # - the mechanism ------------------------------------------------------

    def test_wrong_type_is_reported_once_and_not_range_checked(self):
        """A non-numeric value must not reach the comparison - `"7" < 1`
        raises TypeError in Python 3. The type report is the whole report."""
        result = self._self_monitor_result(incident_log_retention_days="7")
        flagged = [i for i in result.issues if "incident_log_retention_days" in i]
        self.assertEqual(len(flagged), 1, f"expected one issue, got {flagged!r}")
        self.assertIn("expected integer", flagged[0])

    def test_bool_is_not_accepted_as_an_in_range_integer(self):
        """`True == 1` in Python, so a bool would satisfy `>= 1` if it ever
        reached the comparison. `_check_type` rejects it first; pin that the
        range pass cannot resurrect it."""
        result = self._self_monitor_result(incident_log_retention_days=True)
        flagged = [i for i in result.issues if "incident_log_retention_days" in i]
        self.assertEqual(len(flagged), 1, f"expected one issue, got {flagged!r}")
        self.assertIn("expected integer", flagged[0])

    def test_range_message_states_the_bound_and_the_value(self):
        result = self._self_monitor_result(incident_log_retention_days=0)
        flagged = [i for i in result.issues if "incident_log_retention_days" in i]
        self.assertEqual(len(flagged), 1, f"expected one issue, got {flagged!r}")
        self.assertIn("0", flagged[0])
        self.assertIn("1", flagged[0])

    def test_every_ranged_key_is_typed_numeric_in_the_same_spec(self):
        """A range on a key the spec does not type numerically is DEAD - it
        can never be evaluated, and nothing would say so. This is the
        `_check_type` unknown-type-spec failure class (D3) in a new place."""
        for spec in cv._CONFIG_SPECS:
            for key in spec.field_ranges:
                self.assertIn(
                    key, spec.field_types,
                    f"{spec.rel_path}: ranged key {key!r} is not typed",
                )
                self.assertIn(
                    spec.field_types[key], ("integer", "number"),
                    f"{spec.rel_path}: ranged key {key!r} is typed "
                    f"{spec.field_types[key]!r}, which no range can apply to",
                )

    def test_every_ranged_key_is_a_declared_key_of_its_spec(self):
        for spec in cv._CONFIG_SPECS:
            declared = set(spec.required_keys) | set(spec.optional_keys)
            for key in spec.field_ranges:
                self.assertIn(
                    key, declared,
                    f"{spec.rel_path}: ranged key {key!r} is neither "
                    f"required nor optional, so it is never validated",
                )

    def test_incident_log_retention_days_is_actually_ranged(self):
        """The registry sweeps above are vacuous on an empty table. Pin the
        one row RM-161 exists for."""
        self.assertIn(
            "incident_log_retention_days", cv._SELF_MONITOR_SPEC.field_ranges,
        )
        low, high = cv._SELF_MONITOR_SPEC.field_ranges["incident_log_retention_days"]
        self.assertEqual(low, 1)
        self.assertIsNone(high)

    def test_range_applies_to_a_required_key_too(self):
        """The range pass must not be optional-only. Exercised directly
        because no shipped spec ranges a required key today, which is exactly
        how that path would rot unnoticed."""
        self.write_json("ops/probe.json", {"n": 0})
        result = cv._validate_config(
            rel_path="ops/probe.json",
            required_keys=["n"],
            optional_keys=[],
            field_types={"n": "integer"},
            field_ranges={"n": (1, None)},
        )
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(any("'n'" in i for i in result.issues), result.issues)

    def test_upper_bound_is_enforced(self):
        self.write_json("ops/probe.json", {"n": 11})
        result = cv._validate_config(
            rel_path="ops/probe.json",
            required_keys=[],
            optional_keys=["n"],
            field_types={"n": "integer"},
            field_ranges={"n": (1, 10)},
        )
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(any("10" in i for i in result.issues), result.issues)

    def test_a_value_exactly_on_either_bound_passes(self):
        """Both bounds are INCLUSIVE. Without this, `<` -> `<=` and
        `>` -> `>=` are both undetectable mutations."""
        for n in (1, 10):
            with self.subTest(n=n):
                self.write_json("ops/probe.json", {"n": n})
                result = cv._validate_config(
                    rel_path="ops/probe.json",
                    required_keys=[],
                    optional_keys=["n"],
                    field_types={"n": "integer"},
                    field_ranges={"n": (1, 10)},
                )
                self.assertEqual(result.status, "OK", result.issues)

    def test_a_range_on_a_non_numeric_key_is_reported_not_ignored(self):
        """A range that can never be evaluated is dead validation, and dead
        validation that says nothing is the D3 failure class again."""
        self.write_json("ops/probe.json", {"n": "x"})
        result = cv._validate_config(
            rel_path="ops/probe.json",
            required_keys=[],
            optional_keys=["n"],
            field_types={"n": "string"},
            field_ranges={"n": (1, None)},
        )
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(
            any(i.startswith("ERROR") and "range" in i and "'n'" in i
                for i in result.issues),
            f"an unevaluatable range was silently ignored: {result.issues!r}",
        )

    def test_value_inside_both_bounds_passes(self):
        self.write_json("ops/probe.json", {"n": 5})
        result = cv._validate_config(
            rel_path="ops/probe.json",
            required_keys=[],
            optional_keys=["n"],
            field_types={"n": "integer"},
            field_ranges={"n": (1, 10)},
        )
        self.assertEqual(result.status, "OK", result.issues)

    def test_ranges_default_to_empty_so_existing_specs_are_unaffected(self):
        """`field_ranges` was appended to `_ConfigSpec` with a default so no
        existing positional construction breaks (CLAUDE.md Python
        Conventions). Pin both halves of that."""
        spec = cv._ConfigSpec(
            rel_path="ops/probe.json",
            required_keys=[],
            optional_keys=[],
            field_types={},
            is_optional_file=False,
        )
        self.assertEqual(spec.field_ranges, {})
        # One shared class default across every spec that omits the field, so
        # it must not be mutable in place.
        with self.assertRaises(TypeError):
            spec.field_ranges["n"] = (1, None)   # type: ignore[index]
        self.write_json("ops/probe.json", {"n": -99})
        result = cv._validate_config(
            rel_path="ops/probe.json",
            required_keys=[],
            optional_keys=["n"],
            field_types={"n": "integer"},
        )
        self.assertEqual(result.status, "OK", result.issues)


class BackupRetentionRangeCase(_TmpAppDirCase):
    """RM-363 sibling sweep. Same shape as RM-161, same missing guard.

    `_RC_CONFIG_SPEC` types `backup_retention_count` as `"integer"` and is
    constructed with NO `field_ranges` at all, so `0` is a valid integer and
    the validator waves it through. `ops/rc_supervisor.py:1332` (FROZEN)
    reads it straight into `retention`, and `:1339` slices
    `backups[retention:]` - "keep newest N, delete the rest". At 0 that
    slice is EVERY backup and `:1343` calls `shutil.rmtree` on all of them.
    The call sits at the tail of `_do_rollback`, so the run that just
    restored from a snapshot then erases that snapshot along with every
    other rollback point. At -1 the knob inverts outright: `backups[-1:]`
    deletes the oldest rather than keeping the newest.

    Because the supervisor is frozen, the validator is the non-frozen place
    to reject the config before the supervisor ever reads it - which is
    exactly the reasoning `_SELF_MONITOR_SPEC` already carries for RM-161.
    """

    RC_CONFIG = "ops/rc_config.json"

    def _rc_result(self, **over):
        self.write_all_valid()
        cfg = self.valid_rc_config()
        cfg.update(over)
        self.write_json(self.RC_CONFIG, cfg)
        return self.result_for(cv.validate_all(), self.RC_CONFIG)

    def test_zero_backup_retention_is_rejected(self):
        result = self._rc_result(backup_retention_count=0)
        self.assertEqual(result.status, "ERROR", result.issues)
        self.assertTrue(
            any("backup_retention_count" in i and "ERROR" in i
                for i in result.issues),
            f"a keep-zero backup policy was accepted: {result.issues!r}",
        )

    def test_negative_backup_retention_is_rejected(self):
        result = self._rc_result(backup_retention_count=-1)
        self.assertEqual(result.status, "ERROR", result.issues)

    def test_the_shipped_default_still_passes(self):
        """`ops/rc_config.json` ships 10 and the supervisor defaults to 10.
        A range that rejected the live value would be a regression."""
        result = self._rc_result(backup_retention_count=10)
        self.assertFalse(
            any("backup_retention_count" in i for i in result.issues),
            f"the shipped default was flagged: {result.issues!r}",
        )

    def test_the_smallest_legal_value_passes(self):
        result = self._rc_result(backup_retention_count=1)
        self.assertFalse(
            any("backup_retention_count" in i for i in result.issues),
            f"the boundary value 1 was flagged: {result.issues!r}",
        )

    def test_absent_optional_key_is_not_range_checked(self):
        """It is OPTIONAL, and the shipped rc_config is allowed to omit it."""
        result = self._rc_result()
        self.assertFalse(
            any("backup_retention_count" in i for i in result.issues),
            f"an absent optional key was range-checked: {result.issues!r}",
        )


if __name__ == "__main__":
    unittest.main()
