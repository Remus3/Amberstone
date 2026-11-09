"""S144-T-719 - true-audit of agents/agent7_context/warm_session.py.

The warm Agent 7 session keeps ONE Messages API conversation alive for
/api/input. Its history is replayed on every request, so one bad entry
poisons every later turn until the 30-minute idle reset - and it does so
SILENTLY, because both consumers (agents/supervisor.py
_warm_agent7_handle and agents/_supervisor_http.py _spawn_with_fallback)
catch WarmSessionError and fall back to the ephemeral CLI this module
exists to avoid.

Findings pinned here, one test class each:

1. A response with no usable text (content [] or only non-text blocks)
   raised "malformed response" but left the user turn in the history,
   so the next request carried two user turns in a row and the stale
   question rode along on every later turn. The failure path already
   rolled back; the malformed path did not.
2. An empty or whitespace-only reply (or a non-str .text) was appended
   as an assistant turn. The Messages API contract requires non-empty
   text content in every non-final message, so every later request
   would carry an invalid message (stated as a contract violation; no
   live call was made).
3. A reply whose FIRST block is not text (a thinking or tool block ahead
   of the text) was reported malformed although it carried a reply.
4. The failure log line wrote the raw exception, so an error string
   carrying the key reached logs/ unredacted; only the raised copy was
   redacted.
5. warm_spawn_factory: a non-dict payload or a non-str instruction
   escaped as AttributeError / was stringified into the prompt instead
   of raising WarmSessionError (the only exception the consumers catch).
6. send(max_tokens=...) accepted a bool, a float, zero or a negative
   value and spent a network round trip on a request the API rejects.
7. A usage block with a non-numeric token count raised ValueError past
   the consumers' WarmSessionError handler after the reply was received.
   And a billed-but-malformed response was never recorded in
   cost_tracker.

Every fake transport here is synthetic; no live call is made. The key is
a unit-test literal, never the real key.
"""
from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.agent7_context.warm_session import (
    WarmAgent7Session,
    WarmSessionError,
    warm_spawn_factory,
)

API_KEY = "sk-ant-unit-test-not-a-real-key"  # rc-credential-scan: allow-fixture


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _resp(blocks, inp=3, out=4):
    return SimpleNamespace(
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out),
    )


