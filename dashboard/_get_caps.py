"""RM-299b: GET query-list caps for routes whose parsed list FANS OUT.

The POST side has had `_MAX_POST_BYTES` since lane 8 cycle 4; nothing capped
GET query work. This is NOT a blanket cap: it is called only by the route
modules whose parsed list drives per-element work (measured in RM-299b), and
each passes its OWN limit, because what a legitimate list length is differs
per route. Over-limit is a 400 naming the parameter - never a silent
truncation (a junk TOKEN is still dropped by each module's own parser; a junk
LENGTH is not a typo). Same contract as routes_pickban._oversized.
"""
from __future__ import annotations

import json

# Champion lists: an SR side is 5 and Arena carries 16 players, so 16 clears
# every real lobby while bounding the per-champion engine work.
MAX_CHAMPION_LIST = 16


def reject_oversized(h, limit: int, **lists) -> bool:
    """Send a 400 and return True when any named list exceeds ``limit``."""
    for name, values in lists.items():
        n = len(values)
        if n > limit:
            h._send(400, json.dumps({
                "ok": False,
                "error": f"{name}: {n} values exceeds the limit of {limit}",
            }).encode("utf-8"), "application/json")
            return True
    return False
