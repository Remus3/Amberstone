"""OVL2: client-origin-gated CORS on the :8888 dashboard handler.

The Pengu Loader plugin (pengu/) runs inside the League client UX at a
loopback origin (https://127.0.0.1:<port>) and does a cross-origin GET of
RC_ORIGIN/api/state. CEF enforces CORS, so dashboard/_handler.py must echo
the plugin's Origin in Access-Control-Allow-Origin - but ONLY for an allowed
client (loopback, or an explicit RC_CORS_ALLOW_ORIGINS allowlist), never
wildcard. These tests pin that gate at the helper level and through _send.
"""
from __future__ import annotations

import io

import pytest

from dashboard._handler import Handler, _cors_allowed_origin


# -- pure helper ---------------------------------------------------------

def test_cors_helper_echoes_loopback_variants():
    assert _cors_allowed_origin("https://127.0.0.1:8888") == "https://127.0.0.1:8888"
    assert _cors_allowed_origin("https://localhost:1234") == "https://localhost:1234"
    assert _cors_allowed_origin("http://[::1]:9000") == "http://[::1]:9000"


def test_cors_helper_rejects_remote_null_and_empty():
    assert _cors_allowed_origin("https://example.com") is None
    assert _cors_allowed_origin("http://192.168.8.230:8888") is None
    assert _cors_allowed_origin("null") is None
    assert _cors_allowed_origin("") is None


def test_cors_helper_env_allowlist(monkeypatch):
    monkeypatch.setenv("RC_CORS_ALLOW_ORIGINS", "https://riot.example,https://x.test")
    assert _cors_allowed_origin("https://riot.example") == "https://riot.example"
    assert _cors_allowed_origin("https://x.test") == "https://x.test"
    assert _cors_allowed_origin("https://other.test") is None


# -- _send integration ---------------------------------------------------

def _make_handler(origin=None):
    """Build a Handler without a socket and capture every send_header call."""
    h = Handler.__new__(Handler)
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    h.headers = headers
    h.connection = object()  # no .cipher -> no HSTS, no TLS branch
    sent = []
    h.send_response = lambda code: sent.append(("__status__", code))
    h.send_header = lambda k, v: sent.append((k, v))
    h.end_headers = lambda: sent.append(("__end__", None))
    h.wfile = io.BytesIO()
    h._sent = sent
    return h


def _header_map(h):
    return {k: v for k, v in h._sent if k not in ("__status__", "__end__")}


def test_send_echoes_acao_for_loopback_origin():
    h = _make_handler("https://127.0.0.1:5123")
    h._send(200, b"{}", "application/json")
    hdrs = _header_map(h)
    assert hdrs.get("Access-Control-Allow-Origin") == "https://127.0.0.1:5123"
    assert hdrs.get("Vary") == "Origin"


def test_send_omits_acao_for_remote_origin():
    h = _make_handler("https://evil.example.com")
    h._send(200, b"{}", "application/json")
    keys = [k for k, _ in h._sent]
    assert "Access-Control-Allow-Origin" not in keys


def test_send_omits_acao_when_no_origin_header():
    h = _make_handler(None)
    h._send(200, b"{}", "application/json")
    keys = [k for k, _ in h._sent]
    assert "Access-Control-Allow-Origin" not in keys


def test_send_still_writes_body_and_core_headers():
    h = _make_handler("https://127.0.0.1:5123")
    h._send(200, b'{"ok":1}', "application/json")
    hdrs = _header_map(h)
    assert hdrs.get("Content-Type") == "application/json"
    assert hdrs.get("Content-Length") == str(len(b'{"ok":1}'))
    assert h.wfile.getvalue() == b'{"ok":1}'


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
