"""2026-05-30 (DS scraper-review slice; additive, no ENGINE bump) - champion-ability MODIFIER-block taxonomy.

Context (2026-05-30 DS review): a sibling project's scraper-refactor chat
flagged "modifiers aren't being considered" for abilities like Caitlyn W
(which shows 0 ability damage). The extractor classifies every ability
sub-block into ``attribute_kind`` and the ability-DPS evaluator consumes
ONLY ``"damage"`` blocks (``ability_dps.py`` block-select). When first read
at 16.11.1, 180 blocks carried ``attribute_kind == "modifier"`` and were
dropped from the damage sum (the live total is pinned by
``test_modifier_blocks_2026_05_30.py``).

That drop is CORRECT - but only because the modifier blocks are a
heterogeneous bag, NOT one clean "damage x N" multiplier. A blanket
"apply every modifier block as a multiplier" (the refactor's tempting
shortcut) is wrong: it would multiply champion damage by minion-only
numbers, double-count resist shred, and treat defensive damage-reduction
self-buffs as offense. The chat's own author noted "edge cases like that
will have to be reverted."

This module makes the modifier blocks QUERYABLE (so "modifiers are
considered" is true in the honest sense - visible + classified) without
corrupting any DPS number. Two engine modules import the classifier, and
each reads exactly one kind: ``data_loader.py`` (the per-rank percent
damage-reduction walk reads ``defensive_self``) and ``self_shred.py`` (the
self-shred uplift reads ``target_shred``). ``server.py`` serves
``summarize_modifiers`` on the modifier-summary route. Moving a block
between ``pve_only``, ``damage_amp_self`` and ``other`` therefore changes
that route's JSON and nothing a scorer reads
(``test_modifier_taxonomy_live_s144d282.py`` pins the importers and
the kinds they read).

Taxonomy (``classify_modifier_kind``):

* ``pve_only``       - minion / monster / non-champion / epic / turret
                       damage or heal (Aatrox W, Belveth Q, Heimerdinger W
                       minion totals). CORRECTLY excluded from champion
                       DPS. The bulk (about two thirds when first read at
                       16.11.1). A "Non-Minion" block is champion-scoped
                       and is NOT PvE.
* ``target_shred``   - reduces the TARGET's armor / MR / resistances / AD
                       (Nasus E, Corki E, Briar Q, KogMaw Q, JarvanIV Q,
                       Trundle Q). The ONE class with real unconditional
                       champion-DPS impact that the damage scorers do not
                       apply - RC models it only as the fight report's
                       self-shred uplift (``self_shred``); folding it into
                       a scorer is a future engine slice (its own ENGINE
                       bump + DS validation), NOT applied here.
* ``defensive_self`` - damage reduction / bonus resistance on the caster
                       or an ally (Garen W, Alistar R, Galio W, Braum E,
                       Jax R magic resistance). Belongs to EHP, never DPS.
* ``damage_amp_self``- increases the caster's OWN damage (Caitlyn W headshot,
                       Fiora E crit, Mordekaiser Q isolation, Hwei Q /
                       Sion Q max-charge). These are EITHER conditional-target-state
                       amps (the conditional-block schema's job; the arc is
                       operator-CLOSED per s232) OR auto-attack
                       empowerments that belong in the AA scorer
                       (``compute_dps``), NOT ``ability_dps``.
* ``other``          - movement speed / size / cost / cooldown / grey-health
                       / replicated-projectile utility (Quinn R, Shyvana R,
                       Vayne R, TahmKench E grey health, Mel W replicated
                       projectile), plus champion-scoped maxima and totals
                       that restate the form's own damage blocks (Aatrox Q,
                       Heimerdinger W "Non-Minion" rows).

The classifier is a pure function over the Meraki attribute name (the same
string ``_classify_attribute`` already routed to ``"modifier"``).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# Ordered classification: the FIRST matching bucket wins, so PvE is checked
# before everything (a "Monster Damage Reduction" is PvE, not shred).
MODIFIER_KINDS: tuple[str, ...] = (
    "pve_only",
    "target_shred",
    "defensive_self",
    "damage_amp_self",
    "other",
)

# PvE: anything scoped to minions / monsters / non-champions / epic / turret.
# The lookbehind keeps "Non-Minion" (champion-scoped: Aatrox Q, Heimerdinger W)
# out; a bare word boundary matches the word after the hyphen.
_PVE_RE = re.compile(
    r"\b(?<!non-)(minion|monster|non-champion|nonchampion|non-epic|epic|turret|"
    r"jungle|small monster|large monster)\b",
    re.IGNORECASE,
)

# target_shred: reduces an enemy stat (armor / MR / resistance / AD).
_SHRED_RE = re.compile(
    r"(armor reduction|magic resistance reduction|"
    r"resistances? reduction|mr reduction|"
    r"attack damage reduction|resistance reduction)",
    re.IGNORECASE,
)

# defensive_self: caster/ally takes less damage OR gains resistance.
_DEFENSIVE_RE = re.compile(
    r"(damage reduction|bonus magic resistance|bonus armor|"
    r"bonus resistance|magic shield|spell shield)",
    re.IGNORECASE,
)

# other, checked BEFORE the amp patterns: grey health is damage TAKEN
# (TahmKench E) and a replicated projectile reflects an ENEMY's damage
# (Mel W); both match "damage stored" / "damage modifier" otherwise.
_OTHER_FIRST_RE = re.compile(r"(grey health|replicated projectile)", re.IGNORECASE)

# damage_amp_self: increases the caster's OWN outgoing damage.
_AMP_RE = re.compile(
    r"(damage increase|critical damage|headshot|"
    r"increased damage|damage modifier|stored damage|"
    r"maximum base damage|damage stored)",
    re.IGNORECASE,
)


def classify_modifier_kind(attribute: str) -> str:
    """Return one of :data:`MODIFIER_KINDS` for a modifier-block attribute.

    Pure function over the Meraki attribute name. Order: PvE first (a
    "Monster Damage Reduction" is PvE), then target-shred, then defensive
    self-buff, then grey-health / replicated-projectile ``other``, then
    self damage-amp, else ``other``.
    """
    s = (attribute or "").strip()
    if _PVE_RE.search(s):
        return "pve_only"
    if _SHRED_RE.search(s):
        return "target_shred"
    if _DEFENSIVE_RE.search(s):
        return "defensive_self"
    if _OTHER_FIRST_RE.search(s):
        return "other"
    if _AMP_RE.search(s):
        return "damage_amp_self"
    return "other"


@dataclass(frozen=True)
class ModifierSummary:
    """Roster-wide modifier-block taxonomy snapshot."""

    total: int
    by_kind: dict[str, int]
    target_shred_examples: tuple[str, ...]   # "Champion.Key attribute"
    damage_amp_examples: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "by_kind": dict(self.by_kind),
            "target_shred_examples": list(self.target_shred_examples),
            "damage_amp_examples": list(self.damage_amp_examples),
        }


def summarize_modifiers(abilities) -> ModifierSummary:
    """Walk an :class:`AbilitiesSnapshot` and bucket every modifier block.

    ``abilities`` is an ``abilities.AbilitiesSnapshot`` (or anything exposing
    ``iter_forms() -> (champ_id, key, form)`` whose forms carry
    ``damage_blocks`` with ``attribute_kind`` / ``attribute``).
    """
    by_kind: Counter[str] = Counter()
    shred: list[str] = []
    amp: list[str] = []
    total = 0
    for champ_id, key, form in abilities.iter_forms():
        for b in form.damage_blocks:
            if b.attribute_kind != "modifier":
                continue
            total += 1
            kind = classify_modifier_kind(b.attribute)
            by_kind[kind] += 1
            tag = f"{champ_id}.{key} {b.attribute}"
            if kind == "target_shred" and len(shred) < 24:
                shred.append(tag)
            elif kind == "damage_amp_self" and len(amp) < 24:
                amp.append(tag)
    # Ensure every known kind has a (possibly zero) entry for stable shape.
    full = {k: int(by_kind.get(k, 0)) for k in MODIFIER_KINDS}
    return ModifierSummary(
        total=total,
        by_kind=full,
        target_shred_examples=tuple(shred),
        damage_amp_examples=tuple(amp),
    )
