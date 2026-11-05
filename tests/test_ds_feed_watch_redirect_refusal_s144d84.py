"""RM-1508 / RM-1441 (third-party fetcher census, the Daemon Slayer feed watch) -
``tools/ds_feed_watch.py`` ``UrllibHttp`` refuses a request to, or a redirect
INTO, the League wiki host (ruling 51, ``RM962-S146-R51``; the RM-1507 test
``test_ds_extractors_redirect_refusal_s144d82.py`` closes the same shape on the
four DS extractors).

``UrllibHttp.head`` and ``UrllibHttp.get`` opened the upstream feed with
``urllib.request.urlopen``, whose default opener follows a 3xx: a feed url (or a
live-build crawl url) answering 302 to the wiki host opened a wiki socket with
no consent record. They now open through ``lib.wiki_consent.open_consented``.

The origin is a real local HTTP server on 127.0.0.1 so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.

The watch is report-only and never raises on a transport error:
``check_blocks`` and the live-build crawl catch every exception, so a refused
hop is a missing status, not a crash.
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
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

import ds_feed_watch as fw  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
OK_BODY = b"chunk-bytes"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            path = urlsplit(self.path).path
            hits.append(f"{method} {path}")
            stem = path.rsplit("/", 1)[1].rpartition(".")[0]
            if stem.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[stem[len("to-wiki-"):]])
            elif stem.startswith("hop-"):
                self._redirect(f"to-wiki-{stem[len('hop-'):]}.js")
            elif stem == "to-local":
                self._redirect("ok.js")
            elif stem == "ok":
                self.send_response(200)
                self.send_header("Content-Length", str(len(OK_BODY)))
                self.end_headers()
                if method == "GET":
                    self.wfile.write(OK_BODY)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_GET(self):  # noqa: N802 - stdlib handler name
            self._serve("GET")

        def do_HEAD(self):  # noqa: N802 - stdlib handler name
            self._serve("HEAD")

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
                         name="s144d84-ds-feed-watch-origin", daemon=True)
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


METHODS = {"head": lambda url: fw.UrllibHttp().head(url),
           "get": lambda url: fw.UrllibHttp().get(url)}


@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_redirect_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, method, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        METHODS[method](f"{base}/x/to-wiki-{target}.js")
    assert net == []
    assert hits == [f"{method.upper()} /x/to-wiki-{target}.js"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, method):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        METHODS[method](f"{base}/x/hop-vanity.js")
    assert net == []
    verb = method.upper()
    assert hits == [f"{verb} /x/hop-vanity.js", f"{verb} /x/to-wiki-vanity.js"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_a_direct_wiki_url_is_refused_before_any_socket(net, method):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        METHODS[method](WIKI_TARGETS["vanity"])
    assert net == []


@pytest.mark.parametrize("method", sorted(METHODS))
def test_with_consent_the_redirect_is_followed(net, origin, method):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    with pytest.raises(OSError):  # URLError wrapping the patched connect's refusal
        METHODS[method](f"{base}/x/to-wiki-vanity.js")
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin):
    base, hits = origin
    assert fw.UrllibHttp().head(f"{base}/x/to-local.js") == 200
    assert fw.UrllibHttp().get(f"{base}/x/to-local.js") == (200, OK_BODY)
    assert net == []
    assert hits == ["HEAD /x/to-local.js", "HEAD /x/ok.js",
                    "GET /x/to-local.js", "GET /x/ok.js"]


def test_a_missing_chunk_is_still_a_status_not_a_raise(net, origin):
    """The carve-out for a refusal must keep the HTTPError -> status mapping."""
    base, _hits = origin
    assert fw.UrllibHttp().head(f"{base}/x/missing.js") == 404
    assert fw.UrllibHttp().get(f"{base}/x/missing.js") == (404, b"")


# --- the report-only callers stay report-only -----------------------------------

def test_check_blocks_reports_a_refused_redirect_as_a_missing_status(net, origin):
    base, hits = origin
    manifest = {"sources": {"x_data_blocks": {"b1": f"{base}/x/to-wiki-fandom.js",
                                              "b2": f"{base}/x/ok.js"}}}
    rows = fw.check_blocks(manifest, fw.UrllibHttp(), now_iso="2026-11-05T00:00:00Z")
    assert rows["b1"]["status"] is None and rows["b1"]["body_md5"] is None
    assert rows["b2"]["status"] == 200 and rows["b2"]["body_md5"]
    assert net == []
    assert hits == ["HEAD /x/to-wiki-fandom.js", "HEAD /x/ok.js", "GET /x/ok.js"]


def test_the_live_crawl_treats_a_refused_root_as_unreadable(net, origin):
    base, hits = origin
    summary, _seen, _cands = fw.live_chunk_graph(
        f"{base}/x/to-wiki-wikigg.js", f"{base}/x/", fw.UrllibHttp())
    assert net == []
    assert hits == ["GET /x/to-wiki-wikigg.js"]
    assert summary["status"] == "failed" and summary["root_status"] is None


# --- the transport really is the consent opener --------------------------------

def test_the_transport_opens_through_the_consent_opener():
    """Source pin: no bare urlopen is left; the opener is the shared one."""
    src = (_ROOT / "tools" / "ds_feed_watch.py").read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert "open_consented(" in src
    assert fw.open_consented is wiki_consent.open_consented
