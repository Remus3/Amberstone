"""RM-1254 - a redirect INTO the League wiki host is refused like a direct
wiki request (ruling 51, ``RM962-S146-R51``; RM-1227 refused only the url a
caller passed).

The three urllib tools (``tools/daemon_slayer_wiki_ability_extract.py``
``_fetch``, ``tools/daemon_slayer_wiki_stats_extract.py`` ``_fetch``,
``tools/ds_windup_offset_compare.py`` ``_fetch_module``) and the shared
``lib/http/client.py`` ``HttpClient`` follow a 3xx. Before RM-1254 none of
them re-checked ``lib.wiki_consent`` on the redirect TARGET, so a non-wiki url
answering 302 to the wiki host opened a socket to the wiki with no consent
record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and to pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by an
exception alone. With a valid consent record the same redirect IS followed
(one recorded wiki connect), so the refusal is conditional, and a redirect to
a non-wiki target still resolves normally.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lib import wiki_consent
from lib.http import client as http_client
from tests._module_view import this_thread_only

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as ability  # noqa: E402
import daemon_slayer_wiki_stats_extract as stats  # noqa: E402
import ds_windup_offset_compare as windup  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
OK_BODY = "ok-body"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler name
        path = self.path
        if path.startswith("/to-wiki/"):
            self._redirect(WIKI_TARGETS[path.rsplit("/", 1)[1]])
        elif path.startswith("/hop/"):
            self._redirect("/to-wiki/" + path.rsplit("/", 1)[1])
        elif path == "/to-local":
            self._redirect("/ok")
        elif path == "/ok":
            body = OK_BODY.encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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


@pytest.fixture
def origin():
    """A local origin server; stopped, closed and joined at teardown."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="rm1254-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture
def net(monkeypatch, tmp_path):
    """Record-and-refuse connects to a wiki host; consent path in an empty dir."""
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
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    return calls


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


_TOOL_CALLS = {
    "ability._fetch": lambda url: ability._fetch(url, timeout=10),
    "stats._fetch": lambda url: stats._fetch(url, timeout=10),
    "windup._fetch_module": lambda url: windup._fetch_module(url),
}


def _client_get(url: str) -> str:
    return http_client.HttpClient(trust_env_proxy=False).get(url, timeout=10).text()


_ALL_CALLS = dict(_TOOL_CALLS, **{"HttpClient.get": _client_get})


# ----------------------------------------------------------- the refusal


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
@pytest.mark.parametrize("name", sorted(_ALL_CALLS))
def test_redirect_into_the_wiki_is_refused_without_consent(net, origin, name, target):
    with pytest.raises(wiki_consent.WikiFetchRefused, match="RM962-S146-R51"):
        _ALL_CALLS[name](f"{origin}/to-wiki/{target}")
    assert net == [], "no socket may open to the wiki host without consent"


@pytest.mark.parametrize("name", sorted(_ALL_CALLS))
def test_second_hop_into_the_wiki_is_refused_without_consent(net, origin, name):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        _ALL_CALLS[name](f"{origin}/hop/vanity")
    assert net == []


def test_refused_redirect_does_not_count_against_the_breaker(net, origin):
    """A refusal is a policy act, not a remote failure: the HttpClient's
    breaker state for the origin stays clean (no failure, no stuck probe)."""
    client = http_client.HttpClient(trust_env_proxy=False)
    with pytest.raises(wiki_consent.WikiFetchRefused):
        client.get(f"{origin}/to-wiki/vanity", timeout=10)
    st = client._host_state("127.0.0.1")
    assert st.failures == 0 and st.opened_at is None and st.probe_in_flight is False
    assert net == []


# --------------------------------------------------- positive controls


@pytest.mark.parametrize("name", sorted(_TOOL_CALLS))
def test_tool_redirect_into_the_wiki_is_followed_with_consent(net, origin, name):
    _grant()
    with pytest.raises(urllib.error.URLError):
        _TOOL_CALLS[name](f"{origin}/to-wiki/vanity")
    assert net == ["connect wiki.leagueoflegends.com:80"]


def test_client_redirect_into_the_wiki_is_followed_with_consent(net, origin):
    _grant()
    with pytest.raises(http_client.HttpError):
        _client_get(f"{origin}/to-wiki/vanity")
    assert net == ["connect wiki.leagueoflegends.com:80"]


@pytest.mark.parametrize("name", sorted(_ALL_CALLS))
def test_non_wiki_redirect_still_resolves_without_consent(net, origin, name):
    assert _ALL_CALLS[name](f"{origin}/to-local") == OK_BODY
    assert net == []


@pytest.mark.parametrize("kind", ["wiki_consent", "HttpClient"])
def test_redirect_handler_closes_the_redirect_response_when_it_refuses(net, kind):
    """The refused hop's response is closed, not left for the collector."""

    class _Fp:
        closed = False

        def close(self):
            self.closed = True

    fp = _Fp()
    req = urllib.request.Request("http://127.0.0.1:9/x")
    if kind == "wiki_consent":
        handler = wiki_consent.WikiConsentRedirectHandler()
    else:
        handler = http_client._BlocklistRedirectHandler(
            http_client.HttpClient(trust_env_proxy=False))
    with pytest.raises(wiki_consent.WikiFetchRefused):
        handler.redirect_request(req, fp, 302, "Found", {}, WIKI_TARGETS["vanity"])
    assert fp.closed is True
