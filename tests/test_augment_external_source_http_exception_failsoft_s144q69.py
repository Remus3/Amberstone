"""RM-1442 (augment site, provisional RM-1442) - an ``http.client.HTTPException``
or a ``ValueError`` raised inside the fetch no longer escapes the never-raises
boundary of ``core/augment_external_source.py``.

``_http_get`` (the one seam behind ``_http_get_json`` for the Mayhem / Arena
win-rate endpoints and the ``CHERRY_AUGMENTS_URL`` metadata fetch) mapped only
``URLError`` / ``OSError`` / ``TimeoutError`` (plus the RM-1441
``WikiFetchRefused``) to ``AugmentSourceError``. urllib's ``do_open`` lets
``getresponse()`` exceptions through unwrapped, and http.client raises
``BadStatusLine`` (a malformed status line), ``LineTooLong`` (an over-long
status or header line) and ``IncompleteRead`` (a broken chunked body) as
``HTTPException`` subclasses that are NOT ``OSError``; a read on a response the
stack already closed raises ``ValueError``. ``get_priors``,
``get_augment_meta`` and ``refresh_cache`` catch ``AugmentSourceError`` only,
so a misbehaving endpoint made the two "never raises" accessors raise into the
arena / ARAM Mayhem coach path instead of degrading to the cached table, and
the failure skipped the RM-450 backoff gate.

The origin is a real raw-socket server on 127.0.0.1 that answers each path
with scripted bytes, so http.client's own parser raises the real exception;
nothing in the stdlib is faked. An empty reply (``RemoteDisconnected``, an
``OSError``) is the positive control that was already fail-soft on the base.
The twin fix for ``core/synergy_external_source.py`` and
``core/rank_tier_source.py`` is ``tests/test_external_source_http_exception_failsoft_s144q69.py``.
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

from core import augment_external_source as X  # noqa: E402
from lib import wiki_consent  # noqa: E402

# The genuine seams, captured at import: other test files replace them and do
# not always restore them, so each test installs the real ones itself.
_REAL_HTTP_GET = X._http_get
_REAL_HTTP_GET_JSON = X._http_get_json
_REAL_OPEN = X.open_consented

_CHUNKED_HEAD = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")

# path -> raw bytes the server writes before closing the connection.
REPLIES = {
    "/bad-status": b"GARBAGE-NOT-HTTP\r\n\r\n",
    "/long-header": (b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 70000
                     + b"\r\nContent-Length: 2\r\n\r\n{}"),
    "/bad-chunk": _CHUNKED_HEAD + b"ZZ\r\n{}\r\n0\r\n\r\n",
    "/cut-chunk": _CHUNKED_HEAD + b'40\r\n{"data": [',
    "/empty": b"",
}
# The four HTTPException shapes, and the exception http.client raises for each.
HTTP_EXC_PATHS = {
    "/bad-status": http.client.BadStatusLine,
    "/long-header": http.client.LineTooLong,
    "/bad-chunk": http.client.IncompleteRead,
    "/cut-chunk": http.client.IncompleteRead,
}

_PRIORS = {
    "meta": {"count": 1, "generated_at": "2026-11-05T00:00:00Z"},
    "data": [{"augment_id": "1088", "patch": "16.22",
              "stats": {"win_rate": 0.5, "num_games": 10}}],
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

    t = threading.Thread(target=_serve, name="s144q69-augment-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}", hits
    finally:
        stop.set()
        t.join(timeout=10)
        srv.close()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Real seams, no proxy, a tmp cache tree, empty process caches and
    backoff gates, the consent path in an empty dir. Yields the cache root."""
    for name in ("http_proxy", "https_proxy", "all_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(X, "_http_get", _REAL_HTTP_GET)
    monkeypatch.setattr(X, "_http_get_json", _REAL_HTTP_GET_JSON)
    monkeypatch.setattr(X, "open_consented", _REAL_OPEN)
    ds = tmp_path / "ds"
    (ds / "tp").mkdir(parents=True)
    monkeypatch.setattr(X, "_DS_DATA_DIR", ds)
    monkeypatch.setattr(X, "_current_patch", lambda: "tp")
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    X.reset_cache()
    yield ds
    X.reset_cache()


def _seed_older_priors(ds: Path) -> None:
    """A populated mayhem snapshot in an OLDER patch dir: what the degraded
    path must serve when the live fetch fails."""
    old = ds / "old"
    old.mkdir()
    snap = X._normalize("mayhem", "old", _PRIORS)
    (old / "mayhem_augment_stats.json").write_text(
        json.dumps(snap), encoding="utf-8", newline="\n")


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


@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_seam_maps_an_http_exception_to_augment_source_error(env, origin, path):
    base, hits = origin
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(f"{base}{path}", 10)
    assert isinstance(ei.value.__cause__, http.client.HTTPException), repr(ei.value.__cause__)
    assert isinstance(ei.value.__cause__, HTTP_EXC_PATHS[path])
    assert hits == [path]


def test_seam_positive_control_an_empty_reply_was_already_mapped(env, origin):
    base, _hits = origin
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(f"{base}/empty", 10)
    assert isinstance(ei.value.__cause__, OSError)


@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_get_priors_degrades_to_the_cached_table_and_backs_off(env, origin, monkeypatch, path):
    """No raise: the older populated snapshot is served, and the failure is
    held by the RM-450 backoff gate (no second origin request)."""
    base, hits = origin
    _seed_older_priors(env)
    monkeypatch.setitem(X._ENDPOINTS, "mayhem", f"{base}{path}")
    table = X.get_priors("mayhem")
    assert table.win_rate(1088) == 0.5
    assert hits == [path]
    assert X.get_priors("mayhem").win_rate(1088) == 0.5
    assert hits == [path], "the failure was not held by the backoff gate"


@pytest.mark.parametrize("path", sorted(HTTP_EXC_PATHS))
def test_get_augment_meta_stays_never_raises_and_backs_off(env, origin, monkeypatch, path):
    base, hits = origin
    monkeypatch.setattr(X, "CHERRY_AUGMENTS_URL", f"{base}{path}")
    assert not X.get_augment_meta().has_data
    assert hits == [path]
    assert not X.get_augment_meta().has_data
    assert hits == [path], "the failure was not held by the backoff gate"


def test_refresh_cache_force_raises_augment_source_error_not_the_raw_exception(
        env, origin, monkeypatch):
    base, _hits = origin
    monkeypatch.setitem(X._ENDPOINTS, "arena", f"{base}/bad-status")
    with pytest.raises(X.AugmentSourceError) as ei:
        X.refresh_cache("arena", force=True, timeout_s=10)
    assert isinstance(ei.value.__cause__, http.client.BadStatusLine)


class _ClosedResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *_a):
        raise ValueError("I/O operation on closed file.")


