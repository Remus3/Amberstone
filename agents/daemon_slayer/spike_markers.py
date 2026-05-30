# arch: live power-spike markers (level + item-completion thresholds) | section=daemon_slayer | frozen=no
"""Live power-spike markers - discrete level + item-completion thresholds.

Competitor lift #4 (Aggregator C power-spike timeline; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 4"). Pure presentation over
RC's OWN DS curves - NO new ENGINE math, NO schema lift, NO new external
dependency. This module classifies a champion's discrete power spikes
against the operator's LIVE level + owned item count and tells the
operator which spikes are CROSSED and which is NEXT - the "now you can
fight" signal that is a stronger single-player cue than a static editorial
profile.

Two spike families:
  * LEVEL spikes: the canonical ultimate-unlock + scaling breakpoints.
    Default 6 / 11 / 16 (R unlock + R rank-2 + R rank-3). The optional
    9 / 13 / 18 mid-rank breakpoints are included when
    ``include_minor=True``.
  * ITEM-COMPLETION spikes: 1 / 2 / 3 finished legendary items. RC does
    NOT scrape per-champion editorial item-spike lists (BF Sword, Sheen,
    etc.); the honest single-player signal is "you have completed your
    Nth core item" - the count of finished legendaries the operator owns.

A marker is ``crossed`` when the operator is AT or PAST its threshold.
Exactly one not-yet-crossed marker is flagged ``next`` - the nearest
upcoming spike across BOTH families (the level marker and the item marker
each contribute candidates; whichever threshold the operator is closest to
reaching is the single ``next``). When everything is crossed, ``next`` is
None.

Level markers are optionally annotated with ``dps_at`` = the champion's
``weighted_dps`` at that level from ``compute_dps_curve`` (same DS curve
the spike-curve panel uses), so the operator sees the raw power jump at
each breakpoint. Item markers carry no ``dps_at`` (the item-completion
count is a build-progress fact, not a level-sweep sample).

v1 honesty contract (per the DEPTH spec):
  * The LIVE-clock cursor (a "now" line at the live game_time) is the
    live-game-only visual half of this lift and is OWED, not in this
    module. This module returns the discrete marker MATH - which spike is
    crossed / next given the operator's live level + item count - which IS
    mock-testable headless. The frontend strip renders the markers; the
    cursor is wired when a live game proves the visual.
  * ``item_count_done`` is the count of FINISHED legendary items the
    operator owns. The caller derives it (from the live inventory or a
    completed-legendary count); this module does not re-derive item
    completion from raw item ids - it trusts the supplied count. When the
    caller passes ``item_ids`` but no explicit ``item_count_done``, the
    count defaults to ``len(item_ids)`` capped at the number of item
    thresholds (a coarse "owned slots" proxy; the caller should pass the
    real finished-legendary count when it has one).
  * Mode is accepted + threaded to ``compute_dps_curve`` for the optional
    ``dps_at`` annotation (ARAM AS/damage modifiers shift the curve), but
    the spike THRESHOLDS themselves are mode-invariant: level 6 unlocks R
    in every mode, and "first finished item" is a build fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Canonical level breakpoints. Major = ultimate unlock + the two ult
# rank-ups (the classic "level 6 power spike" + 11 + 16). Minor adds the
# intermediate scaling breakpoints Aggregator C also calls out (9/13/18).
_MAJOR_LEVEL_SPIKES: Tuple[int, ...] = (6, 11, 16)
_MINOR_LEVEL_SPIKES: Tuple[int, ...] = (9, 13, 18)

# Item-completion breakpoints: 1st / 2nd / 3rd finished legendary item.
# The "two-item spike" is the canonical mid-game power surge; the third
# completes the core. Beyond 3 is end-game polish, not a discrete spike.
_ITEM_SPIKES: Tuple[int, ...] = (1, 2, 3)

# Human labels for level spikes. The three majors map to ult ranks; the
# minors are scaling breakpoints.
_LEVEL_LABELS: Dict[int, str] = {
    6: "R unlock",
    9: "scaling",
    11: "R rank 2",
    13: "scaling",
    16: "R rank 3",
    18: "max level",
}


@dataclass(frozen=True)
class SpikeMarker:
    """One discrete power-spike threshold.

    ``kind`` is "level" or "item". ``threshold`` is the level number (6,
    11, ...) or the finished-legendary count (1, 2, 3). ``label`` is a
    short human descriptor. ``crossed`` is True when the operator is AT or
    PAST the threshold (level >= threshold, or item_count_done >=
    threshold). ``next`` is True for exactly one marker across both
    families - the nearest not-yet-crossed spike. ``dps_at`` is the
    champion's weighted_dps at this level (level markers only, when the
    DS curve annotation succeeds); None otherwise.
    """

    kind: str
    threshold: int
    label: str
    crossed: bool
    next: bool
    dps_at: Optional[float] = None

    def to_dict(self) -> dict:
        out: dict = {
            "kind": self.kind,
            "threshold": self.threshold,
            "label": self.label,
            "crossed": self.crossed,
            "next": self.next,
        }
        if self.dps_at is not None:
            out["dps_at"] = round(float(self.dps_at), 1)
        return out


@dataclass(frozen=True)
class SpikeMarkersResult:
    """Discrete spike markers for a champion at a live level + item count.

    ``markers`` is ordered level spikes first (ascending threshold) then
    item spikes (ascending). ``next_marker`` is the single nearest
    not-yet-crossed marker (or None when everything is crossed).
    ``champion`` echoes the resolved input; ``level`` + ``item_count_done``
    echo the operator's live state.
    """

    champion: str
    level: int
    item_count_done: int
    markers: Tuple[SpikeMarker, ...] = field(default_factory=tuple)
    next_marker: Optional[SpikeMarker] = None

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "level": self.level,
            "item_count_done": self.item_count_done,
            "markers": [m.to_dict() for m in self.markers],
            "next": self.next_marker.to_dict() if self.next_marker else None,
        }


def _clamp_level(level: int) -> int:
    """Champion levels are 1..18. Out-of-range collapses to the bound."""
    try:
        lv = int(level)
    except (TypeError, ValueError):
        return 1
    if lv < 1:
        return 1
    if lv > 18:
        return 18
    return lv


def _level_thresholds(include_minor: bool) -> Tuple[int, ...]:
    if not include_minor:
        return _MAJOR_LEVEL_SPIKES
    merged = sorted(set(_MAJOR_LEVEL_SPIKES) | set(_MINOR_LEVEL_SPIKES))
    return tuple(merged)


def _dps_by_level(
    champion: str, levels: Tuple[int, ...], item_ids: List[str], mode: str
) -> Dict[int, float]:
    """Best-effort ``{level: weighted_dps}`` from ``compute_dps_curve``.

    Loads the DS snapshot + sweeps the requested levels with the supplied
    build. Fail-soft to ``{}`` on ANY error (unknown champion, snapshot
    load failure, scorer-internal error) so the marker classification
    still returns - the ``dps_at`` annotation is a nicety, not a
    prerequisite. The snapshot + curve helper are the SAME ones the
    spike-curve panel uses (``dashboard/routes_spike_curve.py``).
    """
    if not levels:
        return {}
    try:
        from agents.daemon_slayer.data_loader import DataSnapshot
        from agents.daemon_slayer.dps import compute_dps_curve

        snapshot = DataSnapshot.load()
        pts = compute_dps_curve(
            snapshot,
            champion,
            item_ids=tuple(item_ids),
            mode=mode,
            levels=levels,
        )
    except Exception:
        return {}
    out: Dict[int, float] = {}
    for p in pts:
        try:
            out[int(p.level)] = float(p.weighted_dps)
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _is_known_champion(champion: str) -> bool:
    """True when the champion name is non-blank.

    Fail-soft: this module never hard-rejects a real champion on a
    snapshot miss - the level/item thresholds are mode-and-champion
    invariant facts (level 6 unlocks R for everyone; "first finished
    item" is a build fact). A blank / None name is the only hard-False
    case the caller guards on; the optional ``dps_at`` annotation already
    fail-softs to no value when the champion is unknown to the DS engine.
    """
    return bool(champion and str(champion).strip())


def compute_spike_markers(
    champion: str,
    level: int,
    item_ids: Optional[List[str]] = None,
    mode: str = "SR",
    item_count_done: Optional[int] = None,
    include_minor: bool = False,
    annotate_dps: bool = True,
) -> SpikeMarkersResult:
    """Classify a champion's discrete power spikes vs the live level + items.

    ``champion``        canonical DDragon id ("Aatrox", "Jinx").
    ``level``           operator's live champion level (clamped 1..18).
    ``item_ids``        operator's owned item ids (used only for the
                        optional ``dps_at`` annotation; threaded to the
                        DS curve so the DPS reflects the live build).
    ``mode``            SR / ARAM / ARENA / BRAWL - threaded to the DS
                        curve; does NOT move the spike thresholds.
    ``item_count_done`` count of FINISHED legendary items. When None,
                        defaults to ``min(len(item_ids), 3)`` as a coarse
                        owned-slots proxy (caller should pass the real
                        finished-legendary count when it has one).
    ``include_minor``   add the 9/13/18 minor level breakpoints.
    ``annotate_dps``    annotate level markers with weighted_dps from the
                        DS curve (one snapshot load + level sweep).

    Returns a :class:`SpikeMarkersResult`. Fail-soft: a blank champion
    yields an empty result (no markers, no next). Every marker is a real
    threshold; ``next`` is the single nearest not-yet-crossed spike.
    """
    champ = str(champion or "").strip()
    lv = _clamp_level(level)
    items = [str(x) for x in (item_ids or []) if str(x).strip()]

    n_item_thresh = len(_ITEM_SPIKES)
    if item_count_done is None:
        items_done = min(len(items), n_item_thresh)
    else:
        try:
            items_done = max(0, int(item_count_done))
        except (TypeError, ValueError):
            items_done = 0

    if not _is_known_champion(champ):
        return SpikeMarkersResult(
            champion=champ, level=lv, item_count_done=items_done,
            markers=tuple(), next_marker=None,
        )

    level_thresholds = _level_thresholds(include_minor)

    dps_map: Dict[int, float] = {}
    if annotate_dps:
        dps_map = _dps_by_level(champ, level_thresholds, items, mode)

    markers: List[SpikeMarker] = []

    # Level markers (ascending). crossed = at-or-past; next decided below.
    for t in level_thresholds:
        markers.append(SpikeMarker(
            kind="level",
            threshold=t,
            label=_LEVEL_LABELS.get(t, f"level {t}"),
            crossed=(lv >= t),
            next=False,
            dps_at=dps_map.get(t),
        ))

    # Item-completion markers (ascending).
    for t in _ITEM_SPIKES:
        markers.append(SpikeMarker(
            kind="item",
            threshold=t,
            label=("first item" if t == 1
                   else "two items" if t == 2
                   else f"{t} items"),
            crossed=(items_done >= t),
            next=False,
            dps_at=None,
        ))

    # Pick the single nearest not-yet-crossed marker across BOTH families.
    # "Distance" = thresholds remaining: for a level marker it's
    # (threshold - level); for an item marker it's (threshold -
    # item_count_done). Smaller gap = sooner = next. Ties break level
    # before item (the ult/scaling breakpoint is the headline spike), then
    # ascending threshold for determinism.
    def _gap(m: SpikeMarker) -> int:
        if m.kind == "level":
            return m.threshold - lv
        return m.threshold - items_done

    uncrossed = [m for m in markers if not m.crossed]
    next_marker: Optional[SpikeMarker] = None
    if uncrossed:
        kind_rank = {"level": 0, "item": 1}
        best = min(
            uncrossed,
            key=lambda m: (_gap(m), kind_rank.get(m.kind, 9), m.threshold),
        )
        # Rebuild that one marker with next=True (frozen dataclass).
        rebuilt: List[SpikeMarker] = []
        for m in markers:
            if m is best:
                nm = SpikeMarker(
                    kind=m.kind, threshold=m.threshold, label=m.label,
                    crossed=m.crossed, next=True, dps_at=m.dps_at,
                )
                rebuilt.append(nm)
                next_marker = nm
            else:
                rebuilt.append(m)
        markers = rebuilt

    return SpikeMarkersResult(
        champion=champ,
        level=lv,
        item_count_done=items_done,
        markers=tuple(markers),
        next_marker=next_marker,
    )


__all__ = [
    "SpikeMarker",
    "SpikeMarkersResult",
    "compute_spike_markers",
]
