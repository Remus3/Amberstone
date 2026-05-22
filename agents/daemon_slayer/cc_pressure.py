"""Champion-level CC pressure aggregator over ``_PER_SPELL_CC_DURATIONS``.

First consumer of the per-spell CC duration registry seeded at ENGINE
1.30.0 (2026-05-21) and extended at 1.31.0 (2026-05-21, wave 2 = 53
entries across 44 champions of first-order CC at patch 16.10.1).

ENGINE 1.32.0 (2026-05-22) seam: ``compute_cc_pressure(champion, mode)``
walks the registry, picks max-rank base durations per registered spell,
applies the ARAM tenacity multiplier through
``ehp.effective_cc_duration`` so the math seam is unified, and returns
a structured ``CcPressureResult``. The aggregate ``total_cc_seconds``
is the sum of max-rank post-tenacity values across all registered
spells - the simplest correct first-pass aggregator for downstream
fight-sim / EHP-vs-CC blended scorer / coach-prompt renderer
consumers.

Empty result (``total_cc_seconds=0.0`` + empty ``spells`` tuple) for:
  * champion not in registry (44 of 172 champs at 1.31.0; 128 absent)
  * registry has no spell entries for the champion (defensive)
  * champion is blank / None (still returns the empty result; never
    raises - the helper is fail-soft to match aram_tenacity_context's
    contract).

In ARAM / KIWI mode, reads ``aramTenacity`` from the patch-pinned
``data/daemon_slayer/<patch>/champions.json`` via the SAME loader
pattern as ``core/aram_tenacity_context.py`` (read once at module
import; fail-soft to ``{}`` on missing / malformed files). Other
modes use 1.0 (identity).

Schema mirrors the AbilitySpellDps surface from 1.30.0:
  * ``CcSpellEntry.spell_key`` in {"Q","W","E","R"} - canonical order
  * ``CcSpellEntry.base_durations_s`` - raw per-rank tuple from the
    registry (length 1, 3, or 5)
  * ``CcSpellEntry.max_rank_duration_s`` - last element of the tuple
  * ``CcSpellEntry.duration_post_tenacity_s`` - max-rank post-tenacity
  * ``CcPressureResult.tenacity_mult`` - 1.0 outside ARAM/KIWI

The returned ``spells`` tuple is sorted in canonical Q-W-E-R order
even when the registry stores spells out of order, so consumers can
zip with a fixed-order display layout without re-sorting.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Dict

from .ability_dps import _PER_SPELL_CC_DURATIONS
from .ehp import effective_cc_duration

_DATA_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "data"
    / "daemon_slayer"
)
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)
_SPELL_ORDER = ("Q", "W", "E", "R")


@dataclass(frozen=True)
class CcSpellEntry:
    """Per-spell CC entry for a single champion+spell-key.

    ``spell_key`` is one of ``{"Q", "W", "E", "R"}``. ``base_durations_s``
    is the raw per-rank tuple read directly from the registry (length
    1, 3, or 5). ``max_rank_duration_s`` is the last element of the
    tuple (max rank, the upper-bound expression). ``duration_post_tenacity_s``
    is ``max_rank_duration_s`` after applying the ARAM tenacity
    multiplier via ``ehp.effective_cc_duration``; equals
    ``max_rank_duration_s`` outside ARAM/KIWI mode.
    """

    spell_key: str
    base_durations_s: tuple[float, ...]
    max_rank_duration_s: float
    duration_post_tenacity_s: float


@dataclass(frozen=True)
class CcPressureResult:
    """Aggregate CC pressure for a single champion in a given mode.

    ``total_cc_seconds`` is the sum of ``duration_post_tenacity_s``
    across all registered spells (max-rank post-tenacity). Returns
    0.0 for unregistered champions / empty registries.

    ``spells`` is a tuple of ``CcSpellEntry`` in canonical Q-W-E-R
    order over the SUBSET of spells the champion has registered (Galio
    registers W/E/R only -> the tuple has 3 entries in W-E-R order;
    Annie registers R only -> 1 entry).

    ``tenacity_mult`` is the multiplier applied: 1.0 outside ARAM /
    KIWI; the ``aramTenacity`` value from ``champions.json`` in
    ARAM / KIWI mode (1.0 default for the 155 non-modified champs;
    1.10 / 1.20 for the 17 modified assassins at 16.10.1).
    """

    champion: str
    mode: str
    total_cc_seconds: float
    spells: tuple[CcSpellEntry, ...] = field(default_factory=tuple)
    tenacity_mult: float = 1.0


def _load_tenacity_map() -> Dict[str, float]:
    """Read patch + champions.json once; return {champion_name: tenacity_mult}.

    Mirrors ``core/aram_tenacity_context._load_tenacity_map`` exactly so
    the two modules share the same patch-data source (single registry
    of the 17 modified-tenacity champs at 16.10.1). Default-1.0 champs
    are intentionally omitted; a missing entry signals "no modifier".

    Fail-soft on missing files / malformed JSON / unexpected shapes:
    returns ``{}`` and consumers degenerate to identity.
    """
    try:
        patch_file = _DATA_DIR / "current.txt"
        patch = patch_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not patch:
        return {}
    champs_file = _DATA_DIR / patch / "champions.json"
    try:
        raw = json.loads(champs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, float] = {}
    for cid, champ in data.items():
        if not isinstance(champ, dict):
            continue
        lolmath = champ.get("lolmath") or {}
        aram = lolmath.get("aram_modifiers") or {}
        try:
            mult = float(aram.get("aramTenacity", 1.0))
        except (TypeError, ValueError):
            continue
        if mult != 1.0:
            result[cid] = mult
    return result


_TENACITY_MAP: Dict[str, float] = _load_tenacity_map()


def _is_aram_mode(mode: str | None) -> bool:
    """Return True if ``mode`` is an ARAM-family mode (ARAM / KIWI etc.).

    Mirrors ``aram_tenacity_context._ARAM_MODES`` membership: ARAM,
    KIWI (ARAM Mayhem), ARAM_5V5, ARAM_MAYHEM, plus their lowercase
    forms. Returns False for None, empty string, SR, CHERRY (Arena),
    or any unknown mode token.
    """
    if not mode:
        return False
    return mode in _ARAM_MODES or mode.upper() in _ARAM_MODES


def compute_cc_pressure(champion: str, mode: str = "SR") -> CcPressureResult:
    """Aggregate first-order CC durations for a champion across registered spells.

    Reads ``_PER_SPELL_CC_DURATIONS`` from ``ability_dps``. Returns an
    empty result (``total_cc_seconds=0.0`` + empty ``spells`` tuple)
    when:
      * champion not in registry
      * registry has no spell entries for the champion (defensive)
      * champion is blank / None (still returns the empty result;
        never raises)

    In ARAM / KIWI mode reads ``aramTenacity`` from the patch-pinned
    ``data/daemon_slayer/<patch>/champions.json`` (the same source
    ``core/aram_tenacity_context.py`` uses); other modes use 1.0.
    Tenacity is applied via ``ehp.effective_cc_duration(base, mult)``
    so the math seam is unified.

    The returned ``spells`` tuple is sorted in canonical Q-W-E-R order
    over the subset of spells the champion has registered.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return CcPressureResult(
            champion="",
            mode=safe_mode,
            total_cc_seconds=0.0,
            spells=(),
            tenacity_mult=1.0,
        )
    # Mode-gated tenacity: only ARAM-family modes pull non-1.0 mult.
    if _is_aram_mode(safe_mode):
        tenacity_mult = _TENACITY_MAP.get(champion, 1.0)
    else:
        tenacity_mult = 1.0
    spells_dict = _PER_SPELL_CC_DURATIONS.get(champion, {}) or {}
    if not spells_dict:
        return CcPressureResult(
            champion=champion,
            mode=safe_mode,
            total_cc_seconds=0.0,
            spells=(),
            tenacity_mult=tenacity_mult,
        )
    entries: list[CcSpellEntry] = []
    total = 0.0
    for spell_key in _SPELL_ORDER:
        durations = spells_dict.get(spell_key)
        if not durations:
            continue
        max_rank = float(durations[-1])
        post_tenacity = effective_cc_duration(max_rank, tenacity_mult)
        entries.append(
            CcSpellEntry(
                spell_key=spell_key,
                base_durations_s=tuple(float(d) for d in durations),
                max_rank_duration_s=max_rank,
                duration_post_tenacity_s=post_tenacity,
            )
        )
        total += post_tenacity
    return CcPressureResult(
        champion=champion,
        mode=safe_mode,
        total_cc_seconds=total,
        spells=tuple(entries),
        tenacity_mult=tenacity_mult,
    )


__all__ = [
    "CcPressureResult",
    "CcSpellEntry",
    "compute_cc_pressure",
]
