"""Merge handcurate patch files into champion_loadouts.json.

2026-05-24 (item 166): orchestrator merge step for the 4-slice parallel
hand-curate run. Each worktree agent emits a per-slice patch file at
``data/champion_loadouts_patch_<slice>.json`` carrying ONLY the champs
in its owned name-range. This script deep-merges those patches into
the canonical ``data/champion_loadouts.json``.

Per-champ merge rules:
  - ``default_per_mode``: patch keys overwrite base keys (Arena flip).
  - ``variants``: patch entries ADDED to base (do NOT remove existing).
  - Variants are sorted alphabetically by key for stable diffs.

Atomic write per CLAUDE.md hard rule. Slices that don't touch a champ
leave that champ's entry byte-identical.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAIN = _ROOT / "data" / "champion_loadouts.json"


def _load(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(p: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
            f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def merge_patches(patch_paths: list[Path]) -> tuple[int, int, int]:
    """Returns (champs_touched, variants_added, defaults_flipped)."""
    base = _load(_MAIN)
    base_champs: dict = base.setdefault("champions", {})
    touched = 0
    variants_added = 0
    defaults_flipped = 0
    for pp in patch_paths:
        if not pp.exists():
            print(f"WARN: patch missing: {pp}", file=sys.stderr)
            continue
        patch = _load(pp)
        for name, ent in (patch.get("champions") or {}).items():
            if name not in base_champs:
                print(f"WARN: patch champ not in base: {name}", file=sys.stderr)
                continue
            touched += 1
            base_ent = base_champs[name]
            dpm_patch = ent.get("default_per_mode") or {}
            base_dpm = base_ent.setdefault("default_per_mode", {})
            for m, k in dpm_patch.items():
                if base_dpm.get(m) != k:
                    base_dpm[m] = k
                    defaults_flipped += 1
            vs_patch = ent.get("variants") or {}
            base_vs = base_ent.setdefault("variants", {})
            for vk, vv in vs_patch.items():
                if vk not in base_vs:
                    variants_added += 1
                base_vs[vk] = vv
            base_ent["variants"] = dict(sorted(base_vs.items()))
        base_champs = dict(sorted(base_champs.items()))
        base["champions"] = base_champs
    _atomic_write(_MAIN, base)
    return touched, variants_added, defaults_flipped


def main(argv: list[str]) -> int:
    if not argv:
        # Auto-discover patch files.
        patches = sorted(
            (_ROOT / "data").glob("champion_loadouts_patch_*.json"),
        )
    else:
        patches = [Path(p) for p in argv]
    if not patches:
        print("no patch files found", file=sys.stderr)
        return 1
    print(f"merging {len(patches)} patch file(s):")
    for p in patches:
        print(f"  {p.name}")
    t, v, d = merge_patches(patches)
    print(f"champs_touched={t} variants_added={v} defaults_flipped={d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
