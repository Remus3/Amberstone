"""RM-1564 (RM-1441 shape, third-party fetcher census continued; site
scripts/fetch_external_tft_meta.py) - the external TFT meta fetch refuses a
request to, or a redirect INTO, the League wiki host (ruling 51,
``RM962-S146-R51``; RM-1254 closed the same shape on the three wiki tools and
``lib/http/client.py``, RM-1441 on the synergy, rank-tier and augment sources,
the TFT icon cache, the DDragon mirror refresh, the scripts/ downloaders and
the rewind scraper).

``main`` opened both fetch loops (the GraphQL POSTs and the static data GETs)
with ``urllib.request.urlopen``, whose default opener follows a 3xx: a
configured meta url answering 302 to the wiki host opened a wiki socket with
no consent record. The targets are operator configuration
(``config/external_sources.json``), so a configured wiki url was opened
directly too.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.
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

from lib import wiki_consent  # noqa: E402
from scripts import fetch_external_tft_meta as FM  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

_SRC = _ROOT / "scripts" / "fetch_external_tft_meta.py"

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PAYLOAD = {"comps": [{"name": "synthetic comp", "tier": "S"}]}
BODY = json.dumps(PAYLOAD).encode("utf-8")


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def _route(self, verb: str) -> None:
            path = urlsplit(self.path).path
            hits.append(f"{verb} {path}")
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            leaf = path.rsplit("/", 1)[1]
            if leaf.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[leaf[len("to-wiki-"):]])
            elif leaf.startswith("hop-"):
                self._redirect("to-wiki-" + leaf[len("hop-"):])
            elif leaf == "to-local":
                self._redirect("data.json")
            elif leaf == "data.json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def do_GET(self):  # noqa: N802 - stdlib handler name
            self._route("GET")

        def do_POST(self):  # noqa: N802 - stdlib handler name
            self._route("POST")

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
                         name="s144q80-tft-meta-origin", daemon=True)
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


@pytest.fixture()
def configure(monkeypatch, tmp_path):
    """Point the script at synthetic sources and a tmp RAW_OUT; return RAW_OUT."""
    raw = tmp_path / "out" / "raw.json"

    def _set(graphql: str | None = None, data_urls: list[str] | None = None) -> Path:
        class _Sources:
            @staticmethod
            def value(key):
                if key == "tft_meta_graphql":
                    return graphql
                return "https://example.invalid"

            @staticmethod
            def values(key):
                return list(data_urls or []) if key == "tft_meta_data_urls" else []

        monkeypatch.setattr(FM, "external_sources", _Sources)
        monkeypatch.setattr(FM, "RAW_OUT", raw)
        return raw

    return _set


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_data_url_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, configure, capsys, target):
    base, hits = origin
    url = f"{base}/meta/to-wiki-{target}"
    raw = configure(data_urls=[url])
    assert FM.main() == 1
    assert net == []
    assert hits == [f"GET /meta/to-wiki-{target}"]
    assert not raw.exists()
    assert f"REFUSED {url}" in capsys.readouterr().out


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_graphql_post_redirected_into_the_wiki_is_refused(
        net, origin, configure, capsys, target):
    base, hits = origin
    url = f"{base}/gql/to-wiki-{target}"
    raw = configure(graphql=url)
    assert FM.main() == 1
    assert net == []
    # Both GraphQL shapes are tried, each refused at its first hop.
    assert hits == [f"POST /gql/to-wiki-{target}"] * 2
    assert not raw.exists()
    assert capsys.readouterr().out.count(f"REFUSED {url}") == 2


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, configure):
    base, hits = origin
    raw = configure(data_urls=[f"{base}/meta/hop-vanity"])
    assert FM.main() == 1
    assert net == []
    assert hits == ["GET /meta/hop-vanity", "GET /meta/to-wiki-vanity"]
    assert not raw.exists()


def test_a_configured_wiki_url_is_refused_before_any_socket(net, origin, configure, capsys):
    _base, hits = origin
    raw = configure(graphql=WIKI_TARGETS["wikigg"], data_urls=[WIKI_TARGETS["vanity"]])
    assert FM.main() == 1
    assert net == []
    assert hits == []
    assert not raw.exists()
    out = capsys.readouterr().out
    assert f"REFUSED {WIKI_TARGETS['vanity']}" in out
    assert out.count(f"REFUSED {WIKI_TARGETS['wikigg']}") == 2


def test_with_consent_the_redirect_is_followed(net, origin, configure):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    configure(data_urls=[f"{base}/meta/to-wiki-vanity"])
    assert FM.main() == 1
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, configure):
    base, hits = origin
    url = f"{base}/meta/to-local"
    raw = configure(data_urls=[url])
    assert FM.main() == 0
    assert net == []
    assert hits == ["GET /meta/to-local", "GET /meta/data.json"]
    assert json.loads(raw.read_text(encoding="utf-8")) == {url: PAYLOAD}


def test_a_refused_url_does_not_stop_the_next_one(net, origin, configure, capsys):
    """One refused source is skipped; the sweep goes on to the next url."""
    base, hits = origin
    bad, good = f"{base}/meta/to-wiki-fandom", f"{base}/meta/data.json"
    raw = configure(data_urls=[bad, good])
    assert FM.main() == 0
    assert net == []
    assert json.loads(raw.read_text(encoding="utf-8")) == {good: PAYLOAD}
    assert f"REFUSED {bad}" in capsys.readouterr().out


def test_the_script_opens_through_the_consent_opener():
    """Source pin: both loops open through open_consented, no urlopen is left."""
    assert FM.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 2