def test_seam_maps_a_value_error_from_the_response(env, monkeypatch):
    """A ValueError raised while reading (for example a read on a response the
    stack already closed) is a fetch failure, not an escape. Faked through the
    module's OWN opener name (RM-801), never the shared urllib."""
    monkeypatch.setattr(X, "open_consented", lambda req, timeout=None: _ClosedResp())
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get("http://127.0.0.1:9/x", 1)
    assert isinstance(ei.value.__cause__, ValueError)


def test_get_priors_and_meta_stay_never_raises_on_a_value_error(env, monkeypatch):
    _seed_older_priors(env)
    monkeypatch.setattr(X, "open_consented", lambda req, timeout=None: _ClosedResp())
    assert X.get_priors("mayhem").win_rate(1088) == 0.5
    assert not X.get_augment_meta().has_data


def test_a_bad_json_body_is_still_reported_as_bad_json_not_a_fetch_failure(env, monkeypatch):
    """Control on the ordering: the transport tuple now names ValueError, but
    a JSON parse error (a ValueError subclass) is raised by the SECOND try, so
    it keeps its own "bad JSON" message."""

    class _Resp(_ClosedResp):
        def read(self, *_a):
            return b"{not json"

    monkeypatch.setattr(X, "open_consented", lambda req, timeout=None: _Resp())
    with pytest.raises(X.AugmentSourceError, match="bad JSON"):
        X._http_get("http://127.0.0.1:9/x", 1)
