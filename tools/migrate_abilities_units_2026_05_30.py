"""tools/migrate_abilities_units_2026_05_30.py - in-place unit-map re-type.

Mirrors tools/migrate_abilities_unit_variants_s224.py. Re-applies the extractor's
_normalize_modifiers (with the 2026-05-30 unit-map additions) to every
damage_block's unparsed_modifiers in an EXISTING champion_abilities.json, moving
newly-mappable modifiers into typed scaling fields and recomputing parse_status -
WITHOUT re-fetching Meraki (the bulk `latest` endpoint is mutable; re-extracting
would risk patch drift per the standing no-force-reextract rule).

New units closed this pass:
  "% of Ivern's AP" / "% of Sona's AP" -> ap_pct
  "%  bonus AD" (double space)         -> bonus_ad_pct
  whitespace-only (" "/"  ")           -> base
  "% armor"                            -> caster_armor_pct   (new field)
  "% bonus mana"                       -> caster_bonus_mp_pct (new field)
  "% bonus movement speed"             -> caster_bonus_ms_pct (new field)

Usage:
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/migrate_abilities_units_2026_05_30.py                 # current.txt patch
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/migrate_abilities_units_2026_05_30.py --patch 16.10.1
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/migrate_abilities_units_2026_05_30.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.daemon_slayer_abilities_extract import _normalize_modifiers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data" / "daemon_slayer"
_META_KEYS = {"attribute", "attribute_kind", "unparsed_modifiers", "raw_modifiers"}


def _merge_field(existing: list, incoming: list) -> list:
    n = max(len(existing), len(incoming))
    return [
        (existing[i] if i < len(existing) else 0.0)
        + (incoming[i] if i < len(incoming) else 0.0)
        for i in range(n)
    ]


def _retype_block(block: dict) -> bool:
    """Re-type a block's unparsed_modifiers. Returns True if anything changed."""
    ups = block.get("unparsed_modifiers")
    if not ups:
        return False
    typed_new, still_unparsed = _normalize_modifiers(ups)
    if not typed_new and len(still_unparsed) == len(ups):
        return False
    for fld, vals in typed_new.items():
        if isinstance(block.get(fld), list):
            block[fld] = _merge_field(block[fld], vals)
        else:
            block[fld] = vals
    if still_unparsed:
        block["unparsed_modifiers"] = still_unparsed
    else:
        block.pop("unparsed_modifiers", None)
    return True


def _recompute_parse_status(damage_blocks: list) -> str:
    typed = unparsed = empty = 0
    for b in damage_blocks:
        if b.get("attribute_kind") != "damage":
            continue
        has_typed = any(k for k in b if k not in _META_KEYS)
        has_unparsed = bool(b.get("unparsed_modifiers"))
        if has_typed:
            typed += 1
        elif has_unparsed:
            unparsed += 1
        else:
            empty += 1
    total = typed + unparsed + empty
    if total == 0:
        return "no_damage"
    if unparsed == 0 and empty == 0:
        return "ok"
    if typed > 0:
        return "partial"
    return "unparsed"


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-type abilities unit_map in place (2026-05-30).")
    ap.add_argument("--patch", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    patch = args.patch
    if not patch:
        patch = (DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    path = DATA_ROOT / patch / "champion_abilities.json"
    if not path.exists():
        print(f"MISSING {path}")
        return 1

    doc = json.loads(path.read_text(encoding="utf-8"))
    data = doc.get("data") or {}
    blocks_changed = 0
    forms_status_changed = 0
    status_to = {}
    for champ, keymap in data.items():
        for key, forms in keymap.items():
            for f in forms:
                dbs = f.get("damage_blocks") or []
                any_block = False
                for b in dbs:
                    if _retype_block(b):
                        blocks_changed += 1
                        any_block = True
                if any_block:
                    new_status = _recompute_parse_status(dbs)
                    if new_status != f.get("parse_status"):
                        forms_status_changed += 1
                        status_to[new_status] = status_to.get(new_status, 0) + 1
                        f["parse_status"] = new_status

    # recompute top-level coverage block
    sc = {"ok": 0, "partial": 0, "unparsed": 0, "no_damage": 0}
    total_forms = 0
    for _c, km in data.items():
        for _k, forms in km.items():
            for f in forms:
                total_forms += 1
                s = f.get("parse_status", "unparsed")
                sc[s] = sc.get(s, 0) + 1
    dmg_elig = total_forms - sc["no_damage"]
    ok_rate = round(sc["ok"] / dmg_elig, 4) if dmg_elig else 0.0
    parsed_rate = round((sc["ok"] + sc["partial"]) / dmg_elig, 4) if dmg_elig else 0.0
    cov = doc.get("coverage") or {}
    cov["status_counts"] = sc
    cov["damage_eligible"] = dmg_elig
    cov["ok_rate"] = ok_rate
    cov["parsed_rate"] = parsed_rate
    doc["coverage"] = cov

    print(f"patch={patch} blocks_changed={blocks_changed} forms_status_changed={forms_status_changed} {status_to}")
    print(f"coverage: ok={sc['ok']} partial={sc['partial']} unparsed={sc['unparsed']} no_damage={sc['no_damage']} ok_rate={ok_rate} parsed_rate={parsed_rate}")

    if args.dry_run:
        print("DRY-RUN - no write")
        return 0

    bak = path.with_suffix(f".json.bak-units20260530-{time.strftime('%H%M%S')}")
    shutil.copy2(path, bak)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    print(f"wrote {path} (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
