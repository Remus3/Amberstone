# arch: bounded JSON-RPC reply reader shared by the two Perseus vault clients | section=tools | frozen=no
"""Read one JSON-RPC reply from the perseus-vault stdio server, BOUNDED.

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

S144-T-605. "Parses as JSON" is not "is the reply". The reader now returns
only a JSON-RPC RESPONSE object - a dict with an "id" and a "result" or an
"error", and no "method" - and, when the caller passes `expect_id`, only the
one whose id is that request's id (compared by type as well as value, so a
JSON `true` or `1.0` never answers request 1). Skipped, and counted against
the budget: a bare scalar or array line (a progress "42" was handed back as
the reply, and perseus_recall then raised on it), a server notification or
server-to-client request (perseus_recall read one as "no result" and printed
NO hits, a silent empty recall gate), and a late reply to an earlier request
(the long-lived perseus_sync Vault would read every later reply one request
behind). An error reply with a null id IS returned: JSON-RPC sends that when
the server could not read the id of the request, and requests here are
strictly serial, so it answers the one just sent. A line nested deeply
enough to raise RecursionError in the decoder is chatter too, never a crash.

The bounds are checked at the call, before any read: a NaN deadline never
expired, so the RM-375 deadline could be declined by an argument.

Limit: a deadline checked between lines cannot interrupt a readline() that
never returns (a silent server); that is EOF-or-hang territory the callers
already had, and is not the RM-375 defect.
"""
from __future__ import annotations

import json
import math
import sys
import time
from typing import Callable

DEFAULT_DEADLINE_S = 60.0
DEFAULT_MAX_SKIPPED = 2000


def _check_bounds(deadline_s, max_skipped, expect_id) -> None:
    if isinstance(deadline_s, bool) or not isinstance(deadline_s, (int, float)):
        raise TypeError("deadline_s must be a real number of seconds")
    if not math.isfinite(deadline_s) or deadline_s < 0:
        raise ValueError("deadline_s must be finite and >= 0")
    if isinstance(max_skipped, bool) or not isinstance(max_skipped, int):
        raise TypeError("max_skipped must be an int")
    if max_skipped < 0:
        raise ValueError("max_skipped must be >= 0")
    if expect_id is not None and (
        isinstance(expect_id, bool) or not isinstance(expect_id, (int, str))
    ):
        raise TypeError("expect_id must be None, an int or a str")


def _same_id(got, want) -> bool:
    # type-exact: True == 1 and 1.0 == 1 in Python, never in JSON-RPC.
    return type(got) is type(want) and got == want


def _is_reply(obj, expect_id) -> bool:
    if not isinstance(obj, dict) or "method" in obj or "id" not in obj:
        return False
    has_result = "result" in obj
    has_error = "error" in obj
    if not (has_result or has_error):
        return False
    if expect_id is None:
        return True
    rid = obj["id"]
    if rid is None:
        return has_error and not has_result
    return _same_id(rid, expect_id)


def read_json_reply(
    readline: Callable[[], str],
    *,
    expect_id: int | str | None = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
    max_skipped: int = DEFAULT_MAX_SKIPPED,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """Return the first JSON-RPC response object read (the one answering
    `expect_id` when given), or None on EOF, on more than `max_skipped`
    skipped lines, or once `deadline_s` elapses.

    Skipped: blank lines, non-JSON lines, JSON that is not a response
    object, and responses to another id. Raises TypeError / ValueError for a
    bad bound or id before anything is read."""
    _check_bounds(deadline_s, max_skipped, expect_id)
    deadline = clock() + deadline_s
    skipped = 0
    while True:
        line = readline()
        if not line:
            return None
        line = line.strip()
        if line:
            try:
                obj = json.loads(line)
            except (ValueError, RecursionError):
                # JSONDecodeError and UnicodeDecodeError are ValueErrors.
                obj = None
            if _is_reply(obj, expect_id):
                return obj
        skipped += 1
        if skipped > max_skipped:
            print(f"perseus rpc: gave up after {skipped} skipped line(s) "
                  f"from the vault server (budget {max_skipped})",
                  file=sys.stderr)
            return None
        if clock() >= deadline:
            print(f"perseus rpc: gave up after {skipped} skipped line(s) "
                  f"from the vault server (deadline {deadline_s:g}s)",
                  file=sys.stderr)
            return None
