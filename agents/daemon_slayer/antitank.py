"""Anti-tank / %HP-damage + resist-shred scorer (ENGINE 1.117.0, item 308).

The sixteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303) /
ally-amplification (item 304) / the six archetype scorers. It quantifies how well
a champion's OWN KIT melts a high-HP / high-resist target - the anti-tank
dimension the prior fifteen axes never measured. The DPS / burst scorers measure
raw damage against a fixed dummy; none answers "does this champion's kit care how
much health and armor the enemy stacked". This one does.

Every kind scored here gets STRONGER the tankier the target is: damage that
scales with the target's health POOL (max / current health), or effects that
lower the target's RESISTS so every source hits harder (shred, %resist
penetration). Pure execute / %-missing-health damage is deliberately EXCLUDED -
it does almost nothing to a full-health tank and only ramps as the target dies,
so it is a finisher, the opposite of an anti-tank tool.

A high score means a champion built to shred tanks: the %max-HP carries (Vayne /
Kog'Maw / Gwen / Fiora / Varus / Rumble / Udyr), the resist-shredders (Trundle /
Rell / Nasus / KogMaw Q / Rumble E), the %current-HP threats (Dr. Mundo /
Viego). A low score (or zero) means a champion whose damage does not scale with
the target's health pool or resists - a flat-damage burst mage, a raw-AD bruiser,
most of the roster.

Purely ADDITIVE: a new standalone scorer and a new ``/anti-tank`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a live
draft / teamfight / itemization coach surface is the separate Phase-D step.

Like the sustain / zone-control / ally-amplification axes (and unlike the
full-roster threat-range / wave-clear / objective-damage axes), this axis is
SELECTIVE: a champion whose damage does not scale with enemy health or resists
carries no registry rows and scores ``0.0`` (the empty-result contract).

Model (each anti-tank MECHANISM a champion owns contributes a kind-weighted,
cadence-scaled value; the headline is their sum):
  * a per-(champion, source, kind) ``AntiTankEntry`` tags one mechanism with a
    ``kind`` (key of ``_ANTITANK_KIND_WEIGHT`` - WHAT melts the tank: MAX_HP /
    SHRED / CURRENT_HP / PERCENT_PEN), a ``cadence`` (key of
    ``_ANTITANK_CADENCE_MULT`` - how continuously it applies through a fight:
    SUSTAINED / PERIODIC / BURST), a ``magnitude`` (0..1 how strongly / reliably
    this mechanism melts a tank), and a ``conditional`` flag (needs the ult up, a
    charge / stack, or a specific target state). A single ability can carry two
    kinds (Trundle R is a %max-HP drain AND a resist steal; Vi W / Yorick E / Sion
    E deal %max-HP AND reduce armor), so a champion may hold two rows on one slot.
  * ``compute_antitank`` folds every mechanism into a single ``antitank_score`` =
    sum of ``kind_weight * cadence_mult * magnitude`` (times the conditional
    midpoint when gated). ``top_kind`` labels the kind of the single highest-value
    mechanism (the champion's strongest anti-tank tool); ``shreds_resist`` is True
    when any SHRED or PERCENT_PEN mechanism contributes (the identity a draft /
    itemization consumer keys on - does this champion lower the tank's resists so
    the whole team hits harder, not just herself).

Kinds, cadences and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-308 roster fan-out.

P3.2 (item 315) schema lift: each ``AntiTankEntry`` may carry optional
``ap_ratio`` / ``ad_ratio`` coefficients and ``compute_antitank`` accepts an
optional ``stats`` (a ``ResolvedStats`` or ``.get`` mapping). When a seeded row
meets injected stats, its effective magnitude scales by
``base + ap * ap_ratio + ad * ad_ratio`` - so a %HP mechanism that genuinely
carries a caster-stat term grows with the build, while the pure %max-HP rows
(ratio 0.0, e.g. Vayne W / Fiora P) stay static and every no-stats call is
byte-identical to item 308. The seeded set is VERIFIED against
``champion_abilities.json`` (only rows whose %HP / current-HP block carries a
"% per 100 AP" or "% per 100 bonus AD" term): AP rows Gwen P / Kog'Maw W /
Varus W / Malzahar R, bonus-AD rows Vi W / Camille W / Udyr Q (the first real
AD-path seeds). The per-row slope is a deliberately conservative 0.0004
reliability term, not a literal in-game damage ratio.

R17 (ENGINE 1.151.0) schema lift: each ``AntiTankEntry`` may carry optional
``ramp_lo`` / ``ramp_hi`` endpoints (the verbatim "lo% : hi% (based on level)"
%max-HP figures), and ``compute_antitank`` accepts an optional ``level``. The
hand-tuned magnitude encodes the LATE-game (max-ramp) reliability; when a level is
injected, a ramp-seeded row's effective magnitude scales by
``_level_ramp_factor`` = ``lerp(ramp_lo, ramp_hi, (level-1)/17) / ramp_hi``, so
``level=18`` and ``level=None`` (the /anti-tank route default) are byte-identical
to item 308/315 and early levels discount toward ``ramp_lo``. The seeded set is
the 10 MAX_HP champion-level ramps in champion_abilities.json / the registry
source_quotes: Aatrox P 4:8, Brand P 8:12, KSante P 1:2, Mordekaiser P 1:5,
Ornn P 10:18, Renata P 1:2, Skarner P 5:9, Urgot P 2:6, Zed P 6:10, Zeri P 1:11.
Every un-ramped row is byte-identical at any level (the additive contract). The
live default-ON flip (a consumer calling with the live champion level) is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

R39 (ENGINE 1.155.0) schema lift: the CURRENT_HP-kind sibling of R17. Each
``AntiTankEntry`` may carry optional ``current_hp_ramp_lo`` / ``current_hp_ramp_hi``
endpoints (the verbatim "lo% : hi% (based on level)" %current-HP figures), and a
parallel ``_current_hp_level_ramp_factor`` shares R17's lerp through the extracted
``_ramp_lerp_factor`` helper. ``_effective_magnitude`` multiplies BOTH ramp factors;
a row carries at most one ramp pair (max-HP OR current-HP, never both), so the other
factor is always 1.0 and every existing row is byte-identical. The seeded set is the
1 CURRENT_HP champion-level ramp in the registry source_quotes: Senna P 1:10
(Absolution, "1% : 10% (based on level) of target's current health"). ``level=None``
(the /anti-tank route default) and ``level=18`` stay byte-identical to item
308/315/R17. The live default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

R196 schema lift: each ``AntiTankEntry`` carries an ``axis`` -
``"PHYSICAL"`` / ``"MAGICAL"`` / ``"BOTH"`` (default ``"BOTH"``). ``SHRED`` and
``PERCENT_PEN`` say only THAT a row lowers resists, never WHICH resist, so an
armor-side row (Darius E armor pen, K'Sante R bonus-armor pen) was indistinguishable
from a magic-side one (Mordekaiser E magic pen) and the R190 magic-pen catalog guard
had to carry a hand-maintained physical-side exemption dict. ``axis`` makes that
guard exact. It is METADATA ONLY - no scoring path reads it, it is not serialized
onto ``AntiTankSourceEntry.to_dict()``, and every ``compute_antitank`` output is
byte-identical to R39 (measured over all 171 shipped champions x
{level None/1/9/18} x {stats on/off}). It is load-bearing only on the
``SHRED`` / ``PERCENT_PEN`` rows; every other kind keeps the default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ResolvedStats


def _finite_float(value, default: float = 0.0) -> float:
    """Coerce ``value`` to a finite float, falling back to ``default``.

    A degenerate caster-stat mapping can carry ``None`` (TypeError under
    arithmetic), a NaN, or an inf for ``ap`` / ``ad``. Any of those would poison
    the effective magnitude - a NaN serializes to a bare ``NaN`` JSON token (which
    breaks the dashboard's ``JSON.parse``) and a ``None`` raises mid-tick. Guard at
    the read so the scorer stays fail-soft (standing finding class 1/2).
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Anti-tank-kind -> weight. Hand-authored, operator-tunable. Four tiers by how
# tank-agnostic the mechanism is - all of them get stronger the more health /
# resists the target stacked:
#   1.00 MAX_HP      - damage scaled to the target's MAXIMUM health (the purest
#                      anti-tank: the more HP a tank stacks the more it takes;
#                      true %max-HP ignores resists entirely - Vayne W Silver
#                      Bolts, Kog'Maw W, Gwen passive, Fiora passive, Varus W,
#                      Camille W outer).
#   0.85 SHRED       - lowers the target's ARMOR / MAGIC RESIST or debuffs it to
#                      take more damage (Trundle R steal, Nasus E, Rell passive,
#                      Kog'Maw Q, Rumble E, Vladimir R amp); helps the WHOLE team
#                      melt the tank, not just the caster - the force-multiplier
#                      tier.
#   0.75 CURRENT_HP  - damage scaled to the target's CURRENT health (Dr. Mundo Q,
#                      Viego passive, Elise Q); strong while the tank is full,
#                      fades as it drops.
#   0.65 PERCENT_PEN - kit-intrinsic % armor / MR penetration (rare - Mordekaiser
#                      passive, Nilah passive, K'Sante R, Yasuo R); ignores a
#                      fraction of the tank's resists for the caster only.
_ANTITANK_KIND_WEIGHT: dict[str, float] = {
    "MAX_HP": 1.0,
    "SHRED": 0.85,
    "CURRENT_HP": 0.75,
    "PERCENT_PEN": 0.65,
}

# Cadence -> multiplier. How continuously the mechanism applies across a fight. An
# on-hit / every-few-autos / always-on passive is full value; a short-cooldown
# ability is nearly so; a long-cooldown or ult-only mechanism fires once and is
# discounted.
_ANTITANK_CADENCE_MULT: dict[str, float] = {
    "SUSTAINED": 1.0,
    "PERIODIC": 0.8,
    "BURST": 0.65,
}

# A gated (conditional) mechanism - one that needs the ult up, a charge / stack,
# or a specific target state - is credited at this availability midpoint, the
# zone-control / ally-amplification shape.
_ANTITANK_CONDITIONAL_PROB = 0.5

# Resist axis a row acts on (R196). PHYSICAL = it lowers the target's ARMOR (or
# amplifies physical damage against it), MAGICAL = magic resist, BOTH = it lowers
# both at once (the "reduces their armor and magic resistance" family) or
# amplifies damage from every source. METADATA ONLY - no scoring path reads it;
# it exists so a consumer / guard can tell an armor-side SHRED / PERCENT_PEN row
# from a magic-side one, which the kind alone never expressed.
_ANTITANK_AXES: frozenset[str] = frozenset({"PHYSICAL", "MAGICAL", "BOTH"})


@dataclass(frozen=True)
class AntiTankEntry:
    """One registry row: a champion anti-tank mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = an anti-tank
    identity not tied to one ability). ``kind`` is a key of
    ``_ANTITANK_KIND_WEIGHT``. ``cadence`` is a key of ``_ANTITANK_CADENCE_MULT``.
    ``magnitude`` is the 0..1 strength / reliability with which this one mechanism
    melts a tank. ``conditional`` is True when the mechanism only fires on a gate
    (ult up, charge / stack accrued, a specific target state required).

    ``ap_ratio`` / ``ad_ratio`` (P3.2 item 315) are optional caster-stat
    coefficients: when stats are injected into ``compute_antitank`` the row's
    effective magnitude becomes ``magnitude + ap * ap_ratio + ad * ad_ratio``.
    Default 0.0 keeps the row STATIC (the item-308 contract) - only the rows whose
    %HP truly carries a caster-stat term are seeded, verified against
    champion_abilities.json: Gwen P / Kog'Maw W / Varus W / Malzahar R on AP,
    Vi W / Camille W / Udyr Q on bonus AD.

    ``ramp_lo`` / ``ramp_hi`` (R17) are the optional %max-HP "lo% : hi% (based on
    level)" endpoints; ``current_hp_ramp_lo`` / ``current_hp_ramp_hi`` (R39) are the
    same for a %current-HP row (Senna P). Default 0.0 keeps the row level-static.
    A row carries at most ONE ramp pair (max-HP OR current-HP, never both).

    ``axis`` (R196) is a key of ``_ANTITANK_AXES`` - WHICH resist the row lowers
    (or, for a damage-vulnerability debuff, which damage it amplifies). It is
    load-bearing only on the ``SHRED`` / ``PERCENT_PEN`` rows; every other kind
    keeps the ``"BOTH"`` default. METADATA ONLY - ``_mechanism_value`` and
    ``compute_antitank`` never read it and it is not serialized, so it cannot move
    a score. APPENDED LAST with a default per the CLAUDE.md dataclass convention.
    """

    source: str
    kind: str
    cadence: str
    magnitude: float = 0.0
    conditional: bool = False
    ap_ratio: float = 0.0
    ad_ratio: float = 0.0
    ramp_lo: float = 0.0
    ramp_hi: float = 0.0
    current_hp_ramp_lo: float = 0.0
    current_hp_ramp_hi: float = 0.0
    axis: str = "BOTH"


# Champion level endpoints the ramp interpolates between (levels 1..18).
_RAMP_MIN_LEVEL = 1
_RAMP_MAX_LEVEL = 18


def _ramp_lerp_factor(lo: float, hi: float, level: int | None) -> float:
    """Shared level-interpolation multiplier for a (lo, hi) ramp pair (R17 / R39).

    A hand-tuned ``magnitude`` encodes the LATE-game (max-ramp) reliability; this
    returns the fraction of that power online at ``level``:
    ``lerp(lo, hi, (level-1)/17) / hi``.

    Returns ``1.0`` (the default-OFF / byte-identical path) when ``level`` is None
    (what ``compute_antitank`` / the /anti-tank route passes), when the row carries
    no ramp data (``hi <= 0.0``), or when the endpoints are flat (``lo == hi``). At
    ``level == 18`` the factor is exactly 1.0, so the score equals the item-308
    value; below 18 it discounts toward ``lo``. The level is clamped to [1, 18].
    Fail-soft: a degenerate factor falls back to 1.0.
    """
    if level is None:
        return 1.0
    if hi <= 0.0 or lo == hi:
        return 1.0
    lvl = level
    if lvl < _RAMP_MIN_LEVEL:
        lvl = _RAMP_MIN_LEVEL
    elif lvl > _RAMP_MAX_LEVEL:
        lvl = _RAMP_MAX_LEVEL
    t = (lvl - _RAMP_MIN_LEVEL) / (_RAMP_MAX_LEVEL - _RAMP_MIN_LEVEL)
    pct = lo + (hi - lo) * t
    factor = pct / hi
    return factor if math.isfinite(factor) and factor > 0.0 else 1.0


def _level_ramp_factor(entry: AntiTankEntry, level: int | None = None) -> float:
    """%max-HP level-ramp multiplier on the magnitude (R17, ENGINE 1.151.0).

    A real subset of %max-HP rows deal a percentage that scales with the CASTER's
    champion level (Aatrox P 4%:8%, Brand P 8%:12%, Skarner P 5%:9%, ...). Reads the
    row's ``ramp_lo`` / ``ramp_hi`` endpoints through the shared ``_ramp_lerp_factor``
    (see it for the interpolation + default-OFF contract). ``level=None`` /
    ``level=18`` / a row carrying no ramp data is byte-identical to item 308/315.
    """
    return _ramp_lerp_factor(entry.ramp_lo, entry.ramp_hi, level)


def _current_hp_level_ramp_factor(entry: AntiTankEntry, level: int | None = None) -> float:
    """%current-HP level-ramp multiplier on the magnitude (R39, ENGINE 1.155.0).

    The CURRENT_HP-kind sibling of ``_level_ramp_factor``: a real subset of the
    %current-HP rows deal a percentage that scales with the caster's level (Senna P
    Absolution "1% : 10% (based on level) of target's current health"). Reads the
    row's ``current_hp_ramp_lo`` / ``current_hp_ramp_hi`` endpoints through the same
    shared ``_ramp_lerp_factor``. ``level=None`` / ``level=18`` / a row carrying no
    current-HP ramp data is byte-identical to item 308/315/R17.
    """
    return _ramp_lerp_factor(entry.current_hp_ramp_lo, entry.current_hp_ramp_hi, level)


def _effective_magnitude(
    entry: AntiTankEntry,
    stats: ResolvedStats | None = None,
    level: int | None = None,
) -> float:
    """Magnitude after optional caster-stat (P3.2) + level-ramp (R17) scaling.

    Returns ``entry.magnitude`` unchanged when no ``stats`` are injected or the
    row carries no ratio (the item-308 static path), then multiplies by the optional
    level-ramp factors - the %max-HP ramp (R17) AND the %current-HP ramp (R39). The
    caster-stat half is the P3.2 formula ``base + ap * ap_ratio + ad * ad_ratio``
    (``ap`` / ``ad`` read from ``stats``, a ``ResolvedStats`` or any ``.get``
    mapping). Only seeded rows carry a non-zero ratio (Gwen P / Kog'Maw W / Varus W /
    Malzahar R on AP, Vi W / Camille W / Udyr Q on bonus AD), so every other row is
    byte-identical even when stats are passed. Each ramp factor is 1.0 unless
    ``level`` is supplied AND the row carries that ramp's endpoints, and a row carries
    at most one ramp pair, so ``level=None`` (the route default) is byte-identical to
    item 308/315/R17.
    """
    base = entry.magnitude
    if stats is None or (entry.ap_ratio == 0.0 and entry.ad_ratio == 0.0):
        scaled = base
    else:
        ap = _finite_float(stats.get("ap", 0.0))
        ad = _finite_float(stats.get("ad", 0.0))
        s = base + ap * entry.ap_ratio + ad * entry.ad_ratio
        scaled = s if math.isfinite(s) else base
    out = (
        scaled
        * _level_ramp_factor(entry, level)
        * _current_hp_level_ramp_factor(entry, level)
    )
    return out if math.isfinite(out) else scaled


def _mechanism_value(
    entry: AntiTankEntry,
    stats: ResolvedStats | None = None,
    level: int | None = None,
) -> float:
    """Kind-weighted, cadence-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * cadence_mult * effective_magnitude`` (times the
    conditional midpoint when gated), or ``0.0`` when the kind or cadence is
    unknown. ``effective_magnitude`` applies the optional P3.2 AP/AD scaling and
    the optional R17 level-ramp factor (``_effective_magnitude``); with no
    ``stats`` and no ``level`` it is the static magnitude.
    """
    weight = _ANTITANK_KIND_WEIGHT.get(entry.kind, 0.0)
    cadence_mult = _ANTITANK_CADENCE_MULT.get(entry.cadence, 0.0)
    if weight <= 0.0 or cadence_mult <= 0.0:
        return 0.0
    value = weight * cadence_mult * _effective_magnitude(entry, stats, level)
    if entry.conditional:
        value *= _ANTITANK_CONDITIONAL_PROB
    return value


def _build_antitank_registry() -> dict[str, tuple[AntiTankEntry, ...]]:
    """Build champion_id -> tuple[AntiTankEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry several
    anti-tank mechanisms (including two kinds on one ability slot) without
    dict-literal collision (the allyamp / zonecontrol builder pattern). Runs ONCE
    at import. The axis is selective - only champions whose damage scales with
    enemy health or resists appear.
    """
    raw: dict[str, list[AntiTankEntry]] = {}

    def add(
        champ: str,
        source: str,
        kind: str,
        cadence: str,
        *,
        magnitude: float,
        cond: bool = False,
        ap_ratio: float = 0.0,
        ad_ratio: float = 0.0,
        ramp_lo: float = 0.0,
        ramp_hi: float = 0.0,
        current_hp_ramp_lo: float = 0.0,
        current_hp_ramp_hi: float = 0.0,
        axis: str = "BOTH",
    ) -> None:
        raw.setdefault(champ, []).append(
            AntiTankEntry(
                source=source,
                kind=kind,
                cadence=cadence,
                magnitude=float(magnitude),
                conditional=bool(cond),
                ap_ratio=float(ap_ratio),
                ad_ratio=float(ad_ratio),
                ramp_lo=float(ramp_lo),
                ramp_hi=float(ramp_hi),
                current_hp_ramp_lo=float(current_hp_ramp_lo),
                current_hp_ramp_hi=float(current_hp_ramp_hi),
                axis=str(axis),
            )
        )

    # ------------------------------------------------------------------
    # AXIS CONVENTION (R196). Every SHRED / PERCENT_PEN row below states an
    # EXPLICIT axis, derived from the shipped 16.14.1 champion_abilities.json
    # tooltip for that slot. A row that only says "armor" is PHYSICAL, one
    # that only says "magic resistance" / "magic penetration" is MAGICAL, and
    # the large "reduces their armor and magic resistance" family is BOTH.
    # Every other kind (MAX_HP / CURRENT_HP) leaves the "BOTH" default, where
    # the field is inert. Inline citations appear only where the axis is not
    # obvious from the ability name.
    # ------------------------------------------------------------------

    # Aatrox - P %max-HP ramps 4%:8% (based on level) per the kit source_quote.
    add("Aatrox", "P", "MAX_HP", "SUSTAINED", magnitude=0.85, ramp_lo=4.0, ramp_hi=8.0)
    # Amumu - DELIBERATELY UNREGISTERED (R196). The item-308 fan-out registered
    # add("Amumu", "P", "SHRED", "SUSTAINED", magnitude=0.6), but the 16.14.1
    # passive lowers NO resist: "Cursed targets receive 10% bonus true damage from
    # all incoming pre-mitigation magic damage" - a damage-vulnerability debuff
    # paid out as TRUE damage, which is a different mechanic on a different axis.
    # SHRED means "lowers the target's resists", so the row was factually wrong
    # and is removed. No other Amumu slot belongs here either: W is a flat
    # "Magic Damage Per Tick" toggle (no %max-HP term) and Q / E / R are flat
    # magic damage, so Amumu correctly drops OFF this SELECTIVE axis and scores
    # 0.0. Pinned by test_antitank_axis_r196.py so a future patch that turns
    # Curse back into a real shred goes RED instead of being re-added blind.
    # Annie - R Summon: Tibbers carries an always-on PASSIVE percent MAGIC
    # penetration: 16.14.1 champion_abilities.json states "Passive: Annie gains
    # magic penetration" with a structured damage_block attribute "Magic
    # Penetration", raw_modifiers values [15.0, 17.5, 20.0], units all "%". The
    # shipped prose states NO gate (no "while Tibbers is alive" clause anywhere in
    # her R forms), so the row is cond=False / SUSTAINED - the exact shape of the
    # Mordekaiser E magic-pen passive, which is likewise a percent-pen passive
    # stated on an ability slot. The registry does not treat "it lives on the ult"
    # as conditional either (Trundle R and Vladimir R are both cond=False).
    #
    # MAGNITUDE CALIBRATION (0..1 reliability weight, NOT a percentage). The two
    # always-on SUSTAINED PERCENT_PEN anchors bracket Annie on the real-percentage
    # axis and are both 0.7: Mordekaiser E 15% max-rank -> 0.7 and Darius E 40%
    # max-rank -> 0.7. Annie's 20% sits strictly between them, so monotone
    # interpolation between two equal endpoints gives exactly 0.7. It exceeds no
    # sibling with a strictly larger real magnitude (Darius E 40% is also 0.7) and
    # stays above Mordekaiser E's 15%, which it genuinely beats. Value =
    # 0.65 (PERCENT_PEN) * 1.0 (SUSTAINED) * 0.7 = 0.455.
    #
    # RANK: max-rank only, the convention every kit-pen magnitude here follows
    # (BACKLOG tail (d) - rank-aware resolution needs the rank threaded to the
    # seam and is still OPEN; this row does not close it).
    add("Annie", "R", "PERCENT_PEN", "SUSTAINED", magnitude=0.7, axis="MAGICAL")
    # AurelionSol
    add("AurelionSol", "Q", "MAX_HP", "SUSTAINED", magnitude=0.7)
    # Aurora
    add("Aurora", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    # Brand
    add("Brand", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, ramp_lo=8.0, ramp_hi=12.0)
    # Brand W is a damage-vulnerability amp, not a resist cut ("Ablaze Bonus: The
    # target takes 25% increased damage"), and the damage it amplifies is Brand's
    # own MAGIC damage - hence MAGICAL rather than BOTH.
    add("Brand", "W", "SHRED", "PERIODIC", magnitude=0.65, cond=True, axis="MAGICAL")
    # Briar
    add("Briar", "Q", "SHRED", "PERIODIC", magnitude=0.7, axis="BOTH")
    # Camille - W outer-cone %max-HP carries a bonus-AD term (P3.2 expansion:
    # champion_abilities.json W block "% per 100 bonus AD"); R current-HP is flat.
    add("Camille", "W", "MAX_HP", "PERIODIC", magnitude=0.65, ad_ratio=0.0004)
    add("Camille", "R", "CURRENT_HP", "SUSTAINED", magnitude=0.6, cond=True)
    # Chogath
    add("Chogath", "E", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    # Corki
    add("Corki", "E", "SHRED", "SUSTAINED", magnitude=0.6, axis="BOTH")
    # Darius - E Apprehend passive grants always-on % armor penetration
    # (20% : 40% by E rank per champion_abilities.json 16.13.1 raw damage_blocks),
    # a kit-intrinsic PERCENT_PEN that scales with the target's armor stack. The
    # SUSTAINED sibling of Mordekaiser E's magic-pen row (R93, ENGINE 1.190.0).
    add("Darius", "E", "PERCENT_PEN", "SUSTAINED", magnitude=0.7, axis="PHYSICAL")
    # DrMundo
    add("DrMundo", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.7)
    # Elise
    add("Elise", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.6)
    # Evelynn
    add("Evelynn", "W", "SHRED", "PERIODIC", magnitude=0.45, cond=True, axis="MAGICAL")
    add("Evelynn", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Fiddlesticks
    add("Fiddlesticks", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.55)
    # Fiora
    add("Fiora", "P", "MAX_HP", "SUSTAINED", magnitude=0.9)
    # Galio
    add("Galio", "Q", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Gangplank
    # Keg explosion damage "ignores 40% of the target's armor" - armor only.
    add("Gangplank", "E", "PERCENT_PEN", "PERIODIC", magnitude=0.4, cond=True, axis="PHYSICAL")
    # Garen
    add("Garen", "E", "SHRED", "SUSTAINED", magnitude=0.5, cond=True, axis="PHYSICAL")
    # Gnar
    add("Gnar", "W", "MAX_HP", "SUSTAINED", magnitude=0.65, cond=True)
    # Gragas
    add("Gragas", "W", "MAX_HP", "PERIODIC", magnitude=0.55)
    # Gwen - P magic damage carries an AP-on-%HP term (P3.2 item 315 seed).
    add("Gwen", "P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005)
    # Hwei
    add("Hwei", "Q", "MAX_HP", "PERIODIC", magnitude=0.55, cond=True)
    # Illaoi
    add("Illaoi", "W", "MAX_HP", "SUSTAINED", magnitude=0.7)
    # JarvanIV
    add("JarvanIV", "P", "CURRENT_HP", "SUSTAINED", magnitude=0.6)
    add("JarvanIV", "Q", "SHRED", "PERIODIC", magnitude=0.6, axis="PHYSICAL")
    # Jax
    add("Jax", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Jayce
    add("Jayce", "E", "MAX_HP", "PERIODIC", magnitude=0.8)
    add("Jayce", "R", "SHRED", "SUSTAINED", magnitude=0.65, cond=True, axis="BOTH")
    # KSante
    add("KSante", "P", "MAX_HP", "SUSTAINED", magnitude=0.6, ramp_lo=1.0, ramp_hi=2.0)
    add("KSante", "W", "MAX_HP", "PERIODIC", magnitude=0.65)
    # All Out grants "50% bonus-armor penetration" - PHYSICAL. His All Out prose
    # also says "magic resistance", but that is the cut to K'Sante's OWN base MR,
    # not a target shred; the axis field is what retires the R190 magic-guard
    # exemption that used to encode this by hand.
    add("KSante", "R", "PERCENT_PEN", "BURST", magnitude=0.55, cond=True, axis="PHYSICAL")
    # Kalista
    add("Kalista", "W", "MAX_HP", "SUSTAINED", magnitude=0.45, cond=True)
    # Karthus
    add("Karthus", "W", "SHRED", "PERIODIC", magnitude=0.6, axis="MAGICAL")
    # Kayle
    add("Kayle", "Q", "SHRED", "PERIODIC", magnitude=0.6, axis="BOTH")
    # Kindred
    add("Kindred", "W", "CURRENT_HP", "SUSTAINED", magnitude=0.6, cond=True)
    # Kled
    add("Kled", "W", "MAX_HP", "SUSTAINED", magnitude=0.6, cond=True)
    add("Kled", "R", "MAX_HP", "BURST", magnitude=0.55, cond=True)
    # KogMaw - W on-hit %max-HP carries an AP term (P3.2 item 315 seed); Q shred
    # is flat.
    add("KogMaw", "Q", "SHRED", "PERIODIC", magnitude=0.7, axis="BOTH")
    add("KogMaw", "W", "MAX_HP", "SUSTAINED", magnitude=0.9, cond=True, ap_ratio=0.0004)
    # Lillia
    add("Lillia", "P", "MAX_HP", "SUSTAINED", magnitude=0.85)
    # Malzahar - R Nether Grasp %max-HP channel carries an AP term (P3.2
    # expansion: champion_abilities.json R block "% per 100 AP").
    add("Malzahar", "R", "MAX_HP", "BURST", magnitude=0.6, cond=True, ap_ratio=0.0004)
    # Maokai
    add("Maokai", "Q", "MAX_HP", "PERIODIC", magnitude=0.45)
    # MonkeyKing
    add("MonkeyKing", "Q", "SHRED", "PERIODIC", magnitude=0.65, axis="PHYSICAL")
    add("MonkeyKing", "R", "MAX_HP", "BURST", magnitude=0.7, cond=True)
    # Mordekaiser
    add("Mordekaiser", "P", "MAX_HP", "SUSTAINED", magnitude=0.85, cond=True, ramp_lo=1.0, ramp_hi=5.0)
    add("Mordekaiser", "E", "PERCENT_PEN", "SUSTAINED", magnitude=0.7, axis="MAGICAL")
    add("Mordekaiser", "R", "SHRED", "BURST", magnitude=0.5, cond=True, axis="BOTH")
    # Nasus
    add("Nasus", "E", "SHRED", "PERIODIC", magnitude=0.7, axis="PHYSICAL")
    add("Nasus", "R", "MAX_HP", "BURST", magnitude=0.55, cond=True)
    # Nilah
    # "Nilah gains 0% : 33% (based on critical strike chance) armor penetration".
    add("Nilah", "Q", "PERCENT_PEN", "SUSTAINED", magnitude=0.45, axis="PHYSICAL")
    # Olaf
    add("Olaf", "Q", "SHRED", "PERIODIC", magnitude=0.55, axis="PHYSICAL")
    # Ornn
    add("Ornn", "P", "MAX_HP", "PERIODIC", magnitude=0.7, cond=True, ramp_lo=10.0, ramp_hi=18.0)
    add("Ornn", "W", "MAX_HP", "PERIODIC", magnitude=0.75)
    # Pantheon
    add("Pantheon", "W", "MAX_HP", "PERIODIC", magnitude=0.55)
    # Poppy
    add("Poppy", "Q", "MAX_HP", "PERIODIC", magnitude=0.8)
    # Qiyana
    add("Qiyana", "R", "MAX_HP", "BURST", magnitude=0.55, cond=True)
    # RekSai
    add("RekSai", "R", "MAX_HP", "BURST", magnitude=0.8, cond=True)
    # Rell
    add("Rell", "P", "SHRED", "SUSTAINED", magnitude=0.75, axis="BOTH")
    add("Rell", "E", "MAX_HP", "SUSTAINED", magnitude=0.5)
    # Renata
    add("Renata", "P", "MAX_HP", "SUSTAINED", magnitude=0.55, ramp_lo=1.0, ramp_hi=2.0)
    # Renekton
    add("Renekton", "E", "SHRED", "PERIODIC", magnitude=0.45, cond=True, axis="PHYSICAL")
    # Rengar
    add("Rengar", "R", "SHRED", "BURST", magnitude=0.45, cond=True, axis="PHYSICAL")
    # Rumble
    add("Rumble", "P", "MAX_HP", "SUSTAINED", magnitude=0.6, cond=True)
    add("Rumble", "Q", "MAX_HP", "PERIODIC", magnitude=0.85)
    add("Rumble", "E", "SHRED", "PERIODIC", magnitude=0.65, axis="MAGICAL")
    # Sejuani
    add("Sejuani", "P", "MAX_HP", "PERIODIC", magnitude=0.7, cond=True)
    # Senna - P Absolution deals current-HP physical damage ramping 1%:10% (based
    # on level) per the kit source_quote (R39 current-HP level-ramp seed).
    add("Senna", "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5, current_hp_ramp_lo=1.0, current_hp_ramp_hi=10.0)
    # Sett
    add("Sett", "Q", "MAX_HP", "PERIODIC", magnitude=0.4)
    add("Sett", "R", "MAX_HP", "BURST", magnitude=0.8, cond=True)
    # Shen
    add("Shen", "Q", "MAX_HP", "SUSTAINED", magnitude=0.7)
    # Shyvana
    add("Shyvana", "E", "MAX_HP", "SUSTAINED", magnitude=0.55)
    # Singed
    add("Singed", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Sion
    add("Sion", "P", "MAX_HP", "SUSTAINED", magnitude=0.55, cond=True)
    add("Sion", "W", "MAX_HP", "PERIODIC", magnitude=0.7)
    add("Sion", "E", "SHRED", "PERIODIC", magnitude=0.55, axis="PHYSICAL")
    # Skarner
    add("Skarner", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True, ramp_lo=5.0, ramp_hi=9.0)
    add("Skarner", "Q", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Smolder
    add("Smolder", "Q", "MAX_HP", "PERIODIC", magnitude=0.4, cond=True)
    # TahmKench
    add("TahmKench", "R", "MAX_HP", "BURST", magnitude=0.6, cond=True)
    # Trundle
    add("Trundle", "R", "MAX_HP", "BURST", magnitude=0.8)
    add("Trundle", "R", "SHRED", "BURST", magnitude=0.85, axis="BOTH")
    # Udyr - Q on-hit %max-HP carries a bonus-AD term (P3.2 expansion:
    # champion_abilities.json Q block "% per 100 bonus AD").
    add("Udyr", "Q", "MAX_HP", "PERIODIC", magnitude=0.8, ad_ratio=0.0004)
    # Urgot
    add("Urgot", "P", "MAX_HP", "PERIODIC", magnitude=0.45, ramp_lo=2.0, ramp_hi=6.0)
    # Varus - W Blighted Quiver on-hit %max-HP carries an AP term (P3.2
    # expansion: champion_abilities.json W block "% per 100 AP"; on-hit AP Varus).
    add("Varus", "W", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0004)
    # Vayne
    add("Vayne", "W", "MAX_HP", "SUSTAINED", magnitude=0.95)
    # Vi - W Denting Blows %max-HP carries a bonus-AD term (P3.2 expansion:
    # champion_abilities.json W block "% per 100 bonus AD"); the armor SHRED is flat.
    add("Vi", "W", "MAX_HP", "SUSTAINED", magnitude=0.6, ad_ratio=0.0004)
    add("Vi", "W", "SHRED", "SUSTAINED", magnitude=0.6, axis="PHYSICAL")
    # Viego
    add("Viego", "Q", "CURRENT_HP", "SUSTAINED", magnitude=0.65)
    # Vladimir
    # Hemoplague amps "the damage they take from all sources by 10%" - BOTH axes.
    add("Vladimir", "R", "SHRED", "BURST", magnitude=0.65, axis="BOTH")
    # Volibear
    add("Volibear", "E", "MAX_HP", "PERIODIC", magnitude=0.7)
    # Warwick
    add("Warwick", "Q", "MAX_HP", "PERIODIC", magnitude=0.7)
    # XinZhao
    add("XinZhao", "R", "CURRENT_HP", "BURST", magnitude=0.6, cond=True)
    # Yasuo
    # Crits "ignore 60% of the target's bonus armor" - PHYSICAL (and BACKLOG tail
    # (e): percent-of-BONUS-armor stays uncreditable until the target model splits
    # base from bonus armor).
    add("Yasuo", "R", "PERCENT_PEN", "BURST", magnitude=0.5, cond=True, axis="PHYSICAL")
    # Yone
    add("Yone", "W", "MAX_HP", "PERIODIC", magnitude=0.68)
    # Yorick
    add("Yorick", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    add("Yorick", "E", "SHRED", "PERIODIC", magnitude=0.6, axis="PHYSICAL")
    # Zac
    add("Zac", "W", "MAX_HP", "PERIODIC", magnitude=0.7)
    # Zed
    add("Zed", "P", "MAX_HP", "SUSTAINED", magnitude=0.5, cond=True, ramp_lo=6.0, ramp_hi=10.0)
    # Zeri
    add("Zeri", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True, ramp_lo=1.0, ramp_hi=11.0)
    # Zoe
    add("Zoe", "E", "SHRED", "PERIODIC", magnitude=0.5, cond=True, axis="MAGICAL")

    return {champ: tuple(entries) for champ, entries in raw.items()}


_ANTITANK_REGISTRY: dict[str, tuple[AntiTankEntry, ...]] = _build_antitank_registry()


@dataclass(frozen=True)
class AntiTankSourceEntry:
    """One scored anti-tank mechanism for a champion."""

    source_key: str
    kind: str
    cadence: str
    kind_weight: float
    cadence_mult: float
    magnitude: float
    conditional: bool
    value: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "kind": self.kind,
            "cadence": self.cadence,
            "kind_weight": self.kind_weight,
            "cadence_mult": self.cadence_mult,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class AntiTankResult:
    """Aggregate anti-tank / %HP-damage power for one champion.

    ``antitank_score`` sums every mechanism's kind-weighted, cadence-scaled value
    (higher = melts tanks harder). ``top_kind`` is the kind of the single
    highest-value mechanism (the champion's strongest anti-tank tool, ``""`` when
    none). ``shreds_resist`` is True when at least one SHRED or PERCENT_PEN
    mechanism contributes - the flag a draft / itemization consumer keys on (the
    champion lowers the tank's resists for the whole team). Returns all-zero with
    an empty ``sources`` tuple for an unregistered or blank champion (never
    raises); the axis is selective, so a zero score is the correct, common answer
    for a flat-damage champion whose output ignores enemy health and resists.
    """

    champion: str
    mode: str
    antitank_score: float
    top_kind: str
    shreds_resist: bool
    sources: tuple[AntiTankSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "antitank_score": round(self.antitank_score, 4),
            "top_kind": self.top_kind,
            "shreds_resist": self.shreds_resist,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> AntiTankResult:
    return AntiTankResult(
        champion=champion,
        mode=mode,
        antitank_score=0.0,
        top_kind="",
        shreds_resist=False,
        sources=(),
    )


def _source_sort_key(entry: AntiTankEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_antitank(
    champion: str,
    mode: str = "SR",
    stats: ResolvedStats | None = None,
    level: int | None = None,
) -> AntiTankResult:
    """Aggregate a champion's anti-tank mechanisms into a tank-melt score.

    Reads ``_ANTITANK_REGISTRY``. Each registered mechanism contributes a
    kind-weighted, cadence-scaled value (``_mechanism_value``); the values are
    summed into ``antitank_score``. ``top_kind`` is the kind of the highest-value
    mechanism; ``shreds_resist`` is True when any SHRED or PERCENT_PEN mechanism
    contributes. ``mode`` is carried on the result for parity with the other
    scorers but does not change output today (anti-tank kit value is
    map-independent).

    ``stats`` (P3.2 item 315) is an optional caster-stat object (a
    ``ResolvedStats`` or any ``.get("ap"/"ad")`` mapping). When supplied, a seeded
    row's effective magnitude scales by ``base + ap * ap_ratio + ad * ad_ratio``
    (the seeded source's reported ``magnitude`` / ``value`` reflect the scaled
    figure). ``stats=None`` (the default, and what the /anti-tank route passes) is
    byte-identical to item 308, as is any row carrying no ratio.

    ``level`` (R17, ENGINE 1.151.0) is an optional caster champion level. When
    supplied, a ramp-seeded row (one carrying ``ramp_hi`` endpoints - the %max-HP
    rows whose percentage scales with level: Aatrox P 4%:8%, Brand P 8%:12%,
    Skarner P 5%:9%, ...) has its effective magnitude scaled toward the early-game
    ``ramp_lo`` endpoint. ``level=18`` and ``level=None`` (the route default) are
    byte-identical to item 308/315, and any row with no ramp endpoint is
    byte-identical at every level.

    Returns an all-zero ``AntiTankResult`` (empty ``sources``) when the champion
    is blank / None or absent from the (selective) registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _ANTITANK_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[AntiTankSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    has_shred = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry, stats, level)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.kind in ("SHRED", "PERCENT_PEN"):
            has_shred = True
        scored.append(
            AntiTankSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                cadence=entry.cadence,
                kind_weight=_ANTITANK_KIND_WEIGHT.get(entry.kind, 0.0),
                cadence_mult=_ANTITANK_CADENCE_MULT.get(entry.cadence, 0.0),
                magnitude=_effective_magnitude(entry, stats, level),
                conditional=entry.conditional,
                value=value,
            )
        )

    return AntiTankResult(
        champion=champion,
        mode=safe_mode,
        antitank_score=total,
        top_kind=best_kind if total > 0.0 else "",
        shreds_resist=has_shred,
        sources=tuple(scored),
    )


__all__ = [
    "AntiTankEntry",
    "AntiTankResult",
    "AntiTankSourceEntry",
    "compute_antitank",
    "compute_antitank_live",
    "_ANTITANK_KIND_WEIGHT",
    "_ANTITANK_CADENCE_MULT",
    "_ANTITANK_CONDITIONAL_PROB",
    "_ANTITANK_AXES",
    "_ANTITANK_REGISTRY",
    "_level_ramp_factor",
    "_current_hp_level_ramp_factor",
]


def compute_antitank_live(
    snapshot,
    champion: str,
    level: int,
    item_ids=None,
    mode: str = "SR",
    augments=None,
) -> AntiTankResult:
    """Anti-tank score with the LIVE caster's resolved AP/AD folded in (P3.2).

    The PRODUCER half of the P3.2 (item 315) caster-stat seam. ``compute_antitank``
    leaves the optional ``stats`` None (the /anti-tank route passes no stats), so a
    seeded row's ``ap_ratio`` / ``ad_ratio`` scaling stays dormant. This wrapper
    resolves the champion's stats from its live build via ``engine.build_champion``
    and feeds the ResolvedStats to ``compute_antitank(stats=...)`` so a seeded row's
    %max-HP magnitude scales by ``base + ap*ap_ratio + ad*ad_ratio`` (Gwen P /
    KogMaw W / Varus W / Malzahar R AP; Vi W / Camille W / Udyr Q AD).

    A champion with NO seeded ratio is byte-identical to
    ``compute_antitank(champion, mode=mode)``; a naked / zero-AP-AD build is too.
    This is the live-input producer the section-B anti-tank P3.2 row in
    docs/LIVE_GAME_GATED_SYNC.md asks for - additive (no engine-math change, no
    :8893 restart); the live default-ON wire (a survivability scorer calling this
    with the live build) + the eyeball check stay operator-gated. Fail-soft: a
    build-resolution error falls back to the static score. ASCII only.
    """
    from .engine import build_champion  # deferred - avoid an import cycle

    try:
        stats = build_champion(
            snapshot, champion, level, item_ids, mode=mode, augments=augments
        )
    except Exception:  # noqa: BLE001 - fail-soft to the static (no-stats) score
        return compute_antitank(champion, mode=mode)
    return compute_antitank(champion, mode=mode, stats=stats)
