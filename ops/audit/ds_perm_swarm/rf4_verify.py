"""RF4 residual re-run / loop-until-dry verification (audit-only, no engine change).

RF1-RF3 shipped DEFAULT-OFF ``prefer_survivability_by_win`` survivability
item-credit seams for the three scorer lanes the DSP10 consolidated report exposed
as burying WIN-correlated survivability items under a generic template:

  * RF1 (faeaeb4a) - hybrid/bruiser  (``hybrid.rank_items_by_hybrid``)
  * RF2 (ee826cdc) - hps/enchanter   (``hps.rank_items_by_hps``)
  * RF3 (869656a0) - ehp/tank        (``ehp.rank_items_by_ehp``)

This module closes the RF4 loop-until-dry contract (mirror of
``dsp10_pass2_verify`` for the DSP11 kit-axis seam):

1. ``verify_resolved_survivability`` re-ranks each RF-tabled champ in-process with
   the lane's ``prefer_survivability_by_win`` seam OFF vs ON (the live :8893 server
   is seam-OFF, so the cross-eval ``data/`` snapshot the consolidated report reads
   is the seam-OFF default path; the seam-ON ranking is verified by calling the
   scorer directly, the RF1-RF3 regression-test path) and confirms each champ's
   buried survivability winners FLOAT into the top-K (or are INJECTED, the RF2 case)
   under the partition invariant.

2. ``classify_survivability_worst`` (pure, hermetically tested) buckets every row of
   the DSP10 consolidated worst-N report. The swarm is DRY iff NO new
   survivability-class cluster survives: an untabled, non-Cluster-A hybrid/hps/ehp
   champ whose buried winners still form a COHERENT survivability set (>=
   ``min_axis_hits`` WIN-correlated survivability items at >= ``min_defect_lift``
   lift) the RF1-RF3 tables missed.

The dps/burst lane is DSP2/DSP11's (closed by its own loop-until-dry pass); the
ability/mage lane is the deferred DSV1 AP-DoT / Cluster-A archetype lane - neither
is an RF survivability cluster. Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM)
is operator-gated (do-NOT-auto-flip) and bucketed ``cluster_a_deferred``.

Run (needs the live engine; the rewind db is NOT needed - the consolidated report is
already on disk):
    python ops/audit/ds_perm_swarm/rf4_verify.py        # write report/rf4_residual.{json,md}
The hermetic tests (tests/test_rf4_verify.py) synthesize their own rows.
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

# The operator-gated AP-in-ARAM archetype-divergence set (do-NOT-auto-flip). The RF
# builders' ``_EXCLUDE_CHAMPS``; NOT a survivability cluster. (Udyr is a true bruiser
# and is RF1-tabled, so it never lands here.)
CLUSTER_A: frozenset[str] = frozenset({"Zilean", "Shaco", "Kayle", "Seraphine"})

_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_CE_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_OUT_DIR = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"
_LEVEL = 13


def classify_survivability_worst(
    worst_rows: list[dict],
    *,
    rf1_champs: set[str] | frozenset[str],
    rf2_champs: set[str] | frozenset[str],
    rf3_champs: set[str] | frozenset[str],
    cluster_a: set[str] | frozenset[str],
    survivability_names: set[str] | frozenset[str],
    dsp11_champs: set[str] | frozenset[str] = frozenset(),
    min_axis_hits: int = 2,
    min_defect_lift: float = 5.0,
    min_item_n: int = 5,
) -> dict:
    """Bucket each consolidated worst row; return the RF4 dry verdict.

    Pure: takes the report rows + the RF1-RF3 table membership + the survivability
    item-NAME universe, returns a json-serializable classification. ``dry`` is True
    iff no row buckets to NEW_SURVIVABILITY_CLUSTER.

    A NEW_SURVIVABILITY_CLUSTER requires the champ (untabled, non-Cluster-A,
    hybrid/hps/ehp scorer) to bury a COHERENT survivability set: ``>= min_axis_hits``
    buried winners whose NAME is on the survivability allowlist, each with rewind
    ``n >= min_item_n`` AND a lift over baseline ``>= min_defect_lift``. The lift +
    name floor is what separates a true buried-survivability defect (RF1-RF3 tabled
    such items at +11.5 .. +27.1 lift - Darius Force of Nature +18.7, Rell Giant's
    Belt +27.1, KSante Thornmail +11.5) from within-axis cost noise or an off-axis
    DPS item the raw report carries.
    """
    by_champ: dict[str, dict] = {}
    new_clusters: list[dict] = []
    surv_names = set(survivability_names)
    for row in worst_rows:
        champ = row["champion"]
        scorer = (row.get("scorer") or "").strip().lower()
        buried = row.get("buried_winners") or []
        # survivability hits: name on the allowlist + n + lift floors.
        surv_hits = [
            b for b in buried
            if str(b.get("name") or "") in surv_names
            and int(b.get("n") or 0) >= min_item_n
            and float(b.get("lift_over_baseline") or 0.0) >= min_defect_lift
        ]
        n_surv = len(surv_hits)
        top_surv_lift = (
            max(float(b.get("lift_over_baseline") or 0.0) for b in surv_hits)
            if surv_hits else 0.0
        )

        if champ in rf1_champs:
            cat = "covered_rf1"
        elif champ in rf2_champs:
            cat = "covered_rf2"
        elif champ in rf3_champs:
            cat = "covered_rf3"
        elif champ in cluster_a:
            cat = "cluster_a_deferred"
        elif scorer in ("dps", "burst"):
            cat = "covered_dsp11" if champ in dsp11_champs else "dps_burst_lane"
        elif scorer == "ability":
            cat = "ability_mage_lane"
        elif scorer in ("hybrid", "hps", "ehp"):
            if not buried:
                cat = "no_buried"
            elif n_surv >= min_axis_hits:
                cat = "NEW_SURVIVABILITY_CLUSTER"
            else:
                cat = "thin_or_noise"
        else:
            cat = "other_scorer"

        rec = {
            "category": cat,
            "scorer": scorer,
            "n_buried": len(buried),
            "n_surv_hits": n_surv,
            "top_surv_lift": round(top_surv_lift, 2),
            "surv_hit_ids": [str(b.get("id")) for b in surv_hits],
        }
        by_champ[champ] = rec
        if cat == "NEW_SURVIVABILITY_CLUSTER":
            new_clusters.append({"champion": champ, **rec})

    return {
        "n_worst": len(worst_rows),
        "by_champion": by_champ,
        "new_clusters": new_clusters,
        "dry": not new_clusters,
    }


# --- live-data path (engine present; rewind db NOT needed) -------------------


def _anchor_mode(champ: str) -> str:
    """Anchor mode from the champ's cross-eval data file; 'ARAM' if absent."""
    fp = _CE_DIR / f"{champ}.json"
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        return d.get("anchor_mode") or "ARAM"
    except Exception:  # noqa: BLE001 - fail-soft to the dominant anchor mode
        return "ARAM"


