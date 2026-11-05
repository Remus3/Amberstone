"""RM-1441 (third-party fetcher census, site scripts/audit_ddragon_items.py) -
the item icon coverage audit's ``--download`` leg refuses a request to, or a
redirect INTO, the League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254
closed the same shape on the three wiki tools and ``lib/http/client.py``,
earlier RM-1441 cycles on the synergy and rank-tier sources, the TFT icon
cache, the DDragon mirror refresh, ``scripts/cache_ddragon_assets.py`` and
``scripts/download_aram_icons.py``).

``download_icon`` tries Data Dragon, then CommunityDragon, and opened each with
``urllib.request.urlopen``, whose default opener follows a 3xx: a Data Dragon
or CommunityDragon url answering 302 to the wiki host opened a wiki socket with
no consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.

A refused source writes no file and is skipped like any other per-source
failure, so the CommunityDragon fallback still runs after a refused Data
Dragon hop; a refusal never escapes ``download_icon`` (it is a RuntimeError,
outside the transport-error tuple), so ``main`` finishes and returns 1.
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

_SRC = _ROOT / "scripts" / "audit_ddragon_items.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_ddragon_items_s144q68", _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ADI = _load()

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
VERSION = "16.1.1"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            leaf = path.rsplit("/", 1)[1]
            if leaf.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[leaf[len("to-wiki-"):-len(".png")]])
            elif leaf.startswith("hop-"):
                self._redirect("to-wiki-" + leaf[len("hop-"):])
            elif leaf == "to-local.png":
                self._redirect("ok.png")
            elif leaf == "ok.png":
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
                         name="s144q68-audit-ddragon-items-origin", daemon=True)
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


def _sources(monkeypatch, base: str, dd_leaf: str, cd_leaf: str) -> None:
    """Point both CDN templates at the local origin; ``{id}`` is unused so the
    leaf names pick the origin's behaviour."""
    monkeypatch.setattr(ADI, "CDN_URL", base + "/dd/{version}/" + dd_leaf + "?id={id}")
    monkeypatch.setattr(ADI, "CDN_CD_URL", base + "/cd/" + cd_leaf + "?id={id}")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_ddragon_icon_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, tmp_path, monkeypatch, capsys, target):
    base, hits = origin
    _sources(monkeypatch, base, f"to-wiki-{target}.png", "missing.png")
    dest = tmp_path / "item" / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) is None
    assert net == []
    assert hits == [f"GET /dd/{VERSION}/to-wiki-{target}.png", "GET /cd/missing.png"]
    assert not dest.exists()
    assert "refused" in capsys.readouterr().err


def test_a_refused_ddragon_hop_still_falls_back_to_cdragon(
        net, origin, tmp_path, monkeypatch):
    base, hits = origin
    _sources(monkeypatch, base, "to-wiki-vanity.png", "ok.png")
    dest = tmp_path / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) == "cdragon"
    assert dest.read_bytes() == PNG
    assert net == []
    assert hits == [f"GET /dd/{VERSION}/to-wiki-vanity.png", "GET /cd/ok.png"]


def test_a_cdragon_icon_redirected_into_the_wiki_is_refused(
        net, origin, tmp_path, monkeypatch):
    base, hits = origin
    _sources(monkeypatch, base, "missing.png", "to-wiki-fandom.png")
    dest = tmp_path / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) is None
    assert net == []
    assert hits == [f"GET /dd/{VERSION}/missing.png", "GET /cd/to-wiki-fandom.png"]
    assert not dest.exists()


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, tmp_path, monkeypatch):
    base, hits = origin
    _sources(monkeypatch, base, "hop-vanity.png", "missing.png")
    dest = tmp_path / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) is None
    assert net == []
    assert hits == [f"GET /dd/{VERSION}/hop-vanity.png",
                    f"GET /dd/{VERSION}/to-wiki-vanity.png", "GET /cd/missing.png"]
    assert not dest.exists()


def test_a_direct_wiki_cdn_url_is_refused_before_any_socket(
        net, origin, tmp_path, monkeypatch):
    base, hits = origin
    monkeypatch.setattr(ADI, "CDN_URL", WIKI_TARGETS["vanity"] + "&v={version}&id={id}")
    monkeypatch.setattr(ADI, "CDN_CD_URL", base + "/cd/missing.png?id={id}")
    dest = tmp_path / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) is None
    assert net == []
    assert hits == ["GET /cd/missing.png"]


def test_with_consent_the_redirect_is_followed(net, origin, tmp_path, monkeypatch):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    _sources(monkeypatch, base, "to-wiki-vanity.png", "missing.png")
    assert ADI.download_icon(VERSION, "3089", tmp_path / "3089.png") is None
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, tmp_path, monkeypatch):
    base, hits = origin
    _sources(monkeypatch, base, "to-local.png", "missing.png")
    dest = tmp_path / "3089.png"
    assert ADI.download_icon(VERSION, "3089", dest) == "ddragon"
    assert dest.read_bytes() == PNG
    assert net == []
    assert hits == [f"GET /dd/{VERSION}/to-local.png", f"GET /dd/{VERSION}/ok.png"]


def test_main_download_with_a_refused_icon_finishes_and_returns_1(
        net, origin, tmp_path, monkeypatch, capsys):
    base, _hits = origin
    item_dir = tmp_path / "img" / "item"
    item_dir.mkdir(parents=True)
    monkeypatch.setattr(ADI, "load_index", lambda: (VERSION, {"3089": "Rabadon"}, item_dir))
    monkeypatch.setattr(ADI, "collect_from_db", lambda: {"3089"})
    _sources(monkeypatch, base, "to-wiki-wikigg.png", "to-wiki-vanity.png")
    assert ADI.main(download=True) == 1
    out = capsys.readouterr()
    assert "0 from DDragon + 0 from CommunityDragon = 0/1" in out.out
    refused = [ln for ln in out.err.splitlines() if ln.startswith("refused ")]
    assert len(refused) == 2
    assert net == []
    assert list(item_dir.iterdir()) == []


def test_the_script_opens_through_the_consent_opener():
    """Source pin: the icon GET opens through open_consented, no urlopen is left."""
    assert ADI.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 1
