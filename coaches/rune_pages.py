"""coaches/rune_pages.py - the rune-page model + exact-match dedup (item 1 Phase 1).

Rune-follows-build needs a canonical set of rune PAGES per champion+mode plus a
map from each build to its recommended page. A build stores only
{keystone, primary, secondary} (loadout_resolver.py); the full 9-perk page is a
pure function of those three (lcu/lcu_rune_writer.build_perk_ids), so the dedup
key is the resolved perk_ids tuple: two builds that resolve identically collapse
to ONE page, and a keystone/tree (or user minor-rune) difference mints a distinct
page.

NON-frozen: this module only IMPORTS build_perk_ids (also NOT frozen -
corrected lane 8 cycle 39; lcu/lcu_rune_writer.py is absent from the 16-entry
CLAUDE.md frozen list, unlike lcu/lcu_client.py),
list_variants (the non-frozen loadout reader), and list_for (the user-build
store). It writes nothing. Operator user-curated builds fold into the same
model (Phase 4) via resolve_page, which honors the stored minor_primary/
minor_secondary overrides build_perk_ids applies.

s144 true-audit cycle 103 - what the model now guarantees, each pinned in
tests/test_rune_pages_true_audit_s144t103.py:

  - A served page is LEGAL against the DDragon slot table
    (data/meta/ddragon_runes.json): the keystone is in the primary tree's
    keystone row, the three primary minors cover rows 1-3 of that tree, the two
    secondary minors sit in two different non-keystone rows of the secondary
    tree. build_perk_ids checks none of that, so a keystone outside its tree or
    a user minor rune from the wrong tree used to enter the model (and League
    rejects such a page after the writer has already deleted the old one).
  - The dedup key is ORDER-INSENSITIVE within a row group. The user-build
    editor stores minor runes in click order, so the same page saved twice used
    to mint two pageIds. perk_ids are re-ordered by row before hashing; every
    default page is already in row order, so no shipped pageId moved (saved
    defaults are keyed by pageId in browser localStorage).
  - Every buildId is unique and resolvable, and every pushPageId is the page
    the resolver would actually push: user builds are read the way
    dashboard/routes_loadout._resolve_user_build reads them (format_for_display,
    then str()), a record format_for_display rejects (no label, no items -
    one the chooser never lists) is not served, and a repeated key keeps its
    FIRST entry - the one both resolvers match. (The chooser's own merge in
    _serve_loadout_list_post still drops every LATER user build when one
    record raises; this model isolates per record, deliberately.)
  - One malformed record (a non-string id, a non-dict runes, an unhashable rune
    name) drops only itself, never the rest of the model.

If the slot table cannot be read the model is served UNVALIDATED (the pre-audit
behaviour), logged once - a missing data file must not blank the side panel.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from lcu.lcu_rune_writer import _TREES, build_perk_ids, resolve_tree_ids
from coaches.loadout_resolver import list_variants
# Phase 4: operator user-curated builds fold into the same model. list_for is a
# leaf reader (no coaches imports at module load), so this top-level import is
# circular-safe. Bound as _user_builds_for so tests patch it on this module the
# same way they patch list_variants. format_for_display is the shaping step the
# chooser (routes_loadout._serve_loadout_list_post) and the push resolver
# (routes_loadout._resolve_user_build) both apply; mirroring it keeps
# pushPageId equal to what the resolver pushes.
from coaches.sr_user_builds import format_for_display as _shape_user_build
from coaches.sr_user_builds import list_for as _user_builds_for

_log = logging.getLogger("rc.rune_pages")

# Modes whose shard defaults differ (build_perk_ids is_aram switch). Mirrors the
# set in lcu_rune_writer.load_rune_rec so a page resolves to the same perk_ids the
# writer would push.
_ARAM_MODES = {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}

# The DDragon rune tree file lcu_rune_writer._perk_by_name also reads. Tracked
# in the repo; refreshed with each DDragon patch.
_DDRAGON_RUNES = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_runes.json"

# perk id -> (tree id, slot index); slot 0 is the keystone row. Cached only
# after a successful parse, so a transient read error is retried next call.
# Unlocked on purpose: the build is idempotent and the assignment atomic.
_SLOT_TABLE: Optional[dict[int, tuple[int, int]]] = None
_SLOT_TABLE_FAIL_LOGGED = False

# DDragon tree layout: one keystone row plus three minor rows.
_SLOTS_PER_TREE = 4


def _is_aram(mode: str) -> bool:
    m = str(mode or "").upper()
    return m in _ARAM_MODES or "ARAM" in m


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def page_id(perk_ids) -> str:
    """Stable short id for a resolved rune page = the dedup key. Two builds whose
    resolved 9-element perk_ids match collapse to this one id."""
    key = ",".join(str(int(x)) for x in perk_ids)
    return "p" + hashlib.sha1(key.encode("ascii")).hexdigest()[:12]


def _parse_slot_table(doc: object) -> dict[int, tuple[int, int]]:
    """Build {perk id: (tree id, slot index)} from a runesReforged document.

    Raises ValueError on any shape it does not recognise, so a renamed or
    truncated upstream field reads as "table unavailable", never as a partial
    table that would reject legal pages.
    """
    if not isinstance(doc, list) or not doc:
        raise ValueError("rune document is not a non-empty list")
    table: dict[int, tuple[int, int]] = {}
    for tree in doc:
        tree_id = tree.get("id") if isinstance(tree, dict) else None
        slots = tree.get("slots") if isinstance(tree, dict) else None
        if not _is_int(tree_id) or not isinstance(slots, list) \
                or len(slots) != _SLOTS_PER_TREE:
            raise ValueError("rune tree without an int id and four slots")
        for index, slot in enumerate(slots):
            runes = slot.get("runes") if isinstance(slot, dict) else None
            if not isinstance(runes, list) or not runes:
                raise ValueError("rune slot without runes")
            for rune in runes:
                rune_id = rune.get("id") if isinstance(rune, dict) else None
                if not _is_int(rune_id) or rune_id in table:
                    raise ValueError("rune without a unique int id")
                table[rune_id] = (tree_id, index)
    return table


def _slot_table() -> Optional[dict[int, tuple[int, int]]]:
    """The cached slot table, or None (logged once) when it cannot be read."""
    global _SLOT_TABLE, _SLOT_TABLE_FAIL_LOGGED
    table = _SLOT_TABLE
    if table is not None:
        return table
    try:
        table = _parse_slot_table(
            json.loads(_DDRAGON_RUNES.read_text(encoding="utf-8")))
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        if not _SLOT_TABLE_FAIL_LOGGED:
            _SLOT_TABLE_FAIL_LOGGED = True
            _log.warning("rune-pages slot table unavailable (%s); rune pages "
                         "are served unvalidated", type(exc).__name__)
        return None
    _SLOT_TABLE = table
    return table


def _canonical_perk_ids(perk_ids: list, pri_id: int, sub_id: int,
                        table: dict[int, tuple[int, int]]) -> Optional[list[int]]:
    """Return perk_ids in row order, or None when the page is not legal.

    Layout (build_perk_ids): [keystone, 3 primary minors, 2 secondary minors,
    3 shards]. Shards are not in the slot table and keep their positions.
    """
    if len(perk_ids) != 9 or not all(_is_int(x) for x in perk_ids):
        return None
    if pri_id == sub_id or table.get(perk_ids[0]) != (pri_id, 0):
        return None
    primary = [(table.get(x), x) for x in perk_ids[1:4]]
    secondary = [(table.get(x), x) for x in perk_ids[4:6]]
    if any(slot is None or slot[0] != pri_id for slot, _ in primary):
        return None
    if sorted(slot[1] for slot, _ in primary) != [1, 2, 3]:
        return None
    if any(slot is None or slot[0] != sub_id or slot[1] == 0
           for slot, _ in secondary):
        return None
    if secondary[0][0][1] == secondary[1][0][1]:
        return None
    primary.sort(key=lambda pair: pair[0][1])
    secondary.sort(key=lambda pair: pair[0][1])
    return [perk_ids[0], *(x for _, x in primary), *(x for _, x in secondary),
            *perk_ids[6:]]


def resolve_page(
    keystone: str,
    primary: str,
    secondary: str,
    is_aram: bool = False,
    minor_primary: Optional[list] = None,
    minor_secondary: Optional[list] = None,
) -> Optional[dict]:
    """Resolve a (keystone, primary, secondary[, minor runes]) page to its
    perk_ids + stable pageId. Returns None when build_perk_ids rejects the names,
    when a name is not even hashable, or when the resolved page is not legal
    against the DDragon slot table, so a malformed page never enters the model
    (while that table is readable - see the module docstring)."""
    try:
        perk_ids = build_perk_ids(
            keystone, primary, secondary, is_aram, minor_primary, minor_secondary)
        if not perk_ids:
            return None
        # Lane 8 cycle 39: report the secondary tree the perk ids ACTUALLY came
        # from. build_perk_ids substitutes a secondary that collides with the
        # primary, and echoing the requested name here rendered a page in the UI
        # whose named tree did not own two of its runes.
        pri_id, sub_id = resolve_tree_ids(primary, secondary)
    except TypeError:
        # A list or dict where a rune name belongs: the writer's dict lookups
        # raise on it. Cycle 103 F4 - that used to escape enumerate_pages and
        # turn the whole route into a 500.
        _log.debug("rune-pages: unhashable rune name in %r / %r / %r",
                   type(keystone).__name__, type(primary).__name__,
                   type(secondary).__name__)
        return None
    if not pri_id or not sub_id:
        return None
    perk_ids = list(perk_ids)
    table = _slot_table()
    if table is not None:
        canonical = _canonical_perk_ids(perk_ids, pri_id, sub_id, table)
        if canonical is None:
            # keystone / primary / secondary passed build_perk_ids, so they are
            # names from the writer's own tables - safe to log.
            _log.info("rune-pages: dropped an illegal page %s / %s / %s",
                      keystone, primary, secondary)
            return None
        perk_ids = canonical
    resolved_secondary = next(
        (name for name, tid in _TREES.items() if tid == sub_id), secondary)
    return {
        "pageId": page_id(perk_ids),
        "keystone": keystone,
        "primary": primary,
        "secondary": resolved_secondary,
        "perk_ids": perk_ids,
    }


def _is_variant_key(key: object) -> bool:
    # loadout_resolver.resolve splits "<variant>:<path>" on the FIRST colon and
    # uses a colon-free variant key verbatim, so a key holding a colon, padding
    # or nothing at all is a buildId no resolver can find.
    return isinstance(key, str) and bool(key) and key == key.strip() and ":" not in key


def _is_path_key(key: object) -> bool:
    # resolve() strips the requested path key before comparing it to the
    # stored one, so a padded stored key never matches.
    return isinstance(key, str) and bool(key) and key == key.strip()


def _rune_names(value: object) -> list:
    """Minor-rune names exactly as _resolve_user_build passes them on."""
    return [str(x) for x in (value or []) if x]


def enumerate_pages(champion: str, mode: str) -> dict:
    """Enumerate the deduped rune pages for a champion+mode across every generic
    build variant + its build_paths + each variant's auto (recommended) page, and
    map each buildId -> its recommendedPageId.

    Returns {"pages": [page, ...],
             "builds": [{"buildId", "recommendedPageId", "pushPageId"}]}.
    Pages are exact-match deduped by pageId. buildId is the variant key, or
    "<variant>:<path-key>" for a build_path (mirrors champ_select.js's composed
    key). recommendedPageId is the AUTO page (the keystone the frozen writer
    applies - the star follows it). pushPageId (Phase 6) is the page the manual
    resolver ACTUALLY pushes for that buildId: the variant's OWN runes (which
    can differ from the auto page), or a path/user build's own page (== its
    recommendedPageId). A build whose runes fail to resolve, or resolve to an
    illegal page, maps its id to None (the caller falls back); for a bare
    variant that is BOTH ids, because the panel's push lookup falls back from
    a missing pushPageId to recommendedPageId. Operator
    user-curated builds fold in last, keyed "userbuild_<id>" and deduped against
    the generic pages. buildIds are unique: a build whose id is empty, cannot be
    resolved, or repeats an earlier one is left out (the first entry is the one
    loadout_resolver.resolve and _resolve_user_build match).
    """
    is_aram = _is_aram(mode)
    pages: dict = {}          # pageId -> page (dedup)
    builds: list = []
    seen: set = set()

    def _add(keystone, primary, secondary,
             minor_primary=None, minor_secondary=None):
        pg = resolve_page(keystone or "", primary or "", secondary or "", is_aram,
                          minor_primary, minor_secondary)
        if pg is None:
            return None
        pages.setdefault(pg["pageId"], pg)
        return pg["pageId"]

    def _claim(build_id: str) -> bool:
        if build_id in seen:
            _log.debug("rune-pages: repeated buildId for %r skipped", champion)
            return False
        seen.add(build_id)
        return True

    for v in list_variants(champion, mode):
        if not isinstance(v, dict):
            continue
        vkey = v.get("key")
        if not _is_variant_key(vkey) or not _claim(vkey):
            continue
        # The variant's recommended page = its auto (the keystone the writer
        # applies); fall back to the variant's own keystone/trees.
        rec = _add(v.get("auto_keystone") or v.get("keystone"),
                   v.get("auto_primary") or v.get("primary"),
                   v.get("auto_secondary") or v.get("secondary"))
        # Phase 6: pushPageId = the page resolve(vkey) ACTUALLY pushes through
        # the manual seam = the variant's OWN runes (the resolver never reads
        # auto_*). For a champ where auto != own this is a DIFFERENT page than
        # recommendedPageId, so the JS reverse-maps the selected pageId to the
        # build whose pushPageId matches. The variant's own selectable page is
        # deduped against the auto page above.
        own = _add(v.get("keystone"), v.get("primary"), v.get("secondary"))
        if own is None:
            # champ_select.js _csvPushFollowedRune matches a build on
            # `pushPageId || recommendedPageId`, so a None own page would fall
            # back to the AUTO page and push resolve(vkey) - the variant's own
            # runes, which are illegal or unresolvable - whenever the auto page
            # is selected. No recommended page either, then: the frozen writer
            # still applies the auto page, it just is not starred for this row.
            rec = None
        builds.append({"buildId": vkey, "recommendedPageId": rec,
                       "pushPageId": own})
        # Each build_path is its own selectable build with its own page. The
        # resolver overlays the path runes, so pushPageId == recommendedPageId.
        for bp in (v.get("build_paths") or []):
            if not isinstance(bp, dict):
                continue
            bkey = bp.get("key")
            # A keyless path used to take the variant's own buildId.
            if not _is_path_key(bkey) or not _claim(f"{vkey}:{bkey}"):
                continue
            bp_rec = _add(bp.get("keystone") or v.get("keystone"),
                          bp.get("primary") or v.get("primary"),
                          bp.get("secondary") or v.get("secondary"))
            builds.append({"buildId": f"{vkey}:{bkey}",
                           "recommendedPageId": bp_rec, "pushPageId": bp_rec})

    # Phase 4: fold operator user-curated builds (coaches/sr_user_builds) into
    # the same model. Each is its own selectable build keyed "userbuild_<id>"
    # (mirrors routes_loadout._serve_loadout_list_post's namespacing so the
    # champ-select follow map lines up) whose page carries the stored minor-rune
    # overrides. Exact-match dedup falls out for free: an identical-perk_ids user
    # build collapses onto an existing page, a subrune delta mints a new one.
    # Operator-additive invariant: a broken store never blocks the generic model,
    # and one broken record never blocks the others.
    try:
        records = _user_builds_for(champion)
    except Exception as exc:  # noqa: BLE001
        _log.warning("rune-pages user-build fold for %r: %s",
                     champion, type(exc).__name__)
        records = []
    for rec in (records if isinstance(records, list) else []):
        uid = rec.get("id") if isinstance(rec, dict) else None
        # _resolve_user_build compares the stored id to the STRING after the
        # prefix, so a non-string id can never be pushed.
        # Claimed BEFORE shaping: _resolve_user_build stops at the FIRST record
        # with this id, so if that one is malformed the id is unpushable even
        # when a later duplicate is fine.
        if not isinstance(uid, str) or not uid or not _claim("userbuild_" + uid):
            continue
        try:
            shaped = _shape_user_build(rec)
        except (TypeError, AttributeError, ValueError):
            # e.g. runes stored as a list, items as a number: the chooser and
            # the resolver fail on this record too.
            _log.debug("rune-pages: malformed user build for %r skipped", champion)
            continue
        if not shaped:
            continue
        r = shaped.get("runes") or {}
        rec_page = _add(str(r.get("keystone") or ""), str(r.get("primary") or ""),
                        str(r.get("secondary") or ""),
                        _rune_names(r.get("minor_primary")),
                        _rune_names(r.get("minor_secondary")))
        # Phase 6: the resolver (_resolve_user_build) honors the stored
        # minor runes, so pushPageId == recommendedPageId for a user build.
        builds.append({"buildId": "userbuild_" + uid,
                       "recommendedPageId": rec_page,
                       "pushPageId": rec_page})

    return {"pages": list(pages.values()), "builds": builds}
