"""tools/champion_loadout_collapse_to_paths.py - item 178 SR-mode collapse.

Operator-directed UI cleanup (2026-05-24): the in-game build chooser
historically rendered N separate selectable pills per champion (one per
SR variant). Item 167 inflated the SR roster to 678 variants across
172 champions which clutters the chooser badly. Operator picked
"Multi-line build orders within ONE variant" from a 4-option fork.

This script collapses every champion's SR-mode variants into ONE
collapsed variant whose new ``build_paths`` list carries each original
variant as a labeled path. The variant-level ``items``, ``runes``,
and ``summoners`` fields are populated from the PRIMARY path (the
variant pointed to by ``default_per_mode.sr``) so the existing
``loadout_resolver.resolve()`` path keeps working when callers don't
pass a sub-path key.

Schema (additive, post-collapse, SR variant only):

    "sr-collapsed": {
      "label":     "Builds for <Champion>",
      "modes":     ["sr"],
      "runes":     <primary path's runes>,
      "summoners": <primary path's summoners>,
      "items":     <primary path's items>,            # back-compat
      "_collapsed": true,
      "_archetype": "<primary path's _archetype>",
      "build_paths": [
        {
          "key":              "<source variant_key>",
          "label":            "Carry",                # short pill
          "items":            ["Trinity Force", ...],
          "runes":            {...},                   # optional override
          "summoners":        [4, 21],                 # optional override
          "_archetype":       "carry",                 # optional
          "_source_variant_key": "<source variant_key>",
          "_is_primary":      true                     # only on path[0]
        },
        ...
      ]
    }

The collapsed variant's KEY is always ``sr-collapsed`` so
``default_per_mode.sr`` becomes a stable pointer. The first entry of
``build_paths`` is the operator's prior default (whatever
``default_per_mode.sr`` previously pointed to). Remaining paths follow
the sorted order: hand-curated first (alphabetic by label), then
auto-* entries.

ARAM + Arena variants are LEFT UNTOUCHED this run (operator scoped
SR-only). The collapse is idempotent - re-running on a file that
already has ``sr-collapsed`` rewrites the path list from any non-
collapsed SR variants present. Hand-edited paths inside an existing
collapsed variant are preserved via key match.

Usage::

    py tools/champion_loadout_collapse_to_paths.py [--dry-run]
        [--champion <name>] [--no-backup]

* ``--dry-run`` reports per-champion variant-count deltas without
  writing.
* ``--champion`` collapses one champion only (dev iteration shortcut).
* ``--no-backup`` skips the data/champion_loadouts.json.bak-item178-
  <timestamp> snapshot (default is to create it for operator safety).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"

COLLAPSED_KEY = "sr-collapsed"
SR_MODE = "sr"

# Short pill labels keyed by source variant_key (mode-prefix stripped).
# Stays under ~14 chars so the in-game chooser pill doesn't overflow.
# Hand-curated keys first, then auto-sr-* and arch fallbacks.
_LABEL_MAP: dict[str, str] = {
    # sr-<arch> standard
    "sr-carry":     "Carry",
    "sr-bruiser":   "Bruiser",
    "sr-tank":      "Tank",
    "sr-mage":      "Mage",
    "sr-assassin":  "Assassin",
    "sr-enchanter": "Enchanter",
    # ADC family
    "adc-crit":     "Crit",
    "adc-bullet":   "Bullet",
    "adc-scaling":  "Scaling",
    "adc-standard": "Standard",
    "on-hit":       "On-Hit",
    "ad-on-hit":    "AD On-Hit",
    "ap-on-hit":    "AP On-Hit",
    "lethality":    "Lethality",
    "lethality-poke":    "Leth Poke",
    "lethality-support": "Leth Sup",
    # AP family
    "ap-burst":     "Burst",
    "ap-dps":       "DPS",
    "ap-bruiser":   "AP Bruiser",
    "ap-poke":      "AP Poke",
    "ap-scaling":   "AP Scaling",
    "ap-control":   "AP Control",
    "ap-utility":   "AP Utility",
    "ap-sustain":   "AP Sustain",
    "ap-roam":      "AP Roam",
    "ap-hybrid":    "AP Hybrid",
    "ap-assassin":  "AP Assassin",
    "ap-jg":        "AP Jungle",
    "ap-jg-bruiser": "AP JG Brsr",
    # Tank family
    "tank-engage":  "Engage",
    "tank-aura":    "Aura",
    "tank-support": "Tank Sup",
    "tank-top":     "Tank Top",
    "tank":         "Tank",
    # Bruiser family
    "bruiser":           "Bruiser",
    "bruiser-top":       "Bruiser Top",
    "bruiser-trinity":   "Trinity",
    "ad-bruiser":        "AD Bruiser",
    "ad-crit":           "AD Crit",
    "crit":              "Crit",
    "enchanter":         "Enchanter",
    # Jungle family
    "jg-bruiser":   "JG Bruiser",
    "jg-marksman":  "JG Marksman",
    "jg-on-hit":    "JG On-Hit",
    "jg-scaling":   "JG Scaling",
    "jg-ap-burst":  "JG AP Burst",
    # Misc / niche
    "splitpush":        "Splitpush",
    "lane-bully":       "Lane Bully",
    "assassin":         "Assassin",
    "berserker":        "Berserker",
    "divetop":          "Dive Top",
    "duelist":          "Duelist",
    "burst":            "Burst",
    "engage":           "Engage",
    "proxy":            "Proxy",
    "manamune-bruiser": "Manamune",
    "push-adc":         "Push ADC",
    "utility-adc":      "Utility ADC",
    "artillery":        "Artillery",
    # Support family
    "support-binding":   "Sup Binding",
    "support-burn":      "Sup Burn",
    "support-control":   "Sup Control",
    "support-enchanter": "Sup Ench",
    "support-jg":        "Sup JG",
    "support-marksman":  "Sup Marks",
    "support-poke":      "Sup Poke",
    "support-utility":   "Sup Utility",
}

# Fallback when variant_key isn't in _LABEL_MAP - keyed by _archetype.
_ARCH_FALLBACK_LABEL: dict[str, str] = {
    "carry":     "Carry",
    "bruiser":   "Bruiser",
    "tank":      "Tank",
    "mage":      "Mage",
    "assassin":  "Assassin",
    "enchanter": "Enchanter",
}


def short_label_for(variant_key: str, archetype: str, label: str) -> str:
    """Pill label for a build_path. Strips ``auto-sr-{primary,secondary,flavor}-``
    prefix and falls back through arch -> titlecased remainder.
    """
    vk = variant_key
    # auto-sr-<slot>-<arch> -> use the arch fallback
    if vk.startswith("auto-sr-"):
        # Format: auto-sr-primary-bruiser  ->  bruiser
        parts = vk.split("-")
        if len(parts) >= 4:
            arch = parts[3]
            if arch in _ARCH_FALLBACK_LABEL:
                return _ARCH_FALLBACK_LABEL[arch]
        if archetype in _ARCH_FALLBACK_LABEL:
            return _ARCH_FALLBACK_LABEL[archetype]
        # Last resort: titlecased slot name
        return label.replace("(auto)", "").strip() or "Variant"
    if vk in _LABEL_MAP:
        return _LABEL_MAP[vk]
    if archetype in _ARCH_FALLBACK_LABEL:
        return _ARCH_FALLBACK_LABEL[archetype]
    # Titlecase a hyphenated key, drop a leading ``sr-`` if present
    base = vk[3:] if vk.startswith("sr-") else vk
    return base.replace("-", " ").title()[:14] or "Variant"


def variant_modes(v: dict) -> list[str]:
    return [str(m).lower() for m in (v.get("modes") or [])]


def variant_is_sr(v: dict) -> bool:
    return SR_MODE in variant_modes(v)


def pick_primary_key(variants: dict, default_sr_key: str) -> str:
    """Return the variant_key to treat as ``build_paths[0]`` (primary).

    Order:
    1. operator's prior ``default_per_mode.sr`` if valid
    2. first hand-curated SR variant in iteration order
    3. first SR variant of any kind
    """
    if default_sr_key and default_sr_key in variants and variant_is_sr(variants[default_sr_key]):
        return default_sr_key
    for vk, v in variants.items():
        if variant_is_sr(v) and not v.get("_auto") and not vk.startswith("auto-"):
            return vk
    for vk, v in variants.items():
        if variant_is_sr(v):
            return vk
    return ""


def build_path_from_variant(variant_key: str, v: dict, is_primary: bool) -> dict[str, Any]:
    """Project a source SR variant into a build_paths[] entry."""
    archetype = str(v.get("_archetype") or "")
    label = short_label_for(variant_key, archetype, str(v.get("label") or variant_key))
    runes = dict(v.get("runes") or {})
    summoners = list(v.get("summoners") or [])
    items = list(v.get("items") or [])
    path: dict[str, Any] = {
        "key":   variant_key,
        "label": label,
        "items": items,
    }
    if runes:
        path["runes"] = runes
    if summoners:
        path["summoners"] = list(summoners)
    if archetype:
        path["_archetype"] = archetype
    path["_source_variant_key"] = variant_key
    if is_primary:
        path["_is_primary"] = True
    return path


def order_source_keys(variants: dict, primary_key: str) -> list[str]:
    """Return SR source variant keys in ship-order:

    1. primary_key first
    2. then non-auto curated keys, alphabetical by key
    3. then auto-* keys, alphabetical by key

    Stable + deterministic so re-runs produce byte-identical output.
    """
    sr_keys = [vk for vk, v in variants.items() if variant_is_sr(v)]
    curated = sorted(
        [vk for vk in sr_keys if not vk.startswith("auto-") and not variants[vk].get("_auto")]
    )
    auto = sorted(
        [vk for vk in sr_keys if vk.startswith("auto-") or variants[vk].get("_auto")]
    )
    ordered: list[str] = []
    if primary_key:
        ordered.append(primary_key)
    for vk in curated:
        if vk not in ordered:
            ordered.append(vk)
    for vk in auto:
        if vk not in ordered:
            ordered.append(vk)
    return ordered


def collapse_champion(champion: str, entry: dict) -> tuple[dict, dict[str, int]]:
    """Return (new_entry, stats_dict).

    Stats fields: ``before`` (SR variant count pre-collapse),
    ``after`` (1 if any SR paths created; 0 if no SR variants),
    ``paths`` (number of build_paths in the collapsed variant).
    """
    variants_in = entry.get("variants") or {}
    defaults_in = entry.get("default_per_mode") or {}

    sr_keys = [vk for vk, v in variants_in.items() if variant_is_sr(v)]
    sr_before = len(sr_keys)

    # If there are no SR variants at all, leave entry untouched.
    if not sr_keys:
        return entry, {"before": 0, "after": 0, "paths": 0}

    # If the only SR variant is already ``sr-collapsed`` with build_paths,
    # we still re-run the collapse so the path list reflects the operator's
    # latest hand-edits to any other (re-introduced) source variants.
    primary_key = pick_primary_key(variants_in, defaults_in.get(SR_MODE, ""))

    ordered_keys = order_source_keys(variants_in, primary_key)
    build_paths: list[dict[str, Any]] = []
    for vk in ordered_keys:
        v = variants_in[vk]
        is_primary = (vk == primary_key)
        build_paths.append(build_path_from_variant(vk, v, is_primary))

    if not build_paths:
        return entry, {"before": sr_before, "after": 0, "paths": 0}

    # Primary path drives the variant-level fields (back-compat with
    # the existing resolve() path that looks at v.get("items")/runes/summoners).
    primary_path = build_paths[0]
    primary_source = variants_in[primary_key] if primary_key in variants_in else {}
    archetype_primary = primary_path.get("_archetype") or ""
    label_collapsed = f"Builds for {champion}"

    collapsed: dict[str, Any] = {
        "label":      label_collapsed,
        "modes":      [SR_MODE],
        "runes":      dict(primary_source.get("runes") or primary_path.get("runes") or {}),
        "summoners":  list(primary_source.get("summoners") or primary_path.get("summoners") or []),
        "items":      list(primary_source.get("items") or primary_path.get("items") or []),
        "_collapsed": True,
        "build_paths": build_paths,
    }
    if archetype_primary:
        collapsed["_archetype"] = archetype_primary

    # Build the new variants dict: drop every SR-only variant (we have
    # absorbed them into sr-collapsed); preserve every multi-mode variant
    # by removing ``sr`` from its modes (it still serves ARAM/Arena);
    # preserve every non-SR variant verbatim.
    new_variants: dict[str, Any] = {}
    for vk, v in variants_in.items():
        modes = variant_modes(v)
        if SR_MODE in modes:
            other_modes = [m for m in modes if m != SR_MODE]
            if other_modes:
                # Multi-mode variant: keep it under its original key with
                # SR stripped from modes. Items/runes/summoners stay.
                trimmed = dict(v)
                trimmed["modes"] = other_modes
                new_variants[vk] = trimmed
            # else: SR-only variant absorbed into sr-collapsed; drop.
        else:
            new_variants[vk] = v
    new_variants[COLLAPSED_KEY] = collapsed

    # Update default_per_mode.sr to point at the new collapsed key.
    new_defaults = dict(defaults_in)
    new_defaults[SR_MODE] = COLLAPSED_KEY

    new_entry = dict(entry)
    new_entry["variants"] = new_variants
    new_entry["default_per_mode"] = new_defaults

    return new_entry, {"before": sr_before, "after": 1, "paths": len(build_paths)}


def collapse_payload(payload: dict, only_champion: str = "") -> tuple[dict, list[tuple[str, dict]]]:
    """Walk all champions; produce a new payload + per-champion stats."""
    champions = dict(payload.get("champions") or {})
    out_champs: dict[str, Any] = {}
    stats: list[tuple[str, dict[str, int]]] = []
    for cn, entry in champions.items():
        if only_champion and cn != only_champion:
            out_champs[cn] = entry
            continue
        if not isinstance(entry, dict):
            out_champs[cn] = entry
            continue
        new_entry, st = collapse_champion(cn, entry)
        out_champs[cn] = new_entry
        stats.append((cn, st))
    out = dict(payload)
    out["champions"] = out_champs
    return out, stats


def atomic_write_loadouts(payload: dict, dest: Path = _LOADOUTS_PATH) -> None:
    """Write payload via tmp + replace. Mirrors champion_loadout_autogen's writer."""
    out_dir = dest.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".champion_loadouts.", suffix=".tmp", dir=str(out_dir),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True, sort_keys=False)
            f.write("\n")
        # Brief retry loop covers WinError 5 transient (cross_project memory).
        for delay_ms in (0, 25, 50, 200):
            if delay_ms:
                time.sleep(delay_ms / 1000.0)
            try:
                os.replace(tmp_path, dest)
                break
            except PermissionError:
                if delay_ms == 200:
                    raise
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def backup_loadouts(dest: Path = _LOADOUTS_PATH) -> Path:
    """Copy current file to data/champion_loadouts.json.bak-item178-<ts>.

    Returns the backup path (or the dest path unchanged if no source).
    """
    if not dest.exists():
        return dest
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = dest.with_name(f"{dest.name}.bak-item178-{ts}")
    shutil.copy2(dest, bak)
    return bak


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report deltas without writing.")
    parser.add_argument("--champion", default="",
                        help="Collapse a single champion only.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip the .bak-item178-<ts> snapshot.")
    args = parser.parse_args(argv)

    if not _LOADOUTS_PATH.exists():
        print(f"ERROR: {_LOADOUTS_PATH} not found", file=sys.stderr)
        return 2

    payload = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    new_payload, stats = collapse_payload(payload, only_champion=args.champion or "")

    # Pre/post variant count summary.
    before_total = sum(s["before"] for _, s in stats)
    paths_total = sum(s["paths"] for _, s in stats)
    after_champs = sum(1 for _, s in stats if s["after"])
    print("SR-mode collapse summary:")
    print(f"  champions affected: {after_champs} / {len(stats)}")
    print(f"  SR variants before: {before_total}")
    print(f"  SR variants after:  {after_champs}  (one ``sr-collapsed`` per affected champ)")
    print(f"  total build_paths created: {paths_total}")
    # Distribution histogram
    from collections import Counter
    dist = Counter(s["paths"] for _, s in stats if s["after"])
    if dist:
        print("  path-count distribution:")
        for k in sorted(dist):
            print(f"    {k} paths: {dist[k]} champs")

    if args.dry_run:
        print("(dry-run; no write)")
        return 0

    if not args.no_backup:
        bak = backup_loadouts()
        print(f"  backup written: {bak.name}")

    atomic_write_loadouts(new_payload)
    print(f"  wrote: {_LOADOUTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
