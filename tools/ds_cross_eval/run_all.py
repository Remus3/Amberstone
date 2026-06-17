"""Batch-run probe_champion over the full DDragon roster.

Deterministic pre-compute: writes ops/audit/ds_cross_eval/data/<canon>.json for
every champion so the per-champion judge agents read ground truth instead of
each booting the engine (de-risks 172 subprocess launches; proves the harness
once). Read-only. ASCII only.

Usage: python tools/ds_cross_eval/run_all.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(r"C:/Riot Commander")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "ds_cross_eval"))

import probe_champion as P  # noqa: E402


def roster() -> list:
    patch = P._ds_patch() or "16.12.1"
    for p in (
        ROOT / "data" / "meta_build" / "ddragon" / patch / "champion.json",
        ROOT / "data" / "meta_build" / "ddragon" / "16.12.1" / "champion.json",
    ):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            return sorted(j.get("data", {}).keys())
        except Exception:
            continue
    return []


def main() -> int:
    champs = roster()
    outdir = ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
    outdir.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, []
    t0 = time.time()
    for ch in champs:
        try:
            data = P.probe(ch)
            fp = outdir / (data["champion"] + ".json")
            tmp = fp.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(fp)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail.append((ch, f"{type(exc).__name__}: {exc}"))
            traceback.print_exc()
    dt = time.time() - t0
    print(f"ROSTER {len(champs)} OK {ok} FAIL {len(fail)} {dt:.1f}s")
    for ch, err in fail:
        print(f"FAIL {ch} {err}")
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
