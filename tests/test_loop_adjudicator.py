# arch: the loop's single read-only adjudicator + the decommission guard | section=tests | frozen=no
"""ops/loop/adjudicator.py: the loop's external brain.

There is ONE vendor. The loop self-adjudicates - the same vendor that executes a
cycle also directs and audits it - and the read-only guarantee comes from
`--permission-mode plan`, not from asking a different company.

This file was 39 tests of a two-vendor seam until 2026-08-01: a backend
registry, an exhaustion-signature matcher, a sticky one-way failover and a spend
ceiling that governed one vendor while explicitly excluding the other. All of
that machinery was deleted with the vendor, so the tests for it were deleted
too - a test suite that outlives its subject is how a decommission looks
finished while the code is still there.

What replaced them is smaller and load-bearing:
  1. the read-only + non-interactive flags survive (the safety property that
     used to be spread across two backends and could quietly vanish with one);
  2. the None-on-empty sentinel, which the director and auditor both depend on;
  3. spend accounting survives an object rebuild, which is the only reason the
     wrapper class still exists;
  4. THE DECOMMISSION GUARD - the deleted machinery stays deleted, and the
     removed spend ceiling cannot creep back as a cap on the vendor that policy
     says is uncapped.

These are pure-unit guards - the subprocess layer is monkeypatched, so no
network call and no real CLI invocation happens. Loaded by file path (ops/loop
is not a package on sys.path).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

_ADJ = Path(__file__).resolve().parent.parent / "ops" / "loop" / "adjudicator.py"
_LOOP = Path(__file__).resolve().parent.parent / "ops" / "loop"


@pytest.fixture(scope="module")
def adj():
    spec = importlib.util.spec_from_file_location("adjudicator_uut", _ADJ)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg(**over):
    cfg = {"claude_adjudicator": {"cmd": "claude.cmd", "model": "opus"}}
    cfg.update(over)
    return cfg


def _cp(stdout="", rc=0, stderr=""):
    """A finished child, as the fleet kit's run seam returns it (FLEET-KIT-v1:
    the call now goes through ops/loop/fleet_route.py into the vendored kit,
    which reads an int returncode)."""
    return subprocess.CompletedProcess(args=["claude"], returncode=rc, stdout=stdout,
                                       stderr=stderr)


def _run_returning(*stdouts):
    """A subprocess.run stub returning each stdout in turn, recording the command."""
    seen = []

    def fake(args, **_kw):
        seen.append(" ".join(str(a) for a in args))
        out = stdouts[len(seen) - 1] if len(seen) <= len(stdouts) else ""
        return _cp(out)

    return fake, seen


# --- resolution ----------------------------------------------------------


def test_resolve_returns_the_claude_adjudicator(adj):
    assert adj.resolve({}).name == "claude"
    assert adj.resolve(None).name == "claude"
    assert adj.resolve({"adjudicator": "claude"}).name == "claude"


def test_a_retired_vendor_name_is_ignored_and_logged_not_honoured(adj):
    """A stale config naming the retired vendor must not select anything.

    Silently accepting a vendor name that no longer resolves is how an old lane
    config ends up running against a brain nobody configured. The log line is
    asserted because a silent fallback here is indistinguishable from a config
    that was read correctly.
    """
    for stale in ("gemini", "bard", "GEMINI"):
        lines = []
        b = adj.resolve({"adjudicator": stale}, log=lines.append)
        assert b.name == "claude"
        assert any(stale.lower() in ln.lower() for ln in lines), \
            f"resolving {stale!r} must say so, not fall back in silence"


# --- the read-only contract ----------------------------------------------


def test_invocation_is_read_only_and_non_interactive(adj, tmp_path):
    """The safety property, asserted on the command line that actually runs.

    `--permission-mode plan` is what makes the adjudicator read-only and `-p`
    is what makes it non-interactive. With one backend left there is no second
    implementation to cross-check this against, so it is asserted directly.
    """
    fake, seen = _run_returning("answer")
    with mock.patch.object(subprocess, "run", side_effect=fake):
        out = adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("body", "inst")
    assert out == "answer"
    assert "--permission-mode plan" in seen[0]
    assert " -p " in seen[0]
    # FLEET-KIT-v1: the kit always asks for JSON; the answer is its `result`.
    assert "--output-format json" in seen[0]


def test_the_prompt_body_goes_to_a_file_not_the_command_line(adj, tmp_path):
    """Quoting a multi-KB prompt on the command line is a failure class the
    design avoids; the body must reach the CLI via stdin from a file."""
    fake, seen = _run_returning("ok")
    body = "quote ' and backslash \\ and newline\n" * 50
    with mock.patch.object(subprocess, "run", side_effect=fake):
        adj.ClaudeAdjudicator(_cfg(), tmp_path).ask(body, "inst")
    assert (tmp_path / "_claude_in.txt").read_text(encoding="utf-8") == body
    assert body not in seen[0]
    # ... and it reaches the child on stdin, through the kit's run seam
    with mock.patch.object(subprocess, "run", return_value=_cp("ok")) as run:
        adj.ClaudeAdjudicator(_cfg(), tmp_path).ask(body, "inst")
    assert run.call_args.kwargs["input"] == body


# --- the None sentinel ---------------------------------------------------


def test_completed_but_empty_is_the_none_sentinel(adj, tmp_path):
    """Empty output is NEVER an answer: the director prompt mandates a directive
    or NO_WORK and the auditor mandates a VERDICT line, so empty is a swallowed
    error. Returning "" would read downstream as a real (blank) answer."""
    with mock.patch.object(subprocess, "run", return_value=_cp("   \n")):
        assert adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("b", "i") is None


def test_raised_subprocess_error_is_the_none_sentinel(adj, tmp_path):
    with mock.patch.object(subprocess, "run",
                           side_effect=subprocess.TimeoutExpired("claude", 1)):
        assert adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("b", "i") is None


def test_a_real_answer_is_never_the_sentinel(adj, tmp_path):
    with mock.patch.object(subprocess, "run", return_value=_cp(" text ")):
        assert adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("b", "i") == "text"


def test_stderr_is_surfaced_when_the_answer_is_empty(adj, tmp_path):
    """A silent empty answer must say WHY. Repointed for FLEET-KIT-v1: the old
    PS 5.1 `2>file` UTF-16 trap went with the PowerShell wrapper - the kit
    captures stderr in-process - so the property pinned now is that the ERROR
    lines of the captured stream reach the log and `last_stderr`."""
    err = ("node.exe : Warning: Windows 10 detected.\n"
           "Attempt 1 failed with status 503. UNAVAILABLE high demand\n")
    lines = []
    with mock.patch.object(subprocess, "run", return_value=_cp("", rc=1, stderr=err)):
        a = adj.ClaudeAdjudicator(_cfg(), tmp_path, log=lines.append)
        out = a.ask("b", "i")
    assert out is None
    assert any("503" in ln and "UNAVAILABLE" in ln for ln in lines)
    assert "503" in a.last_stderr


def test_an_is_error_result_is_never_an_answer(adj, tmp_path):
    """The kit asks for JSON. A result record flagged is_error carries the API
    error as its `result` text; handing that to the controller would read as a
    directive."""
    stdout = '{"type": "result", "is_error": true, "result": "API Error: 529 overloaded"}'
    lines = []
    with mock.patch.object(subprocess, "run", return_value=_cp(stdout)):
        a = adj.ClaudeAdjudicator(_cfg(), tmp_path, log=lines.append)
        assert a.ask("b", "i") is None
    assert "529" in a.last_stderr


def test_the_json_result_is_the_answer(adj, tmp_path):
    with mock.patch.object(subprocess, "run",
                           return_value=_cp('{"type": "result", "is_error": false, '
                                            '"result": " VERDICT: CLEAN "}')):
        assert adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("b", "i") == "VERDICT: CLEAN"


# --- spend accounting (the wrapper's only reason to exist) ---------------


def test_spend_survives_the_rebuild_the_controller_does_every_call(adj, tmp_path):
    """CFG / CTL / log / awrite are controller module globals that tests and a
    hot config edit both swap, so the wrapper is rebuilt per call. If spend did
    not survive that, the recorded workload signal would reset every cycle."""
    state = {"active": "", "usd": {}}
    with mock.patch.object(subprocess, "run", return_value=_cp("a" * 400)):
        for _ in range(3):
            sup = adj.Adjudicator(_cfg(), tmp_path, state=state)
            sup.ask("body" * 100, "inst")
            sup.save_state(state)
    assert state["usd"]["claude"] > 0.0
    assert state["active"] == "claude"
    rebuilt = adj.Adjudicator(_cfg(), tmp_path, state=state)
    assert rebuilt.total_usd() == pytest.approx(state["usd"]["claude"])


def test_spend_accumulates_monotonically(adj, tmp_path):
    state = {"active": "", "usd": {}}
    seen = []
    with mock.patch.object(subprocess, "run", return_value=_cp("x" * 100)):
        for _ in range(4):
            sup = adj.Adjudicator(_cfg(), tmp_path, state=state)
            sup.ask("b" * 50, "i")
            sup.save_state(state)
            seen.append(state["usd"]["claude"])
    assert seen == sorted(seen) and seen[0] < seen[-1]


def test_atomic_write_goes_through_a_tmp_then_replace(adj, tmp_path):
    target = tmp_path / "x.txt"
    adj._atomic_write(target, "payload")
    assert target.read_text(encoding="utf-8") == "payload"
    assert not (tmp_path / "x.txt.tmp").exists(), "tmp file left behind"


# --- THE DECOMMISSION GUARD ----------------------------------------------


def test_the_retired_vendor_machinery_stays_deleted(adj):
    """A decommission is not done while its machinery is still importable.

    Each name below was deleted on 2026-08-01. This fails if any comes back,
    which is the point: the failure mode being guarded is a future session
    restoring "just the failover" or "just the ceiling helper" because
    something still referenced it.
    """
    for gone in ("GeminiAdjudicator", "FailoverAdjudicator", "ceiling_spend",
                 "match_exhaustion", "EXHAUSTION_SIGNATURES", "BACKENDS",
                 "backend_name", "make_backend"):
        assert not hasattr(adj, gone), (
            f"{gone} is back in adjudicator.py - the loop is single-vendor since "
            f"2026-08-01; if a second vendor is genuinely wanted, that is a "
            f"decision to re-open, not a helper to restore")


def test_no_vendor_string_survives_in_the_adjudicator_source(adj):
    src = _ADJ.read_text(encoding="utf-8").lower()
    # The module docstring names what was removed, on purpose, so the count is
    # asserted against the prose block rather than against zero.
    assert "gemini" not in src.split('"""')[2].lower(), \
        "the retired vendor is named outside the docstring - live code or comment"


