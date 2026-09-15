# arch: guard - GET /api/moon-sync-status verdict, read-only reads, codes-only wire | section=tests | frozen=no
"""Behaviour tests for dashboard.routes_moon_sync - the read-only JSON route
that reports whether the moon_sync cross-repo poller is still alive.

The route is a thin reader over the poller's own status.md. It never writes,
never creates the state directory, and never puts a note name or a filesystem
path on the wire - only CODES and counts (plan section 6 row 8).

Ground truth this module was written against (each grepped before use):
  dashboard/_dispatch.py:50   `_GET_CACHE` (the registry cache this resets)
  dashboard/_dispatch.py:54   `_gather_get()` (the registry under test)
  dashboard/_matchers.py:20   `equals()` - the matcher factory the route uses
  dashboard/_errors.py:31     `send_error(h, exc, status=500, public_msg=None)`
  tests/test_loop_status_route.py:24-32   the FakeHandler `_send` capture idiom
  tests/test_dashboard_error_scrub_rm134.py:33-34  the LEAKY / FORBIDDEN idiom
  tools/moon_sync_poller.py:122  `state_dir()` - the resolution this mirrors
  tools/moon_sync_poller.py:268  `write_status()` - the status.md header shape

THE RULE IS BOUND TWICE OVER, AT TWO DIFFERENT ALTITUDES, and both bindings
are load-bearing. `test_route_and_poller_agree_on_the_verdict` binds the RULE
(`status_verdict` against `status_verdict`) and is blind to anything either
surface does before calling it.
`test_entry_points_agree_on_the_same_status_md` binds the ENTRY POINTS
(`build_moon_sync_status` against the poller's `status_report`) over one
status.md and is what catches a divergence introduced ABOVE the rule - the
class of bug that once shipped UNMEASURED on the route and STALE on --status
for the identical file. Do not drop either for the other.

TWO TESTS ARE EXPECTED RED IN THE BUILD WORKTREE, BY DESIGN.
`test_route_and_poller_agree_on_the_verdict` and
`test_state_dir_resolution_matches_the_poller` HARD-import
`tools.moon_sync_poller.status_verdict` / `._state_dir_path`, which a sibling
slice is adding in a different worktree. The import sits INSIDE each test body
so an ImportError reds exactly those two and every other test in this module
still collects and runs. There is deliberately NO skip: a skip gated on a
tracked module is a DEFECT skip under tests/test_skip_condition_hygiene.py and
would survive the merge, quietly retiring the only check that binds the route's
verdict to the poller's. After the rebase onto a main that carries both
symbols, all of this module must be green with zero skips.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from dashboard import routes_moon_sync as mod

# Same leak-shaped exception text and forbidden-token set the RM-134 envelope
# guard uses, so the two surfaces cannot drift apart in what "scrubbed" means.
LEAKY = r"unable to open database file at C:\Riot Commander\data\rewind_history.db (ZORBLEAK)"
FORBIDDEN = ("ZORBLEAK", "rewind_history.db", "C:\\", "Riot Commander", "OperationalError")

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


class FakeHandler:
    """Minimal handler stand-in capturing the _send(status, body, ctype) call."""

    def __init__(self, path: str = "/api/moon-sync-status") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _header(*, checked=NOW, interval=300, pid=4242, expect=None, fault=None,
            boot=None, unmapped=None, prompt_half=None, body_lines=()) -> str:
    """Build a synthetic status.md in the poller's own header shape."""
    lines = ["# moon_sync cross-repo poller", ""]
    if checked is not None:
        lines.append(f"- checked: {_iso(checked)}")
    lines.append("- desktop+prompt idle: 12s")
    if interval is not None:
        lines.append(f"- next interval: {interval}s")
    if pid is not None:
        lines.append(f"- pid: {pid}")
    if expect is not None:
        lines.append(f"- expect next poll by: {_iso(expect)}")
    if fault is not None:
        lines.append(f"- fault: {fault}")
    if boot is not None:
        lines.append(f"- boot: {boot}")
    if unmapped is not None:
        lines.append(f"- unmapped roots: {unmapped}")
    if prompt_half is not None:
        lines.append(f"- prompt half: {prompt_half}")
    lines.append("")
    lines.extend(body_lines)
    return "\n".join(lines) + "\n"


