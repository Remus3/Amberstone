"""
core/config_validator.py
Phase 1 Step 1 - Config schema validation for Riot Commander.

Non-fatal: validation results are logged as warnings/errors but never abort startup.
Non-mutating: config files are never written or modified.
Python 3.9 compatible: no walrus operator, no match statements, no X|Y unions.

Validation statuses:
  OK       - file present and all required keys found with correct types
  WARNING  - file present but optional key has wrong type, or an advisory note
  ERROR    - file present but required key missing or has wrong type
  SKIP     - file not present and is marked as optional/future

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
from typing import Any, Dict, List, NamedTuple, Optional

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

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load and return a JSON file, or None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None  # caller handles missing/unreadable


_PYTHON_TYPE_MAP = {
    "string":  str,
    "boolean": bool,
    "number":  (int, float),
    "integer": int,
    "array":   list,
    "object":  dict,
}


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
) -> ValidationResult:
    """
    Validate a config file against required/optional key lists and type map.
    Returns a ValidationResult.
    """
    path = APP_DIR / rel_path

    if not path.exists():
        if is_optional_file:
            return ValidationResult(
                file=rel_path, status="SKIP",
                message="Not present (optional/future file - expected for later Phase 1 step)",
                issues=[],
            )
        return ValidationResult(
            file=rel_path, status="ERROR",
            message="Required config file not found",
            issues=[f"File missing: {rel_path}"],
        )

    data = _load_json(path)
    if data is None:
        return ValidationResult(
            file=rel_path, status="ERROR",
            message="Could not read or parse JSON",
            issues=[f"JSON parse error in {rel_path}"],
        )

    issues: List[str] = []
    warnings: List[str] = []

    # Check required keys
    for key in required_keys:
        if key not in data:
            issues.append(f"ERROR: required key '{key}' is missing")
        elif key in field_types:
            if not _check_type(data[key], field_types[key]):
                actual_type = type(data[key]).__name__
                issues.append(
                    f"ERROR: required key '{key}' has wrong type "
                    f"(expected {field_types[key]}, got {actual_type})"
                )

    # Check optional key types (wrong type → WARNING not ERROR)
    for key in optional_keys:
        if key in data and key in field_types:
            if not _check_type(data[key], field_types[key]):
                actual_type = type(data[key]).__name__
                warnings.append(
                    f"WARNING: optional key '{key}' has wrong type "
                    f"(expected {field_types[key]}, got {actual_type})"
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

def _validate_rc_config() -> ValidationResult:
    # heartbeat_interval_s and command_poll_interval_s are read by main.py
    # when constructing DevRuntime (non-frozen). They are absent from the live
    # rc_config.json (main.py falls back to hardcoded defaults of 1.0 / 0.5),
    # so they are validated as optional keys here.
    return _validate_config(
        rel_path="ops/rc_config.json",
        required_keys=[
            "project_root", "runtime_dir", "python_exe",
            "app_cmd", "health_file", "admin_bridge_enabled",
        ],
        optional_keys=[
            "heartbeat_interval_s",       # read by main.py → DevRuntime; default 1.0
            "command_poll_interval_s",    # read by main.py → DevRuntime; default 0.5
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
    )


def _validate_coach_settings() -> ValidationResult:
    return _validate_config(
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


def _validate_self_monitor_profile() -> ValidationResult:
    return _validate_config(
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
    )


def _validate_feature_flags() -> ValidationResult:
    """
    Validate config/feature_flags.json - created in Step 7.
    Checks that each mode block contains only known features with valid decision values.
    """
    path = APP_DIR / "config" / "feature_flags.json"
    if not path.exists():
        return ValidationResult(
            file="config/feature_flags.json",
            status="SKIP",
            message="Not present (optional - runtime safe-defaults apply)",
            issues=[],
        )
    data = _load_json(path)
    if data is None:
        return ValidationResult(
            file="config/feature_flags.json",
            status="ERROR",
            message="Could not read or parse JSON",
            issues=["JSON parse error in config/feature_flags.json"],
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

def validate_all() -> List[ValidationResult]:
    """
    Run validation for all config files. Returns a list of ValidationResult.

    Never raises. Never aborts startup. Logs results at appropriate levels:
      OK      → INFO
      WARNING → WARNING
      ERROR   → ERROR
      SKIP    → INFO
    """
    validators = [
        _validate_rc_config,
        _validate_coach_settings,
        _validate_self_monitor_profile,
        _validate_feature_flags,
    ]

    results: List[ValidationResult] = []
    for fn in validators:
        try:
            result = fn()
        except Exception as exc:
            # Validator itself crashed - log and continue
            result = ValidationResult(
                file="<unknown>", status="ERROR",
                message=f"Validator raised unexpectedly: {exc}",
                issues=[str(exc)],
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
    print("Riot Commander - Config Validation")
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
