"""s144 true-audit regressions for core.live_metrics.

Each test pins one defect measured at the pre-fix HEAD:

  - a JSON string "false" (or 1, "no", [0]) in coach_settings.json turned
    capture ON, because the gate was bool(value);
  - a UTF-8 BOM (Notepad, PowerShell 5.1 Set-Content -Encoding UTF8) made the
    file unparseable, so capture went silently OFF with no log line at all;
  - an unreadable / non-object file was swallowed silently and the read was
    unbounded on a file re-read every coach tick;
  - one tick whose clock was missing or junk read as game_time 0.0, so the
    next real tick looked like a clock reset and minted a NEW synthetic match
    mid-game (the fresh MetricStreamer re-fires game_start and every passed
    min_mark under the new id);
  - an inf / negative clock poisoned the reset comparison the same way;
  - a transiently empty game_id (snapshot_normalizer drops it when the tick
    budget is spent) flipped a live_<id> match to a sess_ id and back,
    recreating the streamer twice and duplicating its milestone rows;
  - a bool / float / dict / sentinel / oversized game_id became a live_ key;
  - a non-str or oversized champion was formatted into the session id;
  - a persistent streamer fault was logged at DEBUG only, so a capture that
    recorded nothing all game left no trace at the default log level.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import live_metrics


class _FakeStreamer:
    created: list = []

    def __init__(self, *, match_id, champion=None, mode=None):
        self.match_id = match_id
        self.champion = champion
        self.mode = mode
        _FakeStreamer.created.append(self)

    def on_state(self, payload, **kw):
        return 1


class _Holder:
    pass


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _FakeStreamer.created = []
    monkeypatch.setattr(live_metrics, "_cfg_warned", False, raising=False)
    monkeypatch.setattr(live_metrics, "_stream_fault", None, raising=False)
    yield


def _cfg(monkeypatch, tmp_path, raw: bytes):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_bytes(raw)
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", cfg)
    return cfg


def _enable(monkeypatch):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: _FakeStreamer)


# ---------- config gate -----------------------------------------------------

@pytest.mark.parametrize("value", ["false", "0", "no", 1, [0], {"on": True}, "true"])
def test_only_json_true_enables_capture(monkeypatch, tmp_path, value):
    _cfg(monkeypatch, tmp_path, json.dumps({"live_metrics_enabled": value}).encode())
    assert live_metrics.enabled() is False


def test_json_true_still_enables(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path, b'{"live_metrics_enabled": true}')
    assert live_metrics.enabled() is True


def test_utf8_bom_config_is_read(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path, b'\xef\xbb\xbf{"live_metrics_enabled": true}')
    assert live_metrics.enabled() is True


def test_oversized_config_fails_closed(monkeypatch, tmp_path):
    pad = b" " * (live_metrics._CFG_MAX_BYTES + 1)
    _cfg(monkeypatch, tmp_path, b'{"live_metrics_enabled": true}' + pad)
    assert live_metrics.enabled() is False


def test_deeply_nested_config_fails_closed(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path, b"[" * 100000 + b"]" * 100000)
    assert live_metrics.enabled() is False


@pytest.mark.parametrize("raw", [b"{ not json", b"[1, 2]", b"\xff\xfe\x00junk"])
def test_broken_config_warns_once_per_streak(monkeypatch, tmp_path, caplog, raw):
    cfg = _cfg(monkeypatch, tmp_path, raw)
    caplog.set_level(logging.DEBUG, logger="rc.live_metrics")
    for _ in range(5):
        assert live_metrics.enabled() is False
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1
    assert "coach_settings.json" in warns[0].getMessage()
    assert str(tmp_path) not in warns[0].getMessage()
    # a good read ends the streak; the next breakage warns again
    cfg.write_bytes(b'{"live_metrics_enabled": true}')
    assert live_metrics.enabled() is True
    cfg.write_bytes(raw)
    assert live_metrics.enabled() is False
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 2


def test_absent_config_is_quiet(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", tmp_path / "absent.json")
    caplog.set_level(logging.DEBUG, logger="rc.live_metrics")
    assert live_metrics.enabled() is False
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------- game clock ------------------------------------------------------

@pytest.mark.parametrize("junk", [None, "abc", float("nan"), True, [], {}])
def test_one_unreadable_clock_tick_does_not_split_the_match(monkeypatch, junk):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 600, "champion": "Sona"}, {}, "aram")
    first = h._streamer.match_id
    live_metrics.stream(h, {"game_time_s": junk, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": 660, "champion": "Sona"}, {}, "aram")
    assert len(_FakeStreamer.created) == 1
    assert h._streamer.match_id == first


@pytest.mark.parametrize("bad", [float("inf"), -50.0, 10 ** 400, "1e400"])
def test_out_of_range_clock_is_ignored(monkeypatch, bad):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 600, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": bad, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": 660, "champion": "Sona"}, {}, "aram")
    assert len(_FakeStreamer.created) == 1


def test_huge_int_clock_does_not_blank_the_match_key():
    # float(10 ** 400) raises OverflowError, which used to escape the clock
    # parse and turn the whole match_key() into "".
    key = live_metrics.match_key(_Holder(), {"game_time_s": 10 ** 400,
                                             "champion": "Zed"}, {}, "aram")
    assert key.startswith("sess_aram_Zed_"), key


def test_clock_falls_through_a_zero_like_before(monkeypatch):
    # cur 0 falls through to state's clock (the old `or` chain), so a
    # state-carried clock still drives the reset detection.
    h = _Holder()
    k1 = live_metrics.match_key(h, {"game_time_s": 0}, {"game_seconds": 900}, "aram")
    k2 = live_metrics.match_key(h, {"game_time_s": 0}, {"game_seconds": 10}, "aram")
    assert k1 != k2


def test_a_real_clock_reset_still_mints(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 1400, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": None, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": 5, "champion": "Lux"}, {}, "aram")
    assert len(_FakeStreamer.created) == 2


# ---------- real game id ----------------------------------------------------

def test_transient_missing_game_id_keeps_the_live_match(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 600}, {"game_id": "1000000911"}, "sr")
    live_metrics.stream(h, {"game_time_s": 602}, {"game_id": ""}, "sr")
    live_metrics.stream(h, {"game_time_s": 604}, {"game_id": "1000000911"}, "sr")
    assert [s.match_id for s in _FakeStreamer.created] == ["live_1000000911"]


def test_missing_game_id_after_a_clock_reset_mints_a_session(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 1500}, {"game_id": "1000000911"}, "sr")
    live_metrics.stream(h, {"game_time_s": 4, "champion": "Zed"}, {}, "sr")
    assert h._streamer.match_id.startswith("sess_sr_Zed_")


@pytest.mark.parametrize("gid", [True, False, 1.5, float("nan"), {"a": 1}, [7],
                                 "-1", "000", " ", "a b", "x" * 65, "77\x007",
                                 10 ** 30, -5])
def test_junk_game_id_is_not_a_live_key(gid):
    h = _Holder()
    key = live_metrics.match_key(h, {"game_time_s": 60, "champion": "Zed"},
                                 {"game_id": gid}, "sr")
    assert key.startswith("sess_sr_Zed_"), key


@pytest.mark.parametrize("gid,want", [(1000000912, "live_1000000912"),
                                      (" 1000000913 ", "live_1000000913"),
                                      ("ABC", "live_ABC")])
def test_valid_game_ids_still_win(gid, want):
    assert live_metrics.match_key(_Holder(), {}, {"game_id": gid}, "sr") == want


def test_zero_game_id_falls_through_to_camel():
    key = live_metrics.match_key(_Holder(), {}, {"game_id": "0", "gameId": "42"}, "sr")
    assert key == "live_42"


# ---------- champion token --------------------------------------------------

@pytest.mark.parametrize("champ", [{"name": "Ahri"}, 7, "x" * 200, "Ahri\r\nX", ""])
def test_junk_champion_never_reaches_the_session_id(champ):
    key = live_metrics.match_key(_Holder(), {"champion": champ}, {}, "aram")
    assert key.startswith("sess_aram_champ_"), key


def test_spaced_and_apostrophe_champions_are_kept():
    assert live_metrics.match_key(_Holder(), {"champion": "Kai'Sa"}, {}, "aram") \
        .startswith("sess_aram_Kai'Sa_")
    assert live_metrics.match_key(_Holder(), {"champion": "Lee Sin"}, {}, "aram") \
        .startswith("sess_aram_Lee Sin_")


# ---------- stream fault visibility ----------------------------------------

def test_persistent_stream_fault_warns_once_per_streak(monkeypatch, caplog):
    state = {"boom": True}

    class _Flaky(_FakeStreamer):
        def on_state(self, payload, **kw):
            if state["boom"]:
                raise RuntimeError("db locked at C:\\secret\\path")
            return 1

    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: _Flaky)
    caplog.set_level(logging.DEBUG, logger="rc.live_metrics")
    h = _Holder()
    for t in range(4):
        assert live_metrics.stream(h, {"game_time_s": 60 + t}, {"game_id": "1"}, "sr") == 0
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1
    assert "RuntimeError" in warns[0].getMessage()
    assert "secret" not in warns[0].getMessage()
    state["boom"] = False
    assert live_metrics.stream(h, {"game_time_s": 70}, {"game_id": "1"}, "sr") == 1
    state["boom"] = True
    live_metrics.stream(h, {"game_time_s": 71}, {"game_id": "1"}, "sr")
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 2


def test_holder_streamer_without_match_id_is_replaced(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    h._streamer = object()
    assert live_metrics.stream(h, {"game_time_s": 60}, {"game_id": "9"}, "sr") == 1
    assert h._streamer.match_id == "live_9"
