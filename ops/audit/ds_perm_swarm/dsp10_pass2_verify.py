"""DSP10 pass-2 loop-until-dry verification (audit-only, no engine change).

Pass 1 (7b96328f) surfaced the Cluster-B2 kit-axis item-crediting defect; DSP11
(0c2b88e5) shipped the DEFAULT-OFF ``prefer_kit_axis_by_win`` seam that fixes it.
This module closes the loop-until-dry contract:

1. ``verify_resolved`` re-ranks each DSP11-tabled champ in-process with the seam
   OFF vs ON (the live :8893 server is seam-OFF, so the cross-eval ``data/`` files
   are the default-path snapshot; the seam-ON ranking is verified by calling the
   scorer directly, the DSP11 test path) and confirms the buried kit-axis items
   float into the top-K - i.e. the named B2 defects (Pyke / Nilah / Ezreal / ...)
   are resolved in the rankings.

2. ``classify_worst`` (pure, hermetically tested) buckets every row of the DSP10
   consolidated worst-N report. The swarm is DRY iff NO new B2-class defect
   survives: an untabled, non-Cluster-A dps/burst champ whose buried winners
   still form a coherent kit-axis set (>= ``min_axis_hits`` items from one axis)
   the DSP11 table missed. AP-mage / bruiser / tank scorers are a separate lane
   (the DSV1 AP-DoT / archetype-routing work), not B2; pure-crit-ADC single-item
   divergence is within-axis cost noise (the DSP11 "pure crit ADCs untouched"
   rationale).

Cluster A (Zilean / Shaco / Kayle / Seraphine / Udyr AP-in-ARAM archetype
divergence) is an operator-gated policy decision (do-NOT-auto-flip) and is
bucketed ``cluster_a_deferred``, never a new defect.

Run (needs the live engine + gitignored rewind data, Legion/dev box):
    python ops/audit/ds_perm_swarm/dsp10_pass2_verify.py        # write report
The hermetic tests (tests/test_dsp10_pass2.py) synthesize their own rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The DSP10/DSP11 named operator-gated archetype-divergence cluster. Not B2.
CLUSTER_A: frozenset[str] = frozenset(
    {"Zilean", "Shaco", "Kayle", "Seraphine", "Udyr"}
)

_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_CE_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_OUT_DIR = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"
_LEVEL = 13


def classify_worst(
    worst_rows: list[dict],
    *,
    tabled_champs: set[str] | frozenset[str],
    cluster_a: set[str] | frozenset[str],
    axis_item_sets: dict[str, set[str]],
    min_axis_hits: int = 2,
    min_defect_lift: float = 5.0,
) -> dict:
    """Bucket each consolidated worst row; return the dry verdict.

    Pure: takes the report rows + the DSP11 table membership + the kit-axis item
    universe, returns a json-serializable classification. ``dry`` is True iff no
    row buckets to NEW_B2_DEFECT.

    A NEW_B2_DEFECT requires the champ (untabled, non-Cluster-A, dps/burst scorer)
    to bury a COHERENT kit-axis set: ``>= min_axis_hits`` buried winners on one
    axis AND that axis's strongest buried winner carrying a lift over baseline
    ``>= min_defect_lift``. The lift floor is what separates a true off-axis B2
    defect (the DSP11-tabled champs buried kit-axis winners at +5.8 .. +15.8 lift -
    Pyke Opportunity +6.1, Nilah Immortal Shieldbow +15.8, Senna Black Cleaver
    +11.5, Quinn Infinity Edge +6.5) from within-axis cost noise (a pure ranged
    crit marksman whose model already targets crit and only differs on WHICH crit
    item by a marginal lift - Caitlyn's strongest buried crit item is LDR at +3.4).
    Mode-2 exclusion defects (an off-class hard-stripped staple at ~baseline wr,
    e.g. Ezreal/Corki Trinity) are an off-class-deny concern already carried by the
    DSP11 table, not this burial lens.
    """
    by_champ: dict[str, dict] = {}
    new_defects: list[dict] = []
    for row in worst_rows:
        champ = row["champion"]
        scorer = (row.get("scorer") or "").strip().lower()
        buried = row.get("buried_winners") or []
        buried_ids = [str(b.get("id")) for b in buried]
        lift_by_id = {
            str(b.get("id")): float(b.get("lift_over_baseline") or 0.0) for b in buried
        }
        # per kit-axis: the buried ids that land on it + the strongest lift among them
        axis_hits: dict[str, list[str]] = {}
        axis_max_lift: dict[str, float] = {}
        for ax, ids in axis_item_sets.items():
            hits = [i for i in buried_ids if i in ids]
            if hits:
                axis_hits[ax] = hits
                axis_max_lift[ax] = max(lift_by_id.get(i, 0.0) for i in hits)
        # the dominant axis: most hits, tiebreak by strongest lift
        top_axis = (
            max(axis_hits, key=lambda a: (len(axis_hits[a]), axis_max_lift[a]))
            if axis_hits else None
        )
        max_hits = len(axis_hits[top_axis]) if top_axis else 0
        top_lift = axis_max_lift.get(top_axis, 0.0) if top_axis else 0.0

        if champ in tabled_champs:
            cat = "covered_dsp11"
        elif champ in cluster_a:
            cat = "cluster_a_deferred"
        elif not buried_ids:
            cat = "no_buried"
        elif scorer not in ("dps", "burst"):
            cat = "other_scorer"
        elif max_hits >= min_axis_hits and top_lift >= min_defect_lift:
            cat = "NEW_B2_DEFECT"
        else:
            cat = "within_axis_noise"

        rec = {
            "category": cat,
            "scorer": scorer,
            "n_buried": len(buried_ids),
            "top_axis": top_axis,
            "top_axis_lift": round(top_lift, 2),
            "axis_hits": dict(axis_hits),
        }
        by_champ[champ] = rec
        if cat == "NEW_B2_DEFECT":
            new_defects.append({"champion": champ, **rec})

    return {
        "n_worst": len(worst_rows),
        "by_champion": by_champ,
        "new_b2_defects": new_defects,
        "dry": not new_defects,
    }


# --- live-data path (engine + rewind present) -------------------------------


def _scorer_for(champ: str) -> tuple[str, str]:
    """(scorer, anchor_mode) from the champ's cross-eval data file; ('', '') if absent."""
    fp = _CE_DIR / f"{champ}.json"
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        return (d.get("scorer") or "", d.get("anchor_mode") or "ARAM")
    except Exception:  # noqa: BLE001
        return ("", "ARAM")


def verify_resolved(top_k: int = 6) -> list[dict]:
    """Re-rank each DSP11-tabled champ seam OFF vs ON in-process; confirm resolved.

    A champ is RESOLVED when the seam-ON ranking is partitioned (kit-axis rows
    first) AND at least one of its kit-axis items that was buried (outside the
    OFF top-K) floats into the ON top-K. Mirrors the DSP11 regression-test path.
    """
    from agents.daemon_slayer import kit_axis_credit
    from agents.daemon_slayer.abilities import reset_default_cache
    from agents.daemon_slayer.burst import rank_items_by_burst
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.rank import rank_items

    from ops.audit.ds_perm_swarm.build_kit_axis_item_credit import _CHAMP_AXIS  # noqa: E501

    reset_default_cache()
    kit_axis_credit.reset_cache()
    snap = DataSnapshot.load()
    out: list[dict] = []
    for champ in sorted(_CHAMP_AXIS):
        scorer, mode = _scorer_for(champ)
        fn = rank_items_by_burst if scorer == "burst" else rank_items
        off = fn(snap, champ, _LEVEL, mode=mode, top_n=45)
        on = fn(snap, champ, _LEVEL, mode=mode, top_n=45,
                prefer_kit_axis_by_win=True)
        off_top = [r.item_id for r in off.ranked[:top_k]]
        on_top = [r.item_id for r in on.ranked[:top_k]]
        axis_ids = kit_axis_credit.kit_axis_item_ids(champ)
        surfaced = [r.item_id for r in on.ranked if r.kit_axis_score > 0.0]
        # partition invariant: all kit-axis rows precede all non-axis rows
        seen_zero = False
        partitioned = True
        for r in on.ranked:
            if r.kit_axis_score <= 0.0:
                seen_zero = True
            elif seen_zero:
                partitioned = False
                break
        floated = [i for i in surfaced if i not in off_top and i in on_top]
        # un-strip case (Ezreal Trinity): item absent OFF, present anywhere ON
        unstripped = [
            i for i in axis_ids
            if i not in {r.item_id for r in off.ranked}
            and i in {r.item_id for r in on.ranked}
        ]
        resolved = partitioned and bool(floated or unstripped)
        out.append({
            "champion": champ,
            "scorer": scorer or "?",
            "mode": mode,
            "off_top": off_top,
            "on_top": on_top,
            "surfaced_kit_axis": surfaced,
            "floated_into_top": floated,
            "unstripped": unstripped,
            "partitioned": partitioned,
            "resolved": resolved,
        })
    return out


def _axis_item_sets() -> dict[str, set[str]]:
    from ops.audit.ds_perm_swarm.build_kit_axis_item_credit import _AXIS_ITEM_IDS
    return {ax: set(ids) for ax, ids in _AXIS_ITEM_IDS.items()}


def _tabled() -> set[str]:
    from ops.audit.ds_perm_swarm.build_kit_axis_item_credit import _CHAMP_AXIS
    return set(_CHAMP_AXIS)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _render_md(report: dict) -> str:
    res = report["resolved"]
    cls = report["classification"]
    lines = [
        "# DSP10 Pass 2 - Loop-Until-Dry Verification",
        "",
        f"verdict: {'DRY' if report['dry'] else 'NOT DRY'} "
        f"({len(cls['new_b2_defects'])} new B2 defect(s))",
        f"tabled champs resolved: {sum(1 for r in res if r['resolved'])}/{len(res)}",
        f"worst-N rows classified: {cls['n_worst']}",
        "",
        "## DSP11 seam-ON resolution (in-process re-rank, OFF vs ON)",
        "",
    ]
    for r in res:
        mark = "RESOLVED" if r["resolved"] else "NOT-RESOLVED"
        detail = (
            f"floated={r['floated_into_top']}"
            if r["floated_into_top"] else f"unstripped={r['unstripped']}"
        )
        lines.append(
            f"- {r['champion']} ({r['scorer']}/{r['mode']}) {mark}: "
            f"OFF{r['off_top']} -> ON{r['on_top']}; {detail}"
        )
    lines += ["", "## Worst-N classification", ""]
    buckets: dict[str, list[str]] = {}
    for champ, rec in cls["by_champion"].items():
        buckets.setdefault(rec["category"], []).append(champ)
    for cat in sorted(buckets):
        lines.append(f"- {cat} ({len(buckets[cat])}): {', '.join(sorted(buckets[cat]))}")
    lines.append("")
    if cls["new_b2_defects"]:
        lines.append("## NEW B2 defects (loop continues)")
        for d in cls["new_b2_defects"]:
            lines.append(f"- {d['champion']} [{d['top_axis']}] {d['axis_hits']}")
    else:
        lines.append(
            "## NEW B2 defects: NONE - the swarm is DRY. The only divergent tail is "
            "Cluster A (operator-gated), other-scorer AP/bruiser lanes, no-buried, and "
            "within-axis cost noise. DSP10 loop-until-dry satisfied."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DSP10 pass-2 loop-until-dry verification")
    ap.add_argument("--report", default=str(_REPORT))
    ap.add_argument("--out-dir", default=str(_OUT_DIR))
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--min-axis-hits", type=int, default=2)
    args = ap.parse_args(argv)

    rp = Path(args.report)
    if not rp.exists():
        print(f"[dsp10-pass2] consolidated report not found: {rp}")
        return 2
    worst = json.loads(rp.read_text(encoding="utf-8")).get("worst", [])

    resolved = verify_resolved(top_k=args.top_k)
    classification = classify_worst(
        worst,
        tabled_champs=_tabled(),
        cluster_a=CLUSTER_A,
        axis_item_sets=_axis_item_sets(),
        min_axis_hits=args.min_axis_hits,
    )
    report = {
        "dry": classification["dry"] and all(r["resolved"] for r in resolved),
        "resolved": resolved,
        "classification": classification,
    }
    out = Path(args.out_dir)
    _atomic_write(out / "dsp10_pass2.json", json.dumps(report, indent=2))
    _atomic_write(out / "dsp10_pass2.md", _render_md(report))
    n_res = sum(1 for r in resolved if r["resolved"])
    print(
        f"[dsp10-pass2] resolved {n_res}/{len(resolved)} tabled champs; "
        f"new B2 defects: {len(classification['new_b2_defects'])}; "
        f"DRY={report['dry']}; wrote {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