def test_no_config_reintroduces_a_spend_ceiling(adj):
    """ceiling_usd was a rail on the METERED vendor and Claude was explicitly
    EXCLUDED from it. With no metered vendor, a restored ceiling would invert
    into a cap on exactly the spend operator policy says is uncapped."""
    for cfg_path in sorted(_LOOP.glob("config*.json")):
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert "ceiling_usd" not in cfg, f"{cfg_path.name} restored a spend ceiling"
        assert cfg.get("adjudicator", "claude") == "claude", \
            f"{cfg_path.name} names a vendor that no longer resolves"
        blk = cfg.get("claude_adjudicator") or {}
        assert "count_against_ceiling" not in blk, \
            f"{cfg_path.name} restored the ceiling opt-in flag"


# --- controller wiring ---------------------------------------------------


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location(
        "loop_controller_uut_adj", _LOOP / "loop_controller.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_controller_exposes_the_adjudicator_seam(lc):
    assert hasattr(lc, "adjudicator")
    assert callable(lc.adjudicate), "the single external-brain call site"
    assert not hasattr(lc, "gemini"), \
        "the vendor-named shim was renamed to adjudicate() on 2026-08-01"
    assert not hasattr(lc, "GEMINI_USD"), "renamed to ADJ_USD"
    assert not hasattr(lc, "GEMINI_STDIN_CAP"), "renamed to ADJ_STDIN_CAP"


def test_controller_call_reaches_the_claude_cli_read_only(lc, tmp_path):
    state = {"active": "", "usd": {}}
    seen = []

    def fake(args, **_k):
        seen.append(" ".join(str(a) for a in args))
        return _cp("directive")

    with mock.patch.object(lc, "CFG", _cfg()), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", state), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", side_effect=fake):
        assert lc.adjudicate("body", "inst") == "directive"
    # FLEET-KIT-v1: the kit resolves the exe (faked by tests/conftest.py)
    assert "claude-fake.exe" in seen[0]
    assert "plan" in seen[0], "the adjudicator call must stay read-only"
    assert "gemini" not in seen[0].lower()


