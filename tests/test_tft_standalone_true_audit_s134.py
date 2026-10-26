"""True-audit s134 cycle 9: tft/tft_standalone.py, the live standalone TFT
source, under merely WRONG input from the per-round file
(TFTEoGStats.json) and the machine environment.

One test per finding (S1-S7 in the cycle report). The module's own contract
is "every function is fail-soft: a probe error reads as no standalone game,
never an exception into a poll loop" - and, sharper, ONE bad field must cost
that field, never the whole live game: synth_allgamedata swallowing a raise
returns None, which the poller reads as "no TFT game" for every tick the
file stands.
"""
from __future__ import annotations

import json
import time

import pytest

from tft import tft_standalone as ts

GID = "1000000911"
LCU = {"phase": "InProgress", "game_queue_mode": "TFT", "game_id": GID}
HUGE = 10 ** 400  # a JSON integer float() cannot hold (OverflowError)


def _eog(**sb_extra):
    sb = {
        "gameLengthSeconds": 828,
        "setCoreName": "TFTSet18",
        "players": [
            {"isInteractable": False, "health": 92, "ffaStanding": 3,
             "boardPieces": [{"championName": "DA_18_Rakan", "starLevel": 2,
                              "itemNames": []}]},
            {"isInteractable": True, "health": 74, "ffaStanding": 2,
             "boardPieces": [{"championName": "DA_18_Yorick", "starLevel": 2,
                              "itemNames": ["TFT_Item_A"]}]},
            {"isInteractable": False, "health": 0, "ffaStanding": 8,
             "boardPieces": []},
        ],
    }
    sb.update(sb_extra)
    return {"gameId": int(GID), "gameMode": "TFT", "queueId": 1090,
            "statsBlock": sb, "_mtime": time.time() - 5.0}


def _synth(eog, now=None):
    return ts.synth_allgamedata(lcu=LCU, running=True, eog=eog,
                                now=time.time() if now is None else now)


@pytest.fixture(autouse=True)
def _clear_caches():
    ts._reset_caches_for_tests()
    yield
    ts._reset_caches_for_tests()


def test_baseline_shape_serves_the_game():
    raw = _synth(_eog())
    assert raw is not None
    assert raw["rc_standalone"]["local"]["standing"] == 2


# -- S1: a number float() cannot hold costs the field, never the game --------

def test_int_huge_json_integer_is_the_default():
    assert ts._int(HUGE) == 0
    assert ts._int(HUGE, 1) == 1
    assert ts._int(-HUGE, 7) == 7


@pytest.mark.parametrize("where", ["opponent_standing", "local_standing",
                                   "star", "game_length"])
def test_synth_survives_a_huge_integer_field(where):
    eog = _eog()
    players = eog["statsBlock"]["players"]
    if where == "opponent_standing":
        players[0]["ffaStanding"] = HUGE
    elif where == "local_standing":
        players[1]["ffaStanding"] = HUGE
    elif where == "star":
        players[1]["boardPieces"][0]["starLevel"] = HUGE
    else:
        eog["statsBlock"]["gameLengthSeconds"] = HUGE
    raw = _synth(eog)
    assert raw is not None, "one bad field dropped the whole live game"
    st = raw["rc_standalone"]
    assert st["eog"] is True and st["local_index"] == 1
    if where == "opponent_standing":
        assert any(r["standing"] is None for r in st["lobby"])
    if where == "local_standing":
        assert st["local"]["standing"] is None
    if where == "star":
        assert st["local"]["board"][0]["star"] == 1


def test_live_status_never_raises_on_a_huge_integer_field():
    eog = _eog()
    eog["statsBlock"]["players"][0]["ffaStanding"] = HUGE
    out = ts.tft_live_status(LCU, running=True, eog=eog)
    assert out["source"] == ts.SOURCE_TAG and out["eog"] is True


# -- S2: read_eog keeps its own "else None" contract -------------------------

def _file(tmp_path, monkeypatch, text):
    p = tmp_path / "TFTEoGStats.json"
    p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ts, "eog_stats_path", lambda: p)
    return p


def test_read_eog_deep_nest_is_none(tmp_path, monkeypatch):
    # json raises RecursionError (not a ValueError) on a deep nest
    _file(tmp_path, monkeypatch, "[" * 200000)
    assert ts.read_eog(now=time.time()) is None


def test_read_eog_oversize_file_is_not_read(tmp_path, monkeypatch):
    doc = _eog()
    doc["pad"] = "x" * (ts.EOG_MAX_BYTES + 10)
    _file(tmp_path, monkeypatch, json.dumps(doc))
    assert ts.read_eog(now=time.time()) is None


