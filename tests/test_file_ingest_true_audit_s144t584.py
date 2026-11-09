"""S144-T-584 - lane 8 true audit of agents/agent2_backend/file_ingest.py.

FileIngest is the supervisor's :8891 /push feed: it polls health.json and the
coaching JSON files every 0.5 s and broadcasts each change. Measured defects
this file pins (each test was RED against the pre-fix module):

1. The change signature was recorded BEFORE the broadcast, so a broadcast that
   raised lost that update for good (the file was "unchanged" on every later
   tick) and skipped the mode-transition hook with it.
2. One source raising anything but OSError on stat aborted the whole tick, so
   every file after it (all coaching files, when health.json raised) was never
   broadcast while the fault lasted.
3. The 128 KB cap was checked on stat only; the read was unbounded, so a file
   that grew between stat and read was read and broadcast whole.
4. A corrupt or oversize file logged a WARNING on every 0.5 s tick, forever
   (7200 lines an hour).
5. json.loads accepts NaN / Infinity / -Infinity and turns 1e999 into inf;
   broadcast_push re-emits them as bare NaN / Infinity, which the dashboard's
   JSON.parse (web/js/main.js, the /push onmessage) rejects, so the WHOLE
   envelope was dropped silently.
6. A 5000-digit integer (ValueError) or deep nesting (RecursionError) escaped
   the (JSONDecodeError, OSError, UnicodeDecodeError) catch and aborted the tick.
7. Change detection compared float st_mtime only, so a rewrite with a different
   size but the same mtime was never broadcast.
8. A UTF-8 BOM (a PowerShell writer) made every read a JSONDecodeError.
9. _compute_effective_mode str()-ed a non-str health.mode, so mode=True read as
   "true" and fired a bogus mode transition.

Coroutines run through tests._asyncio_isolation.run_coro (fresh loop on a fresh
thread), never IsolatedAsyncioTestCase - see test_file_ingest_mirror.py.
"""
from __future__ import annotations

import json
import logging
import os

import pytest

from agents.agent2_backend import file_ingest as fi
from tests._asyncio_isolation import run_coro


class _WS:
    """Captures envelopes; raises on the first ``fail_first`` calls."""

    def __init__(self, fail_first: int = 0) -> None:
        self.sent: list[dict] = []
        self.calls = 0
        self._fail_first = fail_first

    async def broadcast_push(self, env: dict) -> None:
        self.calls += 1
        if self.calls <= self._fail_first:
            raise RuntimeError("synthetic fanout failure")
        self.sent.append(env)


@pytest.fixture(autouse=True)
def _no_lcu(monkeypatch):
    # Never reach a real LCU from a test: the preflip mirror sees no lobby.
    monkeypatch.setattr(fi, "_lcu_summary", lambda: {"phase": "None"})


def _check(ingest: fi.FileIngest, path, source="aram_coaching_data.json",
           envelope_type="state") -> None:
    run_coro(ingest._check_one(path, source, mode="aram",
                               envelope_type=envelope_type))


def _warnings_for(caplog, source: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == "agent2.file_ingest"
            and r.levelno >= logging.WARNING
            and source in r.getMessage()]


# 1 -------------------------------------------------------------------------

def test_broadcast_failure_does_not_lose_the_update(tmp_path):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text('{"action": "push"}', encoding="utf-8")
    ws = _WS(fail_first=1)
    ingest = fi.FileIngest(ws)
    _check(ingest, p)          # fanout raises; must not propagate
    _check(ingest, p)          # file unchanged; the update must still go out
    assert [e["payload"] for e in ws.sent] == [{"action": "push"}]
    _check(ingest, p)          # delivered now, so no duplicate
    assert len(ws.sent) == 1


def test_mode_transition_fires_even_when_broadcast_fails(tmp_path):
    p = tmp_path / "health.json"
    seen: list[tuple] = []
    ws = _WS()
    ingest = fi.FileIngest(ws, on_mode_transition=lambda a, b: seen.append((a, b)))
    p.write_text('{"mode": "client"}', encoding="utf-8")
    _check(ingest, p, "health", "health")
    ws._fail_first = ws.calls + 1          # the next fanout raises
    p.write_text('{"mode": "in_progress", "pad": 1}', encoding="utf-8")
    _check(ingest, p, "health", "health")
    assert seen == [("client", "in_progress")]
    _check(ingest, p, "health", "health")  # retry delivers, no second hook
    assert seen == [("client", "in_progress")]
    assert ws.sent[-1]["payload"]["mode"] == "in_progress"


# 2 -------------------------------------------------------------------------

