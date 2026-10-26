"""RM-720 (a) KEEP guard: two item-icon spellings the row filed as never
requested, which the legacy dashboard does request.

`/icons/items/<slug>.png` (dashboard/routes_static.py `_serve_icon_items_route`)
serves `data/icons/aram_items/`, and `web/legacy_index.html` `itemSlug` builds
the slug from an item NAME. The legacy page (`?ui=legacy`, or the fallback when
web/index.html fails to serve) is the only requester; the default UI moved off
this route (RM-857). RM-720 (a) proposed to `git rm` four spellings as never
requested. Measured s134 (lane 7), two of them ARE requested:
  - "Liandry's Anguish" and "Navori Flickerblades" are Arena item names in
    data/meta_build/arena_champion_builds.json `ideal_core_priority`. They flow
    through coaches/_arena_item_advisor.py `_resolve_build_path`, then
    coaches/arena_coach.py `item_build`, then legacy `renderItemBuildStrip`,
    which slugs each one to liandry-anguish / navori-flickerblades.
The other two (deaths-dance, lichbane) come only from the misspelled
"Deaths Dance" / "Lichbane" in aram_champion_builds.json `full_build`. The
only path that turns that list into `item_build` is the advisor's aram
fallback, which does not fire for Kayn or Twisted Fate (the Arena / Brawl
coaches read it only into a Haiku build note), so this guard does not pin them.

This guard fails if a pinned file is removed while the build data still names
it, or if the JS slug rule changes under the Python mirror below.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ICON_DIR = _ROOT / "data" / "icons" / "aram_items"
_LEGACY = _ROOT / "web" / "legacy_index.html"
_ARENA_BUILDS = _ROOT / "data" / "meta_build" / "arena_champion_builds.json"

# slug -> the arena build item name that produces it
_KEEP = {
    "navori-flickerblades": "Navori Flickerblades",
    "liandry-anguish": "Liandry's Anguish",
}

# The exact JS body this mirror copies (web/legacy_index.html itemSlug).
_JS_RULE = (
    "return String(name || '').toLowerCase()\n"
    "    .replace(/'s\\b|'/g, '')\n"
    "    .replace(/[^a-z0-9]+/g, '-')\n"
    "    .replace(/^-+|-+$/g, '');"
)


def _item_slug(name: str) -> str:
    s = re.sub(r"'s\b|'", "", str(name or "").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"^-+|-+$", "", s)


def _arena_build_names() -> set[str]:
    data = json.loads(_ARENA_BUILDS.read_text(encoding="utf-8"))
    names: set[str] = set()
    for row in data.values():
        if isinstance(row, dict):
            icp = row.get("ideal_core_priority") or []
            names.update(n for n in icp if isinstance(n, str))
    return names


def test_python_mirror_matches_the_js_item_slug_rule() -> None:
    src = _LEGACY.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"function itemSlug\(name\) \{\n  (.*?)\n\}", src, re.S)
    assert m, "itemSlug not found in web/legacy_index.html"
    assert m.group(1) == _JS_RULE, "itemSlug changed - update _item_slug and _JS_RULE together"


def test_mirror_reproduces_the_canonical_spellings() -> None:
    # Positive control: the canonical names slug to the OTHER file of each pair.
    assert _item_slug("Death's Dance") == "death-dance"
    assert _item_slug("Lich Bane") == "lich-bane"
    assert _item_slug("Liandry's Torment") == "liandry-torment"


def test_each_keep_spelling_is_named_by_the_arena_build_data() -> None:
    names = _arena_build_names()
    assert len(names) > 100, f"arena build names look empty: {len(names)}"
    for slug, name in _KEEP.items():
        assert _item_slug(name) == slug, (slug, name)
        assert name in names, f"{name!r} left arena ideal_core_priority; re-check {slug}.png"


def test_each_keep_spelling_is_still_on_disk() -> None:
    missing = [s for s in _KEEP if not (_ICON_DIR / f"{s}.png").is_file()]
    assert not missing, (
        f"{missing} removed while the arena build data still names them: the "
        "legacy item-build strip would 404 those icons (RM-720 (a) narrowed)."
    )
