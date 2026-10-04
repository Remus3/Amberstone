"""RM-296e: measured, NOT changed - pin the measurement.

The row asked to measure the dashboard's worker-pool size BEFORE making the
three sequential 2 s /lcu-cmd enqueues of /api/loadout/apply concurrent.

Measured 2026-10-03: both :8888 server classes in dashboard/server.py
(_DualStackHTTPServer, _DualProtocolHTTPServer) are ThreadingHTTPServer
subclasses with no process_request override and no pool - socketserver's
ThreadingMixIn starts ONE NEW THREAD PER REQUEST, unbounded. A request that
blocks for up to 6 s therefore occupies only its own thread and cannot
starve any other request. The only cost is that one operator click waits up
to 6 s when the vision server is unresponsive - the same 2 s-per-call bound
the sibling /api/lcu-cmd uses, which the row forbids diverging from.

Verdict: no fix needed; a change would be churn on a champ-select POST path.
This test makes the verdict re-open itself: if the server ever gains a
bounded pool, the starvation question is live again and this goes red.
"""
from __future__ import annotations

import socketserver

from dashboard import server


def test_dashboard_servers_are_thread_per_request():
    for cls in (server._DualStackHTTPServer, server._DualProtocolHTTPServer):
        assert issubclass(cls, socketserver.ThreadingMixIn), cls
        # No override of the per-request thread spawn anywhere in our MRO
        # above ThreadingMixIn - i.e. no bounded pool was bolted on.
        owner = next(k for k in cls.__mro__ if "process_request" in vars(k))
        assert owner is socketserver.ThreadingMixIn, (
            f"{cls.__name__}.process_request now comes from {owner.__name__}: "
            "a bounded worker pool makes RM-296e's 6 s enqueue a starvation "
            "risk again - re-measure before shipping")
