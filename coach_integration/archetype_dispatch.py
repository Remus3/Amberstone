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
when the scorer POST fails (engine unreachable, an HTTP error status, or a
body that is not a JSON object); this helper propagates that as a return
value of ``None`` so callers can fall back to ``picks_str="unavailable"``
without writing partial calibration entries.

Empty champion string returns ``None`` too - no point dispatching for an
unknown champion. The dispatcher would default to ``"carry"`` archetype +
fail at the engine's champion lookup anyway.

Input boundary (true-audit s144 cycle 168): every coach feeds this helper
values read from the Live Client and from the DS HTTP body, so it sanitizes
both sides instead of trusting them. A non-finite or junk enemy stat reads as
the 0.0 "unknown" default; a one-damage-type comp keeps its 0.0 share (the
old ``x or 0.5`` read turned an all-AD comp into a 1.0 / 0.5 pair the client
scaled to 0.667 / 0.333); a junk caster HP is "no signal"; a junk
cost_ceiling / timeout is dropped rather than sinking the dispatch; items
and augments are materialized ONCE so the ordered-build planner sees the same
list the flat ranking did; and a non-dict engine body, a non-list ``ranked``
or a non-dict row never raises past the ``None`` contract.
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


def _finite(value: object) -> Optional[float]:
    """``value`` as a finite float, else None (bools, NaN, inf and junk)."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _stat(stats: object, name: str) -> float:
    """One EnemyStats target field, 0.0 ("unknown") when absent or junk.

    The old ``float(x or 0.0)`` read let a NaN through (NaN is truthy) to the
    engine body and let a non-numeric value sink the whole dispatch.
    """
    val = _finite(getattr(stats, name, None))
    return 0.0 if val is None else val


def _shares(stats: object) -> tuple[float, float]:
    """Enemy (ad_share, ap_share), keeping a real 0.0 side.

    The old ``float(x or 0.5)`` read turned the 0.0 side of a one-damage-type
    comp into 0.5, so an all-AD comp shipped (1.0, 0.5) and the client scaled
    it to (0.667, 0.333). A side that is missing, junk or outside [0, 1] is
    unknown: with one good side the pair is that side plus its complement
    (the client's own one-side rule); with none, or a pair summing to 0, it
    carries no split and reads as the neutral 0.5 / 0.5.
    """
    def _side(name: str) -> Optional[float]:
        val = _finite(getattr(stats, name, None))
        return val if val is not None and 0.0 <= val <= 1.0 else None

    ad, ap = _side("ad_share"), _side("ap_share")
    if ad is not None and ap is not None:
        return (ad, ap) if ad + ap > 0.0 else (0.5, 0.5)
    if ad is not None:
        return ad, 1.0 - ad
    if ap is not None:
        return 1.0 - ap, ap
    return 0.5, 0.5


def _as_list(values: object) -> list:
    """Materialize ``values`` once: None -> [], a bare str -> [str].

    A generator used to be consumed by the flat ranking, so the ordered-build
    planner saw no owned items; a bare str was iterated letter by letter.
    """
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        return [values]
    return list(values)  # type: ignore[call-overload]


def _caster_missing_hp(caster_hp: object, caster_hp_max: object) -> float:
    """R5 self-HP as a missing fraction in [0, 1]; 0.0 = no signal.

    Absent, junk, negative or non-finite HP is no signal: a NaN HP used to
    slip both clamps and read as 1.0 (near dead), an inf max HP read as 1.0,
    and an absent current HP with a known max read as 0 HP.
    """
    hp = _finite(caster_hp)
    hp_max = _finite(caster_hp_max)
    if hp is None or hp_max is None or hp_max <= 0 or hp < 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - hp / hp_max))


def _row_gold(row: dict) -> int:
    """A row's gold as an int, 0 when absent or junk (NaN / inf / text)."""
    val = _finite(row.get("gold", 0) or 0)
    return 0 if val is None else int(val)


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
    except (TypeError, ValueError, OverflowError):
        # OverflowError: an over-long int delta (float(10**400)) used to
        # raise past every caller instead of degrading this one row.
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
        raw_name = r.get("item_name")
        # One line per prompt splice: an engine-supplied name never carries
        # a newline (or any run of whitespace) into the LLM user prompt, and
        # a non-str / blank name reads as the "?" placeholder.
        name = " ".join(raw_name.split()) if isinstance(raw_name, str) else ""
        # Signed once: the old "+{delta}" template rendered a negative row as
        # "+-5dps"; a delta that rounds to zero reads "+0", never "-0".
        delta = int(round(_row_delta(r, scorer)))
        pieces.append(f"{name or '?'}({delta:+d}{unit},{_row_gold(r)}g)")
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
        # Same JSON-boundary guard as _row_delta (audit cycle 10): a NaN /
        # inf / junk gold degrades this one row to 0, never the block.
        gold = _row_gold(r)
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
    # TRI-STATE seam (Optional[bool], NOT a plain bool - the asymmetry with
    # every seam above is deliberate). Those all default FALSE in the engine,
    # so `if flag: seams[k] = True` covers their whole range. This one defaults
    # TRUE (the ``apply_squishy_burst_target`` default of
    # ``rank_for_primary_archetype`` in core/daemon_slayer_client.py - the L4
    # burst-carry target swap), so the same idiom could only ever say "on" and
    # the OFF half was unreachable through this dispatcher;
    # ``compute_variant_cell`` in core/build_order_variants.py had
    # to hand-build its rank_kwargs to get it. None = inherit the engine
    # default (kwarg omitted, byte-identical to every pre-existing caller),
    # True = force on, False = force off. Appended at the END per repo
    # convention. Resolved here, NOT in the client - the client signature and
    # its True default are untouched.
    apply_squishy_burst_target: Optional[bool] = None,
    # RM-875 (DEFAULT-OFF): the RM-172 ARENA / Swiftplay growth-ADDEND lane.
    # Rides the shared ``seams`` dict, so the flat ranking AND the ordered-build
    # planner both get it. rank_for_primary_archetype forwards it to every
    # archetype branch; False never reaches it (no body key, byte-identical).
    # The only live caller that can set it is coaches/arena_coach.py behind
    # RC_ARENA_MODE_MODIFIERS; the default-ON flip is gated row G5-05.
    apply_mode_modifiers: bool = False,
) -> Optional[CoachDispatchResult]:
    """Resolve archetype for ``champion`` + call the right DS scorer.

    Returns ``None`` on:
      - empty/blank champion
      - engine unreachable (dispatcher returned ``None``) or a body that is
        not a dict
      - unexpected import/runtime errors (logged at debug)

    Caller writes ``picks_str="unavailable"`` and skips calibration logging
    in those cases. The empty-engine-response case ("engine up but
    returned empty list") yields a ``CoachDispatchResult`` with empty
    ``rows`` + ``display_rows`` + ``picks_str="none"`` - caller still
    has a populated ``archetype``/``scorer`` for diagnostics.
    """
    if not champion or not str(champion).strip():
        return None
    # The stripped name is the one the archetype lookup and the engine see:
    # a padded " Ezreal " used to miss the per-champion pick and the engine's
    # champion lookup alike.
    champ = str(champion).strip()

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

        pick = get_archetype_for(champ)
        # A non-dict pick or a non-str primary is a junk store row, not a
        # reason to drop the whole recommendation: it reads as carry.
        primary = pick.get("primary") if isinstance(pick, dict) else None
        archetype = (primary.strip().lower()
                     if isinstance(primary, str) else "") or "carry"

        # Materialized ONCE: the flat ranking and the ordered-build planner
        # below read the same lists (a generator used to reach the planner
        # already consumed).
        owned = _as_list(item_ids)
        aug_list = _as_list(augments) or None
        ad_share, ap_share = _shares(enemy_stats)
        # A junk / non-positive timeout is dropped (the client default
        # applies) rather than shipped to the client as NaN.
        _timeout = _finite(timeout)
        timeout_s = _timeout if _timeout is not None and _timeout > 0 else None

        kwargs: dict = {
            "champion":              champ,
            "archetype":             archetype,
            "level":                 int(level),
            "item_ids":              owned,
            "mode":                  str(mode_engine),
            "target_armor":          _stat(enemy_stats, "armor"),
            "target_mr":             _stat(enemy_stats, "mr"),
            "target_max_hp":         _stat(enemy_stats, "max_hp"),
            "target_bonus_hp":       _stat(enemy_stats, "bonus_hp"),
            # EHP-side: enemy damage-type split so the bruiser/tank scorer
            # values armor vs MR by the actual comp (carry/mage/assassin/
            # enchanter branches ignore these). Default 0.5/0.5 when the
            # EnemyStats predates the field or carries junk; a real 0.0 side
            # (a one-damage-type comp) survives.
            "enemy_ad_share":        ad_share,
            "enemy_ap_share":        ap_share,
            "top":                   int(top),
            "augments":              aug_list,
        }
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s

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
            # A junk ceiling (NaN, inf, text, a bool, a negative) is dropped
            # with a debug line: it used to raise inside this try and sink
            # the whole dispatch to None ("unavailable").
            _ceiling = _finite(cost_ceiling)
            if _ceiling is not None and _ceiling >= 0:
                seams["cost_ceiling"] = int(_ceiling)
            else:
                logger.debug("dispatch_for_coach(%s): junk cost_ceiling %r dropped",
                             champ, cost_ceiling)
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
        # Tri-state: an explicit False MUST survive (it is the whole point of
        # the seam), so this is an `is not None` test, not a truthiness test.
        # None leaves the kwarg absent -> the engine's own True default.
        if apply_squishy_burst_target is not None:
            seams["apply_squishy_burst_target"] = bool(apply_squishy_burst_target)
        if apply_mode_modifiers:
            seams["apply_mode_modifiers"] = True

        # R5 self-HP -> caster_missing_hp_pct. Shared guard: absent / junk /
        # non-finite HP or hp_max <= 0 yields 0.0 ("no signal", OFF) and is
        # NOT forwarded.
        _missing = _caster_missing_hp(caster_hp, caster_hp_max)
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
        # pick (its ``_select_boots`` call in core/build_order.py) and
        # splats them into every
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

    # Engine-response boundary: a non-dict body is "engine unavailable"; a
    # non-list ``ranked`` (a dict would list its keys, a str its letters) is
    # an empty ranking; a non-dict row is dropped and the good rows kept.
    # Each used to raise AttributeError past this helper's None contract.
    if not isinstance(out, dict):
        return None

    scorer = str(out.get("scorer") or "dps")
    ranked = out.get("ranked")
    rows = ([r for r in ranked if isinstance(r, dict)]
            if isinstance(ranked, (list, tuple)) else [])
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

            # Same sanitized values the flat ranking sent, so RANK and PLAN
            # can never disagree on an input.
            result.build_order = plan_build_order(
                champ,
                archetype,
                level=kwargs["level"],
                owned_item_ids=list(owned),
                mode=kwargs["mode"],
                target_armor=kwargs["target_armor"],
                target_mr=kwargs["target_mr"],
                target_max_hp=kwargs["target_max_hp"],
                target_bonus_hp=kwargs["target_bonus_hp"],
                slots=int(build_order_slots),
                augments=list(aug_list) if aug_list else None,
                timeout=timeout_s,
                # SLICE A defect 2: seams the flat ranking used, splatted
                # into every planner ranker call. Empty dict -> None so the
                # no-seam path is byte-identical to the pre-fix call.
                # plan_build_order re-pins filter_shared_uniques=True AFTER
                # this splat (the ``call_kwargs["filter_shared_uniques"]``
                # re-pin in core/build_order.py), so caller
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
