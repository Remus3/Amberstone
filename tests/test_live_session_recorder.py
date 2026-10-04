"""RM-605 / X-05 (external reference F): live-session recorder.

Covers core/live_session_recorder.py:
  - default-OFF flag (RC_SESSION_RECORDER) and the liveclient_cache tap,
  - header-first JSONL whose header is capture CONFIG only, schema an int,
  - reader rejects a schema newer than it understands; an optional field
    added to a frame needs no bump,
  - a SINGLE writer thread keeps the JSONL well-formed under concurrent
    record() calls (Windows O_APPEND is not atomic, so many writers on one
    file is not safe).

Fixtures are synthetic: no real Riot IDs or summoner names.
"""
from __future__ import annotations

import json
import threading

import pytest

from core import live_session_recorder as lsr
from core import liveclient_cache


HEADER_FIELDS = {
    "config_key": "1920x1080|HUDScale=0.5",
    "patch": "99.1.1",
    "ENGINE_VERSION": "0.0.1-test",
    "mode_key": "aram",
}


def _snap(game_time: float, gold: float = 500.0) -> dict:
    return {
        "activePlayer": {"summonerName": "SyntheticPlayer#TEST", "currentGold": gold},
        "allPlayers": [{"championName": "Annie", "summonerName": "SyntheticPlayer#TEST"}],
        "gameData": {"gameMode": "ARAM", "gameTime": game_time},
        "events": {"Events": []},
    }


def _recorder(tmp_path, game_id="9000000001", vision=None):
    return lsr.LiveSessionRecorder(
        sessions_dir=tmp_path,
        header_fields=lambda snapshot: dict(HEADER_FIELDS),
        game_id_provider=lambda: game_id,
        vision_provider=(lambda: vision),
    )


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


@pytest.fixture(autouse=True)
def _clean_listeners():
    liveclient_cache.clear_listeners()
    lsr._reset_for_tests()
    yield
    liveclient_cache.clear_listeners()
    lsr._reset_for_tests()


# -- flag -------------------------------------------------------------------

def test_flag_default_off():
    assert lsr.is_enabled({}) is False
    assert lsr.is_enabled({"RC_SESSION_RECORDER": "0"}) is False
    assert lsr.is_enabled({"RC_SESSION_RECORDER": "garbage"}) is False
    for v in ("1", "true", "YES", "on"):
        assert lsr.is_enabled({"RC_SESSION_RECORDER": v}) is True


def test_install_registers_nothing_when_off(monkeypatch):
    monkeypatch.delenv("RC_SESSION_RECORDER", raising=False)
    assert lsr.install_if_enabled() is False
    assert liveclient_cache._listeners == []


def test_install_registers_listener_when_on(monkeypatch):
    monkeypatch.setenv("RC_SESSION_RECORDER", "1")
    assert lsr.install_if_enabled() is True
    assert lsr.on_liveclient_snapshot in liveclient_cache._listeners
    # idempotent
    assert lsr.install_if_enabled() is False
    assert liveclient_cache._listeners.count(lsr.on_liveclient_snapshot) == 1


def test_liveclient_cache_start_tap_is_flag_gated(monkeypatch):
    monkeypatch.delenv("RC_SESSION_RECORDER", raising=False)
    liveclient_cache._install_optional_taps()
    assert liveclient_cache._listeners == []
    monkeypatch.setenv("RC_SESSION_RECORDER", "1")
    liveclient_cache._install_optional_taps()
    assert lsr.on_liveclient_snapshot in liveclient_cache._listeners


def test_liveclient_cache_start_calls_the_tap(monkeypatch):
    calls = []
    monkeypatch.setattr(liveclient_cache, "_install_optional_taps", lambda: calls.append(1))
    monkeypatch.setattr(liveclient_cache, "_loop", lambda poll_s: None)
    monkeypatch.setattr(liveclient_cache, "_thread", None)
    monkeypatch.setattr(liveclient_cache, "_task", None)
    import app._loop as app_loop
    monkeypatch.setattr(app_loop, "get_loop", lambda: None)
    try:
        liveclient_cache.start()
    finally:
        liveclient_cache.stop()
    assert calls == [1]


def test_listener_records_nothing_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_SESSION_RECORDER", raising=False)
    rec = _recorder(tmp_path)
    lsr._set_recorder_for_tests(rec)
    lsr.on_liveclient_snapshot(liveclient_cache.Snapshot(data=_snap(10.0), ts=1.0))
    rec.flush()
    rec.close()
    assert list(tmp_path.iterdir()) == []


