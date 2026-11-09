"""S144-T-605: tools/_perseus_rpc.py read_json_reply returned the first line
that PARSED as JSON, not the JSON-RPC reply to the request just sent.

Measured on the old helper (Python 3.14): a bare scalar line ("42", "null",
'"result"') was returned as the reply (or as None, the EOF answer); a
server notification ({"method": ...}, no id) was returned as the reply, so
perseus_recall read it as "no result" and printed NO hits; a late reply to an
earlier request (id 1) was returned for the next one (id 2), which shifts every
later reply of the long-lived perseus_sync Vault by one; a deeply nested line
raised RecursionError out of the recall gate; a NaN deadline never expired.

Now the helper returns only a JSON-RPC response object (an "id" plus "result"
or "error", no "method"), matching `expect_id` when the caller passes it (an
error reply with a null id is still the answer: the server could not read the
id of our request); everything else counts against the skip budget. The
bounds are checked at the call: a non-finite or negative deadline, a negative
or non-int budget and a bool / non-int / non-str id are refused.
"""
from __future__ import annotations

import io
import itertools
import json

import pytest

from tests._module_view import bind_os_path, bind_subprocess
from tools import _perseus_rpc as rpc


def _lines(*items) -> io.StringIO:
    out = []
    for item in items:
        out.append(item if isinstance(item, str) else json.dumps(item))
    return io.StringIO("\n".join(out) + "\n")


REPLY_1 = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
REPLY_2 = {"jsonrpc": "2.0", "id": 2, "result": {"ok": 2}}
NOTIFY = {"jsonrpc": "2.0", "method": "notifications/message",
          "params": {"level": "info", "data": "warming"}}


# --- scalars and non-objects are chatter, never the reply -----------------

@pytest.mark.parametrize("chatter", ["42", "0.5", "null", "true", '"result"',
                                     "[1, 2]", "[]", "{}", "NaN"])
def test_non_response_json_line_is_skipped(chatter):
    assert rpc.read_json_reply(_lines(chatter, REPLY_1).readline) == REPLY_1


def test_only_non_response_lines_then_eof_is_none():
    assert rpc.read_json_reply(_lines("42", "null", NOTIFY).readline) is None


# --- notifications and server requests are not replies --------------------

def test_notification_before_reply_is_skipped():
    assert rpc.read_json_reply(_lines(NOTIFY, REPLY_1).readline) == REPLY_1


def test_server_request_with_method_and_id_is_skipped():
    req = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert rpc.read_json_reply(_lines(req, REPLY_1).readline,
                               expect_id=1) == REPLY_1


def test_object_carrying_method_is_never_a_reply_even_with_result():
    hybrid = {"jsonrpc": "2.0", "id": 1, "method": "ping", "result": {}}
    assert rpc.read_json_reply(_lines(hybrid, REPLY_1).readline,
                               expect_id=1) == REPLY_1
    assert rpc.read_json_reply(_lines(hybrid, REPLY_1).readline) == REPLY_1


def test_object_with_id_but_no_result_or_error_is_skipped():
    odd = {"jsonrpc": "2.0", "id": 1}
    assert rpc.read_json_reply(_lines(odd, REPLY_1).readline) == REPLY_1


def test_error_reply_is_returned():
    err = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "x"}}
    assert rpc.read_json_reply(_lines(err).readline, expect_id=1) == err


# --- id matching ------------------------------------------------------------

def test_stale_reply_for_an_earlier_id_is_skipped():
    got = rpc.read_json_reply(_lines(REPLY_1, REPLY_2).readline, expect_id=2)
    assert got == REPLY_2


def test_string_id_matches_only_itself():
    a = {"jsonrpc": "2.0", "id": "1", "result": 0}
    b = {"jsonrpc": "2.0", "id": 1, "result": 1}
    assert rpc.read_json_reply(_lines(a, b).readline, expect_id=1) == b
    assert rpc.read_json_reply(_lines(b, a).readline, expect_id="1") == a


def test_bool_id_in_reply_never_matches_int_expect_id():
    # True == 1 in Python; a JSON true id is not the integer id 1.
    t = {"jsonrpc": "2.0", "id": True, "result": 0}
    assert rpc.read_json_reply(_lines(t, REPLY_1).readline,
                               expect_id=1) == REPLY_1


def test_float_id_never_matches_int_expect_id():
    f = {"jsonrpc": "2.0", "id": 1.0, "result": 0}
    assert rpc.read_json_reply(_lines(f, REPLY_1).readline,
                               expect_id=1) == REPLY_1


def test_null_id_error_reply_is_the_answer():
    err = {"jsonrpc": "2.0", "id": None,
           "error": {"code": -32700, "message": "Parse error"}}
    assert rpc.read_json_reply(_lines(err).readline, expect_id=3) == err


def test_null_id_result_reply_is_not_the_answer():
    bad = {"jsonrpc": "2.0", "id": None, "result": 1}
    assert rpc.read_json_reply(_lines(bad, REPLY_1).readline,
                               expect_id=1) == REPLY_1


def test_no_expect_id_still_returns_first_response():
    assert rpc.read_json_reply(_lines(REPLY_2, REPLY_1).readline) == REPLY_2


def test_skipped_responses_count_against_the_budget():
    calls = itertools.count()
    stale = itertools.repeat(json.dumps(REPLY_1) + "\n")

    def readline():
        next(calls)
        return next(stale)

    assert rpc.read_json_reply(readline, expect_id=2, max_skipped=5,
                               deadline_s=1e9) is None
    assert next(calls) == 6


