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
(a fresh object every call) when there is no champion or the resolver has
no loadout - same fail-soft contract as the Haiku path so callers need not
guard. The three parts fail INDEPENDENTLY: a broken runes or notes input
blanks only that part ({} / ""), never the build beside it. Pure:
import-only reuse of loadout_resolver + archetype_picks. NO Anthropic
call, NO new dependency.

This WAS the substrate for the champ-select brief Haiku flip (items
273/276/280/283, flipped 2026-06-06): `_champ_select.brief_via_coach` now
serves THIS output DIRECTLY with zero Anthropic call, so the earlier
shadow-validate lane is retired - no live Haiku brief is left to shadow.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from dashboard._context import APP_DIR

log = logging.getLogger("rc.web_dashboard")

# Reference shape only - never returned (its list / dict would be shared with
# every caller); _empty_brief() builds a fresh one.
_EMPTY: dict = {"build": [], "runes": {}, "ally_notes": ""}
_BUILD_CAP = 7


def _empty_brief() -> dict:
    return {"build": [], "runes": {}, "ally_notes": ""}


def _is_int(value: object) -> bool:
    """A real int id (bool is an int subclass but never an id)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value: object) -> str:
    """Stripped text for a str, "" for anything else."""
    return value.strip() if isinstance(value, str) else ""

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

# Lazy keystone-id -> name resolver loaded from the DDragon runes file. A
# non-empty map is cached for the process; an empty one (file missing, being
# rewritten, corrupt) is NOT - it is retried once _KEYSTONE_RETRY_S has passed,
# so a bad first read cannot blank every keystone until a restart, and a
# missing file is not re-read on every brief.
_KEYSTONE_LOCK = threading.Lock()
_KEYSTONE_ID_TO_NAME: dict | None = None
_KEYSTONE_RETRY_S = 60.0
_KEYSTONE_RETRY_AT = 0.0
_monotonic = time.monotonic


def _parse_keystones(trees: object) -> dict:
    """{perk_id: name} over the row-0 (keystone) runes of every well-formed
    tree. A malformed tree, slot or rune is skipped, never fatal to the rest."""
    mapping: dict = {}
    if not isinstance(trees, list):
        return mapping
    for tree in trees:
        if not isinstance(tree, dict):
            continue
        slots = tree.get("slots")
        if not isinstance(slots, list) or not slots or not isinstance(slots[0], dict):
            continue
        runes = slots[0].get("runes")  # slot 0 is the keystone row
        if not isinstance(runes, list):
            continue
        for rune in runes:
            if not isinstance(rune, dict):
                continue
            rid = rune.get("id")
            name = _text(rune.get("name"))
            if _is_int(rid) and name:
                mapping[rid] = name
    return mapping


def _keystone_id_to_name() -> dict:
    """{perk_id: name} for the keystone runes from the DDragon runes file
    (BOM tolerated). Best-effort: empty dict when it is unreadable."""
    global _KEYSTONE_ID_TO_NAME, _KEYSTONE_RETRY_AT
    cached = _KEYSTONE_ID_TO_NAME
    if cached:
        return cached
    with _KEYSTONE_LOCK:
        if _KEYSTONE_ID_TO_NAME:
            return _KEYSTONE_ID_TO_NAME
        now = _monotonic()
        if _KEYSTONE_ID_TO_NAME is not None and now < _KEYSTONE_RETRY_AT:
            return _KEYSTONE_ID_TO_NAME
        mapping: dict = {}
        try:
            path = APP_DIR / "data" / "meta" / "ddragon_runes.json"
            mapping = _parse_keystones(
                json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, RecursionError) as exc:
            log.debug("keystone id map load: %s", type(exc).__name__)
        _KEYSTONE_ID_TO_NAME = mapping
        if not mapping:
            _KEYSTONE_RETRY_AT = now + _KEYSTONE_RETRY_S
        return mapping


def _runes_from_cmd(rune_cmd: dict) -> dict:
    """Map the resolver's rune_cmd (numeric perk_ids + tree ids) to the brief
    runes sub-dict shape: keystone / primary_tree / secondary_tree / shards.
    Only real int ids are looked up: a non-dict cmd, a non-list perk_ids or
    an unhashable / bool id reads as blank instead of raising."""
    if not isinstance(rune_cmd, dict):
        rune_cmd = {}
    perks = rune_cmd.get("perk_ids")
    if not isinstance(perks, (list, tuple)):
        perks = []
    keystone = ""
    if perks and _is_int(perks[0]):
        keystone = _keystone_id_to_name().get(perks[0], "")
    # Last 3 perk_ids are the stat shards (5xxx).
    shards: list = []
    for sid in perks[-3:] if len(perks) >= 3 else []:
        if _is_int(sid) and 5000 <= sid < 6000:
            shards.append(_SHARD_ID_TO_LABEL.get(sid, ""))

    def tree(key: str) -> str:
        tid = rune_cmd.get(key)
        return _TREE_ID_TO_NAME.get(tid, "") if _is_int(tid) else ""

    return {
        "keystone": keystone,
        "primary_tree": tree("primary_id"),
        "secondary_tree": tree("sub_id"),
        "shards": shards,
    }


def _ally_notes(champ: str, allies: list) -> str:
    """Deterministic one-sentence ally summary from the ally comp + archetype
    tags. Names the main carry (marksman > mage > assassin) and the main
    engage (tank > bruiser > engage support). Only references champ names
    actually present in `allies`; excludes self (`champ`). Empty string when
    allies is empty/unknown or not a list / tuple (a bare string is never
    walked per character), or when the tag table cannot be loaded."""
    if not isinstance(allies, (list, tuple)):
        return ""
    me = _text(champ)
    names = []
    for raw in allies:
        name = _text(raw)
        if name and name != me:
            names.append(name)
    if not names:
        return ""
    try:
        from core.archetype_picks import _load_champion_tags, tag_to_archetype
        tags = _load_champion_tags()
    except Exception as exc:  # best-effort; notes only  # noqa: BLE001
        log.debug("ally_notes tags: %s", type(exc).__name__)
        return ""
    if not isinstance(tags, dict):
        tags = {}
    # Assign each ally champ to its PRIMARY archetype only (first tag) so a
    # tank-with-secondary-mage like Malphite cannot masquerade as the carry.
    # archetype -> first ally champ holding it as primary (preserve comp order).
    by_arch: dict = {}
    for name in names:
        primary_tags = tags.get(name)
        if (not isinstance(primary_tags, (list, tuple)) or not primary_tags
                or not _text(primary_tags[0])):
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
    {build, runes, ally_notes} shape as brief_via_coach: a fresh EMPTY shape
    for a non-text / blank champ or when the resolver has no loadout or
    raises, and a
    blank runes ({}) or notes ("") part when only that part fails."""
    name = _text(champ)
    if not name:
        return _empty_brief()
    try:
        from coaches.loadout_resolver import default_variant, resolve
        variant = default_variant(name, mode)
        resolved = resolve(name, variant or "", mode)
        if not isinstance(resolved, dict) or not resolved.get("ok"):
            return _empty_brief()
        # build[] = curated purchase order (item NAMES), cap 7. Only a real
        # list is read - a bare string would be split into characters.
        raw_items = resolved.get("raw_items")
        if not isinstance(raw_items, (list, tuple)):
            raw_items = []
        build = [it for it in (_text(raw) for raw in raw_items) if it][:_BUILD_CAP]
        rune_cmd = resolved.get("rune_cmd")
    except Exception as exc:  # fail-soft: never raise  # noqa: BLE001
        log.warning("brief_deterministic(%r): %s", name, type(exc).__name__)
        return _empty_brief()
    try:
        runes = _runes_from_cmd(rune_cmd)
    except Exception as exc:  # fail-soft per part  # noqa: BLE001
        log.warning("brief_deterministic(%r) runes: %s", name, type(exc).__name__)
        runes = {}
    try:
        notes = _ally_notes(name, allies)
    except Exception as exc:  # fail-soft per part  # noqa: BLE001
        log.warning("brief_deterministic(%r) notes: %s", name, type(exc).__name__)
        notes = ""
    hint = _enemy_itemization(enemies)
    if hint:
        notes = f"{notes} {hint}" if notes else hint
    return {"build": build, "runes": runes, "ally_notes": notes}
