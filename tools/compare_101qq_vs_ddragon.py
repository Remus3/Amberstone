"""Align Tencent 101.qq.com hero IDs to RC's DDragon champion keys
(item 187 Slice G follow-up; ROADMAP L132).

Companion to tools/probe_101qq_hero_rank_double.py. Where the probe
script just SUMMARIZES the captured payload shape, this script tries to
build a complete `tencent_id -> ddragon_name` map and reports any
mismatches. Output is a canonical id_map.json the live consumer (the
pick/ban synergy lane of `core/smoothed_rates.py`) can load.

Override hook: an optional `data/external/101qq_hero_id_map.json` file
of the same shape (overlaid LAST) lets the operator hand-correct
mismatches without re-running the comparison.

STDLIB-ONLY: argparse / json / pathlib / sys. ASCII-clean.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/compare_101qq_vs_ddragon.py --json C:/path/to/captured.json
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/compare_101qq_vs_ddragon.py --json ... --out data/external/101qq_id_map.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DDRAGON_CACHE_ROOT = _REPO_ROOT / "data" / "meta_build" / "ddragon"
_SEMVER_DIR_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _ddragon_champion_json() -> Path:
    """Newest cached champion.json under data/meta_build/ddragon/.

    Resolved via _index.json latest_pulled first, then the newest semver
    dir present - the cache keeps only current+previous patches (item 397
    retention), so a pinned patch dir rotates out from under a literal."""
    idx = _DDRAGON_CACHE_ROOT / "_index.json"
    try:
        ver = json.loads(idx.read_text(encoding="utf-8")).get("latest_pulled", "")
        p = _DDRAGON_CACHE_ROOT / ver / "champion.json"
        if ver and p.exists():
            return p
    except (OSError, ValueError):
        pass
    dirs = [d for d in _DDRAGON_CACHE_ROOT.glob("*")
            if d.is_dir() and _SEMVER_DIR_RE.match(d.name)]
    dirs.sort(key=lambda d: tuple(int(x) for x in d.name.split(".")), reverse=True)
    for d in dirs:
        p = d / "champion.json"
        if p.exists():
            return p
    return _DDRAGON_CACHE_ROOT / "_absent" / "champion.json"
_OPERATOR_OVERRIDE = _REPO_ROOT / "data" / "external" / "101qq_hero_id_map.json"


def load_ddragon_keys() -> dict:
    """Return both id-keyed and name-keyed views of DDragon champions."""
    out: dict = {"by_id": {}, "by_name_lower": {}}
    if not _ddragon_champion_json().exists():
        return out
    raw = json.loads(_ddragon_champion_json().read_text(encoding="utf-8"))
    for name, payload in (raw.get("data") or {}).items():
        key = str(payload.get("key", "")).strip()
        if key.isdigit():
            out["by_id"][key] = name
        out["by_name_lower"][name.lower()] = name
    return out


def load_override() -> dict:
    """Operator's hand-corrections layered last. Schema: {tencent_id: ddragon_name}."""
    if not _OPERATOR_OVERRIDE.exists():
        return {}
    try:
        return json.loads(_OPERATOR_OVERRIDE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def unwrap_envelope(payload: object) -> object:
    """Unwrap Tencent's `{code, data, message}` envelope if present.

    Item 198 capture (2026-05-26) showed the live shape is
    `{"code":0,"data":[{...pair-records...}],"message":"success"}` with
    pair records living in `data[]`. Returns `payload["data"]` when the
    envelope is detected; otherwise returns `payload` unchanged."""
    if isinstance(payload, dict):
        keys = set(payload.keys())
        if {"code", "data", "message"}.issubset(keys) and isinstance(payload.get("data"), list):
            return payload["data"]
    return payload


def _collect_ids(payload: object) -> list:
    """Return all champion IDs referenced in the payload.

    Handles both shapes:
    (a) dict-of-pairs (synthetic / hypothetical): top-level keys are IDs
    (b) list-of-pair-records (item 198 actual capture): each record has
        `championid1` + `championid2` numeric-string fields
    """
    ids: list = []
    if isinstance(payload, dict):
        ids.extend(str(k) for k in payload.keys())
    elif isinstance(payload, list):
        seen: set = set()
        for rec in payload:
            if isinstance(rec, dict):
                for field in ("championid1", "championid2"):
                    v = rec.get(field)
                    if v is None:
                        continue
                    s = str(v)
                    if s and s not in seen:
                        seen.add(s)
                        ids.append(s)
    return ids


def build_alignment(payload: object, ddragon: dict, override: dict) -> dict:
    """Walk the captured payload's champion IDs and try to map each to a
    DDragon canonical name. Accepts either dict-of-pairs (synthetic) or
    list-of-pair-records (item 198 actual capture shape)."""
    aligned: dict = {}
    unmatched: list = []
    ids = _collect_ids(payload)
    if not ids:
        return {"aligned": aligned, "unmatched": unmatched, "note": "no champion IDs found in payload"}
    for s in ids:
        if s in override:
            aligned[s] = override[s]
            continue
        if s in ddragon["by_id"]:
            aligned[s] = ddragon["by_id"][s]
            continue
        if s.lower() in ddragon["by_name_lower"]:
            aligned[s] = ddragon["by_name_lower"][s.lower()]
            continue
        unmatched.append(s)
    return {"aligned": aligned, "unmatched": unmatched, "note": ""}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align captured 101.qq.com hero IDs to DDragon champion names.",
    )
    parser.add_argument("--json", required=True, help="Path to captured JSON payload on disk.")
    parser.add_argument(
        "--out",
        default="",
        help="Optional output path for canonical id_map.json. If omitted, only prints to stdout.",
    )
    args = parser.parse_args(argv)

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"ERROR: JSON file not found: {json_path}", file=sys.stderr)
        return 1
    try:
        raw_payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not parse JSON: {exc}", file=sys.stderr)
        return 1

    payload = unwrap_envelope(raw_payload)
    ddragon = load_ddragon_keys()
    override = load_override()
    alignment = build_alignment(payload, ddragon, override)

    summary = {
        "total_keys": len(alignment["aligned"]) + len(alignment["unmatched"]),
        "aligned_count": len(alignment["aligned"]),
        "unmatched_count": len(alignment["unmatched"]),
        "unmatched_sample": alignment["unmatched"][:10],
        "override_loaded": bool(override),
        "ddragon_champ_count": len(ddragon["by_id"]),
    }
    print(json.dumps({"summary": summary, "note": alignment.get("note", "")}, ensure_ascii=True, indent=2, sort_keys=True))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(json.dumps(alignment["aligned"], ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(out_path)
        print(f"Wrote id_map: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
