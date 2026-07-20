"""Diff two Daemon Slayer patch snapshots.

The snapshots under `data/daemon_slayer/<patch>/` are full extractions, not
deltas, so "what actually changed this patch" is invisible without a comparison.
This tool answers that at a level a human can act on: item gold and stats,
champion base stats, per-ability cooldown / cost / ratio moves, and build-order
churn.

THE NESTED-REGISTRY TRAP: `champion_abilities.json` has 171 champion entries but
**927 forms** across 58 multiform keys (Aphelios Q alone has 6). Each PQWER value
is a LIST of forms keyed by `form_index`. Any count taken with `len(data)` is
wrong. This module always walks champ -> key -> form_index -> damage_blocks.

READ THE ABILITY RESULT CAREFULLY. Measured 2026-07-20: the `data` payload of
`champion_abilities.json` is BYTE-IDENTICAL across 16.10.1 .. 16.14.1 - only
`version` and `fetched_at` move. That is not a bug in this tool (an injected
change is detected; see `tests/test_ds_patch_diff.py`), it is upstream: the
Meraki `latest` endpoint has been pinned at content patch 25.15 for the whole
span. So "abilities changed: 0" means "the SNAPSHOT did not move", NOT "Riot
shipped no ability changes". `ability_staleness.json` (RM-81) is the file that
answers the second question - it diffs stored Meraki values against the live
wiki and already lists stale champions.

Read-only. Writes nothing back into `data/daemon_slayer/`; the optional JSON
report goes wherever `--json` points, defaulting under `docs/_scratch/`.

Usage:
    python tools/ds_patch_diff.py 16.12.1 16.14.1
    python tools/ds_patch_diff.py 16.13.1 16.14.1 --sections items,builds
    python tools/ds_patch_diff.py 16.12.1 16.14.1 --min-pct 5 --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"

SECTIONS = ("items", "champions", "abilities", "builds")

# Item fields worth surfacing. Anything under stats.* is picked up dynamically.
_ITEM_SCALARS = ("name", "gold.base", "gold.total", "gold.sell")
_ITEM_LISTS = ("into", "tags")

_CHAMP_SCALARS = ("name", "partype")
_CHAMP_LISTS = ("tags",)

# Per-form ability fields compared verbatim.
_ABILITY_FIELDS = ("name", "cooldown", "cost", "damage_type", "targeting")

_BUILD_MODES = ("sr", "aram", "arena")


def _dig(obj: dict, dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _pct_change(old: Any, new: Any) -> Optional[float]:
    """Percent move between two numerics, or None if not comparable."""
    if isinstance(old, bool) or isinstance(new, bool):
        return None
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return None
    if old == 0:
        return None if new == 0 else float("inf")
    return abs((new - old) / old) * 100.0


def _keep(old: Any, new: Any, min_pct: float) -> bool:
    """Should this change survive the --min-pct filter?

    Non-numeric changes are ALWAYS kept - a rename or a tag flip has no percent.
    """
    if min_pct <= 0:
        return True
    pct = _pct_change(old, new)
    if pct is None:
        return True
    return pct >= min_pct


def _compare_fields(
    old: dict,
    new: dict,
    scalars: tuple,
    lists: tuple,
    stats_key: Optional[str],
    min_pct: float,
) -> dict:
    fields: dict[str, list] = {}
    for path in scalars + lists:
        o, n = _dig(old, path), _dig(new, path)
        if o != n and _keep(o, n, min_pct):
            fields[path] = [o, n]
    if stats_key:
        o_stats = old.get(stats_key) or {}
        n_stats = new.get(stats_key) or {}
        if isinstance(o_stats, dict) and isinstance(n_stats, dict):
            for stat in sorted(set(o_stats) | set(n_stats)):
                o, n = o_stats.get(stat), n_stats.get(stat)
                if o != n and _keep(o, n, min_pct):
                    fields[f"{stats_key}.{stat}"] = [o, n]
    return fields


def _registry(blob: dict) -> dict:
    data = blob.get("data")
    return data if isinstance(data, dict) else {}


def _diff_registry(
    old_blob: dict,
    new_blob: dict,
    scalars: tuple,
    lists: tuple,
    min_pct: float,
) -> dict:
    old, new = _registry(old_blob), _registry(new_blob)
    added = [
        {"id": k, "name": (new[k] or {}).get("name", k)}
        for k in sorted(set(new) - set(old))
    ]
    removed = [
        {"id": k, "name": (old[k] or {}).get("name", k)}
        for k in sorted(set(old) - set(new))
    ]
    changed = []
    for k in sorted(set(old) & set(new)):
        o, n = old[k] or {}, new[k] or {}
        fields = _compare_fields(o, n, scalars, lists, "stats", min_pct)
        if fields:
            changed.append({"id": k, "name": n.get("name", k), "fields": fields})
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": [len(old), len(new)],
    }


def diff_items(old_blob: dict, new_blob: dict, min_pct: float = 0.0) -> dict:
    return _diff_registry(old_blob, new_blob, _ITEM_SCALARS, _ITEM_LISTS, min_pct)


def diff_champions(old_blob: dict, new_blob: dict, min_pct: float = 0.0) -> dict:
    return _diff_registry(old_blob, new_blob, _CHAMP_SCALARS, _CHAMP_LISTS, min_pct)


def _forms(entry: Any) -> list:
    """Normalise a PQWER value to a list of form dicts."""
    if isinstance(entry, list):
        return [f for f in entry if isinstance(f, dict)]
    if isinstance(entry, dict):
        return [entry]
    return []


def _blocks_by_attribute(form: dict) -> dict:
    out = {}
    for block in form.get("damage_blocks") or []:
        if isinstance(block, dict) and block.get("attribute"):
            out[block["attribute"]] = block
    return out


def _count_forms(blob: dict) -> int:
    total = 0
    for entry in _registry(blob).values():
        if not isinstance(entry, dict):
            continue
        for value in entry.values():
            total += len(_forms(value))
    return total


def diff_abilities(old_blob: dict, new_blob: dict, min_pct: float = 0.0) -> dict:
    """Walk champ -> key -> form_index -> damage_blocks. Never len(data)."""
    old, new = _registry(old_blob), _registry(new_blob)
    changed: list[dict] = []

    for champ in sorted(set(old) & set(new)):
        o_entry = old[champ] if isinstance(old[champ], dict) else {}
        n_entry = new[champ] if isinstance(new[champ], dict) else {}
        for key in sorted(set(o_entry) | set(n_entry)):
            o_forms = _forms(o_entry.get(key))
            n_forms = _forms(n_entry.get(key))
            for idx in range(max(len(o_forms), len(n_forms))):
                o_form = o_forms[idx] if idx < len(o_forms) else None
                n_form = n_forms[idx] if idx < len(n_forms) else None
                base = {"champion": champ, "key": key, "form_index": idx}
                if o_form is None:
                    changed.append({**base, "change": "form_added"})
                    continue
                if n_form is None:
                    changed.append({**base, "change": "form_removed"})
                    continue
                fields: dict[str, list] = {}
                for field in _ABILITY_FIELDS:
                    o, n = o_form.get(field), n_form.get(field)
                    if o != n and _keep(o, n, min_pct):
                        fields[field] = [o, n]
                o_blocks = _blocks_by_attribute(o_form)
                n_blocks = _blocks_by_attribute(n_form)
                for attr in sorted(set(o_blocks) | set(n_blocks)):
                    ob, nb = o_blocks.get(attr), n_blocks.get(attr)
                    if ob is None:
                        fields[f"{attr}"] = [None, "added"]
                        continue
                    if nb is None:
                        fields[f"{attr}"] = ["removed", None]
                        continue
                    for ratio in sorted(set(ob) | set(nb)):
                        if ratio in ("attribute", "attribute_kind"):
                            continue
                        o, n = ob.get(ratio), nb.get(ratio)
                        if o != n and _keep(o, n, min_pct):
                            fields[f"{attr}.{ratio}"] = [o, n]
                if fields:
                    changed.append({**base, "fields": fields})

    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": changed,
        "champion_count": [len(old), len(new)],
        "form_count": [_count_forms(old_blob), _count_forms(new_blob)],
    }


def diff_builds(old_blob: dict, new_blob: dict, min_pct: float = 0.0) -> dict:
    old = old_blob.get("build_orders") or {}
    new = new_blob.get("build_orders") or {}
    changed = []
    for champ in sorted(set(old) & set(new)):
        o_arch = old[champ] if isinstance(old[champ], dict) else {}
        n_arch = new[champ] if isinstance(new[champ], dict) else {}
        for arch in sorted(set(o_arch) | set(n_arch)):
            o, n = o_arch.get(arch), n_arch.get(arch)
            if o != n:
                changed.append(
                    {"champion": champ, "archetype": arch, "items": [o, n]}
                )
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": changed,
    }


_SECTION_SPEC = {
    "items": ("items.json", diff_items),
    "champions": ("champions.json", diff_champions),
    "abilities": ("champion_abilities.json", diff_abilities),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(patch: str | Path) -> Path:
    p = Path(patch)
    return p if p.exists() and p.is_dir() else SNAPSHOT_ROOT / str(patch)


def diff_snapshots(
    old_patch: str | Path,
    new_patch: str | Path,
    sections: Optional[list] = None,
    min_pct: float = 0.0,
) -> dict:
    sections = list(sections) if sections else list(SECTIONS)
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise ValueError(f"unknown section(s): {unknown}; valid: {list(SECTIONS)}")

    old_dir, new_dir = _resolve(old_patch), _resolve(new_patch)
    for d in (old_dir, new_dir):
        if not d.is_dir():
            raise FileNotFoundError(f"snapshot dir not found: {d}")

    report: dict[str, Any] = {
        "old_patch": old_dir.name,
        "new_patch": new_dir.name,
        "min_pct": min_pct,
        "sections": {},
    }
    for section in sections:
        if section == "builds":
            modes: dict[str, Any] = {}
            for mode in _BUILD_MODES:
                name = f"build_orders_{mode}.json"
                o_path, n_path = old_dir / name, new_dir / name
                if not (o_path.exists() and n_path.exists()):
                    modes[mode] = {"error": f"missing {name} in one or both snapshots"}
                    continue
                modes[mode] = diff_builds(_load(o_path), _load(n_path), min_pct)
            report["sections"]["builds"] = modes
            continue

        filename, fn = _SECTION_SPEC[section]
        o_path, n_path = old_dir / filename, new_dir / filename
        if not (o_path.exists() and n_path.exists()):
            report["sections"][section] = {
                "error": f"missing {filename} in one or both snapshots"
            }
            continue
        report["sections"][section] = fn(_load(o_path), _load(n_path), min_pct)
    return report


def _fmt(value: Any) -> str:
    if isinstance(value, list) and len(value) > 6:
        return f"[{len(value)} entries]"
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def render_text(report: dict) -> str:
    out: list[str] = [
        f"Daemon Slayer patch diff: {report['old_patch']} -> {report['new_patch']}"
    ]
    if report.get("min_pct"):
        out.append(f"(numeric changes below {report['min_pct']}% suppressed)")
    out.append("")

    for section, body in report["sections"].items():
        if section == "builds":
            out.append("== builds")
            for mode, res in body.items():
                if res.get("error"):
                    out.append(f"  {mode}: {res['error']}")
                    continue
                changed = res["changed"]
                out.append(f"  {mode}: {len(changed)} build order change(s)")
                for c in changed[:20]:
                    out.append(
                        f"    {c['champion']} / {c['archetype']}: "
                        f"{_fmt(c['items'][0])} -> {_fmt(c['items'][1])}"
                    )
                if len(changed) > 20:
                    out.append(f"    ... and {len(changed) - 20} more")
            out.append("")
            continue

        out.append(f"== {section}")
        if body.get("error"):
            out.append(f"  {body['error']}")
            out.append("")
            continue
        if "form_count" in body:
            out.append(
                f"  champions {body['champion_count'][0]} -> "
                f"{body['champion_count'][1]}, "
                f"forms {body['form_count'][0]} -> {body['form_count'][1]}"
            )
        elif "counts" in body:
            out.append(f"  entries {body['counts'][0]} -> {body['counts'][1]}")

        for label in ("added", "removed"):
            entries = body.get(label) or []
            if entries:
                names = [
                    e["name"] if isinstance(e, dict) else str(e) for e in entries
                ]
                out.append(f"  {label}: {len(names)} - {', '.join(names[:12])}")

        changed = body.get("changed") or []
        out.append(f"  changed: {len(changed)}")
        for c in changed[:40]:
            if "fields" not in c:
                out.append(
                    f"    {c.get('champion')} {c.get('key')}"
                    f"[{c.get('form_index')}]: {c.get('change')}"
                )
                continue
            if "champion" in c:
                head = f"{c['champion']} {c['key']}[{c['form_index']}]"
            else:
                head = f"{c['name']} ({c['id']})"
            for field, (o, n) in c["fields"].items():
                out.append(f"    {head}: {field}  {_fmt(o)} -> {_fmt(n)}")
        if len(changed) > 40:
            out.append(f"    ... and {len(changed) - 40} more")
        out.append("")
    return "\n".join(out)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Diff two Daemon Slayer patch snapshots."
    )
    ap.add_argument("old", help="old patch (e.g. 16.12.1) or a snapshot dir path")
    ap.add_argument("new", help="new patch (e.g. 16.14.1) or a snapshot dir path")
    ap.add_argument(
        "--sections",
        default=",".join(SECTIONS),
        help=f"comma-separated subset of {list(SECTIONS)}",
    )
    ap.add_argument(
        "--min-pct",
        type=float,
        default=0.0,
        help="suppress numeric changes smaller than this percent",
    )
    ap.add_argument("--json", dest="json_out", help="also write the report as JSON")
    ap.add_argument("--quiet", action="store_true", help="suppress the text summary")
    args = ap.parse_args(argv)

    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    try:
        report = diff_snapshots(args.old, args.new, sections, args.min_pct)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(render_text(report))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(out)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
