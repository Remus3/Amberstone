"""lessons_send.py — fire kind=lesson envelopes for eligible memories.

Operator-driven; not on a /loop. Run after flipping `cross_project: true`
on memories you want to share with the peer.

Usage:
    py tools/lessons_send.py                  # send all eligible-and-new
    py tools/lessons_send.py --only <basename> # smoke a single memory file
    py tools/lessons_send.py --dry-run        # alias for tools/lessons_send_dryrun.py

Reads cross_project + applies_when frontmatter (per Phase 1 §1), builds
envelopes per §2, dedupes against ops/runtime/lessons_sent.jsonl, then
POSTs each via core.bridge.send(). On success the ledger row carries
`ack_received: False` until the peer's kind=result reply lands — track
that via the ack-watcher (TBD) or by grepping bridge log for
`in_reply_to=<lesson_id>`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import lessons_sender  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", default=None,
                   help="restrict to a single memory file (basename)")
    p.add_argument("--dry-run", action="store_true",
                   help="don't actually send; report what would be sent")
    args = p.parse_args()
    if args.dry_run:
        print(json.dumps(lessons_sender.dry_run(), indent=2, ensure_ascii=False))
        return 0
    rep = lessons_sender.send_now(only_path=args.only)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if not rep.get("ok"):
        return 1
    return 0 if all(r.get("send_ok", True) for r in rep.get("results", [])) else 1


if __name__ == "__main__":
    sys.exit(main())
