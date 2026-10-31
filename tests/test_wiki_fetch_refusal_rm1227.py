"""RM-1227 - every League wiki request path refuses before any socket opens
unless a consent record exists (ruling 51, ``RM962-S146-R51``).

The five paths named by the ruling: the ``wiki`` Source fetched by
``lib/game_data/fetch.py``, ``tools/daemon_slayer_wiki_ability_extract.py``,
``tools/daemon_slayer_wiki_stats_extract.py``, ``tools/ds_wiki_staleness_check.py``
(and so ``tools/upstream_drift_check.py --staleness-recent``) and
``tools/ds_windup_offset_compare.py``.

The network layer is patched for every test (``urllib.request.urlopen`` and the
socket connect / resolve calls record and raise), and the consent record path
points at an empty tmp dir, so a refusal is proven by ZERO recorded requests,
not by an exception alone. With a valid record the same calls DO reach the
network layer, so the refusal is conditional, not a blanket off switch.
Parsers fed operator-supplied text (the replay fixture, a saved module body)
keep working without consent.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

from lib import wiki_consent
from lib.game_data import build as gd_build
from lib.game_data import fetch as gd_fetch
from lib.game_data.replay import ReplayClient
from lib.http import client as http_client

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as ability  # noqa: E402
import daemon_slayer_wiki_stats_extract as stats  # noqa: E402
import ds_wiki_staleness_check as staleness  # noqa: E402
import ds_windup_offset_compare as windup  # noqa: E402
import upstream_drift_check as drift  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "game_data_replay"
WIKI_URL = "https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw"
CDRAGON_URL = "https://raw.communitydragon.org/latest/game/data/characters/ahri/ahri.bin.json"
TODAY = _dt.date.today()


class _NetworkTouched(OSError):
    """Raised by the patched network layer after it records the call."""


@pytest.fixture()
def net(monkeypatch, tmp_path):
    """Record-and-raise network layer; consent record path in an empty dir."""
    calls: list[str] = []

    def _urlopen(req, *a, **k):
        url = getattr(req, "full_url", req)
        calls.append(f"urlopen {url}")
        raise _NetworkTouched(f"network touched: {url}")

    def _sock(name):
        def _f(*a, **k):
            calls.append(f"socket.{name} {a[1:2] or a[:1]}")
            raise _NetworkTouched(f"socket.{name}")
        return _f

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(socket, "create_connection", _sock("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _sock("getaddrinfo"))
    monkeypatch.setattr(socket.socket, "connect", _sock("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _sock("connect_ex"))
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    return calls


def _grant(**over) -> dict:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": TODAY.isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    rec.update(over)
    for k in [k for k, v in rec.items() if v is None]:
        del rec[k]
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")
    return rec


# ------------------------------------------------------------ consent record


def test_no_record_is_no_consent(net):
    assert wiki_consent.consent_problem() is not None
    with pytest.raises(wiki_consent.WikiFetchRefused, match="RM962-S146-R51"):
        wiki_consent.require_consent()


def test_valid_record_is_consent(net):
    _grant()
    assert wiki_consent.consent_problem() is None
    wiki_consent.require_consent()
    _grant(expires=TODAY.isoformat())
    assert wiki_consent.consent_problem() is None


@pytest.mark.parametrize("body", [
    "", "not json", "[]", "null",
    json.dumps({"granted": TODAY.isoformat(), "scope": "x"}),
    json.dumps({"ruling": "RM962-OTHER", "granted": TODAY.isoformat(), "scope": "x"}),
    json.dumps({"ruling": "RM962-S146-R51", "scope": "x"}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": "2026-13-01", "scope": "x"}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": 20261031, "scope": "x"}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": TODAY.isoformat()}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": TODAY.isoformat(), "scope": "  "}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": TODAY.isoformat(), "scope": "x",
                "expires": "soon"}),
    json.dumps({"ruling": "RM962-S146-R51",
                "granted": (TODAY + _dt.timedelta(days=1)).isoformat(), "scope": "x"}),
    json.dumps({"ruling": "RM962-S146-R51", "granted": "2026-01-01", "scope": "x",
                "expires": (TODAY - _dt.timedelta(days=1)).isoformat()}),
])
def test_malformed_or_stale_record_refuses(net, body):
    wiki_consent.CONSENT_PATH.write_text(body, encoding="utf-8", newline="\n")
    assert wiki_consent.consent_problem() is not None
    with pytest.raises(wiki_consent.WikiFetchRefused):
        wiki_consent.refuse_unless_consented(WIKI_URL)


@pytest.mark.parametrize("url,is_wiki", [
    (WIKI_URL, True),
    ("https://WIKI.LeagueOfLegends.com./en-us/api.php?action=query", True),
    ("http://wiki.leagueoflegends.com:8080/x", True),
    ("https://leagueoflegends.wiki.gg/api.php", True),
    ("https://leagueoflegends.fandom.com/wiki/Ahri", True),
    ("https://other.wiki.gg/", True),
    ("https://ddragon.leagueoflegends.com/api/versions.json", False),
    (CDRAGON_URL, False),
    ("https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/items.json", False),
    ("https://evilwiki.gg.example.com/", False),
    ("not a url", False),
])
def test_is_wiki_url(url, is_wiki):
    assert wiki_consent.is_wiki_url(url) is is_wiki


def test_ruling_51_stands_no_consent_record_on_disk():
    """Ruling 51 stands: no consent has been granted, so no record exists in
    this checkout. When consent IS granted and recorded, this test is meant
    to fail; update it in the same change that adds the record."""
    assert not (wiki_consent.PROJECT_ROOT / "ops" / "wiki_fetch_consent.json").exists()


# ------------------------------------------------------- lib/game_data fetch


class _NetLikeClient:
    """A network client in shape (no ``offline`` flag) that serves the
    recorded non-wiki bodies and records every url it is asked for."""

    def __init__(self, root: Path) -> None:
        self._replay = ReplayClient(root)
        self.urls: list[str] = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self._replay.get(url)


@pytest.fixture()
def replay(tmp_path):
    d = tmp_path / "replay"
    shutil.copytree(FIX, d)
    return d


def test_pipeline_refuses_the_wiki_source_without_consent(net, replay, tmp_path):
    client = _NetLikeClient(replay)
    fetched = gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    assert not [u for u in client.urls if wiki_consent.is_wiki_url(u)], client.urls
    assert "wiki" not in fetched.parsed
    assert "RM962-S146-R51" in fetched.excluded["wiki"]
    assert set(fetched.parsed) == {"ddragon", "meraki"}
    assert net == []
    # The build still runs from the remaining sources and records why.
    b = gd_build.reconcile(fetched)
    assert "wiki" not in b.sources
    assert "wiki" in b.report["excluded_sources"]


def test_pipeline_live_default_client_never_requests_the_wiki(net, replay, tmp_path, monkeypatch):
    seen: list[str] = []
    rc = ReplayClient(replay)

    def _get(self, url, **kw):
        seen.append(url)
        return rc.get(url)

    monkeypatch.setattr(http_client.HttpClient, "get", _get)
    fetched = gd_fetch.fetch(None, cache_dir=tmp_path / "cache")
    assert seen and not [u for u in seen if wiki_consent.is_wiki_url(u)], seen
    assert "wiki" in fetched.excluded
    assert net == []


def test_pipeline_requests_the_wiki_with_consent(net, replay, tmp_path):
    _grant()
    client = _NetLikeClient(replay)
    fetched = gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    assert WIKI_URL in client.urls
    assert "wiki" in fetched.parsed and "wiki" not in fetched.excluded


def test_pipeline_offline_replay_still_parses_the_wiki_body(net, replay, tmp_path):
    """Operator-supplied text keeps working: the replay client opens no socket."""
    client = ReplayClient(replay)
    assert getattr(client, "offline", False) is True
    fetched = gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    assert "wiki" in fetched.parsed and fetched.parsed["wiki"]["champions"]
    assert net == []


def test_pipeline_uses_an_already_cached_wiki_body_without_a_request(net, replay, tmp_path):
    cache = tmp_path / "cache"
    gd_fetch.fetch(None, client=ReplayClient(replay), cache_dir=cache)
    client = _NetLikeClient(replay)
    fetched = gd_fetch.fetch(None, client=client, cache_dir=cache)
    assert not [u for u in client.urls if wiki_consent.is_wiki_url(u)]
    assert "wiki" in fetched.parsed


# ---------------------------------------------------------------- the tools


@pytest.mark.parametrize("call", [
    lambda: ability._fetch(ability.WIKI_API + "?action=query"),
    lambda: ability._fetch_raw_module(),
    lambda: ability._fetch_batch(["Template:Data Ahri/Orb of Deception"]),
    lambda: stats._fetch(stats.WIKI_RAW_MODULE),
    lambda: stats._fetch_raw_module(),
    lambda: stats._expand("Ahri", "attack_cast_time"),
    lambda: staleness.fetch_recent_titles(days=1),
    lambda: staleness.fetch_pages(["Template:Data Ahri/Orb of Deception"]),
    lambda: windup._fetch_module(),
], ids=["ability._fetch", "ability._fetch_raw_module", "ability._fetch_batch",
        "stats._fetch", "stats._fetch_raw_module", "stats._expand",
        "staleness.fetch_recent_titles", "staleness.fetch_pages", "windup._fetch_module"])
def test_tool_wiki_requests_refuse_before_any_socket(net, call):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        call()
    assert net == []


@pytest.mark.parametrize("call", [
    lambda: ability._fetch(ability.WIKI_API + "?action=query"),
    lambda: stats._fetch(stats.WIKI_RAW_MODULE),
    lambda: windup._fetch_module(),
], ids=["ability", "stats", "windup"])
def test_tool_wiki_requests_reach_the_network_with_consent(net, call):
    _grant()
    with pytest.raises(_NetworkTouched):
        call()
    assert len(net) == 1 and "wiki.leagueoflegends.com" in net[0]


def test_stats_fetch_still_reaches_communitydragon_without_consent(net):
    with pytest.raises(_NetworkTouched):
        stats._fetch(CDRAGON_URL)
    assert net == [f"urlopen {CDRAGON_URL}"]


@pytest.mark.parametrize("source", ["wiki", "both"])
def test_stats_extract_refusal_is_not_swallowed_into_a_degraded_payload(net, monkeypatch, source):
    """The raw-table catch degrades to the per-champ getter and the getter's
    catch is fail-soft per champ; a refusal must pass through both, so the
    extract returns nothing for main() to write."""
    monkeypatch.setattr(stats, "_WIKI_TABLE_CACHE", None)
    with pytest.raises(wiki_consent.WikiFetchRefused):
        stats.extract(stats._resolve_patch(None), 0.0, 1, False, source=source)
    assert net == []


def test_stats_extract_getter_refusal_is_not_swallowed(net, monkeypatch):
    """Raw table supplied (no fetch) but missing the cast time, so the live
    per-champ getter runs and is refused; the per-champ catch re-raises."""
    monkeypatch.setattr(stats, "_load_wiki_table", lambda: {})
    with pytest.raises(wiki_consent.WikiFetchRefused):
        stats.extract(stats._resolve_patch(None), 0.0, 1, False, source="wiki")
    assert net == []


def test_stats_extract_table_refusal_is_not_swallowed_by_a_stubbed_getter(net, monkeypatch):
    """Live raw-table fetch refused, per-champ getter supplied: the raw-table
    catch must re-raise, not degrade to the getter and return a payload."""
    monkeypatch.setattr(stats, "_WIKI_TABLE_CACHE", None)
    monkeypatch.setattr(stats, "_expand", lambda c, f: "0.25")
    with pytest.raises(wiki_consent.WikiFetchRefused):
        stats.extract(stats._resolve_patch(None), 0.0, 1, False, source="wiki")
    assert net == []


def test_stats_retry_helper_never_retries_a_refusal(net, monkeypatch):
    calls: list[str] = []
    real = stats._fetch

    def _spy(url, *a, **k):
        calls.append(url)
        return real(url, *a, **k)

    monkeypatch.setattr(stats, "_fetch", _spy)
    with pytest.raises(wiki_consent.WikiFetchRefused):
        stats._fetch_with_retry(stats.WIKI_RAW_MODULE, retries=3, backoff_s=0.0)
    assert calls == [stats.WIKI_RAW_MODULE], "a refusal is not transient: one attempt only"
    assert net == []


def test_refusal_is_not_a_transport_error():
    """Callers' ``except OSError`` transport handlers must not read a refusal
    as a network blip."""
    assert issubclass(wiki_consent.WikiFetchRefused, RuntimeError)
    assert not issubclass(wiki_consent.WikiFetchRefused, OSError)


def test_stats_extract_on_supplied_text_needs_no_consent(net, monkeypatch):
    """Every wiki fetcher stubbed (operator text): no consent needed."""
    monkeypatch.setattr(stats, "_load_wiki_table", lambda: {})
    monkeypatch.setattr(stats, "_expand", lambda c, f: "0.25")
    out = stats.extract(stats._resolve_patch(None), 0.0, 1, False, source="wiki")
    assert isinstance(out, dict)
    assert net == []


def test_ability_extract_live_module_fetch_refuses(net):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        ability.extract(ability._resolve_patch(None), 0.0, 1, False,
                        _batch_fn=lambda b: {"query": {"pages": {}}})
    assert net == []


def test_ability_extract_batch_refusal_is_not_swallowed(net):
    """Supplied module text with the live batch fetcher: the per-batch
    fail-soft catch must re-raise the refusal, not record an errored batch."""
    text = (FIX / "wiki_championdata.lua.txt").read_text(encoding="utf-8")
    with pytest.raises(wiki_consent.WikiFetchRefused):
        ability.extract(ability._resolve_patch(None), 0.0, 1, False, _module_text=text)
    assert net == []


def test_ability_extract_on_supplied_text_needs_no_consent(net):
    patch = ability._resolve_patch(None)
    out = ability.extract(patch, 0.0, 1, False,
                          _module_text="return {\n}\n", _batch_fn=lambda b: {"query": {"pages": {}}})
    assert isinstance(out, dict)
    assert net == []


def test_windup_compare_refuses(net):
    with pytest.raises(wiki_consent.WikiFetchRefused):
        windup.compare(windup._resolve_patch(None))
    assert net == []


def test_windup_parser_on_supplied_text_needs_no_consent(net):
    text = (FIX / "wiki_championdata.lua.txt").read_text(encoding="utf-8")
    assert windup.parse_module(text)
    assert net == []


def test_upstream_drift_staleness_recent_is_refused_fail_soft(net):
    ok, detail = drift.run_staleness_recent(days=1)
    assert ok is False
    assert "WikiFetchRefused" in detail and "RM962-S146-R51" in detail
    assert net == []
