# arch: guard - /api/moon-sync-status parses status.md like the poller, never 500s on junk | section=tests | frozen=no
"""s144 true-audit of dashboard/routes_moon_sync.py.

The route is a second reader of the poller's status.md, and its module
docstring binds it to the poller at TWO altitudes: the rule
(``status_verdict``) and the entry points (``build_moon_sync_status`` against
the poller's ``status_report``). The existing guard
(tests/test_moon_sync_status_route.py) drives the entry points over five
writer-shaped files. This module drives them over the files the audit found
they disagree on, plus the inputs that turned the route into a 500.

Ground truth each test was written against (read before use):
  tools/moon_sync_poller.py  parse_status_header  the poller's line grammar:
      "- " prefix, exact "checked: " / "next interval: " / "pid: " keys,
      int(...) parsing with ValueError -> None, "participants map absent: N",
      prompt_half_dead = endswith("DEAD")
  tools/moon_sync_poller.py  _parse_iso  datetime.fromisoformat(..).timestamp(),
      which reads a NAIVE stamp as LOCAL time
  tools/moon_sync_poller.py  _render_status  the Fleet rows the writer emits:
      "- <code>: <n> entries, +<new> -<gone>[, newest: <names>], +<k> more -
      findings.json" for OK, "- <code>: INBOX ABSENT", "- <code>: SCAN FAULT X"
  tools/moon_sync_poller.py  code_for  "UNMAPPED-<n>" for a root with no code
  dashboard/routes_moon_sync.py  build_moon_sync_status / _serve_moon_sync_status

The naive-stamp case can only fail on a box whose local zone is not UTC (the
two readings coincide there). It is asserted, not skipped, so on a UTC box it
passes vacuously; the box this was written on is UTC-5/-6.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from dashboard import routes_moon_sync as mod

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


class FakeHandler:
    def __init__(self) -> None:
        self.path = "/api/moon-sync-status"
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _lines(*extra: str, checked: str | None = _iso(NOW), interval: str | None = "300s",
           pid: str | None = None) -> str:
    out = ["# moon_sync cross-repo poller", ""]
    if checked is not None:
        out.append(f"- checked: {checked}")
    if interval is not None:
        out.append(f"- next interval: {interval}")
    if pid is not None:
        out.append(f"- pid: {pid}")
    out.extend(extra)
    out.append("")
    return "\n".join(out) + "\n"


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "moonsync"
    d.mkdir()
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(d))
    monkeypatch.setattr(mod, "_now", lambda: NOW)
    return d


def _serve(state_dir, text: str | bytes) -> tuple[int, dict]:
    target = state_dir / "status.md"
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_bytes(text.encode("utf-8"))
    h = FakeHandler()
    mod._serve_moon_sync_status(h)
    assert h.sent is not None
    status, body, ctype = h.sent
    assert ctype == "application/json"
    return status, json.loads(body.decode("utf-8"))


@pytest.fixture
def poller(monkeypatch):
    from tools import moon_sync_poller as p

    monkeypatch.setattr(p, "_pid_alive_detail", lambda pid: (None, "unknown"))
    monkeypatch.setattr(p, "effective_idle_seconds", lambda now=None: 12.0)
    monkeypatch.setattr(
        p, "prompt_half",
        lambda now=None, self_root=None: ("last ping 1s via repo-root", False))
    return p


def _poller_verdict(p, state_dir, tmp_path) -> str:
    lines = p.status_report(now=NOW.timestamp(), state_path=state_dir, repos=(),
                            self_root=str(tmp_path))
    hits = [ln.split()[1] for ln in lines if ln.startswith("verdict ")]
    assert len(hits) == 1, lines
    return hits[0]


# --------------------------------------------- numbers the route used to 500 on
def test_interval_digit_run_past_the_int_limit_grades_not_500(state, poller, tmp_path):
    """int() refuses a digit run past sys.get_int_max_str_digits() with
    ValueError; the poller catches it (interval None), the route raised."""
    text = _lines(interval="9" * 5000 + "s")
    status, payload = _serve(state, text)
    assert status == 200, payload
    assert payload["next_interval_s"] is None
    assert payload["verdict"] == _poller_verdict(poller, state, tmp_path) == "STALE"


@pytest.mark.parametrize("interval, expected", [
    (str(10 ** 20) + "s", "LIVE"),      # past the timedelta range, positive
    ("-" + str(10 ** 20) + "s", "STALE"),  # past the timedelta range, negative
])
def test_interval_past_the_timedelta_range_grades_like_the_poller(
        state, poller, tmp_path, interval, expected):
    """The poller grades epoch floats and never overflows; the route added a
    timedelta and raised OverflowError."""
    status, payload = _serve(state, _lines(interval=interval))
    assert status == 200, payload
    assert payload["verdict"] == _poller_verdict(poller, state, tmp_path) == expected


def test_stamp_at_the_end_of_the_calendar_grades_not_500(state, poller, tmp_path):
    """checked + interval + 60s past datetime.max overflowed the route."""
    status, payload = _serve(state, _lines(checked="9999-12-31T23:59:30+00:00"))
    assert status == 200, payload
    assert payload["verdict"] == _poller_verdict(poller, state, tmp_path) == "LIVE"


def test_pid_beyond_the_dword_range_is_unprobeable_not_500(state):
    """A Windows pid is a DWORD. ctypes raises ArgumentError past 2**32 and
    os.kill raises OverflowError; neither is an OSError, so the route 500ed.
    Not a provable death either, so it grades by time (None, never False)."""
    status, payload = _serve(state, _lines(pid=str(2 ** 32 + 5)))
    assert status == 200, payload
    assert payload["pid_alive"] is None
    assert payload["verdict"] == "LIVE"
    assert mod._pid_alive(10 ** 30) is None


def test_pid_range_guard_runs_before_any_probe(monkeypatch):
    """The range guard is its own layer: no probe is attempted past the DWORD
    range on either platform branch (the ctypes ArgumentError catch is the
    second layer, pinned by the test above with this guard removed)."""
    import os
    import sys

    calls = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append(pid))
    assert mod._pid_alive(2 ** 32 + 5) is None
    assert calls == []
    assert mod._pid_alive(4242) is True  # positive control: the probe does run
    assert calls == [4242]


def test_unmapped_roots_odd_digit_never_500(state):
    """str.isdigit() is true for a superscript two, which int() refuses."""
    status, payload = _serve(state, _lines("- unmapped roots: \u00b2"))
    assert status == 200, payload
    assert isinstance(payload["unmapped_roots"], int)


def test_undecodable_status_md_still_grades(state):
    """A body byte that is not UTF-8 raised UnicodeDecodeError (a ValueError,
    not the OSError the read caught), so a liveness surface answered 500 for a
    header whose stamp lines were all readable."""
    raw = _lines("## SA", "- NEW: caf\u00e9").encode("utf-8").replace(b"\xc3\xa9", b"\xe9")
    status, payload = _serve(state, raw)
    assert status == 200, payload
    assert payload["verdict"] == "LIVE"


# ------------------------------------- facts the route parsed unlike the poller
def test_naive_stamp_is_read_as_local_time_like_the_poller(state, poller, tmp_path):
    """The poller's _parse_iso calls .timestamp(), which reads a naive stamp
    as LOCAL time; the route read it as UTC, so off UTC the two surfaces
    graded one file hours apart."""
    local_wall = NOW.astimezone().replace(tzinfo=None)
    status, payload = _serve(state, _lines(checked=local_wall.isoformat(timespec="seconds")))
    assert status == 200
    assert payload["status_age_s"] == 0
    assert payload["verdict"] == _poller_verdict(poller, state, tmp_path) == "LIVE"


@pytest.mark.parametrize("line", [
    "- Checked: " + _iso(NOW),          # key case
    "-checked: " + _iso(NOW),           # no space after the dash
    "- checked:" + _iso(NOW),           # no space after the colon
])
def test_header_keys_follow_the_poller_grammar(state, poller, tmp_path, line):
    """The poller only reads the exact writer keys; the route normalised keys
    and stamped a line the poller ignores, grading LIVE against STALE."""
    status, payload = _serve(state, _lines(line, checked=None))
    assert status == 200
    assert payload["verdict"] == _poller_verdict(poller, state, tmp_path) == "STALE"


@pytest.mark.parametrize("value", ["4242abc", "42 42", "1e3"])
def test_pid_parses_like_the_poller(state, poller, value, monkeypatch):
    """The poller takes int(value) or None; the route took the first digit run
    and probed a pid the poller never would."""
    probed = []
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: probed.append(pid) or True)
    status, payload = _serve(state, _lines(pid=value))
    assert status == 200
    assert payload["pid"] == poller.parse_status_header(_lines(pid=value))["pid"] is None
    assert probed == []
    assert payload["fleet_view"] is True


@pytest.mark.parametrize("value", ["1,800s", "5m", "300 s"])
def test_interval_parses_like_the_poller(state, poller, value):
    status, payload = _serve(state, _lines(interval=value))
    assert status == 200
    assert payload["next_interval_s"] == poller.parse_status_header(
        _lines(interval=value))["interval"]


def test_participants_map_absent_line_is_counted(state, poller):
    """The writer's line is "participants map absent: N roots UNMAPPED"; the
    route only knew a route-invented "unmapped roots" key and reported 0."""
    text = _lines("- participants map absent: 2 roots UNMAPPED")
    status, payload = _serve(state, text)
    assert status == 200
    assert payload["unmapped_roots"] == poller.parse_status_header(text)["unmapped_roots"] == 2


@pytest.mark.parametrize("half, dead", [
    ("last ping 9s via legacy DEAD", True),
    ("DEAD reckoning via repo-root", False),
    ("last ping never via none", False),
])
def test_prompt_half_dead_flag_matches_the_poller(state, poller, half, dead):
    text = _lines(f"- prompt half: {half}")
    status, payload = _serve(state, text)
    assert status == 200
    assert payload["prompt_half_dead"] is poller.parse_status_header(text)["prompt_half_dead"] is dead


# ------------------------------------------------------------ Fleet code rows
def _rows(state_dir, *body: str) -> dict:
    status, payload = _serve(state_dir, _lines("", "## Fleet", *body))
    assert status == 200
    return {r["code"]: r for r in payload["per_code"]}


def test_status_token_is_never_read_from_a_note_name(state):
    """The docstring promises a filename fragment is never promoted to a
    status. A note named with STALE in it was."""
    rows = _rows(state, "- SA: 3 entries, +1 -0, newest: 2026-10-27-SA-STALE-ack.md, "
                        "+0 more - findings.json")
    assert rows["SA"]["status"] == "OK"
    assert (rows["SA"]["entries"], rows["SA"]["arrivals"], rows["SA"]["withdrawals"]) == (3, 1, 0)


def test_counts_are_never_read_from_a_note_name(state):
    rows = _rows(state, "- SA: 3 entries, +0 -0, newest: x 7 entries +9 -8.md, "
                        "+0 more - findings.json")
    assert (rows["SA"]["entries"], rows["SA"]["arrivals"], rows["SA"]["withdrawals"]) == (3, 0, 0)


def test_count_digit_run_past_the_int_limit_never_500(state):
    rows = _rows(state, "- SA: " + "7" * 5000 + " entries, +1 -0, +0 more - findings.json")
    assert rows["SA"]["entries"] is None
    assert rows["SA"]["arrivals"] == 1


def test_inbox_absent_row_is_reported_not_dropped(state):
    """The poller made an absent inbox a LOUD row; the route dropped it."""
    rows = _rows(state, "- SA: INBOX ABSENT", "- SB: 2 entries, +0 -0, +0 more - findings.json")
    assert rows["SA"]["status"] == "ABSENT"
    assert rows["SB"]["status"] == "OK"


def test_scan_fault_row_is_fault(state):
    rows = _rows(state, "- SA: SCAN FAULT OSError")
    assert rows["SA"]["status"] == "FAULT"


def test_unmapped_code_row_is_reported_not_dropped(state):
    """code_for() names an unmapped root UNMAPPED-<n>, longer than the 8-char
    code pattern, so its row vanished."""
    rows = _rows(state, "- UNMAPPED-1: 4 entries, +0 -0, +0 more - findings.json")
    assert rows["UNMAPPED-1"]["entries"] == 4


def test_note_body_lines_are_still_never_code_rows(state):
    rows = _rows(state, "## SA", "- NEW: OK-LIVE-STALE.md", "- WITHDRAWN: DEAD.md")
    assert rows == {}


# ------------------------------------------- the entry points, over the new files
_ENTRY_CASES = (
    _lines(interval="9" * 5000 + "s"),
    _lines(interval=str(10 ** 20) + "s"),
    _lines(interval="-" + str(10 ** 20) + "s"),
    _lines(checked="9999-12-31T23:59:30+00:00"),
    _lines("- Checked: " + _iso(NOW), checked=None),
    _lines(checked=NOW.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")),
    _lines(checked=_iso(NOW - timedelta(hours=1))),
)


def test_entry_points_agree_on_every_audit_file(state, poller, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: None)
    for text in _ENTRY_CASES:
        (state / "status.md").write_bytes(text.encode("utf-8"))
        route = mod.build_moon_sync_status()["verdict"]
        assert route == _poller_verdict(poller, state, tmp_path), text[:200]