def test_listener_records_and_ends_on_no_game(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_SESSION_RECORDER", "1")
    rec = _recorder(tmp_path)
    lsr._set_recorder_for_tests(rec)
    lsr.on_liveclient_snapshot(liveclient_cache.Snapshot(data=_snap(10.0), ts=1.0))
    lsr.on_liveclient_snapshot(liveclient_cache.Snapshot(data=_snap(10.5), ts=1.5))
    lsr.on_liveclient_snapshot(liveclient_cache.Snapshot(data=None, no_game=True))
    rec.flush()
    rec.close()
    lines = _lines(tmp_path / "9000000001.jsonl")
    assert len(lines) == 3
    assert json.loads(lines[1])["source_ts"] == 1.0


# -- header -----------------------------------------------------------------

def test_header_is_first_line_and_config_only(tmp_path):
    rec = _recorder(tmp_path)
    for t in (1.0, 2.0, 3.0):
        rec.record(_snap(t))
    rec.flush()
    rec.close()
    lines = _lines(tmp_path / "9000000001.jsonl")
    header = json.loads(lines[0])
    assert header["kind"] == "header"
    assert type(header["schema"]) is int and header["schema"] == lsr.SCHEMA_VERSION
    # The header describes the capture config, never results: exactly these keys.
    assert set(header) == {"kind", "schema", "config_key", "patch", "ENGINE_VERSION", "mode_key"}
    for k, v in HEADER_FIELDS.items():
        assert header[k] == v
    assert [json.loads(x)["kind"] for x in lines[1:]] == ["frame"] * 3


def test_header_drops_non_config_fields(tmp_path):
    rec = lsr.LiveSessionRecorder(
        sessions_dir=tmp_path,
        header_fields=lambda s: dict(HEADER_FIELDS, win=True, frames=3, schema=7),
        game_id_provider=lambda: "9000000002",
        vision_provider=lambda: None,
    )
    rec.record(_snap(1.0))
    rec.flush()
    rec.close()
    header = json.loads(_lines(tmp_path / "9000000002.jsonl")[0])
    assert "win" not in header and "frames" not in header
    assert header["schema"] == lsr.SCHEMA_VERSION


def test_default_header_fields_shape():
    fields = lsr.default_header_fields(_snap(1.0))
    assert set(fields) == {"config_key", "patch", "ENGINE_VERSION", "mode_key"}
    assert fields["mode_key"] == "aram"
    assert isinstance(fields["ENGINE_VERSION"], str) and fields["ENGINE_VERSION"]


# -- reader / schema --------------------------------------------------------

def _write(path, header, frames):
    path.write_text(
        "\n".join(json.dumps(x) for x in [header] + frames) + "\n", encoding="utf-8"
    )


def _hdr(schema):
    return dict(HEADER_FIELDS, kind="header", schema=schema)


def test_reader_rejects_schema_too_new(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, _hdr(lsr.SCHEMA_VERSION + 1), [])
    with pytest.raises(lsr.SchemaTooNewError):
        lsr.read_session(p)


@pytest.mark.parametrize("bad", ["1", True, 1.0, None])
def test_reader_rejects_non_int_schema(tmp_path, bad):
    p = tmp_path / "s.jsonl"
    _write(p, _hdr(bad), [])
    with pytest.raises(lsr.SessionFormatError):
        lsr.read_session(p)


def test_reader_requires_header_first(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"kind": "frame", "seq": 0, "snapshot": {}}) + "\n", encoding="utf-8")
    with pytest.raises(lsr.SessionFormatError):
        lsr.read_session(p)


def test_optional_field_needs_no_bump(tmp_path):
    p = tmp_path / "s.jsonl"
    frame = {"kind": "frame", "seq": 0, "captured_at": 1.0, "snapshot": {"a": 1},
             "some_future_optional_field": {"x": 1}}
    _write(p, dict(_hdr(lsr.SCHEMA_VERSION), some_future_header_field="y"), [frame])
    header, frames = lsr.read_session(p)
    assert frames[0]["snapshot"] == {"a": 1}


