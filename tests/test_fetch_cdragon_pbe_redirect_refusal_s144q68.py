"""RM-1441 (third-party fetcher census, site scripts/fetch_cdragon_pbe.py) -
the CommunityDragon PBE fetcher refuses a request to, or a redirect INTO, the
League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape
on the three wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles
on the synergy and rank-tier sources, the TFT icon cache, the DDragon mirror
refresh and the three scripts/ icon downloaders).

``fetch`` opened with ``urllib.request.urlopen``, whose default opener follows
a 3xx: a CommunityDragon url answering 302 to the wiki host opened a wiki
socket with no consent record.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.

A refusal is caught by each section's existing ``except Exception``: the
section prints its FAILED line, writes nothing, and ``main`` still runs the
second section and exits 0. The fetch keeps the verified TLS context
(RM-1175): it is handed to ``open_consented`` as ``context=``.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import importlib.util
import json
import socket
import ssl
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import tls_policy  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

_SRC = _ROOT / "scripts" / "fetch_cdragon_pbe.py"


def _load():
    spec = importlib.util.spec_from_file_location("fetch_cdragon_pbe_s144q68", _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


PBE = _load()

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
PLANNER = [{"character_id": "TFT17_Alpha", "display_name": "Alpha",
            "team_planner_code": 11}]
BODY = json.dumps(PLANNER).encode("utf-8")


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            leaf = path.rsplit("/", 1)[1]
            if leaf.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[leaf[len("to-wiki-"):-len(".json")]])
            elif leaf.startswith("hop-"):
                self._redirect("to-wiki-" + leaf[len("hop-"):])
            elif leaf == "to-local.json":
                self._redirect("ok.json")
            elif leaf == "ok.json":
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
                         name="s144q68-fetch-cdragon-pbe-origin", daemon=True)
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
def targets(monkeypatch, tmp_path):
    """Point every write target into tmp_path; return the output dir."""
    out = tmp_path / "meta"
    out.mkdir()
    monkeypatch.setattr(PBE, "CODES_FILE", out / "codes.json")
    monkeypatch.setattr(PBE, "TEAMPLANNER_RAW", out / "planner.json")
    monkeypatch.setattr(PBE, "TFT_RAW", out / "tft.json")
    return out


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_cdragon_url_redirected_into_the_wiki_is_refused_before_any_wiki_socket(
        net, origin, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        PBE.fetch(f"{base}/pbe/to-wiki-{target}.json")
    assert net == []
    assert hits == [f"GET /pbe/to-wiki-{target}.json"]


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        PBE.fetch(f"{base}/pbe/hop-vanity.json")
    assert net == []
    assert hits == ["GET /pbe/hop-vanity.json", "GET /pbe/to-wiki-vanity.json"]


def test_a_direct_wiki_url_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        PBE.fetch(WIKI_TARGETS["vanity"])
    assert net == []
    assert hits == []


def test_with_consent_the_redirect_is_followed(net, origin):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    with pytest.raises(OSError):
        PBE.fetch(f"{base}/pbe/to-wiki-vanity.json")
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin):
    base, hits = origin
    assert PBE.fetch(f"{base}/pbe/to-local.json") == BODY.decode("utf-8")
    assert net == []
    assert hits == ["GET /pbe/to-local.json", "GET /pbe/ok.json"]


def test_main_with_both_sources_refused_writes_nothing_and_exits_zero(
        net, origin, targets, monkeypatch, capsys):
    base, hits = origin
    monkeypatch.setattr(PBE, "TEAMPLANNER_URL", f"{base}/pbe/to-wiki-wikigg.json")
    monkeypatch.setattr(PBE, "TFT_EN_US_URL", f"{base}/pbe/to-wiki-fandom.json")
    assert PBE.main() == 0
    out = capsys.readouterr().out
    assert "team planner FAILED" in out
    assert "TFT en_us FAILED" in out
    assert net == []
    assert hits == ["GET /pbe/to-wiki-wikigg.json", "GET /pbe/to-wiki-fandom.json"]
    assert list(targets.iterdir()) == []


def test_main_with_a_refused_planner_still_runs_the_tft_section(
        net, origin, targets, monkeypatch, capsys):
    base, hits = origin
    monkeypatch.setattr(PBE, "TEAMPLANNER_URL", f"{base}/pbe/to-wiki-vanity.json")
    monkeypatch.setattr(PBE, "TFT_EN_US_URL", f"{base}/pbe/ok.json")
    assert PBE.main() == 0
    out = capsys.readouterr().out
    assert "team planner FAILED" in out
    assert net == []
    assert hits == ["GET /pbe/to-wiki-vanity.json", "GET /pbe/ok.json"]
    assert sorted(p.name for p in targets.iterdir()) == ["tft.json"]
    assert (targets / "tft.json").read_bytes() == BODY


def test_the_fetch_hands_the_verified_context_to_the_consent_opener(monkeypatch):
    """RM-1175 survives the swap: open_consented gets the verified context."""
    seen: list = []

    class _Stop(Exception):
        pass

    def fake(req, timeout, context=None):
        seen.append((getattr(req, "full_url", req), timeout, context))
        raise _Stop("test refuses network access")

    monkeypatch.setattr(PBE, "open_consented", fake)
    with pytest.raises(_Stop):
        PBE.fetch(PBE.TFT_EN_US_URL)
    assert len(seen) == 1
    url, timeout, ctx = seen[0]
    assert url == PBE.TFT_EN_US_URL and timeout == 30
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert ctx.minimum_version == tls_policy.TLS_MIN_VERSION


def test_the_script_opens_through_the_consent_opener():
    """Source pin: the fetch opens through open_consented, no urlopen is left."""
    assert PBE.open_consented is wiki_consent.open_consented
    src = _SRC.read_text(encoding="utf-8")
    assert "urlopen" not in src
    assert src.count("open_consented(") == 1
