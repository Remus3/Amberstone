"""Audit 2026-05-18 finding #4 + coverage gap #13.

`_fetch_bridge` did an unguarded urlopen + json.loads, so any bridge
outage or malformed response raised an uncaught exception out of the
/process-incoming-lessons pipeline. It must now fail soft to [] (which
callers already treat as "no lessons").
"""
from __future__ import annotations

import io
import json
import socket
import urllib.error

import core.lessons_receiver as lr


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _patch_urlopen(monkeypatch, fn):
    monkeypatch.setattr(lr.urllib.request, "urlopen", fn)


def test_url_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")
    _patch_urlopen(monkeypatch, boom)
    assert lr._fetch_bridge(0.0) == []


def test_http_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 503, "down", {}, None)
    _patch_urlopen(monkeypatch, boom)
    assert lr._fetch_bridge(0.0) == []


def test_timeout_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise socket.timeout("timed out")
    _patch_urlopen(monkeypatch, boom)
    assert lr._fetch_bridge(0.0) == []


def test_malformed_json_returns_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b"not json{{{"))
    assert lr._fetch_bridge(0.0) == []


def test_non_dict_json_returns_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b"[1, 2, 3]"))
    assert lr._fetch_bridge(0.0) == []


def test_dict_without_messages_returns_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b'{"ok": true}'))
    assert lr._fetch_bridge(0.0) == []


def test_valid_payload_returns_messages(monkeypatch):
    payload = {"messages": [{"kind": "lesson", "id": "x"}]}
    _patch_urlopen(
        monkeypatch, lambda *a, **k: _FakeResp(json.dumps(payload).encode())
    )
    out = lr._fetch_bridge(0.0)
    assert out == [{"kind": "lesson", "id": "x"}]
