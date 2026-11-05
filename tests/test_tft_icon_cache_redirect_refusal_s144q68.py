"""RM-1441 (third-party fetcher census, site tft/assets/icon_cache.py) - the
TFT icon cache refuses a request to, or a redirect INTO, the League wiki host
(ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the three
wiki tools and ``lib/http/client.py``, RM-1440 on
``tools/upstream_drift_check.py``, earlier RM-1441 cycles on
``core/synergy_external_source.py`` and ``core/rank_tier_source.py``).

``tft/assets/icon_cache.py`` ``_http_get`` (the one GET seam of both
``CDragonSource`` and ``LcuSource``) opened with ``urllib.request.urlopen``,
whose default opener follows a 3xx, so a CommunityDragon (or LCU) url
answering 302 to the wiki host opened a wiki socket with no consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by a None
alone (the base also returned None: the patched connect raised an OSError it
swallowed, AFTER the wiki connect was attempted). With a consent record the
same redirect IS followed (one recorded wiki connect), so the refusal is
conditional, and a redirect to a non-wiki target still resolves.

The LCU source needs its no-verify TLS context (Riot's self-signed loopback
certificate), so ``lib.wiki_consent.open_consented`` takes an optional
``context`` and the icon cache passes it on. A fake context whose
``wrap_socket`` records and refuses proves the context reaches the TLS layer
without a certificate: the TCP connect to the local origin succeeds, then the
handshake is the fake's.
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
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402
from tft.assets import icon_cache as ic  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"icon-bytes"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


class _HandshakeRefused(OSError):
    """Raised by the fake TLS context after it records a handshake."""


class _FakeContext:
    """Records every wrap_socket call and refuses it (no certificate needed)."""

    def __init__(self):
        self.calls: list[str] = []

    def wrap_socket(self, sock, server_hostname=None, **_kw):
        self.calls.append(str(server_hostname))
        raise _HandshakeRefused("fake TLS context")


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
                self._redirect("/ok.png")
            elif path == "/ok.png":
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(PNG)))
                self.end_headers()
                self.wfile.write(PNG)
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
    """(base url, port, request-path log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-icon-cache-origin", daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        yield f"http://127.0.0.1:{port}", port, hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture()
def net(monkeypatch, tmp_path):
    """Record-and-refuse wiki connects; no proxy; consent path in an empty dir."""
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


# -- the GET seam -----------------------------------------------------------------

@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, _port, hits = origin
    assert ic._http_get(f"{base}/to-wiki/{target}", timeout=10) is None
    assert net == []
    assert hits == [f"/to-wiki/{target}"]


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, _port, hits = origin
    assert ic._http_get(f"{base}/hop/vanity", timeout=10) is None
    assert net == []
    assert hits == ["/hop/vanity", "/to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, _port, hits = origin
    assert ic._http_get(WIKI_TARGETS["vanity"], timeout=10) is None
    assert net == [] and hits == []


def test_with_consent_the_redirect_is_followed(net, origin):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _port, _hits = origin
    _grant()
    assert ic._http_get(f"{base}/to-wiki/vanity", timeout=10) is None
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, _port, hits = origin
    assert ic._http_get(f"{base}/to-local", timeout=10) == PNG
    assert net == []
    assert hits == ["/to-local", "/ok.png"]


def test_the_refusal_is_logged_by_type_without_the_query(net, origin, caplog):
    base, _port, _hits = origin
    caplog.set_level("DEBUG", logger=ic.logger.name)
    assert ic._http_get(f"{base}/to-wiki/vanity?k=secret-ish", timeout=10) is None
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == ic.logger.name)
    assert "WikiFetchRefused" in text, text
    assert "secret-ish" not in text, text


# -- the two sources ----------------------------------------------------------------

def test_cdragon_source_asset_refuses_a_redirect_into_the_wiki(net, origin, monkeypatch):
    base, _port, hits = origin
    monkeypatch.setattr(ic, "cdragon_url", lambda path, branch="latest": f"{base}/to-wiki/wikigg")
    src = ic.CDragonSource()
    assert src.asset("/lol-game-data/assets/ASSETS/UX/TFT/x.png") is None
    assert net == []
    assert hits == ["/to-wiki/wikigg"]


def test_cdragon_source_game_data_refuses_a_redirect_into_the_wiki(net, origin, monkeypatch):
    base, _port, hits = origin
    monkeypatch.setattr(ic, "CDRAGON_PLUGIN", base + "/hop/fandom?{branch}/")
    src = ic.CDragonSource()
    assert src.game_data("tfttraits.json") is None
    assert net == []
    assert hits == ["/hop/fandom", "/to-wiki/fandom"]


# -- the LCU TLS context survives the move ------------------------------------------

def test_open_consented_hands_a_caller_context_to_the_tls_layer(net, origin):
    _base, port, hits = origin
    ctx = _FakeContext()
    req = urllib.request.Request(f"https://127.0.0.1:{port}/x", method="GET")
    with pytest.raises(urllib.error.URLError):
        wiki_consent.open_consented(req, timeout=10, context=ctx)
    assert ctx.calls == ["127.0.0.1"]
    assert hits == []


def test_open_consented_without_a_context_is_unchanged(net, origin):
    base, _port, _hits = origin
    req = urllib.request.Request(f"{base}/to-local", method="GET")
    with wiki_consent.open_consented(req, timeout=10) as resp:
        assert resp.read() == PNG


def test_lcu_source_keeps_its_own_tls_context(net, origin):
    """The LCU GET still runs its handshake through the source's context (the
    no-verify one in production): a fake context sees exactly one handshake per
    GET, and the GET fails soft."""
    _base, port, hits = origin
    src = ic.LcuSource(port, "s3cret", host="127.0.0.1")
    ctx = _FakeContext()
    src._ctx = ctx
    assert src.queue_id() is None
    assert ctx.calls == ["127.0.0.1"]
    assert hits == []
    assert net == []
