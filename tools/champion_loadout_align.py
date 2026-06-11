"""Align curated SR builds to DS engine output + dedupe unique-family
clashes in ALL curated variants.

2026-05-24 (item 167): operator-directed fix for two related bugs:

  1. SR build chooser surfaces variants with two items sharing a
     unique-passive family (e.g. Trinity Force + Essence Reaver -
     forbidden double per core/build_order.py). The DS-vs-enemy-comp
     build path enforces filter_shared_uniques=True at the engine,
     but the curated variants stored in data/champion_loadouts.json
     went through the flat-N ranker and inherit the duplicates.

  2. Curated SR builds use role-standard items (e.g. Jinx RFC+Kraken)
     while DS-vs-enemy-comp picks BorK+Lord-Dominik's against tanks.
     Pivoting forces selling 3+ items. Homogenize by regenerating SR
     curated items via the SAME plan_build_order engine the live
     coach uses, so the two paths share components.

Per-mode policy (operator-decided):
  * SR    : regenerate items via plan_build_order(target_armor=80,
            target_mr=60, target_max_hp=2000, target_bonus_hp=600,
            level=14, inject_boots=True). Archetype derived from the
            variant key prefix (sr-<arch>), the _archetype field, or
            the keystone reverse-map. Boots integral.
  * ARAM  : dedupe unique-family duplicates in-place (preserve role-
            standard items per operator: "keep role standard as the
            preselected for aram since enemy unknown"). Boots
            integral - if dedupe removed the only boot, it gets re-
            inserted from _DEFAULT_BOOTS_BY_ARCHETYPE.
  * Arena : dedupe in-place. No boots (Arena has no shop boots).

Architecture mirrors tools/champion_loadout_handcurate.py: per-slice
patch files, merged via tools/champion_loadout_handcurate_merge.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from copy import deepcopy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAIN = _ROOT / "data" / "champion_loadouts.json"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Reuse boots-engine constants from the live build planner so SR regen
# + ARAM dedupe-with-boots-backfill stay in lockstep with the runtime.
from core.build_order import (  # noqa: E402
    _BOOTS_IDS,
    _BOOTS_NAMES,
    _BOOTSLESS_CHAMPS,
    _DEFAULT_BOOTS_BY_ARCHETYPE,
    plan_build_order,
)

# Keystone -> archetype reverse-map. Mirrors
# tools/champion_loadout_autogen.ARCH_RUNES exactly. Used when a legacy
# variant key doesn't encode the archetype (e.g. "adc-crit", "ap-burst").
_KEYSTONE_TO_ARCH: dict[str, str] = {
    "Lethal Tempo":         "carry",
    "Press the Attack":     "carry",
    "Fleet Footwork":       "carry",
    "Conqueror":            "bruiser",
    "Grasp of the Undying": "bruiser",
    "Aftershock":           "tank",
    "Guardian":             "enchanter",
    "Arcane Comet":         "mage",
    "Summon Aery":          "enchanter",
    "Phase Rush":           "mage",
    "Electrocute":          "assassin",
    "Dark Harvest":         "assassin",
    "Hail of Blades":       "assassin",
    "Predator":             "assassin",
    "First Strike":         "mage",
    "Unsealed Spellbook":   "enchanter",
    "Glacial Augment":      "enchanter",
}

_VALID_ARCHES = {"carry", "bruiser", "tank", "mage", "assassin", "enchanter"}

# Legacy variant-key token table. The hand-curated variants pre-dating
# the sr-<arch> convention (item 166) use operator-named tokens like
# "ap-burst", "adc-crit", "tank-engage". Map those to one of the 6 valid
# archetypes so the SR regen call routes through the right scorer. Order
# matters - first matching token wins (so "ap-bruiser" -> "bruiser" not
# "mage").
_LEGACY_TOKEN_TO_ARCH: list[tuple[str, str]] = [
    ("enchanter",  "enchanter"),
    ("support",    "enchanter"),
    ("assassin",   "assassin"),
    ("lethality",  "assassin"),
    ("bruiser",    "bruiser"),
    ("fighter",    "bruiser"),
    ("splitpush",  "bruiser"),
    ("lane-bully", "bruiser"),
    ("tank",       "tank"),
    ("engage",     "tank"),
    ("mage",       "mage"),
    ("poke",       "mage"),
    ("control",    "mage"),
    ("burst",      "mage"),
    ("ap",         "mage"),
    ("scaling",    "carry"),
    ("crit",       "carry"),
    ("on-hit",     "carry"),
    ("onhit",      "carry"),
    ("adc",        "carry"),
    ("ad",         "carry"),
    ("carry",      "carry"),
    ("roam",       "assassin"),
    ("jg",         "bruiser"),
]

# Typical mid-game enemy comp for the SR regen call. Matches the
# operator's "average enemy" baseline so the regenerated curated items
# are a sensible neutral pivot point against which the live
# DS-vs-enemy-comp build is the per-match adjustment.
_SR_TARGET_ARMOR    = 80.0
_SR_TARGET_MR       = 60.0
_SR_TARGET_MAX_HP   = 2000.0
_SR_TARGET_BONUS_HP = 600.0
_SR_LEVEL           = 14
# Item s8 (2026-06-10): SR builds are 7 entries (6 legendaries + boots;
# plan_build_order's slots count INCLUDES the injected boots). ARAM /
# Arena targets live in tools.champion_loadout_invariants.TARGET_LEN.
from tools.champion_loadout_invariants import TARGET_LEN  # noqa: E402

_SR_SLOTS           = TARGET_LEN["sr"]

_SHAPER = None


def _shaper():
    """Lazy item-213 Cleaner - shapes dedup output back to the exact
    per-mode length (pool refill + tail trim, boots at index 1)."""
    global _SHAPER
    if _SHAPER is None:
        from tools.champion_loadout_cleanup_pollution_item213 import Cleaner
        _SHAPER = Cleaner()
    return _SHAPER


def _build_name_to_family_map() -> dict[str, str]:
    """Return ``normalized_item_name -> unique_passive_key`` for the live
    DS engine's item registry. Normalized via ``_norm`` so curated
    variants' loose name strings ('Trinity Force' vs 'trinity force')
    map cleanly."""
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS
    out: dict[str, str] = {}
    for iid, eff in ITEM_EFFECTS.items():
        upk = getattr(eff, "unique_passive_key", None)
        nm = getattr(eff, "name", None)
        if upk and nm:
            out[_norm(nm)] = upk
    return out


def _norm(s: str) -> str:
    return (s or "").lower().strip().replace(" ", "").replace(
        "'", "").replace("-", "").replace(",", "").replace(".", "")


def _detect_archetype(variant_key: str, variant: dict) -> str:
    """Derive the archetype tag for a variant.

    Order: explicit ``_archetype`` -> variant-key suffix (sr-<arch>)
    -> keystone reverse-map -> ``carry`` default. Returned tag is one of
    the 6 ``_VALID_ARCHES`` values; unknown -> ``carry``.
    """
    explicit = (variant.get("_archetype") or "").strip().lower()
    if explicit in _VALID_ARCHES:
        return explicit
    # Variant key like "sr-bruiser" / "aram-mage" / "arena-tank".
    parts = variant_key.split("-")
    if len(parts) >= 2 and parts[0] in {"sr", "aram", "arena"}:
        if parts[-1] in _VALID_ARCHES:
            return parts[-1]
    # auto-<mode>-<slot>-<arch>
    if variant_key.startswith("auto-") and len(parts) >= 4:
        if parts[-1] in _VALID_ARCHES:
            return parts[-1]
    # Legacy token scan: walk the ordered table, first matching token
    # in the variant key wins. Catches "ap-burst", "adc-crit",
    # "tank-engage", etc.
    vk_lower = variant_key.lower()
    for token, arch in _LEGACY_TOKEN_TO_ARCH:
        if token in vk_lower:
            return arch
    # Reverse-map keystone as last resort.
    keystone = ((variant.get("runes") or {}).get("keystone") or "")
    arch = _KEYSTONE_TO_ARCH.get(keystone, "carry")
    if arch in _VALID_ARCHES:
        return arch
    return "carry"


def _dedupe_items(items: list[str], fam_map: dict[str, str]) -> list[str]:
    """Drop second + later items that share a unique-family with an
    earlier item. Returns the deduped list (length may shrink)."""
    out: list[str] = []
    seen_fams: set[str] = set()
    for it in items:
        fam = fam_map.get(_norm(it))
        if fam and fam in seen_fams:
            continue
        if fam:
            seen_fams.add(fam)
        out.append(it)
    return out


def _ensure_boots(items: list[str], archetype: str, champion: str) -> list[str]:
    """If the deduped list lost its only boot and the champ is bootsful,
    re-insert the archetype-default boot at index 1."""
    if champion in _BOOTSLESS_CHAMPS:
        return items
    if not items:
        return items
    # Detect any boots family entry.
    boots_names_lower = {nm.lower() for nm in _BOOTS_NAMES.values()}
    has_boots = any((it or "").strip().lower() in boots_names_lower
                     for it in items)
    if has_boots:
        return items
    boots_id = _DEFAULT_BOOTS_BY_ARCHETYPE.get(archetype, "3047")
    boots_name = _BOOTS_NAMES.get(boots_id, "Plated Steelcaps")
    out = list(items)
    out.insert(1, boots_name)
    return out


def _regenerate_sr(champion: str, archetype: str) -> list[str] | None:
    """Call plan_build_order with the SR typical-enemy baseline.
    Returns the item-name sequence (incl. boots) or None if the engine
    is unreachable / can't plan."""
    try:
        result = plan_build_order(
            champion,
            archetype,
            level=_SR_LEVEL,
            owned_item_ids=[],
            mode="SR",
            target_armor=_SR_TARGET_ARMOR,
            target_mr=_SR_TARGET_MR,
            target_max_hp=_SR_TARGET_MAX_HP,
            target_bonus_hp=_SR_TARGET_BONUS_HP,
            slots=_SR_SLOTS,
            inject_boots=True,
            timeout=15.0,
        )
    except Exception as exc:
        print(f"WARN: plan_build_order raised for {champion}|{archetype}: {exc}",
              file=sys.stderr)
        return None
    if result is None or not result.order:
        return None
    return [s.item_name for s in result.order]


