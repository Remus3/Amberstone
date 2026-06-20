"""Hand-curate promotion + variant-fill tool.

2026-05-24 (item 166): operator-directed roster population for SR /
Arena / ARAM Mayhem builds. Promotes auto-generated variants into
canonical hand-curated entries and fills missing 2nd-SR / 3rd-ARAM
variant slots. Boots injected for SR/ARAM (integral); excluded from
Arena (no shop boots).

Per-champ transformation:
  * Arena: take ``auto-arena-primary-<arch>`` (or first ``auto-arena-*``
    fallback). Clone it as ``arena-<arch>`` without ``_auto`` /
    ``_archetype``. Flip ``default_per_mode.arena`` to the new key.
  * SR: if hand-variant-count for sr < 2, promote
    ``auto-sr-secondary-<arch>`` (or any sr auto not equal to current
    sr default) to ``sr-<arch>``. Inject boots from
    ``_DEFAULT_BOOTS_BY_ARCHETYPE`` unless champ is in
    ``_BOOTSLESS_CHAMPS``. Boots inserted at index 1 (after the 1st
    item) mirroring ``core/build_order.py``.
  * ARAM: same as SR but threshold 3, secondary slot
    ``auto-aram-flavor-<arch>``, boots from same table.

Hand-curated = a variant whose key does NOT start with ``auto-``. The
``loadout_resolver`` treats both equally at fetch time; the
distinction is operator-intent: hand keys survive autogen reruns,
auto keys are regenerated each cycle.

Outputs a partial JSON patch keyed by champion name. The orchestrator
merges patches via ``tools/champion_loadout_handcurate_merge.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAIN = _ROOT / "data" / "champion_loadouts.json"

# Mirrors core/build_order.py at this date (item 164b ship-time).
_DEFAULT_BOOTS_BY_ARCHETYPE = {
    "carry":     "Berserker's Greaves",
    "marksman":  "Berserker's Greaves",
    "adc":       "Berserker's Greaves",
    "dps":       "Berserker's Greaves",
    "bruiser":   "Plated Steelcaps",
    "tank":      "Plated Steelcaps",
    "ehp":       "Plated Steelcaps",
    "hybrid":    "Plated Steelcaps",
    "mage":      "Sorcerer's Shoes",
    "burst":     "Sorcerer's Shoes",
    "assassin":  "Mobility Boots",
    "enchanter": "Ionian Boots of Lucidity",
    "support":   "Ionian Boots of Lucidity",
    "hps":       "Ionian Boots of Lucidity",
    "ability":   "Ionian Boots of Lucidity",
}

_BOOTSLESS_CHAMPS = frozenset({"Yuumi", "Cassiopeia"})

_ARENA_ARCH_FALLBACK = ("carry", "bruiser", "tank", "mage", "assassin", "enchanter")
_SR_ARCH_FALLBACK    = ("bruiser", "mage", "tank", "carry", "assassin", "enchanter")
_ARAM_ARCH_FALLBACK  = ("mage", "carry", "bruiser", "tank", "assassin", "enchanter")


def _hand_variant_count(variants: dict, mode: str) -> int:
    n = 0
    for vk, v in variants.items():
        if vk.startswith("auto-"):
            continue
        if mode in (v.get("modes") or []):
            n += 1
    return n


def _hand_keys_for_mode(variants: dict, mode: str) -> set[str]:
    out = set()
    for vk, v in variants.items():
        if vk.startswith("auto-"):
            continue
        if mode in (v.get("modes") or []):
            out.add(vk)
    return out


def _find_auto_seed(variants: dict, mode: str, slot_hint: str,
                    arch_fallback: tuple[str, ...]) -> tuple[str, dict] | None:
    """Find an auto-mode-slot-arch variant for cloning, prefer slot_hint."""
    # First: try slot_hint with each archetype in fallback order.
    for arch in arch_fallback:
        key = f"auto-{mode}-{slot_hint}-{arch}"
        if key in variants:
            return key, variants[key]
    # Second: any auto-<mode>- variant.
    for vk, v in variants.items():
        if vk.startswith(f"auto-{mode}-"):
            return vk, v
    return None


def _inject_boots_into_items(items: list[str], archetype: str,
                              champion: str) -> list[str]:
    """Mirror core/build_order.py: boots after 1st item, skip bootsless champs."""
    if champion in _BOOTSLESS_CHAMPS:
        return list(items)
    if not items:
        return list(items)
    # Detect existing boots (any of the known names, fuzzy lower-strip match).
    boots_names_lower = {nm.lower() for nm in _DEFAULT_BOOTS_BY_ARCHETYPE.values()}
    boots_extra = {"berserker's greaves", "boots of swiftness", "symbiotic soles",
                   "sorcerer's shoes", "plated steelcaps", "mercury's treads",
                   "mobility boots", "ionian boots of lucidity"}
    boots_names_lower |= boots_extra
    for it in items:
        if (it or "").strip().lower() in boots_names_lower:
            return list(items)  # already present, leave as-is
    boots = _DEFAULT_BOOTS_BY_ARCHETYPE.get(archetype, "Plated Steelcaps")
    out = list(items)
    out.insert(1, boots)
    return out


def _promote_to_hand(seed: dict, *, mode: str, archetype: str,
                     champion: str, inject_boots: bool) -> dict:
    """Clone an auto variant into a hand-curated form."""
    v = deepcopy(seed)
    v.pop("_auto", None)
    v.pop("_archetype", None)
    items = list(v.get("items") or [])
    if inject_boots:
        items = _inject_boots_into_items(items, archetype, champion)
    v["items"] = items
    # Re-label without "(auto)" suffix.
    label = v.get("label") or ""
    if "(auto)" in label:
        v["label"] = label.replace(" (auto)", "").replace("(auto)", "").strip()
    return v


def _hand_key(mode: str, archetype: str) -> str:
    return f"{mode}-{archetype}"


def _current_arena_archetype(champ_entry: dict) -> str | None:
    """Pick the archetype for the Arena hand-promotion."""
    dpm = champ_entry.get("default_per_mode") or {}
    cur = dpm.get("arena") or ""
    if cur and cur.startswith("auto-arena-"):
        # auto-arena-{slot}-{arch}
        parts = cur.split("-", 3)
        if len(parts) == 4:
            return parts[3]
    # Look for the primary slot.
    for vk, v in (champ_entry.get("variants") or {}).items():
        if vk.startswith("auto-arena-primary-"):
            return vk.split("-", 3)[3]
    # Fallback: first arena auto.
    for vk, v in (champ_entry.get("variants") or {}).items():
        if vk.startswith("auto-arena-"):
            return vk.split("-", 3)[3]
    return None


def _pick_secondary_arch(champ_entry: dict, mode: str,
                         exclude_keys: set[str],
                         fallback: tuple[str, ...]) -> str | None:
    """Pick an archetype for the secondary hand-fill that doesn't collide
    with already-existing hand keys."""
    variants = champ_entry.get("variants") or {}
    # Prefer the auto-secondary slot for the mode.
    for arch in fallback:
        if f"{mode}-{arch}" in exclude_keys:
            continue
        seed_key = f"auto-{mode}-secondary-{arch}"
        if seed_key in variants:
            return arch
    # Then auto-flavor.
    for arch in fallback:
        if f"{mode}-{arch}" in exclude_keys:
            continue
        seed_key = f"auto-{mode}-flavor-{arch}"
        if seed_key in variants:
            return arch
    # Then auto-primary if needed (but should usually be the existing default).
    for arch in fallback:
        if f"{mode}-{arch}" in exclude_keys:
            continue
        seed_key = f"auto-{mode}-primary-{arch}"
        if seed_key in variants:
            return arch
    return None


def transform_champion(name: str, champ_entry: dict) -> dict:
    """Compute the per-champ patch entry. Returns {} if no changes needed."""
    out: dict = {"variants": {}, "default_per_mode": {}}
    variants = champ_entry.get("variants") or {}

    # ---- Arena ----
    arena_arch = _current_arena_archetype(champ_entry)
    if arena_arch:
        arena_hand_key = _hand_key("arena", arena_arch)
        arena_hand_existing = _hand_keys_for_mode(variants, "arena")
        if arena_hand_key not in variants:
            seed_lookup = _find_auto_seed(variants, "arena", "primary",
                                           (arena_arch,) + _ARENA_ARCH_FALLBACK)
            if seed_lookup:
                _, seed = seed_lookup
                out["variants"][arena_hand_key] = _promote_to_hand(
                    seed, mode="arena", archetype=arena_arch,
                    champion=name, inject_boots=False)
        # Flip arena default to the hand key (even if hand key already exists).
        cur_arena_default = (champ_entry.get("default_per_mode") or {}).get("arena")
        if cur_arena_default != arena_hand_key:
            out["default_per_mode"]["arena"] = arena_hand_key

    # ---- SR ----
    sr_hand_count = _hand_variant_count(variants, "sr")
    if sr_hand_count < 2:
        sr_hand_existing = _hand_keys_for_mode(variants, "sr")
        secondary_arch = _pick_secondary_arch(champ_entry, "sr",
                                               sr_hand_existing,
                                               _SR_ARCH_FALLBACK)
        if secondary_arch:
            seed_lookup = (
                _find_auto_seed(variants, "sr", "secondary", (secondary_arch,))
                or _find_auto_seed(variants, "sr", "flavor", (secondary_arch,))
                or _find_auto_seed(variants, "sr", "primary", (secondary_arch,))
            )
            if seed_lookup:
                _, seed = seed_lookup
                key = _hand_key("sr", secondary_arch)
                if key not in variants:
                    out["variants"][key] = _promote_to_hand(
                        seed, mode="sr", archetype=secondary_arch,
                        champion=name, inject_boots=True)

    # ---- ARAM ----
    aram_hand_count = _hand_variant_count(variants, "aram")
    if aram_hand_count < 3:
        aram_hand_existing = _hand_keys_for_mode(variants, "aram")
        third_arch = _pick_secondary_arch(champ_entry, "aram",
                                           aram_hand_existing,
                                           _ARAM_ARCH_FALLBACK)
        if third_arch:
            seed_lookup = (
                _find_auto_seed(variants, "aram", "flavor", (third_arch,))
                or _find_auto_seed(variants, "aram", "secondary", (third_arch,))
                or _find_auto_seed(variants, "aram", "primary", (third_arch,))
            )
            if seed_lookup:
                _, seed = seed_lookup
                key = _hand_key("aram", third_arch)
                if key not in variants:
                    out["variants"][key] = _promote_to_hand(
                        seed, mode="aram", archetype=third_arch,
                        champion=name, inject_boots=True)

    if not out["variants"] and not out["default_per_mode"]:
        return {}
    if not out["variants"]:
        del out["variants"]
    if not out["default_per_mode"]:
        del out["default_per_mode"]
    return out


def build_patch(champ_names: list[str]) -> dict:
    with _MAIN.open("r", encoding="utf-8") as f:
        base = json.load(f)
    champs = base.get("champions") or {}
    patch_champs: dict = {}
    for nm in champ_names:
        if nm not in champs:
            print(f"WARN: not in base: {nm}", file=sys.stderr)
            continue
        delta = transform_champion(nm, champs[nm])
        if delta:
            patch_champs[nm] = delta
    return {
        "_schema_version": 1,
        "_doc": [
            "Item 166 hand-curate patch slice.",
            "Generated by tools/champion_loadout_handcurate.py.",
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
                        "data/champion_loadouts_patch_<slice>.json")
    args = p.parse_args(argv)
    names = [c.strip() for c in args.champs.split(",") if c.strip()]
    if not names:
        print("no champion names supplied", file=sys.stderr)
        return 1
    out_path = (Path(args.out) if args.out
                else _ROOT / "data" / f"champion_loadouts_patch_{args.slice}.json")
    patch = build_patch(names)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(patch, f, indent=2, ensure_ascii=True)
        f.write("\n")
    n = len(patch["champions"])
    v = sum(len(e.get("variants") or {}) for e in patch["champions"].values())
    d = sum(len(e.get("default_per_mode") or {}) for e in patch["champions"].values())
    print(f"slice={args.slice} champs_touched={n} variants_added={v} defaults_flipped={d}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
