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

from ._ad_axis_ability import (
    AD_AXIS_CREDITED_DAMAGE_TYPES,
    physical_ability_damage,
)
from .ability_dps import compute_ability_dps
from .cast_propensity import propensity_adjusted_dps_delta
from .data_loader import DataSnapshot, canonical_mode
from .dps import compute_dps
from .effects import ITEM_EFFECTS
from .ehp import compute_ehp
from .kit_conversion import conversion_factor, kit_conversion
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _champion_is_melee,
    _filter_candidates,
    _is_terminal,
    mode_filter_note,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .survivability_credit import survivability_item_ids


# --- Damage-axis awareness (bruiser scorer) --------------------------------
# The hybrid (bruiser) scorer's damage term must reflect the champion's real
# damage axis. An AP bruiser routed here (Mordekaiser / Sylas / Vladimir via an
# archetype request or the /rank-bruiser route) scales its power off ABILITY
# damage, not auto-attacks; without this the scorer valued only
# compute_dps().weighted_dps (auto-attack) and built AP champs full AD -
# identical to an AD bruiser (zero AP items).
#
# PRIMARY SOURCE = the kit's own ``lolmath.damage_distribution`` on the snapshot
# champion record. The DDragon ``info.attack`` / ``info.magic`` 0-10 designer
# ratings this function used to read ALONE are cosmetic class flavor that
# reflects base stat GROWTH, not build reality - the exact complaint
# ``onhit_dps.py:315-324`` already had to write down when it bolted on a local
# ``_onhit_ap_axis`` workaround for Gwen and KogMaw. Measured against the live
# snapshot the ratings disagree with the kit for 12 of 173 champions: Alistar
# Gwen KogMaw Leona Locke Ornn Rell Seraphine TwistedFate Vex all read "ad" and
# are really AP, while Belveth and Qiyana read "ap" and are really AD. Belveth
# was the broken and unmitigated one - the "ap" branch below drops
# ``weighted_dps`` entirely, so a 0.698-physical kit was served Liandry's
# Torment #1 and Blackfire Torch #2.
#
# DECISIVENESS GATES mirror ``core.archetype_picks._axis_from_distribution``
# (dominant share >= 0.55 AND margin >= 0.20) so the two resolvers agree by
# construction. A genuine hybrid (measured at this patch: DrMundo Jax Kaisa
# Sejuani Shaco Shen Shyvana Udyr Volibear Warwick) clears neither gate and
# FALLS BACK to the rating split rather than flipping on noise - as does any
# champion with a missing or malformed distribution block.
#
# The constants are LOCAL LITERALS, not an import. This function is deliberately
# self-contained (no ``core`` import) so the engine package stays standalone -
# ``_burst_off_axis.py`` mirrors the same two numbers for the same reason.
# ``tests/test_kit_axis_ap_scaling_guard.py`` pins the two files' literals equal
# by reading both off disk.
#
# THE AXIS SPLIT NO LONGER GUARDS THE AD-AXIS ABILITY TERM - that guard is now
# explicit and lives in ``_physical_ability_damage`` below. The measured
# evidence that made the old accidental protection load-bearing still stands and
# is why the explicit guard exists: Belveth R (dAP +1.2153, ap_pct_sum 300.0)
# and Chogath R (dAP +0.6076, ap_pct_sum 150.0) are AP-SCALING TRUE rows, and
# nothing in the damage-type filter stops them after the L2 TRUE widen. They
# used to be out of reach only because this function routed both to "ap". It now
# routes Belveth to "ad", so the term's own AP-scaling exclusion is what keeps
# her R out. Do NOT reintroduce a rating-based split as a damage-term guard.
_AXIS_DOMINANT_MIN = 0.55
_AXIS_MARGIN_MIN = 0.20


def _damage_axis(snapshot: DataSnapshot, champion_id: str) -> str:
    """Return ``"ap"`` when the champion is magic-primary, else ``"ad"``.

    Reads the kit's own ``lolmath.damage_distribution`` first; falls back to
    the DDragon ``info.attack`` / ``info.magic`` comparison when that block is
    missing, malformed, or not decisive under the dominance / margin gates.
    """
    rec = snapshot.champions.get(str(champion_id)) or {}
    kit = _kit_axis_from_distribution(rec)
    if kit is not None:
        return kit
    info = rec.get("info") or {}
    attack = int(info.get("attack", 0) or 0)
    magic = int(info.get("magic", 0) or 0)
    return "ap" if magic > attack else "ad"


