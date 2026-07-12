"""coaches/rune_pages.py - the rune-page model + exact-match dedup (item 1 Phase 1).

Rune-follows-build needs a canonical set of rune PAGES per champion+mode plus a
map from each build to its recommended page. A build stores only
{keystone, primary, secondary} (loadout_resolver.py); the full 9-perk page is a
pure function of those three (lcu/lcu_rune_writer.build_perk_ids), so the dedup
key is the resolved perk_ids tuple: two builds that resolve identically collapse
to ONE page, and a keystone/tree (or user minor-rune) difference mints a distinct
page.

NON-frozen: this module only IMPORTS build_perk_ids (the frozen resolver) and
list_variants (the non-frozen loadout reader). It writes nothing. User-build
pages fold into the same model in Phase 4 (resolve_page already accepts the
minor_primary/minor_secondary overrides build_perk_ids honors).
"""
from __future__ import annotations

import hashlib
from typing import Optional

from lcu.lcu_rune_writer import build_perk_ids
from coaches.loadout_resolver import list_variants

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
    return {
        "pageId": page_id(perk_ids),
        "keystone": keystone,
        "primary": primary,
        "secondary": secondary,
        "perk_ids": list(perk_ids),
    }


def enumerate_pages(champion: str, mode: str) -> dict:
    """Enumerate the deduped rune pages for a champion+mode across every generic
    build variant + its build_paths + each variant's auto (recommended) page, and
    map each buildId -> its recommendedPageId.

    Returns {"pages": [page, ...], "builds": [{"buildId", "recommendedPageId"}]}.
    Pages are exact-match deduped by pageId. buildId is the variant key, or
    "<variant>:<path-key>" for a build_path (mirrors champ_select.js's composed
    key). A build whose runes fail to resolve maps to recommendedPageId=None (the
    caller falls back to the champ's first page). User-build pages fold in Phase 4.
    """
    is_aram = _is_aram(mode)
    pages: dict = {}          # pageId -> page (dedup)
    builds: list = []

    def _add(keystone, primary, secondary):
        pg = resolve_page(keystone or "", primary or "", secondary or "", is_aram)
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
        builds.append({"buildId": vkey, "recommendedPageId": rec})
        # The variant's own selectable page (deduped against the auto above).
        _add(v.get("keystone"), v.get("primary"), v.get("secondary"))
        # Each build_path is its own selectable build with its own page.
        for bp in (v.get("build_paths") or []):
            bp_rec = _add(bp.get("keystone") or v.get("keystone"),
                          bp.get("primary") or v.get("primary"),
                          bp.get("secondary") or v.get("secondary"))
            bkey = bp.get("key") or ""
            bid = f"{vkey}:{bkey}" if bkey else vkey
            builds.append({"buildId": bid, "recommendedPageId": bp_rec})

    return {"pages": list(pages.values()), "builds": builds}
