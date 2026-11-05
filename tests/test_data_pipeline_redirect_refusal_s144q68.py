"""RM-1441 (third-party fetcher census, site scripts/data_pipeline.py) - the
weekly data pipeline refuses a request to, or a redirect INTO, the League wiki
host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the three
wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles on the other
DDragon / CommunityDragon fetchers).

``scripts/data_pipeline.py`` ``_fetch_json`` (the version list, the champion /
item / summoner / rune JSON and the operator-configured ARAM tier table) and
``_fetch_bytes`` (every champion, spell and rune icon) opened with
``urllib.request.urlopen``, whose default opener follows a 3xx, so a Data
Dragon url answering 302 to the wiki host opened a wiki socket with no consent
record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still resolves.

Every caller of the two fetchers already catches ``Exception``, so a refusal
(a RuntimeError, not an OSError) lands in the command's existing failure path:
an icon counts as not downloaded and writes no file, and a meta command logs
its FAILED line and returns False with nothing written.
"""
from __future__ import annotations

import ast
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

import scripts.data_pipeline as dp  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402
from tests._sleep_probe import record_sleeps  # noqa: E402

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
DOC = {"version": "16.1.1", "data": {}}
PNG = b"\x89PNG\r\n\x1a\n" + b"icon-bytes"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            if path.startswith("/to-wiki/"):
                self._redirect(WIKI_TARGETS[path.rsplit("/", 1)[1]])
            elif path.startswith("/hop/"):
                self._redirect("/to-wiki/" + path.rsplit("/", 1)[1])
            elif path.startswith("/cdn/"):
                # Every DDragon CDN path of a pipeline command goes to the wiki.
                self._redirect(WIKI_TARGETS["vanity"])
            elif path == "/to-local":
                self._redirect("/ok.json")
            elif path == "/ok.json":
                self._body(json.dumps(DOC).encode("utf-8"), "application/json")
            elif path == "/ok.png":
                self._body(PNG, "image/png")
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def _body(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
                         name="s144q68-data-pipeline-origin", daemon=True)
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


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_json_fetch_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        dp._fetch_json(f"{base}/to-wiki/{target}")
    assert net == []
    assert hits == [f"GET /to-wiki/{target}"]


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_bytes_fetch_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        dp._fetch_bytes(f"{base}/to-wiki/{target}")
    assert net == []
    assert hits == [f"GET /to-wiki/{target}"]


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        dp._fetch_json(f"{base}/hop/vanity")
    assert net == []
    assert hits == ["GET /hop/vanity", "GET /to-wiki/vanity"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    for fetch in (dp._fetch_json, dp._fetch_bytes):
        with pytest.raises(wiki_consent.WikiFetchRefused):
            fetch(WIKI_TARGETS["vanity"])
    assert net == [] and hits == []


def test_with_consent_the_redirect_is_followed(net, origin):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    with pytest.raises(OSError):
        dp._fetch_json(f"{base}/to-wiki/vanity")
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, hits = origin
    assert dp._fetch_json(f"{base}/to-local") == DOC
    assert dp._fetch_bytes(f"{base}/ok.png") == PNG
    assert net == []
    assert hits == ["GET /to-local", "GET /ok.json", "GET /ok.png"]


def test_an_icon_redirected_into_the_wiki_writes_nothing(net, origin, tmp_path):
    """The icon caller's existing failure path: False, no file, run moves on."""
    base, _hits = origin
    dest = tmp_path / "icons" / "champions" / "Ahri.png"
    dest.parent.mkdir(parents=True)
    with record_sleeps() as sleeps:
        assert dp._download_icon(f"{base}/to-wiki/vanity", dest, "Ahri") is False
    assert net == [] and sleeps == []
    assert not dest.exists()
    # The same caller still lands an icon from a non-wiki origin.
    with record_sleeps():
        assert dp._download_icon(f"{base}/ok.png", dest, "Ahri") is True
    assert dest.read_bytes() == PNG


def test_cmd_runes_with_its_cdn_redirected_into_the_wiki_fails_and_writes_nothing(
        net, origin, tmp_path, monkeypatch):
    """End to end: a refused meta JSON is the command's FAILED path, no file."""
    base, hits = origin
    meta = tmp_path / "meta"
    icons = tmp_path / "icons"
    meta.mkdir()
    icons.mkdir()
    monkeypatch.setattr(dp, "META", meta)
    monkeypatch.setattr(dp, "ICONS", icons)
    monkeypatch.setattr(dp, "DDRAGON_BASE", base)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "16.1.1")
    assert dp.cmd_runes(force=True) is False
    assert net == []
    assert hits == ["GET /cdn/16.1.1/data/en_US/runesReforged.json"]
    assert list(meta.iterdir()) == []
    assert list(icons.iterdir()) == []


def test_both_fetchers_open_through_the_consent_opener():
    """Source pin: no bare urlopen call is left in the module."""
    assert dp.open_consented is wiki_consent.open_consented
    src = (_ROOT / "scripts" / "data_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    urlopen_calls = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
        and getattr(node.func, "attr", getattr(node.func, "id", "")) == "urlopen"
    ]
    assert urlopen_calls == []
