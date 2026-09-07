"""s224 - deterministic in-place migration: promote the Meraki
text-drift health-unit variants newly added to ``_UNIT_TO_FIELD`` in
s224 (double-space / "the target's" target-health forms + caster-max
pronoun/name forms) out of ``unparsed_modifiers`` into typed fields.

Same mechanism + safety contract as ``migrate_abilities_nested_hp_s223``
(zero re-fetch, imports the extractor's own logic, hard audit-gate
aborts on change-set drift). Reuses that module's generic ``_promote``
/ ``_recompute_parse_status`` helpers - only the expected change-set
constants differ. s223 already promoted its 22; re-parsing those is a
no-op (idempotent), so this run touches exactly the s224 set.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/migrate_abilities_unit_variants_s224.py --dry-run
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/migrate_abilities_unit_variants_s224.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.daemon_slayer_abilities_extract import (  # noqa: E402
    _atomic_write_json,
    _coverage_summary,
)
from tools.migrate_abilities_nested_hp_s223 import (  # noqa: E402
    _promote,
    _recompute_parse_status,
)

# Audited from the post-s223 snapshot with the 8 s224 _UNIT_TO_FIELD
# additions active. Drift here means Meraki changed -> abort, no write.
_EXPECTED_CHAMPS = {
    "Ambessa", "Braum", "Briar", "Fiddlesticks", "Gnar", "Gwen",
    "Maokai", "Sejuani", "Skarner", "TahmKench", "Trundle", "Varus",
    "Zac",
}
_EXPECTED_BLOCKS = 32


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
    champs: set[str] = set()
    for champ, keys in data.items():
        if not isinstance(keys, dict):
            continue
        for key, forms in keys.items():
            for form in forms:
                changed = False
                for bi, b in enumerate(form.get("damage_blocks") or []):
                    for orig_unit, field, vals in _promote(b):
                        touched.append((champ, key, form.get("form_index"),
                                        bi, b.get("attribute"), orig_unit,
                                        field, vals[0]))
                        champs.add(champ)
                        changed = True
                if changed:
                    _recompute_parse_status(form)

    print(f"patch={patch}  promoted {len(touched)} modifier(s) "
          f"across {len(champs)} champion(s)")
    for t in touched:
        print(f"  {t[0]}.{t[1]} f{t[2]} b{t[3]} '{t[4]}'  "
              f"{t[5]!r} -> {t[6]}={t[7]}")

    if champs != _EXPECTED_CHAMPS:
        print(f"\n!! CHANGE SET DRIFT - expected {sorted(_EXPECTED_CHAMPS)}, "
              f"got {sorted(champs)}. Aborting without write.")
        return 2
    if len(touched) != _EXPECTED_BLOCKS:
        print(f"\n!! expected {_EXPECTED_BLOCKS} promotions, got "
              f"{len(touched)} - aborting.")
        return 2

    snap["coverage"] = _coverage_summary(data)
    if args.dry_run:
        print("\n[dry-run] no write. coverage would be:",
              json.dumps(snap["coverage"]["status_counts"]))
        return 0

    _atomic_write_json(path, snap)
    print(f"\nok wrote {path}")
    print("  coverage:", json.dumps(snap["coverage"]["status_counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
