"""RM-1440 - the upstream drift checker refuses a redirect INTO the League
wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the
three wiki tools and ``lib/http/client.py`` only).

``tools/upstream_drift_check.py`` ``_http_get`` probes Data Dragon, Meraki and
CommunityDragon with ``urllib.request.urlopen``, whose default opener follows a
3xx. A non-wiki url answering 302 to the wiki host therefore opened a socket to
the wiki with no consent record. The same process runs the wiki staleness mode
(``--staleness-recent``), so the drift checker is the fetcher the RM-1254
filing named first.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and to pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by an
exception alone. With a valid consent record the same redirect IS followed
(one recorded wiki connect), so the refusal is conditional, and a redirect to a
non-wiki target still resolves normally.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import json
import socket
import sys
import threading
import urllib.error
from pathlib import Path

import pytest

from lib import wiki_consent
from tests._module_view import this_thread_only

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import upstream_drift_check as drift  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
OK_BODY = b'["16.22.1", "16.21.1"]'


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = self.path
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
                         name="s144q67-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture
def net(monkeypatch, tmp_path):
    """Record-and-refuse wiki connects; no retry sleeps; consent path in an empty dir."""
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
    # The retry schedule keeps its length (the retry COUNT) but sleeps 0 s.
    monkeypatch.setattr(drift, "RETRY_BACKOFFS", (0.0,) * len(drift.RETRY_BACKOFFS))
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    return calls


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, _hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        drift._http_get(f"{base}/to-wiki/{target}", timeout=10)
    assert net == []


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        drift._http_get(f"{base}/hop/vanity", timeout=10)
    assert net == []
    assert hits == ["/hop/vanity", "/to-wiki/vanity"]


def test_the_refusal_is_not_retried(net, origin):
    """A refusal is a ruling, not a transport blip: one origin request, no retry."""
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        drift._http_get(f"{base}/to-wiki/vanity", timeout=10)
    assert hits == ["/to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        drift._http_get(WIKI_TARGETS["vanity"], timeout=10)
    assert net == [] and hits == []


def test_with_consent_the_redirect_is_followed(net, origin):
    base, _hits = origin
    _grant()
    with pytest.raises(urllib.error.URLError):
        drift._http_get(f"{base}/to-wiki/vanity", timeout=10)
    # The consented redirect reaches the wiki host; the patched connect refuses
    # it, and the retry loop retries a transport error, so every attempt
    # reaches the wiki once.
    assert net and all(c.startswith("connect wiki.leagueoflegends.com:") for c in net)
    assert len(net) == len(drift.RETRY_BACKOFFS) + 1


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, _hits = origin
    assert drift._http_get(f"{base}/to-local", timeout=10) == OK_BODY
    assert net == []


def test_the_probe_stays_fail_soft_on_a_refused_redirect(net, origin, monkeypatch):
    """probe_ddragon_version records the refusal as its error and returns None."""
    base, _hits = origin
    monkeypatch.setattr(drift, "DDRAGON_VERSIONS_URL", f"{base}/to-wiki/vanity")
    monkeypatch.setitem(drift._LAST_ERRORS, "ddragon_version", None)
    assert drift.probe_ddragon_version() is None
    assert (drift._LAST_ERRORS["ddragon_version"] or "").startswith("WikiFetchRefused:")
    assert net == []


def test_the_probe_still_reads_a_non_wiki_redirect(net, origin, monkeypatch):
    base, _hits = origin
    monkeypatch.setattr(drift, "DDRAGON_VERSIONS_URL", f"{base}/to-local")
    monkeypatch.setitem(drift._LAST_ERRORS, "ddragon_version", None)
    assert drift.probe_ddragon_version() == "16.22.1"
    assert drift._LAST_ERRORS["ddragon_version"] is None
