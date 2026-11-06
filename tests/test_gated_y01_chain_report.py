"""Tests for tools/gated_y01_chain_report.py - the lane-9 read-only Y-01 (G4-30)
read-back that joins game ends, the post-game collector's own-id line, the
rewind live writer's chain-end line, the Y-08 receipt, the pin and the rewind
DB row. Every id below is synthetic (RM-906); log lines are rendered in the
verbose shape core/log_setup.py writes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import pytest

from tools import gated_y01_chain_report as y

ROOT = Path(__file__).resolve().parent.parent
BASE = time.mktime((2026, 11, 2, 10, 0, 0, 0, 0, -1))
GAP = 40 * 60.0
PLAT = "NA1"


def _gid(i: int) -> str:
    return str(1000000001 + i)


def _tid(i: int) -> str:
    return f"{PLAT}_{_gid(i)}"


class Lab:
    """A synthetic checkout: logs/, ops/runtime/ and data/ under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.logs = root / "logs"
        self.logs.mkdir(parents=True)
        self.runtime = root / "ops" / "runtime"
        self.runtime.mkdir(parents=True)
        (root / "data").mkdir()
        self.lines: list[tuple[float, str]] = []
        self.receipts: list[dict] = []
        self.db_rows: list[str] = []

    def log(self, ts: float, logger: str, msg: str, src: str = "x.py:1") -> None:
        lt = time.localtime(ts)
        ms = round((ts % 1) * 1000) % 1000
        self.lines.append((ts, f"{time.strftime('%H:%M:%S', lt)}.{ms:03d} INFO     "
                               f"{logger:<20} [{src}] {msg}"))

    def game(self, i: int, *, status: str = "ok", target: str | None = "own",
             attempt: int = 0, pinned: bool = True, fallback: bool = False,
             parked: bool = False, kiwi: bool = False, own_line: bool = True,
             chain: bool = True, receipt: bool = True, db: bool = True,
             end_after: float = 150.0) -> float:
        t0 = BASE + i * GAP
        self.log(t0, "rc.app.lifecycle", "Game ended", "_game_lifecycle.py:195")
        self.log(t0 + 0.01, "rc.postgame",
                 f"PostgameCollector: triggered for mode={'KIWI' if kiwi else 'CLASSIC'}")
        if own_line:
            self.log(t0 + 6, "rc.postgame",
                     f"postgame: saved match {_gid(i)}  mode=SR  players=10  duration=1800s")
        if target == "own":
            target = _tid(i)
        sched = t0 + 0.25
        if chain:
            self.log(sched + end_after, "rc.lib.rewind_live_writer",
                     f"rewind_live_writer: chain chain-{sched:.6f}-4242 attempt {attempt} "
                     f"ended {status} ({target or 'no target'})")
        if receipt:
            self.receipts.append({"v": 1, "ts": sched + end_after, "target": target,
                                  "status": status, "attempts": attempt + 1,
                                  "elapsed_s": round(end_after, 3), "parked": parked,
                                  "pinned": pinned, "fallback": fallback, "cause": ""})
        if db and status == "ok" and target:
            self.db_rows.append(target)
        return t0

    def flush(self, *, rotate_at: float | None = None) -> None:
        self.lines.sort()
        by_day: dict[str, list[tuple[float, str]]] = {}
        for ts, line in self.lines:
            by_day.setdefault(time.strftime("%Y-%m-%d", time.localtime(ts)), []).append(
                (ts, line))
        for day, rows in by_day.items():
            old = [ln for ts, ln in rows if rotate_at is not None and ts < rotate_at]
            new = [ln for ts, ln in rows if rotate_at is None or ts >= rotate_at]
            (self.logs / f"{day}.log").write_text("\n".join(new) + "\n", encoding="utf-8")
            if old:
                (self.logs / f"{day}.log.1").write_text("\n".join(old) + "\n",
                                                        encoding="utf-8")
        (self.runtime / "rewind_ingest_receipts.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self.receipts), encoding="utf-8")
        conn = sqlite3.connect(self.root / "data" / "rewind_history.db")
        conn.execute("CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO matches VALUES (?)",
                         [(m,) for m in self.db_rows])
        conn.commit()
        conn.close()

    def pin(self, i: int, queue_id=420, mode: str = "CLASSIC") -> None:
        (self.runtime / "last_game_end.json").write_text(json.dumps({
            "game_id": _gid(i), "queue_id": queue_id, "game_mode": mode,
            "game_name": "SyntheticName", "tag_line": "ZZ9",
            "written_at": BASE + i * GAP + 5}), encoding="utf-8")

    def report(self, *, now: float | None = None, db: bool = True, **kw) -> dict:
        return y.build_report(
            logs_dir=self.logs, receipts=self.runtime / "rewind_ingest_receipts.jsonl",
            pin=self.runtime / "last_game_end.json",
            db=(self.root / "data" / "rewind_history.db") if db else None,
            now=now if now is not None else BASE + 20 * GAP, platform=PLAT, **kw)


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path / "checkout")