def transform_champion(name: str, champ_entry: dict,
                        fam_map: dict[str, str],
                        sr_cache: dict[tuple[str, str], list[str] | None],
                        ) -> dict:
    """Per-champ patch entry. Empty dict if nothing changed."""
    patch_variants: dict = {}
    variants = champ_entry.get("variants") or {}
    for vk, v in variants.items():
        modes = v.get("modes") or []
        items_orig = list(v.get("items") or [])
        new_items: list[str] | None = None
        if "sr" in modes:
            arch = _detect_archetype(vk, v)
            cache_key = (name, arch)
            if cache_key not in sr_cache:
                sr_cache[cache_key] = _regenerate_sr(name, arch)
            regen = sr_cache[cache_key]
            if regen:
                new_items = list(regen)
            else:
                # Fall back to dedupe if engine couldn't plan.
                new_items = _dedupe_items(items_orig, fam_map)
                new_items = _ensure_boots(new_items, arch, name)
            # Item s8: dedupe/short-plan output refilled + trimmed to
            # the exact SR length (7 incl boots).
            new_items = _shaper().enforce_length(name, "sr", arch, new_items)
        elif "aram" in modes:
            arch = _detect_archetype(vk, v)
            new_items = _dedupe_items(items_orig, fam_map)
            new_items = _ensure_boots(new_items, arch, name)
            new_items = _shaper().enforce_length(name, "aram", arch, new_items)
        elif "arena" in modes:
            arch = _detect_archetype(vk, v)
            new_items = _dedupe_items(items_orig, fam_map)
            # No boots in Arena (no shop boots) - enforce_length's
            # reseat strips any that leaked in.
            new_items = _shaper().enforce_length(name, "arena", arch, new_items)
        else:
            continue
        if new_items != items_orig:
            patched = deepcopy(v)
            patched["items"] = new_items
            patch_variants[vk] = patched
    if not patch_variants:
        return {}
    return {"variants": patch_variants}


