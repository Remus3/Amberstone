"""RM-1441 (first site) - the live duo-synergy fetch refuses a redirect INTO
the League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same
shape on the three wiki tools and ``lib/http/client.py``, RM-1440 on
``tools/upstream_drift_check.py``).

``core/synergy_external_source.py`` ``_http_get_json`` fetched the Tencent
endpoint with ``urllib.request.urlopen``, whose default opener follows a 3xx,
so an endpoint answering 302 to the wiki host opened a wiki socket with no
consent record. This module is RC-runtime and live-wired (``/api/duo-synergy``
via ``core.smoothed_rates_101qq``), which is why it is the first RM-1441 site.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by an
exception alone. With a consent record the same redirect IS followed (one
recorded wiki connect), so the refusal is conditional, and a redirect to a
non-wiki target still resolves. ``fetch_rows`` stays fail-soft (None), and a
refusal ends its date loop: it is a ruling, not a per-date data gap.
"""
from __future__ import annotations

import datetime as _dt
import http.server
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

from core import synergy_external_source as S  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

# The genuine seam, captured at import: tests/test_synergy_external_source.py
# replaces S._http_get_json and does not restore it, so these tests install
# the real one themselves (the test_synergy_external_source_budget pattern).
_REAL_HTTP_GET_JSON = S._http_get_json

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
_ROW = {
    "championid1": "498", "championid2": "497",
    "doublewinrate": 0.56, "iwinrate1": 0.5, "iwinrate2": 0.5,
    "itemp1": "4.42%", "irank": 1, "lane1": "bottom", "lane2": "support",
}
OK_BODY = json.dumps({"code": 0, "message": "ok", "data": [_ROW]}).encode("ascii")


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


@pytest.fixture
def origin():
    """(base url, request-path log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture
def net(monkeypatch, tmp_path):
    """Record-and-refuse wiki connects; the real seam; empty caches; consent path in an empty dir."""
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
    monkeypatch.setattr(S, "_http_get_json", _REAL_HTTP_GET_JSON)
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    S._reset_cache_for_tests()
    yield calls
    S._reset_cache_for_tests()


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


def _refused(exc_info) -> bool:
    return isinstance(exc_info.value.__cause__, wiki_consent.WikiFetchRefused)


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, _hits = origin
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json(f"{base}/to-wiki/{target}", timeout_s=10)
    assert net == []
    assert _refused(ei)


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json(f"{base}/hop/vanity", timeout_s=10)
    assert net == []
    assert _refused(ei)
    assert hits == ["/hop/vanity", "/to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json(WIKI_TARGETS["vanity"], timeout_s=10)
    assert net == [] and hits == []
    assert _refused(ei)


def test_with_consent_the_redirect_is_followed(net, origin):
    base, _hits = origin
    _grant()
    with pytest.raises(S.SynergyError) as ei:
        S._http_get_json(f"{base}/to-wiki/vanity", timeout_s=10)
    # The consented redirect reaches the wiki host once; the patched connect
    # refuses it, so it fails as an ordinary transport error, not a refusal.
    assert net and all(c.startswith("connect wiki.leagueoflegends.com:") for c in net)
    assert len(net) == 1
    assert not _refused(ei)


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, _hits = origin
    assert S._http_get_json(f"{base}/to-local", timeout_s=10)["data"] == [_ROW]
    assert net == []


def test_fetch_rows_stays_fail_soft_and_stops_the_date_loop_on_a_refusal(net, origin, monkeypatch):
    """None, zero wiki sockets, ONE origin request (not one per candidate
    date), and the failure is negative-cached like any other."""
    base, hits = origin
    monkeypatch.setattr(S, "_ENDPOINT", f"{base}/to-wiki/vanity")
    assert S.fetch_rows("bottom", "support") is None
    assert net == []
    assert hits == ["/to-wiki/vanity"]
    assert S.fetch_rows("bottom", "support") is None
    assert hits == ["/to-wiki/vanity"], "the refusal was not negative-cached"


def test_fetch_rows_still_reads_a_non_wiki_redirect(net, origin, monkeypatch):
    base, _hits = origin
    monkeypatch.setattr(S, "_ENDPOINT", f"{base}/to-local")
    assert S.fetch_rows("bottom", "support") == [_ROW]
    assert net == []