def test_the_director_call_is_no_longer_mutex_serialized(lc):
    """The GEMINI_MUTEX hold was removed with the vendor.

    It existed because one METERED account was shared with the sibling loop and
    parallel calls could trip a quota error the failover would misread. With one
    unmetered vendor there is nothing to burn in parallel, and holding a
    machine-wide mutex here would make two sibling loops wait on each other for
    no benefit. Concurrency is governed by slots.py, which is the right layer.
    """
    src = (_LOOP / "loop_controller.py").read_text(encoding="utf-8")
    body = src.split("def _adjudicate_call")[0].split("def adjudicate")[1]
    assert "winmutex.hold" not in body, "the adjudicator call re-acquired a mutex"


# --- AHK bridge liveness (read side of the sibling slice's contract) -----


def test_heartbeat_age_is_none_when_the_file_is_missing(lc, tmp_path):
    assert lc.heartbeat_age(ctl=tmp_path, now=1000) is None


def test_heartbeat_age_measures_seconds_since_the_stamp(lc, tmp_path):
    (tmp_path / "ahk_heartbeat.txt").write_text("1000\n", encoding="utf-8")
    assert lc.heartbeat_age(ctl=tmp_path, now=1042) == 42


def test_heartbeat_age_is_none_for_a_garbage_stamp(lc, tmp_path):
    (tmp_path / "ahk_heartbeat.txt").write_text("not-a-timestamp", encoding="utf-8")
    assert lc.heartbeat_age(ctl=tmp_path, now=1000) is None


