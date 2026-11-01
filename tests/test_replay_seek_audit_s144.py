"""Lane 8 true-audit (s144 cycle 99) of core/replay_seek.py.

One test group per finding (F1-F13). Each was RED against the module as it
stood on main before this cycle; the controls marked CONTROL passed there too.
Transport is injected or urlopen is monkeypatched, so nothing here touches a
network, a socket or a running client. Every id and name is synthetic.
"""
from __future__ import annotations

import math

import pytest

from core import replay_analysis as ra
from core import replay_seek as rs


def _player(champ="Vi", **kw) -> dict:
    base = {"summonerName": "A", "championName": champ, "level": 11,
            "position": "JUNGLE", "team": "ORDER",
            "scores": {"kills": 3, "deaths": 1, "assists": 7,
                       "creepScore": 112},
            "items": [{"itemID": 6692}, {"itemID": 3111}]}
    base.update(kw)
    return base


class _Client:
    """Records seeks; serves a fixed blob (gameTime follows the seek)."""

    def __init__(self, players=None, game_time=None):
        self.seeks = []
        self.players = [_player()] if players is None else players
        self.game_time = game_time

    def post_playback(self, t_s):
        self.seeks.append(t_s)

    def get_allgamedata(self):
        gt = self.game_time if self.game_time is not None else (
            self.seeks[-1] if self.seeks else 0.0)
        return {"gameData": {"gameTime": gt}, "allPlayers": self.players}


class _Resp:
    """A stand-in for an http.client response."""

    def __init__(self, body: bytes):
        self.body = body
        self.closed = False
        self.read_sizes = []

    def read(self, n=-1):
        self.read_sizes.append(n)
        if n is None or n < 0:
            return self.body
        return self.body[:n]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def fake_urlopen(monkeypatch):
    made = []

    def install(body: bytes):
        def _urlopen(req, timeout=None, context=None):
            resp = _Resp(body)
            made.append((req, timeout, resp))
            return resp
        monkeypatch.setattr(rs.urllib.request, "urlopen", _urlopen)
        monkeypatch.setattr(rs.time, "sleep", lambda s: None)
        return made
    return install


# ------------------------------------------- F1: the seek response is closed

def test_f1_post_playback_closes_its_response(fake_urlopen):
    made = fake_urlopen(b'{"paused": true}')
    rs.ReplayClient(settle_s=0.0).post_playback(600.0)
    assert len(made) == 1
    assert made[0][2].closed is True


def test_f1_control_get_allgamedata_closes_its_response(fake_urlopen):
    # CONTROL: the read path already used `with`.
    made = fake_urlopen(b'{"allPlayers": []}')
    rs.ReplayClient().get_allgamedata()
    assert made[0][2].closed is True


# ------------------------------------------------- F2: reads are bounded

def test_f2_every_read_is_bounded(fake_urlopen):
    made = fake_urlopen(b'{"allPlayers": []}')
    c = rs.ReplayClient(settle_s=0.0)
    c.post_playback(1.0)
    c.get_allgamedata()
    sizes = [n for _req, _t, resp in made for n in resp.read_sizes]
    assert sizes, "no read happened"
    assert all(isinstance(n, int) and n > 0 for n in sizes), sizes


def test_f2_an_oversized_frame_is_a_typed_seek_error(fake_urlopen, monkeypatch):
    monkeypatch.setattr(rs, "MAX_BODY_BYTES", 64, raising=False)
    fake_urlopen(b'{"allPlayers": [], "pad": "' + b"x" * 200 + b'"}')
    with pytest.raises(rs.SeekError):
        rs.sample_at(rs.ReplayClient(settle_s=0.0), 10.0)


def test_f2_an_oversized_body_is_refused_not_truncated(fake_urlopen,
                                                       monkeypatch):
    # The first MAX+1 bytes alone parse as JSON here, so only the explicit
    # length check (not a JSON error on a truncated body) can refuse it.
    monkeypatch.setattr(rs, "MAX_BODY_BYTES", 2, raising=False)
    fake_urlopen(b"{}" + b" " * 200)
    with pytest.raises(rs.SeekError, match="exceeds"):
        rs.ReplayClient(settle_s=0.0).get_allgamedata()


