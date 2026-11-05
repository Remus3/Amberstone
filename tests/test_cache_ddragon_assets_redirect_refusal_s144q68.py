"""RM-1441 (third-party fetcher census, site scripts/cache_ddragon_assets.py) -
the icon cache script refuses a request to, or a redirect INTO, the League wiki
host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape on the three
wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles on
``core/synergy_external_source.py``, ``core/rank_tier_source.py``,
``tft/assets/icon_cache.py`` and ``tools/ddragon_mirror_refresh.py``).

``scripts/cache_ddragon_assets.py`` ``fetch`` (every item and champion icon GET)
opened with ``urllib.request.urlopen``, whose default opener follows a 3xx, so a
Data Dragon url answering 302 to the wiki host opened a wiki socket with no
consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still resolves.

A refusal is not a transient network error: ``fetch`` does not retry it (no
backoff sleep, one origin hit), writes no file, and reports it as one failed
icon (False plus a stderr line), so the run moves on to the next icon exactly
as it does for any other per-icon failure.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import importlib.util
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
from tests._module_view import this_thread_only  # noqa: E402
from tests._sleep_probe import record_sleeps  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location(
        "cache_ddragon_assets_s144q68", _ROOT / "scripts" / "cache_ddragon_assets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CDA = _load()

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
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
    """(base url, request log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-cache-ddragon-origin", daemon=True)
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


def _dest(tmp_path: Path) -> Path:
    return tmp_path / "web" / "data" / "ddragon" / "16.1.1" / "img" / "item" / "1001.png"


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_an_icon_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, tmp_path, capsys, target):
    base, hits = origin
    dest = _dest(tmp_path)
    with record_sleeps() as sleeps:
        assert CDA.fetch(f"{base}/to-wiki/{target}", dest) is False
    assert net == []
    # Refused once, never retried: a refusal is not a transient network error.
    assert hits == [f"GET /to-wiki/{target}"]
    assert sleeps == []
    assert not dest.exists()
    err = capsys.readouterr().err
    assert "refused" in err and f"/to-wiki/{target}" in err


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, tmp_path):
    base, hits = origin
    dest = _dest(tmp_path)
    with record_sleeps() as sleeps:
        assert CDA.fetch(f"{base}/hop/vanity", dest) is False
    assert net == [] and sleeps == []
    assert hits == ["GET /hop/vanity", "GET /to-wiki/vanity"]
    assert not dest.exists()


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin, tmp_path):
    _base, hits = origin
    dest = _dest(tmp_path)
    with record_sleeps() as sleeps:
        assert CDA.fetch(WIKI_TARGETS["vanity"], dest) is False
    assert net == [] and hits == [] and sleeps == []
    assert not dest.exists()


def test_with_consent_the_redirect_is_followed(net, origin, tmp_path):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    with record_sleeps():
        assert CDA.fetch(f"{base}/to-wiki/vanity", _dest(tmp_path), retries=0) is False
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands_the_icon(net, origin, tmp_path):
    base, hits = origin
    dest = _dest(tmp_path)
    assert CDA.fetch(f"{base}/to-local", dest) is True
    assert dest.read_bytes() == PNG
    assert net == []
    assert hits == ["GET /to-local", "GET /ok.png"]


def test_fetch_opens_through_the_consent_opener():
    """Source pin: no bare urlopen is left in the module."""
    assert CDA.open_consented is wiki_consent.open_consented
    assert not hasattr(CDA, "urlopen")