def test_read_eog_cap_is_at_least_the_poller_cap():
    from tft.sources import eog_file
    assert ts.EOG_MAX_BYTES >= eog_file.MAX_EOG_BYTES


def test_read_eog_normal_file_still_reads(tmp_path, monkeypatch):
    _file(tmp_path, monkeypatch, json.dumps(_eog()))
    d = ts.read_eog(now=time.time())
    assert d is not None and str(d["gameId"]) == GID


# -- S3: a game clock the file cannot vouch for is unknown, never 0 ----------

@pytest.mark.parametrize("bad", [None, "junk", -50, True, 1e12, float("nan")])
def test_bad_game_length_is_unknown_not_zero(bad, monkeypatch):
    eog = _eog()
    if bad is None:
        del eog["statsBlock"]["gameLengthSeconds"]
    else:
        eog["statsBlock"]["gameLengthSeconds"] = bad
    now = time.time()
    # the TFT process has run 25 min: that is the clock to fall back on
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 1500.0)
    raw = _synth(eog, now=now)
    st = raw["rc_standalone"]
    assert st["game_length_s"] is None
    assert st["as_of_game_s"] is None
    assert raw["gameData"]["gameTime"] == pytest.approx(1500.0, abs=1.0)


def test_good_game_length_still_drives_the_clock():
    raw = _synth(_eog(gameLengthSeconds=650))
    assert raw["rc_standalone"]["game_length_s"] == 650
    assert raw["gameData"]["gameTime"] == pytest.approx(655.0, abs=1.5)


def test_zero_game_length_is_a_real_value():
    raw = _synth(_eog(gameLengthSeconds=0))
    assert raw["rc_standalone"]["game_length_s"] == 0


# -- S4: queueId / setCoreName are typed before they are served --------------

@pytest.mark.parametrize("qid,want", [
    (1090, 1090), ("1090", 1090), ({"x": 1}, None), ([1090], None),
    (True, None), (-5, None), ("abc", None), (None, None),
])
def test_queue_id_is_an_int_or_none(qid, want):
    eog = _eog()
    eog["queueId"] = qid
    raw = _synth(eog)
    assert raw["gameData"]["queueId"] == want
    assert raw["rc_standalone"]["queue_id"] == want


@pytest.mark.parametrize("val,want", [
    ("TFTSet18", "TFTSet18"), ({"a": 1}, None), (18, None), ("", None),
    ("TFTSet18\u00e9", "TFTSet18"), ("S" * 200, "S" * 40),
])
def test_set_name_is_a_short_ascii_string_or_none(val, want):
    raw = _synth(_eog(setCoreName=val))
    assert raw["rc_standalone"]["set"] == want


# -- S5: the per-round path is absolute even with no LOCALAPPDATA ------------

def _real_eog_stats_path():
    """The module's own eog_stats_path: tests/conftest patches the attribute
    on the imported module (so no test reads the operator's real file), so
    load a private copy of the module to reach the unpatched function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ts_fresh_s134t9", ts.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.eog_stats_path


def test_eog_path_absolute_without_localappdata(monkeypatch):
    monkeypatch.delenv("RC_TFT_EOG_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "")
    p = _real_eog_stats_path()()
    assert p.is_absolute(), p
    assert p.parts[-4:] == ("TFT", "Saved", "Logs", "TFTEoGStats.json")


def test_eog_path_uses_localappdata_when_set(monkeypatch, tmp_path):
    monkeypatch.delenv("RC_TFT_EOG_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _real_eog_stats_path()() == tmp_path / "TFT" / "Saved" / "Logs" / "TFTEoGStats.json"


# -- S6: unit names are ASCII and bounded, like item names -------------------

@pytest.mark.parametrize("raw,want", [
    ("DA_18_Yorick\u00e9", "Yorick"),
    ("DA_18_" + "Z" * 300, "Z" * 40),
    ("DA_18", "DA_18"),
])
def test_clean_unit_name_ascii_and_bounded(raw, want):
    assert ts.clean_unit_name(raw) == want


# -- S7: a junk file stamp or a non-dict file never raises -------------------

def test_junk_mtime_is_an_unknown_age_not_a_raise():
    eog = _eog()
    eog["_mtime"] = "yesterday"
    raw = _synth(eog)
    assert raw is not None and raw["rc_standalone"]["eog"] is True
    assert raw["rc_standalone"]["eog_age_s"] is None


@pytest.mark.parametrize("lcu", [None, {"game_id": GID}])
@pytest.mark.parametrize("bad", [["not", "a", "dict"], "text", 5])
def test_standalone_in_game_non_dict_file_is_no_file(lcu, bad):
    # no LCU verdict: only a per-round file can confirm, and junk is no file
    assert ts.standalone_in_game(lcu, running=True, eog=bad) is False