class _ScriptedClient:
    """Returns the scripted responses in order and records each request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = MagicMock()
        self.messages.create.side_effect = self._create

    def _create(self, **kw):
        self.requests.append([dict(m) for m in kw["messages"]])
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    def close(self):
        pass


def _session(client):
    s = WarmAgent7Session(charter="", api_key=API_KEY)
    s._client = client
    return s


class _CostPatched(unittest.TestCase):
    """Every test here keeps cost_tracker off the live ledger."""

    def setUp(self):
        p = patch("core.cost_tracker.record_anthropic_response")
        self.cost = p.start()
        self.addCleanup(p.stop)


class MalformedReplyRollsBack(_CostPatched):

    def _assert_rolled_back(self, bad):
        c = _ScriptedClient([_resp([_text_block("a1")]), bad,
                             _resp([_text_block("a2")])])
        s = _session(c)
        s.send("q1")
        with self.assertRaises(WarmSessionError):
            s.send("q2")
        self.assertEqual(
            s._messages,
            [{"role": "user", "content": "q1"},
             {"role": "assistant", "content": "a1"}],
        )
        s.send("q3")
        roles = [m["role"] for m in c.requests[-1]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(c.requests[-1][-1]["content"], "q3")

    def test_empty_content_list_rolls_back_the_user_turn(self):
        self._assert_rolled_back(_resp([]))

    def test_only_non_text_blocks_rolls_back_the_user_turn(self):
        self._assert_rolled_back(
            _resp([SimpleNamespace(type="thinking", thinking="hmm")]))

    def test_malformed_reply_is_still_cost_recorded(self):
        bad = _resp([])
        s = _session(_ScriptedClient([bad]))
        with self.assertRaises(WarmSessionError):
            s.send("q1")
        self.assertEqual(self.cost.call_count, 1)
        self.assertIs(self.cost.call_args.args[0], bad)


class EmptyReplyNeverEntersHistory(_CostPatched):

    def test_blank_or_non_string_text_is_malformed(self):
        for bad in ("", "   \n\t", None, 42):
            with self.subTest(text=bad):
                s = _session(_ScriptedClient([_resp([_text_block(bad)])]))
                with self.assertRaises(WarmSessionError):
                    s.send("q1")
                self.assertEqual(s._messages, [])
                self.assertEqual(s.stats()["turns"], 0)


class TextAfterANonTextBlock(_CostPatched):

    def test_reply_text_is_read_past_a_leading_non_text_block(self):
        r = _resp([SimpleNamespace(type="thinking", thinking="plan"),
                   _text_block("hello "), _text_block("there")])
        s = _session(_ScriptedClient([r]))
        reply = s.send("q1")
        self.assertEqual(reply["text"], "hello there")
        self.assertEqual(s._messages[-1],
                         {"role": "assistant", "content": "hello there"})


class KeyNeverReachesTheLog(_CostPatched):

    def test_failure_log_line_is_redacted(self):
        err = RuntimeError(f"401 unauthorized for key {API_KEY}")
        s = _session(_ScriptedClient([err]))
        logger = logging.getLogger("agent7.warm_session")
        with self.assertLogs(logger, level="DEBUG") as cm:
            with self.assertRaises(WarmSessionError):
                s.send("q1")
        joined = "\n".join(cm.output)
        self.assertIn("warm send failed", joined)
        self.assertNotIn(API_KEY, joined)
        self.assertIn("<redacted-api-key>", joined)


class SpawnPayloadValidation(_CostPatched):

    def test_non_dict_payload_raises_warm_session_error(self):
        spawn = warm_spawn_factory(_session(_ScriptedClient([])))
        for bad in (None, "text", ["a"], 7):
            with self.subTest(payload=bad):
                with self.assertRaises(WarmSessionError):
                    spawn("7", "t-1", "op", bad)

    def test_non_string_instruction_raises_warm_session_error(self):
        c = _ScriptedClient([])
        spawn = warm_spawn_factory(_session(c))
        for bad in ({"x": 1}, 5, ["a"]):
            with self.subTest(instruction=bad):
                with self.assertRaises(WarmSessionError):
                    spawn("7", "t-1", "op",
                          {"message": "hi", "instruction": bad})
        self.assertEqual(c.requests, [])

    def test_non_string_message_with_an_instruction_is_refused(self):
        """With an instruction set, the f-string used to stringify a
        dict / int message into the prompt instead of refusing it."""
        c = _ScriptedClient([])
        spawn = warm_spawn_factory(_session(c))
        for bad in ({"x": 1}, 5, ["a"]):
            with self.subTest(message=bad):
                with self.assertRaises(WarmSessionError):
                    spawn("7", "t-1", "op",
                          {"message": bad, "instruction": "do"})
        self.assertEqual(c.requests, [])

    def test_valid_payload_still_builds_the_envelope(self):
        c = _ScriptedClient([_resp([_text_block("{}")], inp=5, out=6)])
        spawn = warm_spawn_factory(_session(c))
        env = spawn("7", "t-1", "op", {"message": "hi", "instruction": "do"})
        self.assertEqual(c.requests[0][-1]["content"], "do\n\nhi")
        self.assertTrue(env["ok"])
        self.assertEqual(env["result"]["result"], "{}")
        self.assertEqual(env["result"]["usage"],
                         {"input_tokens": 5, "output_tokens": 6})


class MaxTokensValidation(_CostPatched):

    def test_invalid_max_tokens_is_refused_before_any_request(self):
        c = _ScriptedClient([])
        s = _session(c)
        for bad in (True, 0, -5, 10.0, "600", None):
            with self.subTest(max_tokens=bad):
                with self.assertRaises(WarmSessionError):
                    s.send("q1", max_tokens=bad)  # type: ignore[arg-type]
        self.assertEqual(c.requests, [])
        self.assertEqual(s._messages, [])

    def test_valid_max_tokens_passes_through(self):
        c = _ScriptedClient([_resp([_text_block("READY")])])
        s = _session(c)
        s.send("q1", max_tokens=10)
        self.assertEqual(c.messages.create.call_args.kwargs["max_tokens"], 10)


class UsageCounts(_CostPatched):

    def test_junk_token_counts_read_as_zero(self):
        for junk in ("lots", None, -3, True, float("nan"), [1]):
            with self.subTest(value=junk):
                r = _resp([_text_block("ok")], inp=junk, out=junk)
                s = _session(_ScriptedClient([r]))
                reply = s.send("q1")
                self.assertEqual(reply["input_tokens"], 0)
                self.assertEqual(reply["output_tokens"], 0)
                self.assertEqual(reply["text"], "ok")

    def test_real_counts_pass_through(self):
        s = _session(_ScriptedClient([_resp([_text_block("ok")], 11, 22)]))
        reply = s.send("q1")
        self.assertEqual((reply["input_tokens"], reply["output_tokens"]),
                         (11, 22))
        st = s.stats()
        self.assertEqual((st["total_input_tokens"], st["total_output_tokens"]),
                         (11, 22))


if __name__ == "__main__":
    unittest.main()
