# arch: P2 cycle-14 slice-D regression tests for DS tooling | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 14 slice D (DS TOOLING:
the review-mirror sync tools, the match-DB MCP server, generators, prefilters,
build scorers, launchers).

That slice list is the historical record of what cycle 14 slice D audited, not
a claim about the current tree: the review-mirror sync tools have since been
deleted from the repo (2026-09-07). This module's second FIX-NOW item covered
one of them - the gist mirror's unbounded ``subprocess.run`` in ``_git`` - and
its three tests were removed with the tool, because a test whose subject no
longer exists proves nothing. The finding itself is preserved below as the
record of what was fixed and why, so the lesson survives the deletion.

NO network, NO live engine: every test feeds the pure helpers inline values.

FIX-NOW covered here
--------------------
1. ds_matchdb_mcp_server: the MCP server proxies DS-scorer output (floats) to a
   client over JSON-RPC. A scorer that returns a non-finite float (NaN / inf -
   e.g. a 0/0 ratio or an unbounded score) flowed straight into
   ``json.dumps(result)`` whose default ``allow_nan=True`` emits the BARE tokens
   ``NaN`` / ``Infinity``. Those are invalid JSON for a strict JSON-RPC client
   and for JS ``JSON.parse``. The dashboard DS routes already guard this with
   ``math.isfinite(v) else None`` (routes_ds_knobs / routes_ds_statcheck); the
   MCP server must too. The fix: a safe-dumps helper that never emits a
   non-finite token (sanitizes to ``null``).

2. gist_share_sync (TOOL DELETED 2026-09-07, tests removed with it): the gist
   mirror ran ``git fetch / push / commit`` via ``subprocess.run`` from a
   post-commit hook. With NO ``timeout`` a network hang (auth prompt, dead
   remote) blocked the hook - and thus the commit - indefinitely. ``_git`` was
   made to pass a bounded ``timeout``. Kept here as the durable lesson: any
   ``subprocess.run`` reached from a git hook needs a bounded timeout.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_matchdb_mcp_server as M  # noqa: E402


# --------------------------------------------------------------------------- MCP safe JSON
class TestMcpServerNeverEmitsNonFiniteJsonToken:
    """The two JSON emit sites (tool-result text + the JSON-RPC envelope) must
    never serialize a bare ``NaN`` / ``Infinity`` token. A strict client
    (``json.loads`` with default args, JS ``JSON.parse``) rejects those."""

    def test_safe_dumps_sanitizes_nan_to_null(self):
        out = M._json_dumps_safe({"score": float("nan")})
        # round-trips through a STRICT parser (parse_constant rejects the bare
        # token the stdlib otherwise tolerates).
        reparsed = json.loads(out, parse_constant=_reject_constant)
        assert reparsed["score"] is None

    def test_safe_dumps_sanitizes_inf_to_null(self):
        out = M._json_dumps_safe({"a": float("inf"), "b": float("-inf")})
        reparsed = json.loads(out, parse_constant=_reject_constant)
        assert reparsed["a"] is None
        assert reparsed["b"] is None

    def test_safe_dumps_sanitizes_nested_non_finite(self):
        payload = {"ranked": [{"item": "X", "score": float("inf")},
                              {"item": "Y", "score": 1.5}],
                   "meta": {"ratio": float("nan")}}
        out = M._json_dumps_safe(payload)
        reparsed = json.loads(out, parse_constant=_reject_constant)
        assert reparsed["ranked"][0]["score"] is None
        assert reparsed["ranked"][1]["score"] == 1.5
        assert reparsed["meta"]["ratio"] is None

    def test_safe_dumps_preserves_finite_values(self):
        payload = {"engine_up": True, "score": 12.5, "name": "Vayne",
                   "ids": [1, 2, 3], "neg": -4.25}
        out = M._json_dumps_safe(payload)
        assert json.loads(out, parse_constant=_reject_constant) == payload

    def test_tools_call_result_text_is_strict_json(self):
        # A handler returning a non-finite float must still produce a tool
        # result whose text is STRICT-parseable JSON (the regression: it was
        # json.dumps(...) with allow_nan=True -> bare NaN).
        M.TOOL_FUNCS["__probe_nonfinite__"] = lambda: {"ratio": float("nan")}
        try:
            env = M.handle_tools_call(
                {"name": "__probe_nonfinite__", "arguments": {}})
        finally:
            M.TOOL_FUNCS.pop("__probe_nonfinite__", None)
        text = env["content"][0]["text"]
        reparsed = json.loads(text, parse_constant=_reject_constant)
        assert reparsed["ratio"] is None

    def test_jsonrpc_envelope_is_strict_json(self):
        # The JSON-RPC envelope writer must also be safe: a result dict with a
        # non-finite float must not leak a bare token onto the wire.
        captured: dict = {}

        class _Stub:
            def _send(self, status, body, ctype="application/json"):
                captured["body"] = body

        M._Handler._send_jsonrpc(
            _Stub(), 7, result={"v": float("inf")})
        reparsed = json.loads(captured["body"].decode("utf-8"),
                              parse_constant=_reject_constant)
        assert reparsed["id"] == 7
        assert reparsed["result"]["v"] is None


def _reject_constant(token: str):
    """parse_constant hook: a strict JSON consumer has NO notion of NaN /
    Infinity. Raise so any bare non-finite token in the serialized output
    fails the test loudly."""
    raise AssertionError(f"non-finite JSON token leaked: {token!r}")


# The gist-mirror subprocess-timeout class that lived here was removed on
# 2026-09-07 with tools/gist_share_sync.py itself. Its three tests drove
# ``G._git`` directly, so they cannot be repointed at anything - see FIX-NOW
# item 2 in the module docstring for the finding they encoded.


def test_safe_dumps_finite_only_uses_fast_path():
    """When the payload is already finite the helper must produce byte-identical
    output to a plain ``json.dumps`` with the same args (no needless rewrite)."""
    payload = {"b": 2, "a": [1, 2, 3], "name": "Kaisa"}
    assert (M._json_dumps_safe(payload, indent=2, sort_keys=True)
            == json.dumps(payload, indent=2, sort_keys=True))
    assert math.isfinite(1.0)  # sanity anchor
