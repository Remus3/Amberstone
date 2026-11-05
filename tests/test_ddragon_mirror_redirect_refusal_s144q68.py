"""RM-1441 (third-party fetcher census, site tools/ddragon_mirror_refresh.py) -
the DDragon mirror refresh refuses a request to, or a redirect INTO, the League
wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the
three wiki tools and ``lib/http/client.py``, RM-1440 on
``tools/upstream_drift_check.py``, earlier RM-1441 cycles on
``core/synergy_external_source.py``, ``core/rank_tier_source.py`` and
``tft/assets/icon_cache.py``).

``tools/ddragon_mirror_refresh.py`` ``_http`` (the one seam behind
``http_get`` / ``http_head``, so behind the versions probe, every bundle pull,
every champion detail pull and every asset GET / HEAD) opened with
``urllib.request.urlopen``, whose default opener follows a 3xx, so a Data
Dragon url answering 302 to the wiki host opened a wiki socket with no consent
record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still resolves.

A refusal is not a transient network error: ``_http`` must not retry it (no
backoff sleep, one origin hit), the versions probe fails loud with it, and an
asset worker counts it as one failed asset with no file written.
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
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402
from tests._sleep_probe import record_sleeps  # noqa: E402
from tools import ddragon_mirror_refresh as ddr  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"asset-bytes"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def _route(self, with_body: bool) -> None:
            path = urlsplit(self.path).path
            hits.append(f"{self.command} {path}")
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
                if with_body:
                    self.wfile.write(PNG)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_GET(self):  # noqa: N802 - stdlib handler name
            self._route(True)

        def do_HEAD(self):  # noqa: N802 - stdlib handler name
            self._route(False)

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
    """(base url, request log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-ddragon-mirror-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
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


# -- the _http seam (http_get / http_head) ------------------------------------------

@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_get_redirected_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, hits = origin
    with record_sleeps() as sleeps:
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.http_get(f"{base}/to-wiki/{target}")
    assert net == []
    # Refused once, never retried: a refusal is not a transient network error.
    assert hits == [f"GET /to-wiki/{target}"]
    assert sleeps == []


def test_a_head_redirected_into_the_wiki_is_refused(net, origin):
    """The --check-changed HEAD probe goes through the same seam."""
    base, hits = origin
    with record_sleeps() as sleeps:
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.http_head(f"{base}/to-wiki/fandom")
    assert net == []
    assert hits == ["HEAD /to-wiki/fandom"]
    assert sleeps == []


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with record_sleeps():
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.http_get(f"{base}/hop/vanity")
    assert net == []
    assert hits == ["GET /hop/vanity", "GET /to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with record_sleeps() as sleeps:
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.http_get(WIKI_TARGETS["vanity"])
    assert net == [] and hits == [] and sleeps == []


def test_with_consent_the_redirect_is_followed(net, origin, monkeypatch):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    monkeypatch.setattr(ddr, "RETRY_BACKOFFS", ())
    with pytest.raises(urllib.error.URLError):
        ddr.http_get(f"{base}/to-wiki/vanity")
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, hits = origin
    res = ddr.http_get(f"{base}/to-local")
    assert (res.status, res.body) == (200, PNG)
    assert net == []
    assert hits == ["GET /to-local", "GET /ok.png"]


def test_a_head_to_a_non_wiki_target_still_resolves(net, origin):
    base, hits = origin
    res = ddr.http_head(f"{base}/to-local")
    assert (res.status, res.body) == (200, b"")
    assert res.headers.get("content-length") == str(len(PNG))
    assert hits == ["HEAD /to-local", "HEAD /ok.png"]


# -- the callers ---------------------------------------------------------------------

def test_the_versions_probe_fails_loud_on_a_wiki_redirect(net, origin, monkeypatch):
    base, hits = origin
    monkeypatch.setattr(ddr, "VERSIONS_URL", f"{base}/to-wiki/wikigg")
    with record_sleeps() as sleeps:
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.resolve_latest_version()
    assert net == [] and sleeps == []
    assert hits == ["GET /to-wiki/wikigg"]


def test_an_asset_redirected_into_the_wiki_writes_no_file(net, origin, tmp_path):
    base, hits = origin
    dest = tmp_path / "img" / "item" / "1001.png"
    asset = ddr.Asset(cls="item", url=f"{base}/to-wiki/vanity", rel_dest="img/item/1001.png")
    with record_sleeps():
        with pytest.raises(wiki_consent.WikiFetchRefused):
            ddr.fetch_one(asset, dest, manifest_entry=None, check_changed=False, force=True)
    assert not dest.exists()
    assert net == []
    assert hits == ["GET /to-wiki/vanity"]