def test_reader_tolerates_torn_final_line_only(tmp_path):
    p = tmp_path / "s.jsonl"
    good = {"kind": "frame", "seq": 0, "captured_at": 1.0, "snapshot": {}}
    p.write_text(json.dumps(_hdr(1)) + "\n" + json.dumps(good) + "\n" + '{"kind": "fra',
                 encoding="utf-8")
    _, frames = lsr.read_session(p)
    assert len(frames) == 1
    p.write_text(json.dumps(_hdr(1)) + "\n" + '{"kind": "fra\n' + json.dumps(good) + "\n",
                 encoding="utf-8")
    with pytest.raises(lsr.SessionFormatError):
        lsr.read_session(p)


# -- single writer ----------------------------------------------------------

def test_concurrent_record_yields_well_formed_jsonl(tmp_path):
    rec = _recorder(tmp_path)
    n_threads, per = 8, 250
    barrier = threading.Barrier(n_threads)

    def worker(i):
        barrier.wait()
        for k in range(per):
            rec.record(_snap(1.0 + k * 0.001, gold=float(i * 10000 + k)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rec.flush()
    rec.close()
    lines = _lines(tmp_path / "9000000001.jsonl")
    assert len(lines) == 1 + n_threads * per
    parsed = [json.loads(x) for x in lines]
    assert parsed[0]["kind"] == "header"
    assert sum(1 for x in parsed if x.get("kind") == "header") == 1
    seqs = [x["seq"] for x in parsed[1:]]
    assert seqs == list(range(n_threads * per))
    golds = sorted(x["snapshot"]["activePlayer"]["currentGold"] for x in parsed[1:])
    assert golds == sorted(float(i * 10000 + k) for i in range(n_threads) for k in range(per))
    header, frames = lsr.read_session(tmp_path / "9000000001.jsonl")
    assert len(frames) == n_threads * per


def test_writer_thread_is_the_only_file_owner(tmp_path, monkeypatch):
    rec = _recorder(tmp_path)
    opened_by = []
    real_open = lsr._open_append

    def spy(path):
        opened_by.append(threading.current_thread().name)
        return real_open(path)

    monkeypatch.setattr(lsr, "_open_append", spy)
    rec.record(_snap(1.0))
    rec.flush()
    rec.close()
    assert opened_by == [lsr.WRITER_THREAD_NAME]


# -- sessions / ids ---------------------------------------------------------

def test_unsafe_game_id_falls_back_inside_dir(tmp_path):
    rec = _recorder(tmp_path, game_id="../../evil")
    rec.record(_snap(1.0))
    rec.flush()
    rec.close()
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].parent == tmp_path
    assert files[0].name.startswith("nogameid-")


def test_game_time_rewind_starts_new_session(tmp_path):
    ids = iter(["9000000010", "9000000011"])
    rec = lsr.LiveSessionRecorder(
        sessions_dir=tmp_path,
        header_fields=lambda s: dict(HEADER_FIELDS),
        game_id_provider=lambda: next(ids),
        vision_provider=lambda: None,
    )
    rec.record(_snap(600.0))
    rec.record(_snap(601.0))
    rec.record(_snap(2.0))
    rec.flush()
    rec.close()
    assert len(_lines(tmp_path / "9000000010.jsonl")) == 3
    assert len(_lines(tmp_path / "9000000011.jsonl")) == 2


def test_vision_state_attached_when_available(tmp_path):
    rec = _recorder(tmp_path, vision={"enemies": [{"visible": False}]})
    rec.record(_snap(1.0))
    rec.flush()
    rec.close()
    frame = json.loads(_lines(tmp_path / "9000000001.jsonl")[1])
    assert frame["vision_state"] == {"enemies": [{"visible": False}]}


def test_vision_state_absent_is_omitted(tmp_path):
    rec = _recorder(tmp_path, vision=None)
    rec.record(_snap(1.0))
    rec.flush()
    rec.close()
    frame = json.loads(_lines(tmp_path / "9000000001.jsonl")[1])
    assert "vision_state" not in frame


def test_snapshot_content_is_captured_at_record_time(tmp_path):
    rec = _recorder(tmp_path)
    s = _snap(1.0)
    rec.record(s)
    s["gameData"]["gameTime"] = 999.0   # caller mutates after handing it over
    rec.flush()
    rec.close()
    frame = json.loads(_lines(tmp_path / "9000000001.jsonl")[1])
    assert frame["snapshot"]["gameData"]["gameTime"] == 1.0
