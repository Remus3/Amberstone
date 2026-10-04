"""Build + verify steps of the game-data pipeline (P1-4).

``reconcile(fetched)`` turns every source's parsed tables into one normalised
set of champions and items. Every output value carries its source in the
entity's ``_provenance`` map. When sources disagree, the value of the field's
NAMED AUTHORITY is kept and the disagreement is recorded in ``caveats`` with
all values by source, so a stale or wrong value in any one source stays
visible instead of being averaged away.

Authorities (official first, per the RC rule that Data Dragon owns item
magnitudes):

- champion base stats: ddragon, then wiki, then meraki;
- ``ad_per_level`` / ``as_per_level``: as above, but a Data Dragon ZERO is a
  known placeholder (measured 2026-10-04 on 16.19.1: all 173 champions
  publish ``attackdamageperlevel: 0``; the wiki and Meraki carry non-zero
  growth for 172 of them), so a ddragon 0 contradicted by another source is skipped, and a
  ddragon 0 nothing can contradict is kept with an "unresolved" caveat;
- ``as_ratio``: wiki, then meraki (Data Dragon does not publish it);
- item gold and flat stats: ddragon, then meraki.

``verify`` re-derives every disagreement from the raw parsed tables and lists
any the build did not explain; the acceptance bar is zero.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.game_data.fetch import Fetched

ROSTER_SOURCE = "ddragon"


@dataclass(frozen=True)
class FieldPolicy:
    authority: tuple[str, ...]
    zero_placeholder: frozenset = frozenset()


_BASE = FieldPolicy(("ddragon", "wiki", "meraki"))
_GROWTH_PLACEHOLDER = FieldPolicy(("ddragon", "wiki", "meraki"), frozenset({"ddragon"}))
_ITEM = FieldPolicy(("ddragon", "meraki"))

CHAMPION_FIELDS: dict[str, FieldPolicy] = {
    "hp": _BASE,
    "hp_per_level": _BASE,
    "armor": _BASE,
    "armor_per_level": _BASE,
    "mr": _BASE,
    "mr_per_level": _BASE,
    "ad": _BASE,
    "ad_per_level": _GROWTH_PLACEHOLDER,
    "attack_speed": _BASE,
    "as_per_level": _GROWTH_PLACEHOLDER,
    "as_ratio": FieldPolicy(("wiki", "meraki")),
    "move_speed": _BASE,
    "attack_range": _BASE,
}
ITEM_FIELDS: dict[str, FieldPolicy] = {
    "gold_total": _ITEM,
    "ad": _ITEM,
    "ap": _ITEM,
    "armor": _ITEM,
    "mr": _ITEM,
    "hp": _ITEM,
}
_KINDS = (("champions", "champion", CHAMPION_FIELDS), ("items", "item", ITEM_FIELDS))
_TOL = 1e-9


@dataclass
class Build:
    version: str
    champions: dict[str, dict] = field(default_factory=dict)
    items: dict[str, dict] = field(default_factory=dict)
    caveats: list[dict] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def _differ(values: dict[str, Any]) -> bool:
    vals = list(values.values())
    return any(abs(v - vals[0]) > _TOL for v in vals[1:])


def _values(parsed: dict, kind: str, eid: str, fname: str, policy: FieldPolicy) -> dict:
    out = {}
    for src in policy.authority:
        v = ((parsed.get(src) or {}).get(kind) or {}).get(eid, {}).get(fname)
        if v is not None:
            out[src] = v
    return out


def _resolve(values: dict, policy: FieldPolicy) -> tuple[str, str]:
    """Return (chosen_source, reason)."""
    placeholders = {
        s for s in policy.zero_placeholder
        if values.get(s) == 0 and any(v != 0 for k, v in values.items() if k != s)
    }
    for src in policy.authority:
        if src in values and src not in placeholders:
            if placeholders:
                skipped = ", ".join(sorted(placeholders))
                return src, f"placeholder: {skipped} publishes 0 for this field; next authority {src} used"
            return src, f"authority: {src} is the named authority for this field"
    raise AssertionError("unreachable: values is non-empty")


def reconcile(fetched: Fetched) -> Build:
    parsed = fetched.parsed
    b = Build(version=fetched.version, excluded=dict(fetched.excluded), sources=sorted(parsed))
    for src, why in sorted(fetched.excluded.items()):
        b.caveats.append({
            "entity": "*", "field": f"source:{src}", "values_by_source": {},
            "chosen": None, "chosen_source": None, "reason": f"excluded: {why}",
        })
    for kind, label, fields in _KINDS:
        roster = (parsed.get(ROSTER_SOURCE) or {}).get(kind) or {}
        target = b.champions if kind == "champions" else b.items
        for eid in sorted(roster):
            row: dict[str, Any] = {}
            prov: dict[str, str] = {}
            for fname, policy in fields.items():
                values = _values(parsed, kind, eid, fname, policy)
                if not values:
                    continue
                src, reason = _resolve(values, policy)
                row[fname] = values[src]
                prov[fname] = src
                unresolved = (
                    src in policy.zero_placeholder and values[src] == 0 and len(values) == 1
                )
                if _differ(values) or unresolved:
                    if unresolved:
                        reason = f"placeholder: {src} publishes 0 and no other source is available; unresolved"
                    b.caveats.append({
                        "entity": f"{label}:{eid}", "field": fname,
                        "values_by_source": dict(sorted(values.items())),
                        "chosen": values[src], "chosen_source": src, "reason": reason,
                    })
            row["_provenance"] = prov
            target[eid] = row
    b.caveats.sort(key=lambda c: (c["entity"], c["field"]))
    b.report = verify(b, fetched)
    return b


def verify(b: Build, fetched: Fetched) -> dict:
    """Counts per source, reconciled-field count, and every disagreement in the
    raw tables that has no caveat (the acceptance bar is an empty list)."""
    parsed = fetched.parsed
    counts = {
        src: {"champions": len(p.get("champions") or {}), "items": len(p.get("items") or {})}
        for src, p in sorted(parsed.items())
    }
    explained = {(c["entity"], c["field"]) for c in b.caveats}
    unexplained = []
    for kind, label, fields in _KINDS:
        built = b.champions if kind == "champions" else b.items
        for eid, row in sorted(built.items()):
            for fname, policy in fields.items():
                values = _values(parsed, kind, eid, fname, policy)
                if values and _differ(values) and (f"{label}:{eid}", fname) not in explained:
                    unexplained.append({"entity": f"{label}:{eid}", "field": fname, "values_by_source": values})
                src = row.get("_provenance", {}).get(fname)
                if src is not None and values.get(src) != row.get(fname):
                    unexplained.append({"entity": f"{label}:{eid}", "field": fname, "values_by_source": values,
                                        "problem": "built value does not match its stated source"})
    roster = {k: set((parsed.get(ROSTER_SOURCE) or {}).get(k) or {}) for k, _l, _f in _KINDS}
    outside = {
        src: {k: len(set(p.get(k) or {}) - roster[k]) for k, _l, _f in _KINDS}
        for src, p in sorted(parsed.items()) if src != ROSTER_SOURCE
    }
    return {
        "patch": b.version,
        "counts_by_source": counts,
        "excluded_sources": dict(sorted(b.excluded.items())),
        "reconciled_fields": sum(1 for c in b.caveats if c["entity"] != "*"),
        "unexplained": unexplained,
        "not_in_official_roster": outside,
    }


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")
    tmp.replace(path)


def write_build(b: Build, out_dir: Path) -> None:
    """Byte-stable outputs: sorted keys, no timestamps."""
    out_dir = Path(out_dir)
    meta = {"patch": b.version, "sources": b.sources, "excluded": dict(sorted(b.excluded.items()))}
    _dump(out_dir / "champions.json", {"_meta": meta, "champions": b.champions})
    _dump(out_dir / "items.json", {"_meta": meta, "items": b.items})
    _dump(out_dir / "caveats.json", b.caveats)
    _dump(out_dir / "report.json", b.report)


def _diff_map(old: dict, new: dict) -> dict:
    changed = []
    for eid in sorted(set(old) & set(new)):
        o, n = old[eid], new[eid]
        fields = {
            f: [o.get(f), n.get(f)]
            for f in sorted((set(o) | set(n)) - {"_provenance"})
            if o.get(f) != n.get(f)
        }
        if fields:
            changed.append({"id": eid, "fields": fields})
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)), "changed": changed}


def diff_builds(old_dir: Path, new_dir: Path) -> dict:
    """What changed between two built patches (e.g. a new patch's report)."""
    def load(d: Path, name: str) -> dict:
        return json.loads((Path(d) / name).read_text(encoding="ascii"))

    oc, nc = load(old_dir, "champions.json"), load(new_dir, "champions.json")
    oi, ni = load(old_dir, "items.json"), load(new_dir, "items.json")
    # Two builds made from different source sets (an old patch keeps only the
    # era-addressable sources) differ by source mix as well as by patch; say so
    # rather than let a source change read as a balance change.
    return {
        "from": oc["_meta"]["patch"],
        "to": nc["_meta"]["patch"],
        "same_sources": oc["_meta"]["sources"] == nc["_meta"]["sources"],
        "sources": {"from": oc["_meta"]["sources"], "to": nc["_meta"]["sources"]},
        "champions": _diff_map(oc["champions"], nc["champions"]),
        "items": _diff_map(oi["items"], ni["items"]),
    }
