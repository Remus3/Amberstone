"""The responder's deterministic executor - hardening, pre-check, scrub, body.

WHY A SECOND LAYER EXISTS AT ALL. The shipped validator judges argv[:2], shell
metacharacters and output-redirecting flags only (tools/inbox_responder.py:259-276).
That is the right shape for an allowlist of VERBS, and it is provably not enough
to run the verb: `git diff --no-index API-Key-Claude.txt README.md` and
`git ls-remote <url>` both pass it. The executor closes that without touching
the validator, so the two layers can be reasoned about - and refuted - apart.

THE PRINCIPLE THE PRE-CHECK SERVES. Every byte a measure can print must be a
projection of bytes already reachable from `origin/main`. The checkout is not
such a set: it carries reflog-only commits, `refs/stash`, local branches and
gitignored files. A character allowlist on a positional cannot tell a public
sha from a reflog-only one, so the pre-check ASKS GIT - through the same
injected runner the measures use, so one recorder sees both and an arm can
prove that a held measure cost zero measurement processes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import inbox_responder_exec as rexec  # noqa: E402

MODULE_REL = "tools/inbox_responder_exec.py"


# ---------------------------------------------------------------------------
# Doubles. No test in this file creates a process or touches a real git tree.
# ---------------------------------------------------------------------------


class FakeResult:
    """The shape `precheck_measure` reads back from the injected runner."""

    def __init__(self, exit_code=0, timed_out=False, exc=None, stdout=b"", stderr=b""):
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.exc = exc
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    """Injected measure runner. Records argv and hands back scripted results."""

    def __init__(self, results=None, default=None):
        self.calls = []
        self.kwargs = []
        self._results = list(results or [])
        self._default = default if default is not None else FakeResult(0)

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.kwargs.append(dict(kw))
        if self._results:
            return self._results.pop(0)
        return self._default

    @property
    def verbs(self):
        return [c[1] for c in self.calls if len(c) > 1]


def _precheck(argv, runner, **kw):
    kw.setdefault("timeout_s", 5)
    return rexec.precheck_measure(argv, runner=runner, **kw)


# ---------------------------------------------------------------------------
# harden_measure_argv - the A1 hardening the validator does not do
# ---------------------------------------------------------------------------


def test_held_verbs_is_a_frozenset_of_exactly_status_and_check_ignore():
    assert rexec.HELD_VERBS == frozenset({"status", "check-ignore"})
    assert isinstance(rexec.HELD_VERBS, frozenset)


@pytest.mark.parametrize("verb_argv", [
    ["git", "status", "--porcelain"],
    ["git", "check-ignore", "x"],
    ["git", "status"],
])
def test_harden_holds_the_held_verbs_with_the_build_scoped_rule(verb_argv):
    # `status --porcelain` prints untracked names; `check-ignore` on an
    # untracked path prints a private one. Both pass the validator's verb list.
    assert rexec.harden_measure_argv(verb_argv) == "executor:verb-held-this-build"


def test_harden_refuses_no_index_because_the_validator_allows_it():
    # The exact validator-allowed case from the spec: two paths, one of them
    # gitignored, compared outside the repo entirely.
    assert rexec.harden_measure_argv(
        ["git", "diff", "--no-index", "C:/x", "NUL"]
    ) == "executor:flag"


def test_harden_refuses_an_absolute_positional():
    assert rexec.harden_measure_argv(
        ["git", "log", "C:/Users/someone/secret"]
    ) == "executor:positional"


def test_harden_refuses_a_url_to_ls_remote():
    assert rexec.harden_measure_argv(
        ["git", "ls-remote", "https://example.invalid"]
    ) == "executor:positional"


def test_harden_allows_the_two_ls_remote_positional_shapes():
    assert rexec.harden_measure_argv(["git", "ls-remote", "--heads", "origin"]) is None
    assert rexec.harden_measure_argv(["git", "ls-remote", "refs/heads/main"]) is None


def test_harden_refuses_an_unknown_flag():
    # `--format=%ae` prints author emails; only the exact `%h %s` form is on
    # the per-verb allowlist.
    assert rexec.harden_measure_argv(
        ["git", "log", "origin/main", "--format=%ae"]
    ) == "executor:flag"


def test_harden_refuses_a_dotdot_positional():
    assert rexec.harden_measure_argv(["git", "log", "origin/main", "../.."]) == "executor:positional"


def test_harden_refuses_others_alone_and_allows_only_the_pair():
    assert rexec.harden_measure_argv(["git", "ls-files", "--others"]) == "executor:flag"
    assert rexec.harden_measure_argv(["git", "ls-files", "--exclude-standard"]) == "executor:flag"
    assert rexec.harden_measure_argv(
        ["git", "ls-files", "--others", "--exclude-standard"]
    ) is None


@pytest.mark.parametrize("bad", [
    ["git", "log", "origin/main", "-n", "abc"],
    ["git", "log", "origin/main", "-n", "0"],
    ["git", "log", "origin/main", "-n", "1000"],
    ["git", "log", "origin/main", "-n"],
    ["git", "log", "origin/main", "--max-count", "abc"],
    ["git", "log", "origin/main", "--max-count=abc"],
    ["git", "for-each-ref", "--count", "abc"],
    ["git", "for-each-ref", "--count=0"],
])
def test_harden_refuses_a_bad_value_after_a_value_taking_flag(bad):
    assert rexec.harden_measure_argv(bad) == "executor:flag-value"


@pytest.mark.parametrize("good", [
    ["git", "log", "origin/main", "-n", "1", "--format=%h %s"],
    ["git", "log", "origin/main", "--max-count", "5"],
    ["git", "log", "origin/main", "--max-count=5"],
    ["git", "for-each-ref", "--count=3", "refs/tags/"],
])
def test_harden_consumes_a_valid_flag_value(good):
    assert rexec.harden_measure_argv(good) is None


def test_a_consumed_flag_value_never_reaches_the_positional_set():
    # `-n 1` must not become a revision the pre-check then asks git about, and
    # must not become a pathspec either. The pre-check is where that is visible.
    rec = Recorder()
    assert _precheck(
        ["git", "log", "origin/main", "-n", "1", "--format=%h %s"], rec
    ) is None
    assert len(rec.calls) == 1
    assert rec.calls[0][1:] == ["merge-base", "--is-ancestor", "origin/main", "origin/main"]
    assert all("1" not in call for call in rec.calls)


@pytest.mark.parametrize("good", [
    ["git", "log", "origin/main", "--oneline"],
    ["git", "show", "--stat", "origin/main"],
    ["git", "diff", "--name-only", "origin/main", "origin/main~1"],
    ["git", "rev-parse", "--short", "origin/main"],
    ["git", "cat-file", "-t", "origin/main"],
    ["git", "for-each-ref", "--format=%(refname)", "refs/tags/"],
])
def test_harden_allows_the_shapes_the_prompt_asks_for(good):
    assert rexec.harden_measure_argv(good) is None


@pytest.mark.parametrize("bad", [
    ["git"],
    ["git", "push", "origin"],
    ["notgit", "log", "origin/main"],
    "git log",
])
def test_harden_refuses_a_malformed_or_unknown_argv(bad):
    assert rexec.harden_measure_argv(bad) is not None


# ---------------------------------------------------------------------------
# precheck_measure - the public-revision and tracked-path gate
# ---------------------------------------------------------------------------


def test_precheck_holds_a_reflog_only_sha():
    # merge-base --is-ancestor exits non-zero: the sha is not reachable from
    # origin/main, so it is not public.
    rec = Recorder(default=FakeResult(exit_code=1))
    assert _precheck(["git", "show", "deadbeefcafe"], rec) == "executor:rev-not-public"
    assert rec.verbs == ["merge-base"]


def test_precheck_holds_a_one_revision_diff_before_any_process():
    rec = Recorder()
    assert _precheck(["git", "diff", "origin/main"], rec) == "executor:diff-needs-two-revs"
    assert rec.calls == []


def test_precheck_allows_a_two_revision_diff():
    rec = Recorder()
    assert _precheck(["git", "diff", "origin/main", "origin/main~1"], rec) is None
    assert rec.verbs == ["merge-base", "merge-base"]


def test_precheck_holds_a_bare_log_because_it_walks_head():
    rec = Recorder()
    assert _precheck(["git", "log", "--oneline"], rec) == "executor:rev-required"
    assert rec.calls == []


def test_precheck_holds_a_local_ref_pattern():
    rec = Recorder()
    assert _precheck(
        ["git", "for-each-ref", "refs/heads/"], rec
    ) == "executor:ref-pattern-not-public"
    assert rec.calls == []


def test_precheck_allows_public_ref_patterns():
    rec = Recorder()
    assert _precheck(["git", "for-each-ref", "refs/remotes/origin/main"], rec) is None
    assert _precheck(["git", "for-each-ref", "refs/tags/v1"], rec) is None
    assert rec.calls == []


def test_precheck_holds_an_untracked_path_and_issues_only_precheck_calls():
    rec = Recorder(results=[FakeResult(exit_code=0), FakeResult(exit_code=1)])
    held = _precheck(["git", "log", "origin/main", "secret.txt"], rec)
    assert held == "executor:path-not-tracked"
    assert rec.verbs == ["merge-base", "ls-files"]
    # The one-seam rule: a held measure costs zero MEASUREMENT processes.
    assert all(c[1] in {"merge-base", "ls-files"} for c in rec.calls)
    assert rec.calls[1][2] == "--error-unmatch"


def test_precheck_holds_a_third_precheckable_positional_before_any_process():
    # The section 11 sum bounds pre-check processes at
    # MAX_MEASURES * PRECHECK_CALLS_PER_MEASURE * PRECHECK_TIMEOUT_S. That is a
    # bound only if a measure can never issue a third.
    rec = Recorder()
    assert _precheck(
        ["git", "log", "origin/main", "a", "b", "c"], rec
    ) == "executor:positional-cap"
    assert rec.calls == []
    assert rexec.PRECHECK_CALLS_PER_MEASURE == 2


def test_precheck_holds_when_the_precheck_process_itself_fails():
    rec = Recorder(default=FakeResult(exit_code=None, timed_out=True))
    assert _precheck(["git", "show", "origin/main"], rec) == "executor:rev-not-public"
    rec2 = Recorder(default=FakeResult(exit_code=None, exc="OSError"))
    assert _precheck(["git", "show", "origin/main"], rec2) == "executor:rev-not-public"


def test_precheck_passes_its_own_timeout_to_the_runner():
    rec = Recorder()
    _precheck(["git", "rev-parse", "--short", "origin/main"], rec, timeout_s=5)
    assert rec.kwargs[0]["timeout_s"] == 5


# ---------------------------------------------------------------------------
# default_measure_runner - the git argv, the env, the caps
# ---------------------------------------------------------------------------


class PopenRecorder:
    def __init__(self, stdout=b"", stderr=b""):
        self.calls = []
        self._stdout = stdout
        self._stderr = stderr

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), dict(kw)))
        return rexec.procs.ProcResult(
            exit_code=0,
            stdout=self._stdout,
            stderr=self._stderr,
            timed_out=False,
            survived_kill=False,
            kill_skipped=False,
            wall_ms=7,
            exc=None,
        )


def _run_measure(monkeypatch, argv, stdout=b"", env=None, timeout_s=15):
    rec = PopenRecorder(stdout=stdout)
    monkeypatch.setattr(rexec.procs, "popen_capture", rec)
    budget = rexec.procs.KillBudget(1)
    res = rexec.default_measure_runner(
        argv,
        timeout_s=timeout_s,
        git_exe="C:/fixture/git.exe",
        repo_root=Path("C:/fixture/repo"),
        env=dict(env if env is not None else {"PATH": "p"}),
        kill_budget=budget,
    )
    return rec, res, budget


def test_measure_argv_prefix_carries_the_configured_git_exe(monkeypatch):
    rec, _, _ = _run_measure(monkeypatch, ["git", "log", "origin/main", "--oneline"])
    argv, _kw = rec.calls[0]
    assert argv[0] == "C:/fixture/git.exe"
    assert argv[0] != "git"
    assert argv[:4] == ["C:/fixture/git.exe", "--no-pager", "-c", "diff.external="]


@pytest.mark.parametrize("verb", ["log", "show", "diff"])
def test_measure_argv_disables_external_diff_for_the_diffing_verbs(monkeypatch, verb):
    rec, _, _ = _run_measure(monkeypatch, ["git", verb, "origin/main"])
    argv, _kw = rec.calls[0]
    assert "--no-ext-diff" in argv


def test_measure_argv_keeps_the_verb_first_and_the_model_tail_last(monkeypatch):
    rec, _, _ = _run_measure(monkeypatch, ["git", "log", "origin/main", "--oneline"])
    argv, _kw = rec.calls[0]
    assert argv[4] == "log"
    assert argv[-2:] == ["origin/main", "--oneline"]


def test_measure_env_extra_is_the_decided_mapping():
    assert rexec.MEASURE_ENV_EXTRA == {
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "GCM_INTERACTIVE": "never",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def test_measure_env_carries_the_extras_and_never_the_api_key(monkeypatch):
    rec, _, _ = _run_measure(
        monkeypatch,
        ["git", "rev-parse", "--short", "origin/main"],
        env={"PATH": "p", "ANTHROPIC_API_KEY": "sk-ant-should-never-reach-a-child"},
    )
    _argv, kw = rec.calls[0]
    env = kw["env"]
    assert "ANTHROPIC_API_KEY" not in env
    for key, value in rexec.MEASURE_ENV_EXTRA.items():
        assert env[key] == value
    assert env["PATH"] == "p"


def test_measure_runs_in_the_repo_root_with_the_cycle_budget(monkeypatch):
    rec, _, budget = _run_measure(monkeypatch, ["git", "log", "origin/main"], timeout_s=15)
    _argv, kw = rec.calls[0]
    assert Path(kw["cwd"]) == Path("C:/fixture/repo")
    assert kw["timeout_s"] == 15
    assert kw["kill_budget"] is budget
    assert kw["stdin_bytes"] == b""


def test_measure_truncates_stdout_at_the_cap_and_says_so(monkeypatch):
    _rec, res, _ = _run_measure(
        monkeypatch, ["git", "log", "origin/main"], stdout=b"x" * 40000
    )
    assert rexec.MEASURE_STDOUT_CAP == 16384
    assert len(res.stdout) == 16384
    assert res.stdout_truncated is True


def test_measure_does_not_flag_a_short_stdout(monkeypatch):
    _rec, res, _ = _run_measure(monkeypatch, ["git", "log", "origin/main"], stdout=b"ok")
    assert res.stdout == b"ok"
    assert res.stdout_truncated is False
    assert res.exit_code == 0
    assert res.wall_ms == 7


def test_the_executor_module_carries_no_literal_subprocess_call():
    # The console-flash guard recognises `subprocess.<verb>(` and the seam is
    # meant to be the ONLY file with one. A census here is cheaper than
    # discovering a second spawn site on Legion.
    src = (ROOT / MODULE_REL).read_text(encoding="utf-8")
    assert "subprocess." not in src
    assert "import subprocess" not in src


# ---------------------------------------------------------------------------
# scrub_output / scrub_text - bytes in, 7-bit ASCII out
# ---------------------------------------------------------------------------


def test_scrub_output_projects_every_shape_the_arm_names():
    raw = (
        b"\xc3\xa9 Author: X <x@example.com>\r\n"
        b"C:\\Users\\someone\\x sk-ant-abc\r"
    )
    text, count = rexec.scrub_output(raw)
    assert text.isascii()
    assert "\\xc3\\xa9" in text
    assert "<email>" in text and "x@example.com" not in text
    assert "<home>" in text and "someone" not in text
    assert "<secret>" in text and "sk-ant-abc" not in text
    assert "\r" not in text
    assert count >= 5


def test_scrub_output_folds_crlf_and_escapes_a_lone_cr():
    text, _ = rexec.scrub_output(b"a\r\nb\rc")
    assert text.startswith("a\nb")
    assert "\r" not in text
    assert "\\x0d" in text


def test_scrub_output_escapes_other_control_bytes_but_keeps_tab_and_lf():
    text, count = rexec.scrub_output(b"a\x07b\tc\nd\x00e")
    assert "\\x07" in text and "\\x00" in text
    assert "\t" in text and "\n" in text
    assert count >= 2


@pytest.mark.parametrize("home", [
    "C:\\Users\\someone\\x",
    "C:/Users/someone/x",
    "/home/someone/x",
    "/Users/someone/x",
])
def test_scrub_output_folds_every_home_shape(home):
    text, count = rexec.scrub_output(home.encode("ascii"))
    assert "<home>" in text and "someone" not in text
    assert count >= 1


@pytest.mark.parametrize("secret", ["sk-ant-abc123", "ghp_abcdef0123", "AKIAABCDEFGHIJKLMNOP"])
def test_scrub_output_folds_every_secret_shape(secret):
    text, _ = rexec.scrub_output(secret.encode("ascii"))
    assert text == "<secret>"


def test_scrub_text_survives_a_lone_surrogate_outside_the_surrogateescape_range():
    # `"\ud800".encode("utf-8", "surrogateescape")` RAISES; a model JSON escape
    # decodes to exactly that. Under the wrong handler the cycle would become
    # runner-failed / exception:reason-scrub:UnicodeEncodeError and re-cycle
    # the note on every tick.
    out = rexec.scrub_text("\ud800")
    assert out == "\\xed\\xa0\\x80"
    assert out.isascii()


def test_scrub_text_bounds_the_model_tainted_reason():
    assert rexec.SCRUB_TEXT_LIMIT == 300
    assert len(rexec.scrub_text("a" * 5000)) == 300


def test_scrub_text_folds_a_home_path_out_of_a_reason():
    out = rexec.scrub_text("['C:\\\\Users\\\\bob\\\\git', 'log'] is not on the allowlist")
    assert "<home>" in out
    assert "Users" not in out and "bob" not in out


# ---------------------------------------------------------------------------
# assemble_body - the tag line and the two grammars
# ---------------------------------------------------------------------------


def _a5_body(**over):
    kw = dict(
        grammar=rexec.GRAMMAR_A5,
        cycle_id="20260908T101112-4242-abcdef",
        note_filename="2026-09-07-1800-from-RSC-topic.md",
        delivery_number=2,
        budget=6,
        model_body="The suite is green on the pinned tree.",
        measurements=[{
            "argv": ["git", "log", "origin/main", "-n", "1", "--format=%h %s"],
            "exit_code": 0,
            "timed_out": False,
            "wall_ms": 31,
            "stdout": "abc123 a commit subject",
            "stdout_truncated": False,
        }],
        held=[{
            "kind": "measure",
            "rule": "executor:verb-held-this-build",
            "reason": "status prints untracked names",
        }],
    )
    kw.update(over)
    return rexec.assemble_body(**kw)


def _latency_body(**over):
    kw = dict(
        grammar=rexec.GRAMMAR_LATENCY_ONLY,
        cycle_id="20260908T101112-4242-abcdef",
        note_filename="2026-09-07-1800-from-RSC-topic.md",
        delivery_number=2,
        budget=6,
        arrived_iso="2026-09-07T18:02:11",
    )
    kw.update(over)
    return rexec.assemble_body(**kw)


def test_the_tag_line_speaks_budget_not_hops():
    body = _a5_body()
    line1 = body.splitlines()[0]
    assert line1.startswith("[RC-RESPONDER] auto-authored under A5-measurement-only;")
    assert "delivery 2 of budget 6 (budget counter, not M1)" in line1
    assert "answering 2026-09-07-1800-from-RSC-topic.md" in line1
    assert "cycle 20260908T101112-4242-abcdef" in line1


def test_the_a5_body_carries_the_measurements_and_the_held_list():
    body = _a5_body()
    assert "## Measurements executed by the responder" in body
    assert '["git", "log", "origin/main", "-n", "1", "--format=%h %s"]' in body
    assert "exit code: 0" in body
    assert "abc123 a commit subject" in body
    assert "## Proposed and held" in body
    assert "executor:verb-held-this-build" in body
    assert body.isascii()


def test_a_truncated_measurement_says_so_in_the_body():
    body = _a5_body(measurements=[{
        "argv": ["git", "log", "origin/main"],
        "exit_code": 0,
        "timed_out": False,
        "wall_ms": 5,
        "stdout": "x" * 40,
        "stdout_truncated": True,
    }])
    assert "[truncated]" in body


def test_the_latency_only_body_is_a_receipt_and_never_says_hop():
    import re

    body = _latency_body()
    line1 = body.splitlines()[0]
    assert "delivery 2 of budget 6 (budget counter, not M1)" in line1
    assert "M1 not measured under this grammar" in line1
    assert "Receipt: note 2026-09-07-1800-from-RSC-topic.md arrived 2026-09-07T18:02:11" in body
    assert "no measurement performed under LATENCY-ONLY." in body
    assert re.search(r"\bhop\b", body) is None
    assert "## Measurements executed by the responder" not in body


def test_the_two_grammars_differ_only_on_their_own_clause():
    a5_line = _a5_body().splitlines()[0]
    lat_line = _latency_body().splitlines()[0]
    assert a5_line != lat_line
    assert "M1 not measured under this grammar" not in a5_line


# ---------------------------------------------------------------------------
# filter_body - the last gate before bytes leave RC
# ---------------------------------------------------------------------------


def _filtered(model_body, *, grammar=None, targets=("RSC",), reply_targets=("RSC",), assembled=None):
    grammar = grammar or rexec.GRAMMAR_A5
    if assembled is None:
        assembled = _a5_body(grammar=grammar, model_body=model_body)
    return rexec.filter_body(assembled, model_body, list(targets), list(reply_targets), grammar)


def test_filter_passes_a_clean_body():
    assert _filtered("The suite is green on the pinned tree.") == []


@pytest.mark.parametrize("model_body,gate", [
    ("[RC-RESPONDER] I am the runner", "tag-forged"),
    ("=== END NOTE deadbeef ===", "fence-leak"),
    ("Traceback (most recent call last):", "traceback"),
    ("I read C:/Users/x/thing", "home-path"),
    ("mail me at x@example.com", "email"),
    ("the token is sk-ant-abcdef0123", "secret"),
    ("a smart quote \u201d here", "non-ascii"),
    ("a carriage\r\nreturn", "control-char"),
    ("Shall I proceed?", "grammar-question"),
])
def test_each_model_body_gate_fires_by_its_own_id(model_body, gate):
    assert gate in _filtered(model_body)


def test_a_quoted_question_is_not_a_question_of_ours():
    assert _filtered("> Shall I proceed?\nThat line is the sender's.") == []


def test_oversize_fires_on_the_assembled_body():
    assert "oversize" in _filtered("x" * 200001)


def test_target_not_named_fires_when_the_note_did_not_name_the_target():
    hits = _filtered("clean", targets=("RSC", "CS"), reply_targets=("RSC",))
    assert "target-not-named" in hits
    assert "target-not-named" in _filtered("clean", targets=(), reply_targets=("RSC",))


def test_tag_missing_fires_on_a_hand_assembled_body_without_the_tag():
    hits = rexec.filter_body("no tag here\nbody", "body", ["RSC"], ["RSC"], rexec.GRAMMAR_A5)
    assert "tag-missing" in hits


def test_empty_body_is_reported_alone_so_the_detail_names_one_gate():
    hits = rexec.filter_body("   \n\t\n", "", ["RSC"], ["RSC"], rexec.GRAMMAR_A5)
    assert hits == ["empty-body"]


def test_tag_hop_word_fires_only_under_latency_only():
    forged = _latency_body().replace("Receipt:", "Receipt hop 2:")
    hits = rexec.filter_body(forged, "", ["RSC"], ["RSC"], rexec.GRAMMAR_LATENCY_ONLY)
    assert "tag-hop-word" in hits
    a5 = _a5_body(model_body="one hop of the exchange")
    assert "tag-hop-word" not in rexec.filter_body(
        a5, "one hop of the exchange", ["RSC"], ["RSC"], rexec.GRAMMAR_A5
    )


def test_every_declared_gate_id_is_reachable_by_name():
    declared = {
        "tag-forged", "fence-leak", "traceback", "home-path", "email", "secret",
        "non-ascii", "control-char", "oversize", "grammar-question",
        "target-not-named", "empty-body", "tag-missing", "tag-hop-word",
    }
    assert rexec.FILTER_GATES == declared