def test_one_raising_source_does_not_starve_the_rest(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    health.write_text('{"mode": "client"}', encoding="utf-8")
    good = tmp_path / "tft_coaching_data.json"
    good.write_text('{"board": 1}', encoding="utf-8")
    monkeypatch.setattr(fi, "HEALTH_PATH", health)
    monkeypatch.setattr(fi, "WATCHED", (("tft_coaching_data.json", good, "tft"),))
    real_stat = fi._stat_blocking

    def stat(path):
        if path == health:
            raise RuntimeError("synthetic stat bug")
        return real_stat(path)

    monkeypatch.setattr(fi, "_stat_blocking", stat)
    ws = _WS()
    run_coro(fi.FileIngest(ws)._tick())
    assert [e["source"] for e in ws.sent] == ["tft_coaching_data.json"]


# 3 -------------------------------------------------------------------------

def test_read_is_bounded_even_when_the_file_grew_after_stat(tmp_path, monkeypatch):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text(json.dumps({"k": "a" * (fi.MAX_PAYLOAD_BYTES + 10)}),
                 encoding="utf-8")
    real_stat = fi._stat_blocking

    def small_stat(path):
        st = real_stat(path)
        fields = list(st)
        fields[6] = 10                       # st_size as seen at stat time
        return os.stat_result(fields)

    monkeypatch.setattr(fi, "_stat_blocking", small_stat)
    ws = _WS()
    _check(fi.FileIngest(ws), p)
    assert ws.sent == []


def test_read_helper_refuses_past_the_cap(tmp_path):
    p = tmp_path / "big.json"
    p.write_bytes(b"[" + b"0," * fi.MAX_PAYLOAD_BYTES + b"0]")
    with pytest.raises(fi.PayloadTooLarge):
        fi._read_text_blocking(p)
    q = tmp_path / "ok.json"
    q.write_bytes(b'{"a": 1}')
    assert fi._read_text_blocking(q) == '{"a": 1}'


# 4 -------------------------------------------------------------------------

def test_corrupt_file_warns_once_per_version(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="agent2.file_ingest")
    p = tmp_path / "aram_coaching_data.json"
    p.write_text('{"broken": ', encoding="utf-8")
    ws = _WS()
    ingest = fi.FileIngest(ws)
    for _ in range(5):
        _check(ingest, p)
    assert len(_warnings_for(caplog, "aram_coaching_data.json")) == 1
    assert ws.sent == []
    p.write_text('{"fixed": true}', encoding="utf-8")
    _check(ingest, p)
    assert [e["payload"] for e in ws.sent] == [{"fixed": True}]
    p.write_text('{"broken again": ', encoding="utf-8")
    _check(ingest, p)
    _check(ingest, p)
    assert len(_warnings_for(caplog, "aram_coaching_data.json")) == 2


def test_oversize_file_warns_once(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="agent2.file_ingest")
    p = tmp_path / "aram_coaching_data.json"
    p.write_bytes(b" " * (fi.MAX_PAYLOAD_BYTES + 1))
    ingest = fi.FileIngest(_WS())
    for _ in range(5):
        _check(ingest, p)
    assert len(_warnings_for(caplog, "aram_coaching_data.json")) == 1


# 5 -------------------------------------------------------------------------

def test_non_finite_numbers_become_null_so_the_envelope_is_strict_json(tmp_path):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text('{"a": NaN, "b": Infinity, "c": -Infinity, "d": 1e999,'
                 ' "e": -1e999, "f": 1.5, "g": [NaN, 2]}', encoding="utf-8")
    ws = _WS()
    _check(fi.FileIngest(ws), p)
    assert ws.sent[0]["payload"] == {"a": None, "b": None, "c": None,
                                     "d": None, "e": None, "f": 1.5,
                                     "g": [None, 2]}
    json.dumps(ws.sent[0], allow_nan=False)   # what JSON.parse accepts


# 6 -------------------------------------------------------------------------

@pytest.mark.parametrize("body", ["1" * 5000, "[" * 100000],
                         ids=["int-digit-limit", "deep-nesting"])
def test_hostile_json_is_a_parse_failure_not_a_tick_abort(tmp_path, body):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text(body, encoding="utf-8")
    ws = _WS()
    _check(fi.FileIngest(ws), p)               # must not raise
    assert ws.sent == []


# 7 -------------------------------------------------------------------------

def test_rewrite_with_same_mtime_but_new_size_is_broadcast(tmp_path):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text('{"v": 1}', encoding="utf-8")
    st = os.stat(p)
    ws = _WS()
    ingest = fi.FileIngest(ws)
    _check(ingest, p)
    p.write_text('{"v": 22}', encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    _check(ingest, p)
    assert [e["payload"] for e in ws.sent] == [{"v": 1}, {"v": 22}]


# 8 -------------------------------------------------------------------------

def test_utf8_bom_is_accepted(tmp_path):
    p = tmp_path / "aram_coaching_data.json"
    p.write_bytes(b'\xef\xbb\xbf{"action": "x"}')
    ws = _WS()
    _check(fi.FileIngest(ws), p)
    assert [e["payload"] for e in ws.sent] == [{"action": "x"}]


# 9 -------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [True, 1, {"x": 1}, ["game"]])
def test_non_str_health_mode_is_no_mode(mode):
    assert fi.FileIngest._compute_effective_mode({"mode": mode}, None) is None


def test_non_str_lcu_phase_is_ignored():
    assert fi.FileIngest._compute_effective_mode(
        {"mode": "client"}, ["ChampSelect"]) == "client"


def test_effective_mode_characterization():
    f = fi.FileIngest._compute_effective_mode
    assert f({"mode": "IN_PROGRESS"}, "ChampSelect") == "in_progress"
    assert f({"mode": "client"}, "ChampSelect") == "champ_select"
    assert f({"mode": "client"}, "GameStart") == "game"
    assert f({}, None) is None


def test_unchanged_file_is_broadcast_once(tmp_path):
    p = tmp_path / "aram_coaching_data.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    ws = _WS()
    ingest = fi.FileIngest(ws)
    for _ in range(3):
        _check(ingest, p)
    assert len(ws.sent) == 1
    assert isinstance(ws.sent[0]["mtime"], float)
