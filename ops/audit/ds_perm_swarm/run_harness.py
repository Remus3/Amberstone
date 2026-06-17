"""DSP1 CLI: score the live DS cross-eval rankings against rewind_history.db WIN data
and write an atomic per-(champ x mode) report.

    python ops/audit/ds_perm_swarm/run_harness.py [--db PATH] [--cross-eval-dir DIR]
        [--out-dir DIR] [--top-k 6] [--min-item-n 5]

Outputs report/perm_anchor_report.json + report/perm_anchor_report.md. The 1.8GB
rewind_history.db is gitignored; this CLI needs it present (dev box / Legion). The
hermetic tests do NOT - they synthesize their own sqlite + cross-eval fixtures.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# Allow `python ops/audit/ds_perm_swarm/run_harness.py` (script form) to import the package.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ops.audit.ds_perm_swarm.cross_eval_loader import load_cross_eval_dir  # noqa: E402
from ops.audit.ds_perm_swarm.perm_score import PermConfig, build_report  # noqa: E402
from ops.audit.ds_perm_swarm.win_anchor import compute_win_rates  # noqa: E402

_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_CE = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_DEFAULT_OUT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _render_md(report: dict) -> str:
    agg = report["aggregate"]
    cfg = report["config"]
    lines = [
        "# DS Permutation Swarm - WIN-Anchor Report (DSP1)",
        "",
        f"top_k={cfg['top_k']} min_item_n={cfg['min_item_n']} modes={','.join(cfg['modes'])}",
        "",
        "## Aggregate",
        "",
        f"- champ-mode considered: {agg['n_champ_mode_considered']}",
        f"- champ-mode scored (DS-favored items have rewind data): {agg['n_champs_scored']}",
        f"- positive lift (DS favors winners): {agg['n_positive_lift']} ({agg['pct_positive_lift']}%)",
        f"- mean lift weighted-by-games: {agg['mean_lift_weighted']}",
        f"- mean lift unweighted: {agg['mean_lift_unweighted']}",
        "",
        "## Top outcome-aligned (champ x mode, by mean lift)",
        "",
        "| champ | mode | n | baseline_wr | mean_lift |",
        "|---|---|---|---|---|",
    ]
    for row in report["champs"][:25]:
        lines.append(
            f"| {row['champion']} | {row['mode']} | {row['n_games']} | "
            f"{row['baseline_wr']} | {row['mean_lift']} |"
        )
    lines.append("")
    lines.append("## Most outcome-divergent (DS favors losers, by lowest lift)")
    lines.append("")
    lines.append("| champ | mode | n | baseline_wr | mean_lift |")
    lines.append("|---|---|---|---|---|")
    scored = [r for r in report["champs"] if r["mean_lift"] is not None]
    for row in sorted(scored, key=lambda r: r["mean_lift"])[:25]:
        lines.append(
            f"| {row['champion']} | {row['mode']} | {row['n_games']} | "
            f"{row['baseline_wr']} | {row['mean_lift']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DSP1 DS-vs-WIN permutation anchor harness")
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--cross-eval-dir", default=str(_DEFAULT_CE))
    ap.add_argument("--out-dir", default=str(_DEFAULT_OUT))
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--min-item-n", type=int, default=5)
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"[dsp1] rewind db not found: {db} (gitignored; run on a box that has it)")
        return 2
    ce_dir = Path(args.cross_eval_dir)
    if not ce_dir.exists():
        print(f"[dsp1] cross-eval dir not found: {ce_dir}")
        return 2

    cfg = PermConfig(top_k=args.top_k, min_item_n=args.min_item_n)
    cross = load_cross_eval_dir(ce_dir)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        win = compute_win_rates(conn)
    finally:
        conn.close()
    report = build_report(cross, win, cfg)

    out = Path(args.out_dir)
    _atomic_write(out / "perm_anchor_report.json", json.dumps(report, indent=2))
    _atomic_write(out / "perm_anchor_report.md", _render_md(report))
    agg = report["aggregate"]
    print(
        f"[dsp1] scored {agg['n_champs_scored']} champ-modes; "
        f"positive_lift={agg['n_positive_lift']} "
        f"mean_lift_weighted={agg['mean_lift_weighted']}; wrote {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