# --- control_dir resolves by the controller's rule, never the CWD --------
# Wave 4 merge-fix: the tracked ops/loop/config.json carries no control_dir
# since the 2026-10-09 leak removal (MAIN 2246 sec 3). loop_controller binds
# CTL = _cfg_path("control_dir", _HERE / "control"): an ABSOLUTE value is a
# per-host override, anything else is ops/loop/control. A caller that hands the
# adjudicator a cfg but no ctl must land in the same place, not in a path
# relative to whatever directory it was started from.

@pytest.mark.parametrize("raw", [None, "", "relative/control"],
                         ids=["absent", "empty", "relative"])
@pytest.mark.parametrize("cls", ["ClaudeAdjudicator", "Adjudicator"])
def test_control_dir_without_an_absolute_value_is_ops_loop_control(
        adj, cls, raw, tmp_path, monkeypatch):
    cfg = _cfg()
    if raw is not None:
        cfg["control_dir"] = raw
    monkeypatch.chdir(tmp_path)
    assert getattr(adj, cls)(cfg).ctl == _LOOP / "control"


def test_an_absolute_control_dir_is_still_a_per_host_override(adj, tmp_path):
    assert adj.ClaudeAdjudicator(_cfg(control_dir=str(tmp_path))).ctl == tmp_path


def test_an_explicit_ctl_still_wins_over_the_config(adj, tmp_path):
    other = tmp_path / "ctl"
    assert adj.ClaudeAdjudicator(_cfg(control_dir=str(tmp_path)), other).ctl == other
