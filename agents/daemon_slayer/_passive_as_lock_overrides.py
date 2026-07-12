"""2026-07-12 - per-champion attack-speed LOCK + AS/crit -> AD conversion registry.

A tiny class of champions have an INNATE passive that LOCKS their attack speed
(item / rune attack speed grants nothing) and instead converts a portion of that
would-be bonus attack speed - plus a portion of critical strike chance - into
bonus ATTACK DAMAGE, scaled as a percentage of BASE AD. Jhin's ``Whisper`` is
the canonical (currently only) case: his attack speed is frozen at 0.625 and he
gains bonus AD = (level% + 0.30 per 1% bonus AS + 0.35 per 1% crit) of base AD.

The DS stat pipeline (``engine.build_champion``) resolves base + item + rune AS
into ``item_totals["as_pct"]`` and folds it into ``stats["as"]`` via the generic
AS rebuild; DDragon / Meraki strip Whisper's numbers (Jhin's champion record is
prose-only), so without this registry the engine (1) over-credits Jhin with item
attack speed he can never actually gain and (2) under-credits the AD his passive
converts that attack speed / crit into. Both errors compound in every scorer that
resolves stats (dps / burst / ability_dps / hybrid / ehp / rank / beam /
build_order), so the fix lives at the single load-time chokepoint
``engine.build_champion`` rather than in any one scorer.

CONSUMER: ``engine.build_champion`` unconditionally (DEFAULT-ON) - Whisper is a
permanent mechanic, not an opt-in seam. The consumer walk is guarded on
``as_lock_entry(champion_id) is not None``, so every champion WITHOUT an entry is
byte-identical to the prior engine version.

WHY AN EXPLICIT DICT, not an automatic "attackspeedperlevel == 0" rule: Belveth
shares Jhin's ``attackspeedperlevel == 0`` DDragon signature but has UNCAPPED
attack-speed scaling (item AS raises her AS normally). A perlevel-derived rule
would wrongly lock her. The lock is a bespoke champion mechanic and MUST be keyed
by champion id, verified per entry from the cited wiki fragment.

WHY HAND-AUTHORED, not parsed: same reasoning as the sibling
``_passive_as_overrides`` / ``_passive_damage_overrides`` registries - a text
parser mis-extracts the "X% (based on level)" endpoints and re-breaks on each
patch's prose rewrite. The exact coefficients + level table are authored from the
verbatim wiki fragment cited in the entry ``note``; a future patch re-extract
re-verifies the cited text rather than re-parsing it.

GROUND TRUTH: wiki.leagueoflegends.com Template:Data_Jhin/Whisper?action=raw,
re-verified 2026-07-12 (patch 16.13.1). Level% table
``4;5;6;7;8;9;10;11;12;14;16;20;24;28;32;36;40;44`` (L1-18); "0.3% per 1% bonus
attack speed"; "0.35% per 1% critical strike chance" (the crit coefficient was
0.4 historically, 0.35 as of this verification); "Jhin's attack speed cannot
increase except by leveling up".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AsLockEntry:
    """One champion's attack-speed lock + AS/crit -> base-AD conversion.

    locks_as: when True the champion's item/rune bonus attack speed is zeroed
      before the AS rebuild, so resolved AS stays at the leveled base value.
    level_ad_pct: 18-tuple of the bonus-AD percentage of BASE AD granted purely
      by champion level (index ``level - 1``); e.g. Jhin 4% at level 1, 44% at 18.
    ad_per_bonus_as: bonus AD as a fraction of base AD, per 1.0 (=100%) of bonus
      attack speed. 0.30 means 40% bonus AS -> 0.30 * 0.40 = 12% of base AD.
    ad_per_crit: bonus AD as a fraction of base AD, per 1.0 (=100%) of crit
      chance. 0.35 means 25% crit -> 0.35 * 0.25 = 8.75% of base AD.
    note: provenance (verbatim wiki fragment + patch).
    """

    locks_as: bool
    level_ad_pct: tuple[float, ...]
    ad_per_bonus_as: float = 0.30
    ad_per_crit: float = 0.35
    note: str = ""

    def level_ad_fraction(self, level: int) -> float:
        """Innate bonus-AD fraction of base AD from champion level alone."""
        idx = 1 if level < 1 else (18 if level > 18 else int(level))
        return self.level_ad_pct[idx - 1] / 100.0


# champion_id (canonical DDragon id) -> AsLockEntry. Exactly ONE entry (Jhin);
# no other live champion has an attack-speed-lock passive. Belveth is the
# deliberate NON-entry (see module docstring: same perlevel==0 signature, but
# her AS is uncapped so she must NOT be locked).
_AS_LOCK_OVERRIDES: dict[str, AsLockEntry] = {
    # Jhin Whisper: "Jhin's attack speed cannot increase except by leveling up"
    # and he gains bonus AD equal to (4% : 44% based on level, + 0.35% per 1%
    # critical strike chance, + 0.3% per 1% bonus attack speed) of his BASE
    # attack damage. Base AS is a flat 0.625 (attackspeedperlevel 0).
    "Jhin": AsLockEntry(
        locks_as=True,
        level_ad_pct=(4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0,
                      14.0, 16.0, 20.0, 24.0, 28.0, 32.0, 36.0, 40.0, 44.0),
        ad_per_bonus_as=0.30,
        ad_per_crit=0.35,
        note=(
            "Whisper (wiki raw 16.13.1): AS locked (base 0.625); bonus AD = "
            "(4%:44% by level + 0.35% per 1% crit + 0.3% per 1% bonus AS) of BASE AD."
        ),
    ),
}


def as_lock_entry(champion_id: str) -> AsLockEntry | None:
    """Return the AsLockEntry for ``champion_id`` or None (no AS-lock passive)."""
    return _AS_LOCK_OVERRIDES.get(champion_id)
