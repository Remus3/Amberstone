"""lessons_pull.py — fetch unhandled kind=lesson envelopes targeted at RC.

Mirrors bridge_pull_tasks.py for lessons. Runs the cheap auto-gates
(schema_version, does_not_apply_when) inline and prints the remainder
as JSON for the slash command to triage.

Output schema:
    {
      "now": <ts>,
      "fetched_total": <n>,
      "auto_handled_count": <n>,        # rejected + skipped_neg_match
      "auto_handled": [ledger entries],
      "pending_count": <n>,
      "pending": [<full lesson envelope>, ...],
      "skipped_already_handled": <n>,
      "ledger_path": "..."
    }

Auto-handled lessons have already had ack messages sent + ledger
entries appended. The slash command only needs to triage `pending`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import lessons_receiver  # noqa: E402


def main() -> int:
    rep = lessons_receiver.pull()
    print(json.dumps(lessons_receiver._report_to_dict(rep),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
