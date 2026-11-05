"""RM-1441 (augment site, provisional RM-1441) - the external augment
win-rate prior and the cherry-augments metadata fetch refuse a redirect INTO
the League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same
shape on the three wiki tools and ``lib/http/client.py``, RM-1440 on
``tools/upstream_drift_check.py``, RM-1441 on the synergy, rank-tier and TFT
icon fetchers).

``core/augment_external_source.py`` ``_http_get`` (the one seam behind both
``_http_get_json`` for the Mayhem / Arena win-rate endpoints and the
``CHERRY_AUGMENTS_URL`` metadata fetch) opened with ``urllib.request.urlopen``,
whose default opener follows a 3xx, so an endpoint answering 302 to the wiki
host opened a wiki socket with no consent record. The module is live-wired
(the augment recommender reaches ``get_priors`` / ``get_augment_meta`` from
the arena and ARAM Mayhem coaches).

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by an
exception alone. With a consent record the same redirect IS followed (one
recorded wiki connect), so the refusal is conditional, and a redirect to a
non-wiki target still resolves. The refusal surfaces as AugmentSourceError
(its cause the WikiFetchRefused), because ``WikiFetchRefused`` is a
RuntimeError and would otherwise escape the never-raises accessors, whose
boundary catches AugmentSourceError only.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import inspect
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
from tests._module_view import this_thread_only  # noqa: E402

# The genuine seam, captured at import, so a sibling file that replaces
# X._http_get without restoring it cannot hand these tests a stub.
_REAL_HTTP_GET = X._http_get

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
_PRIORS = {
    "meta": {"count": 1, "generated_at": "2026-11-05T00:00:00Z"},
    "data": [{"augment_id": "1088", "patch": "16.22",
              "stats": {"win_rate": 0.5, "num_games": 10}}],
}
OK_BODY = json.dumps(_PRIORS).encode("ascii")


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(path)
            if path.startswith("/to-wiki/"):
                self._redirect(WIKI_TARGETS[path.rsplit("/", 1)[1]])
            elif path.startswith("/hop/"):
                self._redirect("/to-wiki/" + path.rsplit("/", 1)[1])
            elif path == "/to-local":
                self._redirect("/ok")
            elif path == "/ok":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(OK_BODY)))
                self.end_headers()
                self.wfile.write(OK_BODY)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):  # silence the stdlib access log
            pass

    return _Handler


@pytest.fixture()
def origin():
    """(base url, request-path log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-augment-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture()
def net(monkeypatch, tmp_path):
    """Record-and-refuse wiki connects; the real seam; a tmp cache tree; empty
    process caches; the consent path in an empty dir."""
    calls: list[str] = []
    real = socket.create_connection

    def _connect(address, *a, **k):
        host = str(address[0])
        if wiki_consent.is_wiki_url(f"http://{host}/"):
            calls.append(f"connect {host}:{address[1]}")
            raise _NetworkTouched(f"wiki connect: {host}")
        return real(address, *a, **k)

    monkeypatch.setattr(socket, "create_connection", this_thread_only(_connect, real))
    for name in ("http_proxy", "https_proxy", "all_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(X, "_http_get", _REAL_HTTP_GET)
    ds = tmp_path / "ds"
    (ds / "tp").mkdir(parents=True)
    monkeypatch.setattr(X, "_DS_DATA_DIR", ds)
    monkeypatch.setattr(X, "_current_patch", lambda: "tp")
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    X.reset_cache()
    yield calls
    X.reset_cache()


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


def _refused(exc_info) -> bool:
    return isinstance(exc_info.value.__cause__, wiki_consent.WikiFetchRefused)


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, _hits = origin
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(f"{base}/to-wiki/{target}", 10)
    assert net == []
    assert _refused(ei)


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(f"{base}/hop/vanity", 10)
    assert net == []
    assert _refused(ei)
    assert hits == ["/hop/vanity", "/to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(WIKI_TARGETS["vanity"], 10)
    assert net == [] and hits == []
    assert _refused(ei)


def test_with_consent_the_redirect_is_followed(net, origin):
    base, _hits = origin
    _grant()
    with pytest.raises(X.AugmentSourceError) as ei:
        X._http_get(f"{base}/to-wiki/vanity", 10)
    # The consented redirect reaches the wiki host once; the patched connect
    # refuses it, so it fails as an ordinary transport error, not a refusal.
    assert net and all(c.startswith("connect wiki.leagueoflegends.com:") for c in net)
    assert len(net) == 1
    assert not _refused(ei)


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, _hits = origin
    assert X._http_get(f"{base}/to-local", 10) == _PRIORS
    assert net == []


def test_get_priors_stays_never_raises_on_a_refusal_and_backs_off(net, origin, monkeypatch):
    """An empty table, zero wiki sockets, and the refusal is held by the
    RM-450 backoff gate like any other failure (no second origin request)."""
    base, hits = origin
    monkeypatch.setitem(X._ENDPOINTS, "mayhem", f"{base}/to-wiki/vanity")
    table = X.get_priors("mayhem")
    assert not table.has_data
    assert net == []
    assert hits == ["/to-wiki/vanity"]
    assert not X.get_priors("mayhem").has_data
    assert hits == ["/to-wiki/vanity"], "the refusal was not held by the backoff gate"


def test_refresh_cache_force_raises_the_refusal_as_augment_source_error(net, origin, monkeypatch):
    base, _hits = origin
    monkeypatch.setitem(X._ENDPOINTS, "arena", f"{base}/to-wiki/fandom")
    with pytest.raises(X.AugmentSourceError) as ei:
        X.refresh_cache("arena", force=True, timeout_s=10)
    assert net == []
    assert _refused(ei)


def test_get_priors_still_reads_a_non_wiki_redirect(net, origin, monkeypatch):
    base, _hits = origin
    monkeypatch.setitem(X._ENDPOINTS, "mayhem", f"{base}/to-local")
    table = X.get_priors("mayhem")
    assert table.win_rate(1088) == 0.5
    assert net == []


def test_get_augment_meta_stays_never_raises_on_a_refusal(net, origin, monkeypatch):
    base, hits = origin
    monkeypatch.setattr(X, "CHERRY_AUGMENTS_URL", f"{base}/to-wiki/wikigg")
    assert not X.get_augment_meta().has_data
    assert net == []
    assert hits == ["/to-wiki/wikigg"]


def test_source_pin_the_one_seam_opens_through_open_consented():
    """Source pin: the GET opens through open_consented, no urlopen is left."""
    assert X.open_consented is wiki_consent.open_consented
    src = inspect.getsource(X)
    assert "urlopen(" not in src
    assert inspect.getsource(X._http_get).count("open_consented(") == 1
