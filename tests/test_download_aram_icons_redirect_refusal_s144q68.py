"""RM-1441 (third-party fetcher census, site scripts/download_aram_icons.py) -
the ARAM item icon download refuses a request to, or a redirect INTO, the
League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape
on the three wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles on
``core/synergy_external_source.py``, ``core/rank_tier_source.py``,
``tft/assets/icon_cache.py``, ``tools/ddragon_mirror_refresh.py`` and
``scripts/cache_ddragon_assets.py``).

``scripts/download_aram_icons.py`` had two network seams, ``fetch_json`` (the
version list and the item data) and the icon GET in ``download_icons``, and
both opened with ``urllib.request.urlopen``, whose default opener follows a
3xx: a Data Dragon url answering 302 to the wiki host opened a wiki socket with
no consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still resolves.

A refused icon writes no file and counts as one failed icon, so the run moves
on to the next icon exactly as it does for any other per-icon failure; a
refused version list makes ``main`` return 1 like any other fetch failure.
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

_SRC = _ROOT / "scripts" / "download_aram_icons.py"


def _load():
    spec = importlib.util.spec_from_file_location("download_aram_icons_s144q68", _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


DAI = _load()

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PNG = b"\x89PNG\r\n\x1a\n" + b"icon-bytes"
VERSION = "16.1.1"


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            leaf = path.rsplit("/", 1)[1]
            if path == "/wiki-versions/api/versions.json":
                self._redirect(WIKI_TARGETS["vanity"])
            elif path.startswith("/to-wiki/"):
                self._redirect(WIKI_TARGETS[leaf])
            elif leaf.startswith("to-wiki-"):
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


@pytest.fixture
def origin():
    """(base url, request log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-download-aram-icons-origin", daemon=True)
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
    monkeypatch.setattr(DAI.time, "sleep", lambda _s: None)
    return calls


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


def _icons(monkeypatch, base: str, img: str, tmp_path: Path):
    monkeypatch.setattr(DAI, "DDRAGON", base)
    out = tmp_path / "icons"
    out.mkdir()
    return {"1": {"name": "Wiki Item", "img": img}}, out


def _icon_path(img: str) -> str:
    return f"GET /cdn/{VERSION}/img/item/{img}"


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_an_icon_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, tmp_path, monkeypatch, capsys, target):
    base, hits = origin
    img = f"to-wiki-{target}.png"
    items, out = _icons(monkeypatch, base, img, tmp_path)
    assert DAI.download_icons(items, VERSION, out) == (0, 0, 1)
    assert net == []
    assert hits == [_icon_path(img)]
    assert list(out.iterdir()) == []
    text = capsys.readouterr().out
    assert "FAIL [1] Wiki Item:" in text and "refused" in text


def test_a_two_hop_icon_redirect_into_the_wiki_is_refused(
        net, origin, tmp_path, monkeypatch):
    base, hits = origin
    items, out = _icons(monkeypatch, base, "hop-vanity.png", tmp_path)
    assert DAI.download_icons(items, VERSION, out) == (0, 0, 1)
    assert net == []
    assert hits == [_icon_path("hop-vanity.png"), _icon_path("to-wiki-vanity.png")]
    assert list(out.iterdir()) == []


def test_with_consent_the_icon_redirect_is_followed(net, origin, tmp_path, monkeypatch):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    items, out = _icons(monkeypatch, base, "to-wiki-vanity.png", tmp_path)
    assert DAI.download_icons(items, VERSION, out) == (0, 0, 1)
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_an_icon_redirect_to_a_non_wiki_target_still_lands(
        net, origin, tmp_path, monkeypatch):
    base, hits = origin
    items, out = _icons(monkeypatch, base, "to-local.png", tmp_path)
    assert DAI.download_icons(items, VERSION, out) == (1, 0, 0)
    assert (out / "wiki-item.png").read_bytes() == PNG
    assert net == []
    assert hits == [_icon_path("to-local.png"), _icon_path("ok.png")]


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_fetch_json_redirected_into_the_wiki_is_refused(net, origin, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        DAI.fetch_json(f"{base}/to-wiki/{target}", timeout=5)
    assert net == []
    assert hits == [f"GET /to-wiki/{target}"]


def test_fetch_json_refuses_a_direct_wiki_url_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        DAI.fetch_json(WIKI_TARGETS["vanity"], timeout=5)
    assert net == [] and hits == []


def test_main_returns_1_when_the_version_list_redirects_into_the_wiki(
        net, origin, tmp_path, monkeypatch, capsys):
    base, hits = origin
    monkeypatch.setattr(DAI, "DDRAGON", f"{base}/wiki-versions")
    monkeypatch.setattr(DAI, "OUT_DIR", tmp_path / "icons")
    assert DAI.main() == 1
    assert "ERROR fetching versions:" in capsys.readouterr().out
    assert net == []
    assert hits == ["GET /wiki-versions/api/versions.json"]


def test_the_script_opens_through_the_consent_opener():
    """Source pin: both seams open through open_consented, no urlopen is left."""
    assert DAI.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 2
