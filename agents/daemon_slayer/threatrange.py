"""Effective threat-range scorer (ENGINE 1.113.0, item 301).

The twelfth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / the six
archetype scorers. It quantifies how FAR OUT a champion can deliver meaningful
damage or CC - the poke / siege / safe-DPS-distance dimension the prior eleven
axes never measured (they score WHAT a champion does in a fight; this one scores
from HOW FAR AWAY it can do it).

A high score means a champion who threatens real damage or a pick from screens
away and never has to enter melee range to influence a fight (Xerath / Ziggs /
Velkoz / Caitlyn / Jinx / Lux / Nidalee); a low score means a champion who must
close to melee to do anything (Garen / Master Yi / Udyr / Warwick / Olaf /
most juggernauts and melee assassins).

Purely ADDITIVE: a new standalone scorer and a new ``/threat-range`` route. It
reads no existing scorer and is read by none, so every existing route is
byte-identical (the opt-in is the new endpoint itself - inert until a caller
invokes it, the section-5 "default inert" contract for a brand-new surface).
Wiring it into a live poke / siege / draft-range coach surface is the separate
Phase-D step.

Model (each threatening MECHANISM a champion owns contributes a reach-weighted,
threat-typed value; the headline is their sum):
  * a per-(champion, source) ``ThreatRangeEntry`` tags one mechanism with a
    ``band`` (key of ``_THREATRANGE_BAND_WEIGHT`` - how FAR it reaches: GLOBAL /
    ARTILLERY / LONG / MEDIUM / SHORT / MELEE), a ``kind`` (key of
    ``_THREATRANGE_KIND_MULT`` - WHAT the threat is at that range: BURST / CC /
    SUSTAINED / POKE), a ``magnitude`` (0..1 how much of the champion's threat
    this one mechanism carries / how reliably it lands at that range), and a
    ``conditional`` flag (needs the ult up / a charge / a setup).
  * ``compute_threatrange`` folds every mechanism into a single
    ``threatrange_score`` = sum of ``band_weight * kind_mult * magnitude`` (times
    the conditional midpoint when gated). ``top_band`` labels the band of the
    single highest-value mechanism (the champion's longest REAL threat);
    ``is_artillery`` is True when any ARTILLERY/GLOBAL-band mechanism contributes
    (the long-siege identity a poke consumer keys on).

Bands, kinds and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-301 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Reach-band -> weight. Hand-authored, operator-tunable. Six tiers by how far
# the threatening mechanism reaches (League range units in the gloss):
#   1.10 GLOBAL    - cross-map / screens-away, a threat from the other side of
#                    the map (Ezreal R / Jinx R / Ashe R / Draven R / Senna R /
#                    Karthus R / TwistedFate R / Pantheon R); the longest reach.
#   1.00 ARTILLERY - 1000+ unit poke / siege, out-ranges everything on the rift
#                    (Xerath Q/W/R / Ziggs Q/R / Velkoz / Lux Q/R / Nidalee Q /
#                    Caitlyn R / Jayce Q / Varus Q); the siege identity.
#   0.75 LONG      - ~700-1000, most skillshot mages + long-range ADC autos
#                    (Morgana Q / Lux E / Brand / Orianna / Ahri Q / Caitlyn Q /
#                    Senna / Jhin); reaches well past a screen-edge fight.
#   0.50 MEDIUM    - ~500-700, standard caster range / short ADC autos / point-
#                    blank-ish casts (Syndra / Annie / Viktor / Twitch / Kaisa).
#   0.30 SHORT     - ~300-500, melee-extended: dash-in casts, short pokes, a
#                    bruiser Q that out-reaches an auto (Renekton / Riven /
#                    Katarina / Camille / Irelia).
#   0.15 MELEE     - <300, must be in melee range to threaten anything at all
#                    (Garen / MasterYi / Udyr / Warwick / Olaf / most juggernauts
#                    and melee assassins); a LOW-reach signal.
_THREATRANGE_BAND_WEIGHT: dict[str, float] = {
    "GLOBAL": 1.1,
    "ARTILLERY": 1.0,
    "LONG": 0.75,
    "MEDIUM": 0.5,
    "SHORT": 0.3,
    "MELEE": 0.15,
}

# Threat-kind -> multiplier. WHAT the mechanism threatens at its range. A burst
# commitment or a CC pick from range is a full threat; a sustained-DPS poke is
# nearly so; a chip-only poke is discounted (it pressures but does not kill or
# lock down on its own).
_THREATRANGE_KIND_MULT: dict[str, float] = {
    "BURST": 1.0,
    "CC": 1.0,
    "SUSTAINED": 0.9,
    "POKE": 0.7,
}

# A gated (conditional) threat - one that needs the ult up, a charge / stack, or
# a setup (a mark, a tether, a primed passive) - is credited at this availability
# midpoint, the waveclear / sustain / scaling shape.
_THREATRANGE_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class ThreatRangeEntry:
    """One registry row: a champion threatening mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = a threat
    identity not tied to one ability, e.g. an inherent long auto-attack range).
    ``band`` is a key of ``_THREATRANGE_BAND_WEIGHT``. ``kind`` is a key of
    ``_THREATRANGE_KIND_MULT``. ``magnitude`` is the 0..1 share of the champion's
    threat this one mechanism carries (how reliably it lands at that range).
    ``conditional`` is True when the mechanism only fires on a gate (ult up,
    charge / stack accrued, a setup primed).
    """

    source: str
    band: str
    kind: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: ThreatRangeEntry) -> float:
    """Reach-weighted, threat-typed value for one mechanism (0 if unknown).

    Returns ``band_weight * kind_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the band or kind is unknown.
    """
    weight = _THREATRANGE_BAND_WEIGHT.get(entry.band, 0.0)
    kind_mult = _THREATRANGE_KIND_MULT.get(entry.kind, 0.0)
    if weight <= 0.0 or kind_mult <= 0.0:
        return 0.0
    value = weight * kind_mult * entry.magnitude
    if entry.conditional:
        value *= _THREATRANGE_CONDITIONAL_PROB
    return value


def _build_threatrange_registry() -> dict[str, tuple[ThreatRangeEntry, ...]]:
    """Build champion_id -> tuple[ThreatRangeEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several threatening mechanisms without dict-literal collision (the waveclear
    / scaling / sustain / mobility builder pattern). Runs ONCE at import.
    """
    raw: dict[str, list[ThreatRangeEntry]] = {}

    def add(
        champ: str,
        source: str,
        band: str,
        kind: str,
        *,
        magnitude: float,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            ThreatRangeEntry(
                source=source,
                band=band,
                kind=kind,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "Q", "SHORT", "BURST", magnitude=0.85)
    add("Aatrox", "W", "MELEE", "CC", magnitude=0.5)
    add("Aatrox", "E", "SHORT", "BURST", magnitude=0.4)
    add("Aatrox", "R", "SHORT", "BURST", magnitude=0.75, cond=True)
    add("Aatrox", "BASE", "MELEE", "SUSTAINED", magnitude=0.7)
    # Ahri
    add("Ahri", "Q", "LONG", "POKE", magnitude=0.7)
    add("Ahri", "W", "SHORT", "BURST", magnitude=0.45)
    add("Ahri", "E", "LONG", "CC", magnitude=0.8)
    add("Ahri", "R", "SHORT", "BURST", magnitude=0.9, cond=True)
    add("Ahri", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.2)
    # Akali
    add("Akali", "Q", "SHORT", "POKE", magnitude=0.55)
    add("Akali", "W", "SHORT", "CC", magnitude=0.3)
    add("Akali", "E", "SHORT", "BURST", magnitude=0.6)
    add("Akali", "R", "SHORT", "BURST", magnitude=0.85, cond=True)
    add("Akali", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Akshan
    add("Akshan", "P", "MEDIUM", "SUSTAINED", magnitude=0.4)
    add("Akshan", "Q", "ARTILLERY", "POKE", magnitude=0.55)
    add("Akshan", "E", "SHORT", "BURST", magnitude=0.3)
    add("Akshan", "R", "GLOBAL", "BURST", magnitude=0.8, cond=True)
    # Alistar
    add("Alistar", "Q", "MELEE", "CC", magnitude=0.75)
    add("Alistar", "W", "SHORT", "CC", magnitude=0.7)
    add("Alistar", "E", "MELEE", "CC", magnitude=0.5, cond=True)
    add("Alistar", "BASE", "MELEE", "SUSTAINED", magnitude=0.3)
    # Ambessa
    add("Ambessa", "Q", "SHORT", "BURST", magnitude=0.6)
    add("Ambessa", "W", "SHORT", "BURST", magnitude=0.45)
    add("Ambessa", "E", "SHORT", "BURST", magnitude=0.5)
    add("Ambessa", "R", "SHORT", "BURST", magnitude=0.85, cond=True)
    add("Ambessa", "BASE", "MELEE", "SUSTAINED", magnitude=0.6)
    # Amumu
    add("Amumu", "Q", "ARTILLERY", "CC", magnitude=0.85)
    add("Amumu", "W", "SHORT", "SUSTAINED", magnitude=0.5)
    add("Amumu", "E", "SHORT", "BURST", magnitude=0.4)
    add("Amumu", "R", "MEDIUM", "CC", magnitude=0.9, cond=True)
    # Anivia
    add("Anivia", "Q", "LONG", "CC", magnitude=0.65)
    add("Anivia", "W", "LONG", "CC", magnitude=0.35)
    add("Anivia", "E", "MEDIUM", "BURST", magnitude=0.6, cond=True)
    add("Anivia", "R", "MEDIUM", "SUSTAINED", magnitude=0.7, cond=True)
    add("Anivia", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.25)
    # Annie
    add("Annie", "P", "MEDIUM", "CC", magnitude=0.55, cond=True)
    add("Annie", "Q", "MEDIUM", "BURST", magnitude=0.85)
    add("Annie", "W", "MEDIUM", "BURST", magnitude=0.65)
    add("Annie", "R", "MEDIUM", "BURST", magnitude=0.75, cond=True)
    # Aphelios
    add("Aphelios", "Q", "ARTILLERY", "POKE", magnitude=0.75, cond=True)
    add("Aphelios", "W", "MEDIUM", "BURST", magnitude=0.55, cond=True)
    add("Aphelios", "R", "ARTILLERY", "BURST", magnitude=0.8, cond=True)
    add("Aphelios", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Ashe
    add("Ashe", "P", "MEDIUM", "CC", magnitude=0.65)
    add("Ashe", "Q", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Ashe", "W", "LONG", "POKE", magnitude=0.55)
    add("Ashe", "R", "GLOBAL", "CC", magnitude=0.9, cond=True)
    add("Ashe", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.75)
    # AurelionSol
    add("AurelionSol", "Q", "LONG", "POKE", magnitude=0.65)
    add("AurelionSol", "W", "LONG", "BURST", magnitude=0.5)
    add("AurelionSol", "E", "LONG", "CC", magnitude=0.55)
    add("AurelionSol", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("AurelionSol", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.2)
    # Aurora
    add("Aurora", "Q", "MEDIUM", "BURST", magnitude=0.65)
    add("Aurora", "W", "SHORT", "CC", magnitude=0.5)
    add("Aurora", "R", "LONG", "BURST", magnitude=0.8, cond=True)
    add("Aurora", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.35)
    # Azir
    add("Azir", "Q", "ARTILLERY", "POKE", magnitude=0.7)
    add("Azir", "W", "LONG", "SUSTAINED", magnitude=0.75)
    add("Azir", "E", "LONG", "BURST", magnitude=0.4)
    add("Azir", "R", "MEDIUM", "CC", magnitude=0.7, cond=True)
    # Bard
    add("Bard", "P", "MEDIUM", "SUSTAINED", magnitude=0.45)
    add("Bard", "Q", "LONG", "CC", magnitude=0.8)
    add("Bard", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    add("Bard", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.3)
    # Belveth
    add("Belveth", "Q", "SHORT", "BURST", magnitude=0.6)
    add("Belveth", "W", "SHORT", "CC", magnitude=0.4)
    add("Belveth", "E", "MELEE", "SUSTAINED", magnitude=0.45)
    add("Belveth", "R", "MELEE", "BURST", magnitude=0.7, cond=True)
    add("Belveth", "BASE", "MELEE", "SUSTAINED", magnitude=0.7)
    # Blitzcrank
    add("Blitzcrank", "Q", "ARTILLERY", "CC", magnitude=0.9)
    add("Blitzcrank", "E", "MELEE", "CC", magnitude=0.7)
    add("Blitzcrank", "R", "MEDIUM", "BURST", magnitude=0.5, cond=True)
    # Brand
    add("Brand", "Q", "LONG", "CC", magnitude=0.7, cond=True)
    add("Brand", "W", "LONG", "BURST", magnitude=0.6)
    add("Brand", "E", "MEDIUM", "BURST", magnitude=0.45)
    add("Brand", "R", "LONG", "BURST", magnitude=0.8, cond=True)
    # Braum
    add("Braum", "P", "MELEE", "CC", magnitude=0.5, cond=True)
    add("Braum", "Q", "LONG", "CC", magnitude=0.75)
    add("Braum", "E", "MEDIUM", "CC", magnitude=0.4)
    add("Braum", "R", "LONG", "CC", magnitude=0.8, cond=True)
    # Briar
    add("Briar", "W", "SHORT", "SUSTAINED", magnitude=0.8)
    add("Briar", "E", "SHORT", "CC", magnitude=0.55)
    add("Briar", "R", "GLOBAL", "BURST", magnitude=0.7, cond=True)
    add("Briar", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Caitlyn
    add("Caitlyn", "Q", "ARTILLERY", "POKE", magnitude=0.75)
    add("Caitlyn", "W", "LONG", "CC", magnitude=0.35)
    add("Caitlyn", "E", "LONG", "CC", magnitude=0.35)
    add("Caitlyn", "R", "ARTILLERY", "BURST", magnitude=0.7, cond=True)
    add("Caitlyn", "BASE", "LONG", "SUSTAINED", magnitude=0.8)
    # Camille
    add("Camille", "Q", "MELEE", "BURST", magnitude=0.5)
    add("Camille", "W", "LONG", "POKE", magnitude=0.4)
    add("Camille", "E", "LONG", "CC", magnitude=0.75)
    add("Camille", "R", "SHORT", "CC", magnitude=0.7, cond=True)
    add("Camille", "BASE", "MELEE", "SUSTAINED", magnitude=0.3)
    # Cassiopeia
    add("Cassiopeia", "Q", "LONG", "POKE", magnitude=0.6)
    add("Cassiopeia", "W", "LONG", "CC", magnitude=0.45)
    add("Cassiopeia", "E", "MEDIUM", "SUSTAINED", magnitude=0.9)
    add("Cassiopeia", "R", "MEDIUM", "CC", magnitude=0.8, cond=True)
    add("Cassiopeia", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.3)
    # Chogath
    add("Chogath", "Q", "LONG", "CC", magnitude=0.75)
    add("Chogath", "W", "MEDIUM", "CC", magnitude=0.65)
    add("Chogath", "E", "MEDIUM", "POKE", magnitude=0.4)
    add("Chogath", "R", "MELEE", "BURST", magnitude=0.85, cond=True)
    # Corki
    add("Corki", "P", "MEDIUM", "SUSTAINED", magnitude=0.5)
    add("Corki", "Q", "LONG", "POKE", magnitude=0.55)
    add("Corki", "W", "SHORT", "BURST", magnitude=0.45)
    add("Corki", "E", "MEDIUM", "SUSTAINED", magnitude=0.5)
    add("Corki", "R", "ARTILLERY", "POKE", magnitude=0.8)
    add("Corki", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Darius
    add("Darius", "Q", "SHORT", "BURST", magnitude=0.7)
    add("Darius", "E", "MEDIUM", "CC", magnitude=0.65)
    add("Darius", "R", "SHORT", "BURST", magnitude=0.9, cond=True)
    add("Darius", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Diana
    add("Diana", "P", "MELEE", "BURST", magnitude=0.45)
    add("Diana", "Q", "LONG", "POKE", magnitude=0.55)
    add("Diana", "W", "MELEE", "BURST", magnitude=0.35)
    add("Diana", "E", "SHORT", "BURST", magnitude=0.6, cond=True)
    add("Diana", "R", "SHORT", "CC", magnitude=0.8, cond=True)
    # DrMundo
    add("DrMundo", "Q", "LONG", "POKE", magnitude=0.6)
    add("DrMundo", "W", "SHORT", "SUSTAINED", magnitude=0.4)
    add("DrMundo", "E", "MELEE", "SUSTAINED", magnitude=0.55)
    add("DrMundo", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Draven
    add("Draven", "Q", "MEDIUM", "SUSTAINED", magnitude=0.8)
    add("Draven", "E", "LONG", "CC", magnitude=0.65)
    add("Draven", "R", "GLOBAL", "BURST", magnitude=0.7, cond=True)
    add("Draven", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.7)
    # Ekko
    add("Ekko", "Q", "LONG", "POKE", magnitude=0.6)
    add("Ekko", "W", "ARTILLERY", "CC", magnitude=0.45)
    add("Ekko", "E", "SHORT", "BURST", magnitude=0.65)
    add("Ekko", "R", "SHORT", "BURST", magnitude=0.8, cond=True)
    # Elise
    add("Elise", "Q", "MEDIUM", "BURST", magnitude=0.65)
    add("Elise", "W", "LONG", "POKE", magnitude=0.3)
    add("Elise", "E", "LONG", "CC", magnitude=0.7)
    add("Elise", "R", "SHORT", "BURST", magnitude=0.55, cond=True)
    # Evelynn
    add("Evelynn", "Q", "LONG", "POKE", magnitude=0.55)
    add("Evelynn", "W", "LONG", "CC", magnitude=0.5)
    add("Evelynn", "E", "LONG", "BURST", magnitude=0.65)
    add("Evelynn", "R", "SHORT", "BURST", magnitude=0.9, cond=True)
    add("Evelynn", "BASE", "MELEE", "SUSTAINED", magnitude=0.2)
    # Ezreal
    add("Ezreal", "Q", "ARTILLERY", "POKE", magnitude=0.8)
    add("Ezreal", "W", "ARTILLERY", "POKE", magnitude=0.3)
    add("Ezreal", "E", "SHORT", "BURST", magnitude=0.45)
    add("Ezreal", "R", "GLOBAL", "BURST", magnitude=0.65, cond=True)
    # Fiddlesticks
    add("Fiddlesticks", "Q", "MEDIUM", "CC", magnitude=0.65)
    add("Fiddlesticks", "W", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Fiddlesticks", "E", "MEDIUM", "CC", magnitude=0.5)
    add("Fiddlesticks", "R", "MEDIUM", "BURST", magnitude=0.85, cond=True)
    # Fiora
    add("Fiora", "P", "MELEE", "BURST", magnitude=0.6, cond=True)
    add("Fiora", "Q", "SHORT", "BURST", magnitude=0.75)
    add("Fiora", "W", "LONG", "CC", magnitude=0.5, cond=True)
    add("Fiora", "E", "MELEE", "SUSTAINED", magnitude=0.6)
    add("Fiora", "BASE", "MELEE", "SUSTAINED", magnitude=0.8)
    # Fizz
    add("Fizz", "Q", "MEDIUM", "BURST", magnitude=0.55)
    add("Fizz", "W", "MELEE", "SUSTAINED", magnitude=0.4)
    add("Fizz", "E", "SHORT", "BURST", magnitude=0.5)
    add("Fizz", "R", "ARTILLERY", "CC", magnitude=0.85, cond=True)
    # Galio
    add("Galio", "P", "MELEE", "BURST", magnitude=0.3)
    add("Galio", "Q", "LONG", "BURST", magnitude=0.65)
    add("Galio", "W", "SHORT", "CC", magnitude=0.7)
    add("Galio", "E", "MEDIUM", "CC", magnitude=0.65)
    add("Galio", "R", "GLOBAL", "CC", magnitude=0.85, cond=True)
    # Gangplank
    add("Gangplank", "Q", "MEDIUM", "POKE", magnitude=0.7)
    add("Gangplank", "E", "LONG", "CC", magnitude=0.4)
    add("Gangplank", "R", "GLOBAL", "POKE", magnitude=0.65, cond=True)
    # Garen
    add("Garen", "Q", "MELEE", "CC", magnitude=0.6)
    add("Garen", "E", "MELEE", "SUSTAINED", magnitude=0.85)
    add("Garen", "R", "MELEE", "BURST", magnitude=0.75, cond=True)
    add("Garen", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Gnar
    add("Gnar", "Q", "LONG", "POKE", magnitude=0.7)
    add("Gnar", "W", "LONG", "CC", magnitude=0.35)
    add("Gnar", "E", "SHORT", "CC", magnitude=0.45)
    add("Gnar", "R", "SHORT", "CC", magnitude=0.85, cond=True)
    add("Gnar", "BASE", "SHORT", "SUSTAINED", magnitude=0.55)
    # Gragas
    add("Gragas", "Q", "LONG", "POKE", magnitude=0.6)
    add("Gragas", "W", "MELEE", "SUSTAINED", magnitude=0.4)
    add("Gragas", "E", "SHORT", "CC", magnitude=0.65)
    add("Gragas", "R", "LONG", "CC", magnitude=0.75, cond=True)
    add("Gragas", "BASE", "MELEE", "SUSTAINED", magnitude=0.3)
    # Graves
    add("Graves", "Q", "LONG", "POKE", magnitude=0.6)
    add("Graves", "W", "LONG", "CC", magnitude=0.35)
    add("Graves", "R", "LONG", "BURST", magnitude=0.85, cond=True)
    add("Graves", "BASE", "SHORT", "SUSTAINED", magnitude=0.5)
    # Gwen
    add("Gwen", "Q", "SHORT", "SUSTAINED", magnitude=0.75)
    add("Gwen", "W", "SHORT", "SUSTAINED", magnitude=0.35)
    add("Gwen", "E", "SHORT", "BURST", magnitude=0.5)
    add("Gwen", "R", "LONG", "BURST", magnitude=0.7, cond=True)
    add("Gwen", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Hecarim
    add("Hecarim", "Q", "MELEE", "BURST", magnitude=0.55)
    add("Hecarim", "W", "MEDIUM", "SUSTAINED", magnitude=0.45)
    add("Hecarim", "E", "MEDIUM", "CC", magnitude=0.6)
    add("Hecarim", "R", "LONG", "CC", magnitude=0.8, cond=True)
    # Heimerdinger
    add("Heimerdinger", "Q", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Heimerdinger", "W", "ARTILLERY", "POKE", magnitude=0.7)
    add("Heimerdinger", "E", "LONG", "CC", magnitude=0.65)
    add("Heimerdinger", "R", "ARTILLERY", "BURST", magnitude=0.6, cond=True)
    # Hwei
    add("Hwei", "Q", "ARTILLERY", "BURST", magnitude=0.8)
    add("Hwei", "W", "MEDIUM", "POKE", magnitude=0.3)
    add("Hwei", "E", "LONG", "CC", magnitude=0.55)
    add("Hwei", "R", "LONG", "SUSTAINED", magnitude=0.75, cond=True)
    # Illaoi
    add("Illaoi", "P", "MELEE", "SUSTAINED", magnitude=0.4)
    add("Illaoi", "Q", "LONG", "BURST", magnitude=0.65)
    add("Illaoi", "W", "SHORT", "SUSTAINED", magnitude=0.55)
    add("Illaoi", "E", "LONG", "CC", magnitude=0.75)
    add("Illaoi", "R", "MEDIUM", "BURST", magnitude=0.85, cond=True)
    # Irelia
    add("Irelia", "Q", "SHORT", "BURST", magnitude=0.75)
    add("Irelia", "E", "LONG", "CC", magnitude=0.55)
    add("Irelia", "R", "LONG", "BURST", magnitude=0.55, cond=True)
    add("Irelia", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Ivern
    add("Ivern", "Q", "LONG", "CC", magnitude=0.8)
    add("Ivern", "E", "MEDIUM", "CC", magnitude=0.5)
    add("Ivern", "R", "MEDIUM", "CC", magnitude=0.6, cond=True)
    # Janna
    add("Janna", "Q", "ARTILLERY", "CC", magnitude=0.75)
    add("Janna", "W", "MEDIUM", "CC", magnitude=0.55)
    add("Janna", "R", "SHORT", "CC", magnitude=0.65, cond=True)
    # JarvanIV
    add("JarvanIV", "Q", "LONG", "POKE", magnitude=0.55)
    add("JarvanIV", "W", "SHORT", "CC", magnitude=0.3)
    add("JarvanIV", "E", "LONG", "CC", magnitude=0.6)
    add("JarvanIV", "R", "MEDIUM", "BURST", magnitude=0.65, cond=True)
    add("JarvanIV", "BASE", "MELEE", "SUSTAINED", magnitude=0.35)
    # Jax
    add("Jax", "Q", "LONG", "BURST", magnitude=0.6)
    add("Jax", "W", "MELEE", "BURST", magnitude=0.5)
    add("Jax", "E", "MELEE", "CC", magnitude=0.7)
    add("Jax", "R", "MELEE", "BURST", magnitude=0.7, cond=True)
    add("Jax", "BASE", "MELEE", "SUSTAINED", magnitude=0.6)
    # Jayce
    add("Jayce", "P", "MELEE", "BURST", magnitude=0.6)
    add("Jayce", "Q", "ARTILLERY", "POKE", magnitude=0.75)
    add("Jayce", "W", "MEDIUM", "POKE", magnitude=0.4)
    add("Jayce", "E", "MEDIUM", "CC", magnitude=0.45)
    # Jhin
    add("Jhin", "Q", "MEDIUM", "BURST", magnitude=0.45)
    add("Jhin", "W", "ARTILLERY", "CC", magnitude=0.7)
    add("Jhin", "E", "SHORT", "CC", magnitude=0.35)
    add("Jhin", "R", "GLOBAL", "BURST", magnitude=0.85, cond=True)
    add("Jhin", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Jinx
    add("Jinx", "Q", "LONG", "SUSTAINED", magnitude=0.85)
    add("Jinx", "W", "ARTILLERY", "CC", magnitude=0.7)
    add("Jinx", "E", "LONG", "CC", magnitude=0.5)
    add("Jinx", "R", "GLOBAL", "BURST", magnitude=0.8, cond=True)
    add("Jinx", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.65)
    # KSante
    add("KSante", "Q", "SHORT", "CC", magnitude=0.6)
    add("KSante", "W", "LONG", "CC", magnitude=0.7)
    add("KSante", "E", "MEDIUM", "CC", magnitude=0.45)
    add("KSante", "R", "SHORT", "BURST", magnitude=0.85, cond=True)
    # Kaisa
    add("Kaisa", "Q", "MEDIUM", "BURST", magnitude=0.7)
    add("Kaisa", "W", "ARTILLERY", "POKE", magnitude=0.55)
    add("Kaisa", "R", "GLOBAL", "BURST", magnitude=0.7, cond=True)
    add("Kaisa", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.65)
    # Kalista
    add("Kalista", "Q", "ARTILLERY", "POKE", magnitude=0.6)
    add("Kalista", "E", "MEDIUM", "BURST", magnitude=0.8)
    add("Kalista", "R", "LONG", "CC", magnitude=0.6, cond=True)
    add("Kalista", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.85)
    # Karma
    add("Karma", "Q", "LONG", "POKE", magnitude=0.75)
    add("Karma", "W", "LONG", "CC", magnitude=0.65)
    # Karthus
    add("Karthus", "Q", "LONG", "POKE", magnitude=0.7)
    add("Karthus", "W", "LONG", "CC", magnitude=0.5)
    add("Karthus", "E", "MELEE", "SUSTAINED", magnitude=0.5)
    add("Karthus", "R", "GLOBAL", "BURST", magnitude=0.95, cond=True)
    # Kassadin
    add("Kassadin", "Q", "MEDIUM", "CC", magnitude=0.6)
    add("Kassadin", "W", "MELEE", "SUSTAINED", magnitude=0.35)
    add("Kassadin", "E", "MEDIUM", "CC", magnitude=0.45, cond=True)
    add("Kassadin", "R", "SHORT", "BURST", magnitude=0.85, cond=True)
    # Katarina
    add("Katarina", "Q", "SHORT", "POKE", magnitude=0.45)
    add("Katarina", "E", "SHORT", "BURST", magnitude=0.6)
    add("Katarina", "R", "SHORT", "SUSTAINED", magnitude=0.9, cond=True)
    add("Katarina", "BASE", "MELEE", "SUSTAINED", magnitude=0.2)
    # Kayle
    add("Kayle", "Q", "LONG", "CC", magnitude=0.65)
    add("Kayle", "E", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Kayle", "R", "MEDIUM", "BURST", magnitude=0.85, cond=True)
    add("Kayle", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.55)
    # Kayn
    add("Kayn", "Q", "MELEE", "BURST", magnitude=0.6)
    add("Kayn", "W", "MEDIUM", "CC", magnitude=0.5)
    add("Kayn", "E", "SHORT", "BURST", magnitude=0.35)
    add("Kayn", "R", "MELEE", "BURST", magnitude=0.85, cond=True)
    # Kennen
    add("Kennen", "P", "MEDIUM", "CC", magnitude=0.55, cond=True)
    add("Kennen", "Q", "ARTILLERY", "POKE", magnitude=0.75)
    add("Kennen", "W", "MEDIUM", "CC", magnitude=0.5, cond=True)
    add("Kennen", "E", "SHORT", "BURST", magnitude=0.5)
    add("Kennen", "R", "MELEE", "BURST", magnitude=0.75, cond=True)
    add("Kennen", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.5)
    # Khazix
    add("Khazix", "P", "MELEE", "BURST", magnitude=0.5, cond=True)
    add("Khazix", "Q", "SHORT", "BURST", magnitude=0.75)
    add("Khazix", "W", "LONG", "POKE", magnitude=0.5)
    add("Khazix", "E", "LONG", "BURST", magnitude=0.55)
    # Kindred
    add("Kindred", "Q", "SHORT", "BURST", magnitude=0.5)
    add("Kindred", "W", "LONG", "SUSTAINED", magnitude=0.5)
    add("Kindred", "E", "MEDIUM", "BURST", magnitude=0.65, cond=True)
    add("Kindred", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Kled
    add("Kled", "Q", "LONG", "CC", magnitude=0.55)
    add("Kled", "E", "SHORT", "BURST", magnitude=0.5)
    add("Kled", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    add("Kled", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # KogMaw
    add("KogMaw", "P", "MELEE", "BURST", magnitude=0.3)
    add("KogMaw", "Q", "ARTILLERY", "POKE", magnitude=0.45)
    add("KogMaw", "W", "LONG", "SUSTAINED", magnitude=0.9)
    add("KogMaw", "E", "LONG", "POKE", magnitude=0.5)
    add("KogMaw", "R", "ARTILLERY", "POKE", magnitude=0.65)
    # Leblanc
    add("Leblanc", "Q", "MEDIUM", "BURST", magnitude=0.65)
    add("Leblanc", "W", "MEDIUM", "BURST", magnitude=0.75)
    add("Leblanc", "E", "LONG", "CC", magnitude=0.6)
    add("Leblanc", "R", "MEDIUM", "BURST", magnitude=0.8, cond=True)
    # LeeSin
    add("LeeSin", "Q", "LONG", "BURST", magnitude=0.75)
    add("LeeSin", "E", "SHORT", "CC", magnitude=0.5)
    add("LeeSin", "R", "SHORT", "CC", magnitude=0.8, cond=True)
    add("LeeSin", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Leona
    add("Leona", "Q", "MELEE", "CC", magnitude=0.5)
    add("Leona", "W", "MELEE", "BURST", magnitude=0.3)
    add("Leona", "E", "LONG", "CC", magnitude=0.85)
    add("Leona", "R", "LONG", "CC", magnitude=0.75, cond=True)
    add("Leona", "BASE", "MELEE", "SUSTAINED", magnitude=0.2)
    # Lillia
    add("Lillia", "Q", "MEDIUM", "POKE", magnitude=0.6)
    add("Lillia", "W", "SHORT", "BURST", magnitude=0.5)
    add("Lillia", "E", "LONG", "CC", magnitude=0.45)
    add("Lillia", "R", "GLOBAL", "CC", magnitude=0.85, cond=True)
    # Lissandra
    add("Lissandra", "Q", "LONG", "CC", magnitude=0.75)
    add("Lissandra", "W", "SHORT", "CC", magnitude=0.65)
    add("Lissandra", "E", "ARTILLERY", "CC", magnitude=0.6)
    add("Lissandra", "R", "MEDIUM", "BURST", magnitude=0.8, cond=True)
    # Lucian
    add("Lucian", "Q", "LONG", "BURST", magnitude=0.75)
    add("Lucian", "W", "LONG", "POKE", magnitude=0.45)
    add("Lucian", "R", "ARTILLERY", "SUSTAINED", magnitude=0.7, cond=True)
    add("Lucian", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.8)
    # Lulu
    add("Lulu", "P", "MEDIUM", "POKE", magnitude=0.3)
    add("Lulu", "Q", "LONG", "CC", magnitude=0.7)
    add("Lulu", "W", "MEDIUM", "CC", magnitude=0.65)
    add("Lulu", "R", "LONG", "CC", magnitude=0.75, cond=True)
    # Lux
    add("Lux", "Q", "ARTILLERY", "CC", magnitude=0.85)
    add("Lux", "E", "ARTILLERY", "POKE", magnitude=0.7)
    add("Lux", "R", "GLOBAL", "BURST", magnitude=0.9, cond=True)
    # Malphite
    add("Malphite", "Q", "LONG", "POKE", magnitude=0.55)
    add("Malphite", "E", "SHORT", "SUSTAINED", magnitude=0.45)
    add("Malphite", "R", "LONG", "CC", magnitude=0.9, cond=True)
    add("Malphite", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Malzahar
    add("Malzahar", "Q", "LONG", "CC", magnitude=0.75)
    add("Malzahar", "W", "MELEE", "SUSTAINED", magnitude=0.35, cond=True)
    add("Malzahar", "E", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Malzahar", "R", "MEDIUM", "CC", magnitude=0.85, cond=True)
    # Maokai
    add("Maokai", "Q", "MEDIUM", "CC", magnitude=0.7)
    add("Maokai", "W", "MEDIUM", "CC", magnitude=0.75)
    add("Maokai", "E", "ARTILLERY", "POKE", magnitude=0.45)
    add("Maokai", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    # MasterYi
    add("MasterYi", "Q", "MEDIUM", "BURST", magnitude=0.7)
    add("MasterYi", "E", "MELEE", "SUSTAINED", magnitude=0.6)
    add("MasterYi", "R", "MELEE", "SUSTAINED", magnitude=0.75, cond=True)
    add("MasterYi", "BASE", "MELEE", "SUSTAINED", magnitude=0.85)
    # Mel
    add("Mel", "Q", "LONG", "POKE", magnitude=0.65)
    add("Mel", "E", "LONG", "CC", magnitude=0.6)
    add("Mel", "R", "MEDIUM", "BURST", magnitude=0.8, cond=True)
    add("Mel", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.3)
    # Milio
    add("Milio", "Q", "ARTILLERY", "CC", magnitude=0.65)
    add("Milio", "E", "MEDIUM", "POKE", magnitude=0.35)
    add("Milio", "R", "MEDIUM", "SUSTAINED", magnitude=0.7, cond=True)
    # MissFortune
    add("MissFortune", "Q", "MEDIUM", "BURST", magnitude=0.6)
    add("MissFortune", "E", "LONG", "CC", magnitude=0.45)
    add("MissFortune", "R", "ARTILLERY", "SUSTAINED", magnitude=0.85, cond=True)
    add("MissFortune", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.55)
    # MonkeyKing
    add("MonkeyKing", "Q", "SHORT", "BURST", magnitude=0.55)
    add("MonkeyKing", "W", "SHORT", "BURST", magnitude=0.35)
    add("MonkeyKing", "E", "SHORT", "BURST", magnitude=0.65)
    add("MonkeyKing", "R", "MELEE", "CC", magnitude=0.7, cond=True)
    add("MonkeyKing", "BASE", "MELEE", "SUSTAINED", magnitude=0.7)
    # Mordekaiser
    add("Mordekaiser", "P", "MELEE", "SUSTAINED", magnitude=0.4)
    add("Mordekaiser", "Q", "MEDIUM", "BURST", magnitude=0.6)
    add("Mordekaiser", "E", "LONG", "CC", magnitude=0.7)
    add("Mordekaiser", "R", "SHORT", "BURST", magnitude=0.8, cond=True)
    # Morgana
    add("Morgana", "Q", "ARTILLERY", "CC", magnitude=0.85)
    add("Morgana", "W", "LONG", "SUSTAINED", magnitude=0.55)
    add("Morgana", "R", "MEDIUM", "CC", magnitude=0.75, cond=True)
    # Naafiri
    add("Naafiri", "Q", "LONG", "BURST", magnitude=0.6)
    add("Naafiri", "W", "SHORT", "BURST", magnitude=0.4)
    add("Naafiri", "E", "SHORT", "BURST", magnitude=0.45)
    add("Naafiri", "R", "LONG", "BURST", magnitude=0.75, cond=True)
    add("Naafiri", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Nami
    add("Nami", "Q", "LONG", "CC", magnitude=0.8)
    add("Nami", "W", "MEDIUM", "POKE", magnitude=0.45)
    add("Nami", "R", "ARTILLERY", "CC", magnitude=0.75, cond=True)
    # Nasus
    add("Nasus", "Q", "MELEE", "BURST", magnitude=0.85, cond=True)
    add("Nasus", "W", "LONG", "CC", magnitude=0.6)
    add("Nasus", "E", "MEDIUM", "POKE", magnitude=0.35)
    add("Nasus", "R", "MELEE", "SUSTAINED", magnitude=0.6, cond=True)
    add("Nasus", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Nautilus
    add("Nautilus", "Q", "LONG", "CC", magnitude=0.85)
    add("Nautilus", "W", "MELEE", "SUSTAINED", magnitude=0.3)
    add("Nautilus", "E", "SHORT", "CC", magnitude=0.55)
    add("Nautilus", "R", "LONG", "CC", magnitude=0.8, cond=True)
    add("Nautilus", "BASE", "MELEE", "CC", magnitude=0.45)
    # Neeko
    add("Neeko", "Q", "LONG", "POKE", magnitude=0.55)
    add("Neeko", "E", "LONG", "CC", magnitude=0.75)
    add("Neeko", "R", "MELEE", "CC", magnitude=0.8, cond=True)
    add("Neeko", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.25)
    # Nidalee
    add("Nidalee", "Q", "ARTILLERY", "BURST", magnitude=0.85)
    add("Nidalee", "W", "LONG", "CC", magnitude=0.4)
    add("Nidalee", "R", "SHORT", "BURST", magnitude=0.75, cond=True)
    # Nilah
    add("Nilah", "Q", "SHORT", "SUSTAINED", magnitude=0.65)
    add("Nilah", "E", "SHORT", "BURST", magnitude=0.5)
    add("Nilah", "R", "MELEE", "BURST", magnitude=0.85, cond=True)
    add("Nilah", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Nocturne
    add("Nocturne", "Q", "ARTILLERY", "POKE", magnitude=0.55)
    add("Nocturne", "E", "SHORT", "CC", magnitude=0.6)
    add("Nocturne", "R", "GLOBAL", "CC", magnitude=0.75, cond=True)
    add("Nocturne", "BASE", "MELEE", "SUSTAINED", magnitude=0.7)
    # Nunu
    add("Nunu", "Q", "MELEE", "BURST", magnitude=0.45)
    add("Nunu", "W", "LONG", "CC", magnitude=0.75)
    add("Nunu", "E", "LONG", "CC", magnitude=0.5)
    add("Nunu", "R", "MEDIUM", "BURST", magnitude=0.7, cond=True)
    # Olaf
    add("Olaf", "Q", "ARTILLERY", "CC", magnitude=0.65)
    add("Olaf", "E", "MELEE", "BURST", magnitude=0.6)
    add("Olaf", "R", "MELEE", "SUSTAINED", magnitude=0.8, cond=True)
    add("Olaf", "BASE", "MELEE", "SUSTAINED", magnitude=0.7)
    # Orianna
    add("Orianna", "Q", "LONG", "POKE", magnitude=0.55)
    add("Orianna", "W", "LONG", "CC", magnitude=0.5)
    add("Orianna", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("Orianna", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.3)
    # Ornn
    add("Ornn", "Q", "LONG", "CC", magnitude=0.7)
    add("Ornn", "W", "SHORT", "CC", magnitude=0.55)
    add("Ornn", "E", "SHORT", "BURST", magnitude=0.5)
    add("Ornn", "R", "ARTILLERY", "CC", magnitude=0.85, cond=True)
    # Pantheon
    add("Pantheon", "Q", "ARTILLERY", "POKE", magnitude=0.7)
    add("Pantheon", "W", "MELEE", "CC", magnitude=0.65)
    add("Pantheon", "E", "SHORT", "SUSTAINED", magnitude=0.5)
    add("Pantheon", "R", "GLOBAL", "BURST", magnitude=0.65, cond=True)
    # Poppy
    add("Poppy", "Q", "SHORT", "BURST", magnitude=0.6)
    add("Poppy", "W", "SHORT", "CC", magnitude=0.55)
    add("Poppy", "E", "SHORT", "CC", magnitude=0.7)
    add("Poppy", "R", "LONG", "CC", magnitude=0.75, cond=True)
    add("Poppy", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Pyke
    add("Pyke", "Q", "LONG", "CC", magnitude=0.75)
    add("Pyke", "E", "SHORT", "CC", magnitude=0.65)
    add("Pyke", "R", "MEDIUM", "BURST", magnitude=0.9, cond=True)
    add("Pyke", "BASE", "MELEE", "SUSTAINED", magnitude=0.2)
    # Qiyana
    add("Qiyana", "Q", "SHORT", "BURST", magnitude=0.75)
    add("Qiyana", "E", "SHORT", "BURST", magnitude=0.6)
    add("Qiyana", "R", "LONG", "CC", magnitude=0.9, cond=True)
    add("Qiyana", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Quinn
    add("Quinn", "P", "MEDIUM", "BURST", magnitude=0.5)
    add("Quinn", "Q", "ARTILLERY", "CC", magnitude=0.65)
    add("Quinn", "E", "SHORT", "CC", magnitude=0.55)
    add("Quinn", "R", "SHORT", "BURST", magnitude=0.6, cond=True)
    add("Quinn", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.55)
    # Rakan
    add("Rakan", "Q", "LONG", "POKE", magnitude=0.5)
    add("Rakan", "W", "SHORT", "CC", magnitude=0.75)
    add("Rakan", "R", "SHORT", "CC", magnitude=0.7, cond=True)
    add("Rakan", "BASE", "MELEE", "SUSTAINED", magnitude=0.2)
    # Rammus
    add("Rammus", "Q", "LONG", "CC", magnitude=0.7)
    add("Rammus", "W", "MELEE", "SUSTAINED", magnitude=0.5)
    add("Rammus", "E", "SHORT", "CC", magnitude=0.75)
    add("Rammus", "R", "LONG", "CC", magnitude=0.65, cond=True)
    # RekSai
    add("RekSai", "Q", "ARTILLERY", "CC", magnitude=0.7, cond=True)
    add("RekSai", "W", "MELEE", "CC", magnitude=0.6)
    add("RekSai", "E", "MELEE", "BURST", magnitude=0.65, cond=True)
    add("RekSai", "R", "GLOBAL", "BURST", magnitude=0.8, cond=True)
    # Rell
    add("Rell", "P", "MELEE", "SUSTAINED", magnitude=0.3)
    add("Rell", "Q", "MEDIUM", "CC", magnitude=0.55)
    add("Rell", "W", "SHORT", "CC", magnitude=0.75)
    add("Rell", "E", "MEDIUM", "CC", magnitude=0.5)
    add("Rell", "R", "SHORT", "CC", magnitude=0.75, cond=True)
    add("Rell", "BASE", "MELEE", "SUSTAINED", magnitude=0.35)
    # Renata
    add("Renata", "P", "MEDIUM", "SUSTAINED", magnitude=0.35)
    add("Renata", "Q", "LONG", "CC", magnitude=0.75)
    add("Renata", "W", "LONG", "CC", magnitude=0.4)
    add("Renata", "E", "LONG", "CC", magnitude=0.6)
    add("Renata", "R", "ARTILLERY", "CC", magnitude=0.8, cond=True)
    # Renekton
    add("Renekton", "Q", "SHORT", "SUSTAINED", magnitude=0.65)
    add("Renekton", "W", "MELEE", "CC", magnitude=0.75)
    add("Renekton", "E", "SHORT", "BURST", magnitude=0.7)
    add("Renekton", "R", "MELEE", "SUSTAINED", magnitude=0.55, cond=True)
    add("Renekton", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Rengar
    add("Rengar", "Q", "MELEE", "BURST", magnitude=0.8)
    add("Rengar", "W", "SHORT", "CC", magnitude=0.35)
    add("Rengar", "E", "LONG", "CC", magnitude=0.55)
    add("Rengar", "R", "GLOBAL", "BURST", magnitude=0.85, cond=True)
    add("Rengar", "BASE", "MELEE", "SUSTAINED", magnitude=0.55)
    # Riven
    add("Riven", "Q", "MELEE", "BURST", magnitude=0.6)
    add("Riven", "W", "MELEE", "CC", magnitude=0.55)
    add("Riven", "E", "SHORT", "BURST", magnitude=0.35)
    add("Riven", "R", "LONG", "BURST", magnitude=0.85, cond=True)
    add("Riven", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Rumble
    add("Rumble", "Q", "SHORT", "SUSTAINED", magnitude=0.7)
    add("Rumble", "W", "MELEE", "CC", magnitude=0.2)
    add("Rumble", "E", "LONG", "CC", magnitude=0.6)
    add("Rumble", "R", "LONG", "SUSTAINED", magnitude=0.85, cond=True)
    # Ryze
    add("Ryze", "Q", "ARTILLERY", "BURST", magnitude=0.8)
    add("Ryze", "W", "MEDIUM", "CC", magnitude=0.7)
    add("Ryze", "E", "MEDIUM", "SUSTAINED", magnitude=0.55)
    add("Ryze", "R", "GLOBAL", "CC", magnitude=0.35, cond=True)
    # Samira
    add("Samira", "Q", "LONG", "POKE", magnitude=0.55)
    add("Samira", "W", "MELEE", "BURST", magnitude=0.5)
    add("Samira", "E", "SHORT", "BURST", magnitude=0.5)
    add("Samira", "R", "MELEE", "BURST", magnitude=0.8, cond=True)
    add("Samira", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.75)
    # Sejuani
    add("Sejuani", "Q", "LONG", "CC", magnitude=0.7)
    add("Sejuani", "W", "SHORT", "CC", magnitude=0.45)
    add("Sejuani", "E", "LONG", "CC", magnitude=0.65, cond=True)
    add("Sejuani", "R", "ARTILLERY", "CC", magnitude=0.85, cond=True)
    # Senna
    add("Senna", "Q", "ARTILLERY", "POKE", magnitude=0.7)
    add("Senna", "W", "ARTILLERY", "CC", magnitude=0.8)
    add("Senna", "R", "GLOBAL", "BURST", magnitude=0.75, cond=True)
    add("Senna", "BASE", "LONG", "SUSTAINED", magnitude=0.65)
    # Seraphine
    add("Seraphine", "Q", "LONG", "POKE", magnitude=0.5)
    add("Seraphine", "E", "ARTILLERY", "CC", magnitude=0.7)
    add("Seraphine", "R", "ARTILLERY", "CC", magnitude=0.85, cond=True)
    add("Seraphine", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.3)
    # Sett
    add("Sett", "Q", "MELEE", "SUSTAINED", magnitude=0.7)
    add("Sett", "W", "MEDIUM", "BURST", magnitude=0.75)
    add("Sett", "E", "SHORT", "CC", magnitude=0.65)
    add("Sett", "R", "SHORT", "CC", magnitude=0.8, cond=True)
    # Shaco
    add("Shaco", "Q", "SHORT", "BURST", magnitude=0.7)
    add("Shaco", "W", "LONG", "CC", magnitude=0.55)
    add("Shaco", "E", "MEDIUM", "POKE", magnitude=0.45)
    add("Shaco", "R", "SHORT", "BURST", magnitude=0.6, cond=True)
    # Shen
    add("Shen", "Q", "MEDIUM", "SUSTAINED", magnitude=0.55)
    add("Shen", "W", "MELEE", "CC", magnitude=0.5)
    add("Shen", "E", "SHORT", "CC", magnitude=0.7)
    add("Shen", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    add("Shen", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Shyvana
    add("Shyvana", "Q", "MELEE", "SUSTAINED", magnitude=0.55)
    add("Shyvana", "W", "SHORT", "SUSTAINED", magnitude=0.5)
    add("Shyvana", "E", "LONG", "POKE", magnitude=0.5)
    add("Shyvana", "R", "LONG", "CC", magnitude=0.6, cond=True)
    add("Shyvana", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Singed
    add("Singed", "Q", "SHORT", "SUSTAINED", magnitude=0.65)
    add("Singed", "W", "LONG", "CC", magnitude=0.55)
    add("Singed", "E", "MELEE", "CC", magnitude=0.8)
    add("Singed", "R", "SHORT", "SUSTAINED", magnitude=0.6, cond=True)
    add("Singed", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Sion
    add("Sion", "Q", "MEDIUM", "CC", magnitude=0.7)
    add("Sion", "W", "MEDIUM", "BURST", magnitude=0.55)
    add("Sion", "E", "LONG", "CC", magnitude=0.6)
    add("Sion", "R", "GLOBAL", "CC", magnitude=0.8, cond=True)
    # Sivir
    add("Sivir", "Q", "ARTILLERY", "POKE", magnitude=0.75)
    add("Sivir", "W", "MEDIUM", "SUSTAINED", magnitude=0.65)
    add("Sivir", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.7)
    # Skarner
    add("Skarner", "Q", "SHORT", "BURST", magnitude=0.55)
    add("Skarner", "W", "MEDIUM", "CC", magnitude=0.45)
    add("Skarner", "E", "LONG", "CC", magnitude=0.7)
    add("Skarner", "R", "MEDIUM", "CC", magnitude=0.85, cond=True)
    # Smolder
    add("Smolder", "Q", "MEDIUM", "POKE", magnitude=0.6)
    add("Smolder", "W", "LONG", "BURST", magnitude=0.65)
    add("Smolder", "R", "ARTILLERY", "BURST", magnitude=0.8, cond=True)
    add("Smolder", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.55)
    # Sona
    add("Sona", "Q", "LONG", "POKE", magnitude=0.5)
    add("Sona", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("Sona", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.35)
    # Soraka
    add("Soraka", "Q", "LONG", "POKE", magnitude=0.65)
    add("Soraka", "E", "LONG", "CC", magnitude=0.75)
    add("Soraka", "R", "GLOBAL", "CC", magnitude=0.3, cond=True)
    # Swain
    add("Swain", "Q", "LONG", "CC", magnitude=0.6)
    add("Swain", "W", "ARTILLERY", "CC", magnitude=0.65)
    add("Swain", "E", "LONG", "BURST", magnitude=0.7)
    add("Swain", "R", "SHORT", "SUSTAINED", magnitude=0.75, cond=True)
    # Sylas
    add("Sylas", "Q", "LONG", "CC", magnitude=0.65)
    add("Sylas", "W", "SHORT", "BURST", magnitude=0.55)
    add("Sylas", "E", "LONG", "CC", magnitude=0.6)
    add("Sylas", "R", "MEDIUM", "BURST", magnitude=0.75, cond=True)
    add("Sylas", "BASE", "MELEE", "SUSTAINED", magnitude=0.35)
    # Syndra
    add("Syndra", "Q", "LONG", "POKE", magnitude=0.6)
    add("Syndra", "W", "LONG", "CC", magnitude=0.5)
    add("Syndra", "E", "MEDIUM", "CC", magnitude=0.7)
    add("Syndra", "R", "LONG", "BURST", magnitude=0.95, cond=True)
    add("Syndra", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.2)
    # TahmKench
    add("TahmKench", "Q", "LONG", "CC", magnitude=0.75)
    add("TahmKench", "W", "MELEE", "CC", magnitude=0.5)
    add("TahmKench", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    add("TahmKench", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Taliyah
    add("Taliyah", "Q", "ARTILLERY", "POKE", magnitude=0.75)
    add("Taliyah", "W", "LONG", "CC", magnitude=0.65)
    add("Taliyah", "E", "LONG", "CC", magnitude=0.55)
    add("Taliyah", "R", "GLOBAL", "CC", magnitude=0.5, cond=True)
    # Talon
    add("Talon", "Q", "SHORT", "BURST", magnitude=0.65)
    add("Talon", "W", "LONG", "POKE", magnitude=0.6)
    add("Talon", "R", "SHORT", "BURST", magnitude=0.75, cond=True)
    add("Talon", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Taric
    add("Taric", "E", "MEDIUM", "CC", magnitude=0.65)
    add("Taric", "R", "GLOBAL", "CC", magnitude=0.8, cond=True)
    add("Taric", "BASE", "MELEE", "SUSTAINED", magnitude=0.35)
    # Teemo
    add("Teemo", "Q", "LONG", "CC", magnitude=0.65)
    add("Teemo", "E", "MEDIUM", "SUSTAINED", magnitude=0.7)
    add("Teemo", "R", "SHORT", "CC", magnitude=0.65, cond=True)
    # Thresh
    add("Thresh", "Q", "LONG", "CC", magnitude=0.85)
    add("Thresh", "E", "MEDIUM", "CC", magnitude=0.6)
    add("Thresh", "R", "SHORT", "CC", magnitude=0.55, cond=True)
    add("Thresh", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.35)
    # Tristana
    add("Tristana", "W", "LONG", "CC", magnitude=0.55)
    add("Tristana", "E", "MEDIUM", "BURST", magnitude=0.7)
    add("Tristana", "R", "MEDIUM", "CC", magnitude=0.65, cond=True)
    add("Tristana", "BASE", "LONG", "SUSTAINED", magnitude=0.8, cond=True)
    # Trundle
    add("Trundle", "Q", "MELEE", "SUSTAINED", magnitude=0.7)
    add("Trundle", "W", "LONG", "POKE", magnitude=0.3)
    add("Trundle", "E", "MELEE", "CC", magnitude=0.65)
    add("Trundle", "R", "LONG", "CC", magnitude=0.75, cond=True)
    add("Trundle", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Tryndamere
    add("Tryndamere", "Q", "MELEE", "SUSTAINED", magnitude=0.5)
    add("Tryndamere", "W", "LONG", "CC", magnitude=0.45)
    add("Tryndamere", "E", "SHORT", "BURST", magnitude=0.6)
    add("Tryndamere", "R", "MELEE", "SUSTAINED", magnitude=0.85, cond=True)
    add("Tryndamere", "BASE", "MELEE", "SUSTAINED", magnitude=0.75)
    # TwistedFate
    add("TwistedFate", "Q", "LONG", "POKE", magnitude=0.6)
    add("TwistedFate", "W", "MEDIUM", "CC", magnitude=0.85, cond=True)
    add("TwistedFate", "E", "MEDIUM", "SUSTAINED", magnitude=0.3)
    add("TwistedFate", "R", "GLOBAL", "CC", magnitude=0.7, cond=True)
    add("TwistedFate", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.4)
    # Twitch
    add("Twitch", "E", "MEDIUM", "BURST", magnitude=0.7)
    add("Twitch", "R", "LONG", "SUSTAINED", magnitude=0.9, cond=True)
    add("Twitch", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Udyr
    add("Udyr", "Q", "MELEE", "BURST", magnitude=0.7)
    add("Udyr", "E", "SHORT", "CC", magnitude=0.65)
    add("Udyr", "R", "SHORT", "SUSTAINED", magnitude=0.5)
    add("Udyr", "BASE", "MELEE", "SUSTAINED", magnitude=0.55)
    # Urgot
    add("Urgot", "P", "MELEE", "SUSTAINED", magnitude=0.55)
    add("Urgot", "Q", "LONG", "POKE", magnitude=0.65)
    add("Urgot", "W", "MEDIUM", "SUSTAINED", magnitude=0.75)
    add("Urgot", "E", "SHORT", "CC", magnitude=0.65)
    add("Urgot", "R", "ARTILLERY", "CC", magnitude=0.7, cond=True)
    add("Urgot", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.5)
    # Varus
    add("Varus", "Q", "ARTILLERY", "BURST", magnitude=0.75)
    add("Varus", "E", "LONG", "POKE", magnitude=0.4)
    add("Varus", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("Varus", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.55)
    # Vayne
    add("Vayne", "Q", "SHORT", "BURST", magnitude=0.55)
    add("Vayne", "W", "MEDIUM", "SUSTAINED", magnitude=0.75)
    add("Vayne", "E", "MEDIUM", "CC", magnitude=0.7)
    add("Vayne", "R", "MELEE", "BURST", magnitude=0.8, cond=True)
    # Veigar
    add("Veigar", "Q", "LONG", "POKE", magnitude=0.55)
    add("Veigar", "W", "LONG", "BURST", magnitude=0.65)
    add("Veigar", "E", "LONG", "CC", magnitude=0.75)
    add("Veigar", "R", "MEDIUM", "BURST", magnitude=0.9, cond=True)
    add("Veigar", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.2)
    # Velkoz
    add("Velkoz", "Q", "ARTILLERY", "POKE", magnitude=0.8)
    add("Velkoz", "W", "LONG", "POKE", magnitude=0.65)
    add("Velkoz", "E", "LONG", "CC", magnitude=0.7)
    add("Velkoz", "R", "LONG", "SUSTAINED", magnitude=0.85, cond=True)
    # Vex
    add("Vex", "Q", "ARTILLERY", "POKE", magnitude=0.7)
    add("Vex", "W", "SHORT", "CC", magnitude=0.55)
    add("Vex", "E", "ARTILLERY", "CC", magnitude=0.65)
    add("Vex", "R", "GLOBAL", "BURST", magnitude=0.85, cond=True)
    # Vi
    add("Vi", "Q", "LONG", "CC", magnitude=0.75)
    add("Vi", "W", "MELEE", "SUSTAINED", magnitude=0.4)
    add("Vi", "E", "SHORT", "BURST", magnitude=0.5)
    add("Vi", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("Vi", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Viego
    add("Viego", "Q", "MELEE", "SUSTAINED", magnitude=0.5)
    add("Viego", "W", "LONG", "CC", magnitude=0.65)
    add("Viego", "E", "SHORT", "BURST", magnitude=0.35)
    add("Viego", "R", "SHORT", "CC", magnitude=0.8, cond=True)
    add("Viego", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Viktor
    add("Viktor", "Q", "MEDIUM", "POKE", magnitude=0.4)
    add("Viktor", "W", "LONG", "CC", magnitude=0.7)
    add("Viktor", "E", "LONG", "SUSTAINED", magnitude=0.8)
    add("Viktor", "R", "LONG", "SUSTAINED", magnitude=0.85, cond=True)
    # Vladimir
    add("Vladimir", "Q", "MEDIUM", "BURST", magnitude=0.65)
    add("Vladimir", "W", "MELEE", "BURST", magnitude=0.35)
    add("Vladimir", "E", "MEDIUM", "POKE", magnitude=0.5)
    add("Vladimir", "R", "LONG", "BURST", magnitude=0.8, cond=True)
    # Volibear
    add("Volibear", "Q", "SHORT", "CC", magnitude=0.7)
    add("Volibear", "W", "MELEE", "SUSTAINED", magnitude=0.55)
    add("Volibear", "E", "ARTILLERY", "CC", magnitude=0.65)
    add("Volibear", "R", "GLOBAL", "BURST", magnitude=0.65, cond=True)
    add("Volibear", "BASE", "MELEE", "SUSTAINED", magnitude=0.65)
    # Warwick
    add("Warwick", "Q", "MEDIUM", "BURST", magnitude=0.6)
    add("Warwick", "E", "SHORT", "CC", magnitude=0.5)
    add("Warwick", "R", "LONG", "CC", magnitude=0.85, cond=True)
    add("Warwick", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Xayah
    add("Xayah", "Q", "ARTILLERY", "POKE", magnitude=0.65)
    add("Xayah", "E", "ARTILLERY", "CC", magnitude=0.85, cond=True)
    add("Xayah", "R", "LONG", "BURST", magnitude=0.75, cond=True)
    add("Xayah", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.6)
    # Xerath
    add("Xerath", "Q", "ARTILLERY", "POKE", magnitude=0.85)
    add("Xerath", "W", "ARTILLERY", "POKE", magnitude=0.65)
    add("Xerath", "E", "ARTILLERY", "CC", magnitude=0.7)
    add("Xerath", "R", "GLOBAL", "BURST", magnitude=0.8, cond=True)
    add("Xerath", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.2)
    # XinZhao
    add("XinZhao", "P", "MELEE", "SUSTAINED", magnitude=0.4)
    add("XinZhao", "Q", "MELEE", "CC", magnitude=0.7)
    add("XinZhao", "W", "MEDIUM", "SUSTAINED", magnitude=0.6)
    add("XinZhao", "E", "LONG", "CC", magnitude=0.75)
    add("XinZhao", "R", "SHORT", "CC", magnitude=0.65, cond=True)
    # Yasuo
    add("Yasuo", "Q", "SHORT", "POKE", magnitude=0.65)
    add("Yasuo", "E", "SHORT", "BURST", magnitude=0.7)
    add("Yasuo", "R", "ARTILLERY", "BURST", magnitude=0.85, cond=True)
    add("Yasuo", "BASE", "MELEE", "SUSTAINED", magnitude=0.45)
    # Yone
    add("Yone", "Q", "LONG", "BURST", magnitude=0.7)
    add("Yone", "E", "SHORT", "CC", magnitude=0.6)
    add("Yone", "R", "LONG", "CC", magnitude=0.8, cond=True)
    add("Yone", "BASE", "MELEE", "SUSTAINED", magnitude=0.6)
    # Yorick
    add("Yorick", "Q", "MELEE", "BURST", magnitude=0.5)
    add("Yorick", "W", "MEDIUM", "CC", magnitude=0.45)
    add("Yorick", "E", "LONG", "POKE", magnitude=0.55)
    add("Yorick", "R", "MEDIUM", "SUSTAINED", magnitude=0.65, cond=True)
    add("Yorick", "BASE", "MELEE", "SUSTAINED", magnitude=0.5)
    # Yunara
    add("Yunara", "Q", "LONG", "POKE", magnitude=0.65)
    add("Yunara", "W", "MEDIUM", "CC", magnitude=0.55)
    add("Yunara", "R", "LONG", "BURST", magnitude=0.8, cond=True)
    add("Yunara", "BASE", "MEDIUM", "SUSTAINED", magnitude=0.5)
    # Yuumi
    add("Yuumi", "Q", "ARTILLERY", "POKE", magnitude=0.65)
    add("Yuumi", "R", "ARTILLERY", "CC", magnitude=0.8, cond=True)
    # Zac
    add("Zac", "Q", "MEDIUM", "CC", magnitude=0.65)
    add("Zac", "W", "MELEE", "BURST", magnitude=0.4)
    add("Zac", "E", "ARTILLERY", "CC", magnitude=0.75)
    add("Zac", "R", "SHORT", "CC", magnitude=0.6, cond=True)
    add("Zac", "BASE", "MELEE", "SUSTAINED", magnitude=0.4)
    # Zed
    add("Zed", "Q", "LONG", "POKE", magnitude=0.6)
    add("Zed", "W", "LONG", "BURST", magnitude=0.5)
    add("Zed", "E", "MELEE", "BURST", magnitude=0.4)
    add("Zed", "R", "MEDIUM", "BURST", magnitude=0.9, cond=True)
    # Zeri
    add("Zeri", "Q", "LONG", "SUSTAINED", magnitude=0.75)
    add("Zeri", "W", "ARTILLERY", "POKE", magnitude=0.65)
    add("Zeri", "R", "LONG", "BURST", magnitude=0.7, cond=True)
    # Ziggs
    add("Ziggs", "P", "MEDIUM", "BURST", magnitude=0.4)
    add("Ziggs", "Q", "ARTILLERY", "POKE", magnitude=0.8)
    add("Ziggs", "W", "LONG", "CC", magnitude=0.45)
    add("Ziggs", "E", "LONG", "CC", magnitude=0.4)
    add("Ziggs", "R", "GLOBAL", "BURST", magnitude=0.75, cond=True)
    # Zilean
    add("Zilean", "Q", "LONG", "CC", magnitude=0.8)
    add("Zilean", "W", "SHORT", "POKE", magnitude=0.25, cond=True)
    add("Zilean", "E", "MEDIUM", "CC", magnitude=0.55)
    add("Zilean", "R", "MEDIUM", "CC", magnitude=0.45, cond=True)
    # Zoe
    add("Zoe", "Q", "ARTILLERY", "BURST", magnitude=0.8)
    add("Zoe", "W", "LONG", "POKE", magnitude=0.4, cond=True)
    add("Zoe", "E", "ARTILLERY", "CC", magnitude=0.85)
    add("Zoe", "R", "SHORT", "BURST", magnitude=0.5, cond=True)
    # Zyra
    add("Zyra", "Q", "LONG", "POKE", magnitude=0.6)
    add("Zyra", "W", "LONG", "SUSTAINED", magnitude=0.45)
    add("Zyra", "E", "LONG", "CC", magnitude=0.75)
    add("Zyra", "R", "MEDIUM", "CC", magnitude=0.7, cond=True)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_THREATRANGE_REGISTRY: dict[str, tuple[ThreatRangeEntry, ...]] = (
    _build_threatrange_registry()
)


@dataclass(frozen=True)
class ThreatRangeSourceEntry:
    """One scored threatening mechanism for a champion."""

    source_key: str
    band: str
    kind: str
    band_weight: float
    kind_mult: float
    magnitude: float
    conditional: bool
    value: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "band": self.band,
            "kind": self.kind,
            "band_weight": self.band_weight,
            "kind_mult": self.kind_mult,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class ThreatRangeResult:
    """Aggregate effective threat-range for one champion.

    ``threatrange_score`` sums every mechanism's reach-weighted, threat-typed
    value (higher = threatens from farther out). ``top_band`` is the band of the
    single highest-value mechanism (the champion's longest REAL threat, ``""``
    when none). ``is_artillery`` is True when at least one ARTILLERY/GLOBAL-band
    mechanism contributes - the long-siege flag a poke consumer keys on. Returns
    all-zero with an empty ``sources`` tuple for an unregistered or blank champion
    (never raises).
    """

    champion: str
    mode: str
    threatrange_score: float
    top_band: str
    is_artillery: bool
    sources: tuple[ThreatRangeSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "threatrange_score": round(self.threatrange_score, 4),
            "top_band": self.top_band,
            "is_artillery": self.is_artillery,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> ThreatRangeResult:
    return ThreatRangeResult(
        champion=champion,
        mode=mode,
        threatrange_score=0.0,
        top_band="",
        is_artillery=False,
        sources=(),
    )


def _source_sort_key(entry: ThreatRangeEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_threatrange(champion: str, mode: str = "SR") -> ThreatRangeResult:
    """Aggregate a champion's threatening mechanisms into a threat-range score.

    Reads ``_THREATRANGE_REGISTRY``. Each registered mechanism contributes a
    reach-weighted, threat-typed value (``_mechanism_value``); the values are
    summed into ``threatrange_score``. ``top_band`` is the band of the
    highest-value mechanism; ``is_artillery`` is True when any ARTILLERY/GLOBAL
    mechanism contributes. ``mode`` is carried on the result for parity with the
    other scorers but does not change output today (threat reach is
    map-independent).

    Returns an all-zero ``ThreatRangeResult`` (empty ``sources``) when the
    champion is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _THREATRANGE_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[ThreatRangeSourceEntry] = []
    total = 0.0
    best_band = ""
    best_value = -1.0
    has_artillery = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_band = entry.band
        if value > 0.0 and entry.band in ("ARTILLERY", "GLOBAL"):
            has_artillery = True
        scored.append(
            ThreatRangeSourceEntry(
                source_key=entry.source,
                band=entry.band,
                kind=entry.kind,
                band_weight=_THREATRANGE_BAND_WEIGHT.get(entry.band, 0.0),
                kind_mult=_THREATRANGE_KIND_MULT.get(entry.kind, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return ThreatRangeResult(
        champion=champion,
        mode=safe_mode,
        threatrange_score=total,
        top_band=best_band if total > 0.0 else "",
        is_artillery=has_artillery,
        sources=tuple(scored),
    )


__all__ = [
    "ThreatRangeEntry",
    "ThreatRangeResult",
    "ThreatRangeSourceEntry",
    "compute_threatrange",
    "_THREATRANGE_BAND_WEIGHT",
    "_THREATRANGE_KIND_MULT",
    "_THREATRANGE_CONDITIONAL_PROB",
    "_THREATRANGE_REGISTRY",
]
