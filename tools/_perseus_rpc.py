# arch: bounded JSON-RPC reply reader shared by the two Perseus vault clients | section=tools | frozen=no
"""Read one JSON-RPC reply line from the perseus-vault stdio server, BOUNDED.

RM-375. `tools/perseus_recall.py` and `tools/perseus_sync.py` each ran
`while True: readline()`, returning only on EOF or a line that parsed as JSON
and `continue`-ing past anything else. stdout belongs to an external binary,
so any non-JSON chatter it emits indefinitely (a banner, a log line, a
progress bar) wedged the reader forever - and perseus_recall is the
MANDATORY recall gate at the head of every lane cycle, so one chatty vault
release would stall every lane before it reached its row.

The shape is `core/obs_publisher.py`'s: a bound the loop body cannot decline
to advance. Two of them - a wall-clock deadline and a skipped-line budget -
because a fast spew exhausts the budget long before the deadline and a slow
drip hits the deadline. On either, the reader returns None, which both
callers already treat as "no reply" (the EOF answer). One helper for both
clients so the two near-identical copies cannot drift apart again.

Limit: a deadline checked between lines cannot interrupt a readline() that
never returns (a silent server); that is EOF-or-hang territory the callers
already had, and is not the RM-375 defect.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Callable

DEFAULT_DEADLINE_S = 60.0
DEFAULT_MAX_SKIPPED = 2000


def read_json_reply(
    readline: Callable[[], str],
    *,
    deadline_s: float = DEFAULT_DEADLINE_S,
    max_skipped: int = DEFAULT_MAX_SKIPPED,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """Return the first line that parses as JSON, or None on EOF, on more
    than `max_skipped` non-JSON / blank lines, or once `deadline_s` elapses."""
    deadline = clock() + deadline_s
    skipped = 0
    while True:
        line = readline()
        if not line:
            return None
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
        skipped += 1
        if skipped > max_skipped or clock() >= deadline:
            print(f"perseus rpc: gave up after {skipped} non-JSON line(s) "
                  f"from the vault server", file=sys.stderr)
            return None
