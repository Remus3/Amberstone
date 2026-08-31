"""
core/feature_policy.py
Phase 1 Step 7 / 7.1 / Phase 2 Step 2 - Runtime feature policy matrix with hot-reload.

Public API
----------
  is_allowed(mode, feature) -> bool
    Returns True if the feature is "allow" for the given mode.
    Hot-reload: on each call the file mtime is checked cheaply; if changed,
    the file is reloaded.  If the reload fails, the last-known-good matrix
    is kept active.  Safe default is True (allow) for any failure.

  write_disabled_placeholder(mode, feature=None) -> None
    Writes a neutral policy-disabled placeholder to coaching artifact files.

  get_policy_state() -> dict
    Returns a compact snapshot of the current effective policy for MetricsCache.
    Keys: policy_source_status, policy_last_reload_ts, policy_last_warning,
          effective_decisions (nested dict of mode -> feature -> decision).
    Never raises. Called from MetricsCache background thread.

Phase 2 Step 2 hot-reload design
---------------------------------
  - _PolicyCache class owns the loaded matrix, last-known-good snapshot,
    file mtime, and status/warning state.
  - is_allowed() calls _cache._check_reload() on each invocation.
  - get_policy_state() also calls _cache._check_reload() (Phase 2 Step 2.1),
    so MetricsCache/OPS UI picks up changes in idle mode without waiting
    for a coach gate call.
  - _check_reload() compares current file mtime to cached mtime.
    - If unchanged: no I/O (O(1) os.stat call only).
    - If changed: attempt reload; validate each decision value.
      - If valid: replace active matrix + last-known-good.
      - If invalid: keep last-known-good; record warning + "invalid_reload_retained" status.
  - File disappearance after a valid load: mtime comparison fails (file gone),
    treated as reload failure -> last-known-good retained.
  - Scope honesty: hot-reload is "next is_allowed() call sees new decision".
    It is a lazy pull model, not a push/subscribe model.
  - Warnings are last-one-wins (single string field, not a history list).

Python 3.9 compatible: no X|Y unions, no walrus, no match.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger("rc.feature_policy")

# -- Paths -----------------------------------------------------------------

_PROJECT_DIR = Path(__file__).parent.parent
_CONFIG_PATH = _PROJECT_DIR / "config" / "feature_flags.json"
_DATA_DIR    = _PROJECT_DIR / "data"

# SR coaching artifact lives at the project root (not in data/)
# This matches app.py: DATA_FILE = SCRIPT_DIR / "coaching_data.json"
_SR_ARTIFACT  = _PROJECT_DIR / "coaching_data.json"

# -- Constants -------------------------------------------------------------

_VALID_DECISIONS = {"allow", "disabled"}
_SAFE_DEFAULT    = "allow"

# Known modes and their known features
_KNOWN_FEATURES: Dict[str, set] = {
    "sr":    {"live_coaching"},
    "aram":  {"live_coaching"},
    "arena": {"live_coaching"},
    "brawl": {"live_coaching"},
    "tft":   {"live_coaching", "tft_vision_analysis"},
}

# -- Neutral placeholder payloads ------------------------------------------

_SR_DISABLED_PAYLOAD = {
    "mode": "game",
    "action": "COACHING DISABLED",
    "immediate": "Live coaching is currently disabled by policy.",
    "next": "", "wave": "", "objective": "", "fight_rule": "",
    "reset_item": "", "risk": "", "map": "", "log": [], "pregame": "",
    "win_pct": None,
}

_TFT_COACHING_DISABLED_PAYLOAD = {
    "mode": "tft",
    "action": "COACHING DISABLED",
    "board": "", "econ": "", "rolldown": "", "items": "",
    # LANE 8 CYCLE 30: this said "carousel". This module is a co-writer of
    # data/tft_coaching_data.json, whose shape is declared by
    # core/coaching_payload.TftPayload (god_pick) and seeded by
    # coaches/tft_coach.py (god_pick). The disabled payload was the third
    # disagreeing spelling of one field.
    "god_pick": "", "placement": "", "upgrade": "", "risk": "",
}

_TFT_LIVE_DISABLED_PAYLOAD = {
    "mode": "tft_live",
    "comp": "", "build": "", "buy": "", "sell": "", "keep": "",
    "augment_play": "", "loss": "", "unit_placement": "", "unit_swap": "",
    "augment_select": False, "stage_round": "", "level": 0, "hp": 0,
    "board_units": [], "bench_units": [], "shop_units": [],
    "traits_active": [], "augments": [],
}

# -- Policy status values ---------------------------------------------------

_STATUS_DEFAULT              = "default"           # no file; all-allow defaults
_STATUS_LOADED               = "loaded"            # file parsed and valid
_STATUS_LAST_KNOWN_GOOD      = "last_known_good"   # reloaded from previously good snapshot
_STATUS_INVALID_RELOAD       = "invalid_reload_retained"  # bad reload; prior good kept
_STATUS_MISSING              = "missing"           # file absent at startup


# -- _PolicyCache ----------------------------------------------------------

class _PolicyCache:
    """
    Holds the effective policy matrix and manages hot-reload.

    Hot-reload semantics (pull model):
      - _check_reload() is called from is_allowed() on each invocation.
      - mtime of config/feature_flags.json is compared to cached mtime.
      - If unchanged: no I/O.
      - If changed or file disappeared: attempt reload.
        - Valid reload: replaces _matrix, _lkg_matrix, updates status.
        - Invalid reload: keeps _lkg_matrix active, sets warning + invalid status.
      - "last warning" is last-one-wins (single string, not a history list).
    """

    __slots__ = (
        "_path", "_matrix", "_lkg_matrix",
        "_mtime", "_status", "_reload_ts", "_last_warning",
    )

    def __init__(self, path: Path) -> None:
        self._path         = path
        self._matrix:      Dict[str, Any] = {}
        self._lkg_matrix:  Dict[str, Any] = {}   # last-known-good
        self._mtime:       float = -1.0
        self._status:      str   = _STATUS_DEFAULT
        self._reload_ts:   Optional[str] = None
        self._last_warning: Optional[str] = None
        self._initial_load()

    # -- Initial load ------------------------------------------------------

    def _initial_load(self) -> None:
        if not self._path.exists():
            self._status = _STATUS_MISSING
            _log.info("feature_policy: %s not found - using safe defaults", self._path)
            return
        data, err = self._try_load()
        if data is not None:
            self._matrix     = data
            self._lkg_matrix = data
            self._mtime      = self._get_mtime()
            self._status     = _STATUS_LOADED
            self._reload_ts  = _utc_now()
            _log.info("feature_policy: loaded from %s", self._path)
        else:
            self._status      = _STATUS_INVALID_RELOAD
            self._last_warning = f"Initial load failed: {err}"
            _log.error("feature_policy: initial load failed: %s - using safe defaults", err)

    # -- Hot-reload --------------------------------------------------------

    def _check_reload(self) -> None:
        """Check mtime and reload if changed. O(1) stat call when unchanged."""
        try:
            current_mtime = self._get_mtime()
        except Exception:  # noqa: BLE001
            # File disappeared after prior load - keep last-known-good
            if self._lkg_matrix:
                if self._status != _STATUS_LAST_KNOWN_GOOD:
                    self._status       = _STATUS_LAST_KNOWN_GOOD
                    self._last_warning = "config/feature_flags.json missing at reload; retaining last-known-good"
                    _log.warning("feature_policy: %s", self._last_warning)
                self._matrix = self._lkg_matrix
            return

        if current_mtime == self._mtime:
            return  # unchanged

        # File changed - attempt reload
        data, err = self._try_load()
        if data is not None:
            self._matrix     = data
            self._lkg_matrix = data
            self._mtime      = current_mtime
            self._status     = _STATUS_LOADED
            self._reload_ts  = _utc_now()
            self._last_warning = None
            _log.info("feature_policy: hot-reloaded from %s", self._path)
        else:
            # Invalid reload - keep last-known-good
            self._matrix       = self._lkg_matrix
            self._mtime        = current_mtime  # advance mtime so we don't re-try every call
            self._status       = _STATUS_INVALID_RELOAD
            self._last_warning = f"Hot-reload failed: {err} - retaining last-known-good"
            _log.warning("feature_policy: %s", self._last_warning)

    # -- Helpers -----------------------------------------------------------

    def _get_mtime(self) -> float:
        return self._path.stat().st_mtime

    def _try_load(self):
        """
        Parse and validate feature_flags.json.
        Returns (data_dict, None) on success, (None, error_str) on failure.
        """
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return None, f"JSON parse error: {exc}"

        if not isinstance(raw, dict):
            return None, "top-level value is not a JSON object"

        # Validate all present mode/feature/decision values
        for key, block in raw.items():
            if key.startswith("_"):
                continue  # metadata keys
            if key not in _KNOWN_FEATURES:
                # Unknown mode - warn but still accept (forward-compatible)
                _log.warning("feature_policy: unknown mode %r in config", key)
                continue
            if not isinstance(block, dict):
                return None, f"mode '{key}' block is not an object"
            for feat, dec in block.items():
                if feat not in _KNOWN_FEATURES.get(key, set()):
                    _log.warning("feature_policy: unknown feature %r in mode %r", feat, key)
                    continue
                if dec not in _VALID_DECISIONS:
                    return None, (
                        f"invalid decision {dec!r} for {key}.{feat}"
                        f" (expected 'allow' or 'disabled')"
                    )
        return raw, None

    # -- Policy state snapshot ---------------------------------------------

    def get_policy_state(self) -> Dict[str, Any]:
        """
        Return a compact snapshot of effective policy for MetricsCache.
        Never raises. Called from MetricsCache background thread.

        Keys:
          policy_source_status  : str - one of the _STATUS_* values
          policy_last_reload_ts : str | None - ISO-8601 UTC of last successful load
          policy_last_warning   : str | None - last warning text (last-one-wins)
          effective_decisions   : dict - {mode: {feature: "allow"|"disabled"|"default"}}
        """
        try:
            decisions: Dict[str, Dict[str, str]] = {}
            for mode, features in _KNOWN_FEATURES.items():
                decisions[mode] = {}
                block = self._matrix.get(mode)
                for feat in sorted(features):
                    if isinstance(block, dict):
                        dec = block.get(feat)
                        if dec in _VALID_DECISIONS:
                            decisions[mode][feat] = dec
                        else:
                            decisions[mode][feat] = "allow"  # safe default
                    else:
                        decisions[mode][feat] = "allow"  # safe default

            return {
                "policy_source_status":  self._status,
                "policy_last_reload_ts": self._reload_ts,
                "policy_last_warning":   self._last_warning,
                "effective_decisions":   decisions,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "policy_source_status":  "error",
                "policy_last_reload_ts": None,
                "policy_last_warning":   str(exc),
                "effective_decisions":   {},
            }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- Module-level cache singleton ------------------------------------------

_cache = _PolicyCache(_CONFIG_PATH)


def _reload(path: Optional[Path] = None) -> None:
    """
    Force-replace the module-level cache. For testing only.
    In production, hot-reload happens automatically via mtime check.
    """
    global _cache
    _cache = _PolicyCache(path or _CONFIG_PATH)


# -- Public API ------------------------------------------------------------

def is_allowed(mode: str, feature: str) -> bool:
    """
    Return True if the feature is "allow" for the given mode.

    Hot-reload: checks file mtime on each call; reloads if changed.
    Safe default: True (allow) for unknown mode/feature/malformed value or any error.

    Parameters
    ----------
    mode    : "sr" | "aram" | "arena" | "brawl" | "tft"
    feature : "live_coaching" | "tft_vision_analysis"
    """
    try:
        _cache._check_reload()
    except Exception:  # noqa: BLE001
        pass  # reload errors are non-fatal; proceed with cached matrix

    mode_key = mode.lower().strip()

    if mode_key not in _KNOWN_FEATURES:
        _log.warning("feature_policy: unknown mode %r - defaulting to allow", mode_key)
        return True

    if feature not in _KNOWN_FEATURES[mode_key]:
        _log.warning(
            "feature_policy: unknown feature %r for mode %r - defaulting to allow",
            feature, mode_key,
        )
        return True

    mode_block = _cache._matrix.get(mode_key)
    if not isinstance(mode_block, dict):
        return True

    decision = mode_block.get(feature)
    if decision is None:
        return True

    if decision not in _VALID_DECISIONS:
        _log.warning(
            "feature_policy: malformed decision %r for %s.%s - defaulting to allow",
            decision, mode_key, feature,
        )
        return True

    return decision == "allow"


def get_policy_state() -> Dict[str, Any]:
    """
    Return compact effective policy snapshot for MetricsCache.
    Never raises. Safe to call from any thread.

    Phase 2 Step 2.1: also calls _check_reload() so that MetricsCache/OPS
    policy visibility picks up file changes without requiring any worker or
    coach gate path (is_allowed) to fire first.  This makes policy state
    current in idle/client mode.
    """
    try:
        _cache._check_reload()
    except Exception:  # noqa: BLE001
        pass  # non-fatal; proceed with cached state
    try:
        return _cache.get_policy_state()
    except Exception as exc:  # noqa: BLE001
        return {
            "policy_source_status":  "error",
            "policy_last_reload_ts": None,
            "policy_last_warning":   str(exc),
            "effective_decisions":   {},
        }


def write_disabled_placeholder(mode: str, feature: Optional[str] = None,
                               artifact_root: Optional[Path] = None) -> None:
    """
    Write a neutral policy-disabled placeholder to coaching artifact files.

    artifact_root: optional test-only override for the output root directories.
      When None (default): writes to the real production paths (_PROJECT_DIR
      and _DATA_DIR) - production behavior is fully preserved.
      When set: sr artifact -> artifact_root/coaching_data.json;
                data/* artifacts -> artifact_root/data/<name>.
      Tests should always pass artifact_root pointing to a temp directory.
      No runtime code path sets this parameter.

    Feature-specific for TFT:
      mode="tft", feature="live_coaching"       -> tft_coaching_data.json only
      mode="tft", feature="tft_vision_analysis" -> tft_live_data.json only
      mode="tft", feature=None                  -> both TFT artifacts

    Non-fatal. Does not affect GameEnvelope or worker state authority.
    """
    mode_key = mode.lower().strip()
    # Resolve output paths: use override root for tests, live paths for production.
    if artifact_root is not None:
        _sr   = Path(artifact_root) / "coaching_data.json"
        _data = Path(artifact_root) / "data"
    else:
        _sr   = _SR_ARTIFACT
        _data = _DATA_DIR
    try:
        if mode_key == "sr":
            _write_json(_sr, _SR_DISABLED_PAYLOAD)
        elif mode_key == "aram":
            _write_json(_data / "aram_coaching_data.json", _SR_DISABLED_PAYLOAD)
        elif mode_key == "arena":
            _write_json(_data / "arena_coaching_data.json", _SR_DISABLED_PAYLOAD)
        elif mode_key == "brawl":
            _write_json(_data / "brawl_coaching_data.json", _SR_DISABLED_PAYLOAD)
        elif mode_key == "tft":
            if feature is None or feature == "live_coaching":
                _write_json(_data / "tft_coaching_data.json",
                            _TFT_COACHING_DISABLED_PAYLOAD)
            if feature is None or feature == "tft_vision_analysis":
                _write_json(_data / "tft_live_data.json",
                            _TFT_LIVE_DISABLED_PAYLOAD)
        else:
            _log.warning("feature_policy: write_disabled_placeholder: unknown mode %r", mode_key)
    except Exception as exc:  # noqa: BLE001
        _log.error(
            "feature_policy: write_disabled_placeholder(%r, %r) failed: %s",
            mode_key, feature, exc,
        )


def _write_json(path: Path, data: dict) -> None:
    """Atomically write a JSON file. Parent dir is created if absent."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        _log.error("feature_policy: _write_json(%s) failed: %s", path, exc)
