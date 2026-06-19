"""Phase 2 (s175, 2026-05-12) - Bruiser hybrid scorer.

Composes ``compute_dps()`` (Phase 4 thin slice + later batches) with
``compute_ehp()`` (Phase 1 s174) into a single archetype score for
bruisers - champions that want both damage AND survivability.

The score is

    hybrid_score = alpha * dps + beta * ehp

with raw absolute units exposed alongside, plus a normalized
percentage-delta view used by the ranker so the alpha/beta weights stay
intuitive (alpha=0.55 weights a 1% DPS gain 10% more than a 1% EHP gain
at beta=0.45, rather than DPS swamping EHP by an order of magnitude
because the raw units differ by ~10x).

Per-champion (alpha, beta) overrides live in ``archetype_weights.json``;
the table ships with ~20 bruisers (Jarvan IV, Darius, Garen, Camille,
Renekton, Sett, Mordekaiser, Riven, Volibear, Nasus, Olaf, Skarner,
Hecarim, Udyr, Vi, Xin Zhao, Lee Sin, Wukong/MonkeyKing, Warwick,
Trundle). Unlisted champions fall back to the default (0.50, 0.50).

Phase 2 deliberate omissions (deferred):
* Per-champion calibration from rewind_history.db - Phase 2.5 once we
  have enough hybrid-scorer logs to compare against actual outcomes.
* Phase/level-aware weights - early-game Camille is more snowball-DPS
  than late-game Camille, but a single weight pair is good enough for
  the v1 ranker.

The ``archetype_weights.json`` table is a static design choice, not a
patch-derived snapshot, so it lives alongside the engine code rather
than under ``data/daemon_slayer/<patch>/`` like the lolmath snapshots.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .dps import compute_dps
from .effects import ITEM_EFFECTS
from .ehp import compute_ehp
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .survivability_credit import survivability_item_ids

_ARCHETYPE_WEIGHTS_PATH = Path(__file__).resolve().parent / "archetype_weights.json"

_WEIGHTS_LOCK = threading.Lock()
_WEIGHTS_CACHE: Optional[dict] = None


def _load_archetype_weights() -> dict:
    """Load the alpha/beta table from disk; cache for the process lifetime.

    Returns the parsed JSON object. Tests that need to override the table
    can ``_WEIGHTS_CACHE`` directly via the module attribute.
    """
    global _WEIGHTS_CACHE
    with _WEIGHTS_LOCK:
        if _WEIGHTS_CACHE is None:
            _WEIGHTS_CACHE = json.loads(_ARCHETYPE_WEIGHTS_PATH.read_text(encoding="utf-8"))
        return _WEIGHTS_CACHE


def get_weights_for(champion_id: str) -> tuple[float, float]:
    """Return ``(alpha, beta)`` for ``champion_id``. Falls back to default.

    ``champion_id`` is the DDragon canonical id (e.g. ``"JarvanIV"``,
    ``"MonkeyKing"``), not the display name. Server-side
    ``_resolve_champion_id`` runs display->id resolution before this is
    called.
    """
    table = _load_archetype_weights()
    overrides = table.get("champions") or {}
    if champion_id in overrides:
        pair = overrides[champion_id]
        return (float(pair[0]), float(pair[1]))
    default = table.get("default") or [0.5, 0.5]
    return (float(default[0]), float(default[1]))


@dataclass(frozen=True)
class HybridResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    alpha: float                       # DPS weight
    beta: float                        # EHP weight
    alpha_source: str                  # "champion" or "default" or "override"
    dps: float                         # weighted_dps from compute_dps
    ehp: float                         # blended_ehp from compute_ehp (PRE-CC discount)
    hybrid_score: float                # alpha * dps + beta * ehp_for_score (raw scalar; units mixed)
    target_armor: float                # passed through to compute_dps
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    enemy_ad_share: float              # passed through to compute_ehp
    enemy_ap_share: float
    enemy_true_share: float
    phase: str                         # from compute_dps result
    mode_multiplier_dps: float         # aramDamageDealt; 1.0 outside ARAM
    mode_multiplier_ehp: float         # aramDamageTaken; 1.0 outside ARAM
    # ENGINE 1.35.0 (item 138 carry (a)) - first DS-engine SCORER
    # consumer of cc_blended_ehp. When enemy_champions is non-empty,
    # hybrid_score reads from cc_blended_ehp (not blended_ehp), and the
    # two new fields surface the cc-aware value + the input tuple.
    # Default (empty tuple) preserves byte-identical behavior with all
    # pre-1.35.0 callers because compute_ehp returns
    # cc_blended_ehp == blended_ehp under that identity contract.
    cc_blended_ehp: float = 0.0        # blended_ehp * (1 - cc_fraction * 0.5) when enemies provided
    enemy_champions: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "alpha": self.alpha,
            "beta": self.beta,
            "alpha_source": self.alpha_source,
            "dps": self.dps,
            "ehp": self.ehp,
            "hybrid_score": self.hybrid_score,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
            "phase": self.phase,
            "mode_multiplier_dps": self.mode_multiplier_dps,
            "mode_multiplier_ehp": self.mode_multiplier_ehp,
            "cc_blended_ehp": self.cc_blended_ehp,
            "enemy_champions": list(self.enemy_champions),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [BRUISER]"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"weights: alpha={self.alpha:.2f}  beta={self.beta:.2f}  "
            f"(source: {self.alpha_source})"
        )
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
        )
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        rows.append("")
        rows.append(f"  dps            {self.dps:.2f}    (weighted)")
        rows.append(f"  ehp            {self.ehp:.0f}    (blended)")
        rows.append(f"  hybrid_score   {self.hybrid_score:.2f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def compute_hybrid(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    phase: Optional[str] = None,
    augments: Optional[Iterable] = None,
    enemy_champions: Iterable[str] = (),
    include_conditional: bool = False,
    apply_mode_modifiers: bool = False,
    apply_build_tenacity: bool = False,
    apply_passive_mitigation: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_spell_shield: bool = False,
    apply_survival_window: bool = False,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    apply_melee_aa_gate: bool = False,
) -> HybridResult:
    """Compute combined DPS + EHP score for the resolved build.

    ``alpha`` / ``beta`` default to per-champion overrides from
    ``archetype_weights.json``; callers can pass explicit floats to
    override (operator chooses different weights mid-game, A/B testing,
    UI sliders).

    The returned ``hybrid_score`` is the raw weighted sum and is in mixed
    units (DPS + EHP). It exists for completeness; the ranker uses a
    normalized percentage-delta formulation that handles the unit
    mismatch - see ``rank_items_by_hybrid``.

    ENGINE 1.35.0 (item 138 carry (a)): ``enemy_champions`` is the first
    DS-engine SCORER consumer of ``cc_blended_ehp`` (the field shipped
    item 137 / ENGINE 1.33.0 via ``compute_ehp``). When non-empty, the
    same iterable is threaded to ``compute_ehp`` and the
    ``hybrid_score`` consumes ``ehp_result.cc_blended_ehp`` in place of
    ``ehp_result.blended_ehp``. Empty tuple (default) preserves
    byte-identical behavior with all pre-1.35.0 callers - by the
    identity contract pinned in item 137 ``ContractTests``, compute_ehp
    returns ``cc_blended_ehp == blended_ehp`` when ``enemy_champions``
    is empty. The ``ehp`` field on ``HybridResult`` keeps its
    ``blended_ehp`` semantics (PRE-CC) for transparency; the new
    ``cc_blended_ehp`` field surfaces the POST-CC value alongside.

    ENGINE 1.39.0 (item 143 Slice B): ``include_conditional`` propagates
    through to ``compute_ehp`` which threads it down to
    ``compute_cc_pressure``. When True, the conditional CC registry
    (operator-tunable probability midpoints) folds into the cc_blended_ehp
    discount; ``HybridResult.cc_blended_ehp`` reflects the larger
    post-CC-erosion discount automatically. Default ``False`` preserves
    byte-identical behavior with item 138 / ENGINE 1.35.0 callers - the
    kwarg flow is indirect (hybrid -> ehp -> cc_pressure) so this module
    has no direct dependency on the conditional CC registry. The 4
    existing consumers of compute_hybrid (ranker baseline, ranker
    per-candidate, direct callers, dashboard) keep byte-identical
    math at the default.

    ENGINE 1.92.0 (item 262): ``apply_passive_mitigation`` threads the
    item-261 effects-text DAMAGE-REDUCTION layer into the BRUISER EHP
    scorer (symmetric completion - item 261 wired the TANK ``compute_ehp``
    + ``rank_items_by_ehp``; this mirrors it for ``compute_hybrid`` +
    ``rank_items_by_hybrid``). When True it flows to ``compute_ehp`` which
    folds the per-champion flat-% DR into the three EHP denominators, so a
    champion with a registered mitigation passive (Kassadin / KSante /
    Briar / Irelia / Nilah) gets a DR-boosted ``ehp`` + ``cc_blended_ehp``
    -> a larger ``hybrid_score`` scalar. Default False = all three DR
    multipliers 1.0 = BYTE-IDENTICAL to 1.91.0. Mitigation is a
    CHAMPION passive (build-independent) so it scales the EHP denominator
    uniformly; it raises the displayed scalar but does NOT change the
    ratio-based ``hybrid_delta_pct`` sort (see ``rank_items_by_hybrid``).
    """
    level = clamp_level(level)
    if alpha is None or beta is None:
        default_alpha, default_beta = get_weights_for(champion_id)
        alpha_resolved = default_alpha if alpha is None else float(alpha)
        beta_resolved = default_beta if beta is None else float(beta)
        if alpha is None and beta is None:
            table = _load_archetype_weights()
            overrides = table.get("champions") or {}
            alpha_source = "champion" if champion_id in overrides else "default"
        else:
            alpha_source = "override"
    else:
        alpha_resolved = float(alpha)
        beta_resolved = float(beta)
        alpha_source = "override"

    item_list = tuple(str(i) for i in (item_ids or ()))
    # Mirror item_list normalization pattern: coerce to tuple-of-str
    # once at the top so both the compute_ehp call AND the HybridResult
    # surface field see the same value. ``or ()`` handles a None input.
    enemy_champions_tuple = tuple(str(e) for e in (enemy_champions or ()))

    dps_result = compute_dps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=item_list,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=phase,
        augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_melee_aa_gate=apply_melee_aa_gate,
    )
    # ENGINE 1.39.0 (item 143 Slice B): pass include_conditional through
    # to compute_ehp ONLY when True. This preserves byte-identical
    # behavior with all pre-Slice-A-merge callers (compute_ehp does not
    # yet accept the kwarg in main; Slice A adds it). Once Slice A
    # merges, the **kwargs threading is byte-identical to threading the
    # kwarg unconditionally because the default is False.
    _ehp_kwargs = {}
    if include_conditional:
        _ehp_kwargs["include_conditional"] = True
    ehp_result = compute_ehp(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=item_list,
        mode=mode,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        augments=augments,
        enemy_champions=enemy_champions_tuple,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_build_tenacity=apply_build_tenacity,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_spell_shield=apply_spell_shield,
        apply_survival_window=apply_survival_window,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_resist=apply_passive_resist,
        apply_passive_revive=apply_passive_revive,
        **_ehp_kwargs,
    )

    # When enemy_champions is empty, ehp_result.cc_blended_ehp ==
    # ehp_result.blended_ehp by the item 137 identity contract, so this
    # branch is a no-op for all pre-1.35.0 call sites. The explicit
    # branch keeps the intent legible.
    ehp_for_score = (
        ehp_result.cc_blended_ehp if enemy_champions_tuple else ehp_result.blended_ehp
    )
    hybrid_score = alpha_resolved * dps_result.weighted_dps + beta_resolved * ehp_for_score

    notes: list[str] = []
    notes.append(
        f"alpha={alpha_resolved:.2f} / beta={beta_resolved:.2f} ({alpha_source})"
    )
    if enemy_champions_tuple and ehp_result.enemy_cc_pressure_s > 0.0:
        notes.append(
            f"enemy CC pressure {ehp_result.enemy_cc_pressure_s:.1f}s "
            f"(fraction {ehp_result.cc_pressure_fraction:.2f}) -> "
            f"cc_blended_ehp {ehp_result.cc_blended_ehp:.0f}"
        )

    return HybridResult(
        champion_id=dps_result.champion_id,
        champion_name=dps_result.champion_name,
        level=level,
        item_ids=item_list,
        mode=mode,
        alpha=alpha_resolved,
        beta=beta_resolved,
        alpha_source=alpha_source,
        dps=dps_result.weighted_dps,
        ehp=ehp_result.blended_ehp,
        hybrid_score=hybrid_score,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=ehp_result.enemy_true_share,
        phase=dps_result.phase,
        mode_multiplier_dps=dps_result.mode_multiplier,
        mode_multiplier_ehp=ehp_result.mode_multiplier,
        cc_blended_ehp=ehp_result.cc_blended_ehp,
        enemy_champions=enemy_champions_tuple,
        notes=tuple(notes),
    )


# ----------------------------------------------------------------- ranker


@dataclass(frozen=True)
class HybridRankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_dps: float                   # raw DPS gain
    delta_ehp: float                   # raw EHP gain
    new_dps: float
    new_ehp: float
    # Normalized score: alpha * (delta_dps / baseline_dps) + beta * (delta_ehp / baseline_ehp).
    # Sort key. Operator-facing - represents the weighted-percentage gain
    # so that alpha+beta=1.0 maps to an intuitive 'balance' default.
    hybrid_delta_pct: float
    hybrid_score: float                # alpha * new_dps + beta * new_ehp (raw, units mixed)
    hybrid_per_1k_gold: float          # hybrid_delta_pct / (gold/1000); 0 when delta<=0
    is_terminal: bool
    tags: tuple[str, ...]
    # Mirror the DPS/EHP dead-unique flag so consumers can suppress or annotate.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""
    # Item 237: CC-adjusted EHP surface (mirrors EhpRankedItem). == new_ehp /
    # delta_ehp when no enemy_champions (the compute_ehp identity contract).
    cc_blended_ehp: float = 0.0
    delta_cc_blended_ehp: float = 0.0
    # RF1 generic-bruiser-template survivability credit marker (1.136.0). 0.0 on
    # the default path (``prefer_survivability_by_win=False``) so the rows + sort
    # stay byte-identical. When the seam is engaged this is 1.0 on a WIN-anchored
    # survivability item (by table membership, NOT by hybrid delta - the defect is
    # that the damage-biased sort rates these low) and 0.0 otherwise; the ranking
    # then sorts by it first, floating those items above the generic AD template.
    survivability_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_dps": self.delta_dps,
            "delta_ehp": self.delta_ehp,
            "new_dps": self.new_dps,
            "new_ehp": self.new_ehp,
            "hybrid_delta_pct": self.hybrid_delta_pct,
            "hybrid_score": self.hybrid_score,
            "hybrid_per_1k_gold": self.hybrid_per_1k_gold,
            "cc_blended_ehp": self.cc_blended_ehp,
            "delta_cc_blended_ehp": self.delta_cc_blended_ehp,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
            "survivability_score": self.survivability_score,
        }


@dataclass(frozen=True)
class HybridRankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    alpha: float
    beta: float
    alpha_source: str
    baseline_dps: float
    baseline_ehp: float
    baseline_hybrid: float             # alpha * baseline_dps + beta * baseline_ehp
    enemy_ad_share: float
    enemy_ap_share: float
    enemy_true_share: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    phase: str
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int
    candidates_evaluated: int
    ranked: tuple[HybridRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Item 237: which EHP metric the delta_pct sort key used - "blended"
    # (default, PRE-cc) or "cc_blended" (enemy-CC-lockdown-adjusted + tenacity).
    score_by: str = "blended"

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "alpha": self.alpha,
            "beta": self.beta,
            "alpha_source": self.alpha_source,
            "baseline_dps": self.baseline_dps,
            "baseline_ehp": self.baseline_ehp,
            "baseline_hybrid": self.baseline_hybrid,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "phase": self.phase,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "score_by": self.score_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - phase {self.phase}  [BRUISER]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"weights: alpha={self.alpha:.2f}  beta={self.beta:.2f}  "
            f"(source: {self.alpha_source})"
        )
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
        )
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline:  dps={self.baseline_dps:.1f}  ehp={self.baseline_ehp:.0f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+dps':>6}  {'+ehp':>6}  {'h%':>6}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_dps:>6.1f}  {r.delta_ehp:>6.0f}  "
                f"{r.hybrid_delta_pct * 100:>5.1f}%"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def _hybrid_delta_pct(
    delta_dps: float,
    delta_ehp: float,
    baseline_dps: float,
    baseline_ehp: float,
    alpha: float,
    beta: float,
) -> float:
    """Return the weighted percentage-delta score.

    Normalizes each delta against its own baseline so the alpha/beta
    weights have a consistent meaning regardless of the raw magnitude
    gap between DPS (~hundreds) and EHP (~thousands). At alpha=beta=0.5,
    a 10% DPS gain weights the same as a 10% EHP gain - intuitive for
    operator-facing slider semantics.

    Falls back to absolute deltas when a baseline is 0 (e.g. naked
    champion with crippled DPS in some niche cases) to avoid div-by-zero.
    """
    dps_pct = (delta_dps / baseline_dps) if baseline_dps > 0 else 0.0
    ehp_pct = (delta_ehp / baseline_ehp) if baseline_ehp > 0 else 0.0
    return alpha * dps_pct + beta * ehp_pct


def rank_items_by_hybrid(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    phase: Optional[str] = None,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    enemy_champions: Iterable[str] = (),
    include_conditional: bool = False,
    apply_mode_modifiers: bool = False,
    apply_build_tenacity: Optional[bool] = None,
    apply_passive_mitigation: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_spell_shield: bool = False,
    apply_survival_window: bool = False,
    score_by: str = "blended",
    filter_shared_uniques: bool = True,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    prefer_survivability_by_win: bool = False,
    cost_ceiling: Optional[int] = None,
) -> HybridRankResult:
    """Rank items by weighted (alpha*dps + beta*ehp) delta when added to ``current_item_ids``.

    Sort keys:
      * ``delta``       - weighted percentage delta (alpha*dps_pct + beta*ehp_pct); default
      * ``efficiency``  - hybrid delta percentage per 1000 gold

    Same candidate filtering pipeline as ``rank_items`` and
    ``rank_items_by_ehp`` - purchasable + mode-legal + optional whitelist
    + budget + terminal-only + dead-unique dedup. Only the scoring
    function differs.

    ``alpha`` / ``beta`` default to ``archetype_weights.json`` lookup;
    callers can override per-call (UI sliders, A/B testing).

    ENGINE 1.92.0 (item 262): ``apply_passive_mitigation`` flows the
    item-261 effects-text DR layer into every ``compute_ehp`` call
    (baseline + each candidate) so the displayed ``hybrid_score`` +
    ``cc_blended_ehp`` row fields are DR-boosted for a champion with a
    registered mitigation passive. Default False = BYTE-IDENTICAL to
    1.91.0. NOTE the mitigation is a CHAMPION passive (build-independent),
    so it scales the EHP denominator uniformly across the baseline AND
    every candidate; the ratio-based ``hybrid_delta_pct`` sort key
    (delta_ehp / baseline_ehp) is INVARIANT under that uniform scale ->
    enabling it does NOT re-rank, it makes the per-row scalars accurate
    (mirrors item 261's tank ``rank_items_by_ehp`` behavior - a champion
    passive cannot differentiate one candidate from another the way the
    build-dependent tenacity term does).

    ``prefer_survivability_by_win`` is the OPTIONAL RF1 generic-bruiser-template
    seam (DEFAULT-OFF). The hybrid sort key (alpha*dps_pct + beta*ehp_pct) is
    alpha-weighted toward damage and the default mixed-damage target preset
    under-credits the pure resist/sustain axis, so the WIN-correlated
    survivability items the player base wins ARAM on (Spirit Visage / Jak'Sho /
    Sterak's Gage / Death's Dance / Force of Nature / Randuin's Omen / Thornmail /
    Titanic Hydra / Fimbulwinter; the DSP10 buried winners) sink below the generic
    AD-DPS template. When ``False`` (default) the output is byte-identical -
    ``survivability_score`` stays 0.0 and the sort is unchanged. When ``True`` and
    the champ has a WIN-anchored ``survivability_item_credit`` entry, every tabled
    survivability item is floated above the generic template (model order preserved
    within each tier). UNLIKE the DSP11 DPS/burst kit-axis seam (which gates the
    float on ``delta_dps > 0``), this floats by TABLE MEMBERSHIP - survivability
    items add EHP not DPS, so their hybrid delta is ~0 and a delta gate would never
    surface them; the win-rate membership IS the signal the damage-biased sort is
    blind to. Champs absent from the table are a no-op. The live default-ON flip is
    EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    if score_by not in ("blended", "cc_blended"):
        raise ValueError(
            f"score_by must be 'blended' or 'cc_blended', got {score_by!r}"
        )
    # Item 237: tenacity-credit defaults ON for cc_blended bruiser ranking (the
    # cc_blended discount is build-INDEPENDENT without it -> an inert sort) and
    # OFF for the default blended mode (byte-identical). Explicit bool overrides.
    apply_tenacity = (
        apply_build_tenacity if apply_build_tenacity is not None
        else (score_by == "cc_blended")
    )
    level = clamp_level(level)

    if alpha is None or beta is None:
        default_alpha, default_beta = get_weights_for(champion_id)
        alpha_resolved = default_alpha if alpha is None else float(alpha)
        beta_resolved = default_beta if beta is None else float(beta)
        if alpha is None and beta is None:
            table = _load_archetype_weights()
            overrides = table.get("champions") or {}
            alpha_source = "champion" if champion_id in overrides else "default"
        else:
            alpha_source = "override"
    else:
        alpha_resolved = float(alpha)
        beta_resolved = float(beta)
        alpha_source = "override"

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    # ENGINE 1.35.0 - shared enemy_champions tuple flows into BOTH the
    # baseline + the scored compute_ehp calls so deltas are consistent.
    enemy_champions_tuple = tuple(str(e) for e in (enemy_champions or ()))
    current_unique_keys: set[str] = set()
    for iid in current_ids:
        eff = ITEM_EFFECTS.get(iid)
        if eff is not None and eff.unique_passive_key:
            current_unique_keys.add(eff.unique_passive_key)

    if len(current_ids) >= slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"leaves no room for a new item"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    baseline_dps_result = compute_dps(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        phase=phase, augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
    )
    # ENGINE 1.39.0 (item 143 Slice B): pass include_conditional through
    # only when True (same pattern as compute_hybrid above).
    _ehp_kwargs_baseline = {}
    if include_conditional:
        _ehp_kwargs_baseline["include_conditional"] = True
    baseline_ehp_result = compute_ehp(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
        augments=augments,
        enemy_champions=enemy_champions_tuple,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_build_tenacity=apply_tenacity,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_resist=apply_passive_resist,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_spell_shield=apply_spell_shield,
        apply_survival_window=apply_survival_window,
        **_ehp_kwargs_baseline,
    )
    baseline_dps = baseline_dps_result.weighted_dps
    # baseline_ehp keeps the blended_ehp semantics for the
    # _hybrid_delta_pct percentage-normalizer below (the ranker compares
    # apples-to-apples: blended_ehp delta over blended_ehp baseline).
    # The cc_blended_ehp value influences the baseline_hybrid scalar via
    # the same ehp_for_score branch as compute_hybrid.
    baseline_ehp = baseline_ehp_result.blended_ehp
    baseline_ehp_for_score = (
        baseline_ehp_result.cc_blended_ehp
        if enemy_champions_tuple
        else baseline_ehp_result.blended_ehp
    )
    baseline_hybrid = alpha_resolved * baseline_dps + beta_resolved * baseline_ehp_for_score
    # Item 237: the EHP normalizer the delta_pct sort key divides by. Default
    # "blended" keeps the PRE-cc baseline (byte-identical); "cc_blended" uses the
    # CC-lockdown-adjusted baseline so a tenacity item's cc-EHP gain re-ranks.
    active_baseline_ehp = (
        baseline_ehp_result.cc_blended_ehp if score_by == "cc_blended"
        else baseline_ehp
    )

    # RF1 (DEFAULT-OFF): resolve the champ's WIN-anchored survivability item set.
    # Empty unless the seam is ON AND the champ is tabled -> byte-identical no-op.
    champ_rec = snapshot.champions.get(str(champion_id))
    surv_ids: frozenset[str] = (
        survivability_item_ids(str(champion_id), champ_rec)
        if prefer_survivability_by_win else frozenset()
    )
    surv_active = bool(surv_ids)

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
        # F2 cost-aware-top seam (DEFAULT-OFF). Drops over-cost mega-items
        # (e.g. 6000g Void Immolation 223069) the absolute weighted-delta floats
        # to rank-1 on the bruiser scorer. None -> byte-identical pool.
        cost_ceiling=cost_ceiling,
    )

    ranked: list[HybridRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            dps_scored = compute_dps(
                snapshot,
                champion_id=champion_id, level=level,
                item_ids=new_build, mode=mode,
                target_armor=target_armor, target_mr=target_mr,
                target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
                phase=phase, augments=augments,
                apply_mode_modifiers=apply_mode_modifiers,
            )
            # ENGINE 1.39.0 (item 143 Slice B): same conditional kwarg
            # threading pattern as the baseline call above.
            _ehp_kwargs_scored = {}
            if include_conditional:
                _ehp_kwargs_scored["include_conditional"] = True
            ehp_scored = compute_ehp(
                snapshot,
                champion_id=champion_id, level=level,
                item_ids=new_build, mode=mode,
                enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
                augments=augments,
                enemy_champions=enemy_champions_tuple,
                apply_mode_modifiers=apply_mode_modifiers,
                apply_build_tenacity=apply_tenacity,
                apply_passive_mitigation=apply_passive_mitigation,
                apply_passive_resist=apply_passive_resist,
                apply_passive_revive=apply_passive_revive,
                apply_champion_tenacity=apply_champion_tenacity,
                apply_spell_shield=apply_spell_shield,
                apply_survival_window=apply_survival_window,
                **_ehp_kwargs_scored,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta_dps = dps_scored.weighted_dps - baseline_dps
        delta_ehp = ehp_scored.blended_ehp - baseline_ehp
        cc_delta_ehp = ehp_scored.cc_blended_ehp - baseline_ehp_result.cc_blended_ehp
        # Item 237: the active EHP metric drives the delta_pct sort key. Default
        # "blended" uses the PRE-cc delta (byte-identical); "cc_blended" uses the
        # CC-lockdown-adjusted delta (+ tenacity) so a tenacity item rises vs a
        # non-saturating CC comp - the bruiser mirror of the item-236 tank mode.
        active_delta_ehp = cc_delta_ehp if score_by == "cc_blended" else delta_ehp
        delta_pct = _hybrid_delta_pct(
            delta_dps, active_delta_ehp, baseline_dps, active_baseline_ehp,
            alpha_resolved, beta_resolved,
        )
        ehp_scored_for_score = (
            ehp_scored.cc_blended_ehp
            if enemy_champions_tuple
            else ehp_scored.blended_ehp
        )
        new_hybrid_score = (
            alpha_resolved * dps_scored.weighted_dps
            + beta_resolved * ehp_scored_for_score
        )
        # Efficiency: weighted percentage gain per 1000 gold.
        # Zero or negative deltas zero out - regression isn't "efficient".
        eff = (delta_pct / (gold / 1000.0)) if (gold > 0 and delta_pct > 0) else 0.0
        # RF1 survivability credit marker: 1.0 on a WIN-anchored survivability item
        # when the seam is engaged, else 0.0. Floated BY MEMBERSHIP (these items add
        # EHP not DPS, so a delta gate would never surface them).
        survivability_score = 1.0 if (surv_active and item_id in surv_ids) else 0.0
        ranked.append(HybridRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_dps=delta_dps,
            delta_ehp=delta_ehp,
            new_dps=dps_scored.weighted_dps,
            new_ehp=ehp_scored.blended_ehp,
            hybrid_delta_pct=delta_pct,
            hybrid_score=new_hybrid_score,
            hybrid_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
            cc_blended_ehp=ehp_scored.cc_blended_ehp,
            delta_cc_blended_ehp=cc_delta_ehp,
            survivability_score=survivability_score,
        ))

    def _base_key(r: HybridRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (r.hybrid_per_1k_gold, r.hybrid_delta_pct)
        return (r.hybrid_delta_pct, r.hybrid_per_1k_gold)

    if surv_active:
        # RF1: float surfaced survivability items above the generic template,
        # preserving model order within each tier. Byte-identical when off
        # (surv_active False -> the prefix term is never added).
        ranked.sort(key=lambda r: (r.survivability_score,) + _base_key(r), reverse=True)
    else:
        ranked.sort(key=_base_key, reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"weights alpha={alpha_resolved:.2f} / beta={beta_resolved:.2f} ({alpha_source})"
    )
    if score_by == "cc_blended":
        notes.append(
            f"score_by=cc_blended - ranked on CC-adjusted EHP "
            f"(tenacity {'on' if apply_tenacity else 'off'}) vs "
            f"{len(enemy_champions_tuple)} enemy champ(s)"
        )
    notes.append(
        f"enemy mix: AD {enemy_ad_share * 100:.0f}% / "
        f"AP {enemy_ap_share * 100:.0f}% / "
        f"true {baseline_ehp_result.enemy_true_share * 100:.0f}%"
    )
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline_dps_result.mode_multiplier == 0.0:
        notes.append(
            "DPS mode_multiplier=0 - hybrid score will weight EHP entirely "
            "(e.g. Yunara in ARAM)"
        )

    return HybridRankResult(
        champion_id=baseline_dps_result.champion_id,
        champion_name=baseline_dps_result.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        alpha=alpha_resolved,
        beta=beta_resolved,
        alpha_source=alpha_source,
        baseline_dps=baseline_dps,
        baseline_ehp=baseline_ehp,
        baseline_hybrid=baseline_hybrid,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=baseline_ehp_result.enemy_true_share,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=baseline_dps_result.phase,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
        score_by=score_by,
    )
