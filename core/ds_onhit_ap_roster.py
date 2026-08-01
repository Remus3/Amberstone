"""Slice B Task 9 (2026-07-16) - on-hit-AP roster loader.

Loads ``core/ds_onhit_ap_roster.json`` (nested ``{"champions": {<id>:
{"coherence": <float>}, ...}}``, hand-authored + live-calibrated by
``tools/ds_onhit_ap_prefilter.py`` against :8860/rank-onhit - see
``.superpowers/sdd/task-9-report.md``) and FLATTENS it to
``{canonical_champ_id: coherence}``.

CRITICAL SHAPE CONTRACT: Task 7's ``core/daemon_slayer_client.py
::_onhit_coherence_for`` already does
``from core.ds_onhit_ap_roster import load_onhit_ap_roster`` and then
``float(roster.get(key, 0.0))``. If this loader returned the nested dict
verbatim, ``roster.get(key, 0.0)`` would hand back a ``{"coherence": ...}``
dict (or the 0.0 default for a miss) and ``float(dict)`` raises TypeError -
caught by that caller's own ``except Exception`` fail-soft, silently
collapsing EVERY champion (including the seed 3) to 0.0 forever. The flatten
in ``load_onhit_ap_roster`` below is what keeps the gate live.

Cached per process (module-level dict, threading.Lock - same pattern as
``hybrid._load_archetype_weights`` / ``archetype_picks._ID_CACHE``).
Fail-soft: a missing, unreadable, or malformed file returns ``{}`` (every
champion then resolves through the caller's own ``roster.get(key, 0.0)``
default), never raises - a roster problem must never crash coaching.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_ROSTER_PATH = Path(__file__).resolve().parent / "ds_onhit_ap_roster.json"

_ROSTER_LOCK = threading.Lock()
_ROSTER_CACHE: Optional[dict[str, float]] = None


def _flatten(raw: dict) -> dict[str, float]:
    """``{"champions": {champ: {"coherence": x}, ...}}`` -> ``{champ: x}``.

    Skips (does not raise on) any entry missing/malformed ``coherence`` so
    one bad hand-edit degrades to "that champion falls back to 0.0" rather
    than nuking the whole roster.
    """
    out: dict[str, float] = {}
    champions = raw.get("champions") if isinstance(raw, dict) else None
    if not isinstance(champions, dict):
        return out
    for champ, entry in champions.items():
        if not isinstance(entry, dict):
            continue
        try:
            out[champ] = float(entry["coherence"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_onhit_ap_roster() -> dict[str, float]:
    """Return the cached, flattened ``{canonical_champ_id: coherence}`` map.

    Fail-soft to ``{}`` on any error (missing file / bad JSON / wrong
    shape) - never raises, so a roster problem degrades to "the coherence
    gate is off for every champion" (byte-identical to pre-Task-9
    behavior), not a crash.
    """
    global _ROSTER_CACHE
    with _ROSTER_LOCK:
        if _ROSTER_CACHE is None:
            try:
                raw = json.loads(_ROSTER_PATH.read_text(encoding="utf-8"))
                _ROSTER_CACHE = _flatten(raw)
            except Exception:  # noqa: BLE001 - fail-soft loader, never raise
                _ROSTER_CACHE = {}
        return _ROSTER_CACHE
