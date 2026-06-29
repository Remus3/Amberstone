# arch: HZ-C1 precomputed A/B choice-coach over the laning + build tables | section=core | frozen=no
"""HZ-C1 - deterministic A/B choice-coach over the precomputed Lane A laning
table (+ next build item). PRIMARY north star: drive live Haiku usage to ZERO.

PURPOSE
    The live coach pays a Claude Haiku call to answer "trade / all-in / back
    off". HZ-A1/A2 (``core.laning_scenario_precompute``) already PRECOMPUTE that
    verdict offline into versioned JSON keyed on
    ``(my_champ x enemy x level-band x mana-state x cd-state)`` with an
    ``economy`` recall/spike block per cell. This module is the request-time
    READER that turns ONE precomputed cell into two grounded A/B ``CoachChoice``
    objects - the deterministic coaching surface that REPLACES the Haiku
    paragraph once validated.

    v1 is SHADOW ONLY (charter 4b "do not flip blind"): the choices are recorded
    alongside live Haiku (``core.hz_choice_shadow``) for offline validation
    against real games; NO live coach is flipped off its Haiku call in this
    slice. Unlike the item-265 ``dashboard._deterministic_coaching`` path (which
    calls the DS matchup engine LIVE over :8893 per request), this reader is a
    PURE static table read - no network, no engine import on the hot path.

KEY MAPPING (live game state -> the table's discrete keys)
    * level -> band  : nearest of L2 / L6 / L11 / L16 (``band_for_level``).
    * mana%  -> mana_state : >= ``_FULL_MANA_FRACTION`` -> "full" else "low".
    * ult-up -> cd_state   : ult ready -> "all_up" else "no_ult".

FAIL-SOFT
    A missing table, an uncovered ``(champ, enemy)`` pair, or any malformed cell
    yields ``[]`` - the caller degrades to "no precomputed choice" (it keeps its
    existing path). Never raises.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.archetype_picks import canonical_champion_id
from core.coach_choices import CoachChoice
from core.laning_scenario_precompute import (
    GEN_BANDS,
    LEVEL_BANDS,
    load_laning_scenarios,
    lookup,
)

# Above this fraction of the mana pool you can fire the full rotation (the
# table's "full" cell); below it you are on the affordable-prefix "low" cell.
# The table BUILDS the low cell at LOW_MANA_FRACTION (0.35) of the pool; the
# request-time split at half-pool is the honest live read of "can I full-combo".
_FULL_MANA_FRACTION: float = 0.5

# Source tag stamped on every emitted choice so the surface is distinguishable
# from haiku / synth / the item-265 ds-matchup choices in logs + the UI.
SOURCE_TAG: str = "ds-precompute"

# Verdict -> (recommended action label, prudent-alternative label). The verdict
# IS the recommendation (A); B is the safer alternative. Economy may override B
# with a recall directive (see _build_choices).
#
# RC2 WS1 step 1 (2026-06-20, ops/audit/HZ_HAIKU_CALL_INVENTORY.md:49-108):
# added the "hold" band + relabeled the dominant "even" A-chip so it buckets as
# "hold" in tools/hz_shadow_report.classify_verdict (the +57-tick agreement win,
# 39% -> ~53%). That classifier matches A-label TEXT by ordered phrase (first
# hit wins; "poke"/"trade"/"even" all bucket BEFORE "hold"), so the hold/even
# A-labels here deliberately avoid those substrings and read as "hold and farm"
# -> coarse "hold". B keeps the cd-window trade alternative. Shadow-only: this
# changes the precompute vocabulary + shadow log, NOT any live served chip
# (do-not-flip-blind; the flip is gated on the re-measured agreement delta).
_VERDICT_LABELS: dict[str, Tuple[str, str]] = {
    "all_in": ("All-in {enemy}", "Hold - poke only"),
    "trade": ("Trade {enemy}", "Hold - poke only"),
    "back_off": ("Back off {enemy}", "Force a short trade"),
    "hold": ("Hold and farm this window", "Force a short trade on your cd"),
    "even": ("Hold and farm; reassess", "Trade on your cd window"),
}

# laning_band thresholds (spec 1.3). swing is net_swing in [-1, 1], my-champ
# favored positive. The hold band is the mild-negative zone that used to
# collapse into back_off (the back_off-bias the audit measured). Tunable.
_HOLD_LOW: float = 0.05   # |swing| above the even dead-zone, below a hard back
_BACK_OFF: float = 0.18   # swing at/under -_BACK_OFF is a firm back_off
_TRADE: float = 0.10      # swing at/over +_TRADE is a favored trade

_RECALL_LABELS: dict[str, str] = {
    "recall_now": "Recall now",
    "back_soon": "Back soon",
}

# v4 (Lane A) additive chips. The cooldown-window block surfaces a punish-window
# chip ("their key CC is down - your combo is up"); the spike-timing block
# surfaces a play-for-spike chip. Both are OPTIONAL + additive (absent block ->
# no chip; the verdict-as-"even" filler never emits) so the v3 A/B trade chips
# are unchanged. Keyed on the block's pure derived verdict (window_verdict /
# spike_verdict in core.laning_scenario_precompute).
_WINDOW_LABELS: dict[str, str] = {
    "punish_now": "Punish - their {spell} is down",
    "wait_cd": "Wait for your ult cooldown",
}
_SPIKE_LABELS: dict[str, str] = {
    "play_for_spike": "Play for your {label} spike",
    "spike_up": "Spike up - press your advantage",
}

# RC2 5.3 - mana/cd discrete state -> a human clause for the trigger sub-line.
_MANA_WORD: dict[str, str] = {"full": "full mana", "low": "low mana"}
_CD_WORD: dict[str, str] = {"all_up": "ult up", "no_ult": "ult down"}

# RC2 5.4 - condition-change branching. The aggression ladder ranks the 5 bands
# so a payload probe can tell whether an adjacent (ult-up / full-mana) cell is
# MORE aggressive than the current verdict (i.e. whether waiting on that axis
# actually unlocks a trade). Verdicts the operator should keep playing
# aggressively (the rec already IS the all-in/trade) vs the cautious set.
_AGGRESSIVE_VERDICTS: frozenset = frozenset({"all_in", "trade"})
_AGGRESSION_RANK: dict[str, int] = {
    "back_off": 0, "hold": 1, "even": 2, "trade": 3, "all_in": 4,
}
# Human clause for the axis whose change unlocks aggression (the rebranch_when).
_REBRANCH_AXIS_WORD: dict[str, str] = {
    "ult": "when your ult comes up",
    "mana": "after you back to full mana",
}


def _more_aggressive(a: object, b: object) -> bool:
    """True when verdict ``a`` outranks verdict ``b`` on the aggression ladder."""
    return _AGGRESSION_RANK.get(str(a), -1) > _AGGRESSION_RANK.get(str(b), -1)


def laning_rebranch(
    verdict: object,
    *,
    enemy: object,
    upgrade_axis: Optional[str] = None,
    upgrade_unlocks: bool = False,
    b_is_recall: bool = False,
) -> Tuple[str, str]:
    """The pre-stated condition-change branch for the recommendation chip A.

    RC2 5.4 (WS2 2.3): returns ``(rebranch_when, rebranch_to)`` for the primary
    A chip - "if this observable changes, switch to chip <to>". PURE truth table
    (the impure adjacent-cell probe is done by the resolver and passed in as
    ``upgrade_axis`` / ``upgrade_unlocks``); fail-soft empties, never raises.

    * AGGRESSIVE rec (all_in / trade): re-branch to the safe B option when the
      enemy laner roams or goes missing - the dominant real CV downgrade (spec
      2.3 bullet 1; the WS1 override layer flips the served chip, this names it).
    * CAUTIOUS rec (back_off / hold / even): re-branch to the aggressive B option
      WHEN an adjacent axis unlocks a more aggressive verdict (ult comes up /
      full mana). Skipped when B is an economy recall directive (no aggressive
      alt to point at) or no axis unlocks (the cautious rec is stable)."""
    name = str(enemy or "").strip() or "enemy"
    v = str(verdict or "").strip().lower()
    if v in _AGGRESSIVE_VERDICTS:
        return (f"if {name} roams or goes missing", "B")
    if b_is_recall or not upgrade_unlocks:
        return ("", "")
    when = _REBRANCH_AXIS_WORD.get(str(upgrade_axis or ""))
    if not when:
        return ("", "")
    return (when, "B")


def laning_trigger(
    enemy: object,
    level: object,
    *,
    mana_state: Optional[str] = None,
    cd_state: Optional[str] = None,
) -> str:
    """The live CONDITION an A/B laning option assumes (RC2 5.3 specificity).

    Stamped onto each chip's ``trigger`` field so the operator sees WHEN the
    recommendation holds, not just the verb. Built from the same discrete keys
    the cell was resolved by - enemy laner + level, plus the mana/cd state when
    the caller knows them. Pure + fail-soft: any malformed input degrades to a
    shorter clause, never raises (the coach hot path contract).

    Rich (shadow precompute, all keys): "Caitlyn, full mana, ult up, lvl 6".
    Lean (served matchup, level only):  "Caitlyn, lvl 6"."""
    name = str(enemy or "").strip() or "enemy"
    clauses: list[str] = []
    mana = _MANA_WORD.get(str(mana_state or "").strip().lower())
    if mana:
        clauses.append(mana)
    cd = _CD_WORD.get(str(cd_state or "").strip().lower())
    if cd:
        clauses.append(cd)
    try:
        clauses.append(f"lvl {int(level)}")
    except (TypeError, ValueError):
        pass
    return name + ", " + ", ".join(clauses) if clauses else name


def band_for_level(level: object) -> str:
    """Nearest level-band label for a live level (fail-soft to ``L2``).

    Bands partition the level axis at phase boundaries: 1-3 -> L2 (early
    skirmish), 4-8 -> L6 (first ult spike), 9-13 -> L11 (2-item mid),
    14-18 -> L16 (late lane / roam)."""
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        return "L2"
    if lvl < 4:
        return "L2"
    if lvl < 9:
        return "L6"
    if lvl < 14:
        return "L11"
    return "L16"


def mana_state_for(mana_fraction: Optional[float]) -> str:
    """``full`` when at/above half pool (or unknown), else ``low``.

    Unknown mana (None / non-numeric) defaults to ``full`` - the full-rotation
    cell is the honest baseline read when we cannot see the pool."""
    if mana_fraction is None:
        return "full"
    try:
        frac = float(mana_fraction)
    except (TypeError, ValueError):
        return "full"
    return "full" if frac >= _FULL_MANA_FRACTION else "low"


def cd_state_for(ult_up: Optional[bool]) -> str:
    """``all_up`` when the ult is ready (or unknown), else ``no_ult``."""
    if ult_up is None:
        return "all_up"
    return "all_up" if bool(ult_up) else "no_ult"


def item_state_for(item_count: Optional[int]) -> str:
    """``none`` / ``one_item`` / ``two_item`` from a completed-legendary COUNT.

    Parallel to mana_state_for / cd_state_for: maps the live owned-item count to
    the v4 table's discrete item-state key. 0 (or unknown / non-numeric) ->
    ``none``; 1 -> ``one_item``; >=2 -> ``two_item`` (the table caps the axis at
    two completed legendaries). Fail-soft to ``none`` (the itemless baseline) -
    the table always has a ``none`` cell, and lookup descends to it anyway."""
    if item_count is None:
        return "none"
    try:
        n = int(item_count)
    except (TypeError, ValueError):
        return "none"
    if n <= 0:
        return "none"
    if n == 1:
        return "one_item"
    return "two_item"


def _confidence_for(net_swing: object) -> str:
    """Confidence band from the absolute net swing magnitude.

    The verdict is deterministic; the confidence reflects how lopsided the
    trade math is. |swing| >= 0.20 -> high, >= 0.08 -> mid, else low."""
    try:
        mag = abs(float(net_swing))
    except (TypeError, ValueError):
        return "mid"
    if mag >= 0.20:
        return "high"
    if mag >= 0.08:
        return "mid"
    return "low"


def laning_band(cell: dict) -> str:
    """Recompute the 5-band laning verdict from a cell's trade scalars.

    RC2 WS1 step 1 (spec 1.3): a pure reinterpretation of the EXISTING cell
    scalars (``net_swing`` / ``pct_my_removed`` / ``pct_enemy_removed``) into
    one of ``all_in`` / ``trade`` / ``even`` / ``hold`` / ``back_off`` - NO
    engine call, NO table re-sweep. It adds the ``hold`` band (the mild-negative
    swing zone that the engine's binary _classify collapsed into ``back_off``,
    the back_off-bias measured in HZ_HAIKU_CALL_INVENTORY.md:92-95).

    Precedence (first match wins, mirrors agents.daemon_slayer.matchup._classify
    for the shared bands): enemy fully removed and I survive -> all_in; I am the
    one who dies -> back_off; mild-negative swing -> hold (NEW); firm-negative ->
    back_off; firm-positive -> trade; dead-zone -> even. Fail-soft to ``even``
    on any malformed scalar (the coach hot path must never raise)."""
    try:
        swing = float(cell.get("net_swing"))
    except (TypeError, ValueError, AttributeError):
        return "even"
    try:
        my_removed = float(cell.get("pct_my_removed"))
    except (TypeError, ValueError, AttributeError):
        my_removed = 0.0
    try:
        enemy_removed = float(cell.get("pct_enemy_removed"))
    except (TypeError, ValueError, AttributeError):
        enemy_removed = 0.0

    if enemy_removed >= 1.0 and my_removed < 1.0:
        return "all_in"
    if my_removed >= 1.0:
        return "back_off"
    if -_BACK_OFF < swing <= -_HOLD_LOW:
        return "hold"
    if swing <= -_BACK_OFF:
        return "back_off"
    if swing >= _TRADE:
        return "trade"
    return "even"


def _pct(value: object) -> str:
    """Format a 0..1 fraction as a whole-percent string (fail-soft ``0%``)."""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "0%"


def _combat_outcome(cell: dict, enemy: str) -> str:
    """DS-backed expected-outcome line for the combat choice."""
    swing = cell.get("net_swing")
    try:
        swing_s = f"{float(swing):+.2f}"
    except (TypeError, ValueError):
        swing_s = "+0.00"
    return (
        f"net swing {swing_s}; you remove "
        f"{_pct(cell.get('pct_enemy_removed'))} of {enemy}, "
        f"they remove {_pct(cell.get('pct_my_removed'))} of you"
    )


def _recall_outcome(economy: dict, next_item: Optional[Tuple[str, int]]) -> str:
    """DS-backed expected-outcome line for the economy/recall choice."""
    spike = str(economy.get("next_spike") or "spike")
    gold = economy.get("gold_at_band")
    try:
        gold_s = f"{int(round(float(gold)))}g"
    except (TypeError, ValueError):
        gold_s = "gold"
    if next_item and next_item[0]:
        return f"buy {next_item[0]} ({int(next_item[1])}g) toward {spike}"
    return f"{gold_s} banked; next spike {spike}"


def _window_chip(cell: dict, trigger: str) -> Optional[CoachChoice]:
    """Optional cooldown-window chip from the v4 ``cooldown_window`` block.

    Emits a chip only for an ACTIONABLE window_verdict (punish_now / wait_cd);
    the ``even`` filler (no enemy threat spell) emits nothing. A v3 cell has no
    cooldown_window block -> None. Pure + fail-soft (never raises)."""
    cw = cell.get("cooldown_window") if isinstance(cell.get("cooldown_window"), dict) else None
    if not cw:
        return None
    wv = str(cw.get("window_verdict") or "")
    tpl = _WINDOW_LABELS.get(wv)
    if not tpl:
        return None
    spell = str(cw.get("enemy_threat_spell") or "ability")
    try:
        cd_s = float(cw.get("enemy_cd_s"))
    except (TypeError, ValueError):
        cd_s = 0.0
    return CoachChoice(
        key="C",
        label=tpl.format(spell=spell),
        expected_outcome=(f"their {spell} cd ~{cd_s:.0f}s; your ult is your window"
                          if wv == "punish_now" else "hold until your ult is back"),
        confidence="mid",
        source_tag=SOURCE_TAG,
        trigger=trigger,
    )


def _spike_chip(cell: dict, trigger: str) -> Optional[CoachChoice]:
    """Optional spike-timing chip from the v4 ``spike_timing`` block.

    Emits a chip only for an ACTIONABLE spike_verdict (play_for_spike /
    spike_up); the ``even`` filler emits nothing. A v3 cell has no spike_timing
    block -> None. Pure + fail-soft (never raises)."""
    st = cell.get("spike_timing") if isinstance(cell.get("spike_timing"), dict) else None
    if not st:
        return None
    sv = str(st.get("spike_verdict") or "")
    tpl = _SPIKE_LABELS.get(sv)
    if not tpl:
        return None
    label = str(st.get("next_label") or "next")
    return CoachChoice(
        key="C",
        label=tpl.format(label=label),
        expected_outcome=f"next spike: {label}",
        confidence="low",
        source_tag=SOURCE_TAG,
        trigger=trigger,
    )


def _build_choices(
    cell: dict,
    enemy: str,
    *,
    next_item: Optional[Tuple[str, int]] = None,
    trigger: str = "",
    rebranch_when: str = "",
    rebranch_to: str = "",
) -> list[CoachChoice]:
    """Two grounded A/B choices from one resolved laning cell.

    A = the combat verdict (the recommendation), confidence from the swing
    magnitude. B = the economy alternative when the cell's recall verdict is
    ``recall_now`` / ``back_soon`` (grounded in the spike + next build item),
    else the prudent combat alternative from ``_VERDICT_LABELS``.

    RC2 WS1 step 1: the served verdict is the RECALIBRATED ``laning_band``
    (which adds the hold band + softens the back_off-bias), not the raw cell
    ``verdict`` from the binary engine _classify. The recalibrated label flows
    into the shadow log so tools/hz_shadow_report can re-measure agreement WITH
    the hold band applied, on the same live games, before any served flip."""
    verdict = laning_band(cell)
    a_label_tpl, b_label_alt = _VERDICT_LABELS.get(
        verdict, _VERDICT_LABELS["even"]
    )
    a = CoachChoice(
        key="A",
        label=a_label_tpl.format(enemy=enemy),
        expected_outcome=_combat_outcome(cell, enemy),
        confidence=_confidence_for(cell.get("net_swing")),
        source_tag=SOURCE_TAG,
        trigger=trigger,
        # RC2 5.4: the pre-stated branch lives on the primary recommendation
        # (A); B is the already-named alternative the branch points back to, so
        # it carries no branch of its own in v1.
        rebranch_when=rebranch_when,
        rebranch_to=rebranch_to,
    )

    economy = cell.get("economy") if isinstance(cell.get("economy"), dict) else {}
    recall = str(economy.get("recall") or "")
    if recall in _RECALL_LABELS:
        b = CoachChoice(
            key="B",
            label=_RECALL_LABELS[recall],
            expected_outcome=_recall_outcome(economy, next_item),
            confidence="mid",
            source_tag=SOURCE_TAG,
            trigger=trigger,
        )
    else:
        b = CoachChoice(
            key="B",
            label=b_label_alt,
            expected_outcome="play safe; reassess next tick",
            confidence="low",
            source_tag=SOURCE_TAG,
            trigger=trigger,
        )
    out = [a, b]
    # v4: ONE optional additive chip (key C) from the new blocks. The
    # punish-window is more time-sensitive than the spike note, so it wins when
    # both are actionable; absent / even blocks add nothing (the v3 A/B chips
    # are unchanged). _MAX_CHOICES (coach_choices) is 3, so at most one extra.
    extra = _window_chip(cell, trigger) or _spike_chip(cell, trigger)
    if extra is not None:
        out.append(extra)
    return out


def resolve_enemy(
    my_champion: str,
    enemy_comp: Sequence[str],
    mode: str = "sr",
    *,
    payload: Optional[dict] = None,
) -> Optional[str]:
    """First enemy in ``enemy_comp`` the table covers for ``my_champion``.

    Coverage-first: the seed table holds a champion SAMPLE, so most live games
    will not be covered; this returns the first lane opponent that has a cell
    (any band), else None. ``payload`` overrides the loaded table (test seam)."""
    if not my_champion or not enemy_comp:
        return None
    data = payload if payload is not None else load_laning_scenarios(mode)
    scen = data.get("scenarios") if isinstance(data, dict) else None
    per_enemy = scen.get(canonical_champion_id(my_champion)) if isinstance(scen, dict) else None
    if not isinstance(per_enemy, dict):
        return None
    for enemy in enemy_comp:
        if enemy and canonical_champion_id(enemy) in per_enemy:
            return str(enemy)
    return None


def _resolve_cell_ctx(
    my_champion: str,
    enemy: str,
    level: object,
    *,
    mana_fraction: Optional[float],
    ult_up: Optional[bool],
    mode: str,
    payload: Optional[dict],
    item_count: Optional[int] = None,
) -> Tuple[Optional[dict], dict]:
    """Resolve the laning cell AND the lookup context it was found at.

    Returns ``(cell_or_None, ctx)`` where ctx carries the loaded ``data`` + the
    canonical ids + the RESOLVED axes (``band`` is the post-fallback band the
    cell was actually read from, so a rebranch probe varies the SAME band). The
    item-370 L16->L11 descend-only fallback is applied here. v4 threads the
    ``item_state`` 6th key (item_state_for(item_count)); lookup itself descends
    to the item-state ``none`` cell when the requested state is absent, and is
    backward-compatible with the v3 (item-state-less) committed tables. No
    exception handling - the public callers wrap it so the hot path never
    raises."""
    band = band_for_level(level)
    mana = mana_state_for(mana_fraction)
    cd = cd_state_for(ult_up)
    item_state = item_state_for(item_count)
    data = payload if payload is not None else load_laning_scenarios(mode)
    my_id = canonical_champion_id(my_champion)
    enemy_id = canonical_champion_id(enemy)
    band_used = band
    cell = lookup(data, my_id, enemy_id, band, mana, cd, item_state)
    if not cell and band not in GEN_BANDS:
        # item 370 dropped L16 from the generated sweep to halve the
        # full-roster artifact; the documented lvl>=14 fail-soft now reads
        # the highest generated lane band (L11 / 2-item mid) rather than
        # yielding no coaching. ARAM shared-XP rockets champs to 14-18, so
        # without this nearest-band fallback most live ARAM laning ticks
        # land in the empty L16 and never accrue shadow coverage for the
        # flip gate. Descend-only: rescues the level axis, never the pair /
        # mana / cd axes (a genuinely uncovered cell still yields []).
        band_used = GEN_BANDS[-1] if GEN_BANDS else band
        cell = lookup(data, my_id, enemy_id, band_used, mana, cd, item_state)
    ctx = {
        "data": data, "my_id": my_id, "enemy_id": enemy_id,
        "band": band_used, "mana": mana, "cd": cd, "item_state": item_state,
    }
    return (cell if cell else None), ctx


def _resolve_cell(
    my_champion: str,
    enemy: str,
    level: object,
    *,
    mana_fraction: Optional[float],
    ult_up: Optional[bool],
    mode: str,
    payload: Optional[dict],
    item_count: Optional[int] = None,
) -> Optional[dict]:
    """Look up the one laning cell for the live state (or ``None``).

    Shared by ``precomputed_choices`` (which shapes A/B chips) and
    ``resolve_band`` (which only needs the recalibrated verdict for the CV
    shadow column). Thin wrapper over ``_resolve_cell_ctx`` that drops the
    context the band probe needs."""
    cell, _ctx = _resolve_cell_ctx(
        my_champion, enemy, level, mana_fraction=mana_fraction,
        ult_up=ult_up, mode=mode, payload=payload, item_count=item_count,
    )
    return cell


def _resolve_rebranch(cell: dict, ctx: dict, enemy: str, verdict: str) -> Tuple[str, str]:
    """Probe the adjacent cell + derive the A-chip rebranch (RC2 5.4).

    Impure glue: reads the SAME loaded payload (no engine call, no network) to
    decide whether the axis currently limiting aggression (ult down, then low
    mana) would unlock a more aggressive verdict, then defers the wording to the
    pure ``laning_rebranch``. Fail-soft to ``("", "")`` on any lookup miss."""
    economy = cell.get("economy") if isinstance(cell.get("economy"), dict) else {}
    b_is_recall = str(economy.get("recall") or "") in _RECALL_LABELS

    upgrade_axis: Optional[str] = None
    probe_cell: Optional[dict] = None
    istate = ctx.get("item_state", "none")
    if ctx["cd"] == "no_ult":
        upgrade_axis = "ult"
        probe_cell = lookup(
            ctx["data"], ctx["my_id"], ctx["enemy_id"], ctx["band"],
            ctx["mana"], "all_up", istate)
    elif ctx["mana"] == "low":
        upgrade_axis = "mana"
        probe_cell = lookup(
            ctx["data"], ctx["my_id"], ctx["enemy_id"], ctx["band"],
            "full", ctx["cd"], istate)

    upgrade_unlocks = bool(probe_cell) and _more_aggressive(
        laning_band(probe_cell), verdict)
    return laning_rebranch(
        verdict, enemy=enemy, upgrade_axis=upgrade_axis,
        upgrade_unlocks=upgrade_unlocks, b_is_recall=b_is_recall,
    )


def precomputed_choices(
    my_champion: str,
    enemy: str,
    level: object,
    *,
    mana_fraction: Optional[float] = None,
    ult_up: Optional[bool] = None,
    mode: str = "sr",
    payload: Optional[dict] = None,
    next_item: Optional[Tuple[str, int]] = None,
    item_count: Optional[int] = None,
) -> list[CoachChoice]:
    """Two A/B choices for the live (champ vs enemy) laning cell, or ``[]``.

    Resolves the band / mana-state / cd-state / item-state from the live inputs,
    looks the cell up in the HZ-A table (``payload`` overrides for tests), and
    shapes the A/B choices. v4: the optional ``cooldown_window`` / ``spike_timing``
    blocks add additive chips when present (absent -> no extra chip; the v3 A/B
    trade chips are unchanged). Returns ``[]`` fail-soft on a missing table or
    uncovered cell."""
    try:
        if not my_champion or not enemy:
            return []
        cell, ctx = _resolve_cell_ctx(
            my_champion, enemy, level, mana_fraction=mana_fraction,
            ult_up=ult_up, mode=mode, payload=payload, item_count=item_count,
        )
        if not cell:
            return []
        trigger = laning_trigger(
            enemy, level, mana_state=ctx["mana"], cd_state=ctx["cd"],
        )
        # RC2 5.4: derive the condition-change branch from the recalibrated
        # verdict + an adjacent-cell probe over the same loaded payload.
        rebranch_when, rebranch_to = _resolve_rebranch(
            cell, ctx, enemy, laning_band(cell),
        )
        return _build_choices(
            cell, enemy, next_item=next_item, trigger=trigger,
            rebranch_when=rebranch_when, rebranch_to=rebranch_to,
        )
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return []


def resolve_band(
    my_champion: str,
    enemy: str,
    level: object,
    *,
    mana_fraction: Optional[float] = None,
    ult_up: Optional[bool] = None,
    mode: str = "sr",
    payload: Optional[dict] = None,
    item_count: Optional[int] = None,
) -> Optional[str]:
    """The recalibrated ``laning_band`` verdict for the live cell, or ``None``.

    RC2 P5.1: the CV-override layer (``core.laning_cv_overrides``) needs the
    STATIC band verdict to decide whether a low-HP read should veto an
    aggressive call. This exposes exactly that - the same cell resolution as
    ``precomputed_choices`` (incl. the L16 + item-state fallbacks), reduced to
    its verdict. Fail-soft ``None`` on a missing table or uncovered cell (never
    raises)."""
    try:
        if not my_champion or not enemy:
            return None
        cell = _resolve_cell(
            my_champion, enemy, level, mana_fraction=mana_fraction,
            ult_up=ult_up, mode=mode, payload=payload, item_count=item_count,
        )
        return laning_band(cell) if cell else None
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


# Re-export so a caller never reaches past this module for the band set.
__all__ = [
    "LEVEL_BANDS",
    "SOURCE_TAG",
    "band_for_level",
    "mana_state_for",
    "cd_state_for",
    "item_state_for",
    "laning_band",
    "laning_trigger",
    "laning_rebranch",
    "resolve_enemy",
    "resolve_band",
    "precomputed_choices",
]