def _table_champs(path: Path) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return sorted((raw.get("champions") or {}).keys())
    except Exception:  # noqa: BLE001
        return []


def _rf_tables() -> dict[str, list[str]]:
    ds = _ROOT / "agents" / "daemon_slayer"
    return {
        "rf1": _table_champs(ds / "survivability_item_credit.json"),
        "rf2": _table_champs(ds / "survivability_item_credit_enchanter.json"),
        "rf3": _table_champs(ds / "survivability_item_credit_tank.json"),
    }


def _survivability_names() -> set[str]:
    """Union of the three RF builders' survivability item-NAME allowlists."""
    from ops.audit.ds_perm_swarm.build_survivability_item_credit import (
        _SURVIVABILITY_NAMES as _N1,
    )
    from ops.audit.ds_perm_swarm.build_survivability_item_credit_enchanter import (
        _SURVIVABILITY_NAMES as _N2,
    )
    from ops.audit.ds_perm_swarm.build_survivability_item_credit_tank import (
        _SURVIVABILITY_NAMES as _N3,
    )
    return set(_N1) | set(_N2) | set(_N3)


def _dsp11_champs() -> set[str]:
    try:
        from ops.audit.ds_perm_swarm.build_kit_axis_item_credit import _CHAMP_AXIS
        return set(_CHAMP_AXIS)
    except Exception:  # noqa: BLE001
        return set()