def test_f2_a_body_at_the_cap_is_still_read(fake_urlopen, monkeypatch):
    body = b'{"gameData": {"gameTime": 10.0}, "allPlayers": []}'
    monkeypatch.setattr(rs, "MAX_BODY_BYTES", len(body), raising=False)
    fake_urlopen(body)
    s = rs.sample_at(rs.ReplayClient(settle_s=0.0), 10.0)
    assert s.t_s == 10.0


# ------------------------------------- F3: the client refuses a bad config

@pytest.mark.parametrize("kw", [
    {"settle_s": -1.0}, {"settle_s": float("nan")}, {"settle_s": True},
    {"settle_s": "2"}, {"timeout_s": 0.0}, {"timeout_s": -5.0},
    {"timeout_s": float("inf")}, {"timeout_s": None},
], ids=["settle-neg", "settle-nan", "settle-bool", "settle-str",
        "timeout-0", "timeout-neg", "timeout-inf", "timeout-none"])
def test_f3_bad_timing_is_refused_at_construction(kw):
    with pytest.raises(ValueError):
        rs.ReplayClient(**kw)


@pytest.mark.parametrize("base", [
    "file:///replay/x.json", "ftp://127.0.0.1:2999", "127.0.0.1:2999", "",
    "https://", 2999,
], ids=["file", "ftp", "no-scheme", "empty", "no-host", "int"])
def test_f3_a_non_http_base_is_refused(base):
    with pytest.raises(ValueError):
        rs.ReplayClient(base=base)


def test_f3_control_defaults_and_http_bases_are_accepted():
    assert rs.ReplayClient().base == "https://127.0.0.1:2999"
    assert rs.ReplayClient(base="http://localhost:2999/").base == (
        "http://localhost:2999")
    assert rs.ReplayClient(settle_s=0, timeout_s=1).settle_s == 0


def test_f3_a_negative_settle_no_longer_seeks_then_crashes(fake_urlopen):
    made = fake_urlopen(b"{}")
    with pytest.raises(ValueError):
        rs.ReplayClient(settle_s=-1.0).post_playback(1.0)
    assert made == []


# --------------------------------- F4: requested times are validated first

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True,
                                 "600", None, [600.0]],
                         ids=["nan", "inf", "neg", "bool", "str", "none",
                              "list"])
def test_f4_sample_at_refuses_a_bad_time_before_seeking(bad):
    c = _Client()
    with pytest.raises(ValueError):
        rs.sample_at(c, bad)
    assert c.seeks == []


def test_f4_a_sweep_with_one_bad_time_seeks_nothing():
    c = _Client()
    with pytest.raises(ValueError):
        rs.sample_series(c, [0.0, 30.0, float("nan")])
    assert c.seeks == []


def test_f4_a_lenient_sweep_refuses_a_bad_time_before_seeking():
    c = _Client()
    with pytest.raises(ValueError):
        rs.sample_series_lenient(c, [0.0, -5.0])
    assert c.seeks == []


def test_f4_the_seek_body_is_strict_json(fake_urlopen):
    made = fake_urlopen(b"{}")
    c = rs.ReplayClient(settle_s=0.0)
    with pytest.raises(ValueError):
        c.post_playback(float("nan"))
    assert made == []


def test_f4_control_int_and_zero_times_are_accepted():
    c = _Client()
    out = rs.sample_series(c, [0, 30])
    assert c.seeks == [0.0, 30.0]
    assert [s.t_s for s in out] == [0.0, 30.0]


def test_f4_control_a_lenient_sweep_accepts_a_generator():
    c = _Client()
    out, failed = rs.sample_series_lenient(c, (t for t in (0.0, 30.0)))
    assert [s.t_s for s in out] == [0.0, 30.0]
    assert failed == []


