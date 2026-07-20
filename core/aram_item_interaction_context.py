"""RM-111 consumer-side loader for the ARAM item-interaction snapshot.

WHAT
    ``core/aram_item_interaction.py`` mines the local ARAM corpus for
    ``(enemy-comp-shape x item x purchase-timing) -> outcome``. That aggregation
    walks ~2000 matches worth of timeline frames and is FAR too slow for a live
    coach tick, so it is precomputed OFFLINE to
    ``data/coaching/aram_item_interaction.json`` by
    ``tools/aram_item_interaction_precompute.py``. This module is the read side:
    a module-level memoised index over that snapshot plus a render-side cue
    function.

PRECEDENT
    Mirrors ``core/aram_balance_context.py`` (snapshot read once at import,
    render-side mode-gated function, fail-soft to empty, ``_ARAM_MODES``
    frozenset gate) and ``core/death_patterns_loader.py`` (offline-precomputed
    JSON out of ``data/coaching/``).

HARD FIREWALL (inherited from the aggregator)
    DESCRIPTIVE / EMPIRICAL ONLY. These cues are "what happened in my own
    games", never an input to ``agents/daemon_slayer`` rank.

RENDER CONTRACT
    ``item_interaction_cues`` returns an entry for EVERY requested item name.
    A cell the snapshot does not carry renders ``CUE_SENTINEL`` ("-") rather
    than being omitted, because the UI reserves the tile caption slot and must
    not reflow on data absence (memory ``feedback_no_reflow_on_data_absence``).
    The whole dict is empty ONLY when there is nothing to render at all:
    non-ARAM mode, no snapshot, or no requested items.

Never raises into a coach tick: every path is fail-soft. ASCII only
(CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from core.aram_comp_verdict import compute_factors
from core.aram_item_interaction import (
    DEFAULT_TIMING_BUCKETS,
    _timing_bucket,
    champion_names_by_id,
    shape_from_factors,
)

# Rendered in place of a cue when the snapshot has no cell for
# (shape, timing, item). The key is ALWAYS present so the UI slot is stable.
CUE_SENTINEL = "-"

SCHEMA = "aram_item_interaction/v1"

_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "coaching" / "aram_item_interaction.json"
)

# Same gate literal set as core/aram_balance_context.py.
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)

# Module-level memo. ``None`` = not loaded yet (distinct from ``{}`` = loaded
# and empty / unusable). Tests override it via ``_load_index(path=...)``.
_INDEX: Optional[Dict[str, Any]] = None


def _fmt_cue(cell: dict) -> Optional[str]:
    """Render one snapshot cell as a short ASCII tile caption.

    Uses the SHRUNK / SMOOTHED numbers, never the raw winrate. Shapes:

        "58% n=27 +310g"   with a gold-swing reading
        "58% n=27"         when gold_swing is None (window never fully covered)

    ``None`` when the cell is too malformed to render (the caller then falls
    back to ``CUE_SENTINEL``).
    """
    try:
        pct = int(round(float(cell["winrate_smoothed"]) * 100))
        n = int(cell["n"])
    except (KeyError, TypeError, ValueError):
        return None
    out = f"{pct}% n={n}"
    swing = cell.get("gold_swing")
    if swing is not None:
        try:
            out += f" {int(round(float(swing))):+d}g"
        except (TypeError, ValueError):
            pass
    return out


def _patch_clause(raw: dict) -> str:
    """Render the patch half of the provenance tag, "" when unavailable.

    The corpus is a HISTORICAL blend (it spans many patches and carries no
    games on the patch daemon_slayer currently runs), so a bare "patch=<one>"
    would falsely imply currency. Precedence:

        patch_min != patch_max            -> "patches 13.16-15.17"
        pinned single patch (min == max,
        or only the legacy "patch" field) -> "patch=16.14.1"
        neither                           -> "" (clause omitted)

    ASCII hyphen in the range, never an en-dash (CLAUDE.md hard rule).
    """
    def _str(key: str) -> str:
        val = raw.get(key)
        return val.strip() if isinstance(val, str) and val.strip() else ""

    lo, hi = _str("patch_min"), _str("patch_max")
    if lo and hi:
        return f"patch={lo}" if lo == hi else f"patches {lo}-{hi}"
    pinned = _str("patch") or lo or hi
    return f"patch={pinned}" if pinned else ""


def _load_index(path: Path | str | None = None) -> Dict[str, Any]:
    """Read the snapshot once and build the O(1) lookup structures.

    Returns ``{}`` on ANY failure (absent file, unparseable JSON, unexpected
    shape) so the consumer renders nothing. On success::

        {
          "by_id":       {(shape, timing, item_id): cue_str},
          "by_name":     {(shape, timing, exact_name): cue_str},
          "by_name_ci":  {(shape, timing, lowered_name): cue_str},
          "name_to_id":  {exact_name: item_id},
          "name_ci_to_id": {lowered_name: item_id},
          "provenance":  "own ARAM corpus n=2049 patches 13.16-15.17",
        }

    Cues are pre-rendered at load time so a coach tick is pure dict lookup.
    """
    src = Path(path) if path is not None else _DEFAULT_PATH
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cells = raw.get("cells")
    if not isinstance(cells, list):
        return {}

    by_id: Dict[tuple, str] = {}
    by_name: Dict[tuple, str] = {}
    by_name_ci: Dict[tuple, str] = {}
    name_to_id: Dict[str, int] = {}
    name_ci_to_id: Dict[str, int] = {}

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        shape = cell.get("shape")
        timing = cell.get("timing")
        name = cell.get("name")
        if not isinstance(shape, str) or not isinstance(timing, str):
            continue
        cue = _fmt_cue(cell)
        if cue is None:
            continue
        try:
            iid = int(cell["item_id"])
        except (KeyError, TypeError, ValueError):
            iid = None
        if iid is not None:
            by_id[(shape, timing, iid)] = cue
        if isinstance(name, str) and name:
            by_name[(shape, timing, name)] = cue
            by_name_ci.setdefault((shape, timing, name.lower()), cue)
            if iid is not None:
                name_to_id.setdefault(name, iid)
                name_ci_to_id.setdefault(name.lower(), iid)

    if not by_id and not by_name:
        return {}

    try:
        matches = int(raw.get("matches") or 0)
    except (TypeError, ValueError):
        matches = 0
    bits = ["own ARAM corpus"]
    if matches:
        bits.append(f"n={matches}")
    clause = _patch_clause(raw)
    if clause:
        bits.append(clause)

    return {
        "by_id": by_id,
        "by_name": by_name,
        "by_name_ci": by_name_ci,
        "name_to_id": name_to_id,
        "name_ci_to_id": name_ci_to_id,
        "provenance": " ".join(bits),
    }


def _get_index() -> Dict[str, Any]:
    """Return the memoised index, loading it on first use."""
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = _load_index()
        except Exception:  # noqa: BLE001 - must never raise into a coach tick
            _INDEX = {}
    return _INDEX


def _is_aram(game_mode: str | None) -> bool:
    if not game_mode:
        return False
    return game_mode in _ARAM_MODES or game_mode.upper() in _ARAM_MODES


def _display_names(enemy_champions: Sequence[Any] | None) -> list:
    """Resolve a mixed sequence of riot champion ids / display names to names.

    An entry that parses as an int is looked up in the patch-current catalog;
    anything else is passed through as a display-name string. Unresolvable
    entries are dropped (``compute_factors`` already skips unknown names).
    """
    names_by_id = champion_names_by_id()
    out: list = []
    for entry in (enemy_champions or []):
        if entry is None:
            continue
        if isinstance(entry, bool):
            continue
        if isinstance(entry, int):
            resolved = names_by_id.get(int(entry))
            if resolved:
                out.append(resolved)
            continue
        text = str(entry).strip()
        if not text:
            continue
        if text.isdigit():
            resolved = names_by_id.get(int(text))
            if resolved:
                out.append(resolved)
            continue
        out.append(text)
    return out


def item_interaction_cues(
    enemy_champions: Sequence[Any] | None,
    game_time_s: float | None,
    item_names: Sequence[str] | None,
    *,
    game_mode: str | None = None,
) -> Dict[str, str]:
    """Return ``{item_name: cue}`` for the current comp shape + timing bucket.

    ``enemy_champions`` accepts riot numeric champion ids OR display-name
    strings (mixed is fine); ``game_time_s`` selects the purchase-timing
    bucket; ``item_names`` are the display names on the current build path.

    EVERY name in ``item_names`` gets a key. A cell absent from the snapshot
    renders ``CUE_SENTINEL``. The dict is empty only when ``game_mode`` is not
    an ARAM mode, the snapshot is absent / unparseable, or ``item_names`` is
    empty.
    """
    try:
        if not _is_aram(game_mode):
            return {}
        names = [n for n in (item_names or []) if isinstance(n, str) and n]
        if not names:
            return {}
        index = _get_index()
        if not index:
            return {}
        try:
            timing = _timing_bucket(float(game_time_s or 0.0),
                                    DEFAULT_TIMING_BUCKETS)
        except (TypeError, ValueError):
            timing = None
        shape = shape_from_factors(compute_factors(_display_names(enemy_champions)))

        by_id = index.get("by_id") or {}
        by_name = index.get("by_name") or {}
        by_name_ci = index.get("by_name_ci") or {}
        name_to_id = index.get("name_to_id") or {}
        name_ci_to_id = index.get("name_ci_to_id") or {}

        out: Dict[str, str] = {}
        for name in names:
            cue = None
            if timing is not None:
                iid = name_to_id.get(name)
                if iid is None:
                    iid = name_ci_to_id.get(name.lower())
                if iid is not None:
                    cue = by_id.get((shape, timing, iid))
                if cue is None:
                    cue = by_name.get((shape, timing, name))
                if cue is None:
                    cue = by_name_ci.get((shape, timing, name.lower()))
            out[name] = cue or CUE_SENTINEL
        return out
    except Exception:  # noqa: BLE001 - must never raise into a coach tick
        return {}


def cue_provenance() -> str:
    """Short ASCII provenance tag for the UI, "" when there is no snapshot.

    Example: ``own ARAM corpus n=2049 patches 13.16-15.17``. The corpus spans
    many patches, so the tag carries the RANGE; it collapses to
    ``patch=<p>`` only when the snapshot was pinned to a single patch.
    """
    try:
        return str((_get_index() or {}).get("provenance") or "")
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "CUE_SENTINEL",
    "SCHEMA",
    "cue_provenance",
    "item_interaction_cues",
]
