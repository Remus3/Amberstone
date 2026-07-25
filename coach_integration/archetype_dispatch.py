# arch: per-coach scorer dispatch + display formatting | section=coaching | frozen=no
"""Per-coach archetype dispatch helper (s182, 2026-05-13).

Cross-phase coach-integration follow-up from the archetype-expansion plan.
Each of the four mode coaches (SR via ``coach_integration/_coach.py``,
ARAM via ``coaches/aram_coach.py``, Arena via ``coaches/arena_coach.py``,
Brawl via ``coaches/brawl_coach.py``) previously called
``daemon_slayer_client.rank_for()`` directly - always the auto-attack
DPS scorer (``ds.dps``) regardless of the champion's archetype.

This module exposes a single ``dispatch_for_coach()`` helper that:

1. Resolves the operator's primary archetype for ``champion`` via
   ``core.archetype_picks.get_archetype_for`` (DDragon default + persisted
   per-champion override).
2. Calls ``rank_for_primary_archetype()`` which routes to the right scorer
   (``ds.dps`` for carry, ``ds.hybrid`` for bruiser, ``ds.ehp`` for tank,
   ``ds.ability`` for mage, ``ds.burst`` for assassin, ``ds.hps`` for
   enchanter - Phases 1-6 shipped s174-s181).
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

Empty champion string returns ``None`` too - no point dispatching for an
unknown champion. The dispatcher would default to ``"carry"`` archetype +
fail at the engine's champion lookup anyway.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger("rc.coach_integration.archetype_dispatch")


# Scorer -> display unit suffix. Used in the picks_str format like
# "Stormrazor(+54dps,3500g) > Kraken Slayer(+48dps,3300g)" - operator
# reads the unit + sees the scorer label in the prefix.
_UNIT_SUFFIX: dict[str, str] = {
    "dps":     "dps",
    "ehp":     "ehp",
    "hybrid":  "%",
    "ability": "adps",
    "burst":   "burst",
    "hps":     "hps",
    "onhit":   "dps",
}

# Scorer -> display label for the LLM prompt prefix:
# "DS top items (DPS ranked, own-items-accounted): ..."
#                ^^^ this slot
_DISPLAY_LABEL: dict[str, str] = {
    "dps":     "DPS",
    "ehp":     "EHP",
    "hybrid":  "hybrid",
    "ability": "ability-DPS",
    "burst":   "burst",
    "hps":     "HPS",
    "onhit":   "on-hit DPS",
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
    # Opt-in (default None). Populated only when dispatch_for_coach is
    # called with with_build_order=True - a contextual, match-specific
    # ORDERED build with the cross-family unique-passive no-double rule
    # enforced (core.build_order.BuildOrderResult). Kept off the per-tick
    # path by default: an ordered plan is N sequential engine calls vs
    # the single call display_rows needs.
    build_order: object = None


def _row_delta(row: dict, scorer: str) -> float:
    """Extract the scorer's primary delta from a dispatcher row.

    Most scorers expose a unified ``delta`` field. Bruiser's hybrid
    scorer ships three (``delta_dps`` / ``delta_ehp`` / ``hybrid_delta_pct``)
    and uses the percentage as its display unit - we read that and scale
    to a single-digit-friendly number.
    """
    # Audit cycle 10 (P2-W1-app-B): guard the engine-response JSON
    # boundary. A NaN/inf delta would flow through round() into
    # daemon_slayer_picks in coaching_data.json, where json.dumps emits
    # a bare NaN token that the dashboard's JSON.parse rejects (panel
    # dead). Garbage types (None / non-numeric) degrade one row to 0.0
    # instead of sinking the whole DS block for the tick.
    try:
        if scorer == "hybrid":
            val = float(row.get("hybrid_delta_pct", 0.0)) * 100.0
        else:
            val = float(row.get("delta", row.get("delta_dps", 0.0)))
    except (TypeError, ValueError):
        return 0.0
    return val if math.isfinite(val) else 0.0


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
                                    # for non-DPS scorers - dashboard JS
                                    # will gain a scorer-aware renderer in
                                    # a follow-up session)
            "gold":       <int>,    # gold cost (legacy)
            "delta":      <float>,  # NEW - same value as delta_dps, named
                                    # consistently across scorers
            "scorer":     <str>,    # NEW - "dps"|"ehp"|"hybrid"|"ability"|
                                    # "burst"|"hps" so consumers can render
                                    # the correct unit / color the pill
        }

    The two new fields are additive; readers of the legacy shape see no
    change for the carry/dps case (most common).
    """
    out: list[dict] = []
    for r in rows:
        delta = _row_delta(r, scorer)
        try:
            # Same JSON-boundary guard as _row_delta (audit cycle 10):
            # int(NaN) raises ValueError, int(inf) raises OverflowError.
            gold = int(r.get("gold", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            gold = 0
        out.append({
            "id":        r.get("item_id", ""),
            "name":      r.get("item_name", ""),
            "delta_dps": round(delta, 2),
            "gold":      gold,
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
    with_build_order: bool = False,
    build_order_slots: int = 6,
    # Seam flags (Tier-2, behavior-preserving). Forwarded to
    # rank_for_primary_archetype only when non-default, so a call that omits
    # them is byte-identical to pre-seam dispatch. R5 self-HP is derived
    # from caster_hp / caster_hp_max into caster_missing_hp_pct below.
    # C4 FLIP (2026-07-04): prefer_kit_axis_by_win (DSP11) now defaults ON - the
    # live build-chooser floats a champ's WIN-anchored kit-axis items by default
    # (a byte-identical no-op for the 165 non-tabled champs; operator-validated
    # live for Ezreal / Corki / Senna / Quinn, LEDGER 776). Pass False to opt
    # out. Every OTHER seam stays default-OFF.
    exempt_offclass_by_win: bool = False,
    prefer_kit_axis_by_win: bool = True,
    cost_ceiling: Optional[int] = None,
    prefer_survivability_by_win: bool = False,
    assume_magic_burst: bool = False,
    assume_passive_as_stacks: bool = False,
    apply_target_vuln: bool = False,
    assume_missing_hp_heal_amp: bool = False,
    caster_hp: Optional[float] = None,
    caster_hp_max: Optional[float] = None,
    # RM-04 A-01 (DEFAULT-OFF, CARRY-ONLY): class-wide un-strip of the four
    # ROADMAP-named off-class items for EVERY ranged marksman, not just the
    # four DSP2-tabled champions. Appended at the END per repo convention.
    widen_carry_pool: bool = False,
) -> Optional[CoachDispatchResult]:
    """Resolve archetype for ``champion`` + call the right DS scorer.

    Returns ``None`` on:
      - empty/blank champion
      - engine unreachable (dispatcher returned ``None``)
      - unexpected import/runtime errors (logged at debug)

    Caller writes ``picks_str="unavailable"`` and skips calibration logging
    in those cases. The empty-engine-response case ("engine up but
    returned empty list") yields a ``CoachDispatchResult`` with empty
    ``rows`` + ``display_rows`` + ``picks_str="none"`` - caller still
    has a populated ``archetype``/``scorer`` for diagnostics.
    """
    if not champion or not str(champion).strip():
        return None

    # Seam kwargs threaded into the ordered-build planner (see the
    # with_build_order branch below). Built alongside the flat ranking's
    # kwargs so RANK and PLAN can never disagree on a seam; declared here so
    # it survives the try/except scope.
    plan_rank_kwargs: dict = {}

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
            # EHP-side: enemy damage-type split so the bruiser/tank scorer
            # values armor vs MR by the actual comp (carry/mage/assassin/
            # enchanter branches ignore these). Default 0.5/0.5 when the
            # EnemyStats predates the field (getattr fallback).
            "enemy_ad_share":        float(getattr(enemy_stats, "ad_share", 0.5) or 0.5),
            "enemy_ap_share":        float(getattr(enemy_stats, "ap_share", 0.5) or 0.5),
            "top":                   int(top),
            "augments":              list(augments) if augments else None,
        }
        if timeout is not None:
            kwargs["timeout"] = float(timeout)

        # Seam flags: forward only non-default values so a flagless dispatch
        # stays byte-identical to pre-seam behavior (the rank_* helpers emit
        # a body key only when truthy/non-null, mirroring `if augments:`).
        # Collected into ONE dict so the flat ranking below and the ordered
        # build planner (with_build_order branch) receive the identical set.
        seams: dict = {}
        if exempt_offclass_by_win:
            seams["exempt_offclass_by_win"] = True
        if prefer_kit_axis_by_win:
            seams["prefer_kit_axis_by_win"] = True
        if cost_ceiling is not None:
            seams["cost_ceiling"] = int(cost_ceiling)
        if prefer_survivability_by_win:
            seams["prefer_survivability_by_win"] = True
        if assume_magic_burst:
            seams["assume_magic_burst"] = True
        if assume_passive_as_stacks:
            seams["assume_passive_as_stacks"] = True
        if apply_target_vuln:
            seams["apply_target_vuln"] = True
        if assume_missing_hp_heal_amp:
            seams["assume_missing_hp_heal_amp"] = True
        if widen_carry_pool:
            seams["widen_carry_pool"] = True

        # R5 self-HP -> caster_missing_hp_pct. Shared guard: absent HP or
        # hp_max <= 0 yields 0.0 ("no signal", OFF) and is NOT forwarded.
        try:
            _hp = float(caster_hp) if caster_hp is not None else 0.0
            _hp_max = float(caster_hp_max) if caster_hp_max is not None else 0.0
        except (TypeError, ValueError):
            _hp, _hp_max = 0.0, 0.0
        if _hp_max > 0:
            _missing = max(0.0, min(1.0, 1.0 - _hp / _hp_max))
            if _missing:
                seams["caster_missing_hp_pct"] = _missing

        kwargs.update(seams)

        # SLICE A defect 2: build the planner's rank_kwargs from the SAME
        # seam dict. Before this, the with_build_order branch forwarded ZERO
        # seams, so a dispatch RANKED with prefer_kit_axis_by_win ON (its
        # dispatch-level default since the C4 flip) and PLANNED the ordered
        # build with it OFF - the flat DS rows and the ordered build the
        # operator follows disagreed silently.
        #
        # The damage-type split rides along too: plan_build_order reads
        # enemy_ad_share / enemy_ap_share out of rank_kwargs for its boots
        # pick (core/build_order.py:574-575) and splats them into every
        # ranker call. A neutral 0.5 / 0.5 split IS that function's own
        # default, so it is omitted - a seam-free dispatch keeps the exact
        # pre-fix planner call shape.
        plan_rank_kwargs = dict(seams)
        for _share_key in ("enemy_ad_share", "enemy_ap_share"):
            _share_val = kwargs.get(_share_key)
            if _share_val is not None and float(_share_val) != 0.5:
                plan_rank_kwargs[_share_key] = float(_share_val)

        out = _ds.rank_for_primary_archetype(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_for_coach(%s, %s) failed: %s", champion, mode_engine, exc)
        return None

    if out is None:
        return None

    scorer = str(out.get("scorer") or "dps")
    rows = list(out.get("ranked") or [])
    result = CoachDispatchResult(
        out=out,
        archetype=archetype,
        scorer=scorer,
        rows=rows,
        picks_str=_build_picks_str(rows, scorer),
        display_rows=_build_display_rows(rows, scorer),
    )

    # Opt-in ordered build. Reuses the same champion/archetype/level +
    # enemy context as the flat ranking. plan_build_order issues one
    # engine call per remaining slot (the iteration is exactly what makes
    # the no-double rule hold across the sequence), so it stays off the
    # per-tick path - only champ-select planning / ds-preview / a periodic
    # refresh should pass with_build_order=True. A build-order failure
    # never sinks the (already successful) flat dispatch.
    if with_build_order:
        try:
            from core.build_order import plan_build_order

            result.build_order = plan_build_order(
                str(champion),
                archetype,
                level=int(level),
                owned_item_ids=list(item_ids),
                mode=str(mode_engine),
                target_armor=float(getattr(enemy_stats, "armor", 0.0) or 0.0),
                target_mr=float(getattr(enemy_stats, "mr", 0.0) or 0.0),
                target_max_hp=float(getattr(enemy_stats, "max_hp", 0.0) or 0.0),
                target_bonus_hp=float(getattr(enemy_stats, "bonus_hp", 0.0) or 0.0),
                slots=int(build_order_slots),
                augments=list(augments) if augments else None,
                timeout=timeout,
                # SLICE A defect 2: seams the flat ranking used, splatted
                # into every planner ranker call. Empty dict -> None so the
                # no-seam path is byte-identical to the pre-fix call.
                # plan_build_order re-pins filter_shared_uniques=True AFTER
                # this splat (core/build_order.py:618-619), so caller
                # rank_kwargs can never weaken the no-double-unique rule.
                rank_kwargs=plan_rank_kwargs or None,
                rank_fn=_ds.rank_for_primary_archetype,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("dispatch_for_coach build_order failed (%s): %s",
                         champion, exc)
            result.build_order = None

    return result


def display_label(scorer: str) -> str:
    """Return the LLM-prompt-friendly label for a scorer name.

    Used by coaches to splice into the user-prompt prefix:
        "DS top items ({label} ranked, own-items-accounted): ..."

    Unknown scorers fall through to the scorer name itself.
    """
    return _DISPLAY_LABEL.get(scorer, scorer)