@pytest.fixture
def statedir(tmp_path, monkeypatch):
    """Point the route's state-dir resolution at a tmp sandbox via the env var
    it really reads - no module attribute is patched, so the resolution rule
    itself stays under test."""
    d = tmp_path / "moonsync"
    d.mkdir()
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(d))
    return d


def _serve(handler) -> tuple:
    mod._serve_moon_sync_status(handler)
    assert handler.sent is not None, "_send was never called"
    status, body, ctype = handler.sent
    return status, json.loads(body.decode("utf-8")), ctype


# ------------------------------------------------------------------ registry
def test_route_is_registered_on_8888(monkeypatch):
    """The route must be reachable through the real :8888 GET registry.

    Asserted by HANDLER IDENTITY, not by a substring of _dispatch.py's source:
    a source-text guard passes on a commented-out line and fails on a rename
    for the wrong reason.
    """
    from dashboard import _dispatch

    # Building the WHOLE registry imports routes_state -> _liveclient ->
    # core.vision_token, which raises at import time unless a token is
    # resolvable (core/vision_token.py:86). CI supplies one workflow-wide
    # (tests/test_ci_vision_token_env.py) but a bare checkout has no gitignored
    # config/vision_token.txt, so this test supplies its own rather than
    # depending on machine-local state it does not test.
    monkeypatch.setenv("RC_VISION_TOKEN", "registry-import-token")
    monkeypatch.setattr(_dispatch, "_GET_CACHE", None)
    routes = _dispatch._gather_get()
    hits = [h for matcher, h in routes if matcher("/api/moon-sync-status")]
    assert hits == [mod._serve_moon_sync_status]
    # The matcher must not swallow neighbouring paths.
    assert not any(m("/api/moon-sync-status-extra") for m, _ in routes)


# -------------------------------------------------------------- absent status
def test_absent_status_is_loud_not_empty(statedir):
    """No status.md is UNMEASURED, never a fabricated DEAD and never an empty 200."""
    assert not (statedir / "status.md").exists()
    status, payload, ctype = _serve(FakeHandler())
    assert status == 200
    assert ctype == "application/json"
    assert payload["status_missing"] is True
    assert payload["verdict"] == "UNMEASURED"
    assert payload["checked"] is None
    assert payload["pid_alive"] is None
    assert payload["per_code"] == []
    assert payload["updated_at"]


