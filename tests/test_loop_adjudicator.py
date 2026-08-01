# arch: SWAP-A - pluggable external-brain adjudicator + credit-exhaustion failover | section=tests | frozen=no
"""ops/loop/adjudicator.py: the loop's external brain is a swappable backend.

The autonomous headless loop hard-coupled its director + auditor to the Gemini
CLI. Gemini is a METERED vendor whose credits expire at an unknown moment, so the
swap to the local claude CLI has to be a non-event: one config key, or nothing at
all when the automatic failover fires.

These are pure-unit guards - the subprocess layer is monkeypatched, so no network
call and no real CLI invocation happens. Loaded by file path (ops/loop is not a
package on sys.path), mirroring tests/test_loop_gemini_timeout.py.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest import mock

import pytest

_ADJ = Path(__file__).resolve().parent.parent / "ops" / "loop" / "adjudicator.py"

_OVERLOAD_STDERR = (
    "node.exe : Warning: Windows 10 detected.\n"
    "Attempt 1 failed with status 503. UNAVAILABLE model is overloaded, high demand\n"
)


@pytest.fixture(scope="module")
def adj():
    spec = importlib.util.spec_from_file_location("adjudicator_uut_swap_a", _ADJ)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def nosleep(adj):
    with mock.patch.object(adj.time, "sleep", lambda *_a, **_k: None):
        yield


def _cfg(**over):
    """A config for the FAILOVER-MECHANISM tests, which name their vendor.

    `"adjudicator": "gemini"` is explicit here on purpose. These tests exercise
    the primary-to-fallback ladder, and before 2026-08-01 they got their primary
    from the module default - so flipping that default to claude broke twenty of
    them at once, for a reason that had nothing to do with the ladder they test.
    A test of the mechanism must not depend on which vendor happens to be
    default; it must say which vendor it is exercising.

    The ladder itself is still worth covering. Claude-only is a config flip, not
    a deletion, and the gemini backend stays reachable as the rollback path (see
    `adjudicator.DEFAULT_BACKEND`). The day it is genuinely decommissioned,
    these tests go with it in the same commit.
    """
    cfg = {"gemini_model": "g-pro", "gemini_fallback_model": "g-flash",
           "gemini_cmd": "gemini", "adjudicator": "gemini",
           "adjudicator_fallback": "claude",
           "claude_adjudicator": {"cmd": "claude.cmd", "model": "opus"}}
    cfg.update(over)
    return cfg


def _stderr(ctl, name, text):
    (Path(ctl) / name).write_text(text, encoding="utf-8")


def _run_returning(*stdouts):
    """A subprocess.run stub yielding the given stdouts in order, then "" forever.
    Records the PowerShell command string of every invocation."""
    seen = []

    def fake(args, **_k):
        seen.append(args[-1])
        i = len(seen) - 1
        return mock.Mock(stdout=stdouts[i] if i < len(stdouts) else "")

    return fake, seen


# --- backend resolution --------------------------------------------------


def test_resolve_defaults_to_claude(adj):
    """The default backend is CLAUDE (operator decision 2026-08-01).

    This assertion inverted on that date. It used to pin gemini, on the
    reasoning that the seam must change nothing about the running loop. The
    loop now self-adjudicates - the same vendor executes, directs and audits a
    cycle - so a config that names no backend must get claude, and an absent
    key can never silently re-enable the metered vendor.

    Naming gemini explicitly still resolves, because the flip is reversible.
    """
    assert adj.resolve({}).name == "claude"
    assert adj.backend_name(None) == "claude"
    assert adj.resolve({"adjudicator": "gemini"}).name == "gemini"


def test_resolve_honours_the_claude_flip(adj):
    assert adj.resolve({"adjudicator": "claude"}).name == "claude"
    assert adj.resolve({"adjudicator": "  CLAUDE  "}).name == "claude"


def test_resolve_falls_back_on_an_unknown_backend_name(adj):
    lines = []
    b = adj.resolve({"adjudicator": "bard"}, log=lines.append)
    assert b.name == "claude"
    assert any("bard" in ln for ln in lines)


def test_every_backend_honours_the_ask_contract(adj):
    for name in adj.BACKENDS:
        b = adj.make_backend(name)
        assert callable(b.ask)
        assert b.name == name
        assert b.usd == 0.0


# --- the read-only + non-interactive invocation contract -----------------


def test_gemini_invocation_keeps_its_read_only_flags(adj, tmp_path, nosleep):
    fake, seen = _run_returning("directive")
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        out = adj.GeminiAdjudicator(_cfg(), tmp_path).ask("body", "inst")
    assert out == "directive"
    assert "--approval-mode plan" in seen[0] and "--skip-trust" in seen[0]


def test_claude_invocation_is_read_only_and_non_interactive(adj, tmp_path):
    # `--permission-mode plan` is the claude CLI equivalent of the gemini
    # `--approval-mode plan` read-only guarantee; `-p` makes it a one-shot print.
    fake, seen = _run_returning("verdict")
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        out = adj.ClaudeAdjudicator(_cfg(), tmp_path).ask("body", "inst")
    assert out == "verdict"
    assert "--permission-mode plan" in seen[0]
    assert " -p " in seen[0]
    assert "--model 'opus'" in seen[0]
    # one call per ask - never an interactive/resumed session
    assert len(seen) == 1


# --- the empty-output-is-None sentinel, for BOTH backends ----------------


@pytest.mark.parametrize("backend", ["gemini", "claude"])
def test_completed_but_empty_is_the_none_sentinel(adj, tmp_path, nosleep, backend):
    # The director prompt mandates a directive or the literal NO_WORK token and
    # the auditor prompt mandates a VERDICT line, so "" is a swallowed CLI/API
    # error, never an answer. Returning "" would read as NO_WORK and kill a run.
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="")):
        out = adj.make_backend(backend, _cfg(), tmp_path).ask("body", "inst")
    assert out is None


@pytest.mark.parametrize("backend", ["gemini", "claude"])
def test_raised_subprocess_error_is_the_none_sentinel(adj, tmp_path, nosleep, backend):
    with mock.patch.object(adj.subprocess, "run",
                           side_effect=subprocess.TimeoutExpired("powershell", 300)):
        out = adj.make_backend(backend, _cfg(), tmp_path).ask("body", "inst")
    assert out is None


@pytest.mark.parametrize("backend", ["gemini", "claude"])
def test_a_real_answer_is_never_the_sentinel(adj, tmp_path, nosleep, backend):
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="  ok  ")):
        out = adj.make_backend(backend, _cfg(), tmp_path).ask("body", "inst")
    assert out == "ok"


@pytest.mark.parametrize("backend", ["gemini", "claude"])
def test_backends_decode_a_utf16_stderr_stream(adj, tmp_path, nosleep, backend):
    # PS 5.1 `2>file` writes UTF-16 LE; a utf-8 read mojibakes it and masked a
    # real API error for a 9-hour outage.
    errname = {"gemini": "_gemini_err.txt", "claude": "_claude_err.txt"}[backend]
    body = "Error: 429 RESOURCE_EXHAUSTED quota exceeded\n"
    (tmp_path / errname).write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="")):
        b = adj.make_backend(backend, _cfg(), tmp_path)
        assert b.ask("body", "inst") is None
    assert "RESOURCE_EXHAUSTED" in b.last_stderr
    # no NUL interleave / U+FFFD replacement chars = the utf-16 stream decoded
    assert "\x00" not in b.last_stderr and "\ufffd" not in b.last_stderr


# --- exhaustion classification ------------------------------------------


@pytest.mark.parametrize("sig", ["quota", "exhausted", "insufficient credit",
                                 "out of credit", "billing", "top up", "429",
                                 "RESOURCE_EXHAUSTED"])
def test_every_exhaustion_signature_is_classified(adj, sig):
    assert adj.match_exhaustion(f"Error: the call failed - {sig} - see docs")
    assert adj.match_exhaustion(f"ERROR: {sig.upper()}")


@pytest.mark.parametrize("txt", [_OVERLOAD_STDERR, "503 UNAVAILABLE", "",
                                 "Error: model is overloaded, try again",
                                 "Attempt 2 failed with status 500"])
def test_transient_failures_are_not_exhaustion(adj, txt):
    assert adj.match_exhaustion(txt) is None


# --- automatic failover --------------------------------------------------


def _supervisor(adj, ctl, **over):
    return adj.FailoverAdjudicator(_cfg(**over), ctl)


@pytest.mark.parametrize("sig", ["quota exceeded", "credits exhausted",
                                 "insufficient credit balance", "out of credit",
                                 "billing account disabled", "please top up",
                                 "429 Too Many Requests", "RESOURCE_EXHAUSTED"])
def test_failover_fires_on_each_exhaustion_signature(adj, tmp_path, nosleep, sig):
    _stderr(tmp_path, "_gemini_err.txt", f"Error: {sig}")
    fake, _seen = _run_returning()  # every call empty -> gemini exhausts
    lines = []
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path, log=lines.append)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        sup.ask("body", "inst")
    assert sup.active_name == "claude" and sup.failed_over
    assert any(ln.startswith("ADJUDICATOR FAILOVER: gemini -> claude (reason: ") for ln in lines)


def test_failover_does_not_fire_on_a_transient_overload(adj, tmp_path, nosleep):
    # A 503 is capacity weather. The in-backend 3+2 retry ladder and the cheaper
    # fallback model handle it; abandoning the metered brain for a whole run over
    # a blip is the failure mode this asserts against.
    _stderr(tmp_path, "_gemini_err.txt", _OVERLOAD_STDERR)
    fake, _seen = _run_returning()
    lines = []
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path, log=lines.append)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        out = sup.ask("body", "inst")
    assert out is None
    assert sup.active_name == "gemini" and not sup.failed_over
    assert not any("ADJUDICATOR FAILOVER" in ln for ln in lines)


def test_failover_retries_the_same_call_and_returns_the_fallback_answer(
        adj, tmp_path, nosleep):
    # The whole point: the cycle is NOT lost. The fallback answers the identical
    # question in the same ask().
    _stderr(tmp_path, "_gemini_err.txt", "Error: 429 RESOURCE_EXHAUSTED")
    # 5 empty gemini tries (3 primary + 2 fallback model), then claude answers
    fake, seen = _run_returning("", "", "", "", "", "FALLBACK ANSWER")
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        out = sup.ask("the same body", "the same instruction")
    assert out == "FALLBACK ANSWER"
    assert "--permission-mode plan" in seen[-1], "the retry must run on the claude backend"
    assert "the same instruction" in seen[-1], "the retry must ask the SAME question"


def test_failover_is_sticky_for_the_rest_of_the_run(adj, tmp_path, nosleep):
    _stderr(tmp_path, "_gemini_err.txt", "Error: quota exhausted")
    lines = []
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path, log=lines.append)
    fake, seen = _run_returning("", "", "", "", "", "first")
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        sup.ask("a", "i")
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="second")):
        assert sup.ask("b", "i") == "second"
    assert sup.active_name == "claude"
    # exactly ONE failover announcement for the whole run
    assert sum("ADJUDICATOR FAILOVER" in ln for ln in lines) == 1


def test_stickiness_survives_a_supervisor_rebuild(adj, tmp_path, nosleep):
    # The controller rebuilds the supervisor per call from module globals; the
    # sticky decision lives in the caller-owned state dict so a restart or a
    # rebuild never silently reverts to the exhausted vendor.
    _stderr(tmp_path, "_gemini_err.txt", "Error: quota exhausted")
    state = {}
    fake, _seen = _run_returning("", "", "", "", "", "first")
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        sup.ask("a", "i")
    sup.save_state(state)
    assert adj.FailoverAdjudicator(_cfg(), tmp_path, state=state).active_name == "claude"


def test_sticky_state_is_ignored_when_cfg_arms_no_fallback(adj, tmp_path, nosleep):
    """A sticky decision must not outlive the config that authorized it.

    Honouring it against a cfg that names no resolvable fallback routes the call
    to a backend the ACTIVE configuration never authorized. Production cfg is
    fixed for a whole run so this gate is a no-op for every real launch, but it
    is what stops a decision taken under one config from leaking into a call
    made under another.
    """
    sticky = {"active": "claude", "failed_over": True, "usd": {}}
    # "unarmed" means no resolvable FALLBACK. The primary is named explicitly so
    # the test keeps testing that, rather than the module default (2026-08-01).
    unarmed = {"gemini_model": "g-pro", "gemini_fallback_model": "g-flash",
               "adjudicator": "gemini"}
    sup = adj.FailoverAdjudicator(unarmed, tmp_path, state=sticky)
    assert not sup.failover_armed()
    assert sup.active_name == "gemini"
    fake, seen = _run_returning("", "", "", "flash-answer")
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        out = sup.ask("body", "inst")
    # the whole 3+2 ladder must run on gemini and reach the fallback MODEL
    assert out == "flash-answer"
    assert all("--approval-mode plan" in c for c in seen)
    assert all("g-pro" in c for c in seen[:3]) and "g-flash" in seen[3]


def test_sticky_state_is_ignored_when_failover_is_switched_off(adj, tmp_path, nosleep):
    sticky = {"active": "claude", "failed_over": True, "usd": {}}
    sup = adj.FailoverAdjudicator(_cfg(adjudicator_failover=False), tmp_path, state=sticky)
    assert not sup.failover_armed()
    assert sup.active_name == "gemini"


def test_sticky_state_still_applies_while_the_cfg_arms_failover(adj, tmp_path):
    # The gate must not weaken real stickiness - an armed cfg still honours it.
    sticky = {"active": "claude", "failed_over": True, "usd": {}}
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path, state=sticky)
    assert sup.failover_armed()
    assert sup.active_name == "claude" and sup.failed_over


def test_refusing_a_sticky_route_never_discards_spend(adj, tmp_path):
    # Accounting is not a routing decision: the ceiling must still see prior
    # spend even when the sticky ROUTE is refused.
    sticky = {"active": "claude", "failed_over": True, "usd": {"gemini": 3.0, "claude": 9.0}}
    sup = adj.FailoverAdjudicator({"gemini_model": "g-pro"}, tmp_path, state=sticky)
    assert sup.usd == {"gemini": 3.0, "claude": 9.0}
    assert sup.total_usd() == pytest.approx(12.0)


def test_controller_sticky_state_does_not_leak_across_configs(lc, tmp_path):
    """The merged-main regression, at the controller seam.

    A gemini() call that fired a failover under the live config must not route a
    LATER gemini() call whose cfg arms no fallback. That leak silently skipped
    the 3+2 gemini retry ladder, which is the 2026-07-02 9-hour-outage guard.
    """
    state = {"active": "claude", "failed_over": True, "usd": {}}
    seen = []

    def fake(args, **_k):
        seen.append(args[-1])
        return mock.Mock(stdout="" if len(seen) <= 3 else "flash-directive")

    unarmed = {"gemini_model": "gemini-3-pro-preview",
               "gemini_fallback_model": "gemini-2.5-flash",
               "adjudicator": "gemini"}
    with mock.patch.object(lc, "CFG", unarmed), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", state), \
            mock.patch.object(lc.subprocess, "run", side_effect=fake), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out == "flash-directive"
    assert all("gemini-3-pro-preview" in c for c in seen[:3])
    assert "gemini-2.5-flash" in seen[3]


def test_failover_can_be_disabled(adj, tmp_path, nosleep):
    _stderr(tmp_path, "_gemini_err.txt", "Error: quota exhausted")
    fake, _seen = _run_returning()
    sup = adj.FailoverAdjudicator(_cfg(adjudicator_failover=False), tmp_path)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        assert sup.ask("a", "i") is None
    assert sup.active_name == "gemini" and not sup.failed_over


def test_a_pre_seam_config_never_swaps_vendor(adj, tmp_path, nosleep):
    # An absent adjudicator_fallback means NO FAILOVER, not a silent swap to
    # claude. That is the whole subject of this test and it is unchanged.
    #
    # The premise it used to rest on is not: "today's config.json has no
    # adjudicator keys" stopped being true on 2026-08-01, when the loop went
    # claude-only and the keys were written in. So the vendor is named here
    # rather than inherited from the module default - otherwise this test
    # silently becomes "claude never swaps to claude", which is vacuous.
    _stderr(tmp_path, "_gemini_err.txt", "Error: 429 RESOURCE_EXHAUSTED quota")
    fake, _seen = _run_returning()
    lines = []
    pre_seam = {"gemini_model": "g-pro", "gemini_cmd": "gemini",
                "adjudicator": "gemini"}
    sup = adj.FailoverAdjudicator(pre_seam, tmp_path, log=lines.append)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        assert sup.ask("a", "i") is None
    assert sup.active_name == "gemini" and not sup.failed_over
    assert not any("ADJUDICATOR FAILOVER" in ln for ln in lines)
    assert not (tmp_path / "adjudicator_active.txt").exists()


def test_no_failover_while_the_active_backend_answers(adj, tmp_path, nosleep):
    _stderr(tmp_path, "_gemini_err.txt", "Error: quota exhausted")
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path)
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="fine")):
        assert sup.ask("a", "i") == "fine"
    assert sup.active_name == "gemini" and not sup.failed_over


# --- adjudicator_active.txt is written atomically ------------------------


def test_atomic_write_goes_through_a_tmp_then_replace(adj, tmp_path):
    # The control dir is polled by other processes mid-write, so a partial file
    # must never be observable.
    calls = []
    target = tmp_path / "adjudicator_active.txt"
    with mock.patch.object(adj.os, "replace", side_effect=lambda s, d: calls.append((str(s), str(d)))):
        adj._atomic_write(target, "claude\n")
    assert len(calls) == 1
    src, dst = calls[0]
    assert src.endswith(".tmp") and dst == str(target)


def test_failover_records_the_new_backend_on_disk(adj, tmp_path, nosleep):
    _stderr(tmp_path, "_gemini_err.txt", "Error: quota exhausted")
    fake, _seen = _run_returning("", "", "", "", "", "answer")
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path)
    with mock.patch.object(adj.subprocess, "run", side_effect=fake):
        sup.ask("a", "i")
    marker = tmp_path / "adjudicator_active.txt"
    assert marker.read_text(encoding="utf-8").strip() == "claude"
    assert not (tmp_path / "adjudicator_active.txt.tmp").exists(), "tmp file left behind"


# --- ceiling semantics ---------------------------------------------------


def test_ceiling_excludes_claude_spend_by_default(adj):
    # Operator policy: Claude spend is uncapped. A swap to the local adjudicator
    # must not inherit the metered vendor's rail and then stop a free run.
    usd = {"gemini": 4.0, "claude": 500.0}
    assert adj.ceiling_spend(_cfg(), usd) == pytest.approx(4.0)


def test_ceiling_includes_claude_when_opted_in(adj):
    cfg = _cfg(claude_adjudicator={"cmd": "c", "model": "opus", "count_against_ceiling": True})
    assert adj.ceiling_spend(cfg, {"gemini": 4.0, "claude": 6.0}) == pytest.approx(10.0)


def test_ceiling_spend_never_exceeds_total_spend(adj):
    usd = {"gemini": 3.0, "claude": 7.0}
    total = sum(usd.values())
    assert 0.0 <= adj.ceiling_spend(_cfg(), usd) <= total


def test_spend_accumulates_monotonically_per_backend(adj, tmp_path, nosleep):
    sup = adj.FailoverAdjudicator(_cfg(), tmp_path)
    with mock.patch.object(adj.subprocess, "run", return_value=mock.Mock(stdout="ok")):
        sup.ask("a" * 4000, "i")
        first = sup.usd["gemini"]
        sup.ask("a" * 4000, "i")
    assert first > 0.0
    assert sup.usd["gemini"] > first


# --- controller wiring ---------------------------------------------------


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location(
        "loop_controller_uut_swap_a",
        Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_controller_exposes_the_adjudicator_seam(lc):
    assert hasattr(lc, "adjudicator")
    assert callable(lc.gemini), "the delegating shim must survive for existing callers"
    assert callable(lc._supervisor)


def test_controller_shim_routes_through_the_active_backend(lc, tmp_path):
    # gemini() is now a delegate: with the config flipped to claude it must speak
    # to the claude CLI, which is what makes the swap a one-key edit.
    state = {"active": "", "failed_over": False, "usd": {}}
    seen = []

    def fake(args, **_k):
        seen.append(args[-1])
        return mock.Mock(stdout="answer")

    with mock.patch.object(lc, "CFG", _cfg(adjudicator="claude")), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", state), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", side_effect=fake):
        assert lc.gemini("body", "inst") == "answer"
    assert "--permission-mode plan" in seen[0]
    assert state["active"] == "claude"


def test_controller_default_config_speaks_claude(lc, tmp_path):
    """A config naming no backend must reach the CLAUDE CLI, read-only.

    Inverted 2026-08-01 with `test_resolve_defaults_to_claude`. The assertion
    that carries the safety weight is the flag check: whichever vendor the
    delegate reaches, the adjudicator is a READ-ONLY call. For claude that
    guarantee is `--permission-mode plan` and non-interactivity is `-p`; the
    gemini equivalent was `--approval-mode plan`. Losing vendor diversity must
    not quietly lose the read-only property with it, so it is asserted here
    rather than assumed from the backend class.
    """
    state = {"active": "", "failed_over": False, "usd": {}}
    seen = []

    def fake(args, **_k):
        seen.append(" ".join(str(a) for a in args))
        return mock.Mock(stdout="directive")

    with mock.patch.object(lc, "CFG", {"claude_adjudicator": {"cmd": "claude.cmd",
                                                              "model": "opus"}}), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", state), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", side_effect=fake):
        assert lc.gemini("body", "inst") == "directive"
    assert "claude.cmd" in seen[0], f"did not reach the claude CLI: {seen[0]}"
    assert "plan" in seen[0], f"adjudicator call was not read-only: {seen[0]}"
    assert "gemini" not in seen[0].lower()


# --- AHK bridge liveness (read side of the sibling slice's contract) -----


def test_heartbeat_age_is_none_when_the_file_is_missing(lc, tmp_path):
    assert lc.heartbeat_age(ctl=tmp_path, now=1000) is None


def test_heartbeat_age_measures_seconds_since_the_stamp(lc, tmp_path):
    (tmp_path / "ahk_heartbeat.txt").write_text("1000\n", encoding="utf-8")
    assert lc.heartbeat_age(ctl=tmp_path, now=1042) == 42


def test_heartbeat_age_is_none_for_a_garbage_stamp(lc, tmp_path):
    (tmp_path / "ahk_heartbeat.txt").write_text("not-a-timestamp", encoding="utf-8")
    assert lc.heartbeat_age(ctl=tmp_path, now=1000) is None


def test_a_fresh_heartbeat_is_silent(lc):
    assert lc.bridge_stale_message(0) is None
    assert lc.bridge_stale_message(lc.AHK_HEARTBEAT_STALE_SEC) is None
    assert lc.bridge_stale_message(-5) is None, "clock skew is not a dead bridge"


def test_a_stale_or_missing_heartbeat_is_loud(lc):
    assert lc.bridge_stale_message(lc.AHK_HEARTBEAT_STALE_SEC + 1).startswith("AHK BRIDGE STALE (")
    assert lc.bridge_stale_message(None).startswith("AHK BRIDGE STALE (")
    assert "999s" in lc.bridge_stale_message(999)
