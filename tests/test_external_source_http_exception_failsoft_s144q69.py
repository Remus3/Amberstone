"""RM-1442 - an ``http.client.HTTPException`` (and, for the duo-synergy
fetch, a ``ValueError``) raised inside the fetch no longer escapes the
fail-soft boundary of ``core/synergy_external_source.py`` or
``core/rank_tier_source.py``.

Both ``_http_get_json`` seams mapped only ``URLError`` / ``OSError`` /
``TimeoutError`` to the module's own error. urllib's ``do_open`` lets
``getresponse()`` exceptions through unwrapped, and http.client raises
``BadStatusLine`` (a malformed status line), ``LineTooLong`` (an over-long
status or header line) and ``IncompleteRead`` (a broken chunked body) as
``HTTPException`` subclasses that are NOT ``OSError`` (only
``RemoteDisconnected`` is). So a misbehaving endpoint made:

- synergy ``fetch_rows`` raise (it catches ``SynergyError`` only), instead
  of returning None, trying the next date and negative-caching the failure;
- rank-tier ``fetch_rows`` raise (it catches ``RankTierSourceError`` /
  ``OSError`` / ``ValueError``), instead of returning None.

The origin is a real raw-socket server on 127.0.0.1 that answers each path
with scripted bytes, so http.client's own parser raises the real exception;
nothing in the stdlib is faked. An empty reply (``RemoteDisconnected``, an
``OSError``) is the positive control that was already fail-soft on the base.
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import rank_tier_source as RTS  # noqa: E402
from core import synergy_external_source as S  # noqa: E402
from lib import wiki_consent  # noqa: E402

# The genuine seams, captured at import: other test files replace them and do
# not always restore them, so each test installs the real one itself.
_REAL_SYN_GET = S._http_get_json
_REAL_RTS_GET = RTS._http_get_json

_DUMMY_KEY = "dummy-not-a-real-key"

_CHUNKED_HEAD = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")

# path -> raw bytes the server writes before closing the connection.
REPLIES = {
    "/bad-status": b"GARBAGE-NOT-HTTP\r\n\r\n",
    "/long-header": (b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 70000
                     + b"\r\nContent-Length: 2\r\n\r\n{}"),
    "/bad-chunk": _CHUNKED_HEAD + b"ZZ\r\n{}\r\n0\r\n\r\n",
    "/cut-chunk": _CHUNKED_HEAD + b"40\r\n{\"data\": [",
    "/empty": b"",
}
# The four HTTPException shapes, and the exception http.client raises for each.
HTTP_EXC_PATHS = {
    "/bad-status": http.client.BadStatusLine,
    "/long-header": http.client.LineTooLong,
    "/bad-chunk": http.client.IncompleteRead,
    "/cut-chunk": http.client.IncompleteRead,
}


def _recv_request(conn: socket.socket) -> str:
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < 65536:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    first = buf.split(b"\r\n", 1)[0].decode("latin-1")
    parts = first.split(" ")
    return urlsplit(parts[1]).path if len(parts) >= 2 else ""


@pytest.fixture
def origin():
    """(base url, request-path log) of a raw scripted origin; joined at teardown."""
    hits: list[str] = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    srv.settimeout(0.05)
    stop = threading.Event()

    def _serve():
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    path = _recv_request(conn)
                    hits.append(path)
                    conn.sendall(REPLIES.get(path, b"HTTP/1.1 404 Not Found\r\n"
                                                   b"Content-Length: 0\r\n\r\n"))
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

    t = threading.Thread(target=_serve, name="s144q69-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}", hits
    finally:
        stop.set()
        t.join(timeout=10)
        srv.close()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Real seams, no proxy, empty caches, consent path in an empty dir."""
    for name in ("http_proxy", "https_proxy", "all_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(S, "_http_get_json", _REAL_SYN_GET)
    monkeypatch.setattr(RTS, "_http_get_json", _REAL_RTS_GET)
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    S._reset_cache_for_tests()
    RTS._reset_cache_for_tests()
    yield
    S._reset_cache_for_tests()
    RTS._reset_cache_for_tests()


def _rts_config(tmp_path, monkeypatch, endpoint: str) -> None:
    p = tmp_path / "rank_tier_source.json"
    p.write_text(json.dumps({"endpoint": endpoint, "tier_param": "tier", "enabled": True}),
                 encoding="utf-8", newline="\n")
    monkeypatch.setattr(RTS, "_CONFIG_PATH", p)


def test_the_scripted_replies_raise_the_real_http_client_exceptions(origin):
    """Anchor: each scripted reply really makes stdlib urllib raise the named
    HTTPException subclass, which is not an OSError - so the cases below
    exercise the hole, not a URLError the old tuple already caught."""
    import urllib.request
    base, _hits = origin
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _drain(opener, url):
        with opener.open(url, timeout=10) as r:
            while r.read(4096):
                pass

    for path, exc_type in HTTP_EXC_PATHS.items():
        with pytest.raises(exc_type) as ei:
            _drain(opener, f"{base}{path}")
        assert not isinstance(ei.value, OSError), path


# --- core/synergy_external_source.py ---------------------------------------

@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_synergy_seam_maps_an_http_exception_to_synergy_error(env, origin, path):
    base, _hits = origin
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json(f"{base}{path}", timeout_s=10)
    assert not isinstance(ei.value, S.SynergyRefused)
    assert isinstance(ei.value.__cause__, http.client.HTTPException), repr(ei.value.__cause__)


def test_synergy_seam_positive_control_an_empty_reply_was_already_mapped(env, origin):
    base, _hits = origin
    with pytest.raises(S.SynergyError):
        S._http_get_json(f"{base}/empty", timeout_s=10)


@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_synergy_fetch_rows_stays_fail_soft_tries_every_date_and_neg_caches(
        env, origin, monkeypatch, path):
    """None, not a raise; a transport failure is per-date, so every candidate
    date is asked once; then the failure is negative-cached."""
    base, hits = origin
    monkeypatch.setattr(S, "_ENDPOINT", f"{base}{path}")
    assert S.fetch_rows("bottom", "support") is None
    assert hits == [path] * S._DATE_LOOKBACK_DAYS
    assert S.fetch_rows("bottom", "support") is None
    assert hits == [path] * S._DATE_LOOKBACK_DAYS, "the failure was not negative-cached"


def test_synergy_seam_maps_a_value_error_from_the_response(env, monkeypatch):
    """A ValueError raised while reading (for example a read on a response the
    stack already closed) is a fetch failure, not an escape. Faked through the
    module's OWN opener name (RM-801), never the shared urllib."""

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_a):
            raise ValueError("I/O operation on closed file.")

    monkeypatch.setattr(S, "open_consented", lambda req, timeout=None: _Resp())
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json("http://127.0.0.1:9/x", timeout_s=1)
    assert isinstance(ei.value.__cause__, ValueError)
    assert S.fetch_rows("bottom", "support") is None


