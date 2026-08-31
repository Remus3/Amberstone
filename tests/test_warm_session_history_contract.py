"""Contract tests for agents.agent7_context.warm_session.

LANE 8 (Headless-True-Audit) cycle 36. The module's only existing tests
live in `agents/agent3_testing/suite/test_warm_session.py`, which is
collected by NEITHER `pytest tests/` NOR `pytest agents/daemon_slayer/tests`
- the two trees CI actually runs (.github/workflows/ci.yml:130 and :478).
So every guard on this module was unrun. These live under `tests/` on
purpose, so they execute.

Headline defect this file pins (measured, not inferred):

  `_trim_history` slices `self._messages[-cap:]` with no role alignment.
  The Messages API requires the FIRST message to use the "user" role. On
  turn 21 the append-then-trim order lands the window on an assistant
  turn, so every subsequent request is a 400. Because `_last_activity`
  only advances on SUCCESS, `_check_idle` cannot fire, and the session
  stays broken for the full 30-minute idle timeout.

  It fails SILENTLY: both consumers (agents/supervisor.py:648 and
  agents/_supervisor_http.py:247) catch WarmSessionError and fall back to
  the ephemeral CLI. So the user sees no error - just the ~6s cold path
  and ~6x the cost this module exists to avoid.

The pre-existing `test_history_trimmed_to_cap` could not catch this: it
drives a MagicMock that accepts any messages array and asserts only the
LENGTH, never the role of messages[0].
"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from agents.agent7_context.warm_session import (
    MAX_HISTORY_TURNS,
    WarmAgent7Session,
    WarmSessionError,
    warm_spawn_factory,
)

API_KEY = "sk-ant-unit-test-not-a-real-key"


def _fake_response(text: str = "ok", inp: int = 1, out: int = 1) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage = MagicMock(input_tokens=inp, output_tokens=out)
    return resp


class _RecordingClient:
    """Stand-in for anthropic.Anthropic that records every request and
    enforces the one API rule the production code was violating."""

    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []
        self.closed = 0
        self.messages = MagicMock()
        self.messages.create.side_effect = self._create

    def _create(self, **kwargs: object) -> MagicMock:
        msgs = list(kwargs["messages"])  # type: ignore[arg-type]
        self.requests.append([dict(m) for m in msgs])
        return _fake_response()

    def close(self) -> None:
        self.closed += 1


class WarmSessionHistoryContractTest(unittest.TestCase):
    def _session(self) -> tuple[WarmAgent7Session, _RecordingClient]:
        s = WarmAgent7Session(api_key=API_KEY, charter="TEST CHARTER")
        return s, _RecordingClient()

    def test_every_request_leads_with_a_user_message(self) -> None:
        """The Messages API rejects a leading assistant message. Drive
        past the trim cap and assert EVERY request still honours it."""
        s, client = self._session()
        turns = MAX_HISTORY_TURNS + 5          # 25 - trim engages at 21
        with patch("anthropic.Anthropic", return_value=client):
            for i in range(turns):
                s.send(f"turn-{i}")

        self.assertEqual(len(client.requests), turns)
        offenders = [
            idx for idx, msgs in enumerate(client.requests, start=1)
            if msgs[0]["role"] != "user"
        ]
        self.assertEqual(
            offenders, [],
            f"requests leading with a non-user message (turn numbers): {offenders}",
        )

    def test_history_never_exceeds_the_cap(self) -> None:
        """The cost guard the trim exists for must still hold after the
        role-alignment fix - a fix that only ever DROPS messages."""
        s, client = self._session()
        with patch("anthropic.Anthropic", return_value=client):
            for i in range(MAX_HISTORY_TURNS + 10):
                s.send(f"turn-{i}")
        self.assertLessEqual(len(s._messages), MAX_HISTORY_TURNS * 2)
        for msgs in client.requests:
            self.assertLessEqual(len(msgs), MAX_HISTORY_TURNS * 2)

    def test_roles_strictly_alternate_in_every_request(self) -> None:
        """Characterization: alternation held before the fix and must
        keep holding after it."""
        s, client = self._session()
        with patch("anthropic.Anthropic", return_value=client):
            for i in range(MAX_HISTORY_TURNS + 5):
                s.send(f"turn-{i}")
        for turn, msgs in enumerate(client.requests, start=1):
            roles = [m["role"] for m in msgs]
            dupes = [i for i in range(len(roles) - 1) if roles[i] == roles[i + 1]]
            self.assertEqual(dupes, [], f"turn {turn} has adjacent same-role messages")

    def test_history_stays_valid_after_a_failed_send(self) -> None:
        """A failure rolls back the user turn. The next send must still
        produce an API-valid array - the rollback must not leave the
        window parked on an assistant message."""
        s, client = self._session()
        with patch("anthropic.Anthropic", return_value=client):
            for i in range(MAX_HISTORY_TURNS + 2):
                s.send(f"turn-{i}")

            client.messages.create.side_effect = RuntimeError("upstream 500")
            with self.assertRaises(WarmSessionError):
                s.send("this one fails")

            client.messages.create.side_effect = client._create
            s.send("recovery turn")

        self.assertEqual(client.requests[-1][0]["role"], "user")


class WarmSessionResourceAndValidationTest(unittest.TestCase):
    def test_close_releases_the_sdk_connection_pool(self) -> None:
        """anthropic 0.96.0 exposes Anthropic.close(); the module's
        comment claimed the SDK had none and left it to GC."""
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        client = _RecordingClient()
        with patch("anthropic.Anthropic", return_value=client):
            s.send("hello")
            s.close()
        self.assertEqual(client.closed, 1, "close() did not close the SDK client")
        self.assertIsNone(s._client)

    def test_close_is_safe_when_the_sdk_close_raises(self) -> None:
        """Shutdown must not be blocked by a failing transport close."""
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        client = _RecordingClient()
        client.close = MagicMock(side_effect=RuntimeError("pool already gone"))
        with patch("anthropic.Anthropic", return_value=client):
            s.send("hello")
            s.close()
        self.assertIsNone(s._client)

    def test_non_string_payload_raises_warm_session_error(self) -> None:
        """Both consumers catch ONLY WarmSessionError to fall back to the
        ephemeral CLI (supervisor.py:648, _supervisor_http.py:247). A
        payload field that is not a string must not escape as a raw
        AttributeError past that handler."""
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        spawn = warm_spawn_factory(s)
        for bad in ({"nested": "dict"}, 12345, ["a", "list"]):
            with self.subTest(payload=bad):
                with self.assertRaises(WarmSessionError):
                    spawn("7", "task-1", "op", {"message": bad})

    def test_send_rejects_non_string_user_text(self) -> None:
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        for bad in (None, 42, {"a": 1}, [1, 2]):
            with self.subTest(value=bad):
                with self.assertRaises(WarmSessionError):
                    s.send(bad)  # type: ignore[arg-type]

    def test_api_key_never_appears_in_a_raised_error(self) -> None:
        """The key is gitignored and must never reach an exception string
        a caller might log or render."""
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        client = _RecordingClient()
        client.messages.create.side_effect = RuntimeError(
            f"401 unauthorized for key {API_KEY}"
        )
        with patch("anthropic.Anthropic", return_value=client):
            with self.assertRaises(WarmSessionError) as ctx:
                s.send("hello")
        self.assertNotIn(API_KEY, str(ctx.exception))
        self.assertNotIn(API_KEY, repr(ctx.exception))

    def test_unusable_key_files_are_rejected(self) -> None:
        """A key with an internal newline or a non-ASCII character fails
        header encoding on EVERY request, and the client is cached on
        first use, so nothing re-reads the file. Reject it at load."""
        from agents.agent7_context.warm_session import _usable_key
        self.assertTrue(_usable_key("sk-ant-api03-abcDEF123"))
        for bad in (
            "sk-ant-aaa\nbbb",        # internal newline
            "sk-ant-caf\u00e9-key",   # non-ASCII (escaped: this file is ASCII)
            "sk-ant-aaa bbb",         # embedded space
            "not-a-key",              # wrong prefix
            "",
        ):
            with self.subTest(key=bad):
                self.assertFalse(_usable_key(bad))

    def test_reported_turn_count_matches_this_call(self) -> None:
        """`turns` was read outside the lock, so a concurrent send could
        change it between release and return."""
        s = WarmAgent7Session(api_key=API_KEY, charter="C")
        client = _RecordingClient()
        seen: list[int] = []
        lock = threading.Lock()

        def _worker() -> None:
            reply = s.send("concurrent")
            with lock:
                seen.append(reply["turns"])

        with patch("anthropic.Anthropic", return_value=client):
            threads = [threading.Thread(target=_worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(sorted(seen), list(range(1, 9)),
                         f"turn numbers were not unique per call: {sorted(seen)}")


if __name__ == "__main__":
    unittest.main()
