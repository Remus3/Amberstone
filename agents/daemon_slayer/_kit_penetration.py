"""CHAMPION-KIT-intrinsic PHYSICAL penetration registry and DEFAULT-OFF seam.

R190 slice A. The item-side resist pipeline has been correct since ENGINE
1.5.1: ``effects.effective_target_armor`` applies League's four stages in
order (flat reduction -> percent reduction -> percent penetration -> flat
penetration), composes both percent stages MULTIPLICATIVELY, lets REDUCTION
cross zero and floors only the PENETRATION tail. What it has never seen is a
champion's OWN KIT.

THE GAP, MEASURED. Penetration has no generic stat path anywhere in the
engine. ``stats.ITEM_STAT_KEY_MAP`` carries no penetration key; DDragon's
structured ``stats`` block has no penetration entry; the vendored Meraki
catalog has ZERO keys matching "enetration" or "ethality" across all 320
items. ``ITEM_EFFECTS`` is the SOLE item-side credit path, and
``effective_target_armor`` accepts ONLY ``ItemEffect`` objects. So Darius's
40 percent armor penetration, Ambessa's 30 and Pantheon's 30 are credited
NOWHERE in the damage math. The single place kit penetration appears at all is
``antitank._ANTITANK_REGISTRY``, a hand-tuned 0..1 reliability heuristic on a
standalone opt-in scorer - a different question, a different unit, and it
never feeds the resist pipeline.

WHAT THIS MODULE IS. A hand-authored registry whose every row is derived from
the shipped ``data/daemon_slayer/<patch>/champion_abilities.json`` (both its
structured ``damage_blocks`` half and its ``effects_descriptions`` prose half),
plus a DEFAULT-OFF ``apply_kit_penetration`` seam. The seam calls straight
through to the unmodified pipeline unless a caller passes BOTH a champion and
``enabled=True``, so every existing call site is byte-identical.

THREE KINDS, ONE OF WHICH IS CREDITABLE.

* ``PERCENT_ARMOR`` - percent of the target's TOTAL armor. Exactly the quantity
  ``effective_target_armor`` models, so these fold into the percent-penetration
  stage next to Lord Dominik's and Serylda's, multiplicatively. Darius's own
  wiki notes state the rule verbatim: "The armor penetration stacks
  multiplicatively with other forms of percentage armor penetration."
* ``PERCENT_BONUS_ARMOR`` - percent of the target's BONUS armor only. The
  engine's target model is a single scalar armor with NO base/bonus split, so
  crediting these would require inventing the split. They are registered with
  their verbatim magnitude and are deliberately NOT creditable: a documented
  FUTURE, not a silent omission. K'Sante carries a second, independent reason -
  his notes say the row "stacks additively with other sources of percentage
  armor penetration", which is not the composition rule this seam implements.
* ``FLAT_LETHALITY`` - Aphelios only, and it is a PLAYER CHOICE rather than an
  automatic grant, so it is registered conditional and pays nothing unless a
  caller explicitly opts in.

RANK CONVENTION. Every rank-scaled row credits its MAX-RANK magnitude - the
same convention the DS build scorers use when they evaluate a completed build.
The per-rank ladders are quoted in each row's comment.

MAGIC PENETRATION IS OUT OF SCOPE. Annie R and Mordekaiser E state magic
penetration in the same structured feed; neither appears here, and the R190
guard test asserts they stay excluded. The magic axis is a sibling slice.

DELIBERATELY UNREGISTERED - Sylas R Hijack. His notes describe the stolen
Yasuo ultimate ("Critical strikes ignore 50% of the target's bonus armor after
activation"), but that is (a) a hijacked ability rather than his own kit and
(b) stated only in ``notes``, never in ``effects_descriptions``, so it is not
derivable from the structured or prose sweeps. It would also be
``PERCENT_BONUS_ARMOR`` and therefore uncreditable even if it were registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .effects import effective_target_armor

# Only percent-of-TOTAL-armor rows can enter the resist pipeline. See the
# module docstring: the engine's target model has no base/bonus armor split,
# so PERCENT_BONUS_ARMOR is registered-but-inert, and FLAT_LETHALITY is a
# player skill-point choice rather than an automatic grant.
CREDITABLE_KINDS: tuple[str, ...] = ("PERCENT_ARMOR",)


@dataclass(frozen=True)
class KitPenEntry:
    """One kit-intrinsic penetration mechanism on one champion ability.

    ``magnitude`` is a FRACTION for the two percent kinds (0.40 for Darius E)
    and a FLAT penetration value for ``FLAT_LETHALITY`` (33.0 for Aphelios),
    which is why the shape guard asserts percent rows are <= 1.0 and flat rows
    are > 1.0. ``conditional`` marks a row that needs a specific fight state,
    resource or player choice and therefore does not pay out by default.
    ``crit_scaled`` marks a row whose stated magnitude is the 100-percent-crit
    endpoint of a "(based on critical strike chance)" ramp; the resolver scales
    it by the caller's crit chance. ``tooltip`` is the verbatim ability text
    the magnitude was read from.
    """

    champion: str
    slot: str
    ability: str
    kind: str
    magnitude: float
    tooltip: str
    conditional: bool = False
    crit_scaled: bool = False


@dataclass(frozen=True)
class KitPenetration:
    """The resolved ``(pct, flat)`` a champion contributes to the pipeline.

    ``pct`` is already COMPOSED across every creditable row (and any
    ``extra_pct`` the caller injected), so it is a single penetration fraction
    ready to hand to ``effective_target_armor``'s ``kit_pen_pct``. ``rows`` is
    the subset that actually paid out, for provenance.
    """

    pct: float
    flat: float
    rows: tuple[KitPenEntry, ...]


def _rows() -> dict[str, tuple[KitPenEntry, ...]]:
    """Build the registry. Every row cites its verbatim source text."""
    entries: list[KitPenEntry] = [
        # --- PERCENT_ARMOR: percent of TOTAL armor, creditable ------------
        # Structured block: Armor Penetration [10, 20, 30] percent. Max rank.
        KitPenEntry(
            champion="Ambessa",
            slot="R",
            ability="Public Execution",
            kind="PERCENT_ARMOR",
            magnitude=0.30,
            tooltip=(
                "Passive: Ambessa gains armor penetration and heals herself "
                "for a percentage of the post-mitigation damage she deals to "
                "enemies with her active abilities."
            ),
        ),
        # Structured block: Armor Penetration [20, 25, 30, 35, 40] percent.
        # Max rank. The wiki notes add: "The armor penetration stacks
        # multiplicatively with other forms of percentage armor penetration."
        KitPenEntry(
            champion="Darius",
            slot="E",
            ability="Apprehend",
            kind="PERCENT_ARMOR",
            magnitude=0.40,
            tooltip="Passive: Darius gains armor penetration.",
        ),
        # Structured block: Armor Penetration [10, 20, 30] percent. Max rank.
        KitPenEntry(
            champion="Pantheon",
            slot="R",
            ability="Grand Starfall",
            kind="PERCENT_ARMOR",
            magnitude=0.30,
            tooltip="Passive: Pantheon gains armor penetration.",
        ),
        # Rank-flat 40 percent, but gated on the keg chain reaction landing,
        # so CONDITIONAL: it applies only to the explosion damage.
        KitPenEntry(
            champion="Gangplank",
            slot="E",
            ability="Powder Keg",
            kind="PERCENT_ARMOR",
            magnitude=0.40,
            tooltip=(
                "Enemies caught in an explosion are slowed for 2 seconds, and "
                "are dealt the triggering attack's damage, dealing bonus "
                "physical damage against champions. Each enemy can only be hit "
                "once per chain and the damage dealt ignores 40% of the "
                "target's armor."
            ),
            conditional=True,
        ),
        # Rank-flat ramp whose magnitude is the 100-percent-crit endpoint, so
        # the row is CRIT-SCALED and conditional (zero at zero crit chance).
        KitPenEntry(
            champion="Nilah",
            slot="Q",
            ability="Formless Blade",
            kind="PERCENT_ARMOR",
            magnitude=0.33,
            tooltip=(
                "Passive: Nilah gains 0% : 33% (based on critical strike "
                "chance) armor penetration."
            ),
            conditional=True,
            crit_scaled=True,
        ),
        # --- PERCENT_BONUS_ARMOR: registered, NOT creditable --------------
        # Bonus armor only, and only on critical strikes, for 15 seconds.
        KitPenEntry(
            champion="Yasuo",
            slot="R",
            ability="Last Breath",
            kind="PERCENT_BONUS_ARMOR",
            magnitude=0.60,
            tooltip=(
                "For the next 15 seconds, the damage dealt by Yasuo's critical "
                "strikes ignores 60% of the target's bonus armor."
            ),
            conditional=True,
        ),
        # Bonus armor only. His notes also say it "stacks additively with
        # other sources of percentage armor penetration" - a second reason it
        # cannot ride this multiplicative seam.
        KitPenEntry(
            champion="KSante",
            slot="R",
            ability="All Out",
            kind="PERCENT_BONUS_ARMOR",
            magnitude=0.50,
            tooltip=(
                "In return, he gains bonus attack speed, 50% bonus-armor "
                "penetration, and 20% omnivamp, and modifies his basic "
                "abilities which can be cast at no cost."
            ),
            conditional=True,
        ),
        # --- FLAT_LETHALITY: registered, opt-in only ----------------------
        # Structured block: Lethality [5.5, 11, 16.5, 22, 27.5, 33]. Max rank
        # 33, and only if the player spends every skill point on lethality -
        # a CHOICE, never an automatic grant, so it is conditional.
        KitPenEntry(
            champion="Aphelios",
            slot="P",
            ability="The Hitman and the Seer",
            kind="FLAT_LETHALITY",
            magnitude=33.0,
            tooltip=(
                "Aphelios may spend his skill points to gain bonus attack "
                "damage, bonus attack speed or lethality instead."
            ),
            conditional=True,
        ),
    ]
    registry: dict[str, list[KitPenEntry]] = {}
    for entry in entries:
        registry.setdefault(entry.champion, []).append(entry)
    return {name: tuple(rows) for name, rows in registry.items()}


KIT_PENETRATION_REGISTRY: dict[str, tuple[KitPenEntry, ...]] = _rows()


def kit_penetration_rows(champion: Optional[str]) -> tuple[KitPenEntry, ...]:
    """Every registered row for ``champion``; ``()`` for anyone unregistered.

    The registry is a seeded allowlist keyed by the DDragon champion id, so
    the overwhelming majority of the roster returns the empty tuple by
    construction and contributes exactly nothing.
    """
    if not champion:
        return ()
    return KIT_PENETRATION_REGISTRY.get(champion, ())


def _clamp01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number <= 0.0:
        return 0.0
    return 1.0 if number >= 1.0 else number


def resolve_kit_penetration(
    champion: Optional[str],
    *,
    include_conditional: bool = False,
    crit_chance: float = 0.0,
    extra_pct: Iterable[float] = (),
) -> KitPenetration:
    """Resolve ``champion``'s creditable kit penetration into ``(pct, flat)``.

    Only ``CREDITABLE_KINDS`` rows are considered; a ``PERCENT_BONUS_ARMOR``
    row never pays out on either column no matter what flags are passed (see
    the module docstring - the target model has no base/bonus armor split).

    ``include_conditional`` defaults to False, so a row that needs a specific
    fight state, resource or player choice - Gangplank's keg chain, Nilah's
    crit ramp, Aphelios's skill-point spend - contributes nothing to the
    default frame. ``crit_chance`` (0..1, clamped) scales every ``crit_scaled``
    row by its stated ramp; at the default 0.0 Nilah's row is worth exactly
    what League says it is worth at zero crit, which is nothing.

    ``extra_pct`` lets a caller inject additional percent-of-total-armor
    penetration fractions from outside the registry. They compose under the
    SAME multiplicative rule, which is what keeps this resolver honest: the
    composition is ``1 - PROD(1 - p_i)``, never a sum, mirroring
    ``effects._composed_keep_factor``.

    Returns a ``KitPenetration``. The ``pct`` is a single already-composed
    fraction; ``flat`` is a plain sum (flat penetration sums in League);
    ``rows`` is the subset that actually paid out.
    """
    crit = _clamp01(crit_chance)
    keep = 1.0
    flat = 0.0
    paid: list[KitPenEntry] = []
    for row in kit_penetration_rows(champion):
        if row.kind not in CREDITABLE_KINDS:
            continue
        magnitude = float(row.magnitude)
        if row.crit_scaled:
            # A crit-scaled row is SELF-gating and needs no opt-in: the stated
            # figure is the 100-percent-crit endpoint of a linear
            # "0% : N% (based on critical strike chance)" ramp, so at the
            # default crit_chance=0.0 it already pays exactly nothing, and at
            # a nonzero crit chance the ramp IS the condition.
            magnitude *= crit
            if magnitude <= 0.0:
                continue
        elif row.conditional and not include_conditional:
            continue
        keep *= 1.0 - magnitude
        paid.append(row)
    for extra in extra_pct:
        keep *= 1.0 - _clamp01(extra)
    for row in kit_penetration_rows(champion):
        if row.kind != "FLAT_LETHALITY":
            continue
        if row.conditional and not include_conditional:
            continue
        flat += float(row.magnitude)
        paid.append(row)
    return KitPenetration(pct=1.0 - keep, flat=flat, rows=tuple(paid))


def apply_kit_penetration(
    target_armor: float,
    effects,
    level: Optional[int] = None,
    *,
    champion: Optional[str] = None,
    enabled: bool = False,
    include_conditional: bool = False,
    crit_chance: float = 0.0,
) -> float:
    """DEFAULT-OFF seam over ``effects.effective_target_armor``.

    With ``enabled=False`` (the default) or no ``champion``, this is a pure
    passthrough to the unmodified pipeline and the result is BYTE-IDENTICAL to
    a direct ``effective_target_armor(target_armor, effects, level)`` call - no
    registry lookup, no composition, nothing. That is the whole contract: a
    caller that does not opt in cannot observe this lane.

    With both supplied, the champion's creditable rows are resolved and handed
    to the pipeline through its ``kit_pen_pct`` / ``kit_pen_flat`` arguments,
    where they compose multiplicatively with item percent penetration and sum
    into the flat-penetration stage respectively. An unregistered champion
    resolves to ``(0.0, 0.0)``, which is itself byte-identical.
    """
    if not enabled or not champion:
        return effective_target_armor(target_armor, effects, level)
    resolved = resolve_kit_penetration(
        champion,
        include_conditional=include_conditional,
        crit_chance=crit_chance,
    )
    if not resolved.pct and not resolved.flat:
        return effective_target_armor(target_armor, effects, level)
    return effective_target_armor(
        target_armor,
        effects,
        level,
        kit_pen_pct=resolved.pct,
        kit_pen_flat=resolved.flat,
    )


__all__ = [
    "CREDITABLE_KINDS",
    "KIT_PENETRATION_REGISTRY",
    "KitPenEntry",
    "KitPenetration",
    "apply_kit_penetration",
    "kit_penetration_rows",
    "resolve_kit_penetration",
]