# --- a hostile line cannot crash the reader --------------------------------

def test_deeply_nested_line_is_skipped_not_raised():
    deep = "[" * 200000
    assert rpc.read_json_reply(_lines(deep, REPLY_1).readline) == REPLY_1


def test_deeply_nested_object_line_is_skipped_not_raised():
    deep = '{"a":' * 200000
    assert rpc.read_json_reply(_lines(deep, REPLY_1).readline) == REPLY_1


# --- the bounds cannot be declined -----------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, "60",
                                 None])
def test_bad_deadline_is_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        rpc.read_json_reply(io.StringIO("").readline, deadline_s=bad)


@pytest.mark.parametrize("bad", [-1, 2.5, True, "10", None])
def test_bad_budget_is_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        rpc.read_json_reply(io.StringIO("").readline, max_skipped=bad)


@pytest.mark.parametrize("bad", [True, 1.0, [1], {"a": 1}])
def test_bad_expect_id_is_refused(bad):
    with pytest.raises(TypeError):
        rpc.read_json_reply(io.StringIO("").readline, expect_id=bad)


def test_bounds_are_checked_before_any_read():
    calls = []

    def readline():
        calls.append(1)
        return ""

    with pytest.raises(ValueError):
        rpc.read_json_reply(readline, deadline_s=float("nan"))
    assert calls == []


def test_zero_deadline_and_zero_budget_are_valid():
    assert rpc.read_json_reply(_lines(REPLY_1).readline, deadline_s=0,
                               max_skipped=0) == REPLY_1
    assert rpc.read_json_reply(_lines("x", REPLY_1).readline,
                               max_skipped=0, deadline_s=1e9) is None


def test_int_deadline_is_accepted():
    assert rpc.read_json_reply(_lines(REPLY_1).readline, deadline_s=60) == REPLY_1


def test_give_up_message_names_the_bound_and_never_the_line(capsys):
    secret = "SECRET-LINE-CONTENT"  # rc-credential-scan: allow-fixture
    t = itertools.count(0.0, 1.0)
    src = itertools.repeat(secret + "\n")
    assert rpc.read_json_reply(lambda: next(src), max_skipped=10**9,
                               deadline_s=3.0, clock=lambda: next(t)) is None
    err = capsys.readouterr().err
    assert "deadline" in err
    assert secret not in err
    src2 = itertools.repeat(secret + "\n")
    assert rpc.read_json_reply(lambda: next(src2), max_skipped=3,
                               deadline_s=1e9) is None
    err2 = capsys.readouterr().err
    assert "budget" in err2
    assert secret not in err2


# --- callers pass their request id -----------------------------------------

class _ScriptedProc:
    """A Popen stand-in whose stdout answers each request with the scripted
    lines for its position, so a test can put chatter before a reply."""

    script: list[list[str]] = []
    made = 0

    def __init__(self, *a, **k):
        type(self).made += 1
        self._sent = 0
        self._queue: list[str] = []
        proc = self

        class _In:
            def write(self, data):
                for raw in data.splitlines():
                    msg = json.loads(raw)
                    if "id" in msg:
                        proc._queue.extend(
                            proc.script[proc._sent] if proc._sent < len(proc.script)
                            else [])
                        proc._sent += 1

            def flush(self):
                pass

            def close(self):
                pass

        class _Out:
            def readline(self):
                return (proc._queue.pop(0) + "\n") if proc._queue else ""

        self.stdin = _In()
        self.stdout = _Out()

    def terminate(self):
        pass


def _recall_text(items):
    return json.dumps({"items": items})


def test_perseus_recall_skips_a_notification_before_its_reply(monkeypatch):
    from tools import perseus_recall as pr
    items = [{"category": "ledger", "key": "item-1", "summary": "hit one"}]
    tool_reply = {"jsonrpc": "2.0", "id": 2, "result": {
        "content": [{"type": "text", "text": _recall_text(items)}]}}
    script = [
        [json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})],
        [json.dumps(NOTIFY), "42",
         json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"late": True}}),
         json.dumps(tool_reply)],
    ]
    monkeypatch.setattr(_ScriptedProc, "script", script)
    monkeypatch.setattr(_ScriptedProc, "made", 0)
    bind_os_path(monkeypatch, pr, exists=lambda p: True)
    bind_subprocess(monkeypatch, pr, Popen=_ScriptedProc)
    rows = pr.recall("anything")
    assert _ScriptedProc.made == 1
    assert [r["key"] for r in rows] == ["item-1"]


def test_perseus_sync_vault_skips_a_stale_reply(monkeypatch):
    from tools import perseus_sync as ps
    script = [
        # initialize (id 1) answered, then a duplicate late copy of it
        [json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})],
        [json.dumps({"jsonrpc": "2.0", "id": 1, "result": "stale"}),
         json.dumps({"jsonrpc": "2.0", "id": 2, "result": "fresh"})],
    ]
    monkeypatch.setattr(_ScriptedProc, "script", script)
    monkeypatch.setattr(_ScriptedProc, "made", 0)
    bind_subprocess(monkeypatch, ps, Popen=_ScriptedProc)
    vault = ps.Vault()
    assert vault.rpc("tools/list", {}) == {"jsonrpc": "2.0", "id": 2,
                                           "result": "fresh"}
    assert _ScriptedProc.made == 1