# ------------------------------- F5: an impossible gameTime is not trusted

@pytest.mark.parametrize("gt", [-3.0, "-1"], ids=["neg", "neg-str"])
def test_f5_a_negative_game_time_falls_back_to_the_request(gt):
    s = rs.sample_at(_Client(game_time=gt), 300.0)
    assert s.t_s == 300.0


def test_f5_control_a_real_observed_time_wins():
    s = rs.sample_at(_Client(game_time=301.5), 300.0)
    assert s.t_s == 301.5


# --------------------------------- F6: counts and item ids are strict ints

@pytest.mark.parametrize("bad", [-3, 2.5, "2.5", "-1", 1e300],
                         ids=["neg", "frac", "frac-str", "neg-str", "huge"])
def test_f6_a_bad_count_degrades_to_zero(bad):
    p = rs._player_from(_player(level=bad, scores={
        "kills": bad, "deaths": bad, "assists": bad, "creepScore": bad}))
    assert (p.level, p.kills, p.deaths, p.assists, p.cs) == (0,) * 5


@pytest.mark.parametrize("bad", [-5, 3111.5, "3111.5", 0, 1e300, "1_000"],
                         ids=["neg", "frac", "frac-str", "zero", "huge",
                              "underscore"])
def test_f6_a_bad_item_id_is_skipped(bad):
    p = rs._player_from(_player(items=[{"itemID": bad}, {"itemID": 6692}]))
    assert p.item_ids == [6692]


def test_f6_control_integral_numbers_and_numeric_strings_still_read():
    p = rs._player_from(_player(level="12", scores={
        "kills": 3.0, "deaths": "1", "assists": 0, "creepScore": 112}))
    assert (p.level, p.kills, p.deaths, p.assists, p.cs) == (12, 3, 1, 0, 112)
    assert rs._player_from(_player(items=[{"itemID": "3111"},
                                          {"itemID": 6692.0}])).item_ids == [
        3111, 6692]


# ------------------------------------- F7: names are strings, never a repr

@pytest.mark.parametrize("field", ["championName", "summonerName",
                                   "position", "team"])
@pytest.mark.parametrize("bad", [{"x": 1}, [1, 2], 5, 1.5, True],
                         ids=["dict", "list", "int", "float", "bool"])
def test_f7_a_non_string_name_reads_empty(field, bad):
    p = rs._player_from(_player(**{field: bad}))
    got = {"championName": p.champion, "summonerName": p.summoner,
           "position": p.role, "team": p.team}[field]
    assert got == ""


def test_f7_the_summoner_falls_back_to_the_riot_id_game_name():
    raw = _player()
    del raw["summonerName"]
    raw["riotIdGameName"] = "Synth"
    assert rs._player_from(raw).summoner == "Synth"


def test_f7_control_summoner_name_wins_over_riot_id():
    raw = _player(summonerName="A", riotIdGameName="B")
    assert rs._player_from(raw).summoner == "A"


# --------------------- F8: a skipped entry does not shift the later seats

def test_f8_a_skipped_entry_keeps_every_later_seat():
    players = [_player("Vi"), "garbage"] + [
        _player(c) for c in ("Lux", "Ahri", "Jinx", "Nami", "Garen",
                             "Zed", "Ezreal", "Lulu")]
    s = rs.sample_at(_Client(players=players), 10.0)
    seats = {p.champion: p.seat for p in s.players}
    assert seats["Vi"] == 1
    assert seats["Lux"] == 3
    assert seats["Nami"] == 6        # the old list-order id was 5
    tl = rs.to_timeline([s])
    by_pid = {f.participant_id: f for f in tl.frames}
    assert sorted(by_pid) == [1, 3, 4, 5, 6, 7, 8, 9, 10]
    assert ra.team_of(6) == 200      # Nami stays on the CHAOS side


