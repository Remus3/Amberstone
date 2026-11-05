"""RM-1441 (third-party fetcher census, site scripts/fetch_cdragon_tft.py) -
the set-agnostic CommunityDragon TFT ingest refuses a request to, or a
redirect INTO, the League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254
closed the same shape on the three wiki tools and ``lib/http/client.py``,
earlier RM-1441 cycles on the synergy and rank-tier sources, the TFT icon
cache, the DDragon mirror refresh, the three scripts/ icon downloaders and
the PBE fetcher).

``_http_get`` opened with ``urllib.request.urlopen``, whose default opener
follows a 3xx: a CommunityDragon url answering 302 to the wiki host opened a
wiki socket with no consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (a recorded wiki connect), so the refusal
is conditional, and a redirect to a non-wiki target still lands.

A refusal is a ``WikiFetchRefused`` (a RuntimeError, not an OSError): the
retry loop does not retry it (no backoff sleep), ``main`` reports it on stderr
and exits 1 with nothing written when the TFT payload is refused, and a
refused content-metadata hop leaves ``_content_version`` None like any other
metadata failure while the extract from the non-wiki payload is still
written. The transient-HTTP retry idiom survives the swap.
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

import scripts.fetch_cdragon_tft as fct  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import bind_module_view, this_thread_only  # noqa: E402
from tests.test_fetch_cdragon_tft import FIXTURE, META  # noqa: E402

_SRC = _ROOT / "scripts" / "fetch_cdragon_tft.py"

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
TFT_PATH = "/latest/cdragon/tft/en_us.json"
META_PATH = "/latest/content-metadata.json"
PAYLOAD = json.dumps(FIXTURE).encode("utf-8")
META_BODY = json.dumps(META).encode("utf-8")
OK_BODY = b'{"ok": true}'


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str], routes: dict):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            route = routes.get(path)
            if route is None:
                leaf = path.rsplit("/", 1)[1]
                if leaf.startswith("to-wiki-"):
                    route = ("redirect", WIKI_TARGETS[leaf[len("to-wiki-"):-len(".json")]])
                elif leaf.startswith("hop-"):
                    route = ("redirect", "to-wiki-" + leaf[len("hop-"):])
                elif leaf == "to-local.json":
                    route = ("redirect", "ok.json")
                elif leaf == "ok.json":
                    route = ("body", OK_BODY)
            if route is None:
                self._send(404, b"")
            elif route[0] == "redirect":
                self.send_response(302)
                self.send_header("Location", route[1])
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif route[0] == "status":
                self._send(route[1], b"")
                routes.pop(path)  # one transient answer, then the default route
            else:
                self._send(200, route[1])

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the stdlib access log
            pass

    return _Handler


@pytest.fixture()
def origin(monkeypatch):
    """(base url, request log, routes) of a local origin; CDRAGON_BASE points at
    it; stopped and joined at teardown."""
    hits: list[str] = []
    routes: dict = {}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits, routes))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-fetch-cdragon-tft-origin", daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(fct, "CDRAGON_BASE", base)
    try:
        yield base, hits, routes
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
def sleeps(monkeypatch):
    """The retry loop's backoff sleeps, recorded and skipped (module view only)."""
    seen: list[float] = []
    bind_module_view(monkeypatch, fct, "time", sleep=seen.append)
    return seen


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_cdragon_url_redirected_into_the_wiki_is_refused_and_not_retried(
        net, origin, sleeps, target):
    base, hits, _routes = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        fct._http_get(f"{base}/latest/to-wiki-{target}.json", timeout=10)
    assert net == []
    assert hits == [f"GET /latest/to-wiki-{target}.json"]
    assert sleeps == []


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, sleeps):
    base, hits, _routes = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        fct._http_get(f"{base}/latest/hop-vanity.json", timeout=10)
    assert net == []
    assert hits == ["GET /latest/hop-vanity.json", "GET /latest/to-wiki-vanity.json"]
    assert sleeps == []


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin, sleeps):
    _base, hits, _routes = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        fct._http_get(WIKI_TARGETS["vanity"], timeout=10)
    assert net == []
    assert hits == []
    assert sleeps == []


