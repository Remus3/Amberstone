"""S144-T-705: true-audit hardening of tools/lcu_push_watcher.py.

The watcher tails RC's day-log and decides the gated A1 verdict. The audit
found (each test below is named for its finding):

1. DEAF AFTER A SIZE ROTATION. core/log_setup.py DailyRotatingFileHandler
   renames the live YYYY-MM-DD.log to .log.1 at 3 MB and starts a new
   YYYY-MM-DD.log. The old main loop kept its handle on the renamed file and
   never reopened the path, so every line after the first rotation of the day
   was never seen (measured: the 2026-10-25 day-log rotated three times).
2. MIDNIGHT ROLLOVER dropped the old day's unread tail (closed without a
   final read) and could skip the new day's first lines (a file first seen
   after the switch was opened at its END).
3. A day-log CREATED AFTER ARM was opened at its end, so its first lines -
   all of them new - were skipped.
4. UNBOUNDED RE-CLASSIFICATION. Every 2 s poll re-ran classify_events over
   EVERY line read since start, so memory and CPU grew without bound for a
   watcher meant to run for days. Each line is now classified exactly once.
5. A read error on the handle raised out of the poll loop and killed the
   watcher.
6. _fetch_state turned a non-object /api/state body into a crash
   (list.get) and swallowed every exception class, bugs included.
7. _emit never filled the mode from /api/state (record.setdefault on a key
   _finalize always sets), wrote the markdown verdict IN PLACE (not atomic),
   and printed the notify detail BEFORE writing the verdict files, so a
   console encode error skipped both files (the LEDGER 1564 residual).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import tools.lcu_push_watcher as w


def _cs_lines(port_a: int = 100, port_b: int = 200) -> list[str]:
    return [
        f"LCU connected: port {port_a} (from x)",
        f"LCU connected: port {port_b} (from x)",
        "RuneWriter: champ select entered",
    ]


def _append(path: Path, *lines: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for ln in lines:
            fh.write(ln + "\n")


class _Clock:
    def __init__(self, path: Path):
        self.path = path

    def __call__(self) -> Path:
        return self.path


# --- 1. size rotation --------------------------------------------------------
def test_tailer_follows_a_size_rotation(tmp_path):
    day = tmp_path / "2026-07-11.log"
    _append(day, "history before arm")
    t = w.DayLogTailer(_Clock(day))
    try:
        assert t.poll() == []                     # armed at the end: history ignored
        _append(day, "A")
        assert t.poll() == ["A"]
        _append(day, "B")                         # written just before the rename
        os.replace(day, tmp_path / "2026-07-11.log.1")
        _append(day, "C")                         # the handler's fresh file
        assert t.poll() == ["B", "C"]
        _append(day, "D")
        assert t.poll() == ["D"]
    finally:
        t.close()


def test_tailer_does_not_reread_an_unrotated_file(tmp_path):
    # The rotation check must not fire on the same file: a false positive would
    # re-read the file from its start and duplicate every line.
    day = tmp_path / "2026-07-11.log"
    _append(day, "x")
    t = w.DayLogTailer(_Clock(day))
    try:
        t.poll()
        got = []
        for i in range(20):
            _append(day, f"L{i}")
            got.extend(t.poll())
            got.extend(t.poll())
        assert got == [f"L{i}" for i in range(20)]
    finally:
        t.close()


# --- 2. midnight rollover ----------------------------------------------------
def test_tailer_rollover_drains_old_day_and_reads_new_day_from_start(tmp_path):
    d1 = tmp_path / "2026-07-11.log"
    d2 = tmp_path / "2026-07-12.log"
    _append(d1, "old history")
    clock = _Clock(d1)
    t = w.DayLogTailer(clock)
    try:
        t.poll()
        _append(d1, "late on day 1")              # unread when midnight passes
        _append(d2, "first on day 2", "second on day 2")
        clock.path = d2
        assert t.poll() == ["late on day 1", "first on day 2", "second on day 2"]
    finally:
        t.close()


def test_tailer_rollover_flushes_an_unterminated_last_line(tmp_path):
    d1 = tmp_path / "2026-07-11.log"
    d2 = tmp_path / "2026-07-12.log"
    d1.write_text("", encoding="utf-8")
    clock = _Clock(d1)
    t = w.DayLogTailer(clock)
    try:
        t.poll()
        with d1.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("no newline yet")
        assert t.poll() == []                     # held as a partial line
        clock.path = d2                           # d2 not created yet
        assert t.poll() == ["no newline yet"]     # the old file is finished
    finally:
        t.close()


def test_tailer_new_day_file_created_after_the_switch_is_read_from_start(tmp_path):
    d1 = tmp_path / "2026-07-11.log"
    d2 = tmp_path / "2026-07-12.log"
    d1.write_text("", encoding="utf-8")
    clock = _Clock(d1)
    t = w.DayLogTailer(clock)
    try:
        t.poll()
        clock.path = d2
        assert t.poll() == []                     # day 2 file not there yet
        _append(d2, "first on day 2")
        assert t.poll() == ["first on day 2"]
    finally:
        t.close()


# --- 3. day-log created after arm --------------------------------------------
def test_tailer_file_created_after_arm_is_read_from_start(tmp_path):
    day = tmp_path / "2026-07-11.log"
    t = w.DayLogTailer(_Clock(day))
    try:
        assert t.poll() == []
        _append(day, "RC started", "LCU connected: port 1 (from x)")
        assert t.poll() == ["RC started", "LCU connected: port 1 (from x)"]
    finally:
        t.close()


# --- 5. read error -----------------------------------------------------------
def test_tailer_read_error_is_survived(tmp_path):
    day = tmp_path / "2026-07-11.log"
    _append(day, "x")
    t = w.DayLogTailer(_Clock(day))
    try:
        t.poll()

        class _Broken:
            def read(self):
                raise OSError(6, "invalid handle")

            def fileno(self):
                raise OSError(6, "invalid handle")

            def close(self):
                pass

        t._fh = _Broken()
        assert t.poll() == []                     # no raise; reopened at the end
        _append(day, "after")
        assert t.poll() == ["after"]
    finally:
        t.close()


# --- 4. each line classified once; incremental classifier --------------------
def test_classifier_is_incremental_and_matches_classify_events():
    lines = _cs_lines() + ["RuneWriter: champion=Ahri mode=aram - applying runes",
                           "RuneWriter: champ select ended - re-armed for next pick"]
    clf = w.A1Classifier()
    got = []
    for ln in lines:
        got.extend(clf.feed(ln))
    assert got == w.classify_events(lines)
    assert got[0]["verdict"] == "PASS"
    assert clf.window_seq == 1 and not clf.has_open_window()


def test_watcher_classifies_each_line_exactly_once(tmp_path, monkeypatch):
    day = tmp_path / "2026-07-11.log"
    day.write_text("", encoding="utf-8")
    fed: list[str] = []
    real_feed = w.A1Classifier.feed

    def spy(self, line):
        fed.append(line)
        return real_feed(self, line)

    monkeypatch.setattr(w.A1Classifier, "feed", spy)
    emitted: list[dict] = []
    watcher = w.Watcher(w.DayLogTailer(_Clock(day)), emitted.append)
    try:
        for n in range(5):
            _append(day, *[f"noise {n}-{i}" for i in range(50)])
            watcher.tick(now=float(n))
        assert len(fed) == 250
        assert len(set(fed)) == 250
        assert emitted == []
    finally:
        watcher.close()


def test_watcher_emits_pass_and_times_out_a_silent_window(tmp_path):
    day = tmp_path / "2026-07-11.log"
    day.write_text("", encoding="utf-8")
    emitted: list[dict] = []
    watcher = w.Watcher(w.DayLogTailer(_Clock(day)), emitted.append)
    try:
        _append(day, *_cs_lines(), "RuneWriter: champion=Ahri mode=aram - applying runes",
                "RuneWriter: champ select ended - re-armed for next pick")
        watcher.tick(now=0.0)
        assert [r["verdict"] for r in emitted] == ["PASS"]

        _append(day, *_cs_lines(300, 400))
        watcher.tick(now=100.0)
        assert len(emitted) == 1                  # open window: not yet decided
        watcher.tick(now=100.0 + w._WINDOW_TIMEOUT_S - 1)
        assert len(emitted) == 1
        watcher.tick(now=100.0 + w._WINDOW_TIMEOUT_S)
        assert len(emitted) == 2
        assert emitted[1]["verdict"] == "FAIL" and emitted[1]["timeout"] is True
        assert emitted[1]["port_after"] == 400

        # A push logged after the timeout belongs to a closed window: no second record.
        _append(day, "RuneWriter: champion=Zed mode=aram - applying runes")
        watcher.tick(now=500.0)
        watcher.tick(now=500.0 + 2 * w._WINDOW_TIMEOUT_S)  # and the timeout never re-fires
        assert len(emitted) == 2
    finally:
        watcher.close()


def test_watcher_timeout_clock_restarts_for_a_reopened_window(tmp_path):
    day = tmp_path / "2026-07-11.log"
    day.write_text("", encoding="utf-8")
    emitted: list[dict] = []
    watcher = w.Watcher(w.DayLogTailer(_Clock(day)), emitted.append)
    try:
        _append(day, *_cs_lines())
        watcher.tick(now=0.0)
        # A second restart + enter closes the first window (FAIL, reopened) and
        # opens a new one, whose timeout counts from when IT was seen.
        _append(day, "LCU connected: port 300 (from x)", "RuneWriter: champ select entered")
        watcher.tick(now=w._WINDOW_TIMEOUT_S - 1)
        assert [r["verdict"] for r in emitted] == ["FAIL"]
        watcher.tick(now=w._WINDOW_TIMEOUT_S + 1)
        assert len(emitted) == 1                  # new window is 2 s old, not 21 s
        watcher.tick(now=2 * w._WINDOW_TIMEOUT_S)
        assert len(emitted) == 2 and emitted[1].get("timeout") is True
    finally:
        watcher.close()


# --- 6. _fetch_state ----------------------------------------------------------
class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.mark.parametrize("body", [b"[1, 2]", b"null", b"\"x\"", b"{bad", b"\xff\xfe"])
def test_fetch_state_non_object_or_junk_body_is_none(monkeypatch, body):
    monkeypatch.setattr(w.urllib.request, "urlopen", lambda *_a, **_k: _Resp(body))
    assert w._fetch_state() is None


def test_fetch_state_object_body_is_returned(monkeypatch):
    monkeypatch.setattr(w.urllib.request, "urlopen",
                        lambda *_a, **_k: _Resp(b"{\"mode_key\": \"aram\"}"))
    assert w._fetch_state() == {"mode_key": "aram"}


def test_fetch_state_network_error_is_none_but_a_bug_surfaces(monkeypatch):
    def refuse(*_a, **_k):
        raise ConnectionRefusedError(10061, "refused")

    monkeypatch.setattr(w.urllib.request, "urlopen", refuse)
    assert w._fetch_state() is None

    def bug(*_a, **_k):
        raise RuntimeError("programming error")

    monkeypatch.setattr(w.urllib.request, "urlopen", bug)
    with pytest.raises(RuntimeError):
        w._fetch_state()


# --- 7. _emit -----------------------------------------------------------------
@pytest.fixture
def emit_env(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_VERDICT_MD", tmp_path / "v.md")
    monkeypatch.setattr(w, "_VERDICT_JSONL", tmp_path / "v.jsonl")
    monkeypatch.setattr(w.operator_notify, "notify", lambda *_a, **_k: (True, "held"))
    return tmp_path


def _record(**over) -> dict:
    rec = {"verdict": "PASS", "restart_reason": "port_change", "port_before": 1,
           "port_after": 2, "champion": None, "mode": None, "matched": ["m"]}
    rec.update(over)
    return rec


def test_emit_fills_mode_and_champion_from_state(emit_env, monkeypatch):
    monkeypatch.setattr(w, "_fetch_state",
                        lambda: {"mode_key": "aram", "coach": {"champion": "Ahri"}})
    rec = _record()
    w._emit(rec)
    assert rec["mode"] == "aram" and rec["champion"] == "Ahri"


def test_emit_ignores_non_string_state_fields(emit_env, monkeypatch):
    monkeypatch.setattr(w, "_fetch_state",
                        lambda: {"mode_key": ["x"], "coach": "not a dict"})
    rec = _record()
    w._emit(rec)
    assert rec["mode"] is None and rec["champion"] is None
    monkeypatch.setattr(w, "_fetch_state",
                        lambda: {"mode_key": 5, "coach": {"champion": {"n": 1}}})
    rec = _record()
    w._emit(rec)
    assert rec["mode"] is None and rec["champion"] is None


def test_emit_writes_files_even_when_the_console_cannot_print(emit_env, monkeypatch):
    monkeypatch.setattr(w, "_fetch_state", lambda: None)
    monkeypatch.setattr(w.operator_notify, "notify",
                        lambda *_a, **_k: (False, "toast: failed " + chr(0x2014) + " no shell"))

    def strict_print(*args, **_k):
        " ".join(str(a) for a in args).encode("ascii")

    monkeypatch.setattr("builtins.print", strict_print)
    w._emit(_record(champion="Ahri"))
    assert (emit_env / "v.md").read_text(encoding="utf-8").startswith("# LCU push watcher")
    row = json.loads((emit_env / "v.jsonl").read_text(encoding="utf-8"))
    assert row["champion"] == "Ahri"


def test_emit_writes_markdown_atomically(emit_env, monkeypatch):
    monkeypatch.setattr(w, "_fetch_state", lambda: None)
    calls = []
    monkeypatch.setattr(w, "atomic_write_text", lambda p, c: calls.append((p, c)))
    w._emit(_record(champion="Ahri"))
    assert len(calls) == 1 and calls[0][0] == emit_env / "v.md"
    assert not (emit_env / "v.md").exists()     # never written in place


def test_emit_md_failure_does_not_cost_the_jsonl_row(emit_env, monkeypatch):
    monkeypatch.setattr(w, "_fetch_state", lambda: None)

    def refuse(*_a):
        raise PermissionError(5, "denied")

    monkeypatch.setattr(w, "atomic_write_text", refuse)
    w._emit(_record(champion="Ahri"))
    assert json.loads((emit_env / "v.jsonl").read_text(encoding="utf-8"))["verdict"] == "PASS"
