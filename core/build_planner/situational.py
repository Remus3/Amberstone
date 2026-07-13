"""core.build_planner.situational - WP-C3 counter-build situational fit.

Fills the WP-C3 stub at core/build_planner/scoring.py:321. Given an enemy
threat profile + the current build, scores how well the build COUNTERS the
enemy composition (resist-vs-damage-split, antiheal de-dup, fed-enemy resist
override, HP+resist vs penetration, pen TYPE from the kill-target armor/MR,
tenacity vs CC) plus the operator-deviation re-anchor helper.

PURITY boundary (mirrors scoring.py):

  * ``classify_item`` / ``situational_fit`` / ``reanchor_plan`` are PURE - the
    only side effect is a lazy ONE-TIME read of data/meta/ddragon_items.json
    for the item catalog (the same file enemy_aware_stats already reads). No DS
    engine, no liveclient, no network.
  * ``build_enemy_profile`` is the ONLY impure function (a dashboard tick
    builder) and is NEVER reached from score_build. It may import
    core.defensive_picks / core.enemy_aware_stats / core.liveclient_cache.

Item classification is patch-stable by construction:

  * armor / magic_resist / health: DATA-driven from the FlatArmorMod /
    FlatSpellBlockMod / FlatHPPoolMod flats (reuses
    enemy_aware_stats._load_stat_index).
  * tenacity / armor-pen-presence / magic-pen-presence: TAG-driven from the
    catalog 'tags' (Tenacity / ArmorPenetration / MagicPenetration).
  * antiheal (Grievous Wounds) + the lethality-vs-percent-armor-pen split: no
    catalog tag captures these, so they are NAME-driven from a small curated
    roster matched on the RESOLVED catalog name - stable across the 4-digit and
    22-prefixed id keyspaces with no alias map.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.enemy_aware_stats import _load_stat_index

# --------------------------------------------------------------------------- #
# Curated NAME rosters (every name VERIFIED present in the catalog this
# session; ids cited for traceability). Matched on the RESOLVED catalog name so
# the 4-digit ("3033") and 22-prefixed ("223033") ids classify identically with
# no alias map. All apostrophes are straight ASCII U+0027.
# --------------------------------------------------------------------------- #
_ANTIHEAL_NAMES = frozenset({
    "Executioner's Calling",   # 3123  tags=['Damage']  (no antiheal tag)
    "Mortal Reminder",         # 3033, 223033  (ALSO percent-armor-pen)
    "Morellonomicon",          # 3165, 223165
    "Chempunk Chainsword",     # 6609, 226609
    "Oblivion Orb",            # 3916  tags=['SpellDamage']  (no antiheal tag)
})
_PCT_ARMOR_PEN_NAMES = frozenset({
    "Lord Dominik's Regards",  # 3036, 223036
    "Mortal Reminder",         # 3033, 223033  (in BOTH rosters by design)
    "Serylda's Grudge",        # 6694, 226694
})
_PCT_MAGIC_PEN_NAMES = frozenset({
    "Void Staff",              # 3135, 223135
    "Cryptbloom",              # 3137, 223137
})

# --------------------------------------------------------------------------- #
# Scoring constants. Magnitudes are tunable - the tests assert ONLY ordinal
# relations / margins, never absolute floats. See the per-criterion notes in
# situational_fit for what each weight gates.
# --------------------------------------------------------------------------- #
W_RESIST = 0.45
W_AH = 0.6
W_FED = 0.55
W_PEN_MIX = 0.5
W_PEN = 0.55
W_TEN = 0.5
HEAL_THRESHOLD = 2
LETH_CUT = 100.0
PCT_CUT = 100.0
MR_CUT = 60.0
CC_CUT = 5.0
PEN_DAMP = 0.5
SAT = 1.5
HP_SAT = 800.0   # soft-saturation HP for the C4 mix reward (~half-credit @800)

_ITEMS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "meta" / "ddragon_items.json"
_CATALOG: dict | None = None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _load_catalog() -> dict:
    """Read ddragon_items.json ONCE -> {id_str: {"name", "tags": frozenset}}.

    Reuses the enemy_aware_stats file shape (items under the ``data`` key, both
    keyspaces present). Any load failure degrades to an empty dict so every
    classify_item returns an all-False / zero-float ItemProps (graceful).
    """
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    out: dict = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for item_id, entry in data.items():
            out[str(item_id)] = {
                "name": entry.get("name", "") or "",
                "tags": frozenset(entry.get("tags") or ()),
            }
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - any parse failure -> empty catalog
        pass
    _CATALOG = out
    return out


# --------------------------------------------------------------------------- #
# Dataclasses (LOCKED surface; frozen throughout).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EnemyProfile:
    ad_share: float = 0.0          # 0..1 physical damage share
    ap_share: float = 0.0          # 0..1 magic damage share
    true_share: float = 0.0        # 0..1 true damage share (counters nothing)
    kill_target_armor: float = 0.0  # armor of the priority kill target (NOT avg)
    kill_target_mr: float = 0.0
    enemy_pen: float = 0.0         # 0..1 how much the enemy stacks penetration
    heal_sources: int = 0          # count of enemy heal / sustain sources
    cc_score: float = 0.0          # 0..10 enemy CC load
    burst_threat: float = 0.0      # 0..10
    tank_pressure: float = 0.0     # 0..10
    fed: bool = False              # fed-enemy / threat override -> resist NOW


@dataclass(frozen=True)
class AllyState:
    has_antiheal: bool = False     # an ally already owns a Grievous-Wounds item


@dataclass(frozen=True)
class ItemProps:
    is_armor: bool = False
    is_magic_resist: bool = False
    is_health: bool = False
    is_antiheal: bool = False
    is_lethality: bool = False
    is_percent_armor_pen: bool = False
    is_percent_magic_pen: bool = False
    is_tenacity: bool = False
    armor: float = 0.0
    mr: float = 0.0
    hp: float = 0.0


@dataclass(frozen=True)
class ReanchorResult:
    deviated: bool
    anchored_ids: tuple


# --------------------------------------------------------------------------- #
# classify_item - patch-stable item -> ItemProps.
# --------------------------------------------------------------------------- #
def classify_item(item_id) -> ItemProps:
    """Classify one item id into ItemProps (int or str id both accepted).

    Stat floats come from the shared stat index (absent -> 0.0, correct).
    Categorical flags come from the full catalog: flats for resist/HP, tags for
    tenacity + pen-presence, curated NAME rosters for antiheal + the
    lethality-vs-percent-armor-pen split. An unknown id -> all-False ItemProps.
    """
    iid = str(item_id)
    stat = _load_stat_index().get(iid) or {}
    armor = float(stat.get("armor", 0.0))
    mr = float(stat.get("mr", 0.0))
    hp = float(stat.get("hp", 0.0))

    entry = _load_catalog().get(iid)
    if entry is None:
        return ItemProps()
    name = entry["name"]
    tags = entry["tags"]

    is_armor = armor > 0.0
    is_magic_resist = mr > 0.0
    is_health = hp > 0.0
    is_tenacity = "Tenacity" in tags
    is_antiheal = name in _ANTIHEAL_NAMES
    is_percent_armor_pen = name in _PCT_ARMOR_PEN_NAMES
    is_percent_magic_pen = name in _PCT_MAGIC_PEN_NAMES
    # lethality = an ArmorPenetration-tagged item that is NOT a %armor-pen item.
    is_lethality = ("ArmorPenetration" in tags) and not is_percent_armor_pen

    return ItemProps(
        is_armor=is_armor,
        is_magic_resist=is_magic_resist,
        is_health=is_health,
        is_antiheal=is_antiheal,
        is_lethality=is_lethality,
        is_percent_armor_pen=is_percent_armor_pen,
        is_percent_magic_pen=is_percent_magic_pen,
        is_tenacity=is_tenacity,
        armor=armor,
        mr=mr,
        hp=hp,
    )


# --------------------------------------------------------------------------- #
# situational_fit - the WP-C3 0..1 counter-build term.
# --------------------------------------------------------------------------- #
def situational_fit(build_ids, enemy_profile, ally_state=None, *, stage="mid") -> float:
    """Score how well ``build_ids`` counters ``enemy_profile`` -> [0, 1).

    Sum of non-negative per-criterion reward terms, lightly stage-tilted, then
    squashed by raw / (raw + SAT). raw == 0 -> EXACTLY 0.0 so an all-zero
    EnemyProfile reproduces the old stub. The squash is monotone in raw so it
    preserves every '>' acceptance comparison and never saturates a C-test.
    """
    ids = [str(i) for i in (build_ids or [])]
    props = [classify_item(i) for i in ids]
    ep = enemy_profile
    a = AllyState() if ally_state is None else ally_state

    # C1 resist vs enemy damage split. true_share rewards nothing (uncounterable
    # by resist). Mismatched resist self-zeroes via its share multiplier; both
    # shares 0 -> no blind reward. resist_value dampens flat resist under enemy
    # penetration (feeds the C4 contrast against a HP+resist mix). Resist credit
    # is PRESENCE-based (cap at 1) so swapping a 2nd resist item for an HP item
    # does not out-score the mix on C1 - the HP-vs-resist trade lives in C4.
    has_armor = any(p.is_armor for p in props)
    has_mr = any(p.is_magic_resist for p in props)
    resist_value = 1.0 - PEN_DAMP * _clamp01(ep.enemy_pen)
    r_resist = W_RESIST * (
        (1.0 if has_armor else 0.0) * ep.ad_share
        + (1.0 if has_mr else 0.0) * ep.ap_share
    ) * resist_value

    # C2 antiheal - boolean-first (a 2nd antiheal adds nothing); de-duped when an
    # ally already owns one; not warranted below the heal-source threshold.
    has_ah = any(p.is_antiheal for p in props)
    warranted = ep.heal_sources >= HEAL_THRESHOLD
    r_antiheal = W_AH if (has_ah and warranted and not a.has_antiheal) else 0.0

    # C3 fed override - ADDITIVE flat (not a multiplier), so the resist-build vs
    # no-resist margin is strictly wider when fed (resist gains W_FED, the
    # pure-damage build gains 0). Gated on owning ANY survival stat.
    any_survival = any(p.is_armor or p.is_magic_resist or p.is_health for p in props)
    r_fed = W_FED if (ep.fed and any_survival) else 0.0

    # C4 HP + resist vs penetration - pen shreds resist, not raw HP, so a mix
    # beats pure resist once enemy_pen is high. The reward scales with TOTAL HP
    # (soft-saturated) so the more-HP build wins under pen even when both carry
    # some HP. Collapses to 0 at enemy_pen == 0 (the pen multiplier), so two
    # builds tie at zero pen regardless of HP magnitude.
    has_resist = any(p.is_armor or p.is_magic_resist for p in props)
    total_hp = sum(p.hp for p in props)
    hp_factor = total_hp / (total_hp + HP_SAT) if total_hp > 0 else 0.0
    r_mix = W_PEN_MIX * _clamp01(ep.enemy_pen) * hp_factor if has_resist else 0.0

    # C5 pen TYPE from the kill-target (NOT team avg), boolean-first so a 2nd
    # %pen is redundant. Squishy kill target -> lethality; tanky -> %armor-pen;
    # the wrong type for the regime earns 0. Unknown (0) armor -> squishy regime.
    has_leth = any(p.is_lethality for p in props)
    has_pct_armor = any(p.is_percent_armor_pen for p in props)
    has_pct_magic = any(p.is_percent_magic_pen for p in props)
    if ep.kill_target_armor < LETH_CUT:
        r_pa = W_PEN if has_leth else 0.0
    elif ep.kill_target_armor >= PCT_CUT:
        r_pa = W_PEN if has_pct_armor else 0.0
    else:  # pragma: no cover - LETH_CUT == PCT_CUT leaves no gap
        r_pa = 0.0
    r_pm = (W_PEN / 2.0) if (ep.kill_target_mr > MR_CUT and has_pct_magic) else 0.0
    r_pen = r_pa + r_pm

    # C6 tenacity vs CC - rewarded only above the CC threshold; low CC -> 0.
    has_ten = any(p.is_tenacity for p in props)
    r_ten = W_TEN * (ep.cc_score / 10.0) if (has_ten and ep.cc_score >= CC_CUT) else 0.0

    # Stage tilt - light multiplier on already-bounded terms; keeps the band.
    survival = r_resist + r_fed + r_mix
    pen = r_pen
    rest = r_antiheal + r_ten
    if stage == "early":
        survival *= 1.0
        pen *= 0.8
    elif stage == "late":
        survival *= 0.9
        pen *= 1.1
    # mid (and any unknown stage): *= 1.0 each.
    raw = survival + pen + rest

    # Smooth squash -> [0, 1); raw == 0 -> exactly 0.0 (stub-equivalent);
    # monotone in raw -> preserves every ordering.
    return raw / (raw + SAT) if raw > 0.0 else 0.0


# --------------------------------------------------------------------------- #
# reanchor_plan - C7 operator-deviation re-anchor (PURE, no I/O).
# --------------------------------------------------------------------------- #
def reanchor_plan(planned_ids, observed_ids) -> ReanchorResult:
    """Re-anchor a plan to the operator's ACTUAL purchase prefix.

    ``deviated`` is True when ``observed`` is not an order-preserving prefix of
    ``planned``. ``anchored_ids`` keeps the observed purchases verbatim as the
    fixed prefix, then continues with the remaining planned items in plan order
    (no id duplicated). int / str ids are coerced to str.
    """
    planned = [str(i) for i in (planned_ids or [])]
    observed = [str(i) for i in (observed_ids or [])]
    deviated = False
    for i, o in enumerate(observed):
        if i >= len(planned) or planned[i] != o:
            deviated = True
            break
    owned = set(observed)
    tail = [p for p in planned if p not in owned]
    anchored = tuple(observed) + tuple(tail)
    return ReanchorResult(deviated=deviated, anchored_ids=anchored)


# --------------------------------------------------------------------------- #
# counter_build_hints - surface the C1-C7 counter-build criteria the enemy
# profile WARRANTS as discrete overlay hints (PURE, UI transport only). This is
# the per-criterion companion to situational_fit's scalar: it reuses the SAME
# classify_item + gating constants and adds ZERO DS math. A criterion emits a
# hint ONLY when the profile actively warrants it; ``satisfied`` flags whether
# the current build already owns the counter. The scalar situational_fit stays
# LOCKED - this is a read-only projection of the same gates for the UI.
# --------------------------------------------------------------------------- #
RESIST_HINT_CUT = 0.55   # dominant damage share that warrants a resist hint
PEN_HINT_CUT = 0.5       # enemy penetration that warrants the HP-vs-pen hint
HP_HINT_FLOOR = 300.0    # total build HP that counts the HP-vs-pen hint satisfied
PEN_SAT_ITEMS = 4.0      # >=2 enemy penetration items -> enemy_pen crosses PEN_HINT_CUT (C4 warrant)


@dataclass(frozen=True)
class CounterHint:
    criterion: str        # resist antiheal fed hp_vs_pen pen_type tenacity
    satisfied: bool       # does the current build ALREADY carry the counter?
    severity: str         # "high" or "med"
    label: str            # short ASCII chip label eg "ARMOR"
    detail: str           # one-line ASCII reason eg "enemy 78% physical"
    suggest_class: str    # armor mr antiheal hp lethality pct_armor_pen etc


def counter_build_hints(build_ids, enemy_profile, ally_state=None, *, stage="mid") -> tuple:
    """Surface the C1-C7 counter-build criteria the enemy_profile WARRANTS.

    Emit a hint ONLY for a criterion the profile actively warrants (mirrors the
    situational_fit gates EXACTLY, reusing classify_item + the module
    constants). ``satisfied`` = the current build already owns the counter.
    Order: severity high first, then criterion order
    resist -> antiheal -> fed -> hp_vs_pen -> pen_type -> tenacity. An all-zero
    EnemyProfile returns an EMPTY tuple (honest no-data). ``stage`` is accepted
    for signature parity with situational_fit and does not change the hint set.
    """
    ids = [str(i) for i in (build_ids or [])]
    props = [classify_item(i) for i in ids]
    ep = enemy_profile
    a = AllyState() if ally_state is None else ally_state
    _ = stage  # accepted for parity; the warranted hint set is stage-invariant.

    has_armor = any(p.is_armor for p in props)
    has_mr = any(p.is_magic_resist for p in props)
    has_antiheal = any(p.is_antiheal for p in props)
    has_lethality = any(p.is_lethality for p in props)
    has_pct_armor_pen = any(p.is_percent_armor_pen for p in props)
    has_pct_magic_pen = any(p.is_percent_magic_pen for p in props)
    has_tenacity = any(p.is_tenacity for p in props)
    has_resist = any(p.is_armor or p.is_magic_resist for p in props)
    any_survival = any(p.is_armor or p.is_magic_resist or p.is_health for p in props)
    total_hp = sum(p.hp for p in props)

    hints: list = []

    # C1 resist vs enemy damage split - warranted once the dominant damage
    # share clears RESIST_HINT_CUT. true_share counters nothing so it never
    # warrants; the LARGER of ad/ap picks the resist type (ad ties -> armor).
    dom = max(ep.ad_share, ep.ap_share)
    if dom >= RESIST_HINT_CUT:
        sev = "high" if dom >= 0.70 else "med"
        if ep.ad_share >= ep.ap_share:
            hints.append(CounterHint(
                criterion="resist", satisfied=has_armor, severity=sev,
                label="ARMOR",
                detail=f"enemy {round(ep.ad_share * 100)}% physical",
                suggest_class="armor"))
        else:
            hints.append(CounterHint(
                criterion="resist", satisfied=has_mr, severity=sev,
                label="MR",
                detail=f"enemy {round(ep.ap_share * 100)}% magic",
                suggest_class="mr"))

    # C2 antiheal - warranted at/above the heal-source threshold and only when
    # no ally already owns a Grievous-Wounds item (de-dup mirrors the scalar).
    if ep.heal_sources >= HEAL_THRESHOLD and not a.has_antiheal:
        hints.append(CounterHint(
            criterion="antiheal", satisfied=has_antiheal, severity="high",
            label="ANTIHEAL",
            detail=f"{ep.heal_sources} enemy heal sources",
            suggest_class="antiheal"))

    # C3 fed override - a fed enemy warrants itemizing ANY defensive stat now.
    if ep.fed:
        hints.append(CounterHint(
            criterion="fed", satisfied=any_survival, severity="high",
            label="SURVIVE",
            detail="fed enemy - itemize defense",
            suggest_class="resist"))

    # C4 HP vs penetration - warranted only when the build already carries the
    # resist the enemy is actively shredding (pen shreds resist, not raw HP).
    if ep.enemy_pen >= PEN_HINT_CUT and has_resist:
        hints.append(CounterHint(
            criterion="hp_vs_pen", satisfied=(total_hp >= HP_HINT_FLOOR),
            severity="med", label="HP",
            detail="enemy stacks penetration - add HP",
            suggest_class="hp"))

    # C5 pen TYPE from the kill target - two INDEPENDENT branches. The armor
    # branch is warranted ONLY when the kill-target armor is KNOWN (> 0); 0
    # means unknown, so it emits nothing (honest no-data). LETH_CUT == PCT_CUT
    # so a known armor always resolves to exactly one of pct-pen / lethality.
    kt_armor = ep.kill_target_armor
    if kt_armor > 0:
        if kt_armor >= PCT_CUT:
            hints.append(CounterHint(
                criterion="pen_type", satisfied=has_pct_armor_pen,
                severity="med", label="ARMOR PEN",
                detail=f"kill target {int(kt_armor)} armor",
                suggest_class="pct_armor_pen"))
        elif kt_armor < LETH_CUT:
            hints.append(CounterHint(
                criterion="pen_type", satisfied=has_lethality,
                severity="med", label="LETHALITY",
                detail=f"kill target {int(kt_armor)} armor",
                suggest_class="lethality"))
    if ep.kill_target_mr > MR_CUT:
        hints.append(CounterHint(
            criterion="pen_type", satisfied=has_pct_magic_pen,
            severity="med", label="MAGIC PEN",
            detail=f"kill target {int(ep.kill_target_mr)} MR",
            suggest_class="pct_magic_pen"))

    # C6 tenacity vs CC - warranted at/above the CC threshold.
    if ep.cc_score >= CC_CUT:
        hints.append(CounterHint(
            criterion="tenacity", satisfied=has_tenacity, severity="med",
            label="TENACITY",
            detail=f"enemy CC {round(ep.cc_score)}/10",
            suggest_class="tenacity"))

    # Order: severity high first, then the criterion append order (Python's
    # sort is stable, so within a severity the criterion order is preserved).
    hints.sort(key=lambda h: 0 if h.severity == "high" else 1)
    return tuple(hints)


# --------------------------------------------------------------------------- #
# build_enemy_profile - IMPURE dashboard tick builder. NEVER called by
# score_build. The FORMULA here is advisory; only the EnemyProfile return type
# is locked. Imports are engine-free at module scope (defensive_picks lazily
# HTTP-imports the DS client only in its EHP path, which this does NOT call).
# --------------------------------------------------------------------------- #
def build_enemy_profile(
    enemy_champions,
    enemy_items_by_player=None,
    *,
    level=None,
    heal_sources=0,
    cc_score=0.0,
    fed=False,
    ad_share=None,
    ap_share=None,
) -> EnemyProfile:
    """Build an EnemyProfile from live enemy comp + items (dashboard tick).

    Derives ad_share / ap_share from the defensive_picks threat profile when
    not supplied; kill_target_armor / kill_target_mr from the WORST-CASE enemy
    (aggregator="max"), NOT the team average; enemy_pen (advisory) from the count
    of enemy penetration items saturated at PEN_SAT_ITEMS. cc_score /
    heal_sources / fed come from the caller (no live CC API exists). Network-free
    given a snapshot. With no enemy items supplied, enemy_pen / kill_target_*
    stay 0.0 (the champion-only path).
    """
    from core.defensive_picks import compute_threat_profile
    from core.enemy_aware_stats import compute_target_stats_from_items

    champs = list(enemy_champions or [])
    items = list(enemy_items_by_player or [])

    if ad_share is None or ap_share is None:
        threat = compute_threat_profile(champs, items or None)
        ad = float(threat.get("ad_threat", 0.0) or 0.0)
        ap = float(threat.get("ap_threat", 0.0) or 0.0)
        denom = ad + ap
        if ad_share is None:
            ad_share = (ad / denom) if denom > 0 else 0.0
        if ap_share is None:
            ap_share = (ap / denom) if denom > 0 else 0.0
        burst = float(threat.get("burst_threat", 0.0) or 0.0)
        tank = float(threat.get("tank_pressure", 0.0) or 0.0)
    else:
        burst = 0.0
        tank = 0.0

    kt_armor = 0.0
    kt_mr = 0.0
    if items:
        stats = compute_target_stats_from_items(
            items, aggregator="max",
            enemy_champions=champs or None, level=level,
        )
        kt_armor = float(stats.get("target_armor", 0.0) or 0.0)
        kt_mr = float(stats.get("target_mr", 0.0) or 0.0)

    # enemy_pen (advisory) - count enemy penetration items (lethality OR
    # percent armor/magic pen) and saturate at PEN_SAT_ITEMS so >=2 clears
    # PEN_HINT_CUT (0.5) and warrants the C4 hp_vs_pen hint. The None / empty
    # items path stays enemy_pen=0.0 EXACTLY (today's champion-only behaviour).
    enemy_pen = 0.0
    if items:
        pen_count = 0
        for player_items in items:
            for iid in (player_items or []):
                p = classify_item(iid)
                if p.is_lethality or p.is_percent_armor_pen or p.is_percent_magic_pen:
                    pen_count += 1
        enemy_pen = min(1.0, pen_count / PEN_SAT_ITEMS)

    return EnemyProfile(
        ad_share=float(ad_share),
        ap_share=float(ap_share),
        kill_target_armor=kt_armor,
        kill_target_mr=kt_mr,
        enemy_pen=float(enemy_pen),
        heal_sources=int(heal_sources),
        cc_score=float(cc_score),
        burst_threat=burst,
        tank_pressure=tank,
        fed=bool(fed),
    )
