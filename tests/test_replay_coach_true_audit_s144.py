"""True-audit (s144, lane 8) of coaches/replay_coach.py.

One test per confirmed finding, each red on the pre-audit file:

F1  the Anthropic client was built per call and never closed (a connection
    pool leaked per call) and kept the SDK default max_retries=2, so one call
    could block for three 20 s timeouts plus backoff and bill attempts
    cost_tracker never sees.
F2  _load_match opened the database read-WRITE: if the file vanished between
    the exists() check and connect(), sqlite3 created an empty database at the
    live path.
F3  a non-integer numeric column (SQLite is dynamically typed) made
    _format_for_prompt raise OUTSIDE the try, so analyze_match raised instead
    of returning its documented dict; a mixed-type timestamp column made the
    loader report the match as "not in rewind_history.db".
F4  match_id was never validated and was echoed verbatim into the
    user-facing summary.
F5  every parsed body was cut to 300 chars before the summary's own 600 cap,
    so the summary cap was dead code and a normal paragraph was truncated.
F6  only content[0] was read: a reply whose first block is not text degraded
    to "coaching unavailable" although a text block was present.
F7  a whitespace-only key was treated as present and sent to the API.

The anthropic module and cost_tracker are stubbed: no network, no live write.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

from coaches import replay_coach as mod

_COLS_EV = ("match_id", "timestamp_ms", "event_type")


def _db(tmp_path: Path, *, match_row: dict, events: list[tuple]) -> Path:
    path = tmp_path / "rewind.db"
    conn = sqlite3.connect(path)
    cols = ", ".join(match_row)
    conn.execute(f"CREATE TABLE matches ({cols})")
    conn.execute(
        f"INSERT INTO matches ({cols}) VALUES ({', '.join('?' * len(match_row))})",
        tuple(match_row.values()))
    conn.execute("CREATE TABLE participants (match_id, champion_name, team_id, "
                 "lane, champ_level)")
    conn.execute("INSERT INTO participants VALUES ('M1', 'Ahri', 100, 'MID', 12)")
    conn.execute("CREATE TABLE timeline_events (match_id, timestamp_ms, event_type)")
    conn.executemany("INSERT INTO timeline_events VALUES (?, ?, ?)", events)
    conn.commit()
    conn.close()
    return path


_GOOD_MATCH = {"match_id": "M1", "tracked_champion_name": "Ahri",
               "tracked_win": 1, "game_duration_s": 1320, "patch": "25.1",
               "game_mode": "CLASSIC", "tracked_kills": 5,
               "tracked_deaths": 2, "tracked_assists": 7}

_REPLY = ("Summary: You won.\nMoment 1: 3:10 - first blood\n"
          "Suggestion 1: ward more")


class _Block:
    def __init__(self, text: str | None, btype: str = "text"):
        self.type = btype
        if text is not None:
            self.text = text


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        _FakeClient.instances.append(self)
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        if _FakeClient.next_raise is not None:
            raise _FakeClient.next_raise
        return types.SimpleNamespace(content=list(_FakeClient.next_content),
                                     stop_reason="end_turn")

    def close(self):
        self.closed = True

    next_raise: BaseException | None = None
    next_content: list = []


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    _FakeClient.instances = []
    _FakeClient.next_raise = None
    _FakeClient.next_content = [_Block(_REPLY)]
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    import core.cost_tracker as ct
    monkeypatch.setattr(ct, "record_anthropic_response",
                        lambda *a, **k: None)
    events = [("M1", 190_000, "CHAMPION_KILL"), ("M1", 600_000, "BUILDING_KILL")]
    monkeypatch.setattr(mod, "_REWIND_DB",
                        _db(tmp_path, match_row=_GOOD_MATCH, events=events))
    return _FakeClient


# --- F1 client lifecycle -----------------------------------------------------

def test_f1_client_is_closed_after_a_successful_call(fake_api):
    out = mod.analyze_match("M1", api_key="sk-test")
    assert out["ok"] is True
    assert len(fake_api.instances) == 1
    assert fake_api.instances[0].closed is True


def test_f1_client_is_closed_after_a_failed_call(fake_api):
    fake_api.next_raise = RuntimeError("boom 400 credit balance")
    out = mod.analyze_match("M1", api_key="sk-test")
    assert out["ok"] is False
    assert fake_api.instances[0].closed is True
    assert "credit" not in out["summary"] and "boom" not in out["summary"]


def test_f1_sdk_retries_are_disabled(fake_api):
    mod.analyze_match("M1", api_key="sk-test")
    assert fake_api.instances[0].kwargs.get("max_retries") == 0


# --- F2 read-only open -------------------------------------------------------

class _VanishingPath(type(Path())):
    """exists() says yes, but the file is not there - the TOCTOU window."""

    def exists(self, *a, **k):  # noqa: D401
        return True


def test_f2_loader_never_creates_the_database(tmp_path, monkeypatch):
    target = _VanishingPath(tmp_path / "gone.db")
    monkeypatch.setattr(mod, "_REWIND_DB", target)
    assert mod._load_match("M1") is None
    assert not Path(tmp_path / "gone.db").exists()


def test_f2_loader_still_reads_an_existing_database(fake_api):
    blob = mod._load_match("M1")
    assert blob is not None
    assert [e["event_type"] for e in blob["events"]] == [
        "CHAMPION_KILL", "BUILDING_KILL"]


# --- F3 malformed numeric columns --------------------------------------------

def test_f3_text_duration_does_not_raise_out_of_analyze_match(fake_api, tmp_path,
                                                             monkeypatch):
    bad = dict(_GOOD_MATCH, game_duration_s="1320", tracked_kills=None)
    events = [("M1", "190000", "CHAMPION_KILL"), ("M1", None, "BUILDING_KILL"),
              ("M1", -5000, "WARD_PLACED"), ("M1", 12.7, "ITEM_PURCHASED")]
    sub = tmp_path / "bad"
    sub.mkdir()
    monkeypatch.setattr(mod, "_REWIND_DB", _db(sub, match_row=bad, events=events))
    out = mod.analyze_match("M1", api_key="sk-test")
    assert out["ok"] is True


def test_f3_mixed_type_timestamps_still_load(tmp_path, monkeypatch):
    events = [("M1", "abc", "CHAMPION_KILL"), ("M1", 5000, "BUILDING_KILL")]
    monkeypatch.setattr(mod, "_REWIND_DB",
                        _db(tmp_path, match_row=_GOOD_MATCH, events=events))
    blob = mod._load_match("M1")
    assert blob is not None
    assert len(blob["events"]) == 2


def test_f3_format_tolerates_junk_values():
    blob = {"match": {"game_duration_s": "x", "tracked_kills": [1]},
            "participants": [{"champion_name": None, "champ_level": "9"}],
            "events": [{"event_type": None, "timestamp_ms": "nope"},
                       {"event_type": "CHAMPION_KILL", "timestamp_ms": -1000}]}
    text = mod._format_for_prompt(blob)
    assert "0 min" in text
    assert "-" not in text.split("Timeline samples:")[1].replace("\n  ", "\n")


# --- F4 match_id validation --------------------------------------------------

@pytest.mark.parametrize("bad", [None, 123, "", "   ", "a" * 65,
                                 "<img src=x onerror=alert(1)>", "M1; DROP"])
def test_f4_invalid_match_id_is_refused_without_echo(fake_api, bad):
    out = mod.analyze_match(bad, api_key="sk-test")
    assert out["ok"] is False
    assert out["summary"] == "(invalid match id)"
    assert fake_api.instances == []


def test_f4_unknown_valid_id_does_not_echo_the_id(fake_api):
    out = mod.analyze_match("NA1_999", api_key="sk-test")
    assert out["ok"] is False
    assert "NA1_999" not in out["summary"]


# --- F5 summary cap ----------------------------------------------------------

def test_f5_summary_keeps_up_to_600_chars():
    para = "x" * 500
    assert mod._parse_response(f"Summary: {para}")["summary"] == para
    assert len(mod._parse_response("Summary: " + "y" * 900)["summary"]) == 600


def test_f5_moments_stay_capped_at_300():
    out = mod._parse_response("Moment 1: " + "z" * 500)
    assert out["key_moments"] == ["z" * 300]


# --- F6 non-text first block -------------------------------------------------

def test_f6_text_after_a_non_text_block_is_used(fake_api):
    fake_api.next_content = [_Block(None, btype="thinking"), _Block(_REPLY)]
    out = mod.analyze_match("M1", api_key="sk-test")
    assert out["ok"] is True
    assert out["summary"] == "You won."


# --- F7 whitespace key -------------------------------------------------------

@pytest.mark.parametrize("key", ["   ", "\n", 42])
def test_f7_unusable_key_is_treated_as_missing(fake_api, key):
    out = mod.analyze_match("M1", api_key=key)
    assert out["summary"] == "(API key missing - coach disabled)"
    assert fake_api.instances == []
