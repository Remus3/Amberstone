"""The DS HTTP server's listen backlog.

MEASURED 2026-07-27. `start_server` built a stdlib `ThreadingHTTPServer` and
never raised `request_queue_size`, so socketserver's default of 5 applied: past
5 pending connects the OS REFUSES the connection outright, and no client-side
timeout can fix a refusal. Under 12-way load, 3 of 500 sequential POSTs raised
`ConnectionRefusedError [WinError 10061]` even at a 30s deadline.

The consequence was not a slow test, it was a WRONG one.
`core/daemon_slayer_client.py:95-112` maps every transport failure to `None` -
correct production shape, because a live coach tick must fail fast rather than
stall a frame - and callers then read `None` as "the engine had nothing to say"
instead of "the engine never answered". So a refused socket surfaced as an
engine VERDICT: a control champion that "moved" when its base call was a hole,
and an alias-dedupe failure reporting "expected 6 slots, got []". Every DS
live-route test in the suite shares that exposure, which is why this belongs at
the source and not in the two tests that happened to catch it.

`request_queue_size` is consumed by `server_activate()` -> `socket.listen(...)`
during construction, so it MUST be a class attribute. Setting it on the instance
afterwards is too late and would pass a naive read of the code while changing
nothing - which is the shape of guard this repo keeps getting bitten by.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.daemon_slayer import server as ds_server  # noqa: E402


class ListenBacklogTests(unittest.TestCase):
    def test_backlog_is_raised_above_the_socketserver_default(self) -> None:
        self.assertGreaterEqual(
            ds_server._RcThreadingHTTPServer.request_queue_size, 64,
            "the stdlib default of 5 refuses connects under concurrent load")

    def test_backlog_is_a_class_attribute_not_an_instance_one(self) -> None:
        """server_activate() reads it during __init__ - an instance set is inert."""
        self.assertIn("request_queue_size",
                      vars(ds_server._RcThreadingHTTPServer),
                      "must be set on the class or listen() never sees it")

    def test_daemon_threads_survived_the_subclass(self) -> None:
        self.assertTrue(ds_server._RcThreadingHTTPServer.daemon_threads)

    def test_a_started_server_actually_carries_the_backlog(self) -> None:
        """End to end: the object start_server returns, not just the class."""
        snap = ds_server._load_default_snapshot()
        srv = ds_server.start_server(host="127.0.0.1", port=0, snapshot=snap)
        try:
            self.assertGreaterEqual(srv.request_queue_size, 64)
            self.assertTrue(srv.daemon_threads)
        finally:
            srv.server_close()

# A burst-of-connects test was WRITTEN AND THEN DELETED here, deliberately.
# Opening 24 sockets against the listener passed BEFORE the fix as well as
# after: Windows absorbs a burst well past the nominal backlog when the accept
# loop is draining, so the test was green either way and discriminated nothing.
# A test that cannot fail is worse than no test, because it reads as coverage.
# The refusal reproduces only under sustained 12-way REQUEST load against the
# long-running daemon, which is not something to rebuild inside the unit suite;
# it was measured directly instead (3 of 500 POSTs refused at a 30s deadline)
# and that measurement is what justifies the constant above.


if __name__ == "__main__":
    unittest.main()
