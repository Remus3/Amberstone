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
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class AntiTankEntry:
    """One registry row: a champion anti-tank mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = an anti-tank
    identity not tied to one ability). ``kind`` is a key of
    ``_ANTITANK_KIND_WEIGHT``. ``cadence`` is a key of ``_ANTITANK_CADENCE_MULT``.
    ``magnitude`` is the 0..1 strength / reliability with which this one mechanism
    melts a tank. ``conditional`` is True when the mechanism only fires on a gate
    (ult up, charge / stack accrued, a specific target state required).
    """

    source: str
    kind: str
    cadence: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: AntiTankEntry) -> float:
    """Kind-weighted, cadence-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * cadence_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or cadence is unknown.
    """
    weight = _ANTITANK_KIND_WEIGHT.get(entry.kind, 0.0)
    cadence_mult = _ANTITANK_CADENCE_MULT.get(entry.cadence, 0.0)
    if weight <= 0.0 or cadence_mult <= 0.0:
        return 0.0
    value = weight * cadence_mult * entry.magnitude
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
    ) -> None:
        raw.setdefault(champ, []).append(
            AntiTankEntry(
                source=source,
                kind=kind,
                cadence=cadence,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "P", "MAX_HP", "SUSTAINED", magnitude=0.85)
    # Amumu
    add("Amumu", "P", "SHRED", "SUSTAINED", magnitude=0.6)
    # AurelionSol
    add("AurelionSol", "Q", "MAX_HP", "SUSTAINED", magnitude=0.7)
    # Aurora
    add("Aurora", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    # Brand
    add("Brand", "P", "MAX_HP", "SUSTAINED", magnitude=0.7)
    add("Brand", "W", "SHRED", "PERIODIC", magnitude=0.65, cond=True)
    # Briar
    add("Briar", "Q", "SHRED", "PERIODIC", magnitude=0.7)
    # Camille
    add("Camille", "W", "MAX_HP", "PERIODIC", magnitude=0.65)
    add("Camille", "R", "CURRENT_HP", "SUSTAINED", magnitude=0.6, cond=True)
    # Chogath
    add("Chogath", "E", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    # Corki
    add("Corki", "E", "SHRED", "SUSTAINED", magnitude=0.6)
    # DrMundo
    add("DrMundo", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.7)
    # Elise
    add("Elise", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.6)
    # Evelynn
    add("Evelynn", "W", "SHRED", "PERIODIC", magnitude=0.45, cond=True)
    add("Evelynn", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Fiddlesticks
    add("Fiddlesticks", "Q", "CURRENT_HP", "PERIODIC", magnitude=0.55)
    # Fiora
    add("Fiora", "P", "MAX_HP", "SUSTAINED", magnitude=0.9)
    # Galio
    add("Galio", "Q", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Gangplank
    add("Gangplank", "E", "PERCENT_PEN", "PERIODIC", magnitude=0.4, cond=True)
    # Garen
    add("Garen", "E", "SHRED", "SUSTAINED", magnitude=0.5, cond=True)
    # Gnar
    add("Gnar", "W", "MAX_HP", "SUSTAINED", magnitude=0.65, cond=True)
    # Gragas
    add("Gragas", "W", "MAX_HP", "PERIODIC", magnitude=0.55)
    # Gwen
    add("Gwen", "P", "MAX_HP", "SUSTAINED", magnitude=0.85)
    # Hwei
    add("Hwei", "Q", "MAX_HP", "PERIODIC", magnitude=0.55, cond=True)
    # Illaoi
    add("Illaoi", "W", "MAX_HP", "SUSTAINED", magnitude=0.7)
    # JarvanIV
    add("JarvanIV", "P", "CURRENT_HP", "SUSTAINED", magnitude=0.6)
    add("JarvanIV", "Q", "SHRED", "PERIODIC", magnitude=0.6)
    # Jax
    add("Jax", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Jayce
    add("Jayce", "E", "MAX_HP", "PERIODIC", magnitude=0.8)
    add("Jayce", "R", "SHRED", "SUSTAINED", magnitude=0.65, cond=True)
    # KSante
    add("KSante", "P", "MAX_HP", "SUSTAINED", magnitude=0.6)
    add("KSante", "W", "MAX_HP", "PERIODIC", magnitude=0.65)
    add("KSante", "R", "PERCENT_PEN", "BURST", magnitude=0.55, cond=True)
    # Kalista
    add("Kalista", "W", "MAX_HP", "SUSTAINED", magnitude=0.45, cond=True)
    # Karthus
    add("Karthus", "W", "SHRED", "PERIODIC", magnitude=0.6)
    # Kayle
    add("Kayle", "Q", "SHRED", "PERIODIC", magnitude=0.6)
    # Kindred
    add("Kindred", "W", "CURRENT_HP", "SUSTAINED", magnitude=0.6, cond=True)
    # Kled
    add("Kled", "W", "MAX_HP", "SUSTAINED", magnitude=0.6, cond=True)
    add("Kled", "R", "MAX_HP", "BURST", magnitude=0.55, cond=True)
    # KogMaw
    add("KogMaw", "Q", "SHRED", "PERIODIC", magnitude=0.7)
    add("KogMaw", "W", "MAX_HP", "SUSTAINED", magnitude=0.9, cond=True)
    # Lillia
    add("Lillia", "P", "MAX_HP", "SUSTAINED", magnitude=0.85)
    # Malzahar
    add("Malzahar", "R", "MAX_HP", "BURST", magnitude=0.6, cond=True)
    # Maokai
    add("Maokai", "Q", "MAX_HP", "PERIODIC", magnitude=0.45)
    # MonkeyKing
    add("MonkeyKing", "Q", "SHRED", "PERIODIC", magnitude=0.65)
    add("MonkeyKing", "R", "MAX_HP", "BURST", magnitude=0.7, cond=True)
    # Mordekaiser
    add("Mordekaiser", "P", "MAX_HP", "SUSTAINED", magnitude=0.85, cond=True)
    add("Mordekaiser", "E", "PERCENT_PEN", "SUSTAINED", magnitude=0.7)
    add("Mordekaiser", "R", "SHRED", "BURST", magnitude=0.5, cond=True)
    # Nasus
    add("Nasus", "E", "SHRED", "PERIODIC", magnitude=0.7)
    add("Nasus", "R", "MAX_HP", "BURST", magnitude=0.55, cond=True)
    # Nilah
    add("Nilah", "Q", "PERCENT_PEN", "SUSTAINED", magnitude=0.45)
    # Olaf
    add("Olaf", "Q", "SHRED", "PERIODIC", magnitude=0.55)
    # Ornn
    add("Ornn", "P", "MAX_HP", "PERIODIC", magnitude=0.7, cond=True)
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
    add("Rell", "P", "SHRED", "SUSTAINED", magnitude=0.75)
    add("Rell", "E", "MAX_HP", "SUSTAINED", magnitude=0.5)
    # Renata
    add("Renata", "P", "MAX_HP", "SUSTAINED", magnitude=0.55)
    # Renekton
    add("Renekton", "E", "SHRED", "PERIODIC", magnitude=0.45, cond=True)
    # Rengar
    add("Rengar", "R", "SHRED", "BURST", magnitude=0.45, cond=True)
    # Rumble
    add("Rumble", "P", "MAX_HP", "SUSTAINED", magnitude=0.6, cond=True)
    add("Rumble", "Q", "MAX_HP", "PERIODIC", magnitude=0.85)
    add("Rumble", "E", "SHRED", "PERIODIC", magnitude=0.65)
    # Sejuani
    add("Sejuani", "P", "MAX_HP", "PERIODIC", magnitude=0.7, cond=True)
    # Senna
    add("Senna", "P", "CURRENT_HP", "SUSTAINED", magnitude=0.5)
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
    add("Sion", "E", "SHRED", "PERIODIC", magnitude=0.55)
    # Skarner
    add("Skarner", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    add("Skarner", "Q", "MAX_HP", "PERIODIC", magnitude=0.6)
    # Smolder
    add("Smolder", "Q", "MAX_HP", "PERIODIC", magnitude=0.4, cond=True)
    # TahmKench
    add("TahmKench", "R", "MAX_HP", "BURST", magnitude=0.6, cond=True)
    # Trundle
    add("Trundle", "R", "MAX_HP", "BURST", magnitude=0.8)
    add("Trundle", "R", "SHRED", "BURST", magnitude=0.85)
    # Udyr
    add("Udyr", "Q", "MAX_HP", "PERIODIC", magnitude=0.8)
    # Urgot
    add("Urgot", "P", "MAX_HP", "PERIODIC", magnitude=0.45)
    # Varus
    add("Varus", "W", "MAX_HP", "SUSTAINED", magnitude=0.85)
    # Vayne
    add("Vayne", "W", "MAX_HP", "SUSTAINED", magnitude=0.95)
    # Vi
    add("Vi", "W", "MAX_HP", "SUSTAINED", magnitude=0.6)
    add("Vi", "W", "SHRED", "SUSTAINED", magnitude=0.6)
    # Viego
    add("Viego", "Q", "CURRENT_HP", "SUSTAINED", magnitude=0.65)
    # Vladimir
    add("Vladimir", "R", "SHRED", "BURST", magnitude=0.65)
    # Volibear
    add("Volibear", "E", "MAX_HP", "PERIODIC", magnitude=0.7)
    # Warwick
    add("Warwick", "Q", "MAX_HP", "PERIODIC", magnitude=0.7)
    # XinZhao
    add("XinZhao", "R", "CURRENT_HP", "BURST", magnitude=0.6, cond=True)
    # Yasuo
    add("Yasuo", "R", "PERCENT_PEN", "BURST", magnitude=0.5, cond=True)
    # Yone
    add("Yone", "W", "MAX_HP", "PERIODIC", magnitude=0.68)
    # Yorick
    add("Yorick", "E", "MAX_HP", "PERIODIC", magnitude=0.6)
    add("Yorick", "E", "SHRED", "PERIODIC", magnitude=0.6)
    # Zac
    add("Zac", "W", "MAX_HP", "PERIODIC", magnitude=0.7)
    # Zed
    add("Zed", "P", "MAX_HP", "SUSTAINED", magnitude=0.5, cond=True)
    # Zeri
    add("Zeri", "P", "MAX_HP", "SUSTAINED", magnitude=0.7, cond=True)
    # Zoe
    add("Zoe", "E", "SHRED", "PERIODIC", magnitude=0.5, cond=True)

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


def compute_antitank(champion: str, mode: str = "SR") -> AntiTankResult:
    """Aggregate a champion's anti-tank mechanisms into a tank-melt score.

    Reads ``_ANTITANK_REGISTRY``. Each registered mechanism contributes a
    kind-weighted, cadence-scaled value (``_mechanism_value``); the values are
    summed into ``antitank_score``. ``top_kind`` is the kind of the highest-value
    mechanism; ``shreds_resist`` is True when any SHRED or PERCENT_PEN mechanism
    contributes. ``mode`` is carried on the result for parity with the other
    scorers but does not change output today (anti-tank kit value is
    map-independent).

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
        value = _mechanism_value(entry)
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
                magnitude=entry.magnitude,
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
    "_ANTITANK_KIND_WEIGHT",
    "_ANTITANK_CADENCE_MULT",
    "_ANTITANK_CONDITIONAL_PROB",
    "_ANTITANK_REGISTRY",
]
