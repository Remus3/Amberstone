"""RM-1507 / RM-1441 (third-party fetcher census, the Daemon Slayer extractors) -
the DS extractor fetch helpers refuse a request to, or a redirect INTO, the
League wiki host (ruling 51, ``RM962-S146-R51``; RM-1254 closed the same shape
on the three wiki tools and ``lib/http/client.py``, earlier RM-1441 cycles on
the synergy and rank-tier sources, the TFT icon cache, the DDragon mirror
refresh and the icon scripts).

Five call sites opened Meraki, Data Dragon, lolmath and CommunityDragon urls
with ``urllib.request.urlopen``, whose default opener follows a 3xx: a url
answering 302 to the wiki host opened a wiki socket with no consent record.

- ``tools/daemon_slayer_extract.py``: ``_fetch_text`` and
  ``_fetch_meraki_champion``
- ``tools/daemon_slayer_abilities_extract.py``: ``_fetch_text``
- ``tools/daemon_slayer_cdragon_spell_extract.py``: ``_fetch`` (and so
  ``_fetch_with_retry``)
- ``tools/daemon_slayer_cdragon_ratio_extract.py``: the standalone
  ``_fetch_with_retry`` fallback used when the sibling spell extractor cannot
  be imported

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects. With a consent
record the same redirect IS followed (one recorded wiki connect), so the
refusal is conditional, and a redirect to a non-wiki target still lands.

A refusal is a ``WikiFetchRefused`` (a RuntimeError): the two retrying helpers
must not burn their retry budget on it (one origin hit, not three), and the
Meraki per-champion fetch stays fail-soft (returns None) like any transport
error.
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

_TOOLS = _ROOT / "tools"
_SPELL = "daemon_slayer_cdragon_spell_extract"

WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
OK_BODY = '{"ok": 1}'


def _load(stem: str, alias: str, *, block_spell: bool = False):
    """Import ``tools/<stem>.py`` under a private name. ``block_spell`` makes
    ``import daemon_slayer_cdragon_spell_extract`` raise ImportError for the
    duration of the load (the ratio extractor's standalone fallback)."""
    spec = importlib.util.spec_from_file_location(alias, _TOOLS / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    saved = sys.modules.get(_SPELL, _MISSING)
    saved_alias = sys.modules.get(alias, _MISSING)
    sys.modules[alias] = mod
    if block_spell:
        sys.modules[_SPELL] = None  # type: ignore[assignment]
    try:
        spec.loader.exec_module(mod)
    finally:
        if block_spell:
            if saved is _MISSING:
                sys.modules.pop(_SPELL, None)
            else:
                sys.modules[_SPELL] = saved
        if saved_alias is _MISSING:
            sys.modules.pop(alias, None)
        else:
            sys.modules[alias] = saved_alias
    return mod


_MISSING = object()
DSE = _load("daemon_slayer_extract", "dse_s144d82")
DAE = _load("daemon_slayer_abilities_extract", "dae_s144d82")
SPELL = _load(_SPELL, "spell_s144d82")
RATIO = _load("daemon_slayer_cdragon_ratio_extract", "ratio_s144d82", block_spell=True)


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(f"GET {path}")
            leaf = path.rsplit("/", 1)[1]
            stem, _, ext = leaf.rpartition(".")
            if stem.startswith("to-wiki-"):
                self._redirect(WIKI_TARGETS[stem[len("to-wiki-"):]])
            elif stem.startswith("hop-"):
                self._redirect(f"to-wiki-{stem[len('hop-'):]}.{ext}")
            elif stem == "to-local":
                self._redirect(f"ok.{ext}")
            elif stem == "ok":
                body = OK_BODY.encode("ascii")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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
                         name="s144d82-ds-extractors-origin", daemon=True)
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


def _no_sleep(monkeypatch, *mods) -> None:
    for mod in mods:
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)


# Every single-shot text fetcher, as (id, callable(url) -> text). The two
# retrying helpers run with a zero backoff so a refused hop costs no wall clock.
FETCHERS = {
    "extract_fetch_text": lambda url: DSE._fetch_text(url, timeout=10),
    "abilities_fetch_text": lambda url: DAE._fetch_text(url, timeout=10),
    "spell_fetch": lambda url: SPELL._fetch(url, timeout=10),
    "spell_fetch_with_retry": lambda url: SPELL._fetch_with_retry(url, retries=1, backoff_s=0),
    "ratio_fallback_fetch_with_retry": lambda url: RATIO._fetch_with_retry(
        url, retries=1, backoff_s=0),
}
FETCHER_IDS = sorted(FETCHERS)


@pytest.mark.parametrize("fid", FETCHER_IDS)
@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_a_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, fid, target):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        FETCHERS[fid](f"{base}/x/to-wiki-{target}.json")
    assert net == []
    assert hits == [f"GET /x/to-wiki-{target}.json"]


