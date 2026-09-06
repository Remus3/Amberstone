"""
core/config_validator.py
Phase 1 Step 1 - Config schema validation for Amberstone.

Non-fatal: validation results are logged as warnings/errors but never abort startup.
Non-mutating: config files are never written or modified.
Python 3.9 compatible: no walrus operator, no match statements, no X|Y unions.

Validation statuses:
  OK       - file present and all required keys found with correct types
  WARNING  - file present but optional key has wrong type, or an advisory note
  ERROR    - file present but required key missing, empty, or wrongly typed;
             or the file could not be read, parsed, or is not a JSON object
  SKIP     - file not present and is marked as optional/future

Diagnostic contract (this module's entire product is its log output, because
main.py discards the return value and only the log line reaches the operator):

  - A failure is ALWAYS attributed to a named config file. `validate_all`
    pairs every validator with its path up front, so a validator that raises
    is still reported against the file it was validating rather than against
    a placeholder.
  - "unreadable", "not valid JSON", and "valid JSON but not an object" are
    three distinct messages, and the underlying error detail is preserved.
  - A required key must be present, correctly typed, AND non-empty. Emptiness
    is judged by container, not by truthiness: "" / "   " / [] / {} are empty,
    while `false` and `0` are legitimate configured values.
  - A type spec this module does not recognise is reported as an ERROR rather
    than silently passing, so a typo in a field_types map cannot quietly
    disable validation for that field.

Usage:
    from core.config_validator import validate_all
    results = validate_all()
    # results is a list of ValidationResult namedtuples

Startup hook: called from main.py before DevRuntime starts.

Schema files (config/schema/*.schema.json):
  The schema JSON files in config/schema/ are DOCUMENTATION ARTIFACTS in Step 1.
  They are NOT loaded or parsed by this module at runtime. Validation logic is
  hardcoded here directly. The schema files exist to document field expectations
  for audit and future tooling purposes only.
  This is an explicit Step 1 choice; a schema-driven validator may be introduced
  in a later step if the added complexity is justified.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Tuple,
)

_log = logging.getLogger("rc.config_validator")

APP_DIR = Path(__file__).parent.parent.resolve()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class ValidationResult(NamedTuple):
    file:    str    # relative path from APP_DIR
    status:  str    # OK | WARNING | ERROR | SKIP
    message: str    # human-readable summary
    issues:  List[str]  # individual issue strings (may be empty)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Tuple[Any, Optional[str]]:
    """Load a JSON file.

    Returns a ``(data, error)`` pair. On success ``error`` is None. On failure
    ``data`` is None and ``error`` is a human-readable diagnostic that names
    WHICH failure occurred and preserves the underlying detail.

    The two failure modes are deliberately worded so they cannot be confused
    in a log: an unreadable file and a syntactically invalid file are
    different problems with different fixes. The previous implementation
    collapsed both (plus a valid top-level `null`) into one detail-free
    "Could not read or parse JSON".
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, f"Could not read file: {exc}"
    except UnicodeDecodeError as exc:
        # RM-291A: a third distinct failure mode, and it used to escape this
        # function entirely - UnicodeDecodeError is a ValueError, not an
        # OSError, so neither handler here caught it and a non-UTF-8 config
        # crashed the validator instead of being reported as invalid. Worded
        # separately from the two above for the same reason they are worded
        # separately from each other: "not text" and "not JSON" have
        # different fixes.
        return None, f"File is not valid UTF-8: {exc}"
    try:
        return json.loads(raw), None
    except ValueError as exc:
        # json.JSONDecodeError subclasses ValueError and carries line/column.
        return None, f"Invalid JSON: {exc}"


