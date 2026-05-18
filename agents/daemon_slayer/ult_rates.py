"""Per-champion cast rate lookup for ability-triggered items + ability DPS.

Two layers:

* ``get_ult_casts_per_sec`` (s145, 2026-05-05) - R-only path used by
  Malignance Hatefog to convert ult cast frequency into a DPS-time proc
  rate. Reads ``data/daemon_slayer/ult_cast_rates.json``. Predates the
  Phase 4b spell-rate plumbing; kept for backward compat.
* ``get_spell_casts_per_sec`` (s178, 2026-05-12 - Phase 4b) - full
  Q/W/E/R surface used by ``ability_dps.compute_ability_dps()``. Reads
  ``data/daemon_slayer/spell_cast_rates.json``. Same shape and fallback
  chain, expanded to four keys.

Both files are derived from ``rewind_history.db.participants.spell[1-4]_casts
/ matches.game_duration_s`` and refresh via ``scripts/build_spell_cast_rates.py``
(new in Phase 4b - supersedes the s145 ad-hoc query).

Fallback chain (both functions):
  champion+mode → champion global → dataset global_fallback → 0.0

Returns 0.0 only when the JSON is missing entirely - safe no-op for any
proc that multiplies by this value.
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA_ROOT = Path(__file__).parent.parent.parent / "data" / "daemon_slayer"

_ULT_RATE_FILE = _DATA_ROOT / "ult_cast_rates.json"
_SPELL_RATE_FILE = _DATA_ROOT / "spell_cast_rates.json"

# Per-spell global fallback when even the file's global_fallback is missing.
# Roughly matches the s145 ult-only dataset median; Phase 4b's broader
# Q/W/E/R median is ~0.05/0.03/0.04/0.007 - close enough that pinning the
# legacy 0.0073 here keeps R-only Malignance behavior identical.
_LEGACY_GLOBAL_FALLBACK = 0.0073

_ult_cache: dict | None = None
_spell_cache: dict | None = None

# Canonical spell-key set; used to validate inputs to ``get_spell_casts_per_sec``.
_SPELL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")


def _load_ult() -> dict:
    global _ult_cache
    if _ult_cache is None:
        try:
            _ult_cache = json.loads(_ULT_RATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _ult_cache = {"by_champ_mode": {}, "global_fallback": _LEGACY_GLOBAL_FALLBACK}
    return _ult_cache


def _load_spells() -> dict:
    global _spell_cache
    if _spell_cache is None:
        try:
            _spell_cache = json.loads(_SPELL_RATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            # Missing file → all-zero fallback. The function's docstring
            # pins this contract: "Returns 0.0 only when the JSON is
            # missing entirely". Procs that multiply by this value
            # gracefully no-op.
            _spell_cache = {
                "by_champ_mode": {},
                "global_fallback": {k: 0.0 for k in _SPELL_KEYS},
            }
    return _spell_cache


def reset_cache() -> None:
    """Drop both caches so the next call re-reads disk. For test fixtures
    that need to redirect ``_DATA_ROOT`` or rebuild the JSON mid-run.
    """
    global _ult_cache, _spell_cache
    _ult_cache = None
    _spell_cache = None


def get_ult_casts_per_sec(champion_name: str, mode: str) -> float:
    """Return median ult casts/sec for champion+mode.

    Backward-compat shim - predates the Phase 4b spell-rate file. Reads
    ``ult_cast_rates.json`` directly; falls through to the spell file's
    R-key when the ult file is missing or stale.

    Used by Malignance Hatefog's proc-rate model. Phase 4b's
    ``compute_ability_dps`` calls ``get_spell_casts_per_sec(..., "R", ...)``
    for parity.
    """
    data = _load_ult()
    champ_data = data.get("by_champ_mode", {}).get(champion_name, {})
    rate = champ_data.get(mode)
    if rate is not None:
        return float(rate)
    rate = champ_data.get("global")
    if rate is not None:
        return float(rate)
    fb = data.get("global_fallback", _LEGACY_GLOBAL_FALLBACK)
    # Tolerate the legacy file shape (flat float) AND the new dict shape
    # (Q/W/E/R map) in case ult_cast_rates.json gets regenerated from
    # the same payload as spell_cast_rates.json.
    if isinstance(fb, dict):
        return float(fb.get("R", _LEGACY_GLOBAL_FALLBACK))
    return float(fb)


def get_spell_casts_per_sec(champion_name: str, key: str, mode: str) -> float:
    """Return median casts/sec for one of ``Q/W/E/R`` for champion+mode.

    Phase 4b (s178, 2026-05-12). Sibling of ``get_ult_casts_per_sec`` but
    parameterised over the spell key. Same fallback chain:

      1. champion + mode → return matching rate
      2. champion's "global" entry → return matching rate
      3. file-level global_fallback[key]
      4. 0.0 (file missing)

    Raises ``ValueError`` if ``key`` isn't one of Q/W/E/R - passive
    damage isn't covered by this dataset.
    """
    if key not in _SPELL_KEYS:
        raise ValueError(f"key must be one of {_SPELL_KEYS}, got {key!r}")
    data = _load_spells()
    champ_data = data.get("by_champ_mode", {}).get(champion_name, {})
    by_mode = champ_data.get(mode)
    if isinstance(by_mode, dict) and key in by_mode:
        v = by_mode.get(key)
        if v is not None:
            return float(v)
    by_global = champ_data.get("global")
    if isinstance(by_global, dict) and key in by_global:
        v = by_global.get(key)
        if v is not None:
            return float(v)
    fb = data.get("global_fallback")
    if isinstance(fb, dict):
        v = fb.get(key)
        if v is not None:
            return float(v)
    return 0.0
