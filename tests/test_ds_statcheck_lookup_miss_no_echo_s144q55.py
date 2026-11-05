"""RM-1370: the /api/ds-statcheck lookup-miss reply echoes no caller text.

Defect (measured on the base): the ``(KeyError, ValueError)`` engine
lookup-miss branch of ``dashboard.routes_ds_statcheck._serve_ds_statcheck``
replied ``{"ok": false, "error": f"unknown champion: {champion}",
"champion": champion, ...}`` with status 200, where ``champion`` is the raw,
unclipped ``champion`` query value. So any caller string (markup, control
characters, a very long value) came back twice in the reply body.

Fix: a fixed ``error`` line ("unknown champion") and NO ``champion`` field.
Choice recorded (the filing allowed "dropped or replaced by the resolved name
only"): DROPPED, because on a lookup miss there is no resolved name to give -
the engine is what failed to resolve it. The only in-tree consumer,
web/js/panels/ds_statcheck.js, reads ``j.ok`` on this path and renders its own
fixed "No stat readout available." line; it reads neither field.

The success path is untouched: it still names ``res.champion_name`` (the
engine's resolved name), and the 400 / 503 replies were already fixed text.
"""

from __future__ import annotations

import json
import logging

import pytest

from dashboard import routes_ds_statcheck as R

_MARK = "S144Q55MARK"
_EVIL = f"<img src=x onerror=alert(1)>{_MARK}\x1b[31m\r\nFAKE" + "A" * 4000


class _WFile:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, b: bytes) -> None:
        self.chunks.append(b)


class _Handler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.wfile = _WFile()
        self.status: int | None = None

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, _k: str, _v: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


def _qs_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


@pytest.fixture(autouse=True)
def _clean():
    R._reset_caches()
    yield
    R._reset_caches()


def _drive(monkeypatch, champion: str, exc_type: type[Exception]):
    seen: dict = {}

    def _dps(_snap, **kw):
        seen.update(kw)
        raise exc_type("Unknown champion id")

    monkeypatch.setattr(R, "_load_engine", lambda: (object(), _dps))
    h = _Handler("/api/ds-statcheck?champion=" + _qs_quote(champion))
    R._serve_ds_statcheck(h)
    raw = b"".join(h.wfile.chunks)
    return h.status, raw, json.loads(raw.decode("utf-8")), seen


@pytest.mark.parametrize("exc_type", [KeyError, ValueError],
                         ids=["KeyError", "ValueError"])
def test_lookup_miss_reply_is_fixed_text(monkeypatch, exc_type):
    status, raw, payload, seen = _drive(monkeypatch, _EVIL, exc_type)
    # the route really reached the engine with the caller's value
    assert seen.get("champion_id") == _EVIL.strip()
    assert status == 200, payload
    assert payload["ok"] is False
    assert payload["error"] == "unknown champion", payload["error"]
    assert "champion" not in payload, payload
    assert set(payload) == {"ok", "error", "detail"}, payload
    assert "see logs" in payload["detail"]
    assert _MARK.encode() not in raw
    assert b"onerror" not in raw
    assert len(raw) < 200, len(raw)


@pytest.mark.parametrize("champion", ["Caitlyn", "NotAChampion"])
def test_lookup_miss_reply_is_the_same_for_every_name(monkeypatch, champion):
    _status, raw, payload, _seen = _drive(monkeypatch, champion, KeyError)
    assert payload == {"ok": False, "error": "unknown champion",
                       "detail": "engine lookup failed - see logs"}
    assert champion.encode() not in raw


def test_lookup_miss_still_logs_the_cause(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="rc.web_dashboard"):
        _drive(monkeypatch, "Caitlyn", KeyError)
    assert any("lookup miss" in r.getMessage() for r in caplog.records)


def test_lookup_miss_is_not_cached(monkeypatch):
    _drive(monkeypatch, "Caitlyn", KeyError)
    assert not R._CACHE


def test_real_engine_unknown_name_echoes_nothing():
    """Same contract through the real engine (no stub): an unresolvable name
    reaches the real lookup-miss branch, not the 503 path."""
    h = _Handler("/api/ds-statcheck?champion=" + _qs_quote("NoSuchChamp" + _MARK))
    R._serve_ds_statcheck(h)
    raw = b"".join(h.wfile.chunks)
    payload = json.loads(raw.decode("utf-8"))
    assert h.status == 200, payload
    assert payload["ok"] is False
    assert payload["error"] == "unknown champion"
    assert _MARK.encode() not in raw
