"""D9: control-endpoint auth gate on the :8888 POST handler.

dashboard/_handler.py do_POST gates /api/command, /api/input, /api/analyze and
/api/loop-control behind an X-RC-Token == RC_DASH_TOKEN check, but ONLY when
RC_DASH_TOKEN is set + non-empty (open otherwise, so a fresh deploy is not
locked out). These tests pin that gate: 401 on missing/wrong token, pass-through
on a correct token, open when the token is unset, and no gating on a
non-control POST path. Test-only (the handler shipped in the Antigravity D9
batch); nothing in dashboard/_handler.py changes here.
"""
from __future__ import annotations

import io

import pytest

import dashboard._dispatch as _dispatch
from dashboard._handler import Handler


def _make_post_handler(path, token_header=None, body=b"{}"):
    """Build a Handler with no socket, wired for do_POST.

    CSRF is forced OK, the body is staged on a BytesIO rfile, and _send is
    captured. Returns (handler, sent) where sent is a list of (code, payload).
    """
    h = Handler.__new__(Handler)
    headers = {"Content-Length": str(len(body))}
    if token_header is not None:
        headers["X-RC-Token"] = token_header
    h.headers = headers
    h.path = path
    h.rfile = io.BytesIO(body)
    h._csrf_ok = lambda: True
    sent = []
    h._send = lambda code, payload, ctype=None: sent.append((code, payload))
    return h, sent


def _patch_dispatch(monkeypatch):
    """Stub dispatch_post so a reached dispatch == auth passed (records calls)."""
    calls = []

    def fake(handler, payload):
        calls.append(payload)
        handler._send(200, b'{"ok":1}', "application/json")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_post", fake)
    return calls


def test_control_reject_without_token(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/command")
    h.do_POST()
    assert sent and sent[-1][0] == 401
    assert calls == []  # dispatch never reached


def test_control_reject_wrong_token(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/input", token_header="nope")
    h.do_POST()
    assert sent[-1][0] == 401
    assert calls == []


def test_control_pass_with_correct_token(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/command", token_header="s3cret")
    h.do_POST()
    assert len(calls) == 1  # auth passed, dispatch reached
    assert sent[-1][0] == 200


def test_control_open_when_token_unset(monkeypatch):
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/command")  # no X-RC-Token header
    h.do_POST()
    assert len(calls) == 1
    assert sent[-1][0] == 200


def test_control_open_when_token_blank(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "   ")  # whitespace strips to empty
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/command")
    h.do_POST()
    assert len(calls) == 1
    assert sent[-1][0] == 200


def test_non_control_path_not_gated(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/bridge")  # not a control path, no token
    h.do_POST()
    assert len(calls) == 1  # passes despite token set + no header
    assert sent[-1][0] == 200


def test_query_string_stripped_before_match(monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler("/api/command?foo=1")  # path_base must strip ?
    h.do_POST()
    assert sent[-1][0] == 401  # still gated after stripping the query
    assert calls == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
