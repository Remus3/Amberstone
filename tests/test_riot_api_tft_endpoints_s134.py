"""s134: TFT-Match-V1 / TFT-League-V1 wrappers + the TFT key scope in
core/riot_api.py.

MEASURED 2026-10-25 (the reason the key scope exists): the LoL product key in
API-Key-Riot.txt answers 403 on every /tft/* route while Account-V1 answers 200
on it, so TFT calls need their own key, and PUUIDs are encrypted PER KEY
(memory reference_riot_puuid_rotation) - every key-scoped cache key must follow
the scope. All HTTP is a recording spy on `_http_get`; keys are fake.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from core import riot_api as RA
from core import riot_api_cache as RIC

MAIN_KEY = "RGAPI-main-test-key-0000000000000000000000"  # rc-credential-scan: allow-fixture
TFT_KEY = "RGAPI-tft-test-key-11111111111111111111111"  # rc-credential-scan: allow-fixture
PUUID = "TESTPUUID-" + "a" * 68


def _resp(status, body=None, headers=None):
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    return RA._HttpResp(status, payload, dict(headers or {}))


class _Spy:
    def __init__(self, *responses):
        self.calls: list[tuple[str, str]] = []
        self._responses = list(responses)

    def __call__(self, url, api_key, timeout_s=None):
        self.calls.append((url, api_key))
        r = self._responses[min(len(self.calls), len(self._responses)) - 1]
        return r(url) if callable(r) else r


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "_KEY_CACHE", MAIN_KEY)
    monkeypatch.setattr(RA, "_TFT_KEY_CACHE", None)
    monkeypatch.setattr(RA, "_TFT_API_KEY_FILE", tmp_path / "API-Key-Riot-TFT.txt")
    RA._KEY_OVERRIDE_TLS.key = None
    RA._reset_bucket_for_tests()
    RIC._reset_for_tests(db_path=tmp_path / "cache.db")
    yield tmp_path
    RA._KEY_OVERRIDE_TLS.key = None
    RA._reset_bucket_for_tests()
    RIC._reset_for_tests(db_path=None)


def _install(spy, monkeypatch):
    monkeypatch.setattr(RA, "_http_get", spy)


# -- URL shapes (paths per the Riot schema, checked 2026-10-25) -------------

def test_match_ids_url_is_regional_with_start_and_count(env, monkeypatch):
    spy = _Spy(_resp(200, ["NA1_1", "NA1_2"]))
    _install(spy, monkeypatch)
    assert RA.get_tft_match_ids(PUUID, count=10) == ["NA1_1", "NA1_2"]
    url = spy.calls[0][0]
    assert url == ("https://americas.api.riotgames.com/tft/match/v1/matches/"
                   f"by-puuid/{PUUID}/ids?start=0&count=10")


def test_match_ids_count_is_clamped(env, monkeypatch):
    spy = _Spy(_resp(200, []))
    _install(spy, monkeypatch)
    RA.get_tft_match_ids(PUUID, count=5000)
    RA.get_tft_match_ids(PUUID, count=0)
    assert spy.calls[0][0].endswith("count=100")
    assert spy.calls[1][0].endswith("count=1")


def test_league_url_is_platform_by_puuid_and_ttl_cached(env, monkeypatch):
    entries = [{"queueType": "RANKED_TFT", "tier": "GOLD", "rank": "II",
                "leaguePoints": 40, "wins": 3, "losses": 20}]
    spy = _Spy(_resp(200, entries))
    _install(spy, monkeypatch)
    assert RA.get_tft_league_entries(PUUID) == entries
    assert RA.get_tft_league_entries(PUUID) == entries
    assert len(spy.calls) == 1, "second read must come from the TTL cache"
    assert spy.calls[0][0] == f"https://na1.api.riotgames.com/tft/league/v1/by-puuid/{PUUID}"


def test_match_detail_is_immutable_cached_in_its_own_namespace(env, monkeypatch):
    body = {"metadata": {"match_id": "NA1_9"}, "info": {"participants": []}}
    spy = _Spy(_resp(200, body))
    _install(spy, monkeypatch)
    assert RA.get_tft_match("NA1_9") == body
    assert RA.get_tft_match("NA1_9") == body
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "https://americas.api.riotgames.com/tft/match/v1/matches/NA1_9"
    assert RIC.get_cache().get_immutable("tft:match:v1:NA1_9") == body
    assert RIC.get_cache().get_immutable("match:v5:NA1_9") is None


def test_match_detail_refuses_colon_ids_before_any_call(env, monkeypatch):
    spy = _Spy(_resp(200, {}))
    _install(spy, monkeypatch)
    assert RA.get_tft_match("timeline:NA1_9") is None
    assert spy.calls == []


# -- failure paths -----------------------------------------------------------

def test_403_on_tft_route_is_reported_and_negative_cached(env, monkeypatch):
    """The measured live answer for the LoL product key on /tft/*."""
    spy = _Spy(_resp(403, {"status": {"message": "Forbidden", "status_code": 403}}))
    _install(spy, monkeypatch)
    with RA.track_outcomes() as scope:
        assert RA.get_tft_match("NA1_7") is None
    assert scope.outcomes == ["forbidden"]
    RA._reset_bucket_for_tests()
    assert RA.get_tft_match("NA1_7") is None
    assert len(spy.calls) == 1, "403 detail must be negative-cached (RM-163)"


def test_403_on_league_is_not_negative_cached(env, monkeypatch):
    spy = _Spy(_resp(403, {}))
    _install(spy, monkeypatch)
    assert RA.get_tft_league_entries(PUUID) is None
    assert RA.get_tft_league_entries(PUUID) is None
    assert len(spy.calls) == 2


def test_429_honours_retry_after_and_reports_rate_limit(env, monkeypatch):
    spy = _Spy(_resp(429, {}, {"Retry-After": "7"}))
    _install(spy, monkeypatch)
    with RA.track_outcomes() as scope:
        assert RA.get_tft_match_ids(PUUID) is None
    assert scope.rate_limited
    cd = RA.bucket_snapshot()["cooldown_remaining_s"]
    assert 5.0 < cd <= 7.0
    # The bucket now refuses to SEND until Retry-After passes.
    with RA.track_outcomes() as scope2:
        assert RA._call_ex("x", "https://americas.api.riotgames.com/x",
                           rate_limit_timeout_s=0.0)[1] == "rate_limited"
    assert scope2.rate_limited
    assert len(spy.calls) == 1


def test_wrong_shape_is_none(env, monkeypatch):
    spy = _Spy(_resp(200, {"not": "a list"}))
    _install(spy, monkeypatch)
    assert RA.get_tft_match_ids(PUUID) is None
    assert RA.get_tft_league_entries(PUUID) is None


# -- the TFT key scope --------------------------------------------------------

def test_scope_without_tft_key_file_keeps_main_key(env, monkeypatch):
    spy = _Spy(_resp(200, []))
    _install(spy, monkeypatch)
    with RA.tft_key_scope() as have_tft:
        RA.get_tft_match_ids(PUUID)
    assert have_tft is False
    assert spy.calls[0][1] == MAIN_KEY


def test_scope_routes_this_thread_through_tft_key_and_restores(env, monkeypatch):
    (env / "API-Key-Riot-TFT.txt").write_text(f'"{TFT_KEY}"\n', encoding="utf-8")
    spy = _Spy(_resp(200, []))
    _install(spy, monkeypatch)
    fp_main = RA._key_fingerprint()
    with RA.tft_key_scope() as have_tft:
        assert have_tft is True
        fp_tft = RA._key_fingerprint()
        RA.get_tft_match_ids(PUUID)
    RA.get_tft_match_ids(PUUID)
    assert [k for _, k in spy.calls] == [TFT_KEY, MAIN_KEY]
    assert fp_tft != fp_main, "account / negative cache keys must follow the key"
    assert RA._key_fingerprint() == fp_main


def test_scope_restores_on_exception(env):
    (env / "API-Key-Riot-TFT.txt").write_text(TFT_KEY, encoding="utf-8")
    with pytest.raises(RuntimeError), RA.tft_key_scope():
        raise RuntimeError("boom")
    assert RA._get_api_key() == MAIN_KEY


def test_scope_is_thread_local(env):
    (env / "API-Key-Riot-TFT.txt").write_text(TFT_KEY, encoding="utf-8")
    seen = {}
    inside = threading.Event()
    release = threading.Event()

    def other():
        inside.wait(5)
        seen["other"] = RA._get_api_key()
        release.set()

    t = threading.Thread(target=other)
    t.start()
    with RA.tft_key_scope():
        inside.set()
        release.wait(5)
        seen["scoped"] = RA._get_api_key()
    t.join(5)
    assert seen == {"other": MAIN_KEY, "scoped": TFT_KEY}


def test_account_lookup_inside_scope_is_cached_under_tft_fingerprint(env, monkeypatch):
    """A PUUID resolved by the TFT key must never be served to a main-key call."""
    (env / "API-Key-Riot-TFT.txt").write_text(TFT_KEY, encoding="utf-8")
    spy = _Spy(lambda url: _resp(200, {"puuid": "P-" + ("tft" if spy.calls[-1][1] == TFT_KEY
                                                       else "main")}))
    _install(spy, monkeypatch)
    with RA.tft_key_scope():
        a = RA.get_account_by_riot_id("Opponent", "TST1")
    b = RA.get_account_by_riot_id("Opponent", "TST1")
    assert a == {"puuid": "P-tft"}
    assert b == {"puuid": "P-main"}
    assert len(spy.calls) == 2


def test_bad_tft_key_file_is_ignored(env, monkeypatch):
    (env / "API-Key-Riot-TFT.txt").write_text("not-a-key", encoding="utf-8")
    with RA.tft_key_scope() as have_tft:
        assert RA._get_api_key() == MAIN_KEY
    assert have_tft is False


def test_reload_clears_the_tft_key_cache(env):
    p: Path = env / "API-Key-Riot-TFT.txt"
    p.write_text(TFT_KEY, encoding="utf-8")
    assert RA._get_tft_api_key() == TFT_KEY
    p.write_text("RGAPI-rotated-tft-key", encoding="utf-8")
    assert RA._get_tft_api_key() == TFT_KEY
    RA.reload_api_key()
    assert RA._KEY_CACHE is None
    assert RA._get_tft_api_key() == "RGAPI-rotated-tft-key"