# --- core/rank_tier_source.py -----------------------------------------------

@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_rank_tier_seam_maps_an_http_exception_without_leaking_the_url(env, origin, path):
    """RankTierSourceError, no credential or raw url in the message, the
    exception TYPE named, and nothing on __cause__ / __context__ (defect F of
    tests/test_rank_tier_live_budget.py)."""
    base, _hits = origin
    url = RTS._build_url(f"{base}{path}?api_key={_DUMMY_KEY}", "tier", "iron", "SR")
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(url, timeout_s=10)
    text = str(ei.value)
    assert HTTP_EXC_PATHS[path].__name__ in text, text
    assert _DUMMY_KEY not in text and "api_key" not in text and url not in text, text
    assert "127.0.0.1" in text, f"redacted past usefulness: {text!r}"
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_rank_tier_seam_maps_a_value_error_from_the_response(env, monkeypatch):
    """fetch_rows already caught a raw ValueError, but the seam's own contract
    is RankTierSourceError on any failure, redacted and unchained; a ValueError
    from the read used to leave it raw. Faked through the module's OWN opener
    name (RM-801)."""

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_a):
            raise ValueError("I/O operation on closed file.")

    monkeypatch.setattr(RTS, "open_consented", lambda req, timeout=None: _Resp())
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(f"http://127.0.0.1:9/x?api_key={_DUMMY_KEY}", timeout_s=1)
    assert "ValueError" in str(ei.value) and _DUMMY_KEY not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_rank_tier_seam_positive_control_an_empty_reply_was_already_mapped(env, origin):
    base, _hits = origin
    with pytest.raises(RTS.RankTierSourceError):
        RTS._http_get_json(f"{base}/empty", timeout_s=10)


@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_rank_tier_fetch_rows_stays_fail_soft_and_neg_caches(
        env, origin, tmp_path, monkeypatch, path):
    base, hits = origin
    _rts_config(tmp_path, monkeypatch, f"{base}{path}")
    assert RTS.fetch_rows("iron", "SR") is None
    assert hits == [path]
    assert RTS.fetch_rows("iron", "SR") is None
    assert hits == [path], "the failure was not negative-cached"