def _five_pass(lab: Lab) -> None:
    for i in range(4):
        lab.game(i)
    lab.game(4, status="event_mode_excluded", kiwi=True, end_after=90.0)


def test_chain_window_derives_from_the_writer_schedule():
    from lib import rewind_live_writer as rlw
    assert rlw.DEFAULT_DELAY_S + sum(rlw.STAGED_DELAYS_S) + 120.0 == y.CHAIN_WINDOW_S
    assert y.CHAIN_WINDOW_S == 1290.0


def test_idle_checkout_reads_incomplete_never_pass(lab, monkeypatch, capsys):
    monkeypatch.setenv("RC_RIOT_PLATFORM", PLAT)
    assert y.main(["--root", str(lab.root)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("Y-01 verdict: INCOMPLETE - 0 of 5 League game ends")
    assert "pin: absent" in out


def test_missing_root_dirs_read_incomplete(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_RIOT_PLATFORM", PLAT)
    assert y.main(["--root", str(tmp_path / "nope"), "--json"]) == 1


def test_five_pinned_own_id_ends_with_a_mayhem_exclude_pass(lab, monkeypatch, capsys):
    _five_pass(lab)
    lab.pin(4, queue_id=2400, mode="KIWI")
    lab.flush()
    rep = lab.report()
    assert rep["verdict"] == "PASS", rep
    assert [g["verdict"] for g in rep["games"]] == ["PASS"] * 5
    assert [g["db_row"] for g in rep["games"]][:4] == [True] * 4
    assert rep["pin"]["queue_id_present"] is True and rep["pin"]["queue_id"] == 2400
    monkeypatch.setenv("RC_RIOT_PLATFORM", PLAT)
    assert y.main(["--root", str(lab.root)]) == 0
    assert capsys.readouterr().out.startswith("Y-01 verdict: PASS")


def test_a_chain_that_reports_the_previous_games_id_fails(lab):
    _five_pass(lab)
    lab.game(5, target=_tid(3))
    lab.flush()
    rep = lab.report()
    assert rep["verdict"] == "FAIL"
    assert "repeats an earlier game's target" in rep["games"][5]["why"]


def test_ok_for_a_target_that_is_not_this_games_eog_id_fails(lab):
    _five_pass(lab)
    lab.game(5, target=f"{PLAT}_1999999999")
    lab.flush()
    g = lab.report()["games"][5]
    assert g["verdict"] == "FAIL" and "NOT this game's EOG id" in g["why"]


@pytest.mark.parametrize("kw", [{"pinned": False}, {"fallback": True}])
def test_unpinned_or_fallback_chain_fails(lab, kw):
    lab.game(0, **kw)
    lab.flush()
    g = lab.report()["games"][0]
    assert g["verdict"] == "FAIL" and "unpinned" in g["why"]


def test_event_mode_excluded_after_a_late_pin_still_passes(lab):
    # attempt > 0 = the pin arrived after the 90 s delay (awaiting_pin retry);
    # a pin with no queueId and no KIWI never excludes at all.
    lab.game(0, status="event_mode_excluded", attempt=1, kiwi=True)
    lab.flush()
    g = lab.report()["games"][0]
    assert g["verdict"] == "PASS" and "pin arrived late" in g["why"]


@pytest.mark.parametrize("which", ["before_since", "unrelated"])
def test_a_mayhem_exclude_for_another_games_id_fails(lab, which):
    lab.game(0)
    for i in range(1, 5):
        lab.game(i)
    bad = _tid(0) if which == "before_since" else f"{PLAT}_1999999999"
    lab.game(5, status="event_mode_excluded", kiwi=True, target=bad)
    lab.flush()
    rep = lab.report(since=BASE + GAP - 1)
    assert rep["games"][-1]["verdict"] == "FAIL"
    assert "NOT this game's EOG id" in rep["games"][-1]["why"]
    assert rep["verdict"] == "FAIL"


def test_a_wrong_ok_target_fails_even_without_a_receipt(lab):
    lab.game(0, target=f"{PLAT}_1999999999", receipt=False)
    lab.flush()
    assert lab.report()["games"][0]["verdict"] == "FAIL"


def test_a_receipt_without_a_chain_line_is_never_pass(lab):
    lab.game(0, chain=False)
    lab.flush()
    g = lab.report()["games"][0]
    assert g["verdict"] == "INCOMPLETE" and "no chain-end log line" in g["why"]


def test_one_pending_game_holds_an_otherwise_passing_set_at_incomplete(lab):
    _five_pass(lab)
    t5 = lab.game(5, chain=False, receipt=False)
    lab.flush()
    rep = lab.report(now=t5 + 60)
    assert rep["games"][5]["verdict"] == "INCOMPLETE"
    assert rep["verdict"] == "INCOMPLETE" and rep["league_game_ends"] == 6


def test_a_restart_never_voids_a_chain_that_ended(lab):
    t0 = lab.game(0, target=f"{PLAT}_1999999999")
    lab.log(t0 + 400, "rc.postgame", "PostgameCollector started (async)")
    lab.flush()
    rep = lab.report()
    assert rep["games"][0]["verdict"] == "FAIL" and rep["void_game_ends"] == 0


def test_a_tft_marker_never_hides_a_joined_chain(lab):
    lab.game(0, status="no_detail")
    lab.log(BASE + 0.02, "rc.app.lifecycle", y.TFT_SKIP)
    lab.flush()
    rep = lab.report()
    assert rep["games"][0]["verdict"] == "FAIL" and rep["tft_game_ends"] == 0


def test_game_ended_from_another_logger_is_ignored(lab):
    lab.log(BASE, "rc.other", "Game ended")
    lab.flush()
    assert lab.report()["games"] == []


def test_the_platform_comes_from_the_read_checkout(lab, monkeypatch):
    monkeypatch.delenv("RC_RIOT_PLATFORM", raising=False)
    (lab.root / "config").mkdir()
    (lab.root / "config" / "operator_identity.json").write_text(
        json.dumps({"platform": "euw1", "game_name": "SyntheticName"}), encoding="utf-8")
    assert y._platform(lab.root) == "EUW1"
    monkeypatch.setenv("RC_RIOT_PLATFORM", "kr")
    assert y._platform(lab.root) == "KR"
    monkeypatch.delenv("RC_RIOT_PLATFORM")
    assert y._platform(lab.root.parent / "no-config") == "NA1"
    lab.game(0)
    lab.flush()
    # The fixture targets are NA1_..., so the EUW1 checkout reads them as foreign.
    assert y.main(["--root", str(lab.root), "--json", "--no-db"]) == 2


def test_the_db_is_opened_read_only(lab, monkeypatch):
    lab.game(0)
    lab.flush()
    seen = []
    real = sqlite3.connect

    def spy(database, *a, **kw):
        seen.append((database, kw.get("uri")))
        return real(database, *a, **kw)

    monkeypatch.setattr(y.sqlite3, "connect", spy)
    assert lab.report()["games"][0]["db_row"] is True
    assert seen and all(str(d).endswith("?mode=ro") and u is True for d, u in seen)


def test_a_parked_mayhem_game_fails(lab):
    lab.game(0, status="target_not_indexed", attempt=4, parked=True, kiwi=True,
             end_after=1170.0)
    lab.flush()
    rep = lab.report()
    assert rep["games"][0]["verdict"] == "FAIL"
    assert "target_not_indexed (deferred)" in rep["games"][0]["why"]
    assert rep["verdict"] == "FAIL"


def test_no_chain_inside_the_window_is_pending_then_fails(lab):
    t0 = lab.game(0, chain=False, receipt=False)
    lab.flush()
    assert lab.report(now=t0 + 300)["games"][0]["verdict"] == "INCOMPLETE"
    late = lab.report(now=t0 + y.CHAIN_WINDOW_S + 1)
    assert late["games"][0]["verdict"] == "FAIL"
    assert "no chain end within 1290 s" in late["games"][0]["why"]


def test_an_rc_restart_inside_the_window_voids_the_game(lab):
    t0 = lab.game(0, chain=False, receipt=False)
    lab.log(t0 + 47, "rc.postgame", "PostgameCollector started (async)")
    lab.flush()
    rep = lab.report()
    assert rep["games"][0]["verdict"] == "VOID"
    assert rep["league_game_ends"] == 0 and rep["void_game_ends"] == 1
    assert rep["verdict"] == "INCOMPLETE"


def test_tft_ends_are_skipped_by_either_marker(lab):
    t0 = BASE
    lab.log(t0, "rc.app.lifecycle", "Game ended")
    lab.log(t0 + 0.01, "rc.app.lifecycle", y.TFT_SKIP)
    t1 = BASE + GAP
    lab.log(t1, "rc.app.lifecycle", "Game ended")
    lab.log(t1 + 0.01, "rc.postgame", "PostgameCollector: triggered for mode=TFT")
    lab.flush()
    rep = lab.report()
    assert [g["verdict"] for g in rep["games"]] == ["SKIP", "SKIP"]
    assert rep["tft_game_ends"] == 2 and rep["league_game_ends"] == 0


def test_ok_without_a_db_row_fails_and_no_db_is_incomplete(lab):
    lab.game(0, db=False)
    lab.flush()
    g = lab.report()["games"][0]
    assert g["verdict"] == "FAIL" and g["db_row"] is False
    g2 = lab.report(db=False)["games"][0]
    assert g2["verdict"] == "INCOMPLETE" and g2["db_row"] is None


def test_an_unreadable_db_is_incomplete_not_pass(lab):
    lab.game(0)
    lab.flush()
    (lab.root / "data" / "rewind_history.db").write_bytes(b"not a database" * 100)
    g = lab.report()["games"][0]
    assert g["verdict"] == "INCOMPLETE" and g["db_row"] is None


def test_no_receipt_or_no_own_id_line_is_incomplete(lab):
    lab.game(0, receipt=False)
    lab.game(1, own_line=False)
    lab.flush()
    games = lab.report()["games"]
    assert games[0]["verdict"] == "INCOMPLETE" and "no Y-08 receipt" in games[0]["why"]
    assert games[1]["verdict"] == "INCOMPLETE" and "own-id" in games[1]["why"]


def test_an_already_stored_line_never_vouches_for_the_own_id(lab):
    # "already stored" = saved BEFORE this game ended, the stale-EOG shape.
    lab.game(0, own_line=False, status="event_mode_excluded", kiwi=True)
    lab.log(BASE + 6, "rc.postgame", f"postgame: match {_gid(0)} already stored - skip")
    lab.flush()
    g = lab.report()["games"][0]
    assert g["verdict"] == "INCOMPLETE" and "already stored" in g["why"]


@pytest.mark.parametrize("line", [
    "rewind_live_writer: 8 staged Timers pending (cap); not staging another",
    "rewind_live_writer schedule error: boom",
    "rewind live-writer trigger error: boom",
])
def test_a_chain_never_scheduled_fails_even_with_a_later_restart(lab, line):
    _five_pass(lab)
    t5 = lab.game(5, chain=False, receipt=False)
    lab.log(t5 + 0.5, "rc.lib.rewind_live_writer", line)
    lab.log(t5 + 1000, "rc.postgame", "PostgameCollector started (async)")
    lab.flush()
    rep = lab.report()
    assert rep["games"][5]["verdict"] == "FAIL" and rep["verdict"] == "FAIL"


@pytest.mark.parametrize("offset", [-1.0, 6.0, 60.0])
def test_a_cap_line_outside_the_tight_window_is_another_chains(lab, offset):
    # A running chain's retry staging logs the same cap line; only one written
    # 0 .. +5 s after this game's own "Game ended" is this game's refusal.
    t0 = lab.game(0, chain=False, receipt=False)
    lab.log(t0 + offset, "rc.lib.rewind_live_writer",
            "rewind_live_writer: 8 staged Timers pending (cap); not staging another")
    lab.flush()
    assert lab.report(now=t0 + 300)["games"][0]["verdict"] == "INCOMPLETE"


def test_a_restart_long_after_the_window_does_not_void(lab):
    t0 = lab.game(0, chain=False, receipt=False)
    lab.log(t0 + y.CHAIN_WINDOW_S + 7200, "rc.postgame", "PostgameCollector started (async)")
    lab.flush()
    rep = lab.report(now=t0 + y.CHAIN_WINDOW_S + 7300)
    assert rep["games"][0]["verdict"] == "FAIL" and rep["void_game_ends"] == 0


def test_four_passing_ends_are_not_enough(lab):
    for i in range(3):
        lab.game(i)
    lab.game(3, status="event_mode_excluded", kiwi=True)
    lab.flush()
    rep = lab.report()
    assert rep["league_game_ends"] == 4
    assert rep["verdict"] == "INCOMPLETE" and "4 of 5" in rep["why"]


@pytest.mark.parametrize("status", ["already_present", "short_game"])
def test_already_present_and_short_game_are_never_pass(lab, status):
    lab.game(0, status=status)
    lab.flush()
    assert lab.report()["games"][0]["verdict"] == "INCOMPLETE"


def test_pass_needs_both_a_mayhem_exclude_and_an_ok(lab):
    for i in range(5):
        lab.game(i)
    lab.flush()
    rep = lab.report()
    assert rep["verdict"] == "INCOMPLETE" and "ARAM Mayhem" in rep["why"]
    lab2 = Lab(lab.root.parent / "two")
    for i in range(5):
        lab2.game(i, status="event_mode_excluded", kiwi=True)
    lab2.flush()
    rep2 = lab2.report()
    assert rep2["verdict"] == "INCOMPLETE" and "Match-V5-eligible" in rep2["why"]


def test_since_drops_earlier_game_ends(lab):
    lab.game(0, status="no_detail")
    _ = [lab.game(i) for i in range(1, 5)]
    lab.game(5, status="event_mode_excluded", kiwi=True)
    lab.flush()
    assert lab.report()["verdict"] == "FAIL"
    rep = lab.report(since=BASE + GAP - 1)
    assert rep["verdict"] == "PASS" and rep["league_game_ends"] == 5


def test_rotated_backups_and_foreign_lines_are_tolerated(lab):
    _five_pass(lab)
    lab.lines.append((BASE + 1, "garbage \x00\xff line"))
    lab.lines.append((BASE + 2, "10:00:02 INFO     rc.other             unrelated"))
    lab.receipts.append({"status": 7})
    lab.flush(rotate_at=BASE + 2 * GAP)
    with (lab.runtime / "rewind_ingest_receipts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{torn line\n")
    assert (lab.logs / time.strftime("%Y-%m-%d.log.1", time.localtime(BASE))).is_file()
    assert lab.report()["verdict"] == "PASS"


def test_ids_are_redacted_unless_asked_and_the_riot_id_never_prints(lab, monkeypatch, capsys):
    _five_pass(lab)
    lab.pin(4, queue_id=None, mode="KIWI")
    lab.flush()
    rep = lab.report()
    blob = json.dumps(rep) + y.render(rep)
    assert _gid(0) not in blob and _gid(4) not in blob
    assert y._redact(_tid(0), False) in blob
    assert rep["pin"]["queue_id_present"] is False
    monkeypatch.setenv("RC_RIOT_PLATFORM", PLAT)
    y.main(["--root", str(lab.root), "--json"])
    y.main(["--root", str(lab.root), "--show-ids"])
    out = capsys.readouterr().out
    assert _tid(0) in out
    assert "SyntheticName" not in out and "ZZ9" not in out


def test_the_tool_writes_nothing(lab, monkeypatch, capsys):
    _five_pass(lab)
    lab.pin(4)
    lab.flush()

    def snap():
        return {p: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
                for p in lab.root.rglob("*") if p.is_file()}

    before = snap()
    monkeypatch.setenv("RC_RIOT_PLATFORM", PLAT)
    assert y.main(["--root", str(lab.root)]) == 0
    capsys.readouterr()
    assert snap() == before


@pytest.mark.parametrize("rel, literal", [
    ("lib/rewind_live_writer.py",
     '"rewind_live_writer: chain %s attempt %d ended %s (%s)"'),
    ("lib/rewind_live_writer.py", 'f"chain-{now:.6f}-{threading.get_ident()}"'),
    ("app/_game_lifecycle.py", '_log.info("Game ended")'),
    ("app/_game_lifecycle.py", '_log.info("TFT game end: League rewind live-writer skipped")'),
    ("app/_game_lifecycle.py", 'logging.getLogger("rc.app.lifecycle")'),
    ("lcu/lcu_postgame_collector.py", 'logging.getLogger("rc.postgame")'),
    ("lcu/lcu_postgame_collector.py",
     '"postgame: saved match %s  mode=%s  players=%d  duration=%ds"'),
    ("lcu/lcu_postgame_collector.py", '"postgame: match %s already stored - skip"'),
    ("lcu/lcu_postgame_collector.py", '"PostgameCollector: triggered for mode=%s"'),
    ("lcu/lcu_postgame_collector.py", '"PostgameCollector started (async)"'),
    ("lcu/lcu_postgame_collector.py", '"PostgameCollector started (thread)"'),
    ("lib/rewind_live_writer.py", '"rewind_live_writer: %d staged Timers pending (cap); "'),
    ("lib/rewind_live_writer.py", '"not staging another"'),
    ("lib/rewind_live_writer.py", '"rewind_live_writer schedule error: %s"'),
    ("app/_game_lifecycle.py", '"rewind live-writer trigger error: %s"'),
])
def test_every_parsed_line_still_exists_in_its_source(rel, literal):
    assert literal in (ROOT / rel).read_text(encoding="utf-8"), (rel, literal)


def test_the_parsers_read_the_real_format_strings():
    # The logger's own %-style format strings, rendered the way logging does.
    chain_fmt = "rewind_live_writer: chain %s attempt %d ended %s (%s)"
    chain = chain_fmt % ("chain-1793110000.250000-4242", 2, "ok", _tid(0))
    ev = y._classify("rc.lib.rewind_live_writer", chain)
    assert ev["kind"] == "chain_end" and ev["attempt"] == 2
    assert ev["scheduled_at"] == 1793110000.25 and ev["target"] == _tid(0)
    none = y._classify("rc.lib.rewind_live_writer",
                       chain.replace(f"({_tid(0)})", "(no target)"))
    assert none["target"] is None
    saved_fmt = "postgame: saved match %s  mode=%s  players=%d  duration=%ds"
    saved = saved_fmt % (_gid(0), "ARAM", 10, 900)
    assert y._classify("rc.postgame", saved) == {"kind": "eog_id", "game_id": _gid(0)}
    assert y._classify("rc.other", saved) is None


def test_the_line_regex_reads_the_real_log_formatters():
    src = (ROOT / "core" / "log_setup.py").read_text(encoding="utf-8")
    verbose = ('"%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-20s "\n'
               '        "[%(filename)s:%(lineno)d] %(message)s"')
    plain = '"%(asctime)s %(levelname)-8s %(name)-20s %(message)s"'
    assert verbose in src and plain in src
    rec = logging.LogRecord("rc.app.lifecycle", logging.INFO, "_game_lifecycle.py", 195,
                            "Game ended", None, None)
    for fmt in ("%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-20s "
                "[%(filename)s:%(lineno)d] %(message)s",
                "%(asctime)s %(levelname)-8s %(name)-20s %(message)s"):
        line = logging.Formatter(fmt, datefmt="%H:%M:%S").format(rec)
        m = y._LINE.match(line)
        assert m and m.group(6) == "rc.app.lifecycle" and m.group(7) == "Game ended"
