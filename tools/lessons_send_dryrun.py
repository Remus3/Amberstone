"""CLI dry-run for the Phase 2 sender. Scans the memory dir, prints a
summary + the breakdown of skip reasons, and writes
ops/runtime/would_send_lessons.jsonl with the envelopes that WOULD ship
on the next real send.

No bridge traffic. Use this to review which memories opt-in (via
cross_project: true frontmatter) before flipping the actual send code on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import lessons_sender  # noqa: E402


def main() -> int:
    report = lessons_sender.dry_run()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