def build_patch(champ_names: list[str]) -> dict:
    with _MAIN.open("r", encoding="utf-8") as f:
        base = json.load(f)
    champs = base.get("champions") or {}
    fam_map = _build_name_to_family_map()
    sr_cache: dict[tuple[str, str], list[str] | None] = {}
    patch_champs: dict = {}
    for nm in champ_names:
        if nm not in champs:
            print(f"WARN: not in base: {nm}", file=sys.stderr)
            continue
        try:
            delta = transform_champion(nm, champs[nm], fam_map, sr_cache)
        except Exception as exc:
            print(f"ERROR on {nm}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            continue
        if delta:
            patch_champs[nm] = delta
    return {
        "_schema_version": 1,
        "_doc": [
            "Item 167 align/dedupe patch slice.",
            "Generated by tools/champion_loadout_align.py.",
            "Merged into data/champion_loadouts.json via",
            "tools/champion_loadout_handcurate_merge.py.",
        ],
        "champions": patch_champs,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slice", required=True,
                   help="Slice tag (a/b/c/d). Used in output filename.")
    p.add_argument("--champs", required=True,
                   help="Comma-separated champion display names.")
    p.add_argument("--out", default=None,
                   help="Output patch path. Default: "
                        "data/champion_loadouts_align_patch_<slice>.json")
    args = p.parse_args(argv)
    names = [c.strip() for c in args.champs.split(",") if c.strip()]
    if not names:
        print("no champion names supplied", file=sys.stderr)
        return 1
    out_path = (Path(args.out) if args.out
                else _ROOT / "data"
                     / f"champion_loadouts_align_patch_{args.slice}.json")
    patch = build_patch(names)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(patch, f, indent=2, ensure_ascii=True)
        f.write("\n")
    n = len(patch["champions"])
    v = sum(len(e.get("variants") or {}) for e in patch["champions"].values())
    print(f"slice={args.slice} champs_touched={n} variants_changed={v}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
