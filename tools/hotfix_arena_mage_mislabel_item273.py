"""Hotfix item 273 - relabel AD-dominant Arena "Mage" build paths.

Item 269 L4 carry (confirmed item 273): the Arena auto-seed in
``tools/champion_loadout_autogen.py`` stamps the archetype-slot LABEL
("Mage") over whatever items the DS Arena scorer returns for that slot.
For AP-flex champions whose default archetype triplet carries a "mage"
slot (Kha'Zix / Qiyana / Smolder / Talon / Varus / Zed via DDragon
secondary tag, Pyke / Senna via the enchanter->mage flavor heuristic)
the Arena scorer returns AD lethality/bruiser items (Bloodthirster /
Ravenous Hydra / Hemomancer's Helm / Manamune) because Arena AP items
are sparse for an AD kit. The result is an AD-dominant build wearing a
"Mage" label.

This is a LABEL-only defect. The build items are a legitimate AD
bruiser/lifesteal path; only the archetype label is wrong. This tool
RELABELS each AD-dominant Arena "Mage" build path to the AD archetype
its items actually represent (Bruiser), changing ONLY the ``label`` +
``key`` (and ``_archetype`` if present). Item CONTENT is untouched - no
re-ranking. Arena INTENTIONALLY keeps bruiser-ADC items (Trinity Force
/ Heartsteel / Divine Sunderer on ADCs is genuine Arena meta).

AD-dominant = the build path's pure-AD item count exceeds its pure-AP
item count. Hybrid items (flat AP AND flat AD, e.g. Twilight's Edge)
count toward neither. AP/AD source of truth:
``data/daemon_slayer/16.11.1/items.json`` ``data`` map's
``stats.FlatMagicDamageMod`` / ``stats.FlatPhysicalDamageMod`` per item
name (max across id variants, since Arena ships 22-prefixed mirror ids).

A relabel is SKIPPED (left untouched, logged) if the champion's Arena
variant already carries a path with the target ("bruiser") terminal
key - to avoid a duplicate-archetype-key collision within one variant.
At item 273 no affected champion has a Bruiser Arena path, so no skips
occur; the guard is defense-in-depth for re-runs / future data.

Idempotent: a relabeled path is no longer "Mage"-labeled, so a second
run is a no-op. Atomic write via tmp.write_text + tmp.replace.

Usage:
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/hotfix_arena_mage_mislabel_item273.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"
_ITEMS = _ROOT / "data" / "daemon_slayer" / "16.11.1" / "items.json"

# Target AD archetype for an AD-dominant "Mage" path. Bloodthirster /
# Ravenous Hydra / Hemomancer's Helm lifesteal-sustain is the Arena
# bruiser signature (distinct from Assassin's Divine Sunderer / Sundered
# Sky and Carry's crit-shiv).
_TARGET_ARCH = "bruiser"
_TARGET_LABEL = "Bruiser"

# Slot suffix carried on the human label: "Mage" / "Mage (sec)" /
# "Mage (flav)" -> "Bruiser" / "Bruiser (sec)" / "Bruiser (flav)".
_SUFFIX_BY_TOKEN = {"sec": " (sec)", "flav": " (flav)"}


def _ap_ad_maps() -> tuple[dict, dict]:
    with _ITEMS.open("r", encoding="utf-8") as f:
        data = json.load(f)["data"]
    ap_map: dict = {}
    ad_map: dict = {}
    for _iid, rec in data.items():
        nm = rec.get("name", "")
        if not nm:
            continue
        st = rec.get("stats") or {}
        ap = st.get("FlatMagicDamageMod") or 0
        ad = st.get("FlatPhysicalDamageMod") or 0
        ap_map[nm] = max(ap_map.get(nm, 0), ap)
        ad_map[nm] = max(ad_map.get(nm, 0), ad)
    return ap_map, ad_map


def _is_mage_path(bp: dict) -> bool:
    return "Mage" in (bp.get("label") or "") or "mage" in (bp.get("key") or "")


def _pure_counts(items: list, ap_map: dict, ad_map: dict) -> tuple:
    ap_c = 0
    ad_c = 0
    for it in items:
        ap = ap_map.get(it, 0)
        ad = ad_map.get(it, 0)
        if ap > 0 and ad == 0:
            ap_c += 1
        elif ad > 0 and ap == 0:
            ad_c += 1
    return ap_c, ad_c


def _slot_token(key: str) -> str:
    """Return the slot token from a key: '' (primary, 'arena-mage'),
    'sec' (auto-arena-secondary-mage) or 'flav' (auto-arena-flavor-mage)."""
    if "-secondary-" in key:
        return "sec"
    if "-flavor-" in key:
        return "flav"
    return ""


def _relabel(bp: dict) -> dict:
    """Return a relabeled copy of an AD-dominant Mage build path.
    Items, runes, summoners, reason all preserved."""
    key = bp.get("key") or ""
    token = _slot_token(key)
    new = dict(bp)
    new["label"] = _TARGET_LABEL + _SUFFIX_BY_TOKEN.get(token, "")
    # arena-mage -> arena-bruiser ; auto-arena-<slot>-mage ->
    # auto-arena-<slot>-bruiser. Only the trailing 'mage' segment moves.
    if key.endswith("-mage"):
        new["key"] = key[: -len("mage")] + _TARGET_ARCH
    elif key.endswith("mage"):
        new["key"] = key[: -len("mage")] + _TARGET_ARCH
    if new.get("_archetype") == "mage":
        new["_archetype"] = _TARGET_ARCH
    return new


def run(dry_run: bool = False) -> int:
    ap_map, ad_map = _ap_ad_maps()
    with _LOADOUTS.open("r", encoding="utf-8") as f:
        loadouts = json.load(f)

    relabeled: list = []
    skipped: list = []

    for champ, rec in loadouts.get("champions", {}).items():
        av = (rec.get("variants") or {}).get("arena-collapsed")
        if not av:
            continue
        paths = av.get("build_paths") or []
        existing_keys = {(bp.get("key") or "").split("-")[-1] for bp in paths}
        for idx, bp in enumerate(paths):
            if not _is_mage_path(bp):
                continue
            items = bp.get("items", []) or []
            ap_c, ad_c = _pure_counts(items, ap_map, ad_map)
            if ad_c <= ap_c:
                # AP-dominant or balanced Mage path - leave it alone.
                continue
            # AD-dominant Mage path. Guard against duplicate target key.
            if _TARGET_ARCH in (existing_keys - {(bp.get("key") or "").split("-")[-1]}):
                skipped.append(
                    f"{champ} '{bp.get('label')}' -> would collide with "
                    f"existing '{_TARGET_ARCH}' key; left untouched"
                )
                continue
            new = _relabel(bp)
            relabeled.append(
                f"{champ} '{bp.get('label')}' ({bp.get('key')}) -> "
                f"'{new['label']}' ({new['key']})"
            )
            paths[idx] = new
            existing_keys.discard((bp.get("key") or "").split("-")[-1])
            existing_keys.add(_TARGET_ARCH)

    print(f"=== item 273 Arena Mage-mislabel relabel: {len(relabeled)} path(s) ===")
    for line in relabeled:
        print("  " + line)
    if skipped:
        print(f"--- skipped (collision): {len(skipped)} ---")
        for line in skipped:
            print("  " + line)

    if dry_run:
        print("(dry-run; no write)")
        return 0

    if not relabeled:
        print("no changes; data already clean (idempotent no-op)")
        return 0

    text = json.dumps(loadouts, indent=2, ensure_ascii=True) + "\n"
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(_LOADOUTS))
    print(f"wrote {_LOADOUTS}")
    return 0


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="item 273 Arena Mage-mislabel relabel")
    p.add_argument("--dry-run", action="store_true", help="report only, no write")
    args = p.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
