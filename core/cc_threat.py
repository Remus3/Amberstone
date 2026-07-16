# arch: deterministic hard-CC threat / tenacity nudge | section=core | frozen=no
"""Deterministic hard-CC threat -> tenacity counter-hint source.

PURPOSE
    Map an enemy champion roster to a 0..10 CC-load float with NO LLM /
    network / engine - purely a function of the enemy champion display
    names. Feeds the situational EnemyProfile.cc_score, which the C6
    tenacity counter-build hint fires on (at >= CC_CUT (5.0), i.e. 2+
    curated hard-CC champs). A sibling of core/heal_threat.py; lights up
    a criterion that was WIRED BUT DEAD for lack of an enemy-CC source
    (defensive_picks.compute_threat_profile carries no CC metric, and no
    live CC API exists).

WHY correct-by-construction (not a prediction)
    The enemy roster (championName per player) is a hard live fact from
    the Live Client scoreboard. The output is a pure set-membership read
    over a curated hard-CC roster: how many enemies bring reliable
    lockdown CC. A name not in the roster simply does not contribute, so
    the score can never be WRONG - only conservative (under-inclusion
    just fails to fire; over-inclusion is the only risk, so the roster is
    curated for RELIABLE hard CC).

CURATION (the opinionated part)
    _HARD_CC_CHAMPIONS is a hand-curated set of champions whose kit brings
    reliable hard CC (stun / root / suppress / taunt / charm / fear /
    reliable knockup) where rushing tenacity / QSS / cleanse is standard
    counterplay. Deliberately EXCLUDES conditional / skillshot-sweet-spot
    CC (Yasuo / Yone tornado knockup, Aatrox Q sweet spot, Vayne wall
    condemn) to avoid over-firing. Champion keys are normalized display
    names (lowercase, alphanumeric-only) so a Live Client display name and
    any punctuation / spacing variant match the same key.

SCORING
    cc_score = min(10.0, distinct matched hard-CC champs * _PER_CHAMP
    (2.5)). Flat per-champ (each curated champ = 1 unit), mirroring the
    heal_threat count philosophy. A graduated per-champ weight is a
    deliberate future refinement.

    Known simplification: tenacity does not shorten knockups / suppression
    / displacement, but the chip is a general "CC-heavy comp -> itemize
    tenacity / QSS / cleanse" advisory (matching how players itemize), so
    the roster spans all hard-CC types.

FAIL-SOFT
    Any bad / missing / non-list input -> 0.0 (no CC load), never raises.
"""
from __future__ import annotations

import re

# Curated hard-CC champions (normalized display-name keys). Each brings
# reliable lockdown CC where rushing tenacity / QSS is standard advice.
_HARD_CC_CHAMPIONS: frozenset[str] = frozenset({
    # Engage tanks / supports / junglers
    "leona", "nautilus", "amumu", "sejuani", "malphite", "rell", "alistar",
    "thresh", "blitzcrank", "braum", "rakan", "zac", "ornn", "rammus",
    "skarner", "maokai", "chogath", "sion", "gragas", "vi", "wukong",
    "monkeyking", "gnar", "jarvaniv", "nocturne", "warwick", "volibear",
    "nunu", "nunuwillump", "galio", "shen", "poppy", "taric",
    # Mages / control
    "morgana", "veigar", "lissandra", "malzahar", "annie", "neeko", "syndra",
    "ryze", "ahri", "zoe", "swain", "brand", "xerath", "lux", "cassiopeia",
    "vex",
    # Enchanters / utility
    "nami", "bard", "sona", "seraphine", "janna",
    # Marksmen with reliable hard CC
    "ashe", "varus", "jhin", "kalista",
    # Fighters / assassins with reliable hard-CC core
    "renekton", "riven", "irelia", "camille", "ekko", "pantheon", "jax",
    "kennen", "udyr", "xinzhao", "sett", "fiddlesticks",
})

# Flat per-champ CC weight and the 0..10 clamp. 2 matched champs -> 5.0 clears
# the C6 CC_CUT (5.0); 4+ saturate at 10.0.
_PER_CHAMP = 2.5
_MAX_CC = 10.0

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_champ(name: object) -> str:
    """Normalize a champion display name to a lowercase alphanumeric key.

    'Cho\\'Gath' -> 'chogath', 'Jarvan IV' -> 'jarvaniv'. Non-str / empty ->
    '' (never matches a curated key, so a junk roster entry is silently
    skipped). The curation can never produce a WRONG match.
    """
    if not isinstance(name, str):
        return ""
    return _NON_ALNUM.sub("", name.lower())


def _matched_hard_cc_champs(enemy_comp: object) -> list[str]:
    """Distinct enemy champs in the curated hard-CC roster (normalized keys).

    Order-preserving + de-duplicated on the normalized key (a roster never
    repeats a champ, but two junk entries normalizing alike are collapsed).
    Fail-soft: a non-list -> [].
    """
    if not isinstance(enemy_comp, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for c in enemy_comp:
        key = _norm_champ(c)
        if key and key in _HARD_CC_CHAMPIONS and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def compute_cc_score(enemy_comp) -> float:
    """Enemy CC load in 0..10: distinct matched curated hard-CC champs *
    _PER_CHAMP (2.5), clamped to _MAX_CC (10.0).

    The float the situational EnemyProfile.cc_score consumes (the C6 tenacity
    counter-hint fires at >= CC_CUT (5.0), i.e. 2+ hard-CC champs). Reuses the
    same curation the roster defines; fail-soft to 0.0 (bad / missing /
    non-list input -> no matches -> 0.0)."""
    return min(_MAX_CC, len(_matched_hard_cc_champs(enemy_comp)) * _PER_CHAMP)
