"""RED-first tests for tools/lcu_push_watcher.py (gated item A1).

A1 (docs/LIVE_GAME_GATED_SYNC.md line 90 / LEDGER item 779): after a mid-session
League restart, the LCU rune push must STILL fire on the FIRST champ-select enter
(the 2026-07-04 regression was: no push after a restart).

These tests exercise ONLY the PURE core - ``classify_events(lines) -> list[dict]``
and ``render_verdict_md(record) -> str`` - over synthetic log-line fixtures. No
real log file, no toast, no network is touched here; all side-effecting code lives
in thin wrappers (``main``/``_tail_new_lines``/``_toast``/``_fetch_state``) that
these tests never call.
"""
from __future__ import annotations

from tools.lcu_push_watcher import classify_events, render_verdict_md


# --- synthetic log-line builders (mirror the real day-log format) -------------
# Real format (logs/2026-07-10.log:1265):
#   "23:50:37.210 INFO     rc.lcu   [lcu_client.py:77] LCU connected: port 53521 (from ...)"
# classify_events matches by substring/regex, so the prefix is cosmetic here.
def _line(file_line: str, msg: str, level: str = "INFO",
          logger: str = "rc.lcu.runes", t: str = "23:50:37.210") -> str:
    return f"{t} {level:<8} {logger:<20} [{file_line}] {msg}"


def CONNECT(port: int) -> str:  # lcu_client.py:77
    return _line("lcu_client.py:77",
                 f"LCU connected: port {port} (from C:\\Riot Games\\lockfile)",
                 logger="rc.lcu")


def RECONNECT_ROTATED(port: int) -> str:  # lcu_client.py:117
    return _line("lcu_client.py:117",
                 f"LCU reconnected: port {port} (lockfile rotated, from C:\\lockfile)",
                 logger="rc.lcu")


def LOCKFILE_GAP() -> str:  # lcu_client.py:81
    return _line("lcu_client.py:81",
                 "LCU lockfile not found - client may not be running",
                 logger="rc.lcu")


def CS_ENTER() -> str:  # lcu_rune_writer.py:639
    return _line("lcu_rune_writer.py:639", "RuneWriter: champ select entered")


def CS_END() -> str:  # lcu_rune_writer.py:624
    return _line("lcu_rune_writer.py:624",
                 "RuneWriter: champ select ended - re-armed for next pick")


def APPLYING(champ: str, mode: str) -> str:  # lcu_rune_writer.py:665
    return _line("lcu_rune_writer.py:665",
                 f"RuneWriter: champion={champ} mode={mode} - applying runes")


def WROTE(name: str) -> str:  # lcu_rune_writer.py:1023
    return _line("lcu_rune_writer.py:1023",
                 f"RuneWriter: wrote [{name}] id=42  perks=[8010, 9111]")


def FAIL(champ: str, mode: str) -> str:  # lcu_rune_writer.py:671
    return _line("lcu_rune_writer.py:671",
                 f"RuneWriter: rune write failed for {champ}/{mode}", level="WARNING")


def GAVEUP(n: int) -> str:  # lcu_rune_writer.py:1036
    return _line("lcu_rune_writer.py:1036",
                 f"RuneWriter: gave up after {n} attempts for [Ahri Aram]: timeout",
                 level="WARNING")


# --- (a) restart(port A->B) -> enter -> applying runes => PASS ----------------
def test_a_restart_then_enter_then_applying_is_pass():
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(), APPLYING("Ahri", "aram")])
    assert len(v) == 1
    rec = v[0]
    assert rec["verdict"] == "PASS"
    assert rec["port_before"] == 100
    assert rec["port_after"] == 200
    assert rec["restart_reason"] == "port_change"
    assert rec["champion"] == "Ahri"
    assert rec["mode"] == "aram"


# --- (b) restart -> enter -> gave up after 3 attempts => FAIL -----------------
def test_b_restart_then_enter_then_gaveup_is_fail():
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(), GAVEUP(3)])
    assert len(v) == 1
    assert v[0]["verdict"] == "FAIL"
    assert v[0]["port_after"] == 200


# --- (c) champ-select enter with NO preceding restart => quiet (no verdict) ---
def test_c_enter_without_restart_is_quiet():
    assert classify_events([CS_ENTER(), APPLYING("Ahri", "aram")]) == []
    # a FIRST connect (initial arm, last_port was None) is not a restart either
    assert classify_events([CONNECT(100), CS_ENTER(), APPLYING("Ahri", "aram")]) == []


# --- (d) two consecutive champ-selects: only FIRST-after-restart is a case ----
def test_d_only_first_after_restart_is_the_test_case():
    v = classify_events([
        CONNECT(100), CONNECT(200),
        CS_ENTER(), APPLYING("Ahri", "aram"), CS_END(),
        CS_ENTER(), APPLYING("Zed", "aram"),   # 2nd CS: no restart before it -> quiet
    ])
    assert len(v) == 1
    assert v[0]["champion"] == "Ahri"
    assert v[0]["verdict"] == "PASS"


