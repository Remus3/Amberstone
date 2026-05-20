"""tools/lessons_status.py - read-only status surface for the cross-Claude
lesson sync (Phase 4).

Runs the ack-watcher refresh (no-op when offline), then prints:

  - sender ledger summary: total / acked / unacked / took / took_rate
  - per-(peer, mem_type) confidence buckets with smoothed apply/took rates
  - newly-acked lesson ids from this refresh

Usage:
    py tools/lessons_status.py              # refresh + print JSON
    py tools/lessons_status.py --no-refresh # snapshot only (skip bridge)
    py tools/lessons_status.py --plain      # human-readable tabular print
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import lessons_ack_watcher as _watcher  # noqa: E402
from core import lessons_confidence as _conf       # noqa: E402


def _format_plain(report: dict) -> str:
    lines: list[str] = []
    s = report["summary"]
    lines.append("=== sender ledger ===")
    lines.append(f"total_sent={s['total_sent']} acked={s['acked']} "
                 f"unacked={s['unacked']} took={s['took']} "
                 f"took_rate={s['took_rate']:.3f}")
    if s["decisions"]:
        decs = " ".join(f"{k}={v}" for k, v in sorted(s["decisions"].items()))
        lines.append(f"decisions: {decs}")
    refresh = report.get("refresh") or {}
    if refresh:
        lines.append("=== refresh ===")
        lines.append(f"fetched_results={refresh.get('fetched_results')} "
                     f"unacked_before={refresh.get('unacked_before')} "
                     f"unacked_after={refresh.get('unacked_after')} "
                     f"newly_acked={refresh.get('newly_acked_count')}")
        if refresh.get("newly_acked"):
            lines.append("newly acked: " + ", ".join(refresh["newly_acked"]))
    lines.append("=== confidence (smoothed) ===")
    conf = report.get("confidence") or {}
    buckets = conf.get("buckets") or {}
    if not buckets:
        lines.append("(no data)")
    else:
        lines.append(f"{'bucket':<32} {'sent':>4} {'ack':>3} {'took':>4} "
                     f"{'rcv':>4} {'app':>3} {'que':>3} {'dis':>3} "
                     f"{'apply_rate':>10} {'took_rate':>9} {'conf':>5}")
        for key in sorted(buckets):
            b = buckets[key]
            lines.append(
                f"{key:<32} {b['sent']:>4} {b['acked']:>3} {b['took']:>4} "
                f"{b['received']:>4} {b['applied']:>3} {b['queued']:>3} "
                f"{b['discarded']:>3} {b['apply_rate']:>10.3f} "
                f"{b['took_rate']:>9.3f} {b['confidence']:>5.3f}"
            )
        t = conf.get("totals") or {}
        lines.append(
            f"{'TOTAL':<32} {t.get('sent', 0):>4} {t.get('acked', 0):>3} "
            f"{t.get('took', 0):>4} {t.get('received', 0):>4} "
            f"{t.get('applied', 0):>3} {t.get('queued', 0):>3} "
            f"{t.get('discarded', 0):>3} {t.get('apply_rate', 0.0):>10.3f} "
            f"{t.get('took_rate', 0.0):>9.3f} {t.get('confidence', 0.0):>5.3f}"
        )
    return "\n".join(lines)


def build_report(*, refresh: bool = True) -> dict:
    """Public helper - the dashboard route calls this directly."""
    refresh_payload: dict = {}
    if refresh:
        rep = _watcher.update_sent_acks()
        refresh_payload = rep.to_dict()
    return {
        "summary": _watcher.summarize(),
        "refresh": refresh_payload,
        "confidence": _conf.compute_confidence(),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lessons_status")
    p.add_argument("--no-refresh", action="store_true",
                   help="skip the ack-watcher refresh (read-only snapshot)")
    p.add_argument("--plain", action="store_true",
                   help="human-readable tabular output (default = JSON)")
    args = p.parse_args(argv)
    report = build_report(refresh=not args.no_refresh)
    if args.plain:
        print(_format_plain(report))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
