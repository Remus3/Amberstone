"""TFT-02 (docs/TFT_PROGRAM.md section 7): the TFT.log source.

Acceptance, slice row TFT-02 (log half): from a synthetic TFT.log excerpt,
emit phase / VO events with timestamps into the TFT-01 round store; the log
tail is bounded and allowlist-only (section 8 item 2: ~24 MB per match, auth /
chat / telemetry lines mixed in, never a whole-file read on the poll path).

Fixture: tests/fixtures/tft_sources/tft_log_excerpt.txt - SYNTHETIC; every
identity is a Sentinel and it plants look-alike lines (a chat line carrying
the phase text, a stamp not at line start, a VO actor holding a name instead
of a unit api, a blocked cue). Line shapes re-measured s135 against the live
logs (templated, no value copied): the allowlisted bodies match the excerpt;
live files start with a UTF-8 BOM and use CRLF; stamps are UTC (header
"Log file open" is local time, the first stamp is +5 h).
Nothing here reads %LOCALAPPDATA%, data/ or logs/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tft.rounds.store import RoundStore
from tft.sources import eog_file as ef
from tft.sources import tft_log as tl

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "tft_sources"
SALT = b"tft02-synthetic-salt-0123456789ab"
T0 = 1792929600.0  # 2026-10-25 12:00:00 UTC = timeline.json t0_epoch

# (kind, seconds after T0, payload) - every event the excerpt must yield, in order
EXPECTED = [
    ("carousel_music", 5.0, {"track": "carousel", "conf": 1.0}),
    ("phase", 19.0, {"phase": "DraftDeparture", "conf": 1.0}),
    ("carousel_music", 19.5, {"track": "gameplay", "conf": 1.0}),
    ("victory_vo", 60.0, {"unit": "DA_18_Shen", "conf": 0.6}),
    ("phase", 61.0, {"phase": "CombatDeparture", "conf": 1.0}),
    ("purchase_vo", 70.0, {"unit": "DA_18_Xayah", "conf": 0.6}),
    ("phase", 95.0, {"phase": "PlanningDeparture", "conf": 1.0}),
    ("victory_vo", 125.0, {"unit": "DA_18_Yorick", "conf": 0.6}),
    ("phase", 126.0, {"phase": "CombatDeparture", "conf": 1.0}),
    ("starup_vo", 130.0, {"unit": "DA_18_Xayah", "star": 2, "conf": 0.6}),
    ("planner_saved", 150.0, {"conf": 1.0}),
    ("phase", 160.0, {"phase": "PlanningDeparture", "conf": 1.0}),
    ("victory_vo", 189.0, {"unit": "DA_Karma18", "conf": 0.6}),
    ("phase", 190.0, {"phase": "CombatDeparture", "conf": 1.0}),
]
# round each event lands on, from the EoG rewrite mtimes (T0 + 50, 97, 110, 131,
# 162, 200): the last rewrite at or before the event; None = before the first
EXPECTED_ROUND = [None, None, None, 1, 1, 1, 1, 3, 3, 3, 4, 4, 5, 5]

STAMP = "[2026.10.25-12.00.19:000][259]"
PHASE_BODY = ("TFT: [Client] TFTPerformanceSubsystem_2147482162: Scheduled phase garbage "
              "collection - time since last GC start: [18.7] / Phase[ETFTPhaseType::{}]")


def _excerpt_bytes() -> bytes:
    return (FIX / "tft_log_excerpt.txt").read_bytes()


def _events(evs):
    return [(e.kind, round(e.ts - T0, 3), e.payload) for e in evs]


def _drain(tail, limit=10_000):
    out = []
    for _ in range(limit):
        got = tail.poll()
        if not got and tail.stats["last_read"] == 0:
            return out
        out.extend(got)
    raise AssertionError("tail never reached the end")


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "Logs" / "TFT.log"


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------------------------------------------------------------- allowlist


def test_the_excerpt_yields_exactly_the_allowlisted_events(log_path):
    _write(log_path, _excerpt_bytes())
    got = _drain(tl.TftLogTail(log_path))
    assert _events(got) == EXPECTED


def test_rejected_lines_carry_nothing_out():
    lines = _excerpt_bytes().decode("ascii").splitlines()
    kept = [ev for ev in (tl.parse_line(x) for x in lines) if ev is not None]
    assert len(kept) == len(EXPECTED)
    blob = json.dumps([(e.kind, e.ts, e.payload) for e in kept]) + repr(kept)
    for leak in ("Sentinel", "192.0.2", "chat", "Token", "MatchId", "Participant", "Host"):
        assert leak not in blob, leak


@pytest.mark.parametrize("line", [
    # a stamp that does not open the line
    "garbage " + STAMP + PHASE_BODY.format("CombatDeparture"),
    # a chat line carrying the phase text
    STAMP + "RGIOPRiotGamesApiInternal: chat: Scheduled phase garbage collection - time since "
            "last GC start: [1.0] / Phase[ETFTPhaseType::CombatDeparture]",
    # trailing text after an allowlisted body
    STAMP + PHASE_BODY.format("CombatDeparture") + " from SentinelGameName1",
    # a VO actor holding a display name instead of a unit api
    STAMP + "TFT: [Client] TFTAudioEventSubsystem: Trigger[Audio.Event.VO.Unit.Purchase] "
            "Actor[TFTCharacter_2147461664 {SentinelGameName2}] Plays Event[A_VO_X_Purchase_Cue] "
            "with Interrupt Channel [AC_VO_Round]",
    # a blocked cue is not a purchase
    STAMP + "TFT: [Client] TFTAudioEventSubsystem: Actor[TFTCharacter_2147461663 {DA_18_Ahri}] "
            "and Event[Audio.Event.VO.Unit.Purchase] was blocked by InterruptChannel[AC_VO_Round]",
    # a VO trigger outside the three allowlisted cues
    STAMP + "TFT: [Client] TFTAudioEventSubsystem: Trigger[Audio.Event.VO.Unit.Spell] "
            "Actor[TFTCharacter_2147470001 {DA_18_Shen}] Plays Event[A_VO_Shen18_Spell_Cue] "
            "with Interrupt Channel [AC_VO_Action]",
    # an unknown music track
    STAMP + "LogTFTMusic: UTFTMusicPlayerSubsystem::SwitchToMusic - Switched to music "
            "[MS_Music_SentinelGameName0]",
    "[2026.13.45-12.00.19:000][259]" + PHASE_BODY.format("CombatDeparture"),  # impossible date
    STAMP + PHASE_BODY.format("Combat Departure"),
    "",
    "Log file open, 10/25/26 07:00:00",
])
def test_look_alike_lines_are_rejected(line):
    assert tl.parse_line(line) is None


def test_the_ceremony_planning_line_is_a_phase():
    line = (STAMP + "TFT: [Client] TFTTopCeremonySubsystem: Cleanup top ceremony at round "
                    "phase[ETFTPhaseType::Planning]")
    ev = tl.parse_line(line)
    assert (ev.kind, ev.ts, ev.payload) == ("phase", T0 + 19.0, {"phase": "Planning", "conf": 1.0})


def test_stamps_are_utc_epoch_seconds_with_milliseconds():
    ev = tl.parse_line("[2026.10.25-12.00.19:500][296]" + PHASE_BODY.format("Planning"))
    assert ev.ts == T0 + 19.5
    assert ev.kind == "phase"


def test_the_allowlist_is_closed_over_store_event_kinds():
    from tft.rounds import schema as rs
    assert {kind for _name, kind in tl.ALLOWLIST} <= set(rs.EVENT_KINDS)
    assert "eog_rewrite" not in {kind for _name, kind in tl.ALLOWLIST}


# ---------------------------------------------------------------- the bounded tail


def test_bom_and_crlf_read_like_the_plain_excerpt(log_path):
    data = b"\xef\xbb\xbf" + _excerpt_bytes().replace(b"\n", b"\r\n")
    _write(log_path, data)
    assert _events(_drain(tl.TftLogTail(log_path))) == EXPECTED


def test_the_tail_reads_only_new_bytes(log_path):
    data = _excerpt_bytes()
    cut = data.index(b"\n", len(data) // 2) + 1
    _write(log_path, data[:cut])
    tail = tl.TftLogTail(log_path)
    first = _drain(tail)
    with open(log_path, "ab") as fh:
        fh.write(data[cut:])
    second = _drain(tail)
    assert _events(first + second) == EXPECTED
    assert first and second
    assert tail.offset == len(data)


def test_a_partial_line_waits_for_its_newline(log_path):
    line = (STAMP + PHASE_BODY.format("CombatDeparture")).encode("ascii")
    _write(log_path, line[:40])
    tail = tl.TftLogTail(log_path)
    assert _drain(tail) == []
    with open(log_path, "ab") as fh:
        fh.write(line[40:])
    assert _drain(tail) == []  # still no newline: the writer may be mid-line
    with open(log_path, "ab") as fh:
        fh.write(b"\n")
    assert [e.payload["phase"] for e in _drain(tail)] == ["CombatDeparture"]


def test_every_poll_reads_at_most_its_byte_cap(log_path):
    noise = (STAMP + "LogNet: telemetry " + "x" * 180 + "\n").encode("ascii")
    phase = (STAMP + PHASE_BODY.format("PlanningDeparture") + "\n").encode("ascii")
    block = noise * 499 + phase
    data = block * 30  # ~3 MB, 30 phase lines
    _write(log_path, data)
    cap = 256 * 1024
    tail = tl.TftLogTail(log_path, max_bytes_per_poll=cap)
    polls, events = 0, []
    while True:
        got = tail.poll()
        events.extend(got)
        if tail.stats["last_read"] == 0:
            break
        polls += 1
        assert tail.stats["last_read"] <= cap
    assert tail.stats["max_read"] <= cap
    assert polls >= len(data) // cap
    assert len(events) == 30


def test_an_overlong_line_is_dropped_and_parsing_resumes(log_path):
    long_line = (STAMP + "x" * 20_000 + PHASE_BODY.format("CombatDeparture") + "\n").encode("ascii")
    ok = (STAMP + PHASE_BODY.format("PlanningDeparture") + "\n").encode("ascii")
    _write(log_path, ok + long_line + ok)
    tail = tl.TftLogTail(log_path, max_line_bytes=4096, max_bytes_per_poll=3000)
    got = _drain(tail)
    assert [e.payload["phase"] for e in got] == ["PlanningDeparture", "PlanningDeparture"]
    assert tail.stats["dropped_long"] == 1


@pytest.mark.parametrize("chunk", [1 << 20, 1000])
def test_an_overlong_padded_line_is_dropped_in_one_chunk_or_many(log_path, chunk):
    # a valid line padded past max_line_bytes (but under parse_line's own cap):
    # only the tail's length rule can drop it
    padded = (STAMP + PHASE_BODY.format("CombatDeparture") + " " * 4800 + "\n").encode("ascii")
    ok = (STAMP + PHASE_BODY.format("PlanningDeparture") + "\n").encode("ascii")
    _write(log_path, padded + ok)
    tail = tl.TftLogTail(log_path, max_line_bytes=4096, max_bytes_per_poll=chunk)
    assert [e.payload["phase"] for e in _drain(tail)] == ["PlanningDeparture"]
    assert tail.stats["dropped_long"] == 1


def test_a_bom_before_an_allowlisted_first_line_is_skipped(log_path):
    line = (STAMP + PHASE_BODY.format("Planning") + "\r\n").encode("ascii")
    _write(log_path, b"\xef\xbb\xbf" + line)
    assert [e.payload["phase"] for e in _drain(tl.TftLogTail(log_path))] == ["Planning"]


def test_a_rotated_log_restarts_at_zero(log_path):
    data = _excerpt_bytes()
    _write(log_path, data)
    tail = tl.TftLogTail(log_path)
    assert len(_drain(tail)) == len(EXPECTED)
    # the client rotates TFT.log per launch: a new, shorter file
    short = b"Log file open, 10/25/26 08:00:00\n" + (STAMP + PHASE_BODY.format("Planning") + "\n").encode()
    _write(log_path, short)
    assert [e.payload["phase"] for e in _drain(tail)] == ["Planning"]
    # a new file already LONGER than the old offset is caught by its header
    longer = b"Log file open, 10/25/26 09:00:00\n" + data * 2
    _write(log_path, longer)
    assert len(_drain(tail)) == 2 * len(EXPECTED)
    assert tail.stats["rotations"] == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
def test_an_open_tail_never_blocks_the_clients_log_rotation(log_path):
    _write(log_path, _excerpt_bytes())
    backup = log_path.with_name("TFT-backup-x.log")
    # positive control: a plain open() DOES block the rename on this platform
    with open(log_path, "rb"):
        with pytest.raises(PermissionError):
            os.replace(log_path, backup)
    with tl._open_shared(log_path) as fh:
        assert fh.read(3) == b"Log"
        os.replace(log_path, backup)  # the client's per-launch rotation
    assert backup.exists() and not log_path.exists()


def test_the_tail_opens_only_through_the_share_safe_helper(log_path, monkeypatch):
    _write(log_path, _excerpt_bytes())
    calls, real = [], tl._open_shared
    monkeypatch.setattr(tl, "_open_shared", lambda p: calls.append(p) or real(p))
    assert len(tl.TftLogTail(log_path).poll()) == len(EXPECTED)
    assert calls == [log_path]


def test_start_at_end_skips_the_history(log_path):
    data = _excerpt_bytes()
    _write(log_path, data)
    tail = tl.TftLogTail(log_path, start="end")
    assert _drain(tail) == []
    with open(log_path, "ab") as fh:
        fh.write((STAMP + PHASE_BODY.format("Planning") + "\n").encode("ascii"))
    assert [e.payload["phase"] for e in _drain(tail)] == ["Planning"]


def test_a_missing_or_unreadable_log_is_quiet(tmp_path):
    tail = tl.TftLogTail(tmp_path / "nope" / "TFT.log")
    assert tail.poll() == []
    d = tmp_path / "is_a_dir"
    d.mkdir()
    assert tl.TftLogTail(d).poll() == []


def test_default_path_sits_beside_the_p0_eog_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tl.p0, "eog_stats_path", lambda: tmp_path / "Logs" / "TFTEoGStats.json")
    assert tl.tft_log_path() == tmp_path / "Logs" / "TFT.log"
    assert tl.TftLogTail().path == tmp_path / "Logs" / "TFT.log"


# ---------------------------------------------------------------- into the round store


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def _eog_rewrites():
    tlj = json.loads((FIX / "timeline.json").read_text(encoding="ascii"))
    return [(json.loads((FIX / r["file"]).read_text(encoding="ascii")), T0 + float(r["t"]))
            for r in tlj["rewrites"]]


@pytest.fixture
def store(tmp_path):
    s = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        yield s
    finally:
        s.close()


def _eog_ingest(tmp_path, monkeypatch, store, rewrites):
    p = tmp_path / "Logs" / "TFTEoGStats.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ef.p0, "eog_stats_path", lambda: p)  # conftest pins it absent
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    for doc, mtime in rewrites:
        p.write_text(json.dumps(doc), encoding="ascii")
        os.utime(p, (mtime, mtime))
        clock.now = mtime + 1
        assert ing.poll() is not None
    return ing


def test_log_events_land_on_their_rounds(tmp_path, monkeypatch, store, log_path):
    ing = _eog_ingest(tmp_path, monkeypatch, store, _eog_rewrites())
    _write(log_path, _excerpt_bytes())
    clock = Clock(T0 + 3600)
    li = tl.LogIngest(store, tl.TftLogTail(log_path), ing.locate, clock=clock)
    assert li.poll() == len(EXPECTED)
    assert li.poll() == 0
    assert store.flush()
    doc = store.get_match(ing.match_id)
    rows = list(doc["events"]) + [e for r in doc["rounds"] for e in r["events"]]
    rows = sorted((e for e in rows if e["src"] == "tft_log"), key=lambda e: (e["ts"], e["id"]))
    assert [(e["kind"], round(e["ts"] - T0, 3), e["payload"]) for e in rows] == EXPECTED
    assert [e["round_seq"] for e in rows] == EXPECTED_ROUND


def test_events_wait_for_a_match_and_the_buffer_is_bounded(tmp_path, monkeypatch, store, log_path):
    _write(log_path, _excerpt_bytes())
    clock = Clock(T0 + 3600)
    holder = {"ing": None}

    def locate(ts):
        return holder["ing"].locate(ts) if holder["ing"] else None

    li = tl.LogIngest(store, tl.TftLogTail(log_path), locate, clock=clock, buffer_max=10)
    assert li.poll() == 0  # no match yet: held, not written
    assert li.stats["pending"] == 10 and li.stats["dropped_buffer"] == len(EXPECTED) - 10
    holder["ing"] = _eog_ingest(tmp_path, monkeypatch, store, _eog_rewrites())
    assert li.poll() == 10
    assert li.stats["pending"] == 0


def test_an_event_after_the_latest_rewrite_settles_before_it_is_placed(
        tmp_path, monkeypatch, store, log_path):
    rw = _eog_rewrites()
    ing = _eog_ingest(tmp_path, monkeypatch, store, rw[:1])  # only rewrite 1 (T0 + 50) known
    line = ("[2026.10.25-12.01.40:000][1]" + PHASE_BODY.format("PlanningDeparture") + "\n")
    _write(log_path, line.encode("ascii"))  # T0 + 100: after rewrite 2 (T0 + 97), not yet seen
    clock = Clock(T0 + 101)
    li = tl.LogIngest(store, tl.TftLogTail(log_path), ing.locate, clock=clock, settle_s=5.0)
    assert li.poll() == 0 and li.stats["pending"] == 1  # could still belong to an unseen rewrite
    _eog_more = rw[1]
    p = tmp_path / "Logs" / "TFTEoGStats.json"
    p.write_text(json.dumps(_eog_more[0]), encoding="ascii")
    os.utime(p, (_eog_more[1], _eog_more[1]))
    ing.source.clock.now = _eog_more[1] + 1
    assert ing.poll().round_seq == 2
    assert li.poll() == 0  # T0 + 101 < T0 + 100 + settle: still held
    clock.now = T0 + 105
    assert li.poll() == 1
    assert store.flush()
    r2 = [r for r in store.get_match(ing.match_id)["rounds"] if r["round_seq"] == 2][0]
    assert [e["kind"] for e in r2["events"] if e["src"] == "tft_log"] == ["phase"]


def test_stale_pending_events_age_out(tmp_path, monkeypatch, store, log_path):
    old = ("[2026.10.25-10.00.00:000][1]" + PHASE_BODY.format("Planning") + "\n")  # 2 h before
    new = ("[2026.10.25-12.00.19:000][1]" + PHASE_BODY.format("DraftDeparture") + "\n")
    _write(log_path, (old + new).encode("ascii"))
    ing = _eog_ingest(tmp_path, monkeypatch, store, _eog_rewrites()[:1])
    li = tl.LogIngest(store, tl.TftLogTail(log_path), ing.locate, clock=Clock(T0 + 3600))
    assert li.poll() == 1  # the draft departure; the 2 h old line belongs to no match
    assert li.stats["dropped_stale"] == 1 and li.stats["pending"] == 0


# ---------------------------------------------------------------- restart idempotency


def _log_event_count(db: Path) -> int:
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM event WHERE src = 'tft_log'").fetchone()[0]
    finally:
        conn.close()


def _rc_process(tmp_path, monkeypatch, db, log_path, rewrites):
    """One RC process lifetime: open the store, resume the match from the EoG
    file, tail TFT.log from its start (no saved offset), close."""
    st = RoundStore.open(db)
    try:
        ing = _eog_ingest(tmp_path, monkeypatch, st, rewrites)
        li = tl.LogIngest(st, tl.TftLogTail(log_path), ing.locate, clock=Clock(T0 + 3600))
        for _ in range(50):
            li.poll()
            if li.tail.stats["last_read"] == 0:
                break
        assert st.flush()
        return li.stats
    finally:
        st.close()


def test_restarts_never_duplicate_log_events_and_a_rotated_log_still_lands(
        tmp_path, monkeypatch, log_path):
    db = tmp_path / "tft" / "tft_rounds.db"
    rw = _eog_rewrites()
    _write(log_path, _excerpt_bytes())
    counts = []
    for i in range(3):  # three processes over the same log and store
        stats = _rc_process(tmp_path, monkeypatch, db, log_path, rw if i == 0 else rw[-1:])
        counts.append(_log_event_count(db))
        if i:
            assert stats["duplicates"] == len(EXPECTED) and stats["written"] == 0
    assert counts == [len(EXPECTED)] * 3
    # the client rotates TFT.log: a NEW file whose lines are new events
    new = ("Log file open, 10/25/26 07:03:30\n"
           "[2026.10.25-12.03.25:000][1]" + PHASE_BODY.format("PlanningDeparture") + "\n"
           "[2026.10.25-12.03.40:000][2]" + PHASE_BODY.format("CombatDeparture") + "\n")
    _write(log_path, new.encode("ascii"))
    for _ in range(2):
        _rc_process(tmp_path, monkeypatch, db, log_path, rw[-1:])
        counts.append(_log_event_count(db))
    assert counts[3:] == [len(EXPECTED) + 2] * 2


def test_an_in_process_reread_writes_nothing_twice(tmp_path, monkeypatch, store, log_path):
    ing = _eog_ingest(tmp_path, monkeypatch, store, _eog_rewrites())
    _write(log_path, _excerpt_bytes())
    li = tl.LogIngest(store, tl.TftLogTail(log_path), ing.locate, clock=Clock(T0 + 3600))
    assert li.poll() == len(EXPECTED)
    # the same bytes again under a new header (a false rotation) re-read from 0
    _write(log_path, b"Log file open, 10/25/26 07:00:01\n" + _excerpt_bytes())
    assert li.poll() == 0 and li.stats["duplicates"] == len(EXPECTED)
