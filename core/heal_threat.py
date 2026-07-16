# arch: deterministic heal-threat / anti-heal nudge | section=core | frozen=no
"""Deterministic heal-threat (anti-heal / Grievous Wounds) callout.

PURPOSE
    An aggregator-A-overlay-style "the enemy is stacking sustain and your team
    has no anti-heal" nudge, computed with NO LLM / network / engine -
    purely a function of (enemy champion roster, enemy item ids, ally
    item ids). Drives the live coach's Haiku call toward zero (the
    PRIMARY north-star): a correct-by-construction directive the coach
    used to spend prose on.

WHY correct-by-construction (not a prediction)
    Every input is a hard live fact from the Live Client scoreboard:
      - the enemy roster (championName per player),
      - the items each player owns (allPlayers[].items[].itemID - public
        scoreboard data, unlike gold which is activePlayer-only).
    The output is a pure set-membership read: does the enemy field a
    curated heavy-sustain champion (or >=2 sustain items), AND does NO
    ally own a Grievous-Wounds item. No outcome is predicted; the nudge
    states a fact ("they heal, you have no anti-heal") plus the standard
    counter. Omitting any team-side claim it cannot back means the
    callout can never be backwards.

CURATION (the opinionated part)
    _HEAVY_SUSTAIN_CHAMPIONS is a hand-curated set of champions where
    rushing anti-heal is standard advice (heavy ability / passive self-
    or team-sustain). _HEAL_ITEM_IDS is the completed lifesteal /
    omnivamp / heal-amp item set. _GRIEVOUS_ITEM_IDS is every item that
    APPLIES Grievous Wounds (active, on-hit, or on-damage). Item ids are
    the base DDragon ids the Live Client reports (NOT the "22"-prefixed
    catalog aliases - see reference_items_index_alias_ids). All three
    sets are verified against data/daemon_slayer/<patch>/items.json at
    author time (patch 16.11.1).

FAIL-SOFT
    Any bad / missing / non-list input -> None (no callout), never raises.
"""
from __future__ import annotations

import re
from typing import Optional

# Modes where the curated SR/ARAM anti-heal item + champion sets apply.
# Arena (CHERRY) has its own item pool + augment economy, and TFT has no
# Grievous-Wounds analog, so the nudge is SR/ARAM only (client/game are
# SR-equivalent for the live coach).
_HEAL_THREAT_MODES: frozenset[str] = frozenset({"sr", "aram", "client", "game"})

# Curated heavy-sustain champions (display names). Each is a champion where
# rushing Grievous Wounds is standard advice because the bulk of their
# durability is ability / passive HEALING (not shields or pure tankiness).
# Stored normalized (lowercase, alphanumeric-only) so a Live Client display
# name ("Dr. Mundo") and any punctuation/spacing variant match the same key.
_HEAVY_SUSTAIN_CHAMPIONS: frozenset[str] = frozenset({
    "aatrox",
    "briar",
    "drmundo",
    "fiddlesticks",
    "illaoi",
    "kayn",
    "maokai",
    "mordekaiser",
    "nilah",
    "renekton",
    "sett",
    "soraka",
    "swain",
    "sylas",
    "trundle",
    "tryndamere",
    "vladimir",
    "volibear",
    "warwick",
    "yuumi",
    "zac",
})

# Completed lifesteal / omnivamp / heal-amp items (base DDragon ids as the
# Live Client reports them). A SECONDARY signal: two or more on the enemy
# team flags a sustain-leaning build even without a curated champion.
#   3072 Bloodthirster       3074 Ravenous Hydra     6333 Death's Dance
#   6673 Immortal Shieldbow  4633 Riftmaker          6610 Sundered Sky
#   3065 Spirit Visage (heal AMP)   2501 / 447111 Overlord's Bloodmail
_HEAL_ITEM_IDS: frozenset[str] = frozenset({
    "3072", "3074", "6333", "6673", "4633", "6610", "3065", "2501", "447111",
})

# Every item that APPLIES Grievous Wounds (the anti-heal counter). Ownership
# of ANY one of these on the ally team suppresses the nudge.
#   3123 Executioner's Calling  3916 Oblivion Orb     3165 Morellonomicon
#   3033 Mortal Reminder        6609 Chempunk Chainsword
#   3075 Thornmail (on-hit)     3076 Bramble Vest (on-hit)
#   3011 Chemtech Putrifier (on-damage)
_GRIEVOUS_ITEM_IDS: frozenset[str] = frozenset({
    "3123", "3916", "3165", "3033", "6609", "3075", "3076", "3011",
})

# Fire when at least this many curated sustain champions are present, OR at
# least _HEAL_ITEM_FIRE_N sustain items. One heavy-sustain champion (a lone
# Soraka / Aatrox / Vladimir) already warrants anti-heal, so the champion bar
# is 1; a lone sustain item is a weaker signal, so the item bar is 2.
_SUSTAIN_CHAMP_FIRE_N = 1
_HEAL_ITEM_FIRE_N = 2

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_mode(mode: object) -> str:
    """Lowercase a mode string; non-str -> '' (fail-soft)."""
    if not isinstance(mode, str):
        return ""
    return mode.strip().lower()


