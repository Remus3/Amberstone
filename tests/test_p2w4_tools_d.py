# arch: P2 cycle-14 slice-D regression tests for DS tooling | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 14 slice D (DS TOOLING:
Share sync, the match-DB MCP server, generators, prefilters, build scorers,
launchers).

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

2. gist_share_sync: the gist mirror runs ``git fetch / push / commit`` via
   ``subprocess.run`` from a post-commit hook. With NO ``timeout`` a network
   hang (auth prompt, dead remote) blocks the hook - and thus the commit -
   indefinitely. ``_git`` must pass a bounded ``timeout``.
"""
from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_matchdb_mcp_server as M  # noqa: E402
import gist_share_sync as G  # noqa: E402


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


# --------------------------------------------------------------------------- gist subprocess timeout
class TestGistGitCallsAreBounded:
    """``_git`` shells out to git (fetch/push/commit) from a post-commit hook;
    a missing timeout lets a network hang block the commit forever."""

    def test_git_passes_a_timeout(self, monkeypatch):
        captured: dict = {}

        def _fake_run(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

            class _CP:
                returncode = 0
                stdout = ""
                stderr = ""
            return _CP()

        monkeypatch.setattr(G.subprocess, "run", _fake_run)
        G._git("status", "--porcelain")
        assert "timeout" in captured["kwargs"], \
            "_git must pass a bounded timeout to subprocess.run"
        assert isinstance(captured["kwargs"]["timeout"], (int, float))
        assert captured["kwargs"]["timeout"] > 0

    def test_git_module_defines_a_positive_timeout_constant(self):
        # The timeout is a named module constant (not a magic literal), so it
        # is tunable + greppable.
        assert hasattr(G, "GIT_TIMEOUT_S")
        assert isinstance(G.GIT_TIMEOUT_S, (int, float))
        assert G.GIT_TIMEOUT_S > 0

    def test_git_signature_unchanged(self):
        # Defensive: the public call shape (*args) is preserved.
        sig = inspect.signature(G._git)
        params = list(sig.parameters.values())
        assert params[0].kind == inspect.Parameter.VAR_POSITIONAL


def test_safe_dumps_finite_only_uses_fast_path():
    """When the payload is already finite the helper must produce byte-identical
    output to a plain ``json.dumps`` with the same args (no needless rewrite)."""
    payload = {"b": 2, "a": [1, 2, 3], "name": "Kaisa"}
    assert (M._json_dumps_safe(payload, indent=2, sort_keys=True)
            == json.dumps(payload, indent=2, sort_keys=True))
    assert math.isfinite(1.0)  # sanity anchor
