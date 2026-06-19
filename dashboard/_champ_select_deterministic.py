"""Deterministic champ-select brief substrate (NO Haiku call).

PRIMARY north-star, Haiku-elimination Lane B/C (item 273). Composes the
champ-select brief from surfaces RC already trusts - the curated
loadout_resolver (the same data driving the in-game build chooser) for
build + runes, and a role/archetype heuristic over the ally comp for the
one-sentence ally_notes.

`brief_deterministic()` mirrors the EXACT shape of
`dashboard._champ_select.brief_via_coach`:

    {"build": ["item1", ..., "item7"],
     "runes": {"keystone": "...", "primary_tree": "...",
               "secondary_tree": "...", "shards": ["...", "...", "..."]},
     "ally_notes": "<one sentence>"}

and returns the EMPTY shape {"build": [], "runes": {}, "ally_notes": ""}
on ANY error - same fail-soft contract as the Haiku path so callers need
not guard. Pure: import-only reuse of loadout_resolver + archetype_picks.
NO Anthropic call, NO new dependency.

This WAS the substrate for the champ-select brief Haiku flip (items
273/276/280/283, flipped 2026-06-06): `_champ_select.brief_via_coach` now
serves THIS output DIRECTLY with zero Anthropic call, so the earlier
shadow-validate lane is retired - no live Haiku brief is left to shadow.
"""
from __future__ import annotations

import json
import logging
import threading

from dashboard._context import APP_DIR

log = logging.getLogger("rc.web_dashboard")

_EMPTY: dict = {"build": [], "runes": {}, "ally_notes": ""}

# Tree id -> display name (Riot rune-tree IDs, stable across patches).
_TREE_ID_TO_NAME = {
    8000: "Precision",
    8100: "Domination",
    8200: "Sorcery",
    8300: "Inspiration",
    8400: "Resolve",
}

# Stat-shard id -> human label (the 5xxx stat mods; fixed Riot set). Mirrors
# the label vocabulary brief_via_coach emits for the 3 shard rows.
_SHARD_ID_TO_LABEL = {
    5005: "Attack Speed",
    5008: "Adaptive",
    5007: "Ability Haste",
    5001: "Health Scaling",
    5011: "Health",
    5013: "Tenacity and Slow Resist",
    5002: "Armor",
    5003: "Magic Resist",
    5010: "Move Speed",
}

# Archetype priority for picking the main carry / engage out of the ally comp.
# Carry = primary damage class, marksman > mage > assassin. Engage =
# tank > bruiser, then an engage-leaning support (enchanter).
_CARRY_PRIORITY = ("carry", "mage", "assassin")
_ENGAGE_PRIORITY = ("tank", "bruiser", "enchanter")

# Lazy keystone-id -> name resolver loaded from the DDragon runes file.
_KEYSTONE_LOCK = threading.Lock()
_KEYSTONE_ID_TO_NAME: dict | None = None


def _keystone_id_to_name() -> dict:
    """Load + cache {perk_id: name} for the keystone (row-0) runes from the
    DDragon runes file. Best-effort: empty dict if the file is unreadable."""
    global _KEYSTONE_ID_TO_NAME
    if _KEYSTONE_ID_TO_NAME is not None:
        return _KEYSTONE_ID_TO_NAME
    with _KEYSTONE_LOCK:
        if _KEYSTONE_ID_TO_NAME is not None:
            return _KEYSTONE_ID_TO_NAME
        mapping: dict = {}
        try:
            path = APP_DIR / "data" / "meta" / "ddragon_runes.json"
            trees = json.loads(path.read_text(encoding="utf-8"))
            for tree in trees:
                slots = tree.get("slots") or []
                if not slots:
                    continue
                # Slot 0 is the keystone row.
                for rune in slots[0].get("runes") or []:
                    rid = rune.get("id")
                    name = rune.get("name")
                    if isinstance(rid, int) and name:
                        mapping[rid] = name
        except Exception as exc:  # best-effort  # noqa: BLE001
            log.debug("keystone id map load: %s", exc)
        _KEYSTONE_ID_TO_NAME = mapping
        return mapping


def _runes_from_cmd(rune_cmd: dict) -> dict:
    """Map the resolver's rune_cmd (numeric perk_ids + tree ids) to the brief
    runes sub-dict shape: keystone / primary_tree / secondary_tree / shards."""
    perks = rune_cmd.get("perk_ids") or []
    primary_id = rune_cmd.get("primary_id")
    sub_id = rune_cmd.get("sub_id")
    keystone = ""
    if perks:
        keystone = _keystone_id_to_name().get(perks[0], "")
    # Last 3 perk_ids are the stat shards (5xxx).
    shards: list = []
    for sid in perks[-3:] if len(perks) >= 3 else []:
        if isinstance(sid, int) and 5000 <= sid < 6000:
            shards.append(_SHARD_ID_TO_LABEL.get(sid, ""))
    out = {
        "keystone": keystone,
        "primary_tree": _TREE_ID_TO_NAME.get(primary_id, ""),
        "secondary_tree": _TREE_ID_TO_NAME.get(sub_id, ""),
        "shards": shards,
    }
    return out


