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
  champion+mode -> champion global -> dataset global_fallback -> 0.0

Returns 0.0 only when the JSON is missing entirely - safe no-op for any
proc that multiplies by this value.

CANONICAL-KEY SEAM (``apply_canonical_cast_rate_keys``, DEFAULT-OFF)
--------------------------------------------------------------------
Both JSON files are keyed by canonical DDragon **id** ("KogMaw",
"Khazix", "MonkeyKing"), but every production caller passes
``resolved.champion_name``, which ``engine.py`` sets to the DDragon
**display** name ("Kog'Maw", "Kha'Zix", "Wukong"). The 21 champions whose
display name differs from their id therefore miss their measured row and
silently take ``global_fallback`` while ``casts_per_sec_source`` still
reports ``"measured"``. Four call sites are affected:

  * ``ability_dps.py`` - spell rates (ability DPS) + ult rate (item procs)
  * ``dps.py``         - ult rate (carry / Malignance)
  * ``ability_hps.py`` - spell rates (heal/shield HPS)

The correction is NOT byte-identical: ``global_fallback`` is a per-spell
VECTOR, so fixing the key is a per-spell REWEIGHT rather than a uniform
scale (measured: 13 of 21 champions reorder on the ability scorer, 3 of
21 on carry). It therefore ships behind a DEFAULT-OFF flag.

The seam lives HERE rather than at the four callers on purpose - the
parameter is named ``champion_name``, so any future call site inherits
the correction instead of re-arming the trap.

Flip it process-wide::

    from agents.daemon_slayer import ult_rates
    ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS = True

or per call via the trailing ``apply_canonical_cast_rate_keys`` kwarg on
either public function.
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

# DEFAULT-OFF canonical-key seam (see the module docstring). False keeps
# every lookup byte-identical to the raw display-name behavior; True
# resolves the incoming name to its DDragon id before indexing the file.
APPLY_CANONICAL_CAST_RATE_KEYS = False


def _resolve_champ_key(
    champion_name: str,
    apply_canonical_cast_rate_keys: bool | None = None,
) -> str:
    """Map an incoming champion name onto the dataset's key space.

    ``None`` (the default) defers to the module-level
    ``APPLY_CANONICAL_CAST_RATE_KEYS``; an explicit bool overrides it for
    this call only.

    Reuses the single canonical resolver
    (:func:`core.archetype_picks.canonical_champion_id`) rather than
    carrying a second alias dict - it is derived from
    ``ddragon_champions.json``, so a rename or a new release is picked up
    by a data refresh with no code change. It handles the apostrophe /
    space variants AND the three names that are not punctuation variants
    at all ("Wukong" -> MonkeyKing, "Nunu & Willump" -> Nunu, "Renata
    Glasc" -> Renata).

    The import is deliberately LAZY and wrapped: ``agents/daemon_slayer``
    has no module-scope dependency on ``core`` and the real dependency
    runs the other way (``core/aram_tenacity_context.py`` imports
    ``agents.daemon_slayer.ehp``), so a top-level ``from core...`` here
    would invert that edge and risk a cycle. Same pattern as
    ``core.daemon_slayer_client._canon_champ_key``.

    Fail-soft on every path: an unresolvable name, a missing data file, or
    an import failure all pass the input through unchanged, so a lookup is
    never gated on the resolver.
    """
    enabled = (
        APPLY_CANONICAL_CAST_RATE_KEYS
        if apply_canonical_cast_rate_keys is None
        else bool(apply_canonical_cast_rate_keys)
    )
    if not enabled:
        return champion_name
    try:
        from core.archetype_picks import canonical_champion_id

        return canonical_champion_id(champion_name) or champion_name
    except Exception:  # noqa: BLE001 - fail-soft resolver, never gate a lookup
        return champion_name


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
            # Missing file -> all-zero fallback. The function's docstring
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


def get_ult_casts_per_sec(
    champion_name: str,
    mode: str,
    apply_canonical_cast_rate_keys: bool | None = None,
) -> float:
    """Return median ult casts/sec for champion+mode.

    Backward-compat shim - predates the Phase 4b spell-rate file. Reads
    ``ult_cast_rates.json`` directly; falls through to the spell file's
    R-key when the ult file is missing or stale.

    Used by Malignance Hatefog's proc-rate model. Phase 4b's
    ``compute_ability_dps`` calls ``get_spell_casts_per_sec(..., "R", ...)``
    for parity.

    ``champion_name`` accepts a canonical DDragon id or - only under the
    DEFAULT-OFF ``apply_canonical_cast_rate_keys`` seam - a display name.
    See the module docstring.
    """
    data = _load_ult()
    champ_key = _resolve_champ_key(champion_name, apply_canonical_cast_rate_keys)
    champ_data = data.get("by_champ_mode", {}).get(champ_key, {})
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


def get_spell_casts_per_sec(
    champion_name: str,
    key: str,
    mode: str,
    apply_canonical_cast_rate_keys: bool | None = None,
) -> float:
    """Return median casts/sec for one of ``Q/W/E/R`` for champion+mode.

    Phase 4b (s178, 2026-05-12). Sibling of ``get_ult_casts_per_sec`` but
    parameterised over the spell key. Same fallback chain:

      1. champion + mode -> return matching rate
      2. champion's "global" entry -> return matching rate
      3. file-level global_fallback[key]
      4. 0.0 (file missing)

    Raises ``ValueError`` if ``key`` isn't one of Q/W/E/R - passive
    damage isn't covered by this dataset.

    ``champion_name`` accepts a canonical DDragon id or - only under the
    DEFAULT-OFF ``apply_canonical_cast_rate_keys`` seam - a display name.
    See the module docstring.
    """
    if key not in _SPELL_KEYS:
        raise ValueError(f"key must be one of {_SPELL_KEYS}, got {key!r}")
    data = _load_spells()
    champ_key = _resolve_champ_key(champion_name, apply_canonical_cast_rate_keys)
    champ_data = data.get("by_champ_mode", {}).get(champ_key, {})
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
