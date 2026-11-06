"""RM-1564 remainder (RM-1441 shape, third-party fetcher census; site
core/rofl_archive.py ``_http_get_bytes``) - the pre-signed replay download
refuses a request to, or a redirect INTO, the League wiki host (ruling 51,
``RM962-S146-R51``; RM-1254 closed the same shape on the three wiki tools and
``lib/http/client.py``, RM-1441 and RM-1564 on the other third-party
fetchers).

``main`` opened every replay url with ``urllib.request.urlopen``, whose default
opener follows a 3xx: a replay url answering 302 to the wiki host opened a
wiki socket with no consent record. ``download_replays`` also caught only
``HTTPError`` / ``ReplayTooLarge`` / ``OSError``, so a refusal (a
``RuntimeError``) must be caught per item or one bad url aborts the sweep and
the index is never written.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.
Match ids are synthetic (RM-906).
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

import core.rofl_archive as ra  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

_SRC = _ROOT / "core" / "rofl_archive.py"

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
REPLAY = b"RIOT\x02\x00" + b"\x00" * 64
MID = "NA1_1000000001"
MID2 = "NA1_1000000002"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            route, _, leaf = path.strip("/").partition("/")
            if route.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[route[len("to-wiki-"):]])
            elif route.startswith("hop-"):
                self._redirect("/to-wiki-" + route[len("hop-"):] + "/" + leaf)
            elif route == "to-local":
                self._redirect("/ok/" + leaf)
            elif route == "ok":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(REPLAY)))
                self.end_headers()
                self.wfile.write(REPLAY)
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
    """(base url, request log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q80-rofl-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture
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
def test_a_replay_url_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, tmp_path, target):
    base, hits = origin
    archive = tmp_path / "archive"
    res = ra.download_replays([f"{base}/to-wiki-{target}/{MID}.rofl"], archive)
    assert res.failed == [MID]
    assert res.downloaded == []
    assert net == []
    assert hits == [f"GET /to-wiki-{target}/{MID}.rofl"]
    assert not (archive / f"{MID}.rofl").exists()


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_the_transport_raises_the_refusal(net, origin, target):
    base, _hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        ra._http_get_bytes(f"{base}/to-wiki-{target}/{MID}.rofl")
    assert net == []


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, tmp_path):
    base, hits = origin
    res = ra.download_replays([f"{base}/hop-vanity/{MID}.rofl"], tmp_path / "a")
    assert res.failed == [MID]
    assert net == []
    assert hits == [f"GET /hop-vanity/{MID}.rofl", f"GET /to-wiki-vanity/{MID}.rofl"]


def test_a_wiki_replay_url_is_refused_before_any_socket(net, origin, tmp_path):
    _base, hits = origin
    url = f"http://wiki.leagueoflegends.com/{MID}.rofl"
    res = ra.download_replays([url], tmp_path / "a")
    assert res.failed == [MID]
    assert net == []
    assert hits == []


def test_with_consent_the_redirect_is_followed(net, origin, tmp_path):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    res = ra.download_replays([f"{base}/to-wiki-vanity/{MID}.rofl"], tmp_path / "a")
    assert res.failed == [MID]
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, tmp_path):
    base, hits = origin
    archive = tmp_path / "archive"
    res = ra.download_replays([f"{base}/to-local/{MID}.rofl"], archive)
    assert res.downloaded == [MID]
    assert net == []
    assert hits == [f"GET /to-local/{MID}.rofl", f"GET /ok/{MID}.rofl"]
    assert (archive / f"{MID}.rofl").read_bytes() == REPLAY


def test_a_refused_url_does_not_stop_the_sweep(net, origin, tmp_path):
    """One refused replay is a per-item failure; the next one still lands and
    the index is written."""
    base, _hits = origin
    archive = tmp_path / "archive"
    res = ra.download_replays(
        [f"{base}/to-wiki-fandom/{MID}.rofl", f"{base}/ok/{MID2}.rofl"], archive)
    assert res.failed == [MID]
    assert res.downloaded == [MID2]
    assert net == []
    index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
    assert sorted(index["replays"]) == [MID2]


def test_the_transport_opens_through_the_consent_opener():
    """Source pin: _http_get_bytes opens through open_consented, no urlopen is left."""
    assert ra.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen(" not in src
    assert src.count("open_consented(") == 1
