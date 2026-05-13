# arch: per-coach scorer dispatch + display formatting | section=coaching | frozen=no
"""Per-coach archetype dispatch helper (s182, 2026-05-13).

Cross-phase coach-integration follow-up from the archetype-expansion plan.
Each of the four mode coaches (SR via ``coach_integration/_coach.py``,
ARAM via ``coaches/aram_coach.py``, Arena via ``coaches/arena_coach.py``,
Brawl via ``coaches/brawl_coach.py``) previously called
``daemon_slayer_client.rank_for()`` directly — always the auto-attack
DPS scorer (``ds.dps``) regardless of the champion's archetype.

This module exposes a single ``dispatch_for_coach()`` helper that:

1. Resolves the operator's primary archetype for ``champion`` via
   ``core.archetype_picks.get_archetype_for`` (DDragon default + persisted
   per-champion override).
2. Calls ``rank_for_primary_archetype()`` which routes to the right scorer
   (``ds.dps`` for carry, ``ds.hybrid`` for bruiser, ``ds.ehp`` for tank,
   ``ds.ability`` for mage, ``ds.burst`` for assassin, ``ds.hps`` for
   enchanter — Phases 1-6 shipped s174-s181).
3. Returns a ``CoachDispatchResult`` containing:
   - ``picks_str``: scorer-aware formatted string for the LLM user prompt
     (unit suffix flips per scorer: "dps" / "ehp" / "%" / "adps" / etc.).
   - ``display_rows``: list of dicts compatible with the existing
     ``daemon_slayer_picks`` payload shape (``{id, name, delta_dps, gold}``
     keys preserved for dashboard JS backward-compat) plus new ``delta`` +
     ``scorer`` fields for future disambiguation.
   - ``rows``: the raw dispatcher rows (dicts from ``out["ranked"]``).
   - ``archetype`` + ``scorer``: the resolved pick + the engine branch used.
   - ``out``: the full dispatcher dict (for callers that want shape parity).

Engine-down semantics: ``rank_for_primary_archetype()`` returns ``None``
when the engine is unreachable; this helper propagates that as a return
value of ``None`` so callers can fall back to ``picks_str="unavailable"``
without writing partial calibration entries.

Empty champion string returns ``None`` too — no point dispatching for an
unknown champion. The dispatcher would default to ``"carry"`` archetype +
fail at the engine's champion lookup anyway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger("rc.coach_integration.archetype_dispatch")


# Scorer → display unit suffix. Used in the picks_str format like
# "Stormrazor(+54dps,3500g) > Kraken Slayer(+48dps,3300g)" — operator
# reads the unit + sees the scorer label in the prefix.
_UNIT_SUFFIX: dict[str, str] = {
    "dps":     "dps",
    "ehp":     "ehp",
    "hybrid":  "%",
    "ability": "adps",
    "burst":   "burst",
    "hps":     "hps",
}

# Scorer → display label for the LLM prompt prefix:
# "DS top items (DPS ranked, own-items-accounted): ..."
#                ^^^ this slot
_DISPLAY_LABEL: dict[str, str] = {
    "dps":     "DPS",
    "ehp":     "EHP",
    "hybrid":  "hybrid",
    "ability": "ability-DPS",
    "burst":   "burst",
    "hps":     "HPS",
}


@dataclass
class CoachDispatchResult:
    """Result envelope for a single ``dispatch_for_coach`` call.

    The four mode coaches all need three things from a successful DS call:
    a string to splice into the LLM user prompt, a payload to write into
    ``daemon_slayer_picks`` of the output coaching JSON, and the raw rows
    for any custom downstream consumer (e.g. SR's
    ``performance_tracker.save_rating`` snapshot). All three are computed
    once here.
    """

    out: dict
    archetype: str
    scorer: str
    rows: list[dict] = field(default_factory=list)
    picks_str: str = "none"
    display_rows: list[dict] = field(default_factory=list)


def _row_delta(row: dict, scorer: str) -> float:
    """Extract the scorer's primary delta from a dispatcher row.

    Most scorers expose a unified ``delta`` field. Bruiser's hybrid
    scorer ships three (``delta_dps`` / ``delta_ehp`` / ``hybrid_delta_pct``)
    and uses the percentage as its display unit — we read that and scale
    to a single-digit-friendly number.
    """
    if scorer == "hybrid":
        return float(row.get("hybrid_delta_pct", 0.0)) * 100.0
    return float(row.get("delta", row.get("delta_dps", 0.0)))


def _build_picks_str(rows: list[dict], scorer: str) -> str:
    """Format ``rows`` for the LLM user prompt.

    Example outputs::

        "Stormrazor(+54dps,3500g) > Kraken Slayer(+48dps,3300g)"        (dps)
        "Randuin's(+520ehp,2700g) > Force of Nature(+440ehp,2900g)"     (ehp)
        "Trinity Force(+8%,3333g) > Sundered Sky(+6%,3100g)"            (hybrid)
        "Rabadon's(+13adps,3500g) > Shadowflame(+13adps,3200g)"         (ability)
        "Infinity Edge(+250burst,3500g) > Bloodthirster(+213burst,3400g)" (burst)
        "Helia(+25hps,2200g) > Ardent(+15hps,2200g)"                    (hps)
    """
    if not rows:
        return "none"
    unit = _UNIT_SUFFIX.get(scorer, "delta")
    pieces: list[str] = []
    for r in rows:
        name = r.get("item_name", "?")
        delta = _row_delta(r, scorer)
        gold = r.get("gold", 0)
        pieces.append(f"{name}(+{delta:.0f}{unit},{gold}g)")
    return " > ".join(pieces)


def _build_display_rows(rows: list[dict], scorer: str) -> list[dict]:
    """Convert dispatcher rows into the ``daemon_slayer_picks`` payload shape.

    Schema (4 legacy fields + 2 new):
        {
            "id":         <str>,    # item id (legacy)
            "name":       <str>,    # item name (legacy)
            "delta_dps":  <float>,  # scorer's primary delta (legacy field
                                    # name; carries scorer-specific units
                                    # for non-DPS scorers — dashboard JS
                                    # will gain a scorer-aware renderer in
                                    # a follow-up session)
            "gold":       <int>,    # gold cost (legacy)
            "delta":      <float>,  # NEW — same value as delta_dps, named
                                    # consistently across scorers
            "scorer":     <str>,    # NEW — "dps"|"ehp"|"hybrid"|"ability"|
                                    # "burst"|"hps" so consumers can render
                                    # the correct unit / color the pill
        }

    The two new fields are additive; readers of the legacy shape see no
    change for the carry/dps case (most common).
    """
    out: list[dict] = []
    for r in rows:
        delta = _row_delta(r, scorer)
        out.append({
            "id":        r.get("item_id", ""),
            "name":      r.get("item_name", ""),
            "delta_dps": round(delta, 2),
            "gold":      int(r.get("gold", 0) or 0),
            "delta":     round(delta, 2),
            "scorer":    scorer,
        })
    return out


def dispatch_for_coach(
    champion: str,
    *,
    mode_engine: str,
    level: int,
    item_ids: Iterable[str],
    enemy_stats,  # coach_integration.enemy_stats.EnemyStats (frozen dataclass)
    augments: Optional[Iterable[str]] = None,
    top: int = 5,
    timeout: Optional[float] = None,
) -> Optional[CoachDispatchResult]:
    """Resolve archetype for ``champion`` + call the right DS scorer.

    Returns ``None`` on:
      - empty/blank champion
      - engine unreachable (dispatcher returned ``None``)
      - unexpected import/runtime errors (logged at debug)

    Caller writes ``picks_str="unavailable"`` and skips calibration logging
    in those cases. The empty-engine-response case ("engine up but
    returned empty list") yields a ``CoachDispatchResult`` with empty
    ``rows`` + ``display_rows`` + ``picks_str="none"`` — caller still
    has a populated ``archetype``/``scorer`` for diagnostics.
    """
    if not champion or not str(champion).strip():
        return None

    try:
        # Local imports keep the helper lightweight at module-load time +
        # mirror the pattern the coaches use to defer DS imports until
        # the first tick of a live match.
        from core.archetype_picks import get_archetype_for
        from core import daemon_slayer_client as _ds

        pick = get_archetype_for(str(champion))
        archetype = (pick.get("primary") or "carry").strip().lower() or "carry"

        kwargs: dict = {
            "champion":              str(champion),
            "archetype":             archetype,
            "level":                 int(level),
            "item_ids":              list(item_ids),
            "mode":                  str(mode_engine),
            "target_armor":          float(getattr(enemy_stats, "armor", 0.0) or 0.0),
            "target_mr":             float(getattr(enemy_stats, "mr", 0.0) or 0.0),
            "target_max_hp":         float(getattr(enemy_stats, "max_hp", 0.0) or 0.0),
            "target_bonus_hp":       float(getattr(enemy_stats, "bonus_hp", 0.0) or 0.0),
            "top":                   int(top),
            "augments":              list(augments) if augments else None,
        }
        if timeout is not None:
            kwargs["timeout"] = float(timeout)

        out = _ds.rank_for_primary_archetype(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_for_coach(%s, %s) failed: %s", champion, mode_engine, exc)
        return None

    if out is None:
        return None

    scorer = str(out.get("scorer") or "dps")
    rows = list(out.get("ranked") or [])
    return CoachDispatchResult(
        out=out,
        archetype=archetype,
        scorer=scorer,
        rows=rows,
        picks_str=_build_picks_str(rows, scorer),
        display_rows=_build_display_rows(rows, scorer),
    )


def display_label(scorer: str) -> str:
    """Return the LLM-prompt-friendly label for a scorer name.

    Used by coaches to splice into the user-prompt prefix:
        "DS top items ({label} ranked, own-items-accounted): ..."

    Unknown scorers fall through to the scorer name itself.
    """
    return _DISPLAY_LABEL.get(scorer, scorer)
