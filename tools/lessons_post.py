"""lessons_post.py — finalize one inbound lesson with a Claude-decided
outcome. Writes the provenance memory, updates MEMORY.md, appends a
ledger entry, and sends the ack back to the peer.

Usage:
    py tools/lessons_post.py <lesson_id> --decision applied|queued|discarded \\
        --rationale "<one-line>" [--notes "<receiver notes>"]

Decision semantics (per Phase 1 §4):
  applied    — tooling/infra/config pattern; provenance memory written
               with status: applied; appears in MEMORY.md immediately.
  queued     — discipline / process / architecture-adjacent; provenance
               memory written with status: pending_apply; surfaces in
               WAKEUP_NOTES until operator flips status to applied.
  discarded  — domain-bound (slipped past sender filter); no memory
               file is written; ledger records the rationale.

`reject` is auto-only (schema-version mismatch); `skipped_neg_match` is
auto-only (does_not_apply_when matched). Both happen in lessons_pull.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import lessons_receiver  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("lesson_id", help="id of the lesson being finalized")
    p.add_argument("--decision", required=True,
                   choices=sorted(lessons_receiver.VALID_DECISIONS),
                   help="applied | queued | discarded")
    p.add_argument("--rationale", required=True,
                   help="one-line reason for this decision (logged + acked)")
    p.add_argument("--notes", default="",
                   help="optional receiver-side adaptation notes; written "
                        "into the provenance memory's '## Receiver notes' "
                        "section. Defaults to the rationale.")
    args = p.parse_args()
    try:
        entry = lessons_receiver.post_decision(
            lesson_id=args.lesson_id,
            decision=args.decision,
            rationale=args.rationale,
            receiver_notes=args.notes,
        )
    except (ValueError, LookupError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    out = {"ok": True, **entry}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if entry.get("ack_ok") else 1


if __name__ == "__main__":
    sys.exit(main())
