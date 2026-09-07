"""s223 - deterministic in-place migration: promote nested-conditional
"% of target's <missing|current|maximum> health" modifiers that were
trapped in ``unparsed_modifiers`` into their typed scaling fields.

Why a migration and not a re-fetch: ``daemon_slayer_abilities_extract``
pulls Meraki's mutable ``latest`` endpoint - re-running it would risk a
patch bump and smear unrelated upstream churn into the diff. This script
re-applies ONLY the new nested-paren canonicalization to the EXISTING
snapshot's ``unparsed_modifiers`` (which preserve the original
``{values, units}`` verbatim), using the extractor's own helpers so the
logic is byte-identical to a future clean re-extract. Zero network,
fully auditable: it prints every (champion, key, form, block) it touches
and asserts the change set is exactly the expected nested-health blocks.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/migrate_abilities_nested_hp_s223.py --dry-run
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/migrate_abilities_nested_hp_s223.py            # writes in place
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.daemon_slayer_abilities_extract import (  # noqa: E402
    _atomic_write_json,
    _canonicalize_unit,
    _coverage_summary,
    _UNIT_TO_FIELD,
    _values_tuple,
)

_META_KEYS = {"attribute", "attribute_kind", "unparsed_modifiers", "raw_modifiers"}

# The exact change set audited from the pre-migration snapshot (s223). The
# migration asserts it touches precisely these (champion, key) pairs - any
# drift means Meraki shifted under us and the run aborts without writing.
_EXPECTED_CHAMPS = {
    "Amumu", "Chogath", "Elise", "Evelynn", "KSante",
    "Kindred", "Kled", "Sett", "Shen", "Zac",
}


def _promote(block: dict) -> list[tuple[str, str, list[float]]]:
    """Promote resolvable unparsed mods into typed fields (mirrors
    ``_normalize_modifiers``' field-merge). Returns the list of
    (orig_unit, field, values) it promoted; mutates ``block`` in place."""
    ump = block.get("unparsed_modifiers")
    if not ump:
        return []
    kept: list[dict] = []
    promoted: list[tuple[str, str, list[float]]] = []
    for mod in ump:
        if not isinstance(mod, dict):
            kept.append(mod)
            continue
        values = mod.get("values")
        units = mod.get("units")
        if not isinstance(values, list) or not isinstance(units, list):
            kept.append(mod)
            continue
        unit_set = {u for u in units if u is not None}
        unit = next(iter(unit_set)) if len(unit_set) == 1 else ""
        if not unit:
            kept.append(mod)
            continue
        lookup = unit if unit in _UNIT_TO_FIELD else _canonicalize_unit(unit)
        if lookup not in _UNIT_TO_FIELD:
            kept.append(mod)
            continue
        field = _UNIT_TO_FIELD[lookup]
        vals = _values_tuple(values)
        if vals is None:
            kept.append(mod)
            continue
        if field in block and field not in _META_KEYS:
            a, b = block[field], vals
            n = max(len(a), len(b))
            block[field] = [
                (a[i] if i < len(a) else 0.0) + (b[i] if i < len(b) else 0.0)
                for i in range(n)
            ]
        else:
            block[field] = vals
        promoted.append((unit, field, vals))
    if kept:
        block["unparsed_modifiers"] = kept
    else:
        block.pop("unparsed_modifiers", None)
    return promoted


def _recompute_parse_status(form: dict) -> None:
    typed_blocks = unparsed_blocks = empty_blocks = 0
    for b in form.get("damage_blocks") or []:
        if b.get("attribute_kind") != "damage":
            continue
        has_typed = any(k for k in b if k not in _META_KEYS)
        has_unparsed = bool(b.get("unparsed_modifiers"))
        if has_typed:
            typed_blocks += 1
        elif has_unparsed:
            unparsed_blocks += 1
        else:
            empty_blocks += 1
    n = typed_blocks + unparsed_blocks + empty_blocks
    if n == 0:
        form["parse_status"] = "no_damage"
    elif unparsed_blocks == 0 and empty_blocks == 0:
        form["parse_status"] = "ok"
    elif typed_blocks > 0:
        form["parse_status"] = "partial"
    else:
        form["parse_status"] = "unparsed"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = Path("data/daemon_slayer")
    patch = (root / "current.txt").read_text(encoding="utf-8").strip()
    path = root / patch / "champion_abilities.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    data = snap["data"]

    touched: list[tuple] = []
    champs_touched: set[str] = set()
    for champ, keys in data.items():
        if not isinstance(keys, dict):
            continue
        for key, forms in keys.items():
            for form in forms:
                form_changed = False
                for bi, b in enumerate(form.get("damage_blocks") or []):
                    pr = _promote(b)
                    for orig_unit, field, vals in pr:
                        touched.append(
                            (champ, key, form.get("form_index"), bi,
                             b.get("attribute"), orig_unit, field, vals[0])
                        )
                        champs_touched.add(champ)
                        form_changed = True
                if form_changed:
                    _recompute_parse_status(form)

    print(f"patch={patch}  promoted {len(touched)} modifier(s) "
          f"across {len(champs_touched)} champion(s)")
    for t in touched:
        print(f"  {t[0]}.{t[1]} form{t[2]} block{t[3]} "
              f"'{t[4]}'  {t[5]!r} -> {t[6]}={t[7]}")

    # Hard audit gate - abort if the change set drifted from the s223 audit.
    if champs_touched != _EXPECTED_CHAMPS:
        print("\n!! CHANGE SET DRIFT - expected exactly "
              f"{sorted(_EXPECTED_CHAMPS)}, got {sorted(champs_touched)}")
        print("   Aborting without write (Meraki snapshot changed?).")
        return 2
    if len(touched) != 22:
        print(f"\n!! expected 22 promotions, got {len(touched)} - aborting.")
        return 2

    snap["coverage"] = _coverage_summary(data)
    if args.dry_run:
        print("\n[dry-run] no file written. coverage would be:",
              json.dumps(snap["coverage"]["status_counts"]))
        return 0

    _atomic_write_json(path, snap)
    print(f"\nok wrote {path}")
    print("  coverage:", json.dumps(snap["coverage"]["status_counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