def _ally_notes(champ: str, allies: list) -> str:
    """Deterministic one-sentence ally summary from the ally comp + archetype
    tags. Names the main carry (marksman > mage > assassin) and the main
    engage (tank > bruiser > engage support). Only references champ names
    actually present in `allies`; excludes self (`champ`). Empty string when
    allies is empty/unknown."""
    try:
        from core.archetype_picks import _load_champion_tags, tag_to_archetype
    except Exception as exc:  # noqa: BLE001
        log.debug("ally_notes import: %s", exc)
        return ""
    names = [a for a in (allies or []) if isinstance(a, str) and a.strip()
             and a != champ]
    if not names:
        return ""
    tags = _load_champion_tags()
    # Assign each ally champ to its PRIMARY archetype only (first tag) so a
    # tank-with-secondary-mage like Malphite cannot masquerade as the carry.
    # archetype -> first ally champ holding it as primary (preserve comp order).
    by_arch: dict = {}
    for name in names:
        primary_tags = tags.get(name) or []
        if not primary_tags:
            continue
        arch = tag_to_archetype(primary_tags[0])
        if arch and arch not in by_arch:
            by_arch[arch] = name

    carry = next((by_arch[a] for a in _CARRY_PRIORITY if a in by_arch), "")
    engage = next((by_arch[a] for a in _ENGAGE_PRIORITY if a in by_arch
                   and by_arch[a] != carry), "")

    if carry and engage:
        return (f"{carry} is your main carry - peel and follow up; "
                f"{engage} is your engage.")
    if carry:
        return f"{carry} is your main carry - peel and follow up."
    if engage:
        return f"{engage} is your main engage - follow the initiation."
    # No clear carry/engage: name whatever ally is present.
    return f"{names[0]} is on your team - coordinate around their kit."


def _enemy_itemization(enemies: list) -> str:
    """Correct-by-construction itemization hint from the enemy damage-type
    distribution (core.aram_comp_verdict.compute_factors over champions.json
    info.attack/magic primary leans). Fires only with >= 3 resolvable enemies
    AND a CLEAR lean (the opposite primary type entirely absent), so a mixed
    enemy comp returns "". Returns a capitalized standalone clause or "".

    This is a FACT about the enemy comp (their damage profile), not a
    prediction - so it needs no live validation; it just surfaces the
    armor-vs-MR call that is the first itemization decision after the pick."""
    try:
        from core.aram_comp_verdict import compute_factors
        f = compute_factors(enemies or [])
        if f.get("n", 0) < 3:
            return ""
        ad = f.get("ad_count", 0)
        ap = f.get("ap_count", 0)
        if ad and not ap:
            return "Enemy comp is AD-heavy - prioritize armor."
        if ap and not ad:
            return "Enemy comp is AP-heavy - prioritize magic resist."
        return ""
    except Exception as exc:  # best-effort; never breaks the brief  # noqa: BLE001
        log.debug("enemy_itemization: %s", exc)
        return ""


def brief_deterministic(champ: str, enemies: list, allies: list,
                        role: str, mode: str) -> dict:
    """Compose the champ-select brief WITHOUT a Haiku call. build + runes come
    from the curated loadout_resolver (the in-game build-chooser data);
    ally_notes from a deterministic role/archetype heuristic. Returns the same
    {build, runes, ally_notes} shape as brief_via_coach, and the EMPTY shape
    on ANY error."""
    try:
        from coaches.loadout_resolver import default_variant, resolve
        variant = default_variant(champ, mode)
        resolved = resolve(champ, variant or "", mode)
        if not isinstance(resolved, dict) or not resolved.get("ok"):
            return dict(_EMPTY)
        # build[] = curated purchase order (item NAMES), cap 7.
        build = [it for it in (resolved.get("raw_items") or [])
                 if isinstance(it, str) and it][:7]
        runes = _runes_from_cmd(resolved.get("rune_cmd") or {})
        notes = _ally_notes(champ, allies)
        hint = _enemy_itemization(enemies)
        if hint:
            notes = (notes + " " + hint).strip() if notes else hint
        return {"build": build, "runes": runes, "ally_notes": notes}
    except Exception as exc:  # fail-soft: never raise  # noqa: BLE001
        log.warning("brief_deterministic(%s): %s", champ, exc)
        return dict(_EMPTY)
