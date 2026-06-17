"""DSP10 CLI: write the consolidated mismatch report (worst-N anchor-matched champ-
modes, DS-top vs buried empirical winners) to report/dsp10_consolidated.{json,md}.

    python ops/audit/ds_perm_swarm/run_consolidate.py [--db PATH] [--cross-eval-dir DIR]
        [--out-dir DIR] [--top-k 6] [--min-item-n 5] [--worst-n 40]

Needs the gitignored data/rewind_history.db present (dev box / Legion). The hermetic
tests synthesize their own sqlite + cross-eval fixtures and never touch it.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ops.audit.ds_perm_swarm.consolidate import consolidate  # noqa: E402
from ops.audit.ds_perm_swarm.cross_eval_loader import load_cross_eval_dir  # noqa: E402
from ops.audit.ds_perm_swarm.perm_score import PermConfig  # noqa: E402
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
    cfg = report["config"]
    lines = [
        "# DS Permutation Swarm - Consolidated Mismatch Report (DSP10)",
        "",
        f"top_k={cfg['top_k']} min_item_n={cfg['min_item_n']} worst_n={cfg['worst_n']}",
        f"consolidated (anchor-matched, scored) champ-modes: {report['n_consolidated']}",
        "",
        "Each row: DS-favored top-K (union across target-preset buckets, with live "
        "rewind n/wr) vs the above-baseline empirical winners DS buries. A per-champion "
        "fix should lift the buried winners; an empty buried list = DS already favors "
        "the winners (the negative lift is thin-sample / cost-axis noise).",
        "",
    ]
    for m in report["worst"]:
        lines.append(
            f"## {m['champion']} ({m['mode']}) - {m['scorer']}/{m['archetype']} "
            f"- n={m['n_games']} base_wr={m['baseline_wr']} mean_lift={m['mean_lift']}"
        )
        lines.append("")
        lines.append("DS top (rank: item [rewind n/wr]):")
        ds = ", ".join(
            f"{v['best_rank']}:{v['name']}"
            f"[{v['rewind_n']}/{v['rewind_wr'] if v['rewind_wr'] is not None else '-'}]"
            for v in m["ds_top"]
        )
        lines.append(f"  {ds if ds else '(none)'}")
        lines.append("")
        if m["buried_winners"]:
            lines.append("BURIED winners (item n/wr +lift):")
            bw = ", ".join(
                f"{b['name']}[{b['n']}/{b['wr']} +{b['lift_over_baseline']}]"
                for b in m["buried_winners"]
            )
            lines.append(f"  {bw}")
        else:
            lines.append("BURIED winners: (none - DS already favors the winning items)")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DSP10 consolidated mismatch report")
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--cross-eval-dir", default=str(_DEFAULT_CE))
    ap.add_argument("--out-dir", default=str(_DEFAULT_OUT))
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--min-item-n", type=int, default=5)
    ap.add_argument("--worst-n", type=int, default=40)
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"[dsp10] rewind db not found: {db} (gitignored; run where it exists)")
        return 2
    ce_dir = Path(args.cross_eval_dir)
    if not ce_dir.exists():
        print(f"[dsp10] cross-eval dir not found: {ce_dir}")
        return 2

    cfg = PermConfig(top_k=args.top_k, min_item_n=args.min_item_n)
    cross = load_cross_eval_dir(ce_dir)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        win = compute_win_rates(conn)
    finally:
        conn.close()
    report = consolidate(cross, win, cfg, worst_n=args.worst_n)

    out = Path(args.out_dir)
    _atomic_write(out / "dsp10_consolidated.json", json.dumps(report, indent=2))
    _atomic_write(out / "dsp10_consolidated.md", _render_md(report))
    print(
        f"[dsp10] consolidated {report['n_consolidated']} champ-modes; "
        f"wrote worst {len(report['worst'])} to {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
