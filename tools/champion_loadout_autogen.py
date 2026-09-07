"""tools/champion_loadout_autogen.py - s215 build-chooser auto-generator.

Generates up to 3 algorithmic build variants per (champion, mode) into
``data/champion_loadouts.json`` using the Daemon Slayer engine's per-
archetype scorers (carry/bruiser/tank/mage/assassin/enchanter). Closes
the s214 carry-forward where most champs had only 1 SR + 2 ARAM
hand-curated variants while the UI's build-chooser slot has space for
3 curated + 1 experimental row.

Policy
------
**Hand-curated wins.** For each (champion, mode), the script counts
existing variants whose ``modes[]`` includes the target mode. If the
count is >= 3, no auto entries are generated for that slot - the
operator's curated decisions stay untouched. If the count is < 3,
auto-* entries fill the gap. Auto entries can refresh on re-run
(items shift as DS engine evolves); curated entries are never
overwritten.

Three variants per (champion, mode):

* ``auto-<mode>-primary-<arch>``   - champion's primary archetype
* ``auto-<mode>-secondary-<arch>`` - champion's secondary archetype
* ``auto-<mode>-flavor-<arch>``    - complementary archetype heuristic

The complementary archetype follows the same pattern the experimental
row's keystone mapping does (see _CSV_EXPERIMENTAL_RUNES in
``web/js/panels/champ_select.js``): bruiser->carry alt, tank->bruiser
alt, carry->assassin alt, mage->assassin alt, etc.

Per-archetype defaults
----------------------
* ``runes``     - mirrors ``_CSV_EXPERIMENTAL_RUNES`` from champ_select.js
                  (canonical archetype -> keystone+trees consensus).
* ``summoners`` - SR is archetype-keyed (tanks/bruisers Flash+TP,
                  carries Flash+Heal, mages/assassins Flash+Ignite,
                  enchanters Flash+Exhaust). ARAM always Flash+Mark.
                  Arena defaults to Flash+Heal (no smite/teleport).
* ``items``     - top 6 from
                  ``daemon_slayer_client.rank_for_primary_archetype``
                  at level 11 with empty current-build (mid-game items).

Wire-shape
----------
Variant entries match the existing schema in
``data/champion_loadouts.json``: ``label, modes, runes:{keystone,
primary, secondary}, summoners:[d,f], items:[<display name>, ...]``.
Two extra fields ``_auto: true`` and ``_archetype: <arch>`` are added
for round-trip identification (loadout resolver ignores unknown keys).

Usage
-----
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/champion_loadout_autogen.py [--mode sr|aram|arena|all]
        [--champion <name>] [--dry-run] [--reset-auto] [--level 11]

* ``--mode all`` (default) generates for SR + ARAM + Arena.
* ``--champion`` runs only one champion (dev iteration shortcut).
* ``--dry-run`` prints the summary but doesn't write the file.
* ``--reset-auto`` drops all ``auto-*`` entries before regenerating.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Optional

# Project root: tools/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import archetype_picks
from core import daemon_slayer_client as dsc

_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"
_CHAMPS_PATH = _ROOT / "data" / "meta" / "ddragon_champions.json"

AUTO_KEY_PREFIX = "auto-"
SCHEMA_VERSION = 1
MODES = ("sr", "aram", "arena")
DS_MODE_BY_KEY = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}

# Item s8 (2026-06-10): operator-set exact build lengths (SR 7 / ARAM 6
# / Arena 6, boots included on SR/ARAM). Generation-time invariant -
# every emitted variant is shaped through the shared item-213 Cleaner
# (boots reseat + pool refill + tail trim) so a regen can never write a
# truncated or overlong row again.
from tools.champion_loadout_invariants import TARGET_LEN  # noqa: E402

# Engine picks requested per mode = target minus the boots slot the
# Cleaner injects at index 1 on SR/ARAM (Arena has no shop boots).
ENGINE_PICKS_BY_MODE = {
    "sr": TARGET_LEN["sr"] - 1,
    "aram": TARGET_LEN["aram"] - 1,
    "arena": TARGET_LEN["arena"],
}

_SHAPER = None


def _shaper():
    """Lazy singleton of the item-213 Cleaner (loads the item catalog +
    unique-family map once per process)."""
    global _SHAPER
    if _SHAPER is None:
        from tools.champion_loadout_cleanup_pollution_item213 import Cleaner
        _SHAPER = Cleaner()
    return _SHAPER

# Archetype -> (keystone, primary tree, secondary tree). Source of truth
# is also duplicated in ``web/js/panels/champ_select.js`` for the
# experimental row's runes - keep both in sync if updating.
ARCH_RUNES: dict[str, dict[str, str]] = {
    "carry":     {"keystone": "Lethal Tempo",  "primary": "Precision",  "secondary": "Domination"},
    "bruiser":   {"keystone": "Conqueror",     "primary": "Precision",  "secondary": "Resolve"},
    "tank":      {"keystone": "Aftershock",    "primary": "Resolve",    "secondary": "Inspiration"},
    "mage":      {"keystone": "Arcane Comet",  "primary": "Sorcery",    "secondary": "Inspiration"},
    "assassin":  {"keystone": "Electrocute",   "primary": "Domination", "secondary": "Precision"},
    "enchanter": {"keystone": "Summon Aery",   "primary": "Sorcery",    "secondary": "Inspiration"},
}

# Summoner IDs: 1 cleanse, 3 exhaust, 4 flash, 6 ghost, 7 heal, 11 smite,
# 12 teleport, 14 ignite, 21 barrier, 32 mark (snowball/poro).
SR_SUMM_BY_ARCH: dict[str, list[int]] = {
    "carry":     [4, 21],  # Flash + Barrier (solo ADC norm 16.10.x)
    "bruiser":   [4, 12],  # Flash + Teleport (top)
    "tank":      [4, 12],  # Flash + Teleport (top)
    "mage":      [4, 14],  # Flash + Ignite (mid)
    "assassin":  [4, 14],  # Flash + Ignite (mid/jg)
    "enchanter": [4, 3],   # Flash + Exhaust (sup)
}
ARAM_SUMM_DEFAULT = [4, 32]   # Flash + Mark
ARENA_SUMM_DEFAULT = [4, 7]   # Flash + Heal

# Complementary archetype heuristic - when filling the third slot, pick
# something the operator might genuinely consider over the primary.
THIRD_ARCH_HEURISTIC: dict[str, str] = {
    "carry":     "assassin",  # lethality alt for marksmen
    "bruiser":   "carry",     # pure-DPS alt for fighters
    "tank":      "bruiser",   # off-tank alt
    "mage":      "assassin",  # burst alt for AP casters
    "assassin":  "carry",     # sustained-DPS alt
    "enchanter": "mage",      # poke alt for supports
}

# Human-readable label per archetype. Suffixed with "(auto)" so the
# operator can see at a glance which rows are algorithmic.
ARCH_LABEL: dict[str, str] = {
    "carry":     "Carry",
    "bruiser":   "Bruiser",
    "tank":      "Tank",
    "mage":      "Mage",
    "assassin":  "Assassin",
    "enchanter": "Enchanter",
}


def variant_key(mode: str, slot: str, archetype: str) -> str:
    """Stable variant key: ``auto-<mode>-<slot>-<arch>``.

    Keys are mode-scoped so SR vs ARAM vs Arena auto entries don't
    collide (items differ across modes via DS mode multiplier).
    """
    return f"{AUTO_KEY_PREFIX}{mode}-{slot}-{archetype}"


def summoners_for(mode: str, archetype: str) -> list[int]:
    """Pick the summoner pair for ``(mode, archetype)``.

    SR is archetype-aware. ARAM + Arena use mode-fixed defaults since
    they ignore role-based summoner conventions (no lanes, no smite).
    """
    if mode == "aram":
        return list(ARAM_SUMM_DEFAULT)
    if mode == "arena":
        return list(ARENA_SUMM_DEFAULT)
    return list(SR_SUMM_BY_ARCH.get(archetype, [4, 14]))


def resolve_archetype_triplet(primary: str, secondary: str) -> list[tuple[str, str]]:
    """Return [(slot, archetype), ...] for the 3 auto variants.

    Deduplicates: if primary == secondary (shouldn't happen via
    DDragon-tag defaults, but guard anyway), or if heuristic third
    collides with primary/secondary, fall back to the first unused
    archetype in ARCHETYPES canonical order.
    """
    triplet: list[tuple[str, str]] = [("primary", primary)]
    if secondary and secondary != primary:
        triplet.append(("secondary", secondary))
    else:
        # Fill secondary slot with the next-best archetype
        for cand in archetype_picks.ARCHETYPES:
            if cand != primary:
                triplet.append(("secondary", cand))
                break
    used = {a for _, a in triplet}
    third = THIRD_ARCH_HEURISTIC.get(primary, "bruiser")
    if third in used:
        for cand in archetype_picks.ARCHETYPES:
            if cand not in used:
                third = cand
                break
    triplet.append(("flavor", third))
    return triplet


def fetch_items(champion: str, archetype: str, mode: str, level: int) -> list[str]:
    """Call DS engine for the per-mode engine-pick count under
    ``archetype`` at ``level`` (item s8: SR 6 + boots, ARAM 5 + boots,
    Arena 6 - see ENGINE_PICKS_BY_MODE).

    Returns the list of display names (empty list on engine error or
    empty ranking). Caller decides whether to skip generation when
    items is empty.
    """
    ds_mode = DS_MODE_BY_KEY.get(mode, "SR")
    picks = ENGINE_PICKS_BY_MODE.get(mode, 6)
    try:
        result = dsc.rank_for_primary_archetype(
            champion,
            archetype,
            level=level,
            item_ids=[],
            mode=ds_mode,
            # Over-request so a short tail (engine dedup, carry gate)
            # still leaves enough names to fill the pick budget.
            top=picks + 6,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! DS error for {champion}/{archetype}/{mode}: {exc}", file=sys.stderr)
        return []
    if not result or not result.get("ranked"):
        return []
    names: list[str] = []
    for row in result["ranked"]:
        if len(names) >= picks:
            break
        nm = (row.get("item_name") or "").strip()
        if nm:
            names.append(nm)
    return names


def build_variant(
    champion: str,
    archetype: str,
    mode: str,
    *,
    level: int,
) -> Optional[dict]:
    """Construct a single auto variant entry. Returns None on DS miss.

    Item s8 generation-time invariant: the emitted items list is shaped
    to the exact per-mode length (TARGET_LEN) with boots at index 1 on
    SR/ARAM - short engine returns are padded from the shared archetype
    pools, overlong ones tail-trimmed.
    """
    items = fetch_items(champion, archetype, mode, level)
    if not items:
        return None
    skip = (
        dsc.CARRY_RANGED_OFFCLASS_ITEM_NAMES
        if (
            archetype == "carry"
            and dsc.champion_attackrange(champion)
            >= dsc.CARRY_RANGED_ATTACKRANGE_FLOOR
        )
        else frozenset()
    )
    items = _shaper().enforce_length(champion, mode, archetype, items, skip)
    return {
        "label":     f"{ARCH_LABEL[archetype]} (auto)",
        "modes":     [mode],
        "runes":     dict(ARCH_RUNES[archetype]),
        "summoners": summoners_for(mode, archetype),
        "items":     items,
        "_auto":     True,
        "_archetype": archetype,
    }


def count_existing_mode_variants(variants: dict, mode: str) -> int:
    """Count non-auto variants visible for ``mode``.

    Auto entries don't count against the 3-slot budget (so re-running
    refreshes them in place without growing the file)."""
    n = 0
    for key, v in (variants or {}).items():
        if key.startswith(AUTO_KEY_PREFIX):
            continue
        modes = [str(m).lower() for m in (v.get("modes") or [])]
        if mode in modes:
            n += 1
    return n


def generate_for_champion(
    champion: str,
    existing_variants: dict,
    *,
    modes: Iterable[str],
    level: int,
) -> tuple[dict, dict[str, int]]:
    """Return (new_variants_dict, stats_per_mode).

    ``new_variants_dict`` is the merged dict: curated variants
    preserved, auto entries added/refreshed to fill each mode to 3
    visible rows. Auto entries from prior runs are refreshed (items
    may have shifted as DS engine evolved); auto entries for modes
    that already have >=3 curated are dropped.

    ``stats_per_mode`` reports per-mode counts: curated, auto_kept,
    auto_added, slots_unfilled.
    """
    out = dict(existing_variants or {})
    stats: dict[str, int] = {}

    primary, secondary = archetype_picks.default_for_champion(champion)
    triplet = resolve_archetype_triplet(primary, secondary)

    for mode in modes:
        curated_count = count_existing_mode_variants(out, mode)
        needed = max(0, 3 - curated_count)
        auto_added = 0
        unfilled = 0

        # First, drop any auto-<mode>-* entries that we'd be regenerating
        # - needed if --reset-auto fired OR if the archetype mapping has
        # shifted (e.g. DDragon retag). Keep auto entries from OTHER
        # modes untouched.
        auto_keys_for_mode = [
            k for k in list(out.keys())
            if k.startswith(f"{AUTO_KEY_PREFIX}{mode}-")
        ]

        # Decide which (slot, archetype) pairs we still want
        wanted: list[tuple[str, str, str]] = []
        for slot, arch in triplet[:needed]:
            wanted.append((variant_key(mode, slot, arch), slot, arch))

        wanted_keys = {k for k, _, _ in wanted}
        # Drop stale auto entries (different slot/arch than wanted)
        for k in auto_keys_for_mode:
            if k not in wanted_keys:
                del out[k]

        for key, slot, arch in wanted:
            v = build_variant(champion, arch, mode, level=level)
            if v is None:
                unfilled += 1
                # Keep existing auto entry if present (better than empty)
                continue
            out[key] = v
            auto_added += 1

        stats[mode] = {
            "curated":  curated_count,
            "auto":     auto_added,
            "unfilled": unfilled,
        }

    return out, stats


def load_loadouts() -> dict:
    if not _LOADOUTS_PATH.exists():
        return {"_schema_version": SCHEMA_VERSION, "_doc": [], "champions": {}}
    return json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))


def load_champions() -> list[tuple[str, str]]:
    """Return ``[(display_name, slug), ...]`` for the full DDragon roster."""
    raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
    data = raw.get("data") or {}
    out: list[tuple[str, str]] = []
    for slug, info in data.items():
        name = info.get("name") or slug
        out.append((name, slug))
    # Sort by name for stable iteration order
    out.sort(key=lambda t: t[0].lower())
    return out


def atomic_write_loadouts(payload: dict) -> None:
    """Write payload to the loadouts JSON via tmp + replace.

    Mirrors ``core.archetype_picks._atomic_write_picks``. Sort keys
    inside ``champions`` for stable diffs; preserve top-level key
    order (schema_version, doc, champions).
    """
    out_dir = _LOADOUTS_PATH.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".champion_loadouts.", suffix=".tmp", dir=str(out_dir),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            # Sort within champions, but preserve top-level ordering.
            ordered = {
                "_schema_version": payload.get("_schema_version", SCHEMA_VERSION),
                "_doc":            payload.get("_doc", []),
                "champions":       {
                    name: sort_champ_entry(entry)
                    for name, entry in sorted(
                        (payload.get("champions") or {}).items(),
                        key=lambda kv: kv[0].lower(),
                    )
                },
            }
            json.dump(ordered, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, str(_LOADOUTS_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def sort_champ_entry(entry: dict) -> dict:
    """Sort variants by key for stable diffs."""
    variants = entry.get("variants") or {}
    return {
        "default_per_mode": entry.get("default_per_mode") or {},
        "variants": {k: variants[k] for k in sorted(variants.keys())},
    }


def reset_auto_entries(payload: dict) -> None:
    """Drop every ``auto-*`` variant in-place (across all champions).

    Used when --reset-auto is passed to ensure a clean regeneration
    from scratch (no orphans from a prior archetype-mapping shift)."""
    for champ_entry in (payload.get("champions") or {}).values():
        variants = champ_entry.get("variants") or {}
        for k in list(variants.keys()):
            if k.startswith(AUTO_KEY_PREFIX):
                del variants[k]


def ensure_default_per_mode(champ_entry: dict, mode: str, primary: str) -> None:
    """If no default is set for ``mode``, point at the auto-primary key.

    Hand-curated defaults stay untouched. This only fills empty slots
    so the chooser has a sensible first row on freshly-generated
    champions."""
    defaults = champ_entry.setdefault("default_per_mode", {})
    if defaults.get(mode):
        return  # operator has chosen a default already
    key = variant_key(mode, "primary", primary)
    variants = champ_entry.get("variants") or {}
    if key in variants:
        defaults[mode] = key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="all", choices=("all", "sr", "aram", "arena"),
                    help="Restrict generation to one mode (default: all).")
    ap.add_argument("--champion", default="",
                    help="Single-champion mode (DDragon display name, e.g. 'Aatrox').")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary without writing the file.")
    ap.add_argument("--reset-auto", action="store_true",
                    help="Drop ALL existing auto-* entries before regenerating.")
    ap.add_argument("--level", type=int, default=11,
                    help="Champion level passed to DS engine (default 11).")
    args = ap.parse_args()

    if not dsc.is_engine_up(timeout=1.0):
        print("DS engine at 127.0.0.1:8860 is not responding. Start it via "
              "`$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/start_daemon_slayer.py` and re-run.", file=sys.stderr)
        return 2

    target_modes: tuple[str, ...] = MODES if args.mode == "all" else (args.mode,)
    print(f"autogen modes={target_modes} level={args.level} "
          f"dry_run={args.dry_run} reset_auto={args.reset_auto}")

    payload = load_loadouts()
    if args.reset_auto:
        reset_auto_entries(payload)

    champions = load_champions()
    if args.champion:
        champions = [(n, s) for (n, s) in champions if n == args.champion]
        if not champions:
            print(f"champion {args.champion!r} not in DDragon roster", file=sys.stderr)
            return 2

    payload.setdefault("champions", {})

    totals = {m: {"curated": 0, "auto": 0, "unfilled": 0} for m in target_modes}
    started = time.time()

    for idx, (name, _slug) in enumerate(champions, start=1):
        champ_entry = payload["champions"].get(name) or {}
        variants = champ_entry.get("variants") or {}
        new_variants, stats = generate_for_champion(
            name, variants,
            modes=target_modes,
            level=args.level,
        )
        champ_entry["variants"] = new_variants
        # Pin auto-primary as default when operator hasn't set one
        primary, _secondary = archetype_picks.default_for_champion(name)
        for mode in target_modes:
            ensure_default_per_mode(champ_entry, mode, primary)
            for k in ("curated", "auto", "unfilled"):
                totals[mode][k] += stats.get(mode, {}).get(k, 0)
        payload["champions"][name] = champ_entry

        if idx % 25 == 0 or idx == len(champions):
            elapsed = time.time() - started
            print(f"  {idx:3d}/{len(champions)} champions  ({elapsed:5.1f}s)")

    if not args.dry_run:
        atomic_write_loadouts(payload)
        print(f"wrote {_LOADOUTS_PATH}")
    else:
        print("(dry-run: file not written)")

    print()
    print("Summary by mode:")
    for mode, s in totals.items():
        print(f"  {mode:6s}: curated_slots={s['curated']:4d} "
              f"auto_added={s['auto']:4d} unfilled={s['unfilled']:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
