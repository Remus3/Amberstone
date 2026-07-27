"""R197 - SCALING Heal/Shield Power grants, keyed by item id (mana-regen axis).

The SCALING-CLAUSE lane of the flat-stat ``_hsp_amp.sum_wielder_hsp_pct``. That
helper sums ``heal_shield_amp_pct`` out of the curated ``enchanter_items.json``,
and that curated field stores ONLY the FLAT PRINTED Heal-and-Shield-Power stat.
An item that grants ADDITIONAL HSP through a scaling clause earns ZERO there,
and the gap is structural rather than an omission: the clause lives in the
Meraki ``passives[].effects`` PROSE field (and in the DDragon ``description``
passive body), never in a stat key, and Meraki's top-level ``stats`` is ``None``
for every item in this class - so a stat-key scan finds nothing to fold. Dawncore
prints 16% HSP, the curated field stores exactly 0.16, and its First Light
clause is unmodelled. That is the exact structural gap the sibling
``_rune_hsp_amp`` registry fills on the rune axis.

WHAT IS ARMED - the MANA-REGEN axis (First Light), verbatim from the shipped
16.14.1 snapshots. Each mode mirror carries its OWN per-step magnitude AND its
own printed base mana regen (R161 doctrine B: a mirror credits its own DDragon
stat line, never the SR twin's):

  * 6621   Dawncore (SR)     - DDragon: "Gain 2% Heal and Shield Power and 10
    Ability Power per 100% Base Mana Regen." Printed stat line: 100% Base Mana
    Regen. Meraki First Light: "Gain 2% heal and shield power and 10 ability
    power for every additional 100% base mana regeneration."
  * 226621 Dawncore (Arena)  - DDragon: "Gain 3% Heal and Shield Power ... per
    100% Base Mana Regen." Printed stat line: 200% Base Mana Regen.
  * 326621 Dawncore (ARAM)   - DDragon: "Gain 2% Heal and Shield Power ... per
    100% Base Mana Regen." Printed stat line: 150% Base Mana Regen.

Magnitudes are stored as FRACTIONS (2% -> 0.02) so this lane is DIRECTLY
ADDITIVE with the flat item sum and the rune sum, per the real-LoL additive HSP
model and the "(1 + hsp_pct)" convention at ``_hsp_amp.py:27-30``. The AP half of
First Light ("and 10 Ability Power") is deliberately NOT modelled here - this is
an HSP lane, and the AP axis has its own consumers.

THE SHIPPED READING OF "for every ADDITIONAL 100%" - STATED AS AN ASSUMPTION,
not a measurement. A champion's innate base mana regeneration is 100%; items
grant regen ON TOP of that, so item-granted regen IS the "additional" amount.
Two consequences are asserted by ``test_scaling_hsp_r197``:
  1. The item's OWN printed base mana regen COUNTS toward its own threshold, so
     Dawncore alone earns one step rather than zero.
  2. The champion's innate 100% is NOT added in, so Dawncore alone earns one
     step rather than two.
Steps are DISCRETE - ``floor(total_item_base_mana_regen_pct / 100)`` - following
the printed "for every additional 100%" wording. A sub-step remainder earns
nothing (the ARAM mirror's 150% floors to one step). Floor is also the
conservative direction: a continuous reading would be an upper bound, so if a
live probe ever shows continuous scaling this constant changes and the registry
does not.

WHY THE REGEN TOTAL IS PARSED, NOT ASSUMED. Base mana regen is a PRINTED-TEXT
stat: DDragon's structured ``stats`` object carries no key for it (6621's
``stats`` is ``{"FlatMagicDamageMod": 45}`` and nothing else), so the only
machine-readable source is the ``<stats>`` block of the ``description`` string.
The parse is SCOPED TO THAT BLOCK on purpose: Dawncore's raw description matches
"% Base Mana Regen" TWICE - once on the printed stat line and once inside the
First Light clause itself - and a whole-description regex would read the Arena
mirror as 300% instead of 200%.

KNOWN-EXCLUDED ROWS (recorded so a future pass cannot re-file them as
uncovered, each pinned by a test). Three separate reason classes:

  * HSP CONSUMERS, not granters. 4011 / 124011 / 664011 Sword of Blossoming Dawn
    ("Gain 1.2% bonus attack speed per 1% heal and shield power") and 447123
    Puppeteer ("gain 50% (+ 150% of your heal and shield power) bonus attack
    speed"). Byte-similar prose, OPPOSITE direction - they READ the stat and pay
    out attack speed. This is exactly why the registry is keyed BY ID and never
    by name or substring: a name fold would invert the term's sign of meaning.
  * LIVE TARGET STATE. 443063 Eleisa's Miracle ("Gain 2.5% heal and shield power
    per 100 current health you are missing, up to 60% at 2400 missing") scales on
    MISSING CURRENT HEALTH, which is not an inventory-derivable quantity, and the
    DS conditional-target-state arc is operator-CLOSED.
  * BONUS MANA - REFUTED AT THIS SEAM. 2526 / 222526 / 322526 Whispering Circlet
    and 2530 / 222530 / 322530 Diadem of Songs ("Grants heal and shield power
    equal to 0.5% bonus mana"). The magnitude is real and the ids are correct,
    but the QUANTITY is unreachable here. ``_item_mana_health`` already settled
    the doctrine for the identical quantity: its Awe lane takes ``bonus_mana`` as
    a CALLER-SUPPLIED argument computed from the RESOLVED stat block, because
    item-printed ``FlatMPPoolMod`` is only a floor - it omits Tear-family stacked
    mana (Archangel's / Winter's Approach), the Manaflow Band rune, and
    Whispering Circlet's OWN up-to-360 Manaflow charges (which also gate its
    transformation into Diadem). ``sum_wielder_hsp_pct`` receives ONLY item ids
    and no resolved stats, so shipping a number here would be a fabrication, not
    an approximation. Arming this axis needs a signature lift that passes
    ``bonus_mana`` in - a separate, operator-gated decision.
  * UNRENDERED TEMPLATE. 443064 Talisman Of Ascension carries an EMPTY
    ``<stats></stats>`` block followed by a "?"-placeholder stat list that
    includes "?% Heal and Shield Power". It is a rendering artifact, not a
    clause - there is no magnitude to read and no Meraki HSP prose at all.

FAIL-SOFT, mirroring ``_hsp_amp`` / ``_rune_hsp_amp``: an empty / None /
non-iterable inventory, unknown ids, a missing snapshot, or any load failure
returns 0.0. The seam caller gates on a DEFAULT-OFF flag, so a 0.0 return keeps
its output byte-identical.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# One "additional 100% base mana regeneration" step, in printed percent units.
MANA_REGEN_STEP_PCT: float = 100.0

# id -> HSP FRACTION earned per completed MANA_REGEN_STEP_PCT step.
# Sources are the 16.14.1 DDragon ``description`` clause and the Meraki First
# Light prose, both quoted in the module docstring. Never normalize a mirror by
# stripping its prefix: the three magnitudes genuinely differ.
SCALING_HSP_PER_MANA_REGEN_STEP: dict[str, float] = {
    "6621": 0.02,    # Dawncore SR    - "Gain 2% Heal and Shield Power ... per 100% Base Mana Regen"
    "226621": 0.03,  # Dawncore Arena - "Gain 3% Heal and Shield Power ... per 100% Base Mana Regen"
    "326621": 0.02,  # Dawncore ARAM  - "Gain 2% Heal and Shield Power ... per 100% Base Mana Regen"
}

_CONSUMER_REASON = (
    "HSP CONSUMER, not a granter - reads the wielder's heal and shield power "
    "and pays out bonus attack speed. Opposite direction; a name or substring "
    "fold would wrongly arm it."
)
_BONUS_MANA_REASON = (
    "REFUTED at this seam - grants HSP equal to 0.5% bonus mana, but bonus mana "
    "is not derivable from an item-id list. Item-printed FlatMPPoolMod is only a "
    "floor (it omits Tear-family stacked mana, the Manaflow Band rune, and this "
    "item's own up-to-360 Manaflow charges). Per the _item_mana_health Awe "
    "doctrine the caller must supply bonus mana from the resolved stat block; "
    "sum_wielder_hsp_pct receives no stats, so any number here would be invented."
)

# id -> WHY it is deliberately not armed. Registered, not merely omitted, so a
# future coverage pass cannot re-file these as uncovered.
KNOWN_EXCLUDED_SCALING_HSP_IDS: dict[str, str] = {
    "4011": _CONSUMER_REASON,
    "124011": _CONSUMER_REASON,
    "664011": _CONSUMER_REASON,
    "447123": _CONSUMER_REASON,
    "443063": (
        "LIVE TARGET STATE - scales on MISSING CURRENT HEALTH (2.5% per 100 "
        "missing, capped 60% at 2400 missing). Not an inventory-derivable "
        "quantity, and the DS conditional-target-state arc is operator-CLOSED."
    ),
    "2526": _BONUS_MANA_REASON,
    "222526": _BONUS_MANA_REASON,
    "322526": _BONUS_MANA_REASON,
    "2530": _BONUS_MANA_REASON,
    "222530": _BONUS_MANA_REASON,
    "322530": _BONUS_MANA_REASON,
    "443064": (
        "UNRENDERED TEMPLATE - an empty <stats></stats> block followed by a "
        "'?'-placeholder stat list that includes '?% Heal and Shield Power'. A "
        "rendering artifact with no magnitude and no Meraki HSP prose."
    ),
}

# Every id in the scaling-HSP class: armed plus deliberately excluded. The
# completeness test re-derives the class from the shipped prose and asserts this
# set accounts for all of it.
SCALING_HSP_CLASS_IDS: frozenset[str] = frozenset(
    set(SCALING_HSP_PER_MANA_REGEN_STEP) | set(KNOWN_EXCLUDED_SCALING_HSP_IDS)
)

_TAG_RE = re.compile(r"<[^>]+>")
_STATS_BLOCK_RE = re.compile(r"<stats>(.*?)</stats>", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_BASE_MANA_REGEN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*Base Mana Regen", re.IGNORECASE
)

_regen_table_cache: dict[str, dict[str, float]] = {}


def _resolve_patch(patch: Optional[str]) -> Optional[str]:
    if patch:
        return patch
    try:
        text = (_DEFAULT_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return text or None


def load_base_mana_regen_pct_table(
    patch: Optional[str] = None,
) -> dict[str, float]:
    """Per-item PRINTED base mana regen percent, parsed from DDragon (cached).

    Scoped to the ``<stats>`` block of ``description`` because DDragon exposes no
    structured key for this stat AND because Dawncore's passive clause repeats
    the phrase - a whole-description parse double-counts it. Items with no
    printed regen line are absent from the table rather than stored as 0.0, so a
    caller's ``.get(iid, 0.0)`` and a membership test agree.

    Returns ``{}`` on any load or parse failure - the caller is fail-soft.
    """
    resolved = _resolve_patch(patch)
    if resolved is None:
        return {}
    cached = _regen_table_cache.get(resolved)
    if cached is not None:
        return cached
    table: dict[str, float] = {}
    try:
        path = _DEFAULT_DATA_ROOT / resolved / "items.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(entries, dict):
            return {}
        for iid, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            block = _STATS_BLOCK_RE.search(entry.get("description") or "")
            if block is None:
                continue
            printed = _WS_RE.sub(" ", _TAG_RE.sub(" ", block.group(1)))
            found = _BASE_MANA_REGEN_RE.search(printed)
            if found is None:
                continue
            table[str(iid)] = float(found.group(1))
    except Exception:
        return {}
    _regen_table_cache[resolved] = table
    return table


def sum_scaling_hsp_pct(
    item_ids: Optional[Iterable[str | int]],
    patch: Optional[str] = None,
) -> float:
    """ADDITIONAL HSP fraction earned from scaling clauses (fail-soft).

    Returns the amount the flat ``heal_shield_amp_pct`` sum is MISSING, not the
    total - the caller adds the two. Only the mana-regen axis is armed; every
    other member of the class is registered in
    ``KNOWN_EXCLUDED_SCALING_HSP_IDS`` with its reason.

    An id is credited at most once and only the HIGHEST per-step rate among the
    equipped armed items applies. First Light is a UNIQUE passive over a SHARED
    regen pool, and the mode mirrors are mutually exclusive in a real build, so
    a synthetic inventory listing two must not double-credit that one pool - the
    ``_item_mana_health`` Awe rationale.

    Returns 0.0 on an empty / None / non-iterable inventory, on an inventory
    with no armed item, on a sub-one-step regen total, or on any load failure.
    """
    try:
        if not item_ids:
            return 0.0
        unique: list[str] = []
        seen: set[str] = set()
        for raw in item_ids:
            if raw is None:
                continue
            key = str(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        armed = [k for k in unique if k in SCALING_HSP_PER_MANA_REGEN_STEP]
        if not armed:
            return 0.0
        table = load_base_mana_regen_pct_table(patch)
        if not table:
            return 0.0
        total_regen = sum(table.get(k, 0.0) for k in unique)
        steps = math.floor(total_regen / MANA_REGEN_STEP_PCT)
        if steps <= 0:
            return 0.0
        rate = max(SCALING_HSP_PER_MANA_REGEN_STEP[k] for k in armed)
        return float(steps) * rate
    except Exception:
        return 0.0
