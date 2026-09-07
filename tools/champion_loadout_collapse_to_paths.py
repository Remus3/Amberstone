"""tools/champion_loadout_collapse_to_paths.py - per-mode variant collapse.

Operator-directed UI cleanup. The in-game build chooser historically
rendered N separate selectable pills per champion (one per per-mode
variant). For SR this hit 678 variants across 172 champions which
cluttered the chooser badly; ARAM (685 variants) and Arena (688
variants) followed the same pattern.

Item 178 (2026-05-24) collapsed SR-mode variants into ONE
``sr-collapsed`` per champion carrying a labeled ``build_paths`` list.
Item 179 (2026-05-24) extends the same collapse to ARAM + Arena via
the ``--mode`` flag, producing ``aram-collapsed`` + ``arena-collapsed``
parallels. The variant-level ``items`` / ``runes`` / ``summoners``
fields on the collapsed entry are populated from the PRIMARY path
(the variant pointed to by ``default_per_mode.<mode>``) so the
existing ``loadout_resolver.resolve()`` path keeps working when
callers don't pass a sub-path key.

Schema (additive, post-collapse, per mode):

    "<mode>-collapsed": {
      "label":     "Builds for <Champion>",
      "modes":     ["<mode>"],
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

The collapsed variant's KEY is always ``<mode>-collapsed`` so
``default_per_mode.<mode>`` becomes a stable pointer. The first entry
of ``build_paths`` is the operator's prior default (whatever
``default_per_mode.<mode>`` previously pointed to). Remaining paths
follow the sorted order: hand-curated first (alphabetic by key), then
auto-* entries.

Collapse is per-mode + idempotent. Re-running on a file whose target
mode is already collapsed re-walks any non-collapsed source variants
that may have been re-introduced and rebuilds the path list
deterministically. Running ``--mode aram`` does NOT perturb SR's
sr-collapsed or Arena's per-variant entries (multi-mode isolation).

Usage::

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/champion_loadout_collapse_to_paths.py [--dry-run]
        [--champion <name>] [--no-backup]
        [--mode <sr|aram|arena|all>]

* ``--dry-run`` reports per-champion variant-count deltas without
  writing.
* ``--champion`` collapses one champion only (dev iteration shortcut).
* ``--no-backup`` skips the data/champion_loadouts.json.bak-itemNNN-
  <timestamp> snapshot (default is to create it for operator safety).
* ``--mode`` selects which mode(s) to collapse (default ``sr`` for
  item-178 CLI compatibility; pass ``all`` for the item-179 SR+ARAM+
  Arena pass).
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

SR_MODE = "sr"
ARAM_MODE = "aram"
ARENA_MODE = "arena"
ALL_MODES = (SR_MODE, ARAM_MODE, ARENA_MODE)


def collapsed_key_for(mode: str) -> str:
    """Return the canonical collapsed variant key for a mode."""
    return f"{mode}-collapsed"


# Item 178 carry: SR collapsed key constant for back-compat with tests
# + downstream imports.
COLLAPSED_KEY = collapsed_key_for(SR_MODE)

# Short pill labels keyed by source variant_key. Stays under ~14 chars
# so the in-game chooser pill doesn't overflow. Hand-curated keys first,
# then mode-prefixed standards, then arch fallbacks.
_LABEL_MAP: dict[str, str] = {
    # sr-<arch> standard (item 178)
    "sr-carry":     "Carry",
    "sr-bruiser":   "Bruiser",
    "sr-tank":      "Tank",
    "sr-mage":      "Mage",
    "sr-assassin":  "Assassin",
    "sr-enchanter": "Enchanter",
    # aram-<arch> standard (item 179)
    "aram-carry":     "Carry",
    "aram-bruiser":   "Bruiser",
    "aram-tank":      "Tank",
    "aram-mage":      "Mage",
    "aram-assassin":  "Assassin",
    "aram-enchanter": "Enchanter",
    # arena-<arch> standard (item 179)
    "arena-carry":     "Carry",
    "arena-bruiser":   "Bruiser",
    "arena-tank":      "Tank",
    "arena-mage":      "Mage",
    "arena-assassin":  "Assassin",
    "arena-enchanter": "Enchanter",
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
    "lethal-poke":       "Leth Poke",
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
    "ap-bombs":     "AP Bombs",
    "ap-tank":      "AP Tank",
    # Tank family
    "tank-engage":  "Engage",
    "tank-aura":    "Aura",
    "tank-support": "Tank Sup",
    "tank-top":     "Tank Top",
    "tank-aram":    "Tank ARAM",
    "tank-poke":    "Tank Poke",
    "tank-veigar":  "Tank Veigar",
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

# Slot disambiguator suffixes for auto-<mode>-<slot>-<arch> keys. Item
# 179 picked these because Arena has the most auto-* variants per champ
# (up to 5 across primary/secondary/flavor slots) and the slot identity
# helps the operator distinguish three auto-recs that share an arch
# label. SR + ARAM only have primary slots so slot suffixes are inert
# for them.
_AUTO_SLOT_SUFFIX: dict[str, str] = {
    "primary":   "",          # no suffix; primary is the default presentation
    "secondary": " (sec)",
    "flavor":    " (flav)",
}


def short_label_for(variant_key: str, archetype: str, label: str) -> str:
    """Pill label for a build_path. Strips ``auto-<mode>-{primary,secondary,flavor}-``
    prefix and falls back through arch -> titlecased remainder.

    Item 179: only ``auto-arena-`` gets a slot disambiguator suffix
    (Arena has primary + secondary + flavor slots populated in real
    data so the operator might see 3+ pills sharing an arch). SR + ARAM
    only have primary slots in the live data, so the slot suffix would
    just be noise; item 178's contract for SR auto-* (no suffix) is
    preserved verbatim.
    """
    vk = variant_key
    # auto-arena-<slot>-<arch> - arch base + optional slot suffix.
    if vk.startswith("auto-arena-"):
        parts = vk.split("-")
        if len(parts) >= 4:
            slot = parts[2]
            arch = parts[3]
            base = _ARCH_FALLBACK_LABEL.get(arch, arch.title())
            suffix = _AUTO_SLOT_SUFFIX.get(slot, f" ({slot[:4]})")
            return (base + suffix)[:16]
        if archetype in _ARCH_FALLBACK_LABEL:
            return _ARCH_FALLBACK_LABEL[archetype]
        return label.replace("(auto)", "").strip() or "Variant"
    # auto-sr-* / auto-aram-* - arch base only (no slot disambiguator).
    if vk.startswith("auto-sr-") or vk.startswith("auto-aram-"):
        parts = vk.split("-")
        if len(parts) >= 4:
            arch = parts[3]
            if arch in _ARCH_FALLBACK_LABEL:
                return _ARCH_FALLBACK_LABEL[arch]
        if archetype in _ARCH_FALLBACK_LABEL:
            return _ARCH_FALLBACK_LABEL[archetype]
        return label.replace("(auto)", "").strip() or "Variant"
    if vk in _LABEL_MAP:
        return _LABEL_MAP[vk]
    if archetype in _ARCH_FALLBACK_LABEL:
        return _ARCH_FALLBACK_LABEL[archetype]
    # Titlecase a hyphenated key, drop a leading mode prefix if present.
    base = vk
    for prefix in ("sr-", "aram-", "arena-"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    return base.replace("-", " ").title()[:14] or "Variant"


def variant_modes(v: dict) -> list[str]:
    return [str(m).lower() for m in (v.get("modes") or [])]


def variant_is_mode(v: dict, mode: str) -> bool:
    return mode in variant_modes(v)


def pick_primary_key(variants: dict, default_key: str, mode: str = SR_MODE) -> str:
    """Return the variant_key to treat as ``build_paths[0]`` (primary).

    Order:
    1. operator's prior ``default_per_mode.<mode>`` if valid + still
       in this mode
    2. first hand-curated variant in iteration order
    3. first variant of any kind in this mode
    """
    if default_key and default_key in variants and variant_is_mode(variants[default_key], mode):
        # If the prior default already points at the collapsed key, fall
        # through so we re-pick a real source variant (idempotent
        # collapse on already-collapsed input).
        if default_key != collapsed_key_for(mode):
            return default_key
    for vk, v in variants.items():
        if vk == collapsed_key_for(mode):
            continue
        if variant_is_mode(v, mode) and not v.get("_auto") and not vk.startswith("auto-"):
            return vk
    for vk, v in variants.items():
        if vk == collapsed_key_for(mode):
            continue
        if variant_is_mode(v, mode):
            return vk
    # Final fallback: if only the collapsed key remains, return it so we
    # can re-derive primary from build_paths[0] (re-collapse idempotency).
    if collapsed_key_for(mode) in variants and variant_is_mode(variants[collapsed_key_for(mode)], mode):
        return collapsed_key_for(mode)
    return ""


def build_path_from_variant(variant_key: str, v: dict, is_primary: bool) -> dict[str, Any]:
    """Project a source variant into a build_paths[] entry."""
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


def order_source_keys(variants: dict, primary_key: str, mode: str = SR_MODE) -> list[str]:
    """Return mode-scoped source variant keys in ship-order:

    1. primary_key first
    2. then non-auto curated keys, alphabetical by key
    3. then auto-* keys, alphabetical by key

    Stable + deterministic so re-runs produce byte-identical output.
    Excludes the collapsed key itself (we never re-absorb the collapsed
    pseudo-variant into its own build_paths).
    """
    ck = collapsed_key_for(mode)
    mode_keys = [vk for vk, v in variants.items()
                 if variant_is_mode(v, mode) and vk != ck]
    curated = sorted(
        [vk for vk in mode_keys if not vk.startswith("auto-") and not variants[vk].get("_auto")]
    )
    auto = sorted(
        [vk for vk in mode_keys if vk.startswith("auto-") or variants[vk].get("_auto")]
    )
    ordered: list[str] = []
    if primary_key and primary_key != ck:
        ordered.append(primary_key)
    for vk in curated:
        if vk not in ordered:
            ordered.append(vk)
    for vk in auto:
        if vk not in ordered:
            ordered.append(vk)
    return ordered


def _rebuild_paths_from_collapsed(collapsed: dict) -> list[dict[str, Any]]:
    """Idempotent helper: when re-collapsing an already-collapsed entry
    with NO other source variants in the target mode, derive build_paths
    from the existing collapsed['build_paths'] verbatim. Preserves
    operator hand-edits to individual paths across re-runs.
    """
    paths = collapsed.get("build_paths") or []
    if not isinstance(paths, list):
        return []
    out: list[dict[str, Any]] = []
    for i, p in enumerate(paths):
        if not isinstance(p, dict):
            continue
        copy = dict(p)
        # Re-stamp _is_primary on path[0] (drop on others) so re-runs
        # re-anchor the primary cleanly.
        if i == 0:
            copy["_is_primary"] = True
        else:
            copy.pop("_is_primary", None)
        out.append(copy)
    return out


def collapse_champion(champion: str, entry: dict, mode: str = SR_MODE) -> tuple[dict, dict[str, int]]:
    """Return (new_entry, stats_dict) for ONE mode collapse.

    Stats fields: ``before`` (mode variant count pre-collapse, NOT
    counting the collapsed key itself if already present), ``after``
    (1 if any mode paths created; 0 if no mode variants), ``paths``
    (number of build_paths in the collapsed variant).
    """
    variants_in = entry.get("variants") or {}
    defaults_in = entry.get("default_per_mode") or {}
    ck = collapsed_key_for(mode)

    mode_keys_all = [vk for vk, v in variants_in.items() if variant_is_mode(v, mode)]
    source_keys = [vk for vk in mode_keys_all if vk != ck]
    mode_before = len(source_keys)
    already_collapsed = ck in variants_in and variant_is_mode(variants_in[ck], mode)

    # If there are no mode variants AT ALL (not even an existing
    # collapsed entry), leave entry untouched.
    if not mode_keys_all:
        return entry, {"before": 0, "after": 0, "paths": 0}

    primary_key = pick_primary_key(variants_in, defaults_in.get(mode, ""), mode=mode)

    # Idempotent re-run: if only the collapsed key is in this mode +
    # there are no other source variants, preserve the existing
    # build_paths verbatim (operator-edited paths survive).
    if already_collapsed and not source_keys:
        existing = variants_in[ck]
        build_paths = _rebuild_paths_from_collapsed(existing)
    else:
        ordered_keys = order_source_keys(variants_in, primary_key, mode=mode)
        build_paths = []
        for vk in ordered_keys:
            v = variants_in[vk]
            is_primary = (vk == primary_key)
            build_paths.append(build_path_from_variant(vk, v, is_primary))

    if not build_paths:
        return entry, {"before": mode_before, "after": 0, "paths": 0}

    # Primary path drives the variant-level fields (back-compat with
    # the existing resolve() path that looks at v.get("items")/runes/summoners).
    primary_path = build_paths[0]
    if primary_key and primary_key in variants_in and primary_key != ck:
        primary_source = variants_in[primary_key]
    else:
        primary_source = {}
    archetype_primary = primary_path.get("_archetype") or ""
    label_collapsed = f"Builds for {champion}"

    collapsed: dict[str, Any] = {
        "label":      label_collapsed,
        "modes":      [mode],
        "runes":      dict(primary_source.get("runes") or primary_path.get("runes") or {}),
        "summoners":  list(primary_source.get("summoners") or primary_path.get("summoners") or []),
        "items":      list(primary_source.get("items") or primary_path.get("items") or []),
        "_collapsed": True,
        "build_paths": build_paths,
    }
    if archetype_primary:
        collapsed["_archetype"] = archetype_primary

    # Build the new variants dict: drop every mode-only source variant
    # (we have absorbed them into <mode>-collapsed); preserve every
    # multi-mode source variant by removing the target mode from its
    # modes (it still serves other modes); preserve every non-mode
    # variant verbatim; preserve any OTHER mode's collapsed entries.
    new_variants: dict[str, Any] = {}
    for vk, v in variants_in.items():
        if vk == ck:
            # The pre-existing collapsed key gets replaced by the new
            # collapsed dict below; skip.
            continue
        modes = variant_modes(v)
        if mode in modes:
            other_modes = [m for m in modes if m != mode]
            if other_modes:
                # Multi-mode variant: keep it under its original key
                # with the target mode stripped. Items/runes/summoners
                # stay so other modes still resolve via this entry.
                trimmed = dict(v)
                trimmed["modes"] = other_modes
                new_variants[vk] = trimmed
            # else: mode-only variant absorbed into <mode>-collapsed; drop.
        else:
            new_variants[vk] = v
    new_variants[ck] = collapsed

    # Update default_per_mode.<mode> to point at the new collapsed key.
    new_defaults = dict(defaults_in)
    new_defaults[mode] = ck

    new_entry = dict(entry)
    new_entry["variants"] = new_variants
    new_entry["default_per_mode"] = new_defaults

    return new_entry, {"before": mode_before, "after": 1, "paths": len(build_paths)}


def collapse_payload(
    payload: dict,
    only_champion: str = "",
    mode: str = SR_MODE,
) -> tuple[dict, list[tuple[str, dict[str, int]]]]:
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
        new_entry, st = collapse_champion(cn, entry, mode=mode)
        out_champs[cn] = new_entry
        stats.append((cn, st))
    out = dict(payload)
    out["champions"] = out_champs
    return out, stats


def collapse_payload_modes(
    payload: dict,
    modes: tuple[str, ...],
    only_champion: str = "",
) -> tuple[dict, dict[str, list[tuple[str, dict[str, int]]]]]:
    """Run collapse_payload sequentially across a tuple of modes.

    Returns (final_payload, per-mode-stats). Mode order matters only
    for the print summary; the per-mode passes are independent (each
    pass only touches variants with the target mode in their modes
    list, and the collapsed entries from prior modes are preserved
    via the non-target-mode branch in collapse_champion).
    """
    cur = payload
    per_mode: dict[str, list[tuple[str, dict[str, int]]]] = {}
    for m in modes:
        cur, stats = collapse_payload(cur, only_champion=only_champion, mode=m)
        per_mode[m] = stats
    return cur, per_mode


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


def backup_loadouts(dest: Path = _LOADOUTS_PATH, item_tag: str = "item178") -> Path:
    """Copy current file to data/champion_loadouts.json.bak-<item_tag>-<ts>.

    Returns the backup path (or the dest path unchanged if no source).
    The ``item_tag`` parameter lets the caller stamp the run with the
    ledger item number (item178 = SR-only, item179 = SR+ARAM+Arena).
    """
    if not dest.exists():
        return dest
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = dest.with_name(f"{dest.name}.bak-{item_tag}-{ts}")
    shutil.copy2(dest, bak)
    return bak


def _resolve_modes_arg(arg: str) -> tuple[str, ...]:
    """Parse the --mode flag into an ordered tuple of modes."""
    a = (arg or "").strip().lower()
    if a == "all":
        return ALL_MODES
    if a in ALL_MODES:
        return (a,)
    raise ValueError(f"invalid --mode value: {arg!r} (expected sr|aram|arena|all)")


def _print_mode_summary(mode: str, stats: list[tuple[str, dict[str, int]]]) -> None:
    before_total = sum(s["before"] for _, s in stats)
    paths_total = sum(s["paths"] for _, s in stats)
    after_champs = sum(1 for _, s in stats if s["after"])
    print(f"{mode.upper()}-mode collapse summary:")
    print(f"  champions affected: {after_champs} / {len(stats)}")
    print(f"  {mode} variants before: {before_total}")
    print(f"  {mode} variants after:  {after_champs}  (one ``{collapsed_key_for(mode)}`` per affected champ)")
    print(f"  total build_paths created: {paths_total}")
    from collections import Counter
    dist = Counter(s["paths"] for _, s in stats if s["after"])
    if dist:
        print("  path-count distribution:")
        for k in sorted(dist):
            print(f"    {k} paths: {dist[k]} champs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report deltas without writing.")
    parser.add_argument("--champion", default="",
                        help="Collapse a single champion only.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip the .bak-itemNNN-<ts> snapshot.")
    parser.add_argument("--mode", default=SR_MODE,
                        choices=[SR_MODE, ARAM_MODE, ARENA_MODE, "all"],
                        help="Which mode(s) to collapse (default sr; "
                             "use 'all' for SR+ARAM+Arena).")
    parser.add_argument("--item-tag", default="",
                        help="Backup filename ledger-item tag "
                             "(default: item178 for sr-only, item179 for "
                             "aram/arena/all).")
    args = parser.parse_args(argv)

    if not _LOADOUTS_PATH.exists():
        print(f"ERROR: {_LOADOUTS_PATH} not found", file=sys.stderr)
        return 2

    modes = _resolve_modes_arg(args.mode)
    item_tag = args.item_tag or ("item178" if modes == (SR_MODE,) else "item179")

    payload = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    new_payload, per_mode_stats = collapse_payload_modes(
        payload, modes, only_champion=args.champion or "",
    )

    for m in modes:
        _print_mode_summary(m, per_mode_stats[m])

    if args.dry_run:
        print("(dry-run; no write)")
        return 0

    if not args.no_backup:
        bak = backup_loadouts(item_tag=item_tag)
        print(f"  backup written: {bak.name}")

    atomic_write_loadouts(new_payload)
    print(f"  wrote: {_LOADOUTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