# ------------------------------------------------------------- verdict table
def _verdict_for(statedir, monkeypatch, text, *, pid_alive=True, now=NOW):
    (statedir / "status.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: pid_alive)
    monkeypatch.setattr(mod, "_now", lambda: now)
    return _serve(FakeHandler())[1]


def test_verdict_six_way_table(statedir, monkeypatch):
    # LIVE - fresh stamp, expect still in the future, pid alive.
    live = _verdict_for(statedir, monkeypatch, _header(expect=NOW + timedelta(minutes=5)))
    assert live["verdict"] == "LIVE"
    assert live["fleet_view"] is True
    assert live["pid"] == 4242

    # OVERDUE - the promised next poll is in the past.
    over = _verdict_for(statedir, monkeypatch, _header(expect=NOW - timedelta(minutes=1)))
    assert over["verdict"] == "OVERDUE"

    # STALE - no expect line, but the stamp is older than 2x promise + 60s.
    stale = _verdict_for(
        statedir, monkeypatch,
        _header(checked=NOW - timedelta(seconds=700), interval=300))
    assert stale["verdict"] == "STALE"

    # TIER CLIMB - 6 minutes old against a 5 minute promise is still LIVE, and
    # only a reader that actually reads the promise says so (a hardcoded 60s
    # default would call this STALE).
    climb = _verdict_for(
        statedir, monkeypatch,
        _header(checked=NOW - timedelta(seconds=360), interval=300))
    assert climb["verdict"] == "LIVE"

    # DEAD - the recorded pid is provably gone.
    dead = _verdict_for(
        statedir, monkeypatch,
        _header(expect=NOW + timedelta(minutes=5)), pid_alive=False)
    assert dead["verdict"] == "DEAD"
    assert dead["pid_alive"] is False

    # ACCESS DENIED - an unprobeable pid is None, never False, so never DEAD.
    denied = _verdict_for(
        statedir, monkeypatch,
        _header(expect=NOW + timedelta(minutes=5)), pid_alive=None)
    assert denied["pid_alive"] is None
    assert denied["verdict"] == "LIVE"

    # PRE-FLEET-VIEW - a header with no pid line is graded by TIME alone.
    pre = _verdict_for(
        statedir, monkeypatch,
        _header(pid=None, expect=NOW - timedelta(minutes=1)), pid_alive=False)
    assert pre["fleet_view"] is False
    assert pre["pid"] is None
    assert pre["pid_alive"] is None
    assert pre["verdict"] == "OVERDUE"

    # FAULT - a fault line outranks a fresh stamp and a live pid.
    fault = _verdict_for(
        statedir, monkeypatch,
        _header(expect=NOW + timedelta(minutes=5), fault="SEEN_STORE_UNREADABLE"))
    assert fault["verdict"] == "FAULT"
    assert fault["fault"] == "SEEN_STORE_UNREADABLE"
    assert fault["per_code"] == []

    # The prompt half is carried as its own fact, and its DEAD state is a flag.
    half = _verdict_for(
        statedir, monkeypatch,
        _header(expect=NOW + timedelta(minutes=5), prompt_half="ping 41s ago DEAD"))
    assert half["prompt_half_dead"] is True
    assert "DEAD" in half["prompt_half"]
    ok_half = _verdict_for(
        statedir, monkeypatch,
        _header(expect=NOW + timedelta(minutes=5), prompt_half="ping 41s ago LIVE"))
    assert ok_half["prompt_half_dead"] is False


def test_fault_before_the_stamp_is_fault_not_unmeasured(statedir, monkeypatch):
    """A poller that faults BEFORE it stamps must grade FAULT, not UNMEASURED.

    The shape is production-reachable: a header carrying `- fault:`, `- pid:`
    and `- next interval:` and NO `- checked:` line. THE ONE RULE makes FAULT
    step 1 and says it outranks everything, so the route's missing-stamp
    shortcut must not pre-empt it. `status_missing` stays True regardless - the
    stamp really is absent - so the two facts are reported independently.

    The second arm is the over-correction control: strip the fault line from
    the same shape and the SAME delegation must happen, landing on the rule's
    own no-stamp answer, STALE. It must NOT be UNMEASURED - UNMEASURED means
    the file is ABSENT, and this file exists - so "fault first" still cannot be
    implemented as "never delegate", and the pre-rule gate still cannot be
    widened back to swallow an existing header. `status_missing` stays True on
    BOTH arms: it is the separate, wider "no usable stamp" wire fact, not the
    predicate that selects UNMEASURED.
    """
    faulted = _verdict_for(
        statedir, monkeypatch,
        _header(checked=None, fault="SEEN_STORE_UNREADABLE"))
    assert faulted["verdict"] == "FAULT"
    assert faulted["fault"] == "SEEN_STORE_UNREADABLE"
    assert faulted["status_missing"] is True
    assert faulted["checked"] is None
    assert faulted["status_age_s"] is None

    clean = _verdict_for(statedir, monkeypatch, _header(checked=None))
    assert clean["verdict"] == "STALE"
    assert clean["fault"] is None
    assert clean["status_missing"] is True


# ------------------------------------------------------------------ read-only
def _snapshot(d):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(d.rglob("*")) if p.is_file()}


def test_route_reads_only_and_creates_nothing(statedir, tmp_path, monkeypatch):
    (statedir / "status.md").write_text(_header(), encoding="utf-8")
    (statedir / "poller_seen.json").write_text("{}", encoding="utf-8")
    before = _snapshot(statedir)
    before_names = sorted(p.name for p in statedir.iterdir())

    monkeypatch.setattr(mod, "_pid_alive", lambda pid: True)
    status, _payload, _ctype = _serve(FakeHandler())
    assert status == 200

    assert _snapshot(statedir) == before
    assert sorted(p.name for p in statedir.iterdir()) == before_names

    # The absent-directory arm: a mkdir anywhere in the read path shows up here
    # and nowhere else.
    absent = tmp_path / "never-created"
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(absent))
    status, payload, _ctype = _serve(FakeHandler())
    assert status == 200
    assert payload["verdict"] == "UNMEASURED"
    assert not absent.exists()