def verify_resolved_survivability(top_k: int = 6) -> list[dict]:
    """Re-rank each RF-tabled champ seam OFF vs ON in-process; confirm resolved.

    A champ is RESOLVED when the seam-ON ranking is partitioned (survivability rows
    first) AND at least one of its tabled survivability items that was buried
    (outside the OFF top-K) floats into the ON top-K. RF2 inject items (absent OFF
    under ``enchanter_only``) count as floated when they reach the ON top-K. Mirrors
    the RF1-RF3 regression-test path.
    """
    from agents.daemon_slayer import survivability_credit
    from agents.daemon_slayer.abilities import reset_default_cache
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.ehp import rank_items_by_ehp
    from agents.daemon_slayer.hps import rank_items_by_hps
    from agents.daemon_slayer.hybrid import rank_items_by_hybrid

    reset_default_cache()
    survivability_credit.reset_cache()
    snap = DataSnapshot.load()
    tables = _rf_tables()
    lanes = [
        ("rf1", "hybrid", rank_items_by_hybrid, tables["rf1"],
         survivability_credit.survivability_item_ids),
        ("rf2", "hps", rank_items_by_hps, tables["rf2"],
         survivability_credit.survivability_item_ids_enchanter),
        ("rf3", "ehp", rank_items_by_ehp, tables["rf3"],
         survivability_credit.survivability_item_ids_tank),
    ]
    out: list[dict] = []
    for rf, lane, fn, champs, id_fn in lanes:
        for champ in champs:
            mode = _anchor_mode(champ)
            off = fn(snap, champ, _LEVEL, mode=mode, top_n=45)
            on = fn(snap, champ, _LEVEL, mode=mode, top_n=45,
                    prefer_survivability_by_win=True)
            off_top = [r.item_id for r in off.ranked[:top_k]]
            on_top = [r.item_id for r in on.ranked[:top_k]]
            off_ids = {r.item_id for r in off.ranked}
            surfaced = [r.item_id for r in on.ranked if r.survivability_score > 0.0]
            # partition invariant: all survivability rows precede all non-survivability
            seen_zero = False
            partitioned = True
            for r in on.ranked:
                if r.survivability_score <= 0.0:
                    seen_zero = True
                elif seen_zero:
                    partitioned = False
                    break
            floated = [i for i in surfaced if i in on_top and i not in off_top]
            injected = [i for i in surfaced if i not in off_ids]
            resolved = partitioned and bool(floated)
            out.append({
                "rf": rf,
                "champion": champ,
                "lane": lane,
                "mode": mode,
                "tabled_ids": sorted(id_fn(champ)),
                "off_top": off_top,
                "on_top": on_top,
                "surfaced": surfaced,
                "floated_into_top": floated,
                "injected": injected,
                "partitioned": partitioned,
                "resolved": resolved,
            })
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _render_md(report: dict) -> str:
    res = report["resolved"]
    cls = report["classification"]
    residuals = report.get("resolution_residuals") or []
    lines = [
        "# RF4 Residual Re-run - Loop-Until-Dry Verification",
        "",
        f"loop-until-dry: {'SATISFIED' if report['cluster_dry'] else 'NOT DRY'} "
        f"({len(cls['new_clusters'])} new survivability cluster(s), 1 pass)",
        f"RF1-RF3 tabled champs resolved: {sum(1 for r in res if r['resolved'])}/{len(res)}"
        + (f" - residual: {', '.join(residuals)}" if residuals else ""),
        f"worst-N rows classified: {cls['n_worst']}",
        "",
        "## RF1-RF3 seam-ON resolution (in-process re-rank, OFF vs ON)",
        "",
    ]
    for r in res:
        mark = "RESOLVED" if r["resolved"] else "NOT-RESOLVED"
        detail = (
            f"floated={r['floated_into_top']}"
            if r["floated_into_top"] else f"injected={r['injected']}"
        )
        lines.append(
            f"- [{r['rf']}] {r['champion']} ({r['lane']}/{r['mode']}) {mark}: "
            f"OFF{r['off_top']} -> ON{r['on_top']}; {detail}"
        )
    lines += ["", "## Worst-N classification", ""]
    buckets: dict[str, list[str]] = {}
    for champ, rec in cls["by_champion"].items():
        buckets.setdefault(rec["category"], []).append(champ)
    for cat in sorted(buckets):
        lines.append(f"- {cat} ({len(buckets[cat])}): {', '.join(sorted(buckets[cat]))}")
    lines.append("")
    if residuals:
        lines.append("## Resolution residuals (existing RF table, float-seam no-op - QUEUED)")
        for r in res:
            if r["resolved"]:
                continue
            lines.append(
                f"- [{r['rf']}] {r['champion']} ({r['lane']}): tabled {r['tabled_ids']} "
                f"NOT pooled by the scorer -> the float-only seam cannot surface it "
                f"(needs an INJECT mode, RF2's shape). NOT a new cluster; queued (RF6)."
            )
        lines.append("")
    if cls["new_clusters"]:
        lines.append("## NEW survivability clusters (loop continues)")
        for d in cls["new_clusters"]:
            lines.append(
                f"- {d['champion']} ({d['scorer']}) surv_hits={d['n_surv_hits']} "
                f"top_lift={d['top_surv_lift']} ids={d['surv_hit_ids']}"
            )
    else:
        lines.append(
            "## NEW survivability clusters: NONE - the swarm is DRY. The remaining "
            "divergent tail is Cluster A (operator-gated AP-in-ARAM), the dps/burst "
            "lane (DSP2/DSP11, its own closed loop), the ability/mage lane (deferred "
            "DSV1 AP-DoT valuation), no-buried, and thin-sample / cost-axis noise. "
            "RF4 loop-until-dry satisfied (1 no-new-cluster pass)."
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RF4 residual loop-until-dry verification")
    ap.add_argument("--report", default=str(_REPORT))
    ap.add_argument("--out-dir", default=str(_OUT_DIR))
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--min-axis-hits", type=int, default=2)
    ap.add_argument("--min-defect-lift", type=float, default=5.0)
    args = ap.parse_args(argv)

    rp = Path(args.report)
    if not rp.exists():
        print(f"[rf4] consolidated report not found: {rp}")
        return 2
    worst = json.loads(rp.read_text(encoding="utf-8")).get("worst", [])

    tables = _rf_tables()
    resolved = verify_resolved_survivability(top_k=args.top_k)
    classification = classify_survivability_worst(
        worst,
        rf1_champs=set(tables["rf1"]),
        rf2_champs=set(tables["rf2"]),
        rf3_champs=set(tables["rf3"]),
        cluster_a=CLUSTER_A,
        survivability_names=_survivability_names(),
        dsp11_champs=_dsp11_champs(),
        min_axis_hits=args.min_axis_hits,
        min_defect_lift=args.min_defect_lift,
    )
    residuals = [r["champion"] for r in resolved if not r["resolved"]]
    report = {
        "dry": classification["dry"] and all(r["resolved"] for r in resolved),
        "cluster_dry": classification["dry"],
        "resolution_residuals": residuals,
        "resolved": resolved,
        "classification": classification,
    }
    out = Path(args.out_dir)
    _atomic_write(out / "rf4_residual.json", json.dumps(report, indent=2))
    _atomic_write(out / "rf4_residual.md", _render_md(report))
    n_res = sum(1 for r in resolved if r["resolved"])
    print(
        f"[rf4] resolved {n_res}/{len(resolved)} RF-tabled champs; "
        f"new survivability clusters: {len(classification['new_clusters'])}; "
        f"DRY={report['dry']}; wrote {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