@pytest.mark.parametrize("fid", FETCHER_IDS)
def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin, fid):
    base, hits = origin
    with pytest.raises(wiki_consent.WikiFetchRefused):
        FETCHERS[fid](f"{base}/x/hop-vanity.json")
    assert net == []
    assert hits == ["GET /x/hop-vanity.json", "GET /x/to-wiki-vanity.json"]


@pytest.mark.parametrize("fid", FETCHER_IDS)
def test_a_direct_wiki_url_is_refused_before_any_socket(net, fid):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        FETCHERS[fid](WIKI_TARGETS["vanity"])
    assert net == []


@pytest.mark.parametrize("fid", FETCHER_IDS)
def test_with_consent_the_redirect_is_followed(net, origin, fid):
    """Positive control: the refusal is the consent gate, not a dead redirect."""
    base, _hits = origin
    _grant()
    with pytest.raises(OSError):  # URLError wrapping the patched connect's refusal
        FETCHERS[fid](f"{base}/x/to-wiki-vanity.json")
    assert len(net) == 1 and net[0].startswith("connect wiki.leagueoflegends.com:")


@pytest.mark.parametrize("fid", FETCHER_IDS)
def test_a_redirect_to_a_non_wiki_target_still_lands(net, origin, fid):
    base, hits = origin
    assert FETCHERS[fid](f"{base}/x/to-local.json") == OK_BODY
    assert net == []
    assert hits == ["GET /x/to-local.json", "GET /x/ok.json"]


def test_the_json_helpers_inherit_the_refusal(net, origin):
    base, _hits = origin
    assert DSE._fetch_json(f"{base}/x/ok.json") == {"ok": 1}
    assert DAE._fetch_json(f"{base}/x/ok.json") == {"ok": 1}
    with pytest.raises(wiki_consent.WikiFetchRefused):
        DSE._fetch_json(f"{base}/x/to-wiki-wikigg.json")
    with pytest.raises(wiki_consent.WikiFetchRefused):
        DAE._fetch_json(f"{base}/x/to-wiki-wikigg.json")
    assert net == []


# --- the retrying helpers do not retry a refusal ------------------------------

@pytest.mark.parametrize("which", ["spell", "ratio"])
def test_a_refusal_is_not_retried(net, origin, monkeypatch, which):
    base, hits = origin
    _no_sleep(monkeypatch, SPELL, RATIO)
    fn = SPELL._fetch_with_retry if which == "spell" else RATIO._fetch_with_retry
    with pytest.raises(wiki_consent.WikiFetchRefused):
        fn(f"{base}/x/to-wiki-fandom.json", retries=3, backoff_s=1.0)
    assert hits == ["GET /x/to-wiki-fandom.json"]
    assert net == []


@pytest.mark.parametrize("which", ["spell", "ratio"])
def test_a_transient_404_is_still_retried(net, origin, monkeypatch, which):
    """The refusal carve-out must not turn off the CDN retry: a 404 runs the budget."""
    base, hits = origin
    _no_sleep(monkeypatch, SPELL, RATIO)
    fn = SPELL._fetch_with_retry if which == "spell" else RATIO._fetch_with_retry
    with pytest.raises(Exception) as ei:
        fn(f"{base}/x/missing.json", retries=3, backoff_s=1.0)
    assert not isinstance(ei.value, wiki_consent.WikiFetchRefused)
    assert hits == ["GET /x/missing.json"] * 3


# --- the Meraki per-champion fetch stays fail-soft -----------------------------

@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_meraki_champion_redirected_into_the_wiki_is_none_not_a_raise(
        net, origin, monkeypatch, target):
    base, hits = origin
    monkeypatch.setattr(DSE, "MERAKI_BASE", f"{base}/m")
    assert DSE._fetch_meraki_champion(f"to-wiki-{target}") is None
    assert net == []
    assert hits == [f"GET /m/to-wiki-{target}.json"]


def test_meraki_champion_non_wiki_redirect_still_lands(net, origin, monkeypatch):
    base, hits = origin
    monkeypatch.setattr(DSE, "MERAKI_BASE", f"{base}/m")
    assert DSE._fetch_meraki_champion("to-local") == {"ok": 1}
    assert hits == ["GET /m/to-local.json", "GET /m/ok.json"]


# --- the fallback really is the standalone one ---------------------------------

def test_the_ratio_module_under_test_is_the_standalone_fallback():
    assert RATIO._spell is None
    assert RATIO._fetch_with_retry is not SPELL._fetch_with_retry


def test_the_four_extractors_open_through_the_consent_opener():
    """Source pin: every GET opens through open_consented, no urlopen is left."""
    for stem in ("daemon_slayer_extract", "daemon_slayer_abilities_extract",
                 _SPELL, "daemon_slayer_cdragon_ratio_extract"):
        src = (_TOOLS / f"{stem}.py").read_text(encoding="utf-8")
        assert "urlopen" not in src, stem
        assert "open_consented(" in src, stem
    assert DSE.open_consented is wiki_consent.open_consented
    assert DAE.open_consented is wiki_consent.open_consented
    assert SPELL.open_consented is wiki_consent.open_consented