# --- (e) a 'lockfile rotated' line counts as a restart (even same port) -------
def test_e_lockfile_rotated_counts_as_restart():
    v = classify_events([CONNECT(100), RECONNECT_ROTATED(100),
                         CS_ENTER(), APPLYING("Ahri", "aram")])
    assert len(v) == 1
    assert v[0]["restart_reason"] == "lockfile_rotated"
    assert v[0]["verdict"] == "PASS"


# --- extra coverage ----------------------------------------------------------
def test_wrote_success_line_is_pass():
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(), WROTE("Ahri Aram")])
    assert len(v) == 1
    assert v[0]["verdict"] == "PASS"


def test_rune_write_failed_is_fail_and_parses_champ():
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(), FAIL("Ahri", "aram")])
    assert len(v) == 1
    assert v[0]["verdict"] == "FAIL"
    assert v[0]["champion"] == "Ahri"
    assert v[0]["mode"] == "aram"


def test_lockfile_gap_then_connect_is_restart_even_same_port():
    v = classify_events([CONNECT(100), LOCKFILE_GAP(), CONNECT(100),
                         CS_ENTER(), APPLYING("Ahri", "aram")])
    assert len(v) == 1
    assert v[0]["restart_reason"] == "lockfile_gap"
    assert v[0]["verdict"] == "PASS"


def test_same_port_reconnect_is_not_a_restart():
    # An RC-only restart reconnects on the SAME port with no gap/rotation; that
    # is NOT a League restart, so the following champ-select is not an A1 case.
    assert classify_events([CONNECT(100), CONNECT(100),
                            CS_ENTER(), APPLYING("Ahri", "aram")]) == []


def test_cs_end_with_no_push_after_restart_is_fail():
    # The pure A1-regression signature: restart, enter, champ select ends with
    # no 'applying runes' ever logged.
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(), CS_END()])
    assert len(v) == 1
    assert v[0]["verdict"] == "FAIL"


def test_failure_takes_precedence_over_applying():
    # A real write-failure logs 'applying runes' first, then the failure. The
    # verdict must be FAIL, not PASS.
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER(),
                         APPLYING("Ahri", "aram"), GAVEUP(3), FAIL("Ahri", "aram")])
    assert len(v) == 1
    assert v[0]["verdict"] == "FAIL"


def test_open_window_at_eof_is_pending():
    # Restart + enter but no push/failure/re-arm within the provided lines: the
    # pure core reports PENDING; the live wrapper's wall-clock timeout converts a
    # lingering PENDING to FAIL.
    v = classify_events([CONNECT(100), CONNECT(200), CS_ENTER()])
    assert len(v) == 1
    assert v[0]["verdict"] == "PENDING"


def test_multiple_games_each_after_restart_yield_a_verdict_each():
    v = classify_events([
        CONNECT(100), CONNECT(200), CS_ENTER(), APPLYING("Ahri", "aram"), CS_END(),
        CONNECT(300), CS_ENTER(), APPLYING("Zed", "aram"),
    ])
    assert len(v) == 2
    assert v[0]["champion"] == "Ahri" and v[0]["verdict"] == "PASS"
    assert v[1]["champion"] == "Zed" and v[1]["verdict"] == "PASS"


def test_render_verdict_md_contains_key_fields():
    rec = {
        "timestamp": "2026-07-11T12:00:00", "verdict": "PASS",
        "port_before": 100, "port_after": 200, "restart_reason": "port_change",
        "champion": "Ahri", "mode": "aram",
        "matched": ["RuneWriter: champion=Ahri mode=aram - applying runes"],
    }
    md = render_verdict_md(rec)
    assert "PASS" in md
    assert "Ahri" in md
    assert "100" in md and "200" in md
    assert "A1" in md  # names the gated item it validates


# --- share-lock fix: the day-log open must NOT block RC's log rotation --------
def test_open_shared_allows_rename_while_open(tmp_path):
    # core/log_setup.py DailyRotatingFileHandler does 3 MB size rotation, RENAMING
    # the live YYYY-MM-DD.log -> .log.1 mid-day. On Windows a plain open("r") lacks
    # FILE_SHARE_DELETE, so that rename raises WinError 32 and the watcher would
    # freeze RC's logging. _open_shared must permit the rename while it is open.
    import os as _os
    from tools.lcu_push_watcher import _open_shared
    p = tmp_path / "2026-07-11.log"
    p.write_text("l1\nl2\n", encoding="utf-8")
    fh = _open_shared(p, seek_end=False)
    assert fh is not None, "share-safe open returned None"
    try:
        dest = tmp_path / "2026-07-11.log.1"
        _os.replace(p, dest)   # RC's rotation rename - must NOT raise while open
        assert dest.exists() and not p.exists()
        assert "l1" in fh.read()   # the open handle still reads the content
    finally:
        fh.close()


def test_open_shared_missing_file_returns_none(tmp_path):
    # Matches the prior _open contract: an unopenable path yields None (the main
    # loop retries next poll), never raises.
    from tools.lcu_push_watcher import _open_shared
    assert _open_shared(tmp_path / "nope.log", seek_end=True) is None