# ------------------------------------------------------------ codes-only wire
def test_payload_carries_codes_only(statedir, monkeypatch):
    body = [
        "## fleet",
        "- SA: 12 entries, +1 new, -0 withdrawn, LIVE",
        "- SB: 4 entries, +0 new, -2 withdrawn, STALE",
        "",
    ]
    text = _header(
        expect=NOW + timedelta(minutes=5),
        fault=r"SEEN_STORE_UNREADABLE at C:\Some Sibling\moon_sync_inbox",
        unmapped=r"C:\Some Sibling, C:\Another One",
        body_lines=body)
    payload = _verdict_for(statedir, monkeypatch, text)

    codes = [row["code"] for row in payload["per_code"]]
    assert codes == ["SA", "SB"]
    assert payload["per_code"][0]["entries"] == 12
    assert payload["per_code"][0]["arrivals"] == 1
    assert payload["per_code"][0]["withdrawals"] == 0
    assert payload["per_code"][0]["status"] == "LIVE"
    assert payload["per_code"][1]["withdrawals"] == 2
    # Counted, never named - a root list cannot become a path list on the wire.
    assert payload["unmapped_roots"] == 2

    blob = json.dumps(payload)
    assert re.search(r"[A-Za-z]:[\\/]", blob) is None, blob
    assert "Sibling" not in blob
    assert "name" not in payload and "names" not in payload
    for row in payload["per_code"]:
        assert "name" not in row and "names" not in row


# ------------------------------------------------------------- error envelope
def test_route_fault_uses_scrubbed_error_envelope(statedir, monkeypatch):
    (statedir / "status.md").write_text(_header(), encoding="utf-8")

    def _boom(_text):
        raise OSError(LEAKY)

    monkeypatch.setattr(mod, "parse_status_header", _boom)
    status, payload, ctype = _serve(FakeHandler())
    assert status == 500
    assert ctype == "application/json"
    blob = json.dumps(payload)
    for needle in FORBIDDEN:
        assert needle not in blob, f"raw exception text leaked: {blob!r}"


# --------------------------------------------------------- parity with poller
# The two tests below are the only binding between this route's duplicated
# ONE RULE and the poller's own. Both hard-import inside the body on purpose -
# see the module docstring for why there is no skip.

# Every spelling the poller's status_verdict parameters might legitimately
# carry, mapped to the same six facts. A parameter name outside this table is a
# real parity break and must fail loudly rather than be defaulted around.
def _facts(*, fault, pid_alive, checked, expect, interval_s, now) -> dict:
    epoch = (lambda d: None if d is None else d.timestamp())
    return {
        "fault": fault,
        "pid_alive": pid_alive,
        "checked": checked,
        "checked_at": checked,
        "checked_dt": checked,
        "checked_epoch": epoch(checked),
        "expect": expect,
        "expect_next_poll_by": expect,
        "expect_dt": expect,
        "expect_epoch": epoch(expect),
        "interval_s": interval_s,
        "interval": interval_s,
        "next_interval_s": interval_s,
        "promised_interval_s": interval_s,
        "now": now,
        "now_dt": now,
        "now_epoch": epoch(now),
    }


def _call_by_name(fn, facts):
    """Call `fn` binding every parameter by NAME from `facts`.

    Order-insensitive on purpose: the parity this test asserts is over the
    RULE, not over an argument order that either side may refactor.
    """
    sig = inspect.signature(fn)
    kwargs = {}
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if name in facts:
            kwargs[name] = facts[name]
        elif param.default is not inspect.Parameter.empty:
            continue
        else:
            raise AssertionError(
                f"poller status_verdict has required parameter {name!r}, which "
                "this route supplies no fact for - the two ONE RULE copies have "
                "diverged; reconcile them rather than widening this table")
    return fn(**kwargs)