def test_with_consent_the_redirect_is_followed(net, origin, sleeps):
    """Positive control: the refusal is the consent gate, not a dead redirect.
    The recorded connect is an OSError, so the retry idiom runs all attempts."""
    base, _hits, _routes = origin
    _grant()
    with pytest.raises(OSError):
        fct._http_get(f"{base}/latest/to-wiki-vanity.json", timeout=10)
    assert len(net) == len(fct.RETRY_BACKOFFS) + 1
    assert all(c.startswith("connect wiki.leagueoflegends.com:") for c in net)
    assert sleeps == list(fct.RETRY_BACKOFFS)


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, sleeps):
    base, hits, _routes = origin
    assert fct._http_get(f"{base}/latest/to-local.json", timeout=10) == OK_BODY
    assert net == []
    assert hits == ["GET /latest/to-local.json", "GET /latest/ok.json"]
    assert sleeps == []


def test_a_transient_http_error_is_still_retried(net, origin, sleeps):
    base, hits, routes = origin
    routes["/latest/ok.json"] = ("status", 503)
    assert fct._http_get(f"{base}/latest/ok.json", timeout=10) == OK_BODY
    assert hits == ["GET /latest/ok.json", "GET /latest/ok.json"]
    assert sleeps == [fct.RETRY_BACKOFFS[0]]
    assert net == []


def test_main_with_the_payload_refused_writes_nothing_and_exits_one(
        net, origin, sleeps, tmp_path, capsys):
    _base, hits, routes = origin
    routes[TFT_PATH] = ("redirect", WIKI_TARGETS["wikigg"])
    out = tmp_path / "tft_set18_cdragon.json"
    out.write_bytes(b'{"keep": true}\n')
    assert fct.main(["--set", "18", "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("fetch_cdragon_tft: refused")
    assert "Traceback" not in err
    assert out.read_bytes() == b'{"keep": true}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["consent", out.name]
    assert net == []
    assert hits == [f"GET {TFT_PATH}"]
    assert sleeps == []


def test_main_with_the_metadata_refused_still_writes_the_extract(
        net, origin, sleeps, tmp_path):
    _base, hits, routes = origin
    routes[TFT_PATH] = ("body", PAYLOAD)
    routes[META_PATH] = ("redirect", WIKI_TARGETS["fandom"])
    out = tmp_path / "tft_set18_cdragon.json"
    assert fct.main(["--set", "18", "--out", str(out)]) == 0
    extract = json.loads(out.read_bytes())
    assert extract["_set"] == 18
    assert extract["_content_version"] is None
    assert net == []
    assert hits == [f"GET {TFT_PATH}", f"GET {META_PATH}"]
    assert sleeps == []


def test_main_end_to_end_through_the_local_origin(net, origin, sleeps, tmp_path):
    """The real opener path (no _http_get fake) still produces the extract."""
    _base, hits, routes = origin
    routes[TFT_PATH] = ("body", PAYLOAD)
    routes[META_PATH] = ("body", META_BODY)
    out = tmp_path / "tft_set18_cdragon.json"
    assert fct.main(["--set", "18", "--out", str(out)]) == 0
    assert json.loads(out.read_bytes())["_content_version"] == META["version"]
    assert hits == [f"GET {TFT_PATH}", f"GET {META_PATH}"]
    assert net == []


def test_the_get_hands_the_consent_opener_its_request_and_timeout(monkeypatch):
    """No custom TLS context: the default verifying context stays in force."""
    seen: list = []

    class _Stop(Exception):
        pass

    def fake(req, timeout, context=None):
        seen.append((req.full_url, req.get_header("User-agent"), timeout, context))
        raise _Stop("test refuses network access")

    monkeypatch.setattr(fct, "open_consented", fake)
    with pytest.raises(_Stop):
        fct._http_get(fct.tft_url("pbe"), timeout=7.5)
    assert seen == [(fct.tft_url("pbe"), fct.USER_AGENT, 7.5, None)]


def test_the_script_opens_through_the_consent_opener():
    """Source pin: the GET opens through open_consented, no urlopen is left."""
    assert fct.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 1
