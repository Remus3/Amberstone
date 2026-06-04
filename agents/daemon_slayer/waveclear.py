"""Wave-clear / AoE-shove scorer (ENGINE 1.112.0, item 300).

The eleventh scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / the six archetype scorers. It
quantifies how fast and how safely a champion CLEARS A MINION WAVE and shoves a
lane - the tempo / lane-priority / roam-window / objective-setup capability the
prior ten axes never measured (they all score combat against a CHAMPION target;
this one scores throughput against a wave of minions).

A high score means decisive, low-cost, ranged wave-clear that lets a champion
shove and roam / recall / contest an objective on tempo (Ziggs / Sivir / Brand /
Karthus / Lux / Miss Fortune); a low score means a champion who must last-hit
one minion at a time and concedes lane priority (Zed / Talon / Camille / most
single-target assassins).

Purely ADDITIVE: a new standalone scorer and a new ``/waveclear`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a
live lane-priority / "shove and roam" / draft tempo coach surface is the separate
Phase-D step.

Model (each wave-clear MECHANISM a champion owns contributes a weighted, range-
discounted clear-power; the headline is their sum):
  * a per-(champion, source) ``WaveclearEntry`` tags one clear mechanism with a
    ``kind`` (key of ``_WAVECLEAR_KIND_WEIGHT`` - how decisively it clears), a
    ``range_band`` (key of ``_WAVECLEAR_RANGE_MULT`` - how safely it shoves:
    GLOBAL / RANGED bonus-or-neutral, MELEE walk-into-the-wave penalty), a
    ``magnitude`` (0..1 share of the wave this one mechanism removes), and a
    ``conditional`` flag (needs the ult up / a stack / an AoE item online).
  * ``compute_waveclear`` folds every mechanism into a single ``waveclear_score``
    = sum of ``kind_weight * range_mult * magnitude`` (times the conditional
    midpoint when gated). ``top_kind`` labels the strongest single mechanism;
    ``ranged_shove`` is True when any RANGED/GLOBAL mechanism contributes (the
    safe-shove flag a tempo consumer keys on).

Kinds, range bands and magnitudes are hand-authored from the verbatim patch-16.11
champion kits by the item-300 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SOURCE_ORDER = ("P", "Q", "W", "E", "R", "BASE")

# Wave-clear-kind -> weight. Hand-authored, operator-tunable. Five tiers by how
# decisively the mechanism removes a wave:
#   1.00 FULL_AOE      - one cast clears (or near-clears) the whole caster wave
#                        on a repeatable CD (Ziggs Q / Lux E / Brand / Morgana W
#                        / Miss Fortune E / Sivir Q / Anivia E); the strongest
#                        shove identity.
#   0.85 AOE_DOT       - persistent ground AoE / damage-over-time that clears
#                        over ~1-2s (Malzahar E / Singed Q / Rumble E / Swain W /
#                        Zyra / Heimerdinger turrets); clears but on a beat.
#   0.60 MULTI_HIT     - hits several minions but not the whole wave or needs aim
#                        / setup (Orianna Q+W / Syndra / Viktor / Xerath /
#                        Velkoz / Cassiopeia); good not great shove.
#   0.50 CLEAVE_AA     - auto-attack cleave / reset / bounce clear that needs AA
#                        windup but is reliable (Sivir W / Tristana E reset /
#                        Shyvana / Belveth / Kayle E / Whirlwind cleave).
#   0.25 SINGLE_TARGET - must clear one minion at a time, concedes lane priority
#                        (most assassins / single-target bruisers - Zed / Talon /
#                        Camille / Master Yi early); a LOW-tempo signal.
_WAVECLEAR_KIND_WEIGHT: dict[str, float] = {
    "FULL_AOE": 1.0,
    "AOE_DOT": 0.85,
    "MULTI_HIT": 0.6,
    "CLEAVE_AA": 0.5,
    "SINGLE_TARGET": 0.25,
}

# Range-band -> shove-safety multiplier. A wave cleared from a safe ranged or
# global distance is worth more tempo than one that needs the champion to walk
# into the minions (exposed to gank / minion aggro).
_WAVECLEAR_RANGE_MULT: dict[str, float] = {
    "GLOBAL": 1.1,
    "RANGED": 1.0,
    "MELEE": 0.7,
}

# A gated (conditional) clear mechanism - one that needs the ult up, a stack
# accrued, or an AoE item (Tiamat/Hextech) online - is credited at this
# availability midpoint, the sustain / mobility / cc_output / scaling shape.
_WAVECLEAR_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class WaveclearEntry:
    """One registry row: a champion wave-clear mechanism.

    ``source`` is one of ``{"P","Q","W","E","R","BASE"}`` (``BASE`` = a clear
    identity not tied to one ability, e.g. an inherent cleave AA). ``kind`` is a
    key of ``_WAVECLEAR_KIND_WEIGHT``. ``range_band`` is a key of
    ``_WAVECLEAR_RANGE_MULT``. ``magnitude`` is the 0..1 share of the wave this
    one mechanism removes. ``conditional`` is True when the mechanism only fires
    on a gate (ult up, stacks accrued, AoE item online).
    """

    source: str
    kind: str
    range_band: str
    magnitude: float = 0.0
    conditional: bool = False


def _mechanism_value(entry: WaveclearEntry) -> float:
    """Weighted, range-discounted clear-power for one mechanism (0 if unknown).

    Returns ``kind_weight * range_mult * magnitude`` (times the conditional
    midpoint when gated), or ``0.0`` when the kind or range band is unknown.
    """
    weight = _WAVECLEAR_KIND_WEIGHT.get(entry.kind, 0.0)
    range_mult = _WAVECLEAR_RANGE_MULT.get(entry.range_band, 0.0)
    if weight <= 0.0 or range_mult <= 0.0:
        return 0.0
    value = weight * range_mult * entry.magnitude
    if entry.conditional:
        value *= _WAVECLEAR_CONDITIONAL_PROB
    return value


def _build_waveclear_registry() -> dict[str, tuple[WaveclearEntry, ...]]:
    """Build champion_id -> tuple[WaveclearEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several clear mechanisms without dict-literal collision (the scaling /
    sustain / mobility / cc_output builder pattern). Runs ONCE at import.
    """
    raw: dict[str, list[WaveclearEntry]] = {}

    def add(
        champ: str,
        source: str,
        kind: str,
        *,
        band: str,
        magnitude: float,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            WaveclearEntry(
                source=source,
                kind=kind,
                range_band=band,
                magnitude=float(magnitude),
                conditional=bool(cond),
            )
        )

    # Aatrox
    add("Aatrox", "Q", "MULTI_HIT", band="MELEE", magnitude=0.55)
    # Ahri
    add("Ahri", "Q", "FULL_AOE", band="RANGED", magnitude=0.9)
    add("Ahri", "W", "MULTI_HIT", band="RANGED", magnitude=0.25)
    # Akali
    add("Akali", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Akali", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    # Akshan
    add("Akshan", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Akshan", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1, cond=True)
    # Alistar
    add("Alistar", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Alistar", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    # Ambessa
    add("Ambessa", "Q", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Ambessa", "W", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Amumu
    add("Amumu", "W", "AOE_DOT", band="MELEE", magnitude=0.5)
    add("Amumu", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Anivia
    add("Anivia", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Anivia", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Anivia", "R", "AOE_DOT", band="RANGED", magnitude=0.8, cond=True)
    # Annie
    add("Annie", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Annie", "W", "FULL_AOE", band="RANGED", magnitude=0.9)
    # Aphelios
    add("Aphelios", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5, cond=True)
    add("Aphelios", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Ashe
    add("Ashe", "W", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Ashe", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # AurelionSol
    add("AurelionSol", "Q", "FULL_AOE", band="RANGED", magnitude=0.95)
    add("AurelionSol", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Aurora
    add("Aurora", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Aurora", "W", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Azir
    add("Azir", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Azir", "W", "MULTI_HIT", band="RANGED", magnitude=0.6)
    # Bard
    add("Bard", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Bard", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # Belveth
    add("Belveth", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("Belveth", "R", "CLEAVE_AA", band="MELEE", magnitude=0.7, cond=True)
    add("Belveth", "BASE", "CLEAVE_AA", band="MELEE", magnitude=0.55)
    # Blitzcrank
    add("Blitzcrank", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Blitzcrank", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    # Brand
    add("Brand", "P", "AOE_DOT", band="RANGED", magnitude=0.25)
    add("Brand", "W", "FULL_AOE", band="RANGED", magnitude=0.9)
    add("Brand", "E", "MULTI_HIT", band="RANGED", magnitude=0.5)
    # Braum
    add("Braum", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Briar
    add("Briar", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Briar", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Caitlyn
    add("Caitlyn", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Caitlyn", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # Camille
    add("Camille", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Camille", "W", "MULTI_HIT", band="MELEE", magnitude=0.4)
    add("Camille", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Cassiopeia
    add("Cassiopeia", "W", "AOE_DOT", band="RANGED", magnitude=0.5)
    add("Cassiopeia", "E", "MULTI_HIT", band="RANGED", magnitude=0.55)
    # Chogath
    add("Chogath", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Chogath", "W", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Corki
    add("Corki", "W", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Corki", "E", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Corki", "R", "MULTI_HIT", band="RANGED", magnitude=0.5)
    # Darius
    add("Darius", "Q", "FULL_AOE", band="MELEE", magnitude=0.85)
    add("Darius", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Diana
    add("Diana", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Diana", "W", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Diana", "R", "FULL_AOE", band="MELEE", magnitude=0.75)
    # DrMundo
    add("DrMundo", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("DrMundo", "W", "AOE_DOT", band="MELEE", magnitude=0.45)
    add("DrMundo", "E", "CLEAVE_AA", band="MELEE", magnitude=0.3)
    # Draven
    add("Draven", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Ekko
    add("Ekko", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Ekko", "W", "MULTI_HIT", band="RANGED", magnitude=0.3)
    # Elise
    add("Elise", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Elise", "W", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Evelynn
    add("Evelynn", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Evelynn", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    # Ezreal
    add("Ezreal", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Ezreal", "R", "FULL_AOE", band="GLOBAL", magnitude=0.7, cond=True)
    # Fiddlesticks
    add("Fiddlesticks", "W", "AOE_DOT", band="MELEE", magnitude=0.7)
    add("Fiddlesticks", "E", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Fiora
    add("Fiora", "E", "CLEAVE_AA", band="MELEE", magnitude=0.25)
    add("Fiora", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Fizz
    add("Fizz", "W", "AOE_DOT", band="MELEE", magnitude=0.55)
    add("Fizz", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    # Galio
    add("Galio", "Q", "FULL_AOE", band="RANGED", magnitude=0.75)
    add("Galio", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Gangplank
    add("Gangplank", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Gangplank", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Gangplank", "R", "AOE_DOT", band="GLOBAL", magnitude=0.7, cond=True)
    # Garen
    add("Garen", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Garen", "E", "FULL_AOE", band="MELEE", magnitude=0.85)
    # Gnar
    add("Gnar", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Gnar", "E", "MULTI_HIT", band="MELEE", magnitude=0.3, cond=True)
    add("Gnar", "R", "FULL_AOE", band="MELEE", magnitude=0.75, cond=True)
    # Gragas
    add("Gragas", "Q", "FULL_AOE", band="RANGED", magnitude=0.8)
    add("Gragas", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Graves
    add("Graves", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Graves", "BASE", "CLEAVE_AA", band="RANGED", magnitude=0.35)
    # Gwen
    add("Gwen", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("Gwen", "R", "MULTI_HIT", band="RANGED", magnitude=0.55, cond=True)
    # Hecarim
    add("Hecarim", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.4)
    add("Hecarim", "W", "AOE_DOT", band="MELEE", magnitude=0.4)
    add("Hecarim", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Heimerdinger
    add("Heimerdinger", "P", "AOE_DOT", band="RANGED", magnitude=0.9)
    add("Heimerdinger", "W", "FULL_AOE", band="RANGED", magnitude=0.8)
    add("Heimerdinger", "E", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Hwei
    add("Hwei", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Hwei", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    add("Hwei", "E", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Illaoi
    add("Illaoi", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("Illaoi", "W", "CLEAVE_AA", band="MELEE", magnitude=0.3)
    add("Illaoi", "R", "FULL_AOE", band="MELEE", magnitude=0.9, cond=True)
    # Irelia
    add("Irelia", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.3)
    add("Irelia", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Irelia", "R", "FULL_AOE", band="RANGED", magnitude=0.8, cond=True)
    # Ivern
    add("Ivern", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # Janna
    add("Janna", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Janna", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # JarvanIV
    add("JarvanIV", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("JarvanIV", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    add("JarvanIV", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Jax
    add("Jax", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.25)
    add("Jax", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Jax", "R", "MULTI_HIT", band="MELEE", magnitude=0.4, cond=True)
    # Jayce
    add("Jayce", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Jayce", "W", "AOE_DOT", band="MELEE", magnitude=0.6)
    add("Jayce", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Jhin
    add("Jhin", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Jhin", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Jinx
    add("Jinx", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Jinx", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # KSante
    add("KSante", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("KSante", "W", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Kaisa
    add("Kaisa", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Kaisa", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # Kalista
    add("Kalista", "E", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Kalista", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Karma
    add("Karma", "Q", "FULL_AOE", band="RANGED", magnitude=0.95, cond=True)
    add("Karma", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # Karthus
    add("Karthus", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Karthus", "W", "AOE_DOT", band="RANGED", magnitude=0.2)
    add("Karthus", "E", "AOE_DOT", band="MELEE", magnitude=0.55)
    add("Karthus", "R", "FULL_AOE", band="GLOBAL", magnitude=0.85, cond=True)
    # Kassadin
    add("Kassadin", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Kassadin", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Kassadin", "R", "MULTI_HIT", band="MELEE", magnitude=0.45, cond=True)
    # Katarina
    add("Katarina", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Katarina", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Katarina", "R", "FULL_AOE", band="MELEE", magnitude=0.9, cond=True)
    # Kayle
    add("Kayle", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Kayle", "E", "CLEAVE_AA", band="RANGED", magnitude=0.7)
    add("Kayle", "R", "FULL_AOE", band="RANGED", magnitude=0.9, cond=True)
    # Kayn
    add("Kayn", "Q", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Kayn", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Kennen
    add("Kennen", "W", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Kennen", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    # Khazix
    add("Khazix", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Khazix", "W", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Khazix", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Kindred
    add("Kindred", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Kindred", "W", "AOE_DOT", band="RANGED", magnitude=0.35)
    # Kled
    add("Kled", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Kled", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    # KogMaw
    add("KogMaw", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("KogMaw", "E", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Leblanc
    add("Leblanc", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Leblanc", "W", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # LeeSin
    add("LeeSin", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("LeeSin", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Leona
    add("Leona", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Leona", "W", "MULTI_HIT", band="MELEE", magnitude=0.3)
    add("Leona", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Lillia
    add("Lillia", "Q", "FULL_AOE", band="MELEE", magnitude=0.75)
    add("Lillia", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Lissandra
    add("Lissandra", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Lissandra", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Lucian
    add("Lucian", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Lucian", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Lulu
    add("Lulu", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Lulu", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Lux
    add("Lux", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Lux", "E", "FULL_AOE", band="RANGED", magnitude=0.9)
    # Malphite
    add("Malphite", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Malphite", "W", "CLEAVE_AA", band="MELEE", magnitude=0.3)
    add("Malphite", "E", "FULL_AOE", band="MELEE", magnitude=0.75)
    # Malzahar
    add("Malzahar", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Malzahar", "W", "AOE_DOT", band="RANGED", magnitude=0.5)
    add("Malzahar", "E", "AOE_DOT", band="RANGED", magnitude=0.7)
    # Maokai
    add("Maokai", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Maokai", "E", "MULTI_HIT", band="RANGED", magnitude=0.4)
    # MasterYi
    add("MasterYi", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("MasterYi", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    # Mel
    add("Mel", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Mel", "W", "FULL_AOE", band="RANGED", magnitude=0.8)
    # Milio
    add("Milio", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # MissFortune
    add("MissFortune", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("MissFortune", "E", "FULL_AOE", band="RANGED", magnitude=0.9)
    # MonkeyKing
    add("MonkeyKing", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("MonkeyKing", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("MonkeyKing", "R", "FULL_AOE", band="MELEE", magnitude=0.85, cond=True)
    # Mordekaiser
    add("Mordekaiser", "Q", "MULTI_HIT", band="MELEE", magnitude=0.55)
    add("Mordekaiser", "E", "AOE_DOT", band="MELEE", magnitude=0.4)
    # Morgana
    add("Morgana", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Morgana", "W", "FULL_AOE", band="RANGED", magnitude=0.95)
    # Naafiri
    add("Naafiri", "P", "MULTI_HIT", band="MELEE", magnitude=0.3)
    add("Naafiri", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    # Nami
    add("Nami", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Nami", "W", "MULTI_HIT", band="RANGED", magnitude=0.3)
    # Nasus
    add("Nasus", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.25)
    add("Nasus", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    add("Nasus", "E", "AOE_DOT", band="MELEE", magnitude=0.65)
    # Nautilus
    add("Nautilus", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Nautilus", "E", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Neeko
    add("Neeko", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Neeko", "W", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Neeko", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Nidalee
    add("Nidalee", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Nidalee", "W", "MULTI_HIT", band="MELEE", magnitude=0.45, cond=True)
    # Nilah
    add("Nilah", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.45)
    add("Nilah", "E", "MULTI_HIT", band="MELEE", magnitude=0.5)
    # Nocturne
    add("Nocturne", "P", "CLEAVE_AA", band="MELEE", magnitude=0.3)
    add("Nocturne", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Nocturne", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Nunu
    add("Nunu", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.25)
    add("Nunu", "E", "MULTI_HIT", band="MELEE", magnitude=0.65)
    # Olaf
    add("Olaf", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Olaf", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Orianna
    add("Orianna", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Orianna", "W", "MULTI_HIT", band="RANGED", magnitude=0.5)
    # Ornn
    add("Ornn", "Q", "MULTI_HIT", band="MELEE", magnitude=0.4)
    add("Ornn", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Pantheon
    add("Pantheon", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Pantheon", "E", "FULL_AOE", band="MELEE", magnitude=0.85)
    # Poppy
    add("Poppy", "Q", "MULTI_HIT", band="MELEE", magnitude=0.4)
    add("Poppy", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Pyke
    add("Pyke", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Pyke", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Qiyana
    add("Qiyana", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Qiyana", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Quinn
    add("Quinn", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Quinn", "BASE", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Rakan
    add("Rakan", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Rakan", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Rammus
    add("Rammus", "W", "AOE_DOT", band="MELEE", magnitude=0.25)
    add("Rammus", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Rammus", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # RekSai
    add("RekSai", "Q", "MULTI_HIT", band="MELEE", magnitude=0.6)
    add("RekSai", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Rell
    add("Rell", "W", "MULTI_HIT", band="MELEE", magnitude=0.4)
    add("Rell", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    add("Rell", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Renata
    add("Renata", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Renata", "E", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Renekton
    add("Renekton", "Q", "FULL_AOE", band="MELEE", magnitude=0.75)
    add("Renekton", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Rengar
    add("Rengar", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Rengar", "W", "MULTI_HIT", band="MELEE", magnitude=0.25)
    # Riven
    add("Riven", "Q", "MULTI_HIT", band="MELEE", magnitude=0.5)
    add("Riven", "W", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Rumble
    add("Rumble", "Q", "FULL_AOE", band="MELEE", magnitude=0.85)
    add("Rumble", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Ryze
    add("Ryze", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Ryze", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Samira
    add("Samira", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Samira", "R", "FULL_AOE", band="MELEE", magnitude=0.85, cond=True)
    # Sejuani
    add("Sejuani", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Sejuani", "W", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Senna
    add("Senna", "Q", "MULTI_HIT", band="RANGED", magnitude=0.25)
    add("Senna", "W", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Seraphine
    add("Seraphine", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Seraphine", "E", "MULTI_HIT", band="RANGED", magnitude=0.5)
    # Sett
    add("Sett", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.3)
    add("Sett", "W", "FULL_AOE", band="MELEE", magnitude=0.8)
    # Shaco
    add("Shaco", "W", "AOE_DOT", band="RANGED", magnitude=0.35, cond=True)
    add("Shaco", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Shen
    add("Shen", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.35)
    add("Shen", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Shyvana
    add("Shyvana", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.4)
    add("Shyvana", "E", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Shyvana", "R", "FULL_AOE", band="MELEE", magnitude=0.85, cond=True)
    # Singed
    add("Singed", "Q", "AOE_DOT", band="MELEE", magnitude=0.75)
    # Sion
    add("Sion", "Q", "FULL_AOE", band="MELEE", magnitude=0.85)
    add("Sion", "W", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Sion", "E", "MULTI_HIT", band="RANGED", magnitude=0.4)
    # Sivir
    add("Sivir", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Sivir", "W", "CLEAVE_AA", band="RANGED", magnitude=0.75)
    # Skarner
    add("Skarner", "Q", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Skarner", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    # Smolder
    add("Smolder", "Q", "FULL_AOE", band="RANGED", magnitude=0.85, cond=True)
    add("Smolder", "E", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Sona
    add("Sona", "P", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    add("Sona", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Soraka
    add("Soraka", "Q", "FULL_AOE", band="RANGED", magnitude=0.65)
    add("Soraka", "E", "AOE_DOT", band="RANGED", magnitude=0.2)
    # Swain
    add("Swain", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Swain", "W", "FULL_AOE", band="RANGED", magnitude=0.55)
    add("Swain", "R", "AOE_DOT", band="MELEE", magnitude=0.7, cond=True)
    # Sylas
    add("Sylas", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    add("Sylas", "E", "FULL_AOE", band="MELEE", magnitude=0.85)
    # Syndra
    add("Syndra", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Syndra", "W", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Syndra", "E", "MULTI_HIT", band="RANGED", magnitude=0.5)
    # TahmKench
    add("TahmKench", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("TahmKench", "W", "MULTI_HIT", band="MELEE", magnitude=0.3)
    add("TahmKench", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Taliyah
    add("Taliyah", "Q", "FULL_AOE", band="RANGED", magnitude=0.9)
    add("Taliyah", "W", "MULTI_HIT", band="RANGED", magnitude=0.3)
    # Talon
    add("Talon", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Talon", "W", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Taric
    add("Taric", "W", "SINGLE_TARGET", band="MELEE", magnitude=0.1)
    add("Taric", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Teemo
    add("Teemo", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.35)
    add("Teemo", "R", "AOE_DOT", band="RANGED", magnitude=0.6, cond=True)
    # Thresh
    add("Thresh", "E", "MULTI_HIT", band="MELEE", magnitude=0.25)
    add("Thresh", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Tristana
    add("Tristana", "W", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Tristana", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Trundle
    add("Trundle", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Trundle", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Tryndamere
    add("Tryndamere", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    add("Tryndamere", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    # TwistedFate
    add("TwistedFate", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("TwistedFate", "W", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Twitch
    add("Twitch", "W", "AOE_DOT", band="RANGED", magnitude=0.3)
    add("Twitch", "E", "FULL_AOE", band="RANGED", magnitude=0.7)
    add("Twitch", "R", "MULTI_HIT", band="RANGED", magnitude=0.6, cond=True)
    # Udyr
    add("Udyr", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Udyr", "E", "FULL_AOE", band="MELEE", magnitude=0.8)
    # Urgot
    add("Urgot", "W", "AOE_DOT", band="MELEE", magnitude=0.55)
    add("Urgot", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.15)
    # Varus
    add("Varus", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Varus", "E", "MULTI_HIT", band="RANGED", magnitude=0.4)
    # Vayne
    add("Vayne", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Veigar
    add("Veigar", "Q", "MULTI_HIT", band="RANGED", magnitude=0.3)
    add("Veigar", "W", "FULL_AOE", band="RANGED", magnitude=0.9)
    # Velkoz
    add("Velkoz", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Velkoz", "W", "AOE_DOT", band="RANGED", magnitude=0.5)
    add("Velkoz", "E", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Vex
    add("Vex", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Vex", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Vi
    add("Vi", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Vi", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Viego
    add("Viego", "Q", "CLEAVE_AA", band="MELEE", magnitude=0.35)
    add("Viego", "E", "MULTI_HIT", band="MELEE", magnitude=0.25)
    # Viktor
    add("Viktor", "E", "AOE_DOT", band="RANGED", magnitude=0.75)
    add("Viktor", "R", "FULL_AOE", band="RANGED", magnitude=0.95, cond=True)
    # Vladimir
    add("Vladimir", "W", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("Vladimir", "E", "FULL_AOE", band="MELEE", magnitude=0.85)
    # Volibear
    add("Volibear", "E", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Volibear", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Warwick
    add("Warwick", "BASE", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    # Xayah
    add("Xayah", "Q", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Xayah", "E", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Xerath
    add("Xerath", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Xerath", "W", "FULL_AOE", band="RANGED", magnitude=0.9)
    add("Xerath", "E", "SINGLE_TARGET", band="RANGED", magnitude=0.1)
    # XinZhao
    add("XinZhao", "Q", "MULTI_HIT", band="MELEE", magnitude=0.35)
    add("XinZhao", "W", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Yasuo
    add("Yasuo", "Q", "MULTI_HIT", band="MELEE", magnitude=0.55)
    add("Yasuo", "E", "SINGLE_TARGET", band="MELEE", magnitude=0.15)
    # Yone
    add("Yone", "Q", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Yone", "W", "MULTI_HIT", band="MELEE", magnitude=0.5)
    # Yorick
    add("Yorick", "P", "AOE_DOT", band="MELEE", magnitude=0.55)
    add("Yorick", "Q", "SINGLE_TARGET", band="MELEE", magnitude=0.2)
    add("Yorick", "E", "MULTI_HIT", band="MELEE", magnitude=0.4)
    # Yunara
    add("Yunara", "Q", "MULTI_HIT", band="RANGED", magnitude=0.5)
    add("Yunara", "W", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Yuumi
    add("Yuumi", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    # Zac
    add("Zac", "Q", "MULTI_HIT", band="MELEE", magnitude=0.3)
    add("Zac", "W", "MULTI_HIT", band="MELEE", magnitude=0.45)
    add("Zac", "E", "MULTI_HIT", band="MELEE", magnitude=0.3)
    # Zed
    add("Zed", "Q", "MULTI_HIT", band="RANGED", magnitude=0.35)
    add("Zed", "W", "MULTI_HIT", band="RANGED", magnitude=0.4)
    # Zeri
    add("Zeri", "Q", "SINGLE_TARGET", band="RANGED", magnitude=0.2)
    add("Zeri", "W", "MULTI_HIT", band="RANGED", magnitude=0.45)
    # Ziggs
    add("Ziggs", "Q", "FULL_AOE", band="GLOBAL", magnitude=0.9)
    add("Ziggs", "W", "MULTI_HIT", band="RANGED", magnitude=0.4)
    add("Ziggs", "E", "AOE_DOT", band="RANGED", magnitude=0.7)
    # Zilean
    add("Zilean", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    # Zoe
    add("Zoe", "Q", "MULTI_HIT", band="RANGED", magnitude=0.45)
    add("Zoe", "E", "MULTI_HIT", band="RANGED", magnitude=0.35)
    # Zyra
    add("Zyra", "Q", "FULL_AOE", band="RANGED", magnitude=0.85)
    add("Zyra", "W", "AOE_DOT", band="RANGED", magnitude=0.55)
    add("Zyra", "E", "FULL_AOE", band="RANGED", magnitude=0.8)

    return {champ: tuple(entries) for champ, entries in raw.items()}


_WAVECLEAR_REGISTRY: dict[str, tuple[WaveclearEntry, ...]] = (
    _build_waveclear_registry()
)


@dataclass(frozen=True)
class WaveclearSourceEntry:
    """One scored wave-clear mechanism for a champion."""

    source_key: str
    kind: str
    range_band: str
    kind_weight: float
    range_mult: float
    magnitude: float
    conditional: bool
    value: float

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "kind": self.kind,
            "range_band": self.range_band,
            "kind_weight": self.kind_weight,
            "range_mult": self.range_mult,
            "magnitude": round(self.magnitude, 4),
            "conditional": self.conditional,
            "value": round(self.value, 4),
        }


@dataclass(frozen=True)
class WaveclearResult:
    """Aggregate wave-clear / shove capability for one champion.

    ``waveclear_score`` sums every mechanism's weighted, range-discounted value
    (higher = clears faster / shoves harder). ``top_kind`` is the kind of the
    single strongest mechanism (the headline label, ``""`` when none).
    ``ranged_shove`` is True when at least one RANGED/GLOBAL mechanism
    contributes - the safe-shove flag a tempo consumer keys on. Returns all-zero
    with an empty ``sources`` tuple for an unregistered or blank champion (never
    raises).
    """

    champion: str
    mode: str
    waveclear_score: float
    top_kind: str
    ranged_shove: bool
    sources: tuple[WaveclearSourceEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "waveclear_score": round(self.waveclear_score, 4),
            "top_kind": self.top_kind,
            "ranged_shove": self.ranged_shove,
            "sources": [s.to_dict() for s in self.sources],
        }


def _empty_result(champion: str, mode: str) -> WaveclearResult:
    return WaveclearResult(
        champion=champion,
        mode=mode,
        waveclear_score=0.0,
        top_kind="",
        ranged_shove=False,
        sources=(),
    )


def _source_sort_key(entry: WaveclearEntry) -> tuple[int, str]:
    try:
        return (_SOURCE_ORDER.index(entry.source), entry.source)
    except ValueError:
        return (len(_SOURCE_ORDER), entry.source)


def compute_waveclear(champion: str, mode: str = "SR") -> WaveclearResult:
    """Aggregate a champion's wave-clear mechanisms into a shove score.

    Reads ``_WAVECLEAR_REGISTRY``. Each registered mechanism contributes a
    weighted, range-discounted value (``_mechanism_value``); the values are
    summed into ``waveclear_score``. ``top_kind`` is the kind of the highest-value
    mechanism; ``ranged_shove`` is True when any RANGED/GLOBAL mechanism
    contributes. ``mode`` is carried on the result for parity with the other
    scorers but does not change output today (clear identity is map-independent).

    Returns an all-zero ``WaveclearResult`` (empty ``sources``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _WAVECLEAR_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[WaveclearSourceEntry] = []
    total = 0.0
    best_kind = ""
    best_value = -1.0
    has_ranged = False
    for entry in sorted(entries, key=_source_sort_key):
        value = _mechanism_value(entry)
        total += value
        if value > best_value:
            best_value = value
            best_kind = entry.kind
        if value > 0.0 and entry.range_band in ("RANGED", "GLOBAL"):
            has_ranged = True
        scored.append(
            WaveclearSourceEntry(
                source_key=entry.source,
                kind=entry.kind,
                range_band=entry.range_band,
                kind_weight=_WAVECLEAR_KIND_WEIGHT.get(entry.kind, 0.0),
                range_mult=_WAVECLEAR_RANGE_MULT.get(entry.range_band, 0.0),
                magnitude=entry.magnitude,
                conditional=entry.conditional,
                value=value,
            )
        )

    return WaveclearResult(
        champion=champion,
        mode=safe_mode,
        waveclear_score=total,
        top_kind=best_kind if total > 0.0 else "",
        ranged_shove=has_ranged,
        sources=tuple(scored),
    )


__all__ = [
    "WaveclearEntry",
    "WaveclearResult",
    "WaveclearSourceEntry",
    "compute_waveclear",
    "_WAVECLEAR_KIND_WEIGHT",
    "_WAVECLEAR_RANGE_MULT",
    "_WAVECLEAR_CONDITIONAL_PROB",
    "_WAVECLEAR_REGISTRY",
]