_CASES = (
    # label, fault, pid_alive, checked_delta_s, expect_delta_s, interval_s, expected
    ("live", None, True, 0, 300, 300, "LIVE"),
    ("overdue", None, True, -400, -60, 300, "OVERDUE"),
    ("stale", None, True, -700, None, 300, "STALE"),
    ("dead", None, False, 0, 300, 300, "DEAD"),
    ("pre_fleet_view", None, None, -400, -60, 300, "OVERDUE"),
    ("fault", "SEEN_STORE_UNREADABLE", True, 0, 300, 300, "FAULT"),
    ("access_denied", None, None, 0, 300, 300, "LIVE"),
    ("tier_climb", None, True, -360, None, 300, "LIVE"),
    # The promise has passed AND the stamp is older than 2*interval+60, so the
    # STALE step must be reached BEFORE the OVERDUE step. This row exists to
    # make the ordering fail loudly: reinstate an OVERDUE-first rule on either
    # side and it reds immediately. The `stale` row above now discriminates the
    # same ordering, but only as a side effect of the promise being derived
    # inside the rule; this one pins it by intent.
    ("long_dead", None, True, -5000, -4640, 300, "STALE"),
    # No stamp AND no promise. This is NOT UNMEASURED: UNMEASURED lives ABOVE
    # the rule on both sides - it is the ABSENT-FILE verdict, emitted by
    # build_moon_sync_status's `text is None` gate before delegating and by the
    # poller's own --status absent-file branch. A file that exists but carries
    # no parseable stamp cannot be graded by time, and both copies answer
    # STALE. The pre-rule verdict is bound by test_absent_status_is_loud_not_empty,
    # by the absent-directory arm of test_route_reads_only_and_creates_nothing,
    # and by the second arm of test_fault_before_the_stamp_is_fault_not_unmeasured.
    # None of those can see a divergence introduced ABOVE the rule on only ONE
    # surface, which is what test_entry_points_agree_on_the_same_status_md is for.
    ("no_stamp_no_promise", None, None, None, None, None, "STALE"),
)


def _case_facts(checked_d, expect_d, interval_s, fault, pid_alive) -> dict:
    checked = None if checked_d is None else NOW + timedelta(seconds=checked_d)
    expect = None if expect_d is None else NOW + timedelta(seconds=expect_d)
    return _facts(fault=fault, pid_alive=pid_alive, checked=checked,
                  expect=expect, interval_s=interval_s, now=NOW)


def test_route_verdict_case_table():
    """The route's own half of the parity table, asserted unconditionally.

    Without this the case table would only ever be exercised by the parity
    test, which is red until the poller symbol lands - so a rule regression
    could hide inside an expected failure.
    """
    for label, fault, pid_alive, checked_d, expect_d, interval_s, expected in _CASES:
        facts = _case_facts(checked_d, expect_d, interval_s, fault, pid_alive)
        got = _call_by_name(mod.status_verdict, facts)
        assert got == expected, f"{label}: route said {got}, table says {expected}"


def test_route_and_poller_agree_on_the_verdict():
    from tools.moon_sync_poller import status_verdict as poller_verdict

    for label, fault, pid_alive, checked_d, expect_d, interval_s, expected in _CASES:
        facts = _case_facts(checked_d, expect_d, interval_s, fault, pid_alive)
        mine = _call_by_name(mod.status_verdict, facts)
        theirs = _call_by_name(poller_verdict, facts)
        assert mine == expected, f"{label}: route said {mine}, table says {expected}"
        assert theirs == mine, f"{label}: poller said {theirs}, route said {mine}"


