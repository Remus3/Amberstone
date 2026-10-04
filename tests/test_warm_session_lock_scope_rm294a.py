"""RM-294a: warm_session.send() must not hold the state lock across the
upstream Anthropic call.

Pre-fix ``send()`` held ``self._lock`` for the whole request (30s timeout),
and ``stats()`` / ``close()`` take the same lock, so a dashboard stats read
or a supervisor shutdown racing an in-flight send blocked for up to the
full request timeout. The fix keeps sends SERIALIZED (a separate send lock,
so turns never interleave) while the state lock covers only the history
mutation.

Mutation check: restoring the wide lock (state lock held around the
transport call) makes ``test_close_returns_while_send_blocked`` and
``test_stats_returns_while_send_blocked`` fail on the join timeout.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock

from agents.agent7_context.warm_session import WarmAgent7Session, WarmSessionError

API_KEY = "sk-ant-unit-test-not-a-real-key"


def _resp(text="ok"):
    r = MagicMock()
    r.content = [MagicMock(text=text)]
    r.usage = MagicMock(input_tokens=1, output_tokens=1)
    return r


class _BlockingClient:
    """Transport whose create() parks until released."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.requests = []
        self.messages = MagicMock()
        self.messages.create.side_effect = self._create
        self.closed = 0

    def _create(self, **kw):
        self.requests.append([dict(m) for m in kw["messages"]])
        self.entered.set()
        if not self.release.wait(10):
            raise RuntimeError("never released")
        return _resp(f"r{len(self.requests)}")

    def close(self):
        self.closed += 1


def _session(client):
    s = WarmAgent7Session(charter="", api_key=API_KEY)
    s._client = client
    return s


class LockScope(unittest.TestCase):

    def _start_blocked_send(self, s, c, box):
        def run():
            try:
                box["reply"] = s.send("hello")
            except WarmSessionError as e:
                box["err"] = e
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.assertTrue(c.entered.wait(5))
        return t

    def test_close_returns_while_send_blocked(self):
        c = _BlockingClient()
        s = _session(c)
        box = {}
        t = self._start_blocked_send(s, c, box)
        closer = threading.Thread(target=s.close, daemon=True)
        t0 = time.monotonic()
        closer.start()
        closer.join(2.0)
        self.assertFalse(closer.is_alive(), "close() waited on the in-flight send")
        self.assertLess(time.monotonic() - t0, 2.0)
        c.release.set()
        t.join(5)
        # The closed session must not be resurrected by the late reply.
        self.assertEqual(s.stats()["history_len"], 0)

    def test_stats_returns_while_send_blocked(self):
        c = _BlockingClient()
        s = _session(c)
        box = {}
        t = self._start_blocked_send(s, c, box)
        out = {}
        reader = threading.Thread(target=lambda: out.update(s.stats()), daemon=True)
        reader.start()
        reader.join(2.0)
        self.assertFalse(reader.is_alive(), "stats() waited on the in-flight send")
        self.assertEqual(out["history_len"], 1)
        c.release.set()
        t.join(5)
        self.assertEqual(box["reply"]["text"], "r1")
        self.assertEqual(s.stats()["history_len"], 2)

    def test_sends_still_serialized_no_interleave(self):
        c = _BlockingClient()
        s = _session(c)
        box1, box2 = {}, {}
        t1 = self._start_blocked_send(s, c, box1)

        def second():
            box2["reply"] = s.send("second")
        t2 = threading.Thread(target=second, daemon=True)
        t2.start()
        time.sleep(0.3)
        # Second send must not have reached the transport while the first
        # is in flight.
        self.assertEqual(len(c.requests), 1)
        c.release.set()
        t1.join(5)
        t2.join(5)
        self.assertEqual(len(c.requests), 2)
        roles = [m["role"] for m in c.requests[1]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual([m["content"] for m in c.requests[1]],
                         ["hello", "r1", "second"])

    def test_failed_send_rolls_back_user_turn(self):
        c = _BlockingClient()
        c.messages.create.side_effect = RuntimeError("boom")
        s = _session(c)
        with self.assertRaises(WarmSessionError):
            s.send("hello")
        self.assertEqual(s.stats()["history_len"], 0)


if __name__ == "__main__":
    unittest.main()