def _kit_axis_from_distribution(champ_rec) -> Optional[str]:
    """``"ad"`` / ``"ap"`` for a DECISIVE kit damage split, else ``None``.

    Fail-soft by design: a missing record, a missing or non-dict block, a
    non-numeric entry, or a split that clears neither gate all return ``None``,
    which hands the decision back to the rating-split fallback.
    """
    if not isinstance(champ_rec, dict):
        return None
    lolmath = champ_rec.get("lolmath") or {}
    if not isinstance(lolmath, dict):
        return None
    dist = lolmath.get("damage_distribution") or {}
    if not isinstance(dist, dict):
        return None
    try:
        magical = float(dist.get("magical") or 0.0)
        physical = float(dist.get("physical") or 0.0)
    except (TypeError, ValueError):
        return None
    dominant, other, label = (
        (magical, physical, "ap") if magical >= physical
        else (physical, magical, "ad")
    )
    if dominant >= _AXIS_DOMINANT_MIN and (dominant - other) >= _AXIS_MARGIN_MIN:
        return label
    return None


def _ability_damage(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids,
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    augments,
    target_current_hp_pct: float = 1.0,
    apply_cast_rate_propensity_prior: bool = False,
) -> float:
    """Ability-DPS scalar (the AP analogue of compute_dps().weighted_dps).

    ``apply_cast_rate_propensity_prior`` (RM-98, DEFAULT-OFF) adds the
    per-spell re-basing delta from ``cast_propensity`` on top of the total.
    Expressed as a DELTA so the ability-amp multiplier and the always-on
    ``item_proc_dps`` fold inside ``total_ability_dps`` stay untouched - the
    proc fold is one of the consumers RM-98 is deliberately NOT wiring here
    (SPEC:109-114). Default False never calls the helper, so this returns the
    same attribute read it always did (byte-identical).
    """
    result = compute_ability_dps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        augments=augments,
    )
    if not apply_cast_rate_propensity_prior:
        return result.total_ability_dps
    return result.total_ability_dps + propensity_adjusted_dps_delta(result.per_spell)


# RM-36 / RM-38 (2026-08-04): the AD-axis ability term MOVED to
# _ad_axis_ability so the CARRY ranker can consume the same definition.
# hybrid imports rank (line 50), so rank cannot import hybrid.
# These two names are re-bound, not re-implemented - there is ONE definition.
_AD_AXIS_CREDITED_DAMAGE_TYPES = AD_AXIS_CREDITED_DAMAGE_TYPES
_physical_ability_damage = physical_ability_damage

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


# R58 assume_ms_utility seam (ENGINE 1.167.0) - Movement Speed utility credit
# for the bruiser/juggernaut scorer. WHY: bruisers convert stickiness into
# uptime - bonus MS closes gaps, holds melee range, and dodges return poke,
# none of which the raw auto-attack DPS math sees, so MS items (Dead Man's
# Plate / Force of Nature / Deadman-style pct rollers) under-rank on the
# damage axis. Each 1 pct bonus MS over the champion's BASE MS is credited
# as _MS_UTILITY_DPS_FRACTION pct of effective bruiser DPS - 0.5 is the
# conservative operator-tunable uptime/stickiness midpoint (a full 1:1 would
# claim every MS point converts to hit-time, plainly too hot).
_MS_UTILITY_DPS_FRACTION = 0.5
# Ceiling on the TOTAL MS-derived DPS credit. WHY: pct-MS stacks additively
# across items (DMP + FoN + boots + ...) and an uncapped linear credit blows
# up on a stacked-MS build; +15 pct effective DPS is the most the stickiness
# story can plausibly buy.
_MS_UTILITY_DPS_CAP = 0.15


