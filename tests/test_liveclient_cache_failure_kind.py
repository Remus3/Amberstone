"""RM-637 (ADR-016 "Lifecycle"): the recorder stops only after N CONSECUTIVE
TRANSPORT failures; a parse error or an HTTP error status never ends a
recording. Snapshot therefore names the failure kind (additive field at the
END with a default, per the dataclass rule)."""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from core import liveclient_cache as lc


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, behaviour):
    def fake_urlopen(req, timeout=None):
        if isinstance(behaviour, BaseException):
            raise behaviour
        return _Resp(behaviour)
    monkeypatch.setattr(lc, "urlopen", fake_urlopen)
    monkeypatch.setattr(lc, "_auth_headers", lambda: {})


def test_default_field_is_empty_and_last():
    s = lc.Snapshot()
    assert s.failure == ""
    import dataclasses
    assert [f.name for f in dataclasses.fields(lc.Snapshot)][-1] == "failure"


@pytest.mark.parametrize("behaviour,kind", [
    (URLError("refused"), "transport"),
    (TimeoutError("slow"), "transport"),
    (ConnectionResetError("rst"), "transport"),
    (HTTPError("u", 404, "nf", {}, None), "http"),
    (HTTPError("u", 503, "busy", {}, None), "http"),
    (b"{not json", "parse"),
    (b"[1, 2]", "parse"),
    (json.dumps({"error": "x"}).encode(), "http"),
    (json.dumps({"ts": 1.0, "data": "str"}).encode(), "parse"),
])
def test_failure_kind(monkeypatch, behaviour, kind):
    _patch(monkeypatch, behaviour)
    snap = lc._fetch_once()
    assert snap.data is None
    assert snap.failure == kind


def test_success_has_no_failure(monkeypatch):
    import time
    _patch(monkeypatch, json.dumps({"ts": time.time(), "data": {"gameData": {}}}).encode())
    snap = lc._fetch_once()
    assert snap.data == {"gameData": {}}
    assert snap.failure == ""


def test_404_still_sets_no_game(monkeypatch):
    _patch(monkeypatch, HTTPError("u", 404, "nf", {}, None))
    snap = lc._fetch_once()
    assert snap.no_game is True and snap.failure == "http"
