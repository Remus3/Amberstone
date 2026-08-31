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
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from lcu.lcu_rune_writer import _TREES, build_perk_ids, resolve_tree_ids
from coaches.loadout_resolver import list_variants
# Phase 4: operator user-curated builds fold into the same model. list_for is a
# leaf reader (no coaches imports at module load), so this top-level import is
# circular-safe. Bound as _user_builds_for so tests patch it on this module the
# same way they patch list_variants.
from coaches.sr_user_builds import list_for as _user_builds_for

_log = logging.getLogger("rc.rune_pages")

# Modes whose shard defaults differ (build_perk_ids is_aram switch). Mirrors the
# set in lcu_rune_writer.load_rune_rec so a page resolves to the same perk_ids the
# writer would push.
_ARAM_MODES = {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}


def _is_aram(mode: str) -> bool:
    m = str(mode or "").upper()
    return m in _ARAM_MODES or "ARAM" in m


def page_id(perk_ids) -> str:
    """Stable short id for a resolved rune page = the dedup key. Two builds whose
    resolved 9-element perk_ids match collapse to this one id."""
    key = ",".join(str(int(x)) for x in perk_ids)
    return "p" + hashlib.sha1(key.encode("ascii")).hexdigest()[:12]


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
    so a malformed page never enters the model."""
    perk_ids = build_perk_ids(
        keystone, primary, secondary, is_aram, minor_primary, minor_secondary)
    if not perk_ids:
        return None
    # Lane 8 cycle 39: report the secondary tree the perk ids ACTUALLY came
    # from. build_perk_ids substitutes a secondary that collides with the
    # primary, and echoing the requested name here rendered a page in the UI
    # whose named tree did not own two of its runes.
    _, sub_id = resolve_tree_ids(primary, secondary)
    resolved_secondary = next(
        (name for name, tid in _TREES.items() if tid == sub_id), secondary)
    return {
        "pageId": page_id(perk_ids),
        "keystone": keystone,
        "primary": primary,
        "secondary": resolved_secondary,
        "perk_ids": list(perk_ids),
    }


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
    recommendedPageId). A build whose runes fail to resolve maps its id to None
    (the caller falls back). Operator user-curated builds fold in last, keyed
    "userbuild_<id>" and deduped against the generic pages.
    """
    is_aram = _is_aram(mode)
    pages: dict = {}          # pageId -> page (dedup)
    builds: list = []

    def _add(keystone, primary, secondary,
             minor_primary=None, minor_secondary=None):
        pg = resolve_page(keystone or "", primary or "", secondary or "", is_aram,
                          minor_primary, minor_secondary)
        if pg is None:
            return None
        pages.setdefault(pg["pageId"], pg)
        return pg["pageId"]

    for v in list_variants(champion, mode):
        vkey = v.get("key") or ""
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
        builds.append({"buildId": vkey, "recommendedPageId": rec,
                       "pushPageId": own})
        # Each build_path is its own selectable build with its own page. The
        # resolver overlays the path runes, so pushPageId == recommendedPageId.
        for bp in (v.get("build_paths") or []):
            bp_rec = _add(bp.get("keystone") or v.get("keystone"),
                          bp.get("primary") or v.get("primary"),
                          bp.get("secondary") or v.get("secondary"))
            bkey = bp.get("key") or ""
            bid = f"{vkey}:{bkey}" if bkey else vkey
            builds.append({"buildId": bid, "recommendedPageId": bp_rec,
                           "pushPageId": bp_rec})

    # Phase 4: fold operator user-curated builds (coaches/sr_user_builds) into
    # the same model. Each is its own selectable build keyed "userbuild_<id>"
    # (mirrors routes_loadout._serve_loadout_list_post's namespacing so the
    # champ-select follow map lines up) whose page carries the stored minor-rune
    # overrides. Exact-match dedup falls out for free: an identical-perk_ids user
    # build collapses onto an existing page, a subrune delta mints a new one.
    # Operator-additive invariant: a broken store never blocks the generic model
    # (list_for already degrades to [] on a malformed file; the guard covers any
    # harder failure).
    try:
        for rec in _user_builds_for(champion):
            if not isinstance(rec, dict):
                continue
            uid = rec.get("id") or ""
            if not uid:
                continue
            r = rec.get("runes") or {}
            rec_page = _add(r.get("keystone"), r.get("primary"), r.get("secondary"),
                            r.get("minor_primary"), r.get("minor_secondary"))
            # Phase 6: the resolver (_resolve_user_build) honors the stored
            # minor runes, so pushPageId == recommendedPageId for a user build.
            builds.append({"buildId": "userbuild_" + uid,
                           "recommendedPageId": rec_page,
                           "pushPageId": rec_page})
    except Exception as exc:  # noqa: BLE001
        _log.warning("rune-pages user-build fold for %r: %s", champion, exc)

    return {"pages": list(pages.values()), "builds": builds}
