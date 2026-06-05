"""Extended-dueling / 1v1 sustained-fight scorer (ENGINE 1.118.0, item 309).

The seventeenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303) /
ally-amplification (item 304) / anti-tank (item 308) / the six archetype scorers.
It quantifies how well a champion's OWN KIT wins a PROLONGED 1v1 duel - the fight
that goes PAST the initial burst window (~5s+) into a sustained exchange - the
attrition dimension the prior sixteen axes never measured. The burst scorer
measures front-loaded damage and the DPS scorer measures raw output against a
fixed dummy; neither answers "does this champion's kit WIN the long duel". This
one does.

Extended-dueling is the COMPOSITE win-the-long-1v1 identity: a champion that
RAMPS the longer the fight runs, RE-CYCLES her combo with resets, OUT-HEALS the
attrition mid-fight, and OUT-LASTS a single opponent's resources. A high score
means a built-to-duel kit (Jax / Master Yi / Tryndamere / Fiora / Aatrox /
Vladimir / Warwick / Camille / Nasus / Yone). A low score (or zero) means a
champion who wins-or-loses in the first few seconds and has no attrition tools - a
burst assassin, an artillery mage, a pure enchanter, most of the roster.

Purely ADDITIVE: a new standalone scorer and a new ``/extended-duel`` route. It
reads no existing scorer and is read by none, so every existing route is
byte-identical (the opt-in is the new endpoint itself - inert until a caller
invokes it, the section-5 "default inert" contract for a brand-new surface).
Wiring it into a live draft / matchup / coach surface (a "do not take this lane
into a long 1v1" verdict) is the separate Phase-D step.

Like the sustain / zone-control / ally-amplification / anti-tank axes (and unlike
the full-roster threat-range / wave-clear / objective-damage axes), this axis is
SELECTIVE: a champion with no extended-duel mechanism carries no registry rows and
scores ``0.0`` (the empty-result contract).

Model (each duel MECHANISM a champion owns contributes a kind-weighted,
cadence-scaled value; the headline is their sum):
  * a per-(champion, source, kind) ``ExtendedDuelEntry`` tags one mechanism with a
    ``kind`` (key of ``_EXTENDEDDUEL_KIND_WEIGHT`` - WHAT wins the long duel: RAMP /
    RESET / DUELHEAL / ENDURE), a ``cadence`` (key of
    ``_EXTENDEDDUEL_CADENCE_MULT`` - how continuously it applies through a fight:
    SUSTAINED / PERIODIC / BURST), a ``magnitude`` (0..1 how strongly / reliably
    this mechanism tilts a long 1v1), and a ``conditional`` flag (needs the ult up,
    a fury / stack threshold, or a specific target state). A single ability can
    carry two kinds (Aatrox passive ramps AND heals; Renekton fury resets AND
    endures), so a champion may hold two rows on one slot.
  * ``compute_extendedduel`` folds every mechanism into a single ``duel_score`` =
    sum of ``kind_weight * cadence_mult * magnitude`` (times the conditional
    midpoint when gated). ``top_kind`` labels the kind of the single highest-value
    mechanism (the champion's strongest duel tool); ``ramps`` is True when any RAMP
    mechanism contributes - the identity a draft / matchup consumer keys on (this
    champion gets STRONGER the longer you fight it, so do not commit to a long 1v1
    against it).

Kinds, cadences and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-309 roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Duel-kind -> weight. Hand-authored, operator-tunable. Four tiers by how directly
# the mechanism wins a PROLONGED 1v1 (the fight past the burst window):
#   1.00 RAMP     - power that GROWS the longer the duel runs (the purest
#                   attrition identity: stacking AS / AD / damage steroids,
#                   in-combat scaling, on-hit ramp - Jax E->R, Master Yi Q/E,
#                   Kayle, Nasus Q, Tryndamere fury, Vayne, Kog'Maw W, Kennen).
#                   "The longer you fight, the more you win."
#   0.85 RESET    - cooldown / ability RESETS, refunds or refreshes that re-fire
#                   the combo within ONE duel (Katarina, Akali, Riven, Renekton
#                   fury empowers, Garen Q refresh, Pyke R, Camille, Fiora vitals);
#                   an effective-DPS multiplier over a long exchange.
#   0.75 DUELHEAL - in-fight self-heal that REFILLS mid-duel - a lifesteal steroid
#                   or kit heal that scales WITH the fight (Aatrox P, Warwick P,
#                   Dr Mundo, Sylas W, Fiora P, Vladimir Q, Sett W); the attrition
#                   tool.
#   0.60 ENDURE   - keep-swinging endurance that outlasts a single opponent:
#                   resourceless / fury kits, refreshing defensive layers, sustained
#                   DR / grit while attacking (Garen P, Dr Mundo, Yasuo / Yone
#                   no-mana, Olaf R, Sett grit, Tryndamere R undying).
_EXTENDEDDUEL_KIND_WEIGHT: dict[str, float] = {
    "RAMP": 1.0,
    "RESET": 0.85,
    "DUELHEAL": 0.75,
    "ENDURE": 0.6,
}

# Cadence -> multiplier. How continuously the mechanism applies across a fight. An
# always-on stance / on-hit ramp / passive is full value; a short-cooldown ability
# is nearly so; a one-press steroid or single ult window is discounted.
_EXTENDEDDUEL_CADENCE_MULT: dict[str, float] = {
    "SUSTAINED": 1.0,
    "PERIODIC": 0.8,
    "BURST": 0.65,
}

# A gated (conditional) mechanism - one that needs the ult up, a fury / stack
# threshold, or a specific target state - is credited at this availability
# midpoint, the zone-control / ally-amplification / anti-tank shape.
_EXTENDEDDUEL_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class ExtendedDuelEntry:
    """One registry row: a champion extended-duel mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = a duel
    identity not tied to one ability). ``kind`` is a key of
    ``_EXTENDEDDUEL_KIND_WEIGHT``. ``cadence`` is a key of
    ``_EXTENDEDDUEL_CADENCE_MULT``. ``magnitude`` is the 0..1 strength /
    reliability with which this one mechanism tilts a long 1v1. ``conditional`` is
    True when the mechanism only fires on a gate (ult up, fury / stack accrued, a
    specific target state required).
    """

    source: str
    kind: str
    cadence: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: ExtendedDuelEntry) -> float:
    """Kind-weighted, cadence-scaled value for one mechanism (0 if unknown).

    Returns ``kind_weight * cadence_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or cadence is unknown.
    """
    weight = _EXTENDEDDUEL_KIND_WEIGHT.get(entry.kind, 0.0)
    cadence_mult = _EXTENDEDDUEL_CADENCE_MULT.get(entry.cadence, 0.0)
    if weight <= 0.0 or cadence_mult <= 0.0:
        return 0.0
    value = weight * cadence_mult * entry.magnitude
    if entry.conditional:
        value *= _EXTENDEDDUEL_CONDITIONAL_PROB
    return value


def _build_extendedduel_registry() -> dict[str, tuple[ExtendedDuelEntry, ...]]:
    """Build champion_id -> tuple[ExtendedDuelEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry several
    duel mechanisms (including two kinds on one ability slot) without dict-literal
    collision (the antitank / allyamp builder pattern). Runs ONCE at import. The
    axis is selective - only champions with a real extended-duel mechanism appear.
    """
    raw: dict[str, list[ExtendedDuelEntry]] = {}

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
            ExtendedDuelEntry(
                source=source,
                kind=kind,
                cadence=cadence,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "P", "RAMP", "PERIODIC", magnitude=0.85)
    add("Aatrox", "P", "DUELHEAL", "PERIODIC", magnitude=0.8)
    add("Aatrox", "E", "DUELHEAL", "SUSTAINED", magnitude=0.7)
    add("Aatrox", "R", "RAMP", "BURST", magnitude=0.75, cond=True)
    add("Aatrox", "R", "DUELHEAL", "BURST", magnitude=0.75, cond=True)
    # Akali
    add("Akali", "P", "RESET", "PERIODIC", magnitude=0.65)
    add("Akali", "R", "RESET", "BURST", magnitude=0.6, cond=True)
    # Akshan
    add("Akshan", "P", "ENDURE", "PERIODIC", magnitude=0.4)
    # Alistar
    add("Alistar", "P", "DUELHEAL", "PERIODIC", magnitude=0.45)
    add("Alistar", "R", "ENDURE", "BURST", magnitude=0.78)
    # Ambessa
    add("Ambessa", "R", "DUELHEAL", "SUSTAINED", magnitude=0.45)
    # Amumu
    add("Amumu", "W", "RAMP", "SUSTAINED", magnitude=0.55)
    add("Amumu", "E", "ENDURE", "SUSTAINED", magnitude=0.45)
    # Anivia
    add("Anivia", "P", "ENDURE", "BURST", magnitude=0.65)
    # Aurora
    add("Aurora", "P", "RESET", "PERIODIC", magnitude=0.45)
    add("Aurora", "P", "DUELHEAL", "SUSTAINED", magnitude=0.55)
    # Belveth
    add("Belveth", "W", "RESET", "PERIODIC", magnitude=0.5)
    add("Belveth", "E", "DUELHEAL", "BURST", magnitude=0.55)
    add("Belveth", "E", "ENDURE", "BURST", magnitude=0.5)
    add("Belveth", "R", "RAMP", "SUSTAINED", magnitude=0.75)
    # Braum
    add("Braum", "E", "ENDURE", "PERIODIC", magnitude=0.4)
    # Briar
    add("Briar", "P", "RAMP", "SUSTAINED", magnitude=0.75)
    add("Briar", "P", "DUELHEAL", "SUSTAINED", magnitude=0.7)
    add("Briar", "W", "DUELHEAL", "SUSTAINED", magnitude=0.82)
    add("Briar", "W", "RAMP", "SUSTAINED", magnitude=0.65)
    add("Briar", "R", "ENDURE", "BURST", magnitude=0.7, cond=True)
    # Camille
    add("Camille", "P", "ENDURE", "BURST", magnitude=0.45)
    add("Camille", "W", "DUELHEAL", "BURST", magnitude=0.65, cond=True)
    add("Camille", "E", "RESET", "PERIODIC", magnitude=0.5)
    # Cassiopeia
    add("Cassiopeia", "E", "RESET", "PERIODIC", magnitude=0.9)
    # Darius
    add("Darius", "P", "RAMP", "SUSTAINED", magnitude=0.9)
    add("Darius", "Q", "DUELHEAL", "PERIODIC", magnitude=0.6, cond=True)
    add("Darius", "R", "RESET", "BURST", magnitude=0.7, cond=True)
    # Diana
    add("Diana", "P", "RAMP", "PERIODIC", magnitude=0.4)
    add("Diana", "W", "ENDURE", "PERIODIC", magnitude=0.45)
    add("Diana", "E", "RESET", "PERIODIC", magnitude=0.45, cond=True)
    # DrMundo
    add("DrMundo", "P", "DUELHEAL", "SUSTAINED", magnitude=0.7)
    add("DrMundo", "W", "DUELHEAL", "PERIODIC", magnitude=0.45)
    add("DrMundo", "R", "DUELHEAL", "BURST", magnitude=0.85, cond=True)
    add("DrMundo", "BASE", "ENDURE", "SUSTAINED", magnitude=0.65)
    # Draven
    add("Draven", "Q", "RAMP", "SUSTAINED", magnitude=0.65)
    add("Draven", "W", "RAMP", "PERIODIC", magnitude=0.4, cond=True)
    # Ekko
    add("Ekko", "P", "RESET", "PERIODIC", magnitude=0.6)
    add("Ekko", "W", "ENDURE", "PERIODIC", magnitude=0.55)
    add("Ekko", "R", "DUELHEAL", "BURST", magnitude=0.8, cond=True)
    add("Ekko", "R", "RESET", "BURST", magnitude=0.65, cond=True)
    # Elise
    add("Elise", "P", "DUELHEAL", "SUSTAINED", magnitude=0.45, cond=True)
    add("Elise", "W", "RAMP", "BURST", magnitude=0.4, cond=True)
    # Evelynn
    add("Evelynn", "P", "DUELHEAL", "SUSTAINED", magnitude=0.45, cond=True)
    add("Evelynn", "R", "RESET", "BURST", magnitude=0.6, cond=True)
    # Ezreal
    add("Ezreal", "P", "RAMP", "SUSTAINED", magnitude=0.35)
    add("Ezreal", "Q", "RESET", "SUSTAINED", magnitude=0.4)
    # Fiddlesticks
    add("Fiddlesticks", "W", "DUELHEAL", "PERIODIC", magnitude=0.5)
    # Fiora
    add("Fiora", "P", "DUELHEAL", "PERIODIC", magnitude=0.88)
    add("Fiora", "P", "RESET", "PERIODIC", magnitude=0.85)
    add("Fiora", "Q", "RESET", "PERIODIC", magnitude=0.65, cond=True)
    add("Fiora", "W", "ENDURE", "BURST", magnitude=0.7, cond=True)
    add("Fiora", "R", "DUELHEAL", "BURST", magnitude=0.75, cond=True)
    # Gangplank
    add("Gangplank", "P", "RESET", "PERIODIC", magnitude=0.5)
    add("Gangplank", "W", "DUELHEAL", "BURST", magnitude=0.45)
    # Garen
    add("Garen", "Q", "RESET", "PERIODIC", magnitude=0.55)
    add("Garen", "W", "ENDURE", "SUSTAINED", magnitude=0.35)
    add("Garen", "E", "RAMP", "SUSTAINED", magnitude=0.6)
    # Gnar
    add("Gnar", "P", "RAMP", "SUSTAINED", magnitude=0.72)
    add("Gnar", "P", "ENDURE", "BURST", magnitude=0.68, cond=True)
    # Gragas
    add("Gragas", "P", "DUELHEAL", "PERIODIC", magnitude=0.55)
    add("Gragas", "W", "ENDURE", "BURST", magnitude=0.5)
    # Graves
    add("Graves", "P", "RAMP", "SUSTAINED", magnitude=0.55)
    add("Graves", "E", "ENDURE", "PERIODIC", magnitude=0.4)
    # Gwen
    add("Gwen", "P", "DUELHEAL", "SUSTAINED", magnitude=0.82)
    add("Gwen", "W", "ENDURE", "BURST", magnitude=0.5, cond=True)
    add("Gwen", "E", "RAMP", "BURST", magnitude=0.55)
    # Hecarim
    add("Hecarim", "Q", "RAMP", "PERIODIC", magnitude=0.55)
    add("Hecarim", "W", "DUELHEAL", "PERIODIC", magnitude=0.65)
    # Illaoi
    add("Illaoi", "P", "RAMP", "SUSTAINED", magnitude=0.7)
    add("Illaoi", "W", "DUELHEAL", "PERIODIC", magnitude=0.75)
    add("Illaoi", "E", "DUELHEAL", "PERIODIC", magnitude=0.65, cond=True)
    add("Illaoi", "R", "RESET", "BURST", magnitude=0.7, cond=True)
    # Irelia
    add("Irelia", "P", "RAMP", "SUSTAINED", magnitude=0.75)
    add("Irelia", "P", "ENDURE", "SUSTAINED", magnitude=0.55, cond=True)
    add("Irelia", "Q", "RESET", "SUSTAINED", magnitude=0.7, cond=True)
    add("Irelia", "W", "ENDURE", "BURST", magnitude=0.5)
    # Jax
    add("Jax", "P", "RAMP", "SUSTAINED", magnitude=0.9)
    add("Jax", "E", "ENDURE", "BURST", magnitude=0.8)
    add("Jax", "R", "RAMP", "PERIODIC", magnitude=0.75)
    add("Jax", "R", "ENDURE", "PERIODIC", magnitude=0.65)
    # KSante
    add("KSante", "P", "RAMP", "SUSTAINED", magnitude=0.65)
    add("KSante", "R", "ENDURE", "BURST", magnitude=0.8, cond=True)
    add("KSante", "R", "DUELHEAL", "BURST", magnitude=0.65, cond=True)
    # Kaisa
    add("Kaisa", "P", "RAMP", "SUSTAINED", magnitude=0.55)
    # Kalista
    add("Kalista", "E", "RAMP", "SUSTAINED", magnitude=0.65)
    # Kassadin
    add("Kassadin", "P", "ENDURE", "SUSTAINED", magnitude=0.35)
    add("Kassadin", "R", "RAMP", "SUSTAINED", magnitude=0.5)
    add("Kassadin", "R", "RESET", "SUSTAINED", magnitude=0.55)
    # Katarina
    add("Katarina", "P", "RESET", "PERIODIC", magnitude=0.8)
    add("Katarina", "P", "DUELHEAL", "PERIODIC", magnitude=0.55)
    add("Katarina", "Q", "RESET", "PERIODIC", magnitude=0.65)
    add("Katarina", "R", "RESET", "BURST", magnitude=0.7, cond=True)
    # Kayle
    add("Kayle", "P", "RAMP", "SUSTAINED", magnitude=0.88)
    add("Kayle", "W", "DUELHEAL", "PERIODIC", magnitude=0.55)
    add("Kayle", "R", "ENDURE", "BURST", magnitude=0.72, cond=True)
    # Kayn
    add("Kayn", "P", "DUELHEAL", "SUSTAINED", magnitude=0.6, cond=True)
    add("Kayn", "R", "DUELHEAL", "BURST", magnitude=0.7, cond=True)
    # Kennen
    add("Kennen", "P", "RESET", "PERIODIC", magnitude=0.55)
    add("Kennen", "E", "RAMP", "SUSTAINED", magnitude=0.6)
    # Khazix
    add("Khazix", "W", "DUELHEAL", "PERIODIC", magnitude=0.3, cond=True)
    # Kindred
    add("Kindred", "P", "RAMP", "SUSTAINED", magnitude=0.6)
    add("Kindred", "W", "RAMP", "SUSTAINED", magnitude=0.55)
    add("Kindred", "R", "ENDURE", "BURST", magnitude=0.75, cond=True)
    # Kled
    add("Kled", "P", "ENDURE", "BURST", magnitude=0.8)
    add("Kled", "P", "RAMP", "BURST", magnitude=0.55)
    # KogMaw
    add("KogMaw", "W", "RAMP", "BURST", magnitude=0.6, cond=True)
    # LeeSin
    add("LeeSin", "P", "RESET", "SUSTAINED", magnitude=0.4)
    add("LeeSin", "W", "DUELHEAL", "BURST", magnitude=0.55)
    add("LeeSin", "W", "ENDURE", "BURST", magnitude=0.45)
    # Lillia
    add("Lillia", "P", "DUELHEAL", "SUSTAINED", magnitude=0.45)
    # Lissandra
    add("Lissandra", "R", "DUELHEAL", "BURST", magnitude=0.5, cond=True)
    # Maokai
    add("Maokai", "P", "DUELHEAL", "PERIODIC", magnitude=0.55)
    add("Maokai", "W", "DUELHEAL", "PERIODIC", magnitude=0.5)
    # MasterYi
    add("MasterYi", "P", "RAMP", "SUSTAINED", magnitude=0.7)
    add("MasterYi", "Q", "RESET", "SUSTAINED", magnitude=0.45)
    add("MasterYi", "W", "DUELHEAL", "BURST", magnitude=0.8)
    add("MasterYi", "W", "ENDURE", "BURST", magnitude=0.65)
    add("MasterYi", "E", "RAMP", "SUSTAINED", magnitude=0.75)
    add("MasterYi", "R", "RAMP", "BURST", magnitude=0.8, cond=True)
    # MonkeyKing
    add("MonkeyKing", "P", "RAMP", "SUSTAINED", magnitude=0.62, cond=True)
    add("MonkeyKing", "P", "DUELHEAL", "PERIODIC", magnitude=0.45, cond=True)
    add("MonkeyKing", "Q", "RAMP", "PERIODIC", magnitude=0.42)
    add("MonkeyKing", "R", "ENDURE", "BURST", magnitude=0.5)
    # Mordekaiser
    add("Mordekaiser", "P", "RAMP", "SUSTAINED", magnitude=0.85)
    add("Mordekaiser", "W", "DUELHEAL", "PERIODIC", magnitude=0.6, cond=True)
    add("Mordekaiser", "R", "ENDURE", "BURST", magnitude=0.9, cond=True)
    # Morgana
    add("Morgana", "P", "DUELHEAL", "SUSTAINED", magnitude=0.35)
    add("Morgana", "E", "ENDURE", "BURST", magnitude=0.4, cond=True)
    # Nasus
    add("Nasus", "Q", "RAMP", "SUSTAINED", magnitude=0.95)
    add("Nasus", "R", "DUELHEAL", "SUSTAINED", magnitude=0.8, cond=True)
    add("Nasus", "R", "RAMP", "SUSTAINED", magnitude=0.7, cond=True)
    # Nidalee
    add("Nidalee", "E", "DUELHEAL", "PERIODIC", magnitude=0.5, cond=True)
    add("Nidalee", "R", "RESET", "PERIODIC", magnitude=0.65, cond=True)
    # Nilah
    add("Nilah", "Q", "DUELHEAL", "SUSTAINED", magnitude=0.65, cond=True)
    add("Nilah", "W", "ENDURE", "BURST", magnitude=0.5)
    add("Nilah", "R", "DUELHEAL", "BURST", magnitude=0.55, cond=True)
    # Nocturne
    add("Nocturne", "P", "DUELHEAL", "SUSTAINED", magnitude=0.62)
    add("Nocturne", "Q", "RAMP", "SUSTAINED", magnitude=0.5)
    add("Nocturne", "W", "ENDURE", "BURST", magnitude=0.52, cond=True)
    # Nunu
    add("Nunu", "Q", "DUELHEAL", "PERIODIC", magnitude=0.45)
    # Olaf
    add("Olaf", "P", "RAMP", "SUSTAINED", magnitude=0.8)
    add("Olaf", "W", "DUELHEAL", "BURST", magnitude=0.65)
    add("Olaf", "E", "RAMP", "PERIODIC", magnitude=0.6)
    add("Olaf", "R", "ENDURE", "BURST", magnitude=0.85, cond=True)
    # Ornn
    add("Ornn", "P", "RESET", "PERIODIC", magnitude=0.5)
    add("Ornn", "W", "ENDURE", "BURST", magnitude=0.55, cond=True)
    # Pantheon
    add("Pantheon", "P", "RESET", "PERIODIC", magnitude=0.6)
    add("Pantheon", "E", "ENDURE", "BURST", magnitude=0.55)
    # Poppy
    add("Poppy", "P", "ENDURE", "PERIODIC", magnitude=0.45)
    add("Poppy", "W", "ENDURE", "SUSTAINED", magnitude=0.4)
    # Pyke
    add("Pyke", "P", "DUELHEAL", "BURST", magnitude=0.4, cond=True)
    add("Pyke", "R", "RESET", "BURST", magnitude=0.55, cond=True)
    # Rammus
    add("Rammus", "W", "ENDURE", "SUSTAINED", magnitude=0.75)
    # RekSai
    add("RekSai", "P", "DUELHEAL", "PERIODIC", magnitude=0.55, cond=True)
    add("RekSai", "E", "RAMP", "PERIODIC", magnitude=0.6, cond=True)
    # Rell
    add("Rell", "P", "RAMP", "SUSTAINED", magnitude=0.5)
    # Renekton
    add("Renekton", "P", "RAMP", "SUSTAINED", magnitude=0.7)
    add("Renekton", "Q", "DUELHEAL", "PERIODIC", magnitude=0.72)
    add("Renekton", "E", "RESET", "PERIODIC", magnitude=0.65)
    # Rengar
    add("Rengar", "Q", "RESET", "PERIODIC", magnitude=0.6)
    add("Rengar", "W", "DUELHEAL", "PERIODIC", magnitude=0.65)
    add("Rengar", "W", "ENDURE", "PERIODIC", magnitude=0.5)
    add("Rengar", "BASE", "RAMP", "SUSTAINED", magnitude=0.55)
    # Riven
    add("Riven", "Q", "RESET", "PERIODIC", magnitude=0.75)
    add("Riven", "E", "ENDURE", "PERIODIC", magnitude=0.6)
    add("Riven", "R", "RAMP", "BURST", magnitude=0.65)
    add("Riven", "BASE", "ENDURE", "SUSTAINED", magnitude=0.4)
    # Rumble
    add("Rumble", "P", "RAMP", "PERIODIC", magnitude=0.7)
    add("Rumble", "W", "ENDURE", "BURST", magnitude=0.45)
    add("Rumble", "BASE", "ENDURE", "SUSTAINED", magnitude=0.55)
    # Ryze
    add("Ryze", "BASE", "RESET", "PERIODIC", magnitude=0.6)
    # Samira
    add("Samira", "P", "RAMP", "SUSTAINED", magnitude=0.72)
    add("Samira", "W", "ENDURE", "BURST", magnitude=0.55)
    add("Samira", "R", "RESET", "BURST", magnitude=0.68, cond=True)
    # Sejuani
    add("Sejuani", "P", "ENDURE", "SUSTAINED", magnitude=0.55)
    # Senna
    add("Senna", "P", "RAMP", "SUSTAINED", magnitude=0.35)
    add("Senna", "Q", "DUELHEAL", "PERIODIC", magnitude=0.45)
    add("Senna", "R", "DUELHEAL", "BURST", magnitude=0.5, cond=True)
    # Sett
    add("Sett", "P", "DUELHEAL", "PERIODIC", magnitude=0.5, cond=True)
    add("Sett", "Q", "RESET", "PERIODIC", magnitude=0.4)
    add("Sett", "W", "ENDURE", "BURST", magnitude=0.75)
    # Shaco
    add("Shaco", "R", "ENDURE", "BURST", magnitude=0.58, cond=True)
    # Shen
    add("Shen", "P", "ENDURE", "PERIODIC", magnitude=0.55)
    add("Shen", "Q", "RESET", "PERIODIC", magnitude=0.45)
    add("Shen", "W", "ENDURE", "BURST", magnitude=0.55)
    # Shyvana
    add("Shyvana", "P", "ENDURE", "SUSTAINED", magnitude=0.55)
    add("Shyvana", "R", "RAMP", "BURST", magnitude=0.7, cond=True)
    add("Shyvana", "BASE", "RAMP", "SUSTAINED", magnitude=0.5)
    # Singed
    add("Singed", "Q", "ENDURE", "SUSTAINED", magnitude=0.65)
    add("Singed", "R", "ENDURE", "BURST", magnitude=0.75, cond=True)
    add("Singed", "R", "DUELHEAL", "BURST", magnitude=0.6, cond=True)
    # Sion
    add("Sion", "P", "ENDURE", "BURST", magnitude=0.55, cond=True)
    add("Sion", "W", "ENDURE", "BURST", magnitude=0.65)
    # Sivir
    add("Sivir", "E", "ENDURE", "BURST", magnitude=0.4)
    # Skarner
    add("Skarner", "P", "RAMP", "SUSTAINED", magnitude=0.65, cond=True)
    add("Skarner", "Q", "RESET", "PERIODIC", magnitude=0.5)
    add("Skarner", "W", "ENDURE", "PERIODIC", magnitude=0.5)
    # Smolder
    add("Smolder", "P", "RAMP", "SUSTAINED", magnitude=0.4)
    add("Smolder", "R", "DUELHEAL", "BURST", magnitude=0.4, cond=True)
    # Soraka
    add("Soraka", "Q", "DUELHEAL", "PERIODIC", magnitude=0.35, cond=True)
    # Swain
    add("Swain", "P", "RAMP", "SUSTAINED", magnitude=0.65)
    add("Swain", "R", "DUELHEAL", "SUSTAINED", magnitude=0.88, cond=True)
    add("Swain", "R", "RAMP", "SUSTAINED", magnitude=0.6, cond=True)
    # Sylas
    add("Sylas", "P", "RESET", "SUSTAINED", magnitude=0.65)
    add("Sylas", "W", "DUELHEAL", "PERIODIC", magnitude=0.75)
    add("Sylas", "E", "RESET", "PERIODIC", magnitude=0.45)
    # TahmKench
    add("TahmKench", "E", "ENDURE", "PERIODIC", magnitude=0.65)
    # Taric
    add("Taric", "P", "RESET", "SUSTAINED", magnitude=0.5)
    add("Taric", "Q", "DUELHEAL", "PERIODIC", magnitude=0.5)
    # Teemo
    add("Teemo", "Q", "ENDURE", "PERIODIC", magnitude=0.55)
    add("Teemo", "E", "RAMP", "SUSTAINED", magnitude=0.45)
    # Tristana
    add("Tristana", "Q", "RAMP", "BURST", magnitude=0.55)
    add("Tristana", "E", "RAMP", "PERIODIC", magnitude=0.6)
    # Trundle
    add("Trundle", "Q", "RAMP", "PERIODIC", magnitude=0.78)
    add("Trundle", "W", "ENDURE", "BURST", magnitude=0.55)
    add("Trundle", "W", "DUELHEAL", "SUSTAINED", magnitude=0.5)
    add("Trundle", "R", "RAMP", "BURST", magnitude=0.85)
    add("Trundle", "R", "DUELHEAL", "SUSTAINED", magnitude=0.75)
    # Tryndamere
    add("Tryndamere", "P", "RAMP", "SUSTAINED", magnitude=0.85)
    add("Tryndamere", "Q", "RAMP", "SUSTAINED", magnitude=0.5)
    add("Tryndamere", "Q", "DUELHEAL", "BURST", magnitude=0.7)
    add("Tryndamere", "E", "RESET", "PERIODIC", magnitude=0.45)
    add("Tryndamere", "R", "ENDURE", "BURST", magnitude=0.95, cond=True)
    add("Tryndamere", "R", "RAMP", "BURST", magnitude=0.6, cond=True)
    # Twitch
    add("Twitch", "P", "RAMP", "SUSTAINED", magnitude=0.4)
    add("Twitch", "Q", "RAMP", "BURST", magnitude=0.5)
    # Udyr
    add("Udyr", "Q", "RAMP", "SUSTAINED", magnitude=0.6)
    add("Udyr", "W", "DUELHEAL", "PERIODIC", magnitude=0.65, cond=True)
    add("Udyr", "W", "ENDURE", "PERIODIC", magnitude=0.5)
    add("Udyr", "BASE", "RESET", "SUSTAINED", magnitude=0.55)
    # Urgot
    add("Urgot", "P", "RESET", "PERIODIC", magnitude=0.55)
    add("Urgot", "W", "RAMP", "SUSTAINED", magnitude=0.8)
    add("Urgot", "W", "ENDURE", "BURST", magnitude=0.58)
    # Varus
    add("Varus", "W", "RAMP", "SUSTAINED", magnitude=0.45)
    # Vayne
    add("Vayne", "Q", "RESET", "PERIODIC", magnitude=0.65)
    add("Vayne", "W", "RAMP", "SUSTAINED", magnitude=0.9)
    add("Vayne", "R", "RESET", "BURST", magnitude=0.8, cond=True)
    # Vi
    add("Vi", "P", "ENDURE", "PERIODIC", magnitude=0.5)
    add("Vi", "W", "RAMP", "SUSTAINED", magnitude=0.65)
    # Viego
    add("Viego", "P", "RESET", "BURST", magnitude=0.7, cond=True)
    add("Viego", "Q", "DUELHEAL", "PERIODIC", magnitude=0.75, cond=True)
    # Viktor
    add("Viktor", "Q", "ENDURE", "PERIODIC", magnitude=0.35)
    # Vladimir
    add("Vladimir", "Q", "DUELHEAL", "PERIODIC", magnitude=0.75)
    add("Vladimir", "W", "ENDURE", "BURST", magnitude=0.7)
    add("Vladimir", "W", "DUELHEAL", "BURST", magnitude=0.65)
    add("Vladimir", "E", "RAMP", "PERIODIC", magnitude=0.6)
    # Volibear
    add("Volibear", "P", "RAMP", "PERIODIC", magnitude=0.68, cond=True)
    add("Volibear", "W", "DUELHEAL", "PERIODIC", magnitude=0.72)
    add("Volibear", "R", "ENDURE", "BURST", magnitude=0.55)
    # Warwick
    add("Warwick", "P", "DUELHEAL", "SUSTAINED", magnitude=0.9, cond=True)
    add("Warwick", "Q", "DUELHEAL", "PERIODIC", magnitude=0.65)
    add("Warwick", "W", "RAMP", "SUSTAINED", magnitude=0.7, cond=True)
    add("Warwick", "E", "ENDURE", "PERIODIC", magnitude=0.5)
    add("Warwick", "R", "ENDURE", "BURST", magnitude=0.6)
    # Xayah
    add("Xayah", "W", "RAMP", "BURST", magnitude=0.55)
    add("Xayah", "W", "DUELHEAL", "BURST", magnitude=0.5)
    add("Xayah", "R", "ENDURE", "BURST", magnitude=0.6, cond=True)
    # XinZhao
    add("XinZhao", "P", "DUELHEAL", "SUSTAINED", magnitude=0.7)
    add("XinZhao", "Q", "RESET", "PERIODIC", magnitude=0.65)
    add("XinZhao", "E", "RAMP", "BURST", magnitude=0.5)
    # Yasuo
    add("Yasuo", "P", "ENDURE", "SUSTAINED", magnitude=0.65)
    add("Yasuo", "W", "ENDURE", "BURST", magnitude=0.58)
    add("Yasuo", "E", "RESET", "SUSTAINED", magnitude=0.7)
    add("Yasuo", "R", "RESET", "BURST", magnitude=0.62, cond=True)
    # Yone
    add("Yone", "P", "RAMP", "SUSTAINED", magnitude=0.6)
    add("Yone", "Q", "RESET", "SUSTAINED", magnitude=0.65)
    add("Yone", "W", "ENDURE", "PERIODIC", magnitude=0.45)
    add("Yone", "E", "ENDURE", "BURST", magnitude=0.75)
    # Yorick
    add("Yorick", "P", "RAMP", "SUSTAINED", magnitude=0.6)
    add("Yorick", "Q", "DUELHEAL", "PERIODIC", magnitude=0.55)
    add("Yorick", "E", "ENDURE", "PERIODIC", magnitude=0.45)
    add("Yorick", "R", "RAMP", "SUSTAINED", magnitude=0.75)
    # Zac
    add("Zac", "P", "DUELHEAL", "PERIODIC", magnitude=0.4, cond=True)
    add("Zac", "W", "RAMP", "SUSTAINED", magnitude=0.45)
    # Zeri
    add("Zeri", "E", "RESET", "SUSTAINED", magnitude=0.5)
    add("Zeri", "R", "RAMP", "BURST", magnitude=0.7, cond=True)
    # Zilean
    add("Zilean", "R", "ENDURE", "BURST", magnitude=0.55, cond=True)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_EXTENDEDDUEL_REGISTRY: dict[str, tuple[ExtendedDuelEntry, ...]] = (
    _build_extendedduel_registry()
)


@dataclass(frozen=True)
class ExtendedDuelSourceEntry:
    """One scored extended-duel mechanism for a champion."""

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
class ExtendedDuelResult:
    """Aggregate extended-duel / 1v1 attrition power for one champion.

    ``duel_score`` sums every mechanism's kind-weighted, cadence-scaled value
    (higher = wins the long duel harder). ``top_kind`` is the kind of the single
    highest-value mechanism (the champion's strongest duel tool, ``""`` when none).
    ``ramps`` is True when at least one RAMP mechanism contributes - the flag a
    draft / matchup consumer keys on (the champion gets STRONGER the longer the
    fight runs, so do not commit to a long 1v1 against her). Returns all-zero with
    an empty ``sources`` tuple for an unregistered or blank champion (never
    raises); the axis is selective, so a zero score is the correct, common answer
    for a burst / artillery / utility champion with no attrition tools.
    """

    champion: str
    mode: str
    duel_score: float
    top_kind: str
    ramps: bool
    sources: tuple[ExtendedDuelSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "duel_score": round(self.duel_score, 4),
            "top_kind": self.top_kind,
            "ramps": self.ramps,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> ExtendedDuelResult:
    return ExtendedDuelResult(
        champion=champion,
        mode=mode,
        duel_score=0.0,
        top_kind="",
        ramps=False,
        sources=(),
    )


def _source_sort_key(entry: ExtendedDuelEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_extendedduel(champion: str, mode: str = "SR") -> ExtendedDuelResult:
    """Aggregate a champion's extended-duel mechanisms into a 1v1 attrition score.

    Reads ``_EXTENDEDDUEL_REGISTRY``. Each registered mechanism contributes a
    kind-weighted, cadence-scaled value (``_mechanism_value``); the values are
    summed into ``duel_score``. ``top_kind`` is the kind of the highest-value
    mechanism; ``ramps`` is True when any RAMP mechanism contributes. ``mode`` is
    carried on the result for parity with the other scorers but does not change
    output today (extended-duel kit value is map-independent).

    Returns an all-zero ``ExtendedDuelResult`` (empty ``sources``) when the
    champion is blank / None or absent from the (selective) registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _EXTENDEDDUEL_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[ExtendedDuelSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    has_ramp = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.kind == "RAMP":
            has_ramp = True
        scored.append(
            ExtendedDuelSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                cadence=entry.cadence,
                kind_weight=_EXTENDEDDUEL_KIND_WEIGHT.get(entry.kind, 0.0),
                cadence_mult=_EXTENDEDDUEL_CADENCE_MULT.get(entry.cadence, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return ExtendedDuelResult(
        champion=champion,
        mode=safe_mode,
        duel_score=total,
        top_kind=best_kind if total > 0.0 else "",
        ramps=has_ramp,
        sources=tuple(scored),
    )


__all__ = [
    "ExtendedDuelEntry",
    "ExtendedDuelResult",
    "ExtendedDuelSourceEntry",
    "compute_extendedduel",
    "_EXTENDEDDUEL_KIND_WEIGHT",
    "_EXTENDEDDUEL_CADENCE_MULT",
    "_EXTENDEDDUEL_CONDITIONAL_PROB",
    "_EXTENDEDDUEL_REGISTRY",
]