def _ms_utility_multiplier(resolved_ms: float, base_ms: float) -> float:
    """Effective-DPS multiplier for bonus MS over base (R58, DEFAULT-OFF seam).

    Pure + fail-soft: a zeroed/missing ``base_ms`` or a resolved MS at or
    below base returns the exact identity 1.0 (slows never PENALIZE through
    this seam; it credits utility, it does not model impairment). Above base,
    the bonus fraction converts at ``_MS_UTILITY_DPS_FRACTION`` and the total
    credit clamps at ``_MS_UTILITY_DPS_CAP``.
    """
    if base_ms <= 0.0 or resolved_ms <= base_ms:
        return 1.0
    bonus_frac = (resolved_ms - base_ms) / base_ms
    return 1.0 + min(_MS_UTILITY_DPS_CAP, bonus_frac * _MS_UTILITY_DPS_FRACTION)


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
    # R58 (ENGINE 1.167.0): the MS-utility multiplier applied to the DPS term
    # of hybrid_score when assume_ms_utility=True. 1.0 on the default path
    # AND whenever the build has no bonus MS - ``dps`` stays RAW weighted_dps
    # either way (the credit lives ONLY in hybrid_score).
    ms_utility_mult: float = 1.0

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
            "ms_utility_mult": self.ms_utility_mult,
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
    apply_item_spell_shield: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    assume_item_general_dr: bool = False,
    apply_survival_window: bool = False,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    apply_melee_aa_gate: bool = False,
    caster_current_hp_pct: float = 1.0,
    assume_ms_utility: bool = False,
    apply_ad_axis_ability_damage: bool = False,
    # RM-36 (DEFAULT-OFF): MODIFIER of the term above - a dual-scaling row
    # the AP-scaling gate drops is re-entered at its AD SHARE alone.
    # Inert unless apply_ad_axis_ability_damage is also armed.
    apply_ad_axis_dual_scaling_split: bool = False,
    # ENGINE 1.224.0 (R132) seam, forwarded verbatim to ``compute_ehp``. Appended at
    # the END per compute_ehp's stated convention - a mid-signature insert shifts the
    # positional index of every later parameter. Guarded by
    # tests/test_rune_resist_signature_convention_r134.py.
    apply_rune_resist_grants: bool = False,
    rune_ids: Iterable[str | int] = (),
    # R136 (ENGINE 1.225.0): the RM-101 numerator pair, appended AFTER the R132
    # tail per the same convention. Both reuse the existing ``rune_ids`` transport.
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    # R137 (ENGINE 1.226.0, RM-99): the item permanent-HP-stack seam, appended AFTER
    # the R136 pair per the same convention.
    assume_item_health_stacks: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_proc_heal: bool = False,
    # R142 (ENGINE 1.229.0): the RM-101 residual defensive-rune pair, appended at
    # END per the same no-mid-signature-insert convention and passed straight
    # through to compute_ehp. Both ride the existing ``rune_ids`` transport.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # R145 (ENGINE 1.232.0): the OFFENSE-side rune adaptive stat-grant seam,
    # appended at END per the same no-mid-signature-insert convention and passed
    # straight through to compute_dps. Rides the existing ``rune_ids`` transport.
    apply_rune_offense_grants: bool = False,
    # RM-98 (2026-07-24): the cast-rate propensity prior. Appended at END per the
    # same no-mid-signature-insert convention. Touches ONLY the ability half of
    # the damage axis (both branches); the EHP half and compute_dps are untouched.
    apply_cast_rate_propensity_prior: bool = False,
    # RM-118 (2026-07-29): the wielder HSP ITEM-amp seam (R60, ENGINE 1.171.0),
    # forwarded verbatim to compute_ehp. Appended at END per the same
    # no-mid-signature-insert convention. DEFAULT-OFF -> byte-identical.
    assume_hsp_amp: bool = False,
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

    ``assume_ms_utility`` (R58, ENGINE 1.167.0, DEFAULT-OFF) credits bonus
    Movement Speed over the champion's base MS as effective bruiser DPS via
    ``_ms_utility_multiplier`` (0.5 DPS-pct per MS-pct, capped +15 pct). The
    multiplier scales ONLY the DPS term of ``hybrid_score``; the ``dps``
    field stays RAW weighted_dps. Default False is byte-identical - the
    score line runs on the same raw value with the same op order.

    ``apply_ad_axis_ability_damage`` (RM-39 / RM-43, DEFAULT-OFF) adds the
    PHYSICAL-only ability term to the AD branch of the damage axis, which is
    otherwise scored on auto-attack DPS ALONE (``dps.py:34`` - "Ability damage
    is not included"). 84 of 173 champions resolve ``_damage_axis`` to "ad"
    (92 before the kit-axis fix; the 12 flips are listed above _damage_axis),
    so their real ability DPS is computed nowhere today; this is the defect
    RM-39 and RM-43 actually describe (spec section 2.2 - the ability-HASTE
    mechanism they originally named is inert precisely BECAUSE there is no
    ability term on this branch to credit it into). When True the AD branch
    becomes ``weighted_dps + _physical_ability_damage(...)``; the damage-type
    guard is mandatory, see that helper. The AP branch is UNCHANGED on both
    paths. Default False binds the SAME raw ``dps_result.weighted_dps`` value
    the pre-seam line bound - a name bind, no float op - so the score line is
    byte-identical.

    ``apply_cast_rate_propensity_prior`` (RM-98, DEFAULT-OFF) fixes the
    TIME-BASE of the ability half of the damage axis. The measured cast rate
    every ability row is multiplied by is a WHOLE-GAME rate being folded into a
    combat-window per-second term (``SPEC_rm98_cast_rate_time_base.md``); both
    candidate denominator replacements are measured infeasible (SPEC:116-133),
    so the adjudicated repair demotes the measured rate to a dimensionless
    cast-propensity PRIOR and rebuilds the rate on cooldown-inverse
    availability. See ``cast_propensity`` for the math and the calibration.

    It applies to BOTH damage-axis branches - the AP branch's
    ``total_ability_dps`` and the AD branch's credited per-spell sum - but ONLY
    to the per-spell rows the engine sourced from the measured table. On the AD
    branch it is therefore inert unless ``apply_ad_axis_ability_damage`` is also
    True, because the OFF branch has no ability term to re-base. Default False
    never calls the transform on either branch, so both are byte-identical.
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
        apply_rune_offense_grants=apply_rune_offense_grants,
        rune_ids=rune_ids,
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
        apply_item_spell_shield=apply_item_spell_shield,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_rune_resist_grants=apply_rune_resist_grants,
        rune_ids=rune_ids,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        assume_hsp_amp=assume_hsp_amp,
        assume_item_health_stacks=assume_item_health_stacks,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_proc_heal=assume_item_proc_heal,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        assume_item_general_dr=assume_item_general_dr,
        apply_survival_window=apply_survival_window,
        apply_passive_mitigation=apply_passive_mitigation,
        apply_passive_resist=apply_passive_resist,
        apply_passive_revive=apply_passive_revive,
        caster_current_hp_pct=caster_current_hp_pct,
        **_ehp_kwargs,
    )

    # When enemy_champions is empty, ehp_result.cc_blended_ehp ==
    # ehp_result.blended_ehp by the item 137 identity contract, so this
    # branch is a no-op for all pre-1.35.0 call sites. The explicit
    # branch keeps the intent legible.
    ehp_for_score = (
        ehp_result.cc_blended_ehp if enemy_champions_tuple else ehp_result.blended_ehp
    )
    # R58 (ENGINE 1.167.0, DEFAULT-OFF): MS-utility credit on the DPS term
    # only. OFF path binds the SAME raw value (a name bind, not a float op)
    # so the score line below is byte-identical at the default; ON path with
    # no bonus MS resolves to the exact identity 1.0 and skips the rescale.
    # Damage-axis awareness: an AP-primary champion (kit damage_distribution
    # magic-dominant, ratings as fallback) is scored on ABILITY damage so AP
    # items surface; AD champions keep compute_dps().weighted_dps.
    # RM-39/RM-43 (DEFAULT-OFF): the AD branch is auto-attack-only by design
    # (dps.py:34), so 84 of 173 champions never price their ability damage.
    # ON adds the PHYSICAL-only term; OFF binds the SAME raw value (a name
    # bind, not a float op) so this line is byte-identical at the default.
    # RM-98 (DEFAULT-OFF): the cast-rate propensity prior rides BOTH ability
    # branches. Passed by keyword so the positional tail is unchanged.
    if _damage_axis(snapshot, champion_id) == "ap":
        base_damage = _ability_damage(
            snapshot, champion_id, level, item_list, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp, augments,
            apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
        )
    elif apply_ad_axis_ability_damage:
        base_damage = dps_result.weighted_dps + _physical_ability_damage(
            snapshot, champion_id, level, item_list, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp, augments,
            apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
            apply_dual_scaling_split=apply_ad_axis_dual_scaling_split,
        )
    else:
        base_damage = dps_result.weighted_dps
    dps_for_score = base_damage
    ms_utility_mult = 1.0
    ms_utility_note = ""
    if assume_ms_utility:
        # Fail-soft base-MS resolve: a missing champion record or a zeroed
        # movespeed collapses to base_ms 0.0 -> identity multiplier.
        _champ_rec = snapshot.champions.get(str(champion_id)) or {}
        base_ms = float((_champ_rec.get("stats") or {}).get("movespeed", 0.0) or 0.0)
        ms_utility_mult = _ms_utility_multiplier(
            float(dps_result.stats.get("ms", 0.0)), base_ms
        )
        if ms_utility_mult != 1.0:
            dps_for_score = base_damage * ms_utility_mult
            ms_utility_note = (
                f"ms utility ON: dps x{ms_utility_mult:.3f} "
                f"(resolved_ms {float(dps_result.stats.get('ms', 0.0)):.1f} vs "
                f"base_ms {base_ms:.1f}; fraction {_MS_UTILITY_DPS_FRACTION}, "
                f"cap {_MS_UTILITY_DPS_CAP})"
            )
    hybrid_score = alpha_resolved * dps_for_score + beta_resolved * ehp_for_score

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
    if ms_utility_note:
        notes.append(ms_utility_note)

    return HybridResult(
        champion_id=dps_result.champion_id,
        champion_name=dps_result.champion_name,
        level=level,
        item_ids=item_list,
        mode=mode,
        alpha=alpha_resolved,
        beta=beta_resolved,
        alpha_source=alpha_source,
        dps=base_damage,
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
        ms_utility_mult=ms_utility_mult,
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
    # R58 (ENGINE 1.167.0): the candidate build's MS-utility multiplier when
    # assume_ms_utility=True (1.0 on the default path / no bonus MS). The raw
    # delta_dps / new_dps surfaces above keep RAW weighted_dps semantics; the
    # credit lands only in hybrid_delta_pct / hybrid_score.
    ms_utility_mult: float = 1.0

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
            "ms_utility_mult": self.ms_utility_mult,
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
    apply_item_spell_shield: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    assume_item_general_dr: bool = False,
    apply_survival_window: bool = False,
    score_by: str = "blended",
    filter_shared_uniques: bool = True,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    prefer_survivability_by_win: bool = False,
    cost_ceiling: Optional[int] = None,
    target_current_hp_pct: float = 1.0,
    assume_ms_utility: bool = False,
    apply_ad_axis_ability_damage: bool = False,
    # RM-36 (DEFAULT-OFF): MODIFIER of the term above - a dual-scaling row
    # the AP-scaling gate drops is re-entered at its AD SHARE alone.
    # Inert unless apply_ad_axis_ability_damage is also armed.
    apply_ad_axis_dual_scaling_split: bool = False,
    # ENGINE 1.224.0 (R132) seam, forwarded verbatim to ``compute_ehp``. Appended at
    # the END per compute_ehp's stated convention - a mid-signature insert shifts the
    # positional index of every later parameter. Guarded by
    # tests/test_rune_resist_signature_convention_r134.py.
    apply_rune_resist_grants: bool = False,
    rune_ids: Iterable[str | int] = (),
    # R136 (ENGINE 1.225.0): the RM-101 numerator pair, appended AFTER the R132
    # tail per the same convention. Both reuse the existing ``rune_ids`` transport.
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    # R137 (ENGINE 1.226.0, RM-99): the item permanent-HP-stack seam, appended AFTER
    # the R136 pair per the same convention.
    assume_item_health_stacks: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_proc_heal: bool = False,
    # R142 (ENGINE 1.229.0): the RM-101 residual defensive-rune pair, appended at
    # END per the same no-mid-signature-insert convention and passed straight
    # through to compute_ehp. Both ride the existing ``rune_ids`` transport.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # R145 (ENGINE 1.232.0): the OFFENSE-side rune adaptive stat-grant seam,
    # appended at END per the same no-mid-signature-insert convention and passed
    # straight through to compute_dps. Rides the existing ``rune_ids`` transport.
    apply_rune_offense_grants: bool = False,
    # RM-98 (2026-07-24): ranker mirror of the compute_hybrid seam. Appended at
    # END per the same no-mid-signature-insert convention.
    apply_cast_rate_propensity_prior: bool = False,
    # RM-115 p4 (RM-86 L1): the kit-conversion sort gate reaches the BRUISER
    # scorer. Appended at END per the same no-mid-signature-insert convention.
    kit_conversion_strength: float = 0.0,
    # RM-118 (2026-07-29): ranker mirror of the compute_hybrid seam - the
    # wielder HSP ITEM-amp reaches the bruiser build DECISION, not just the
    # scalar. Appended at END. DEFAULT-OFF -> byte-identical.
    assume_hsp_amp: bool = False,
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

    ``target_current_hp_pct`` (R55) is the seam that scales the three genuine
    %-CURRENT-HP procs (BotRK 3153 / Hellfire 4017 / Fulmination 443055) by the
    fraction of max HP the target sits at when the proc lands. It is forwarded
    unchanged to both ``compute_dps`` calls (baseline + each candidate) so the
    bruiser (hybrid) scorer's DPS axis surfaces the same current-HP model the
    mage/assassin scorers already had. Default 1.0 is an identity multiply ->
    byte-identical.

    ``assume_ms_utility`` (R58, ENGINE 1.167.0, DEFAULT-OFF) credits bonus MS
    over base as effective bruiser DPS in BOTH the baseline and every
    candidate via ``_ms_utility_multiplier`` before the normalized
    ``hybrid_delta_pct`` and the ``hybrid_score`` scalar are composed. The
    raw row surfaces (``delta_dps`` / ``new_dps`` / ``delta_ehp`` /
    ``new_ehp``) keep RAW semantics - no double counting with stat-derived
    DPS procs (e.g. Dead Man's Plate Shipwrecker). A shared multiplier
    (baseline and candidate at the same bonus MS) cancels in the normalized
    pct, so only the CANDIDATE's MS delta re-ranks. Default False is
    byte-identical (the OFF branches are the pre-R58 lines verbatim).

    ``apply_ad_axis_ability_damage`` (RM-39 / RM-43, DEFAULT-OFF) adds the
    PHYSICAL-only ability term to the AD branch of BOTH the baseline and every
    candidate - the ranker mirrors of the ``compute_hybrid`` gate. See that
    function for the rationale and ``_physical_ability_damage`` for the
    mandatory damage-type guard. Unlike the R58 MS multiplier this is an
    ADDITIVE term on the damage axis, so it does NOT cancel in the normalized
    ``hybrid_delta_pct``: it raises the baseline denominator (damping every
    candidate's pct) AND credits each candidate's own AD/on-hit scaling
    through ``post_mit``, which is the point - an item that scales the
    champion's abilities is currently invisible to this scorer. The raw row
    surfaces (``new_dps`` / ``delta_dps``) carry the combined value, matching
    the AP branch's existing semantics where ``dps`` is ability damage.
    Default False keeps the pre-seam lines verbatim (byte-identical).

    ``apply_cast_rate_propensity_prior`` (RM-98, DEFAULT-OFF) is the ranker
    mirror of the ``compute_hybrid`` seam - see that function. It is applied to
    the baseline AND every candidate through the same helpers, so the
    normalized ``hybrid_delta_pct`` stays a like-for-like comparison. It does
    NOT cancel in that ratio: the transform is a per-spell reweight (each row
    lifts by its own ``availability / (measured_propensity_reference)`` factor,
    and 10.4 pct of rows clamp), not a uniform scale, and it raises the
    baseline denominator. Default False keeps the pre-seam lines verbatim.
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

    # Damage-axis awareness (see compute_hybrid): AP champs score on ability DPS.
    axis = _damage_axis(snapshot, champion_id)

    baseline_dps_result = compute_dps(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        phase=phase, augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
        apply_rune_offense_grants=apply_rune_offense_grants,
        rune_ids=rune_ids,
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
        apply_item_spell_shield=apply_item_spell_shield,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_rune_resist_grants=apply_rune_resist_grants,
        rune_ids=rune_ids,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        assume_hsp_amp=assume_hsp_amp,
        assume_item_health_stacks=assume_item_health_stacks,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_proc_heal=assume_item_proc_heal,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        assume_item_general_dr=assume_item_general_dr,
        apply_survival_window=apply_survival_window,
        **_ehp_kwargs_baseline,
    )
    # RM-39/RM-43 (DEFAULT-OFF): ranker-baseline mirror of the compute_hybrid
    # gate. OFF binds the SAME raw value (a name bind, not a float op).
    # RM-98 (DEFAULT-OFF): same prior on the ranker baseline as on the
    # candidates below, so the delta_pct comparison stays like-for-like.
    if axis == "ap":
        baseline_dps = _ability_damage(
            snapshot, champion_id, level, current_ids, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp,
            augments, target_current_hp_pct,
            apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
        )
    elif apply_ad_axis_ability_damage:
        baseline_dps = baseline_dps_result.weighted_dps + _physical_ability_damage(
            snapshot, champion_id, level, current_ids, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp,
            augments, target_current_hp_pct,
            apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
            apply_dual_scaling_split=apply_ad_axis_dual_scaling_split,
        )
    else:
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
    # R58 (ENGINE 1.167.0, DEFAULT-OFF): resolve the champion's base MS ONCE
    # and derive the baseline MS-utility multiplier; the per-candidate loop
    # below reuses _ms_base. OFF binds nothing - the else keeps the pre-R58
    # baseline_hybrid line verbatim (byte-identical contract).
    if assume_ms_utility:
        _ms_champ_rec = snapshot.champions.get(str(champion_id)) or {}
        _ms_base = float((_ms_champ_rec.get("stats") or {}).get("movespeed", 0.0) or 0.0)
        baseline_ms_mult = _ms_utility_multiplier(
            float(baseline_dps_result.stats.get("ms", 0.0)), _ms_base
        )
        baseline_dps_eff = baseline_dps * baseline_ms_mult
        baseline_hybrid = (
            alpha_resolved * baseline_dps_eff + beta_resolved * baseline_ehp_for_score
        )
    else:
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
        # Ranged-only purchasability gate: drop Runaan's (+ alias) for a melee
        # bruiser - the shop blocks the purchase (2026-07-02).
        champion_is_melee=_champion_is_melee(champ_rec, augments),
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
                target_current_hp_pct=target_current_hp_pct,
                phase=phase, augments=augments,
                apply_mode_modifiers=apply_mode_modifiers,
                apply_rune_offense_grants=apply_rune_offense_grants,
                rune_ids=rune_ids,
            )
            # RM-39/RM-43 (DEFAULT-OFF): per-candidate mirror of the same gate.
            # OFF binds the SAME raw value (a name bind, not a float op).
            # RM-98 (DEFAULT-OFF): per-candidate mirror of the prior.
            if axis == "ap":
                scored_damage = _ability_damage(
                    snapshot, champion_id, level, new_build, mode,
                    target_armor, target_mr, target_max_hp, target_bonus_hp,
                    augments, target_current_hp_pct,
                    apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
                )
            elif apply_ad_axis_ability_damage:
                scored_damage = dps_scored.weighted_dps + _physical_ability_damage(
                    snapshot, champion_id, level, new_build, mode,
                    target_armor, target_mr, target_max_hp, target_bonus_hp,
                    augments, target_current_hp_pct,
                    apply_cast_rate_propensity_prior=apply_cast_rate_propensity_prior,
                    apply_dual_scaling_split=apply_ad_axis_dual_scaling_split,
                )
            else:
                scored_damage = dps_scored.weighted_dps
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
                apply_item_spell_shield=apply_item_spell_shield,
                apply_item_mana_health=apply_item_mana_health,
                apply_item_resist_grants=apply_item_resist_grants,
                apply_rune_resist_grants=apply_rune_resist_grants,
                rune_ids=rune_ids,
                apply_rune_health_grants=apply_rune_health_grants,
                apply_rune_hsp_amp=apply_rune_hsp_amp,
        assume_hsp_amp=assume_hsp_amp,
                assume_item_health_stacks=assume_item_health_stacks,
                apply_rune_flat_mitigation=apply_rune_flat_mitigation,
                assume_item_proc_heal=assume_item_proc_heal,
                apply_rune_self_heal=apply_rune_self_heal,
                apply_rune_shield_grants=apply_rune_shield_grants,
                apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
                assume_item_general_dr=assume_item_general_dr,
                apply_survival_window=apply_survival_window,
                **_ehp_kwargs_scored,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta_dps = scored_damage - baseline_dps
        delta_ehp = ehp_scored.blended_ehp - baseline_ehp
        cc_delta_ehp = ehp_scored.cc_blended_ehp - baseline_ehp_result.cc_blended_ehp
        # Item 237: the active EHP metric drives the delta_pct sort key. Default
        # "blended" uses the PRE-cc delta (byte-identical); "cc_blended" uses the
        # CC-lockdown-adjusted delta (+ tenacity) so a tenacity item rises vs a
        # non-saturating CC comp - the bruiser mirror of the item-236 tank mode.
        active_delta_ehp = cc_delta_ehp if score_by == "cc_blended" else delta_ehp
        ehp_scored_for_score = (
            ehp_scored.cc_blended_ehp
            if enemy_champions_tuple
            else ehp_scored.blended_ehp
        )
        # R58 (ENGINE 1.167.0, DEFAULT-OFF): when ON, the candidate build's
        # MS-utility multiplier rescales the DPS term of BOTH the normalized
        # delta (numerator AND normalizer run on the effective baseline, so a
        # multiplier shared with the baseline cancels) and the hybrid_score
        # scalar. delta_dps above stays RAW - no double counting with
        # stat-derived procs. The else branch is the pre-R58 text verbatim.
        cand_ms_mult = 1.0
        if assume_ms_utility:
            cand_ms_mult = _ms_utility_multiplier(
                float(dps_scored.stats.get("ms", 0.0)), _ms_base
            )
            cand_dps_eff = scored_damage * cand_ms_mult
            delta_pct = _hybrid_delta_pct(
                cand_dps_eff - baseline_dps_eff, active_delta_ehp,
                baseline_dps_eff, active_baseline_ehp,
                alpha_resolved, beta_resolved,
            )
            new_hybrid_score = (
                alpha_resolved * cand_dps_eff
                + beta_resolved * ehp_scored_for_score
            )
        else:
            delta_pct = _hybrid_delta_pct(
                delta_dps, active_delta_ehp, baseline_dps, active_baseline_ehp,
                alpha_resolved, beta_resolved,
            )
            new_hybrid_score = (
                alpha_resolved * scored_damage
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
            new_dps=scored_damage,
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
            ms_utility_mult=cand_ms_mult,
        ))

    # RM-115 p4 / RM-86 L1 kit-conversion gate (DEFAULT-OFF). The registry is
    # consulted ONLY when the lever is strictly positive, so 0.0 performs no
    # lookup and no arithmetic and is provably byte-identical.
    _conv = (
        kit_conversion(str(champion_id), champ_rec)
        if kit_conversion_strength > 0.0 else None
    )
    # The BLENDED objective, not the bare damage axis - ds.hybrid scores
    # alpha*dps + beta*ehp, so health and resists are ON-axis here. See
    # kit_conversion._OFF_AXIS_KEYS["hybrid_ad"] / ["hybrid_ap"].
    _conv_objective = f"hybrid_{axis}" if _conv is not None else ""
    _conv_memo: dict[str, float] = {}

    def _conv_key(value: float, item_id: str) -> float:
        """Sort-only view of ``value`` - never mutates the row itself.

        Only ever LOWERS: a non-positive value is returned unchanged, because
        scaling a negative number toward zero would RAISE its rank.
        """
        if _conv is None or value <= 0.0:
            return value
        factor = _conv_memo.get(item_id)
        if factor is None:
            factor = conversion_factor(
                _conv, item_id, snapshot.items.get(item_id) or {},
                kit_conversion_strength, _conv_objective,
            )
            _conv_memo[item_id] = factor
        return value * factor

    def _base_key(r: HybridRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (
                _conv_key(r.hybrid_per_1k_gold, r.item_id),
                _conv_key(r.hybrid_delta_pct, r.item_id),
            )
        return (
            _conv_key(r.hybrid_delta_pct, r.item_id),
            _conv_key(r.hybrid_per_1k_gold, r.item_id),
        )

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
    # RM-329: this ranker filters its pool through ``_filter_candidates`` ->
    # ``_is_legal_in_mode`` exactly as ``rank_items`` does, so it owes the same
    # item-legality provenance line. Without it an unrecognised mode silently
    # returned an UNFILTERED pool - map-illegal ids leaking into a mode-legal
    # answer - with nothing in the payload saying so.
    #
    # ``mode`` is NOT ``canonical_mode``-folded in this function (unlike
    # ``rank_items`` / ``rank_items_by_burst``), and ``result.mode`` deliberately
    # keeps echoing the caller's raw spelling. The FILTER is case-insensitive
    # (``_is_legal_in_mode`` upper-cases), so the note must be built from the
    # RESOLVED spelling or it prints the pre-RM-325 falsehood: "mode=aram not in
    # MODE_MAP_ID" over a pool the map-12 filter had in fact been applied to.
    # ``canonical_mode`` is read here ONLY to build the string - folding ``mode``
    # itself would move what the scorers below are handed, which is a scoring
    # change and out of scope for a notes-only row.
    notes.append(mode_filter_note(canonical_mode(mode)))
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
