"""True-audit hardening of dashboard/_party_mains.py (s144 cycle 120).

One test (or a small group) per finding, RM-1565..RM-1572:

- 185 member-set key: built from the riot_id field, so two different lobbies
  whose members carry no riot_id collapsed onto one key ("",) and served each
  other's cards; the key now comes from the game_name#tag_line actually looked
  up, normalised, plus the region.
- 186 untrusted lobby member shapes: a non-string game_name / tag_line was
  str()-ed into a Riot lookup, control characters and oversized values were
  forwarded, and an unbounded member list fanned out unbounded Riot calls.
- 187 per-member fail-soft: one member whose lookup RAISED dropped every
  member's card (the docstring promises a per-member drop).
- 188 card fields: a junk championId / championLevel / championPoints / player
  reached the panel raw (bool id, negative or non-number level, dict player).
- 189 a thread that cannot start leaked its key into the in-flight set for
  good (the lobby never refreshed again) and raised out of enrich_party_mains,
  which promises never to raise.
- 190 TTL on the wall clock: a clock stepped backwards kept a stale entry
  "fresh" for as long as the step.
- 191 a refresh for an OLDER lobby that finished late overwrote the newer
  lobby's cached result.
- 192 the injected cards were the cache's own dicts, so a caller's mutation
  rewrote the cache.

No network and no real threads: the Riot lookups are monkeypatched and the
background thread is replaced by a recorder that never runs its target.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.archetype_picks as AP  # noqa: E402
import core.riot_api as RA  # noqa: E402
import dashboard._party_mains as PM  # noqa: E402


def _member(game, tag, *, riot_id=None, is_self=False, name=None):
    return {"riot_id": riot_id if riot_id is not None else f"{game}#{tag}",
            "game_name": game, "tag_line": tag,
            "is_self": is_self, "summoner_name": name or game}


@pytest.fixture(autouse=True)
def _reset():
    PM._reset_cache_for_tests()
    yield
    PM._reset_cache_for_tests()


class _ThreadRecorder:
    """Stand-in for threading.Thread: records each start, never runs it."""

    started: list = []

    def __init__(self, *, target=None, args=(), daemon=None, name=None):
        self.target, self.args = target, args

    def start(self):
        _ThreadRecorder.started.append(self.args)


@pytest.fixture
def threads(monkeypatch):
    _ThreadRecorder.started = []
    monkeypatch.setattr(PM.threading, "Thread", _ThreadRecorder)
    return _ThreadRecorder.started


def _patch_riot(monkeypatch, *, tops, champ="Jinx", account=None, calls=None):
    def _acct(g, t, **k):
        if calls is not None:
            calls.append((g, t))
        return account if account is not None else {"puuid": f"P-{g}"}
    monkeypatch.setattr(RA, "get_account_by_riot_id", _acct)
    monkeypatch.setattr(RA, "get_top_champion_masteries", lambda p, **k: tops)
    monkeypatch.setattr(AP, "champion_name_by_key", lambda cid: champ)


_TOP = [{"championId": 222, "championLevel": 7, "championPoints": 43989}]


# -- RM-1565 member-set key ------------------------------------------------

def test_key_distinguishes_lobbies_without_riot_id():
    a = [_member("Alpha", "NA1", riot_id=""), _member("Beta", "NA1", riot_id="")]
    b = [_member("Gamma", "NA1", riot_id=""), _member("Delta", "NA1", riot_id="")]
    assert PM._member_key(a) != PM._member_key(b)


def test_key_follows_looked_up_identity_not_riot_id_field():
    # riot_id disagrees with the game_name/tag_line that is actually queried
    a = [_member("Alpha", "NA1", riot_id="Same#X")]
    b = [_member("Beta", "NA1", riot_id="Same#X")]
    assert PM._member_key(a) != PM._member_key(b)


def test_key_is_case_and_whitespace_insensitive_and_region_scoped():
    a = [_member("Alpha", "NA1")]
    b = [_member(" alpha ", "na1 ")]
    assert PM._member_key(a) == PM._member_key(b)
    assert PM._member_key(a, region="na1") != PM._member_key(a, region="euw1")


def test_enrich_does_not_serve_another_lobbys_cards(threads):
    a = [_member("Me", "NA1", is_self=True),
         _member("Alpha", "NA1", riot_id="")]
    b = [_member("Me", "NA1", is_self=True),
         _member("Gamma", "NA1", riot_id="")]
    PM._cache.update(key=PM._member_key(a), data=[{"name": "Jinx"}],
                     fetched_at=PM.time.monotonic(), ttl=PM._TTL_S)
    out = PM.enrich_party_mains({"lobby": {"members": b}})
    assert "party_mains" not in out


# -- RM-1566 untrusted member shapes -----------------------------------------

@pytest.mark.parametrize("game,tag", [
    ({"a": 1}, "NA1"),
    ("Alpha", 1234),
    (["Alpha"], "NA1"),
    ("Al\x00pha", "NA1"),
    ("Alpha", "NA\n1"),
    ("A" * 200, "NA1"),
    ("Alpha", "T" * 50),
])
def test_ineligible_junk_identity(game, tag):
    assert PM._eligible([{"game_name": game, "tag_line": tag}]) == []


def test_eligible_strips_and_keeps_valid():
    out = PM._eligible([{"game_name": "  Alpha ", "tag_line": " NA1 "}])
    assert len(out) == 1


def test_member_fanout_is_bounded(monkeypatch):
    calls: list = []
    _patch_riot(monkeypatch, tops=_TOP, calls=calls)
    members = [_member(f"P{i}", "NA1") for i in range(60)]
    PM.build_party_mains(members)
    assert 0 < len(calls) <= PM._MAX_MEMBERS


def test_duplicate_member_looked_up_once(monkeypatch):
    calls: list = []
    _patch_riot(monkeypatch, tops=_TOP, calls=calls)
    out = PM.build_party_mains([_member("Alpha", "NA1"), _member("alpha", "na1")])
    assert len(calls) == 1 and len(out) == 1


# -- RM-1567 per-member fail-soft --------------------------------------------

def test_one_raising_member_keeps_the_others(monkeypatch):
    _patch_riot(monkeypatch, tops=_TOP)

    def _acct(g, t, **k):
        if g == "Bad":
            raise RuntimeError("boom")
        return {"puuid": f"P-{g}"}
    monkeypatch.setattr(RA, "get_account_by_riot_id", _acct)
    out = PM.build_party_mains([_member("Bad", "NA1"), _member("Good", "NA1")])
    assert [c["player"] for c in out] == ["Good"]


def test_raising_champion_lookup_keeps_the_others(monkeypatch):
    _patch_riot(monkeypatch, tops=_TOP)
    seen = {"n": 0}

    def _name(cid):
        seen["n"] += 1
        if seen["n"] == 1:
            raise ValueError("bad champions.json")
        return "Jinx"
    monkeypatch.setattr(AP, "champion_name_by_key", _name)
    out = PM.build_party_mains([_member("One", "NA1"), _member("Two", "NA1")])
    assert [c["player"] for c in out] == ["Two"]


# -- RM-1568 card field validation -------------------------------------------

@pytest.mark.parametrize("cid", [True, None, -5, 0, "abc", 2.5, {"x": 1}])
def test_junk_champion_id_drops_card(monkeypatch, cid):
    _patch_riot(monkeypatch, champ="",
                tops=[{"championId": cid, "championLevel": 7,
                       "championPoints": 10}])
    assert PM.build_party_mains([_member("Alpha", "NA1")]) == []


def test_numeric_string_champion_id_resolves(monkeypatch):
    _patch_riot(monkeypatch, champ="Jinx",
                tops=[{"championId": "222", "championLevel": 7,
                       "championPoints": 10}])
    out = PM.build_party_mains([_member("Alpha", "NA1")])
    assert out and out[0]["name"] == "Jinx"


@pytest.mark.parametrize("bad", [True, -1, "7", 1.5, float("nan"), {"a": 1}, 10**15])
def test_junk_mastery_numbers_become_none(monkeypatch, bad):
    _patch_riot(monkeypatch,
                tops=[{"championId": 222, "championLevel": bad,
                       "championPoints": bad}])
    out = PM.build_party_mains([_member("Alpha", "NA1")])
    assert out[0]["mastery_level"] is None
    assert out[0]["mastery_points"] is None


@pytest.mark.parametrize("puuid", [{"x": 1}, 12345, "   ", ["P"]])
def test_junk_puuid_never_reaches_mastery_lookup(monkeypatch, puuid):
    mastery_calls: list = []
    _patch_riot(monkeypatch, tops=_TOP, account={"puuid": puuid})
    monkeypatch.setattr(RA, "get_top_champion_masteries",
                        lambda p, **k: mastery_calls.append(p) or _TOP)
    assert PM.build_party_mains([_member("Alpha", "NA1")]) == []
    assert mastery_calls == []


@pytest.mark.parametrize("bad_name", [{"x": 1}, "   ", None, 7])
def test_non_string_champion_name_falls_back_to_id(monkeypatch, bad_name):
    _patch_riot(monkeypatch, tops=_TOP, champ=bad_name)
    out = PM.build_party_mains([_member("Alpha", "NA1")])
    assert out[0]["name"] == "222"


def test_player_is_a_bounded_string(monkeypatch):
    _patch_riot(monkeypatch, tops=_TOP)
    m = _member("Alpha", "NA1")
    m["summoner_name"] = {"evil": 1}
    m["riot_id"] = ["x"]
    out = PM.build_party_mains([m])
    assert out[0]["player"] == "Alpha#NA1"
    m2 = _member("Beta", "NA1", name="Z" * 500)
    out2 = PM.build_party_mains([m2])
    assert isinstance(out2[0]["player"], str) and len(out2[0]["player"]) <= 64


# -- RM-1569 thread start failure --------------------------------------------

def test_thread_start_failure_never_raises_and_releases_key(monkeypatch):
    class _Boom:
        def __init__(self, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(PM.threading, "Thread", _Boom)
    members = [_member("Me", "NA1", is_self=True), _member("Alpha", "NA1")]
    snap = {"lobby": {"members": members}}
    assert PM.enrich_party_mains(snap) is snap
    assert PM._refreshing == set()


# -- RM-1570 monotonic TTL ---------------------------------------------------

class _Clock:
    def __init__(self, wall, mono):
        self.wall, self.mono = wall, mono

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono


def test_backward_wall_clock_step_does_not_freeze_the_cache(monkeypatch, threads):
    clock = _Clock(wall=2_000_000_000.0, mono=1000.0)
    monkeypatch.setattr(PM, "time", clock)
    monkeypatch.setattr(PM, "build_party_mains", lambda m, **k: [{"name": "Jinx"}])
    members = [_member("Me", "NA1", is_self=True), _member("Alpha", "NA1")]
    key = PM._member_key(members)
    PM._refresh(members, key, PM._DEFAULT_REGION)
    # wall clock stepped back an hour, monotonic advanced past the TTL
    clock.wall -= 3600.0
    clock.mono += PM._TTL_S + 1.0
    PM.enrich_party_mains({"lobby": {"members": members}})
    assert len(threads) == 1


# -- RM-1571 late refresh of an older lobby ----------------------------------

def test_late_older_refresh_does_not_overwrite_newer(monkeypatch, threads):
    a = [_member("Me", "NA1", is_self=True), _member("Alpha", "NA1")]
    b = [_member("Me", "NA1", is_self=True), _member("Beta", "NA1")]
    PM.enrich_party_mains({"lobby": {"members": a}})
    PM.enrich_party_mains({"lobby": {"members": b}})
    assert len(threads) == 2
    monkeypatch.setattr(PM, "build_party_mains",
                        lambda m, **k: [{"name": m[-1]["game_name"]}])
    PM._refresh(*threads[1])   # B finishes first
    PM._refresh(*threads[0])   # A finishes late
    assert PM._cache["key"] == PM._member_key(b)
    out = PM.enrich_party_mains({"lobby": {"members": b}})
    assert out["party_mains"] == [{"name": "Beta"}]
    assert PM._refreshing == set()


# -- RM-1572 caller gets its own copy ----------------------------------------

def test_injected_cards_are_copies(threads):
    members = [_member("Me", "NA1", is_self=True), _member("Alpha", "NA1")]
    PM._cache.update(key=PM._member_key(members),
                     data=[{"name": "Jinx", "player": "Alpha"}],
                     fetched_at=PM.time.monotonic(), ttl=PM._TTL_S)
    out = PM.enrich_party_mains({"lobby": {"members": members}})
    out["party_mains"][0]["name"] = "MUTATED"
    out["party_mains"].append({"name": "extra"})
    again = PM.enrich_party_mains({"lobby": {"members": members}})
    assert again["party_mains"] == [{"name": "Jinx", "player": "Alpha"}]
