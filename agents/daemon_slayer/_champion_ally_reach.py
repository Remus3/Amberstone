"""ENGINE 1.220.0 (Term A, 2026-07-18) - champion-side ALLY-REACH gate.

Answers ONE binary question: does this champion's kit play around allies at all?
If it does, an item that shields or heals teammates lands on someone, so the
``score_by="team_blended"`` seam in ``ehp.py`` may price that item's ally grant
for them. If it does not, the grant reaches nobody and the seam must stay inert.

The signal is the ``affects`` field on each ability form in
``champion_abilities.json``. Measured at 16.14.1: 70 forms across 40 champions
carry a strict ``allies`` token.

WHY BOOLEAN, NOT A PER-CHAMPION MAGNITUDE: the item's shield is the same size
whoever buys it. A per-champion multiplier would be a second invented constant
with no data behind it, and Term A deliberately ships with ZERO new constants
(it reuses ``_passive_ally_grant_overrides._ALLY_SHIELD_HEAL_PROB``).

WHY NOT ``compute_allyamp(champion).allyamp_score > 0`` - a tempting shortcut
that is WRONG two ways:
  1. ``compute_allyamp`` / ``compute_cc_output`` / ``compute_mobility`` /
     ``compute_objdamage`` all take ``(champion, mode)`` and NO ``item_ids``, so
     ``score(build + item) - score(build)`` is identically zero for them. They
     can never be an item-side term - only a champion-side gate.
  2. Even as a gate it silently drops K'Sante, whose E "can also be cast on
     allies ... they receive the shield as well" is a real ally shield that the
     allyamp registry simply has not registered (``allyamp_score`` 0.0). An
     unregistered kit is not an absent kit. Read ``affects`` directly.

``affects`` is FREE TEXT, not an enum, and the file is dirty. Measured hazards
at 16.14.1, all handled by ``_affects_tokens``: two delimiters mixed
(``"Self, Enemies"`` and ``"Enemies / Self"``), non-canonical order
(``"Enemies, Allies"`` vs ``"Allies, Enemies"``), case drift (``"self"``),
three misspellings of "Enemies" (``"Ememies"``), and both ``None`` and the
string ``"None"``.

Documented EXCLUSIONS (strict ``allies`` hits deliberately gated OFF - these are
parser false positives where the token does not mean "I confer something on a
teammate"):
  - Ornn P Living Forge: upgrades allies' ITEMS into Masterwork variants. An
    economy effect, not proximity and not durability - buying Locket does not
    interact with it. ``_passive_ally_grant_overrides`` already flags this exact
    ability as "a false-positive scan hit" for the sibling champion-side
    registry; this module makes the same call for the same reason.
  - Sejuani E Permafrost: "Allies" here means nearby allied melee champions'
    basic attacks apply HER Frost stacks. The direction of benefit is reversed -
    allies feed Sejuani, she grants them nothing.

Documented positive OVERRIDES (``_ALLY_REACH_INCLUDED``, A-21 / RM-90 S2) cover
the reverse failure - champions the ``affects`` field cannot express. See the
per-champion rationale on that constant.

The two THIN inclusions, kept deliberately and flagged for review: Nunu P (grants
a nearby ally attack speed / move speed) and Rell E (tethers move speed to one
ally). Neither grant is durability, so neither is an EHP grant in its own right -
but both kits are proximity-POSITIVE by construction (Nunu's passive rewards
standing beside a teammate, Rell's tether requires it), which is exactly the
question this gate asks. An ally-shielding item does reach someone on both.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Path convention mirrors ``hps.py`` / ``data_loader.py``: repo root resolved
# from this file, patch resolved from the ``current.txt`` pointer.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Strict ally-facing token. Anything else ("allied turrets", "oathsworn ally",
# "rakan") is deliberately NOT admitted: the champions carrying those are
# marksmen who never route to tank, so admitting them widens the parser and
# buys nothing.
_ALLY_TOKEN = "allies"

# Strict ``allies`` hits that are parser false positives. See the module
# docstring for the reason class on each.
_ALLY_REACH_EXCLUDED = frozenset({"Ornn", "Sejuani"})

# A-21 / RM-90 Slice S2 (2026-07-25) - the POSITIVE twin of the exclusion set.
# Keys are DDragon ids, machine-checked against ``champion_abilities.json`` by
# ``tests/test_champion_ally_reach_overrides.py`` so a rename cannot silently
# no-op. Every entry is individually justified; the set is NOT certified by
# count. Each is Support-role and tank-routed, i.e. inside the RM-90 cohort
# whose 28 champions collapsed onto one shipped build order.
#
#   - Leona. The ONE textual case, and the reason a prose scan is tempting.
#     Her Sunlight passive reads "Allied champions' damaging attacks and
#     abilities against a marked target will consume the mark to deal ... bonus
#     magic damage" - a genuine ally-facing grant. ``affects`` reports
#     ``"Enemies"`` for it and is not wrong: the MARK sits on the enemy. The
#     beneficiary is the ally, which the field simply cannot express. Same class
#     as the K'Sante case the docstring above names, one layer deeper.
#   - Blitzcrank / Nautilus / Poppy. NO ally token and NO ally-facing prose -
#     admitted on the THIN, proximity-POSITIVE basis the docstring already
#     applies to Nunu P and Rell E: they are melee engage frontliners played
#     between the enemy and their own carries, so an ally-shielding item lands
#     on someone. That is the only question this gate asks. Flagged for review
#     alongside the other two thin inclusions.
#
# DELIBERATELY NOT a prose-token widening of ``_affects_tokens``: scanning
# ``effects_descriptions`` for allied/allies/ally admits 27 further champions at
# 16.14.1 (Akshan, Annie, Fiora, Jhin, Kha'Zix, ...), almost all of them allied
# TURRET / MINION / wave references. A four-name override is smaller, auditable,
# and reversible; a parser change is none of those.
_ALLY_REACH_INCLUDED = frozenset({
    "Blitzcrank", "Leona", "Nautilus", "Poppy",
})


def _affects_tokens(raw: object) -> list[str]:
    """Split a free-text ``affects`` value into normalized tokens.

    Handles both delimiters (``,`` and ``/``), arbitrary order, case drift, and
    a ``None`` / ``"None"`` value. Never raises.
    """
    if not raw:
        return []
    text = str(raw)
    if text.strip().lower() == "none":
        return []
    return [
        tok.strip().lower()
        for tok in text.replace("/", ",").split(",")
        if tok.strip()
    ]


def _norm_key(champion: object) -> str:
    """Fold a champion identifier to a comparable key.

    The engine's own callers pass the DDragon id (``TahmKench`` / ``KSante``),
    which is byte-identical to the abilities-file key - verified at 16.14.1,
    where ``set(abilities) - set(snapshot.champions)`` is empty. This fold
    additionally absorbs a DISPLAY name (``"Tahm Kench"`` / ``"K'Sante"``) so a
    caller that hands over a live-game name cannot silently miss - the
    name-vs-id split that has bitten the Live Client readers before.
    """
    return "".join(c for c in str(champion or "") if c.isalnum()).lower()


@lru_cache(maxsize=1)
def _ally_reach_index(patch: Optional[str] = None) -> frozenset[str]:
    """Build the folded-key set of champions whose kit reaches allies.

    Fail-soft: any load or parse failure yields an EMPTY set, which makes every
    gate call return False and the Term A seam inert - byte-identical, never a
    crash. Cached; the underlying file is patch-static.
    """
    try:
        resolved = patch
        if resolved is None:
            resolved = (_DEFAULT_DATA_ROOT / "current.txt").read_text(
                encoding="utf-8"
            ).strip()
        if not resolved:
            return frozenset()
        raw = json.loads(
            (_DEFAULT_DATA_ROOT / resolved / "champion_abilities.json")
            .read_text(encoding="utf-8")
        )
    except Exception:
        return frozenset()
    body = raw.get("data", raw) if isinstance(raw, dict) else {}
    if not isinstance(body, dict):
        return frozenset()
    reached: set[str] = set()
    for champion_id, spells in body.items():
        if champion_id in _ALLY_REACH_EXCLUDED or not isinstance(spells, dict):
            continue
        for key in ("P", "Q", "W", "E", "R"):
            forms = spells.get(key)
            if not isinstance(forms, list):
                continue
            for form in forms:
                if not isinstance(form, dict):
                    continue
                if _ALLY_TOKEN in _affects_tokens(form.get("affects")):
                    reached.add(_norm_key(champion_id))
                    break
            if _norm_key(champion_id) in reached:
                break
    # Slice S2: fold in the positive overrides. Applied AFTER the derivation and
    # only on a successful load, so the documented fail-soft contract holds - a
    # missing / malformed abilities file still yields an EMPTY set and leaves the
    # whole team_blended seam inert rather than partially live off a literal
    # list. The exclusion set still wins (the two sets are asserted disjoint).
    for champion_id in _ALLY_REACH_INCLUDED:
        if champion_id in _ALLY_REACH_EXCLUDED or champion_id not in body:
            continue
        reached.add(_norm_key(champion_id))
    return frozenset(reached)


def champion_ally_reach(champion: object, patch: Optional[str] = None) -> bool:
    """Return True when the champion's kit confers something on teammates.

    Fail-soft: blank / unknown champion, missing file or malformed data -> False,
    which keeps the ``team_blended`` seam inert. Never raises.
    """
    key = _norm_key(champion)
    if not key:
        return False
    return key in _ally_reach_index(patch)
