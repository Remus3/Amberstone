"""RM-1441 (third-party fetcher census, site scripts/rewind_scraper.py) - the
rewind.lol scraper refuses a request to, or a redirect INTO, the League wiki
host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the
three wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles on the
synergy, rank-tier and augment sources, the TFT icon cache, the DDragon
mirror refresh and the scripts/ downloaders).

``fetch_json`` opened with ``urllib.request.urlopen``, whose default opener
follows a 3xx: a rewind.lol url answering 302 to the wiki host opened a wiki
socket with no consent record, and the ``except Exception`` retry loop then
did it twice more.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.

A refusal keeps ``fetch_json``'s contract (None on a persistent failure, never
raises) and is NOT retried: it is deterministic, so a retry only re-asks the
origin and sleeps. ``time.sleep`` is recorded, never really slept.
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
from scripts import rewind_scraper as RS  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

_SRC = _ROOT / "scripts" / "rewind_scraper.py"

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PAYLOAD = {"metadata": {"matchId": "NA1_0000000001"}, "info": {"frames": []}}
BODY = json.dumps(PAYLOAD).encode("utf-8")


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            leaf = path.rsplit("/", 1)[1]
            if leaf.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[leaf[len("to-wiki-"):]])
            elif leaf.startswith("hop-"):
                self._redirect("to-wiki-" + leaf[len("hop-"):])
            elif leaf == "to-local":
                self._redirect("stats")
            elif leaf == "stats":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)
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
    """(base url, request log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-rewind-scraper-origin", daemon=True)
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
def sleeps(monkeypatch):
    """Record every retry sleep instead of sleeping."""
    seen: list[float] = []
    monkeypatch.setattr(RS.time, "sleep", seen.append)
    return seen


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_rewind_url_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, sleeps, target):
    base, hits = origin
    assert RS.fetch_json(f"{base}/getmatch/NA/to-wiki-{target}") is None
    assert net == []
    # Refused once, not retried: one origin request and no backoff sleep.
    assert hits == [f"GET /getmatch/NA/to-wiki-{target}"]
    assert sleeps == []


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, sleeps):
    base, hits = origin
    assert RS.fetch_json(f"{base}/getmatch/NA/hop-vanity") is None
    assert net == []
    assert hits == ["GET /getmatch/NA/hop-vanity", "GET /getmatch/NA/to-wiki-vanity"]
    assert sleeps == []


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin, sleeps):
    _base, hits = origin
    assert RS.fetch_json(WIKI_TARGETS["vanity"]) is None
    assert net == []
    assert hits == []
    assert sleeps == []


def test_the_refusal_is_reported_on_the_console(net, origin, sleeps, capsys):
    base, _hits = origin
    url = f"{base}/getmatch/NA/to-wiki-wikigg"
    assert RS.fetch_json(url) is None
    out = capsys.readouterr().out
    assert "refused" in out.lower()
    assert url in out


def test_with_consent_the_redirect_is_followed(net, origin, sleeps):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    assert RS.fetch_json(f"{base}/getmatch/NA/to-wiki-vanity", retries=1) is None
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, sleeps):
    base, hits = origin
    assert RS.fetch_json(f"{base}/getmatch/NA/to-local") == PAYLOAD
    assert net == []
    assert hits == ["GET /getmatch/NA/to-local", "GET /getmatch/NA/stats"]
    assert sleeps == []


def test_a_404_still_returns_none_without_a_retry(net, origin, sleeps):
    """Control: the existing not-found path is unchanged by the opener swap."""
    base, hits = origin
    assert RS.fetch_json(f"{base}/getmatch/NA/missing") is None
    assert hits == ["GET /getmatch/NA/missing"]
    assert sleeps == []


def test_the_scraper_opens_through_the_consent_opener():
    """Source pin: fetch_json opens through open_consented, no urlopen is left."""
    assert RS.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 1