def test_state_dir_resolution_matches_the_poller(tmp_path, monkeypatch):
    from tools.moon_sync_poller import _state_dir_path as poller_state_dir

    override = tmp_path / "override"
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(override))
    assert mod._state_dir_path() == poller_state_dir()

    monkeypatch.delenv("RC_MOON_SYNC_STATE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert mod._state_dir_path() == poller_state_dir()


# -------------------------------------------------- parity at the ENTRY POINTS
# THE RULE-LEVEL PARITY TEST ABOVE IS NOT ENOUGH, and this module is where that
# was proved. `test_route_and_poller_agree_on_the_verdict` binds
# `status_verdict` to `status_verdict`; it is blind to anything either surface
# does BEFORE calling the rule. A divergence lived in exactly that blind spot -
# the route's pre-rule gate intercepted an existing-but-unstampable status.md
# and answered UNMEASURED while the poller's --status delegated to the rule and
# printed STALE - and it survived a full reconciliation pass of the rule
# because nothing in the suite had ever driven the two ENTRY POINTS over one
# file. These tests do that: one status.md, one temp state dir, both surfaces,
# compare the VERDICT (never the prose, which differs by design).

_VERDICT_LINE = re.compile(r"^verdict ([A-Z]+)$")


def _poller_verdict_from_status_report(poller, state_dir, tmp_path, now_epoch) -> str:
    """The verdict the poller's own --status would print over `state_dir`.

    `status_report` is the narrowest entry point that produces it: main()'s
    --status branch only prints what this returns. Every out-of-tmp read the
    report makes for UNRELATED facts (desktop idle, the prompt-half ladder, the
    pid probe) is pinned here, so the only thing that can move the verdict is
    the status.md under test.
    """
    lines = poller.status_report(
        now=now_epoch,
        state_path=state_dir,
        repos=(),
        self_root=str(tmp_path),
    )
    hits = [m.group(1) for m in (_VERDICT_LINE.match(ln) for ln in lines) if m]
    assert len(hits) == 1, f"expected exactly one verdict line, got {lines!r}"
    return hits[0]


@pytest.fixture
def entry_points(tmp_path, monkeypatch):
    """Both surfaces, pinned to one temp state dir and one fixed clock.

    Neither side may touch the real %LOCALAPPDATA%/moonsync and neither may
    write anything: the route gets the env override it really reads, and the
    poller gets `state_path` passed explicitly.
    """
    from tools import moon_sync_poller as poller

    state = tmp_path / "moonsync"
    state.mkdir()
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(state))

    # Facts that are not the status.md under test, pinned on both sides so a
    # machine-local answer can never move a verdict.
    monkeypatch.setattr(mod, "_now", lambda: NOW)
    monkeypatch.setattr(mod, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(poller, "_pid_alive_detail", lambda pid: (True, "yes"))
    monkeypatch.setattr(poller, "effective_idle_seconds", lambda now=None: 12.0)
    monkeypatch.setattr(
        poller, "prompt_half",
        lambda now=None, self_root=None: ("last ping 1s via repo-root", False))

    def _both(text: str | None) -> tuple[str, str]:
        target = state / "status.md"
        if text is None:
            if target.exists():
                target.unlink()
        else:
            target.write_text(text, encoding="utf-8")
        route = mod.build_moon_sync_status()["verdict"]
        poll = _poller_verdict_from_status_report(
            poller, state, tmp_path, NOW.timestamp())
        return route, poll

    return _both


# label -> the status.md text under test (None means no file at all).
_ENTRY_POINT_CASES = (
    # The file is genuinely absent. Both surfaces answer from their OWN
    # pre-rule absent-file branch, and UNMEASURED is what that branch means.
    ("absent", None, "UNMEASURED"),
    # The file EXISTS and carries no `- checked:` line at all. This is the case
    # that diverged: the route said UNMEASURED, the poller said STALE.
    ("exists_no_stamp", _header(checked=None), "STALE"),
    # The file EXISTS and the checked line is present but will not parse. Same
    # answer by the same route through the rule - a stamp that cannot be read
    # is not a stamp.
    ("exists_bad_stamp",
     _header(checked=None).replace(
         "- desktop+prompt idle: 12s",
         "- checked: not-a-timestamp\n- desktop+prompt idle: 12s"),
     "STALE"),
    # Cheap extensions, so the test also fails if agreement is achieved by
    # collapsing every existing file to one verdict.
    ("healthy", _header(expect=NOW + timedelta(minutes=5)), "LIVE"),
    ("faulted",
     _header(expect=NOW + timedelta(minutes=5), fault="SEEN_STORE_UNREADABLE"),
     "FAULT"),
)


def test_entry_points_agree_on_the_same_status_md(entry_points):
    """Drive BOTH entry points over the same status.md and compare verdicts.

    Asserted on the verdict token, never on prose: the route returns JSON and
    the poller returns report lines, and holding those to each other would bind
    formatting rather than meaning. The expected column is asserted too, so the
    pair cannot agree on a wrong answer and pass.
    """
    for label, text, expected in _ENTRY_POINT_CASES:
        route, poll = entry_points(text)
        assert route == poll, (
            f"{label}: the two entry points disagree over one status.md - "
            f"route said {route}, poller --status said {poll}")
        assert route == expected, f"{label}: both said {route}, table says {expected}"


def test_entry_point_parity_fixture_writes_nothing_outside_tmp(entry_points, tmp_path):
    """The parity fixture must not create or touch the real state dir.

    A parity test that quietly reads %LOCALAPPDATA%/moonsync would agree with
    itself on whatever the live poller happened to have written, which is the
    one way this test could pass while proving nothing.
    """
    import os

    real = mod._state_dir_path()
    assert str(tmp_path) in str(real), f"route still resolves outside tmp: {real}"
    assert os.environ["RC_MOON_SYNC_STATE"] == str(tmp_path / "moonsync")

    entry_points(_header())
    written = sorted(p.name for p in (tmp_path / "moonsync").iterdir())
    assert written == ["status.md"], written
