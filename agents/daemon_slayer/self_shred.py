"""2026-05-30 (DS V2 slice; additive, no ENGINE bump) - self-shred DPS uplift.

Context (item 226 NEXT): ``modifier_blocks.py`` classifies champion-ability
modifier blocks into a taxonomy; its ``"target_shred"`` bucket flags the
abilities that reduce a TARGET's own armor / MR (Nasus E, Corki E,
JarvanIV Q, Wukong Q, Yorick E, Briar Q, Evelynn W, Rumble E, KogMaw Q,
Renekton E, Rengar R). The classifier makes those blocks queryable but
computes NOTHING - it deliberately stops short of the DPS impact (see its
docstring: "the ONE class with real unconditional champion-DPS impact
that RC does not yet model").

This module is that deliberate self-shred-DPS slice. Given a champion +
level + a fixed target armor/MR + the champion's OWN physical/magic DPS
against that target, it computes the DPS UPLIFT a champion gets from
shredding the target's resistances over a fight: the mitigation factor
goes UP as the resist drops, so the same raw damage lands harder.

Core math (matches the engine's resist->multiplier curve - we import
``dps._armor_factor`` rather than re-deriving the formula):

    shredded = max(0, target_resist - flat_shred - target_resist * pct_shred)
    old_mit  = armor_factor(target_resist)        # 100/(100+R) for R>=0
    new_mit  = armor_factor(shredded)             # rises as R drops
    uplift   = champion_dps * (new_mit / old_mit - 1)

We shred armor against the champion's PHYSICAL DPS and MR against its
MAGIC DPS (the modifier block's resist-kind selects which). The
``shredded`` value is floored at 0 so the mitigation path never sees a
negative resist created by an over-shred (a real over-shred would push a
target to true 0 armor, not into the negative-armor amp branch - that
branch is for lethality / flat-pen, a different mechanic).

PURELY ADDITIVE + fail-soft: nothing in the live DPS / EHP / ability-DPS
scorer path imports this. It is the substrate a future deliberate engine
slice (its own ENGINE bump + DS validation) or a coach surface would
build on. A champion with no ``target_shred`` block yields a 0.0 uplift
with an explanatory note and NEVER raises.

Source-of-truth: the committed abilities snapshot
``data/daemon_slayer/<patch>/champion_abilities.json`` via
``abilities.AbilitiesSnapshot``. Shred magnitude lives in the modifier
block's ``raw_modifiers`` (``{values: [...], units: [...]}``); the unit
string distinguishes percent ("% of target's armor", "%") from flat
(blank units, e.g. Corki E "Total Resistances Reduction" 12-20 flat).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .abilities import AbilitiesNotFound, AbilitiesSnapshot, AbilityForm
from .dps import _armor_factor
from .modifier_blocks import classify_modifier_kind

__all__ = [
    "SelfShredUplift",
    "compute_self_shred_uplift",
]

# Resist kinds we model. AD-reduction shreds (Trundle Q, Tryndamere W) are
# classified ``target_shred`` by ``modifier_blocks`` but reduce the
# TARGET's OUTGOING damage, not the resist that mitigates OUR damage - so
# they do NOT produce a self-DPS uplift and are skipped here.
RESIST_ARMOR = "armor"
RESIST_MR = "mr"

# When a champion has multiple shred forms/blocks (Corki E ships both a
# per-stack and a Total block; Rumble E ships base + enhanced + totals),
# we pick the single strongest source by post-shred mitigation gain. We
# prefer "Total" / "Enhanced" blocks implicitly because they carry the
# larger magnitude, so the max-by-uplift selection lands on them.


@dataclass(frozen=True)
class SelfShredUplift:
    """DPS uplift a champion gains from shredding a target's resistance.

    ``dps_uplift_pct`` is the percentage increase to the relevant damage
    channel (physical for armor shred, magic for MR shred): the same raw
    DPS lands harder once the resist drops. ``0.0`` when the champion has
    no modeled shred (see ``notes``).
    """

    champion: str
    level: int
    shred_source: str          # e.g. "Nasus:E" or "" when no shred
    flat_shred: float          # flat resist points removed (Corki/Rengar)
    pct_shred: float           # fraction of target resist removed (0.0-1.0)
    resist_kind: str           # "armor" | "mr" | "" (no shred)
    target_resist: float       # the pre-shred resist value used
    old_mit_factor: float      # armor_factor(target_resist)
    new_mit_factor: float      # armor_factor(shredded_resist)
    dps_uplift_pct: float      # (new/old - 1) * 100, >= 0
    dps_uplift_abs: float      # champion_dps * (new/old - 1), >= 0
    notes: str

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "level": self.level,
            "shred_source": self.shred_source,
            "flat_shred": self.flat_shred,
            "pct_shred": self.pct_shred,
            "resist_kind": self.resist_kind,
            "target_resist": self.target_resist,
            "old_mit_factor": self.old_mit_factor,
            "new_mit_factor": self.new_mit_factor,
            "dps_uplift_pct": self.dps_uplift_pct,
            "dps_uplift_abs": self.dps_uplift_abs,
            "notes": self.notes,
        }


def _rank_at_level(level: int) -> int:
    """0-indexed max-rank slot for a basic ability at the given level.

    Self-shred is a ranking/coach substrate, not a per-point optimizer, so
    we use the simple "1 rank per 2 levels, capped at rank 5 (index 4)"
    heuristic for Q/W/E shreds and clamp ult shreds (Rengar R, 3 ranks)
    separately by length. Picking the highest rank the level supports
    matches the "assume the amped condition is met" ranking convention the
    engine uses elsewhere (block_index defaults). The exact per-point order
    does not change the shred magnitude meaningfully for a fight-window
    estimate.
    """
    if level < 1:
        level = 1
    # rank index: lvl 1 -> 0, lvl 3 -> 1, ... lvl 9 -> 4 (rank 5).
    return min(4, (level - 1) // 2)


def _resist_kind_for(attribute: str, damage_type: Optional[str]) -> Optional[str]:
    """Classify a target_shred block's attribute into a resist channel.

    Returns ``"armor"`` / ``"mr"`` / ``None``. ``None`` means the shred
    does not affect a mitigation resist (Attack Damage reduction) and is
    skipped. Generic "Resistances Reduction" blocks (Briar Q, KogMaw Q,
    Corki E) hit BOTH armor and MR in game; we route them by the spell's
    own damage_type (a magic-damage spell's shred boosts the magic
    channel), defaulting to armor when the type is physical/unknown.
    """
    a = (attribute or "").lower()
    if "attack damage" in a:
        return None  # reduces target's outgoing AD, not a mitigation resist
    if "magic resistance" in a or "mr reduction" in a or "total mr" in a:
        return RESIST_MR
    if "armor" in a:
        return RESIST_ARMOR
    if "resistance" in a:
        # Generic "Resistances Reduction" - applies to both. Route by the
        # spell's damage type so the uplift lands on the matching channel.
        dt = (damage_type or "").upper()
        return RESIST_MR if dt == "MAGIC" else RESIST_ARMOR
    return None


def _is_percent(units) -> bool:
    """A shred is percent when its unit string carries a ``%``.

    Flat shreds (Corki E "Total Resistances Reduction", Rengar R) carry a
    blank unit string. Percent shreds carry "%" or "% of target's armor".
    """
    if not units:
        return False
    first = units[0] if isinstance(units, (list, tuple)) else units
    return "%" in str(first or "")


def _extract_shred(block) -> Optional[tuple[float, float, str]]:
    """Pull (flat_shred, pct_shred, label_suffix) from a modifier block.

    ``block`` is an ``abilities.DamageBlock``. Reads ``raw_modifiers`` -
    a tuple of ``{values: [...], units: [...]}`` dicts. Percent shreds
    (units carry ``%``) populate ``pct_shred`` (as a 0.0-1.0 fraction);
    flat shreds populate ``flat_shred`` (resist points). Returns ``None``
    when the block carries no usable magnitude.

    The per-rank value chosen is supplied by the caller via the values
    list index; this helper returns BOTH the values list slot picked and
    whether it is percent so the caller can rank-select.
    """
    raw = getattr(block, "raw_modifiers", None) or ()
    if not raw:
        return None
    first = raw[0] if isinstance(raw, (list, tuple)) else raw
    if not isinstance(first, dict):
        return None
    values = first.get("values") or []
    units = first.get("units") or []
    if not values:
        return None
    pct = _is_percent(units)
    # Marker tuple: (values, is_percent). The caller indexes values by rank.
    return (values, pct)  # type: ignore[return-value]


def _shred_at_rank(values, rank: int) -> float:
    """Read the per-rank shred value, clamping the rank to the list."""
    if not values:
        return 0.0
    if rank < 0:
        rank = 0
    if rank >= len(values):
        rank = len(values) - 1
    try:
        return float(values[rank])
    except (TypeError, ValueError):
        return 0.0


def _candidate_shreds(
    forms_by_key: dict,
    damage_type_by_form,
    rank: int,
) -> list[tuple[str, float, float, str]]:
    """Collect every modeled target_shred from a champion's ability map.

    Returns a list of ``(source, flat_shred, pct_shred, resist_kind)``
    tuples, one per qualifying modifier block (skipping AD-reduction).
    ``source`` is ``"<key>"`` (e.g. ``"E"``); the caller prefixes the
    champion id.
    """
    out: list[tuple[str, float, float, str]] = []
    for key, forms in forms_by_key.items():
        if not isinstance(forms, (list, tuple)):
            forms = (forms,)
        for form in forms:
            blocks = getattr(form, "damage_blocks", None) or ()
            dt = getattr(form, "damage_type", None)
            for block in blocks:
                if getattr(block, "attribute_kind", "") != "modifier":
                    continue
                attr = getattr(block, "attribute", "") or ""
                if classify_modifier_kind(attr) != "target_shred":
                    continue
                rk = _resist_kind_for(attr, dt)
                if rk is None:
                    continue  # AD-reduction: no mitigation uplift
                extracted = _extract_shred(block)
                if extracted is None:
                    continue
                values, is_pct = extracted
                mag = _shred_at_rank(values, rank)
                if mag <= 0:
                    continue
                if is_pct:
                    out.append((str(key), 0.0, mag / 100.0, rk))
                else:
                    out.append((str(key), mag, 0.0, rk))
    return out


def _no_shred_result(
    champion: str,
    level: int,
    target_armor: float,
    target_mr: float,
    note: str,
) -> SelfShredUplift:
    """Build a fail-soft zero-uplift result with an explanatory note."""
    return SelfShredUplift(
        champion=champion,
        level=level,
        shred_source="",
        flat_shred=0.0,
        pct_shred=0.0,
        resist_kind="",
        target_resist=0.0,
        old_mit_factor=0.0,
        new_mit_factor=0.0,
        dps_uplift_pct=0.0,
        dps_uplift_abs=0.0,
        notes=note,
    )


def compute_self_shred_uplift(
    champion: str,
    level: int,
    target_armor: float,
    target_mr: float,
    champion_physical_dps: float = 0.0,
    champion_magic_dps: float = 0.0,
    snapshot: Optional[AbilitiesSnapshot] = None,
) -> SelfShredUplift:
    """DPS uplift ``champion`` gains by shredding the target's resistance.

    Resolves the strongest ``target_shred`` ability the champion owns from
    the abilities snapshot, applies it to the matching resist
    (armor->physical DPS, MR->magic DPS), and returns the resulting
    mitigation-factor gain as a percentage + absolute DPS.

    ``champion_physical_dps`` / ``champion_magic_dps`` are the champion's
    OWN pre-mitigation-applied DPS against the target on each channel - the
    "or a way to derive it" path is kept pure: the caller supplies the DPS
    (e.g. from ``dps.compute_dps`` for the physical AA channel or
    ``ability_dps.compute_ability_dps`` for the magic channel) so this
    module stays free of the build resolver. The uplift scales linearly
    with whichever channel matches the shred's resist kind.

    Fail-soft: a champion with no modeled shred (or an unknown champion, or
    a parse-degenerate snapshot) returns a 0.0-uplift result with a note
    and NEVER raises.

    Selection: when a champion ships multiple shred sources (Corki E
    per-stack + total; Rumble E base + enhanced) the source with the
    largest mitigation-factor gain wins - that naturally lands on the
    "Total" / "Enhanced" block (the realistic max-shred a fight reaches).
    """
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    if lvl < 1:
        lvl = 1
    champ = str(champion or "").strip()
    if not champ:
        return _no_shred_result(
            "", lvl, target_armor, target_mr,
            "blank champion id - no shred resolved",
        )

    try:
        snap = snapshot or AbilitiesSnapshot.load()
    except Exception as exc:  # fail-soft: snapshot load issue
        return _no_shred_result(
            champ, lvl, target_armor, target_mr,
            f"abilities snapshot unavailable ({type(exc).__name__})",
        )

    try:
        forms_by_key = snap.get_abilities(champ)
    except AbilitiesNotFound:
        return _no_shred_result(
            champ, lvl, target_armor, target_mr,
            f"champion {champ!r} not in abilities snapshot",
        )
    except Exception as exc:  # fail-soft: any other lookup failure
        return _no_shred_result(
            champ, lvl, target_armor, target_mr,
            f"ability lookup failed ({type(exc).__name__})",
        )

    if not isinstance(forms_by_key, dict) or not forms_by_key:
        return _no_shred_result(
            champ, lvl, target_armor, target_mr,
            f"no ability forms for {champ!r}",
        )

    rank = _rank_at_level(lvl)
    candidates = _candidate_shreds(forms_by_key, None, rank)
    if not candidates:
        return _no_shred_result(
            champ, lvl, target_armor, target_mr,
            f"{champ!r} has no armor/MR target_shred ability - uplift 0.0",
        )

    best: Optional[SelfShredUplift] = None
    for key, flat_shred, pct_shred, resist_kind in candidates:
        base_resist = float(
            target_armor if resist_kind == RESIST_ARMOR else target_mr
        )
        shredded = base_resist - flat_shred - base_resist * pct_shred
        if shredded < 0.0:
            shredded = 0.0  # floor: never push the mit path into neg-armor amp
        old_mit = _armor_factor(base_resist)
        new_mit = _armor_factor(shredded)
        if old_mit <= 0.0:
            uplift_ratio = 0.0
        else:
            uplift_ratio = (new_mit / old_mit) - 1.0
        if uplift_ratio < 0.0:
            uplift_ratio = 0.0
        channel_dps = float(
            champion_physical_dps
            if resist_kind == RESIST_ARMOR
            else champion_magic_dps
        )
        result = SelfShredUplift(
            champion=champ,
            level=lvl,
            shred_source=f"{champ}:{key}",
            flat_shred=float(flat_shred),
            pct_shred=float(pct_shred),
            resist_kind=resist_kind,
            target_resist=base_resist,
            old_mit_factor=old_mit,
            new_mit_factor=new_mit,
            dps_uplift_pct=uplift_ratio * 100.0,
            dps_uplift_abs=channel_dps * uplift_ratio,
            notes=(
                f"{champ} {key} shreds {resist_kind} "
                f"(flat {flat_shred:.1f} + pct {pct_shred * 100:.0f}%) at "
                f"rank {rank + 1}: mit {old_mit:.4f} -> {new_mit:.4f}"
            ),
        )
        if best is None or result.dps_uplift_pct > best.dps_uplift_pct:
            best = result

    assert best is not None  # candidates non-empty guarantees a best
    return best
