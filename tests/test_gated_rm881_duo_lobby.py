"""tools/gated_rm881_duo_lobby.py - the G1-07 read-back (s144 lane gated cycle 16).

Read-only plumbing for the next live lobby; nothing here ticks a row. The trace
lines are produced by the real ``dashboard/_handler.py`` ``Handler.log_message``
through the day log's own format string (pinned against ``core/log_setup.py``),
and the SR queue set is parsed from the real ``web/js/main.js``, so a change in
either breaks a test here. All lobby data is synthetic; no Riot id appears.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from dashboard._handler import Handler
from tools import gated_rm881_duo_lobby as g

ROOT = Path(__file__).resolve().parent.parent
VERBOSE_FMT = ("%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-20s "
               "[%(filename)s:%(lineno)d] %(message)s")
SR = g.sr_queue_ids((ROOT / "web" / "js" / "main.js").read_text(encoding="utf-8"))


def _trace(requestline: str, code: str = "200") -> str:
    """One day-log line, as the real handler + the real file format write it."""
    records: list[logging.LogRecord] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    lg = logging.getLogger("rc.web_dashboard")
    grab = _Grab(level=logging.DEBUG)
    old = lg.level
    lg.addHandler(grab)
    lg.setLevel(logging.DEBUG)
    try:
        h = Handler.__new__(Handler)
        h.client_address = ("127.0.0.1", 50000)
        h.log_message('"%s" %s %s', requestline, code, "-")
    finally:
        lg.removeHandler(grab)
        lg.setLevel(old)
    assert records, "log_message emitted nothing"
    return logging.Formatter(VERBOSE_FMT, datefmt="%H:%M:%S").format(records[-1])


def _at(line: str, hhmmss: str) -> str:
    return hhmmss + line[8:]


def _state(size: int = 2, qid: int = 420, first: str = "BOTTOM", phase: str = "Lobby") -> dict:
    me = {"is_self": True, "position_preferences": {"first_preference": first,
                                                     "second_preference": "UNSELECTED"}}
    return {"lcu": {"phase": phase, "lobby": {
        "queue_id": qid, "party_size": size, "members": [me] + [{}] * (size - 1),
        "local_member": me}}}


def test_day_log_format_is_the_one_core_log_setup_writes():
    src = (ROOT / "core" / "log_setup.py").read_text(encoding="utf-8")
    assert '"%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-20s "' in src
    assert '"[%(filename)s:%(lineno)d] %(message)s"' in src


def test_route_is_not_suppressed_from_the_trace():
    from dashboard import _handler
    assert not any(n in "GET /api/duo-synergy?my_role=bot" for n in _handler._SUPPRESS_LOG_PATHS)


def test_sr_set_parsed_from_main_js():
    assert {400, 420, 440}.issubset(SR)
    assert 450 not in SR and 1700 not in SR and 2400 not in SR


def test_real_trace_line_is_parsed():
    line = _trace("GET /api/duo-synergy?my_role=sup&top_n=4 HTTP/1.1")
    t = line[:8]
    assert g.read_traces([line], t, t) == [(t, "GET", "/api/duo-synergy?my_role=sup&top_n=4", 200)]


def test_expected_query_role_mapping_mirrors_the_js():
    js = (ROOT / "web" / "js" / "panels" / "lobby_duo_synergy.js").read_text(encoding="utf-8")
    assert '=== "UTILITY" ? "sup" : "bot"' in js and "const TOP_N = 4;" in js
    assert g.expected_query(_state(first="UTILITY"), SR)[0] == {"my_role": "sup", "top_n": "4"}
    assert g.expected_query(_state(first="BOTTOM"), SR)[0] == {"my_role": "bot", "top_n": "4"}
    assert g.expected_query(_state(first="UNSELECTED"), SR)[0]["my_role"] == "bot"


def test_expected_query_refuses_what_the_controller_skips():
    assert g.expected_query(_state(size=1), SR)[0] is None
    assert g.expected_query(_state(qid=450), SR)[0] is None
    assert g.expected_query(_state(phase="ChampSelect"), SR)[0] is None
    assert g.expected_query({"lcu": {"phase": "Lobby"}}, SR)[0] is None
    assert g.expected_query(_state(), frozenset())[0] is None


WANT = {"my_role": "bot", "top_n": "4"}


def _tr(path: str, code: str = "200", t: str = "12:00:05") -> list:
    return g.read_traces([_at(_trace(f"GET {path} HTTP/1.1", code), t)], "12:00:00", "12:01:00")


def test_sent_pass_on_one_expected_get():
    v, notes = g.grade_sent(_tr("/api/duo-synergy?my_role=bot&top_n=4"), WANT, 1)
    assert v == "PASS", notes


def test_sent_no_result_when_trace_absent():
    assert g.grade_sent([], WANT, 1)[0] == "NO_RESULT"


def test_sent_fail_cases():
    other = _tr("/api/health/all")
    assert g.grade_sent(other, WANT, 1)[0] == "FAIL"
    assert g.grade_sent(_tr("/api/duo-synergy?my_role=bot&top_n=4", "500"), WANT, 1)[0] == "FAIL"
    assert g.grade_sent(_tr("/data/ui_mock/duo_synergy.json"), WANT, 1)[0] == "FAIL"
    assert g.grade_sent(_tr("/api/duo-synergy?my_role=sup&top_n=4"), WANT, 1)[0] == "FAIL"
    two = _tr("/api/duo-synergy?my_role=bot&top_n=4") + _tr(
        "/api/duo-synergy?my_role=bot&top_n=4", t="12:00:07")
    assert g.grade_sent(two, WANT, 1)[0] == "FAIL"
    assert g.grade_sent(two, WANT, 2)[0] == "PASS"


def test_spread_out_refires_are_not_spam():
    """A re-formed party, a role flip and back, or a reload re-fires by design."""
    apart = _tr("/api/duo-synergy?my_role=bot&top_n=4") + _tr(
        "/api/duo-synergy?my_role=bot&top_n=4", t="12:00:40")
    assert g.grade_sent(apart, WANT, 1)[0] == "NO_RESULT"
    burst = apart + _tr("/api/duo-synergy?my_role=bot&top_n=4", t="12:00:42")
    assert g.grade_sent(burst, WANT, 1)[0] == "FAIL"


def test_default_logs_include_rotated_files(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    for name in ("2026-01-02.log", "2026-01-02.log.1", "2026-01-02.log.3", "2026-01-02.log.bak",
                 "2026-01-03.log"):
        (logs / name).write_text("", encoding="utf-8")
    got = [p.name for p in g.default_logs("2026-01-02", base=tmp_path)]
    assert got == ["2026-01-02.log.3", "2026-01-02.log.1", "2026-01-02.log"]


def test_window_excludes_lines_outside():
    line = _at(_trace("GET /api/duo-synergy?my_role=bot&top_n=4 HTTP/1.1"), "11:59:59")
    assert g.read_traces([line], "12:00:00", "12:01:00") == []


def test_main_end_to_end(tmp_path, capsys):
    st = tmp_path / "state.json"
    st.write_text(json.dumps(_state()), encoding="utf-8")
    log = tmp_path / "day.log"
    log.write_text("\n".join([
        _at(_trace("GET /api/health/all HTTP/1.1"), "12:00:01"),
        _at(_trace("GET /api/duo-synergy?my_role=bot&top_n=4 HTTP/1.1"), "12:00:03"),
        "12:00:04.000 INFO     rc.other             [x.py:1] unrelated",
    ]) + "\n", encoding="utf-8")
    rc = g.main(["--state", str(st), "--since", "12:00:00", "--until", "12:00:10",
                 "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 0 and "sent   PASS" in out
    assert "127.0.0.1" not in out
    rc = g.main(["--state", str(st), "--since", "13:00:00", "--until", "13:00:10",
                 "--log", str(log)])
    assert rc == 1 and "NO_RESULT" in capsys.readouterr().out
    rc = g.main(["--state", str(st), "--since", "12:00:00", "--until", "12:00:05",
                 "--log", str(log)])
    assert rc == 1 and "window shorter" in capsys.readouterr().out
    st.write_text(json.dumps(_state(size=1)), encoding="utf-8")
    rc = g.main(["--state", str(st), "--since", "12:00:00", "--until", "12:00:10",
                 "--log", str(log)])
    assert rc == 1 and "lobby  NO_RESULT" in capsys.readouterr().out


def test_tool_is_read_only_source():
    src = (ROOT / "tools" / "gated_rm881_duo_lobby.py").read_text(encoding="utf-8")
    for bad in ("write_text", "unlink", "urlopen", "requests", "subprocess", ".replace(", "open("):
        assert bad not in src, bad