def _describe_json_type(value: Any) -> str:
    """Name a decoded JSON value's type using JSON vocabulary."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _is_empty_value(value: Any) -> bool:
    """Return True if a configured value is present but carries no content.

    Emptiness is a property of containers and text, NOT of falsiness. A
    `false` boolean and a `0` number are legitimate configured values and
    must never be reported as empty.
    """
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


_PYTHON_TYPE_MAP = {
    "string":  str,
    "boolean": bool,
    "number":  (int, float),
    "integer": int,
    "array":   list,
    "object":  dict,
}


def _missing_required_file(rel_path: str) -> ValidationResult:
    """Report a required config file that is absent.

    Some required configs are machine-local and deliberately gitignored
    (config/coach_settings.json, .gitignore:40), so this fires on every fresh
    clone. When a tracked `*.example.json` sibling exists, name it - an ERROR
    the reader cannot act on is an ERROR they learn to scroll past.
    """
    issues = [f"File missing: {rel_path}"]
    message = "Required config file not found"
    example_rel = rel_path.replace(".json", ".example.json")
    if example_rel != rel_path and (APP_DIR / example_rel).is_file():
        hint = f"copy {example_rel} to {rel_path} and edit it"
        message = f"Required config file not found - {hint}"
        issues.append(f"FIX: {hint}")
    return ValidationResult(
        file=rel_path, status="ERROR", message=message, issues=issues,
    )


def _check_type(value: Any, expected: str) -> bool:
    """Return True if value matches the expected type string.

    bool is a subclass of int in Python, so isinstance(True, int) is True.
    This must be rejected for both 'integer' and 'number' types - a JSON
    boolean is never a valid substitute for a JSON number.
    """
    expected_types = _PYTHON_TYPE_MAP.get(expected)
    if expected_types is None:
        return True  # unknown type spec - pass
    # Reject bool for any numeric type ('integer' or 'number').
    # This check must come before isinstance() because bool is a subclass of int.
    if expected in ("integer", "number"):
        if isinstance(value, bool):
            return False
    if expected == "integer":
        return isinstance(value, int)
    return isinstance(value, expected_types)


def _validate_config(
    rel_path: str,
    required_keys: List[str],
    optional_keys: List[str],
    field_types: Dict[str, str],
    is_optional_file: bool = False,
    field_ranges: Optional[Mapping[str, Tuple[Any, Any]]] = None,
) -> ValidationResult:
    """
    Validate a config file against required/optional key lists and type map.
    Returns a ValidationResult.

    `field_ranges` maps a key to an inclusive `(low, high)` bound, either end
    `None` for unbounded. It is deliberately NOT a bound on every numeric
    field: it carries only the knobs whose out-of-range value is DESTRUCTIVE
    rather than merely wrong, which is why a range violation is an ERROR even
    on an OPTIONAL key while a wrong type there is only a WARNING (RM-161).
    """
    path = APP_DIR / rel_path

    if not path.exists():
        if is_optional_file:
            return ValidationResult(
                file=rel_path, status="SKIP",
                message="Not present (optional/future file - expected for later Phase 1 step)",
                issues=[],
            )
        return _missing_required_file(rel_path)

    data, load_error = _load_json(path)
    if load_error is not None:
        return ValidationResult(
            file=rel_path, status="ERROR",
            message=load_error,
            issues=[f"{rel_path}: {load_error}"],
        )

    # A file can decode cleanly and still not be a config. Guard this BEFORE
    # any key lookup: `key not in data` is a substring test against a string
    # and an element test against a list, so both silently pass the
    # required-key loop and then raise TypeError on data[key] - which used to
    # surface as a validator crash attributed to "<unknown>".
    if not isinstance(data, dict):
        found = _describe_json_type(data)
        return ValidationResult(
            file=rel_path, status="ERROR",
            message=f"Top-level value must be a JSON object, got {found}",
            issues=[
                f"ERROR: {rel_path} must contain a JSON object "
                f"(a '{{...}}' mapping), got {found}"
            ],
        )

    issues: List[str] = []
    warnings: List[str] = []

    # A type spec this module cannot resolve would silently pass every value.
    # Report it instead - a typo here disables a field's validation forever.
    for key, type_name in sorted(field_types.items()):
        if type_name not in _PYTHON_TYPE_MAP:
            issues.append(
                f"ERROR: key '{key}' declares unknown type spec "
                f"'{type_name}' (validation for this field is not enforced)"
            )

    # Check required keys: present, correctly typed, and non-empty.
    for key in required_keys:
        if key not in data:
            issues.append(f"ERROR: required key '{key}' is missing")
            continue
        if key in field_types and field_types[key] in _PYTHON_TYPE_MAP:
            if not _check_type(data[key], field_types[key]):
                actual_type = type(data[key]).__name__
                issues.append(
                    f"ERROR: required key '{key}' has wrong type "
                    f"(expected {field_types[key]}, got {actual_type})"
                )
                continue
        if _is_empty_value(data[key]):
            issues.append(
                f"ERROR: required key '{key}' is present but empty "
                f"({_describe_json_type(data[key])} with no content)"
            )

    # Check optional key types (wrong type -> WARNING not ERROR)
    for key in optional_keys:
        if key in data and field_types.get(key) in _PYTHON_TYPE_MAP:
            if not _check_type(data[key], field_types[key]):
                actual_type = type(data[key]).__name__
                warnings.append(
                    f"WARNING: optional key '{key}' has wrong type "
                    f"(expected {field_types[key]}, got {actual_type})"
                )

    # Range check (RM-161). Runs after both type loops so a value that failed
    # its type check is reported once, by the type pass, and never reaches a
    # comparison - `"7" < 1` is a TypeError in Python 3, and a bool would
    # satisfy `>= 1` because `True == 1`.
    for key, bounds in sorted((field_ranges or {}).items()):
        type_name = field_types.get(key)
        if type_name not in ("integer", "number"):
            # A range on a key that is not typed numerically can never be
            # evaluated and nothing else would say so - the same silent-death
            # failure the unknown-type-spec report above exists to prevent.
            issues.append(
                f"ERROR: key '{key}' declares a range but is typed "
                f"'{type_name}' (range validation for this field is not "
                f"enforced)"
            )
            continue
        if key not in data or not _check_type(data[key], type_name):
            continue
        low, high = bounds
        value = data[key]
        if low is not None and value < low:
            issues.append(
                f"ERROR: key '{key}' is out of range: {value!r} "
                f"(must be >= {low})"
            )
        elif high is not None and value > high:
            issues.append(
                f"ERROR: key '{key}' is out of range: {value!r} "
                f"(must be <= {high})"
            )

    all_issues = issues + warnings

    if issues:
        status = "ERROR"
        message = f"{len(issues)} error(s), {len(warnings)} warning(s)"
    elif warnings:
        status = "WARNING"
        message = f"0 errors, {len(warnings)} warning(s)"
    else:
        status = "OK"
        message = "All required keys present with correct types"

    return ValidationResult(file=rel_path, status=status, message=message, issues=all_issues)


# ---------------------------------------------------------------------------
# Per-file validators
# ---------------------------------------------------------------------------

class _ConfigSpec(NamedTuple):
    """A declarative description of one schema-driven config file.

    Declarative rather than inline so the shipped specs can be swept for an
    unknown type name by a test, instead of the typo lying dormant until the
    field it guards is the one that breaks.
    """
    rel_path:         str
    required_keys:    List[str]
    optional_keys:    List[str]
    field_types:      Dict[str, str]
    is_optional_file: bool = False
    # Appended at the END with a default, per CLAUDE.md Python Conventions -
    # a mid-class required field breaks every existing positional
    # construction. Empty means "no bounds", which is every spec but one.
    # The default is a read-only mapping, not a bare {}: a NamedTuple class
    # default is ONE object shared by every spec that omits the field, so a
    # mutable one would let a future in-place edit to one spec's table reach
    # all of them.
    field_ranges:     Mapping[str, Tuple[Any, Any]] = MappingProxyType({})


def _validate_spec(spec: _ConfigSpec) -> ValidationResult:
    return _validate_config(
        rel_path=spec.rel_path,
        required_keys=spec.required_keys,
        optional_keys=spec.optional_keys,
        field_types=spec.field_types,
        is_optional_file=spec.is_optional_file,
        field_ranges=spec.field_ranges,
    )


# heartbeat_interval_s and command_poll_interval_s are read by main.py when
# constructing DevRuntime (non-frozen). They are absent from the live
# rc_config.json (main.py falls back to hardcoded defaults of 1.0 / 0.5), so
# they are validated as optional keys here.
_RC_CONFIG_SPEC = _ConfigSpec(
        rel_path="ops/rc_config.json",
        required_keys=[
            "project_root", "runtime_dir", "python_exe",
            "app_cmd", "health_file", "admin_bridge_enabled",
        ],
        optional_keys=[
            "heartbeat_interval_s",       # read by main.py -> DevRuntime; default 1.0
            "command_poll_interval_s",    # read by main.py -> DevRuntime; default 0.5
            "max_heartbeat_age_seconds", "poll_interval_seconds",
            "max_restart_attempts", "restart_window_seconds",
            "restart_cooldown_seconds", "bridge_poll_interval_seconds",
            "image_retention_days", "control_file_retention_hours",
            "backup_retention_count", "deploy_script", "api_key_file",
        ],
        field_types={
            "project_root":               "string",
            "runtime_dir":                "string",
            "python_exe":                 "string",
            "app_cmd":                    "array",
            "health_file":                "string",
            "admin_bridge_enabled":       "boolean",
            "heartbeat_interval_s":       "number",
            "command_poll_interval_s":    "number",
            "max_heartbeat_age_seconds":  "number",
            "poll_interval_seconds":      "number",
            "max_restart_attempts":       "integer",
            "restart_window_seconds":     "number",
            "restart_cooldown_seconds":   "number",
            "bridge_poll_interval_seconds": "number",
            "image_retention_days":       "integer",
            "control_file_retention_hours": "number",
            "backup_retention_count":     "integer",
        },
        is_optional_file=False,
        # RM-363, the RM-161 shape in a second config file. Two frozen-or-not
        # readers slice `backups[retention:]` and rmtree the remainder:
        # `ops/rc_supervisor.py:1339` (FROZEN, fired at the tail of
        # `_do_rollback`) and `prune_backups` in
        # `ops/rc_transactional_deploy.py` (cited by name, not line - this
        # commit adds lines above it). At 0 that
        # slice is EVERY backup, so the knob that bounds the backup corpus
        # erases it - including the snapshot a rollback just restored from.
        # At -1 it inverts to "delete the oldest". `0` is a valid `"integer"`,
        # so the type map alone let it through. Rejecting the config here
        # stops it before the frozen supervisor ever reads it.
        field_ranges={
            "backup_retention_count": (1, None),
        },
)


_COACH_SETTINGS_SPEC = _ConfigSpec(
        rel_path="config/coach_settings.json",
        required_keys=["model", "debounce_seconds", "timeout", "max_tokens"],
        optional_keys=["tft_pbe"],
        field_types={
            "model":            "string",
            "debounce_seconds": "number",
            "timeout":          "number",
            "max_tokens":       "integer",
            "tft_pbe":          "boolean",
        },
        is_optional_file=False,
)


_SELF_MONITOR_SPEC = _ConfigSpec(
        rel_path="config/self_monitor_profile.json",
        required_keys=["enabled", "auto_retry", "remediation_ladder"],
        optional_keys=[
            "resume_on_boot", "max_restart_attempts", "restart_window_seconds",
            "restart_cooldown_seconds", "max_hot_reload_attempts",
            "screen_validation_enabled", "screen_validation_interval_s",
            "safe_live_patch_only", "incident_log_retention_days",
            "allowed_hot_reload_modules", "allowed_panel_rebuild_keys",
        ],
        field_types={
            "enabled":                    "boolean",
            "resume_on_boot":             "boolean",
            "auto_retry":                 "boolean",
            "max_restart_attempts":       "integer",
            "restart_window_seconds":     "number",
            "restart_cooldown_seconds":   "number",
            "max_hot_reload_attempts":    "integer",
            "screen_validation_enabled":  "boolean",
            "screen_validation_interval_s": "number",
            "safe_live_patch_only":       "boolean",
            "incident_log_retention_days": "integer",
            "remediation_ladder":         "array",
            "allowed_hot_reload_modules": "array",
            "allowed_panel_rebuild_keys": "array",
        },
        is_optional_file=False,
        # RM-161. `ops/rc_supervisor.py:1442` (FROZEN) reads this key straight
        # into `ops/rc_incident_log.IncidentLog`, whose purge keeps only
        # entries newer than `now - timedelta(days=retention_days)`. At 0 or
        # less that window is empty or inverted and the purge erases the whole
        # incident log - the record the operator opens to diagnose an
        # incident. `0` is a valid `"integer"`, so the type map alone let it
        # through. Rejecting the profile here stops it before the frozen
        # supervisor ever reads it.
        field_ranges={
            "incident_log_retention_days": (1, None),
        },
)


# Every schema-driven spec, in validation order. Swept by the test suite for
# type names this module cannot resolve.
_CONFIG_SPECS = [
    _RC_CONFIG_SPEC,
    _COACH_SETTINGS_SPEC,
    _SELF_MONITOR_SPEC,
]

_FEATURE_FLAGS_REL = "config/feature_flags.json"


def _validate_rc_config() -> ValidationResult:
    return _validate_spec(_RC_CONFIG_SPEC)


def _validate_coach_settings() -> ValidationResult:
    return _validate_spec(_COACH_SETTINGS_SPEC)


def _validate_self_monitor_profile() -> ValidationResult:
    return _validate_spec(_SELF_MONITOR_SPEC)


def _validate_feature_flags() -> ValidationResult:
    """
    Validate config/feature_flags.json - created in Step 7.
    Checks that each mode block contains only known features with valid decision values.
    """
    path = APP_DIR / _FEATURE_FLAGS_REL
    if not path.exists():
        return ValidationResult(
            file=_FEATURE_FLAGS_REL,
            status="SKIP",
            message="Not present (optional - runtime safe-defaults apply)",
            issues=[],
        )
    data, load_error = _load_json(path)
    if load_error is not None:
        return ValidationResult(
            file=_FEATURE_FLAGS_REL,
            status="ERROR",
            message=load_error,
            issues=[f"{_FEATURE_FLAGS_REL}: {load_error}"],
        )
    if not isinstance(data, dict):
        found = _describe_json_type(data)
        return ValidationResult(
            file=_FEATURE_FLAGS_REL,
            status="ERROR",
            message=f"Top-level value must be a JSON object, got {found}",
            issues=[
                f"ERROR: {_FEATURE_FLAGS_REL} must contain a JSON object "
                f"(a '{{...}}' mapping), got {found}"
            ],
        )
    _KNOWN_MODES = {"sr", "aram", "arena", "brawl", "tft"}
    _KNOWN_FEATURES = {
        "sr":    {"live_coaching"},
        "aram":  {"live_coaching"},
        "arena": {"live_coaching"},
        "brawl": {"live_coaching"},
        "tft":   {"live_coaching", "tft_vision_analysis"},
    }
    _VALID_DECISIONS = {"allow", "disabled"}
    issues: List[str] = []
    for key, block in data.items():
        if key.startswith("_"):
            continue  # metadata keys
        if key not in _KNOWN_MODES:
            issues.append(f"WARNING: unknown mode key '{key}'")
            continue
        if not isinstance(block, dict):
            issues.append(f"ERROR: mode '{key}' must be an object, got {type(block).__name__}")
            continue
        for feat, decision in block.items():
            known = _KNOWN_FEATURES.get(key, set())
            if feat not in known:
                issues.append(f"WARNING: unknown feature '{feat}' in mode '{key}'")
            if decision not in _VALID_DECISIONS:
                issues.append(
                    f"ERROR: '{key}.{feat}' has invalid decision {decision!r} "
                    f"(expected 'allow' or 'disabled')"
                )
    errors  = [i for i in issues if i.startswith("ERROR")]
    status  = "ERROR" if errors else ("WARNING" if issues else "OK")
    message = f"{len(errors)} error(s), {len(issues)-len(errors)} warning(s)" if issues else "All mode/feature decisions valid"
    return ValidationResult(
        file="config/feature_flags.json", status=status, message=message, issues=issues
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# (rel_path, validator) pairs. The path is carried alongside the callable so
# that a validator which raises can still be reported against a named file
# rather than a placeholder.
_VALIDATORS: List[Tuple[str, Callable[[], ValidationResult]]] = [
    (_RC_CONFIG_SPEC.rel_path,      _validate_rc_config),
    (_COACH_SETTINGS_SPEC.rel_path, _validate_coach_settings),
    (_SELF_MONITOR_SPEC.rel_path,   _validate_self_monitor_profile),
    (_FEATURE_FLAGS_REL,            _validate_feature_flags),
]


def validate_all() -> List[ValidationResult]:
    """
    Run validation for all config files. Returns a list of ValidationResult.

    Never raises. Never aborts startup. Logs results at appropriate levels:
      OK      -> INFO
      WARNING -> WARNING
      ERROR   -> ERROR
      SKIP    -> INFO
    """
    results: List[ValidationResult] = []
    for rel_path, fn in _VALIDATORS:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            # Validator itself crashed. Attribute it to the file it was
            # validating: the file name is the only actionable part of the
            # line, and a crash is exactly when the operator needs it.
            result = ValidationResult(
                file=rel_path, status="ERROR",
                message=f"Validator raised unexpectedly: {exc}",
                issues=[f"{type(exc).__name__}: {exc}"],
            )

        results.append(result)

        log_fn = {
            "OK":      _log.info,
            "WARNING": _log.warning,
            "ERROR":   _log.error,
            "SKIP":    _log.info,
        }.get(result.status, _log.info)

        log_fn(
            "config_validator  %-45s  [%s]  %s",
            result.file, result.status, result.message,
        )
        for issue in result.issues:
            _log.warning("  %s  |  %s", result.file, issue)

    ok      = sum(1 for r in results if r.status == "OK")
    warn    = sum(1 for r in results if r.status == "WARNING")
    err     = sum(1 for r in results if r.status == "ERROR")
    skip    = sum(1 for r in results if r.status == "SKIP")
    _log.info(
        "config_validator  summary: %d OK  %d WARNING  %d ERROR  %d SKIP",
        ok, warn, err, skip,
    )
    return results


def print_results(results: List[ValidationResult]) -> None:
    """Print validation results to stdout in a human-readable format."""
    print("=" * 60)
    print("Amberstone - Config Validation")
    print("=" * 60)
    for r in results:
        print(f"  [{r.status:<7}]  {r.file}")
        print(f"           {r.message}")
        for issue in r.issues:
            print(f"           ! {issue}")
    print("-" * 60)
    ok   = sum(1 for r in results if r.status == "OK")
    warn = sum(1 for r in results if r.status == "WARNING")
    err  = sum(1 for r in results if r.status == "ERROR")
    skip = sum(1 for r in results if r.status == "SKIP")
    print(f"  {ok} OK   {warn} WARNING   {err} ERROR   {skip} SKIP")
    print("=" * 60)


if __name__ == "__main__":
    # Allow direct invocation: python -m core.config_validator
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)-7s %(name)s: %(message)s")
    results = validate_all()
    print_results(results)
    has_errors = any(r.status == "ERROR" for r in results)
    sys.exit(1 if has_errors else 0)