def test_f8_control_a_clean_roster_seats_in_order():
    s = rs.sample_at(_Client(players=[_player("Vi"), _player("Lux")]), 10.0)
    assert [(p.champion, p.seat) for p in s.players] == [("Vi", 1),
                                                        ("Lux", 2)]


# ------------------ F9: a seat whose champion changes is a scrambled join

def test_f9_a_roster_reorder_between_samples_is_refused():
    a = rs.sample_at(_Client(players=[_player("Vi"), _player("Lux")]), 0.0)
    b = rs.sample_at(_Client(players=[_player("Lux"), _player("Vi")]), 30.0)
    with pytest.raises(ValueError, match="seat"):
        rs.to_timeline([a, b])


def test_f9_control_an_unreadable_name_is_not_a_reorder():
    a = rs.sample_at(_Client(players=[_player("Vi")]), 0.0)
    b = rs.sample_at(_Client(players=[_player(5)]), 30.0)
    c = rs.sample_at(_Client(players=[_player("Vi")]), 60.0)
    tl = rs.to_timeline([a, b, c])
    assert [f.participant_id for f in tl.frames] == [1, 1, 1]


def test_f9_control_an_empty_roster_sample_is_not_a_reorder():
    a = rs.sample_at(_Client(players=[_player("Vi")]), 0.0)
    b = rs.sample_at(_Client(players=[]), 30.0)
    c = rs.sample_at(_Client(players=[_player("Vi")]), 60.0)
    tl = rs.to_timeline([a, b, c])
    assert [f.t_ms for f in tl.frames] == [0, 60000]


# -------------------------- F10: frame times round, never truncate a ms

def test_f10_a_frame_time_rounds_to_the_nearest_ms():
    assert 1.001 * 1000 < 1001           # the float the old int() truncated
    s = rs.SeekSample(t_s=1.001, players=[rs.PlayerState(champion="Vi")])
    assert rs.to_timeline([s]).frames[0].t_ms == 1001


# ------------------------------- F11: a seek frame declares no position

def test_f11_seek_frames_declare_they_have_no_position():
    tl = rs.to_timeline(rs.sample_series(_Client(), [0.0, 30.0]))
    assert tl.frames
    assert all(f.has_position is False for f in tl.frames)


# --------------- F12: the interval is the sampling step, order-independent

def test_f12_an_unsorted_sweep_infers_the_real_step():
    out = rs.sample_series(_Client(), [60.0, 0.0, 30.0])
    assert rs.to_timeline(out).frame_interval_ms == 30000


def test_f12_a_duplicate_first_time_does_not_fall_back_to_60s():
    out = rs.sample_series(_Client(), [0.0, 0.0, 30.0])
    assert rs.to_timeline(out).frame_interval_ms == 30000


def test_f12_control_single_sample_and_even_sweep():
    assert rs.to_timeline(rs.sample_series(_Client(), [5.0])
                          ).frame_interval_ms == 60000
    assert rs.to_timeline(rs.sample_series(_Client(), [0.0, 15.0, 30.0])
                          ).frame_interval_ms == 15000


# -------------------------------- F13: to_timeline validates its input

@pytest.mark.parametrize("bad", [None, {"t_s": 1.0}, 5, "s"],
                         ids=["none", "dict", "int", "str"])
def test_f13_a_non_sample_is_a_type_error(bad):
    with pytest.raises(TypeError):
        rs.to_timeline([bad])


@pytest.mark.parametrize("t", [float("nan"), float("inf"), -1.0, True],
                         ids=["nan", "inf", "neg", "bool"])
def test_f13_a_sample_with_a_bad_time_is_refused(t):
    s = rs.SeekSample(t_s=t, players=[rs.PlayerState(champion="Vi")])
    with pytest.raises(ValueError):
        rs.to_timeline([s])


def test_f13_control_empty_input_is_an_empty_timeline():
    tl = rs.to_timeline([])
    assert tl.frames == [] and tl.positions_available is False
    assert not math.isnan(tl.frame_interval_ms)
