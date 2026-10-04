"""P1-4 multi-source game-data reconciliation with per-field provenance.

All network traffic in this file goes through the OFFLINE replay client
(lib/game_data/replay.py) over bodies recorded from the real upstreams on
2026-10-04 (tests/fixtures/game_data_replay/_index.json). Nothing here touches
the network.

Recorded facts the assertions lean on (re-checkable by eye in the fixtures):
- DDragon 16.19.1 publishes ``attackdamageperlevel: 0`` for every fixture
  champion (Ahri, Akshan, Draven, Jhin, Kled), and ``attackspeedperlevel: 0``
  for Jhin; the wiki and Meraki carry non-zero growth (Ahri AD growth 3).
- Kled attack range: DDragon 125, wiki 250, Meraki 250.
- Akshan MR: DDragon 33, wiki 33, Meraki 30 (Meraki is a "latest" feed that
  lags patches).
- Draven base AD: 62 in DDragon 16.18.1, 64 in 16.19.1.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lib.game_data import build as gd_build
from lib.game_data import fetch as gd_fetch
from lib.game_data import sources as gd_sources
from lib.game_data.replay import ReplayClient, ReplayMiss

FIX = Path(__file__).resolve().parent / "fixtures" / "game_data_replay"


@pytest.fixture()
def replay(tmp_path):
    """A private copy of the recorded bodies, so a test may plant a change."""
    d = tmp_path / "replay"
    shutil.copytree(FIX, d)
    return d


def _build(replay_dir: Path, tmp_path: Path, patch=None):
    client = ReplayClient(replay_dir)
    fetched = gd_fetch.fetch(patch, client=client, cache_dir=tmp_path / "cache")
    return gd_build.reconcile(fetched), fetched, client


# ----------------------------------------------------------------- replay


def test_replay_serves_recorded_bodies_and_refuses_unknown_urls(replay):
    client = ReplayClient(replay)
    r = client.get("https://ddragon.leagueoflegends.com/api/versions.json")
    assert r.status == 200 and r.json()[0] == "16.19.1"
    with pytest.raises(ReplayMiss):
        client.get("https://ddragon.leagueoflegends.com/cdn/99.1.1/data/en_US/champion.json")


def test_replay_index_points_only_at_existing_files():
    idx = json.loads((FIX / "_index.json").read_text(encoding="ascii"))
    assert len(idx["responses"]) >= 8
    for url, name in idx["responses"].items():
        assert url.startswith("https://") and (FIX / name).is_file(), url


# ----------------------------------------------------------------- build


def test_build_reconciles_with_per_field_provenance(replay, tmp_path):
    b, _f, _c = _build(replay, tmp_path)
    assert b.version == "16.19.1"
    assert sorted(b.champions) == ["Ahri", "Akshan", "Draven", "Jhin", "Kled"]
    assert sorted(b.items) == ["1055", "3031"]
    ahri = b.champions["Ahri"]
    # Every output field carries a documented source.
    assert set(ahri["_provenance"]) == set(gd_build.CHAMPION_FIELDS)
    for field in gd_build.CHAMPION_FIELDS:
        assert field in ahri and ahri["_provenance"][field] in {"ddragon", "wiki", "meraki"}
    # DDragon's 0 growth is a placeholder: the wiki's 3 is used and said so.
    assert ahri["ad_per_level"] == 3 and ahri["_provenance"]["ad_per_level"] == "wiki"
    # The attack-speed ratio exists only in the wiki - single-source field.
    assert ahri["_provenance"]["as_ratio"] == "wiki"
    # Items come from the official source.
    ie = b.items["3031"]
    assert ie["gold_total"] == 3500 and ie["_provenance"]["gold_total"] == "ddragon"


def test_disagreements_are_reconciled_to_the_named_authority_and_recorded(replay, tmp_path):
    b, _f, _c = _build(replay, tmp_path)
    cav = {(c["entity"], c["field"]): c for c in b.caveats}
    kled = cav[("champion:Kled", "attack_range")]
    assert kled["values_by_source"] == {"ddragon": 125, "meraki": 250, "wiki": 250}
    assert kled["chosen"] == 125 and kled["chosen_source"] == "ddragon"
    assert "authority" in kled["reason"]
    aks = cav[("champion:Akshan", "mr")]
    assert aks["values_by_source"]["meraki"] == 30 and aks["chosen"] == 33
    ahri = cav[("champion:Ahri", "ad_per_level")]
    assert ahri["chosen_source"] == "wiki" and "placeholder" in ahri["reason"]


def test_planted_disagreement_lands_in_caveats(replay, tmp_path):
    p = replay / "ddragon_champion.json"
    blob = json.loads(p.read_text(encoding="ascii"))
    blob["data"]["Draven"]["stats"]["movespeed"] = 999
    p.write_text(json.dumps(blob), encoding="ascii")
    b, _f, _c = _build(replay, tmp_path)
    cav = [c for c in b.caveats if c["entity"] == "champion:Draven" and c["field"] == "move_speed"]
    assert len(cav) == 1
    assert cav[0]["values_by_source"]["ddragon"] == 999 and cav[0]["chosen"] == 999


def test_agreement_produces_no_caveat(replay, tmp_path):
    b, _f, _c = _build(replay, tmp_path)
    assert not [c for c in b.caveats if c["entity"] == "champion:Ahri" and c["field"] == "hp"]


def test_missing_source_fails_the_build_loudly(replay, tmp_path):
    idx_p = replay / "_index.json"
    idx = json.loads(idx_p.read_text(encoding="ascii"))
    del idx["responses"]["https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw"]
    idx_p.write_text(json.dumps(idx), encoding="ascii")
    with pytest.raises(gd_fetch.MissingSourceError) as ei:
        _build(replay, tmp_path)
    assert "wiki" in str(ei.value)


def test_unparseable_source_fails_the_build_loudly(replay, tmp_path):
    (replay / "meraki_champions.json").write_text("<html>maintenance</html>", encoding="ascii")
    with pytest.raises(gd_fetch.MissingSourceError) as ei:
        _build(replay, tmp_path)
    assert "meraki" in str(ei.value)


def test_output_is_byte_stable_across_two_runs(replay, tmp_path):
    b1, _f, _c = _build(replay, tmp_path / "a")
    b2, _f, _c = _build(replay, tmp_path / "b")
    o1, o2 = tmp_path / "out1", tmp_path / "out2"
    gd_build.write_build(b1, o1)
    gd_build.write_build(b2, o2)
    names = sorted(p.name for p in o1.iterdir())
    assert names == ["caveats.json", "champions.json", "items.json", "report.json"]
    for n in names:
        assert (o1 / n).read_bytes() == (o2 / n).read_bytes(), n


def test_verify_reports_counts_and_zero_unexplained(replay, tmp_path):
    b, fetched, _c = _build(replay, tmp_path)
    rep = gd_build.verify(b, fetched)
    assert rep["counts_by_source"]["ddragon"] == {"champions": 5, "items": 2}
    assert rep["counts_by_source"]["wiki"] == {"champions": 5, "items": 0}
    assert rep["reconciled_fields"] == len(b.caveats) > 0
    assert rep["unexplained"] == []


def test_verify_catches_a_disagreement_the_build_did_not_explain(replay, tmp_path):
    b, fetched, _c = _build(replay, tmp_path)
    b.caveats = [c for c in b.caveats if not (c["entity"] == "champion:Kled" and c["field"] == "attack_range")]
    rep = gd_build.verify(b, fetched)
    assert [(u["entity"], u["field"]) for u in rep["unexplained"]] == [("champion:Kled", "attack_range")]


# ----------------------------------------------------------------- era / patch


def test_old_patch_uses_that_eras_tables_and_drops_unaddressable_sources(replay, tmp_path):
    b, fetched, _c = _build(replay, tmp_path, patch="16.18.1")
    assert b.version == "16.18.1"
    assert b.champions["Draven"]["ad"] == 62  # the 16.18.1 value, not 16.19.1's 64
    assert set(fetched.excluded) == {"meraki", "wiki"}
    era = [c for c in b.caveats if c["entity"] == "*"]
    assert {c["field"] for c in era} == {"source:meraki", "source:wiki"}
    # With the wiki gone, the DDragon growth placeholder has no alternative:
    # it is kept and the caveat says it is unresolved, never silently trusted.
    ahri = [c for c in b.caveats if c["entity"] == "champion:Ahri" and c["field"] == "ad_per_level"]
    assert ahri and "unresolved" in ahri[0]["reason"]


def test_unknown_patch_is_refused_before_any_source_is_fetched(replay, tmp_path):
    client = ReplayClient(replay)
    with pytest.raises(gd_fetch.MissingSourceError, match="unknown patch"):
        gd_fetch.fetch("9.9.9", client=client, cache_dir=tmp_path / "cache")
    assert client.calls == 1  # the version feed only


def test_new_patch_yields_a_diff_report(replay, tmp_path):
    old, _f, _c = _build(replay, tmp_path / "a", patch="16.18.1")
    new, _f, _c = _build(replay, tmp_path / "b")
    gd_build.write_build(old, tmp_path / "o")
    gd_build.write_build(new, tmp_path / "n")
    d = gd_build.diff_builds(tmp_path / "o", tmp_path / "n")
    assert d["from"] == "16.18.1" and d["to"] == "16.19.1"
    # The old build kept only the era-addressable source: flagged, not hidden.
    assert d["same_sources"] is False and d["sources"]["from"] == ["ddragon"]
    draven = [c for c in d["champions"]["changed"] if c["id"] == "Draven"]
    assert draven and draven[0]["fields"]["ad"] == [62, 64]


# ----------------------------------------------------------------- fetch layer


def test_cache_skips_work_already_done(replay, tmp_path):
    client = ReplayClient(replay)
    gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    first = client.calls
    gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    # Only the version feed is re-read (it decides which patch is current).
    assert client.calls - first == 1


def test_cache_is_keyed_by_patch(replay, tmp_path):
    client = ReplayClient(replay)
    gd_fetch.fetch(None, client=client, cache_dir=tmp_path / "cache")
    n = client.calls
    gd_fetch.fetch("16.18.1", client=client, cache_dir=tmp_path / "cache")
    assert client.calls - n >= 2  # the 16.18.1 tables were not served from the 16.19.1 cache


def test_live_client_ignores_environment_proxies(monkeypatch):
    """One in-process client, and a local proxy in the environment cannot sit
    between it and the upstream (it would be able to rewrite responses)."""
    import urllib.request as ur

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    client = gd_fetch.live_client()
    # An empty ProxyHandler installs no proxy_open hooks, so no ProxyHandler
    # with a proxy map may be present at all.
    proxies = [h for h in client._opener.handlers if isinstance(h, ur.ProxyHandler) and h.proxies]
    assert proxies == []
    assert client._trust_env_proxy is False


def test_default_shared_client_still_honours_environment_proxies(monkeypatch):
    """The opt-out is local to the pipeline; other callers are unchanged."""
    import urllib.request as ur

    from lib.http.client import HttpClient

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    proxies = [h for h in HttpClient()._opener.handlers if isinstance(h, ur.ProxyHandler)]
    assert proxies and proxies[0].proxies.get("https") == "http://127.0.0.1:9"


def test_cli_build_exit_codes(replay, tmp_path, capsys):
    from tools import game_data_pipeline as cli

    rc = cli.main(["--data-root", str(tmp_path / "gd"), "build"], client=ReplayClient(replay))
    out = capsys.readouterr().out
    assert rc == 0 and "unexplained disagreements: 0" in out and "ddragon: 5 champions, 2 items" in out
    assert (tmp_path / "gd" / "16.19.1" / "caveats.json").is_file()
    (replay / "wiki_championdata.lua.txt").write_text("not lua", encoding="ascii")
    rc = cli.main(["--data-root", str(tmp_path / "gd2"), "build"], client=ReplayClient(replay))
    assert rc == 2 and not (tmp_path / "gd2" / "16.19.1").exists()


def test_every_source_declares_its_terms():
    for s in gd_sources.SOURCES:
        assert s.kind in {"official", "community", "wiki"}
        assert s.terms, s.id
    wiki = [s for s in gd_sources.SOURCES if s.kind == "wiki"]
    # The wiki is read through ONE raw-module request, never page scraping.
    assert len(wiki) == 1 and len(wiki[0].urls("16.19.1")) == 1
