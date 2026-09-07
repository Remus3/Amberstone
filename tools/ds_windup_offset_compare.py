"""Compare AA-windup sourcing: current sidecar (old) vs offset-derived (new).

Validator for the DS source-layering adoption plan (Desktop todo.md / docs/_archive/
DS_SOURCE_ADOPTION_PLAN.md). The current wiki_stats sidecar fills champions that
lack an absolute attack_cast_time with a flat engine default (0.25s). Most of
those champions DO carry attack_delay_offset, from which a real per-champ windup
is recoverable:

    windup_fraction = 0.300 + attack_delay_offset          # validated vs published Windup%
    windup_seconds  = windup_fraction / as_base            # combo.py is a fixed-windup model

This tool fetches the live wiki Module:ChampionData/data, parses the offset +
as_base per champion, loads the on-disk sidecar, and reports which champions
would change and by how much. Re-run on a patch bump to find newly-recoverable
champions. Read-only: it never writes the sidecar (use --json to dump a report).

Usage:
    python tools/ds_windup_offset_compare.py
    python tools/ds_windup_offset_compare.py --json out.json --patch 16.11.1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

WIKI_MODULE = (
    "https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw"
)
UA = "RC-Research/1.0 (amberstone DS validator)"
ENGINE_DEFAULT_CAST_TIME = 0.25
WINDUP_BASE = 0.300
CHANGE_EPS = 1e-4

REPO_ROOT = Path(__file__).resolve().parent.parent
DS_DATA = REPO_ROOT / "data" / "daemon_slayer"


def _fetch_module(url: str = WIKI_MODULE) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def _num(block: str, key: str) -> float | None:
    m = re.search(r'\["' + re.escape(key) + r'"\]\s*=\s*(-?[0-9.]+)', block)
    return float(m.group(1)) if m else None


def parse_module(text: str) -> dict[str, dict[str, float | None]]:
    """Window-parse the Lua table keyed by each block's ["apiname"]."""
    anchors = [m.start() for m in re.finditer(r'\["apiname"\]\s*=', text)]
    anchors.append(len(text))
    out: dict[str, dict[str, float | None]] = {}
    for i in range(len(anchors) - 1):
        block = text[anchors[i] : anchors[i + 1]]
        name_m = re.match(r'\["apiname"\]\s*=\s*"([^"]+)"', block)
        if not name_m:
            continue
        out[name_m.group(1)] = {
            "attack_cast_time": _num(block, "attack_cast_time"),
            "attack_delay_offset": _num(block, "attack_delay_offset"),
            "as_base": _num(block, "as_base"),
            "as_ratio": _num(block, "as_ratio"),
        }
    return out


def _resolve_patch(patch: str | None) -> str:
    if patch:
        return patch
    cur = DS_DATA / "current.txt"
    if cur.exists():
        txt = cur.read_text(encoding="utf-8").strip()
        if txt:
            return txt.splitlines()[0].strip()
    dirs = sorted(p.name for p in DS_DATA.iterdir() if p.is_dir())
    if not dirs:
        raise SystemExit(f"no patch dir under {DS_DATA}")
    return dirs[-1]


def load_sidecar(patch: str) -> dict:
    path = DS_DATA / patch / "wiki_stats.json"
    if not path.exists():
        raise SystemExit(f"sidecar not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def new_windup(mod: dict[str, float | None], old_s: float) -> tuple[float, str]:
    cast = mod.get("attack_cast_time")
    if cast is not None and cast > 0:
        return cast, "absolute"
    off = mod.get("attack_delay_offset")
    as_base = mod.get("as_base")
    if off is not None and as_base:
        return (WINDUP_BASE + off) / as_base, "offset"
    return old_s, "unchanged"


def compare(patch: str) -> dict:
    sidecar = load_sidecar(patch)
    champs = sidecar.get("champions", sidecar)
    module = parse_module(_fetch_module())
    rows = []
    for apiname, entry in champs.items():
        if apiname.startswith("_") or not isinstance(entry, dict):
            continue
        if "attack_cast_time" not in entry:
            continue
        old_s = float(entry.get("attack_cast_time") or ENGINE_DEFAULT_CAST_TIME)
        old_src = entry.get("attack_cast_time_src", "?")
        mod = module.get(apiname)
        if not mod:
            continue
        ns, method = new_windup(mod, old_s)
        rows.append(
            {
                "apiname": apiname,
                "old_s": round(old_s, 4),
                "old_src": old_src,
                "offset": mod.get("attack_delay_offset"),
                "as_base": mod.get("as_base"),
                "new_s": round(ns, 4),
                "method": method,
                "changed": abs(ns - old_s) > CHANGE_EPS,
            }
        )
    changed = [r for r in rows if r["changed"]]
    return {
        "_meta": {
            "patch": patch,
            "champs": len(rows),
            "changed": len(changed),
            "with_cast_measured": sidecar.get("_with_cast_measured"),
            "default_cast_fills": sidecar.get("_default_cast_fills"),
            "wiki_module": WIKI_MODULE,
        },
        "rows": sorted(rows, key=lambda r: r["apiname"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patch", default=None, help="patch dir (default: current.txt)")
    ap.add_argument("--json", default=None, help="write full report to this path")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    report = compare(patch)
    meta = report["_meta"]
    changed = [r for r in report["rows"] if r["changed"]]

    print(
        f"patch={meta['patch']} champs={meta['champs']} changed={meta['changed']} "
        f"(sidecar measured={meta['with_cast_measured']} "
        f"default_fills={meta['default_cast_fills']})"
    )
    print(f"{'champ':<16}{'old_s':>8}{'old_src':>10}{'offset':>9}{'new_s':>8}  method")
    for r in changed[:20]:
        off = "-" if r["offset"] is None else f"{r['offset']:.4f}"
        print(
            f"{r['apiname']:<16}{r['old_s']:>8.4f}{r['old_src']:>10}{off:>9}"
            f"{r['new_s']:>8.4f}  {r['method']}"
        )
    if len(changed) > 20:
        print(f"... +{len(changed) - 20} more")

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
