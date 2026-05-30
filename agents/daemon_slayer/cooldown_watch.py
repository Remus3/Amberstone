# arch: matchup cooldown-watch join (CC registry + ability cooldowns) | section=daemon_slayer | frozen=no
"""Matchup cooldown-watch - join enemy CC threat to ability base cooldown.

Competitor lift #5 (breadth scan item 213; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 5"). Pure presentation JOIN
over data RC already owns - NO new compute, NO schema lift, NO new external
dependency, NO ENGINE math change (no scoring output moves; this module is
read-only over two existing registries):

  * CC THREAT (which enemy ability is dangerous + how long it locks down):
    ``_PER_SPELL_CC_DURATIONS`` (``ability_dps.py``, unconditional first-
    order CC) + ``get_conditional_entries`` (``cc_conditional.py``,
    probability-gated CC). Both keyed on canonical DDragon id + Q/W/E/R.
  * ABILITY COOLDOWN (the "watch their hook - 16s" window): per-rank
    ``cooldown`` lists in the patch-pinned
    ``data/daemon_slayer/<patch>/champion_abilities.json`` (1270 cooldown
    entries at patch 16.11.1), keyed on the SAME champion id + Q/W/E/R.

The two halves were never joined. This module surfaces, per enemy champion,
the single HIGHEST-THREAT CC ability (longest max-rank hard-CC duration)
paired with its max-rank base cooldown - the actionable "after they whiff
<spell>, you have ~<cd>s" framing.

v1 honesty contract (per the DEPTH spec):
  * Cooldown is the BASE cooldown by rank, NOT haste-adjusted. RC has no
    live enemy ability haste in champ-select, so base-cd-by-rank is the
    honest number. (summoner + ult haste IS tracked live via
    ``core.summoner_cooldowns`` / ``dashboard/_state_cooldowns.py`` - that
    is a SEPARATE summoner+ult layer; this module is the Q/W/E base-ability
    layer, previously unconsumed.)
  * The headline cooldown is the MAX-RANK value (``cooldown[-1]``) paired
    with the MAX-RANK CC duration (``durations[-1]``) - the fully-leveled
    spell: longest lockdown + shortest (most frequent) cooldown = the
    honest worst-case threat to watch. The full per-rank cooldown tuple is
    also exposed so a consumer may show a range.
  * Mode-agnostic: ARAM tenacity scales how long CC locks the MODIFIED
    champion down, not the enemy's outgoing ability fact. The threat
    ranking + cooldown are intrinsic to the ability, so this module reads
    the raw registries directly and takes no mode parameter.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ability_dps import _PER_SPELL_CC_DURATIONS
from .cc_conditional import get_conditional_entries

_DATA_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "data"
    / "daemon_slayer"
)

# Canonical Q-W-E-R order used as the deterministic spell tiebreak.
_SPELL_RANK = {"Q": 0, "W": 1, "E": 2, "R": 3}


@dataclass(frozen=True)
class CooldownWatchCard:
    """One "watch their <spell>" card for a single enemy champion.

    ``cc_duration_s`` is the max-rank raw hard-CC seconds of the
    highest-threat ability (the lockdown if it lands, BEFORE the
    operator's own tenacity - this module never applies tenacity).
    ``cooldown_s`` is the max-rank base cooldown (the watch window);
    ``0.0`` when the abilities JSON has no cooldown for that slot.
    ``cooldown_by_rank`` is the full per-rank cooldown tuple (``()`` when
    missing). ``conditional`` is True when the CC is probability-gated
    (from ``cc_conditional``); ``probability`` is the operator-tunable
    midpoint for conditional entries, ``1.0`` for unconditional CC.
    ``cc_kind`` is the conditional registry's free-form tag (stun / root
    / fear / ...) or ``""`` for unconditional entries (the unconditional
    registry stores no kind).
    """

    champion: str
    spell_key: str
    spell_name: str
    cc_kind: str
    cc_duration_s: float
    cooldown_s: float
    cooldown_by_rank: Tuple[float, ...]
    conditional: bool
    probability: float


@dataclass(frozen=True)
class CooldownWatchResult:
    """Ranked cooldown-watch cards for an enemy roster.

    ``cards`` is sorted by ``cc_duration_s`` DESC (longest lockdown
    first), tiebroken by ``cooldown_s`` ASC (lower cd = more frequent
    threat = more dangerous), then champion name for determinism.
    """

    cards: Tuple[CooldownWatchCard, ...] = field(default_factory=tuple)


def _load_abilities() -> Dict[str, dict]:
    """Read patch + champion_abilities.json once; return the ``data`` map.

    Mirrors the ``cc_pressure._load_tenacity_map`` patch-pin pattern: read
    ``current.txt`` for the patch, then ``<patch>/champion_abilities.json``,
    return its ``data`` dict (champion id -> {slot: [form, ...]}). Fail-soft
    to ``{}`` on missing files / malformed JSON / unexpected shapes so the
    cooldown join degenerates to "no cooldown data" rather than raising.
    """
    try:
        patch = (_DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not patch:
        return {}
    abil_file = _DATA_DIR / patch / "champion_abilities.json"
    try:
        raw = json.loads(abil_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get("data") or {}
    return data if isinstance(data, dict) else {}


# Loaded once at import (read-only). Tests may monkeypatch this global to
# exercise the missing-data fail-soft path.
_ABILITIES: Dict[str, dict] = _load_abilities()


def _spell_cooldown(
    champion: str, spell_key: str, form_index: Optional[int]
) -> Tuple[str, Tuple[float, ...]]:
    """Return (spell_name, per-rank cooldown tuple) for a champion+slot.

    Reads the patch-pinned abilities JSON via the module-level
    ``_ABILITIES`` global (so a test monkeypatch is honoured). Picks the
    form by ``form_index`` when in range, else form 0. Returns
    ``("", ())`` when the slot / cooldown is absent or malformed; returns
    the resolved name with ``()`` when the name is present but the
    cooldown list is missing.
    """
    forms = (_ABILITIES.get(champion) or {}).get(spell_key)
    if not isinstance(forms, list) or not forms:
        return "", ()
    idx = (
        form_index
        if isinstance(form_index, int) and 0 <= form_index < len(forms)
        else 0
    )
    form = forms[idx]
    if not isinstance(form, dict):
        return "", ()
    name = str(form.get("name") or "")
    cd_raw = form.get("cooldown")
    if not isinstance(cd_raw, list) or not cd_raw:
        return name, ()
    try:
        cd = tuple(float(x) for x in cd_raw)
    except (TypeError, ValueError):
        return name, ()
    return name, cd


# Candidate tuple shape: (cc_duration, conditional, spell_key, cc_kind,
# probability, form_index). Sorting prefers longest duration, then
# unconditional over conditional on ties, then canonical Q-W-E-R order.
_Candidate = Tuple[float, bool, str, str, float, Optional[int]]


def _candidates(champion: str) -> List[_Candidate]:
    out: List[_Candidate] = []
    uncond = _PER_SPELL_CC_DURATIONS.get(champion) or {}
    for spell_key, durs in uncond.items():
        if not durs:
            continue
        out.append((float(durs[-1]), False, spell_key, "", 1.0, None))
    for entry in get_conditional_entries(champion):
        if not entry.durations_s:
            continue
        out.append(
            (
                float(entry.durations_s[-1]),
                True,
                entry.spell,
                entry.cc_kind,
                float(entry.probability),
                entry.form_index,
            )
        )
    return out


def _headline_card(champion: str) -> Optional[CooldownWatchCard]:
    """Build the single highest-threat CC card for one champion.

    Returns ``None`` when the champion has no registered first-order CC
    (neither unconditional nor conditional). When CC exists but the
    abilities JSON lacks the cooldown, the card is still emitted with
    ``cooldown_s=0.0`` + empty ``cooldown_by_rank`` (the threat is real
    even if the cooldown number is unavailable).
    """
    cands = _candidates(champion)
    if not cands:
        return None
    # Longest duration first; unconditional preferred on a duration tie;
    # then canonical Q-W-E-R for full determinism.
    best = min(
        cands,
        key=lambda c: (-c[0], c[1], _SPELL_RANK.get(c[2], 9)),
    )
    cc_dur, conditional, spell_key, cc_kind, prob, form_index = best
    spell_name, cd_by_rank = _spell_cooldown(champion, spell_key, form_index)
    cooldown_s = cd_by_rank[-1] if cd_by_rank else 0.0
    return CooldownWatchCard(
        champion=champion,
        spell_key=spell_key,
        spell_name=spell_name,
        cc_kind=cc_kind,
        cc_duration_s=cc_dur,
        cooldown_s=cooldown_s,
        cooldown_by_rank=cd_by_rank,
        conditional=conditional,
        probability=prob,
    )


def compute_cooldown_watch(
    roster: List[str], top_n: int = 5
) -> CooldownWatchResult:
    """Ranked cooldown-watch cards for an enemy roster.

    For each DISTINCT champion in ``roster`` (first occurrence wins;
    blank / None entries skipped), emits the single highest-threat CC
    ability paired with its max-rank base cooldown. Champions with no
    registered first-order CC are skipped. Cards are sorted by CC
    duration DESC, then cooldown ASC, then champion name, and truncated
    to ``top_n`` (negative / None ``top_n`` returns all).
    """
    seen: set[str] = set()
    cards: List[CooldownWatchCard] = []
    for raw in roster or []:
        if not raw:
            continue
        champ = str(raw).strip()
        if not champ or champ in seen:
            continue
        seen.add(champ)
        card = _headline_card(champ)
        if card is not None:
            cards.append(card)
    cards.sort(key=lambda c: (-c.cc_duration_s, c.cooldown_s, c.champion))
    if top_n is not None and top_n >= 0:
        cards = cards[:top_n]
    return CooldownWatchResult(cards=tuple(cards))


__all__ = [
    "CooldownWatchCard",
    "CooldownWatchResult",
    "compute_cooldown_watch",
]