def _norm_champ(name: object) -> str:
    """Normalize a champion display name to a lowercase alphanumeric key.

    'Dr. Mundo' -> 'drmundo', 'Aurelion Sol' -> 'aurelionsol'. Non-str /
    empty -> '' (never matches a curated key, so a junk roster entry is
    silently skipped). The curation can never produce a WRONG match - a
    name not in the set simply does not contribute to the threat count.
    """
    if not isinstance(name, str):
        return ""
    return _NON_ALNUM.sub("", name.lower())


def _id_strs(ids: object) -> list[str]:
    """Coerce an item-id list to non-empty string ids; bad input -> [].

    Accepts ints or strings (the Live Client itemID can arrive either way)
    and drops bools / None / empties. Fail-soft: a non-list -> []."""
    if not isinstance(ids, list):
        return []
    out: list[str] = []
    for i in ids:
        if isinstance(i, bool) or i is None:
            continue
        if isinstance(i, (int, float)):
            out.append(str(int(i)))
        elif isinstance(i, str) and i.strip():
            out.append(i.strip())
    return out


def _matched_sustain_champs(enemy_comp: object) -> list[str]:
    """Return the original display names of enemy champs in the curated set.

    Order-preserving + de-duplicated on the normalized key (a roster never
    repeats a champ, but two junk entries normalizing alike are collapsed).
    """
    if not isinstance(enemy_comp, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for c in enemy_comp:
        key = _norm_champ(c)
        if key and key in _HEAVY_SUSTAIN_CHAMPIONS and key not in seen:
            seen.add(key)
            out.append(c.strip() if isinstance(c, str) else str(c))
    return out


def _count_in_set(ids: object, id_set: frozenset[str]) -> int:
    """Count distinct item ids from ``ids`` that are in ``id_set``."""
    return len({i for i in _id_strs(ids) if i in id_set})


def _reasons(sustain_champs: list[str], heal_item_n: int) -> str:
    """Compose the short reason clause for the callout line.

    Prefers naming up to two curated champions (the high-signal cause),
    falling back to an item count. '+N' marks additional sustain champs
    beyond the two shown so the operator knows the threat is broader.
    """
    if sustain_champs:
        shown = sustain_champs[:2]
        clause = ", ".join(shown)
        extra = len(sustain_champs) - len(shown)
        if extra > 0:
            clause += f" +{extra}"
        return clause
    n = heal_item_n
    return f"{n} heal items" if n != 1 else "1 heal item"


def heal_threat_callout(
    enemy_comp: object,
    enemy_item_ids: object,
    ally_item_ids: object,
    mode: object = "sr",
) -> Optional[dict]:
    """Return an anti-heal nudge callout, or None when no nudge is warranted.

    Correct-by-construction + fail-soft. Fires only when BOTH hold:
      1. the enemy fields >= _SUSTAIN_CHAMP_FIRE_N curated heavy-sustain
         champions, OR >= _HEAL_ITEM_FIRE_N sustain items, AND
      2. NO ally owns a Grievous-Wounds item.
    Otherwise returns None (a present ally anti-heal item, no enemy sustain,
    or an off-mode/garbage input all suppress the nudge).

    Args:
        enemy_comp: list of enemy champion display names (lc.enemy_team).
        enemy_item_ids: list of item ids owned across the enemy team.
        ally_item_ids: list of item ids owned across the ally team (incl.
            the operator). Only this list suppresses the nudge.
        mode: dashboard mode_key (sr/aram/client/game fire; others -> None).

    Returns:
        ``{tag, line, eta_s, kind}`` with kind == 'heal_threat' and
        eta_s == None (a standing advisory, not a timed event, so the
        callouts panel renders the line with no ETA chip), or None.
    """
    if _norm_mode(mode) not in _HEAL_THREAT_MODES:
        return None
    # An ally Grievous-Wounds item already answers the threat -> no nudge.
    if _count_in_set(ally_item_ids, _GRIEVOUS_ITEM_IDS) > 0:
        return None

    sustain_champs = _matched_sustain_champs(enemy_comp)
    heal_item_n = _count_in_set(enemy_item_ids, _HEAL_ITEM_IDS)
    fire = (
        len(sustain_champs) >= _SUSTAIN_CHAMP_FIRE_N
        or heal_item_n >= _HEAL_ITEM_FIRE_N
    )
    if not fire:
        return None

    return {
        "tag": "heal_threat",
        "line": f"Enemy sustain ({_reasons(sustain_champs, heal_item_n)}) - "
                f"no anti-heal, buy Grievous",
        "eta_s": None,
        "kind": "heal_threat",
    }


def count_heal_sources(enemy_comp, enemy_item_ids) -> int:
    """Count enemy heal SOURCES: matched curated heavy-sustain champions +
    distinct enemy heal items.

    The int the situational ``EnemyProfile.heal_sources`` consumes (the C2
    antiheal counter-hint fires at ``>= HEAL_THRESHOLD``). Reuses the same
    curation the standing callout uses; fail-soft to 0 (the private helpers
    coerce bad / missing input)."""
    return len(_matched_sustain_champs(enemy_comp)) + _count_in_set(
        enemy_item_ids, _HEAL_ITEM_IDS)


def ally_has_antiheal(ally_item_ids) -> bool:
    """True when any ally item applies Grievous Wounds - populates the
    situational ``AllyState.has_antiheal`` de-dup so the antiheal hint is
    suppressed when an ally already owns the counter. Fail-soft False."""
    return _count_in_set(ally_item_ids, _GRIEVOUS_ITEM_IDS) > 0
