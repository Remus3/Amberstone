"""The Stop claim gate must not nag the main session (operator, 2026-10-09).

Measured on session e4ff80f0 (2026-10-09): after EVERY main-session turn the
armed gate injected the same line, "stop_claim_gate: 2 unbacked claims
(count_mismatch,subagent_hook_bypass)", although the main session had already
acknowledged and corrected both. Four root causes, each pinned here:

(a) `main` re-audits the WHOLE transcript every Stop and had no memory of what
    it had already surfaced, so one finding re-fired on every later turn. Each
    finding (check + normalised claim text + claimed value + source turn) now
    surfaces in additionalContext AT MOST ONCE per session; the report still
    lists every finding.
(b) The feedback line was built from ALL findings, advisory ones included, so
    the advisory subagent_hook_bypass reached chat and was counted as an
    "unbacked claim". Advisory checks go to the report and history only.
(c) subagent_hook_bypass was noted at tool_use time - before the result - so a
    command the kit GITLOCK hook REFUSED (it never ran) still counted, and so
    did a bypass in a throwaway scratch repo that is not RC at all. It now
    counts only a command that EXECUTED and whose target (row cwd, `cd`,
    `git -C`) resolves to RC's git common dir; an unresolvable target still
    counts (fail closed).
(d) count_mismatch did not accept a SUM: the main session added two arm counts
    that ONE dual-suite run printed (10971 + 28211) and was flagged. A claim
    equal to the sum of two or more DISTINCT counts observed in the same
    test-output block, or named together in the same sub-agent result (each
    component itself observed), is now accepted. Nothing wider: a number that
    is not such a sum still flags.
(e) The hook stays exit 0 and prints nothing when there is nothing new.

Driven end-to-end as a Stop hook (JSON on stdin), as the sibling gate tests do.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import stop_claim_gate as gate

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "tools" / "stop_claim_gate.py"

SID = "quiet-0000-4000-8000-000000000001"
START = "2026-10-09T19:00:00.000Z"
AGENT = "a6417d082383f2023"

DUAL_CMD = "python -m pytest agents/daemon_slayer -q; python -m pytest tests -q"
DUAL_OUT = ("........\n10971 passed, 13675 subtests passed in 47.70s\n"
            "FAILED tests/test_x.py::test_y - AssertionError\n"
            "7 failed, 28211 passed, 100 skipped, 1 warning, 5089 subtests passed "
            "in 314.17s (0:05:14)")
SUM_CLAIM = "- **Full suite:** 39182 passed, 7 failed."

# Measured 2026-10-09 (agent-a6417d082383f2023.jsonl row 84): the kit GITLOCK
# PreToolUse hook refused the call, so the command never ran.
GITLOCK_DENIAL = ("PreToolUse:Bash hook error: GITLOCK: run `git commit` through "
                  "fleet_gitlock.py: python <kit>/fleet_gitlock.py run --owner "
                  "x.y -- git commit ...")
HOOK_DENIAL_ROW = {"toolDenialKind": "permission-rule",
                   "permissionDecision": {"decision": "reject", "source": "hook",
                                          "reasonType": "hook"},
                   "toolUseResult": "Error: " + GITLOCK_DENIAL}
COMMIT_OK = "[main 0123abc] x\n 1 file changed, 1 insertion(+)"


# ------------------------------------------------------------------ builders

def _main_rows(*texts):
    """A first user row, then one assistant text row per claim, each with its
    own uuid (the source turn of any finding it carries)."""
    rows = [{"type": "user", "timestamp": START, "sessionId": SID, "uuid": "u-start",
             "message": {"role": "user", "content": "continue"}}]
    for i, text in enumerate(texts):
        rows.append({"type": "assistant", "uuid": f"a-{i}", "sessionId": SID,
                     "timestamp": f"2026-10-09T20:00:{i:02d}.000Z",
                     "message": {"role": "assistant",
                                 "content": [{"type": "text", "text": text}]}})
    return rows


def _side(kind, content, cwd=None, **extra):
    row = {"parentUuid": None, "isSidechain": True, "agentId": AGENT, "type": kind,
           "message": {"role": kind, "content": content},
           "timestamp": "2026-10-09T19:30:00.000Z", "sessionId": SID}
    if cwd is not None:
        row["cwd"] = str(cwd)
    row.update(extra)
    return row


def _pair(tid, command, output, is_error=None, cwd=None, result_row=None):
    """One sub-agent Bash call and its result, in the measured row shape."""
    block = {"type": "tool_result", "tool_use_id": tid, "content": output}
    if is_error is not None:
        block["is_error"] = is_error
    return [_side("assistant", [{"type": "tool_use", "id": tid, "name": "Bash",
                                 "input": {"command": command}}], cwd=cwd),
            _side("user", [block], cwd=cwd, **(result_row or {}))]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _session(tmp_path, main_rows, agents=None):
    transcript = tmp_path / (SID + ".jsonl")
    _write_jsonl(transcript, main_rows)
    for agent_id, rows in (agents or {}).items():
        head = _side("user", "Run the task.")
        _write_jsonl(tmp_path / SID / "subagents" / ("agent-" + agent_id + ".jsonl"),
                     [head] + [r for chunk in rows for r in chunk])
    return transcript


def _run(tmp_path, transcript, arm=True, session=SID, reentry=False):
    report = tmp_path / "report.json"
    payload = json.dumps({"session_id": session, "transcript_path": str(transcript),
                          "cwd": str(ROOT), "hook_event_name": "Stop",
                          "stop_hook_active": reentry})
    proc = subprocess.run(
        [sys.executable, str(GATE), "--report", str(report),
         "--history", str(tmp_path / "history.jsonl")] + (["--arm"] if arm else []),
        input=payload, capture_output=True, text=True, cwd=str(ROOT), check=False)
    assert proc.returncode == 0, f"the gate must exit 0: {proc.stderr}"
    assert proc.stderr == "", proc.stderr
    return proc, json.loads(report.read_text(encoding="utf-8"))


def _context(proc):
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, f"exactly one stdout line: {proc.stdout!r}"
    return json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]


def _checks(report):
    return {f["check"] for f in report["findings"]}


def _bypass_checks(tmp_path, command, output, **kw):
    """Main makes an unbacked tests claim (a CLEARABLE finding, so the
    sub-agent files are read); the sub-agent runs COMMAND."""
    agents = {AGENT: [_pair("toolu_01bp", command, output, **kw)]}
    transcript = _session(tmp_path, _main_rows("The full suite passes."), agents)
    return _checks(_run(tmp_path, transcript, arm=False)[1])


# ======================================================== (a) dedupe per session

def test_a_finding_surfaces_once_per_session(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    first, report1 = _run(tmp_path, transcript)
    assert "tests_pass_without_run" in _context(first)
    assert report1["blocked"] is True
    second, report2 = _run(tmp_path, transcript)
    assert second.stdout == "", "an already-surfaced finding must stay silent"
    assert _checks(report2) == {"tests_pass_without_run"}, "the report still lists it"
    assert report2["blocked"] is False
    assert report2["already_surfaced"] == 1


def test_the_seen_set_lives_beside_the_report_and_is_per_session(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    _run(tmp_path, transcript)
    seen_dir = tmp_path / "stop_claim_seen"
    files = sorted(p.name for p in seen_dir.iterdir())
    assert len(files) == 1 and files[0].endswith(".json"), files
    data = json.loads((seen_dir / files[0]).read_text(encoding="utf-8"))
    assert data["session_id"] == SID and len(data["keys"]) == 1
    # Another session is a different conversation: it surfaces again.
    other, _report = _run(tmp_path, transcript, session="another-session")
    assert "tests_pass_without_run" in _context(other)


def test_a_new_finding_in_a_later_turn_still_surfaces_alone(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    _run(tmp_path, transcript)
    transcript = _session(tmp_path, _main_rows("The full suite passes.",
                                                "CI is green on main."))
    proc, report = _run(tmp_path, transcript)
    context = _context(proc)
    assert context.startswith("stop_claim_gate: 1 unbacked claim "), context
    assert "ci_claim_without_probe" in context
    assert "tests_pass_without_run" not in context
    assert _checks(report) == {"tests_pass_without_run", "ci_claim_without_probe"}


def test_the_same_claim_restated_in_a_later_turn_surfaces_again(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    _run(tmp_path, transcript)
    transcript = _session(tmp_path, _main_rows("The full suite passes.",
                                                "The full suite passes."))
    proc, _report = _run(tmp_path, transcript)
    assert _context(proc).startswith("stop_claim_gate: 1 unbacked claim ")


def test_a_reentry_stop_does_not_mark_a_finding_seen(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    quiet, report = _run(tmp_path, transcript, reentry=True)
    assert quiet.stdout == "" and report["reason"] == "stop_hook_active"
    proc, _report = _run(tmp_path, transcript)
    assert "tests_pass_without_run" in _context(proc), "never surfaced, so it surfaces now"


def test_report_only_mode_marks_nothing_seen(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    _run(tmp_path, transcript, arm=False)
    proc, _report = _run(tmp_path, transcript)
    assert "tests_pass_without_run" in _context(proc)


def test_a_corrupt_seen_file_is_an_empty_set_not_a_crash(tmp_path):
    transcript = _session(tmp_path, _main_rows("The full suite passes."))
    path = gate.seen_path(tmp_path / "stop_claim_seen", SID)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    proc, _report = _run(tmp_path, transcript)
    assert "tests_pass_without_run" in _context(proc)
    assert json.loads(path.read_text(encoding="utf-8"))["keys"]


def test_finding_key_normalises_the_claim_text_but_keeps_the_turn():
    base = {"check": "count_mismatch", "quote": "Full  suite: 5 passed.",
            "claimed": "5", "observed": "4", "turn": "a-1"}
    same = dict(base, quote="  full suite:\n5 PASSED. ", observed="3")
    later = dict(base, turn="a-9")
    other = dict(base, claimed="6")
    assert gate.finding_key(base) == gate.finding_key(same)
    assert gate.finding_key(base) != gate.finding_key(later)
    assert gate.finding_key(base) != gate.finding_key(other)


def test_seen_path_never_escapes_its_directory(tmp_path):
    for session in ("../../evil", "a/b", "", "x" * 300, "C:" + chr(92) + "x"):
        assert gate.seen_path(tmp_path, session).parent == tmp_path, session


def test_prune_keeps_the_newest_seen_files(tmp_path):
    import os
    for i in range(7):
        path = tmp_path / f"s{i}.json"
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
    gate.prune_seen(tmp_path, keep=3)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s4.json", "s5.json", "s6.json"]


def test_live_seen_dir_sits_under_ops_runtime():
    assert gate.DEFAULT_SEEN_DIR == gate.ROOT / "ops" / "runtime" / "stop_claim_seen"


# ====================================================== (b) advisory never to chat

def test_an_advisory_finding_never_reaches_the_feedback_line(tmp_path):
    agents = {AGENT: [_pair("toolu_01bp", "git commit --no-verify -m x", COMMIT_OK,
                            cwd=ROOT)]}
    transcript = _session(tmp_path, _main_rows("The full suite passes."), agents)
    proc, report = _run(tmp_path, transcript)
    context = _context(proc)
    assert context.startswith("stop_claim_gate: 1 unbacked claim (tests_pass_without_run)")
    assert "subagent_hook_bypass" not in context
    assert _checks(report) == {"tests_pass_without_run", "subagent_hook_bypass"}


def test_only_advisory_findings_emit_nothing(tmp_path):
    out = "To https://github.com/owner/repo.git\n   00618c625..0b8511641  main -> main"
    agents = {AGENT: [_pair("toolu_01p", "git push --no-verify origin main", out,
                            cwd=ROOT)]}
    # A push claim the sub-agent's push clears (RM-687's measured shape), so
    # the only finding left is the advisory bypass.
    transcript = _session(tmp_path, _main_rows("- **Commits:** 2a072d72f, pushed."), agents)
    proc, report = _run(tmp_path, transcript)
    assert "subagent_hook_bypass" in _checks(report)
    assert proc.stdout == "" and report["blocked"] is False


# ================================================ (c) subagent_hook_bypass scope

def test_a_bypass_the_hook_refused_is_not_counted(tmp_path):
    checks = _bypass_checks(tmp_path, "git commit --no-verify -m x", GITLOCK_DENIAL,
                            is_error=True, cwd=ROOT, result_row=HOOK_DENIAL_ROW)
    assert "subagent_hook_bypass" not in checks


@pytest.mark.parametrize("output,row", [
    (GITLOCK_DENIAL, None),                       # text alone, no row markers
    ("This agent is isolated in the worktree X, but this command is too complex "
     "to verify that it stays inside the worktree. Refusing to run it.", None),
    ("<tool_use_error>This agent is isolated in the worktree X.</tool_use_error>", None),
    ("<tool_use_error>Blocked: sleep 60 followed by: git status</tool_use_error>", None),
    ("Permission to use Bash has been denied.", None),
    ("Remove-Item on system path is blocked.",
     {"toolDenialKind": "permission-rule",
      "permissionDecision": {"decision": "reject", "source": "config"}}),
])
def test_every_measured_refusal_shape_is_not_an_execution(tmp_path, output, row):
    checks = _bypass_checks(tmp_path, "git commit --no-verify -m x", output,
                            is_error=True, cwd=ROOT, result_row=row)
    assert "subagent_hook_bypass" not in checks


def test_a_failed_but_executed_bypass_still_counts(tmp_path):
    checks = _bypass_checks(tmp_path, "git commit --no-verify -m x",
                            "Exit code 1\nnothing to commit, working tree clean",
                            is_error=True, cwd=ROOT)
    assert "subagent_hook_bypass" in checks


def test_a_bypass_with_no_result_yet_is_not_counted(tmp_path):
    use = _pair("toolu_01bp", "git commit --no-verify -m x", COMMIT_OK, cwd=ROOT)[:1]
    transcript = _session(tmp_path, _main_rows("The full suite passes."), {AGENT: [use]})
    assert "subagent_hook_bypass" not in _checks(_run(tmp_path, transcript, arm=False)[1])


def _scratch_repo(tmp_path):
    repo = tmp_path / "scratch" / "idprobe" / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_a_bypass_in_a_throwaway_repo_via_cd_is_not_counted(tmp_path):
    repo = _scratch_repo(tmp_path)
    command = (f'S="{repo.parent.as_posix()}"; mkdir -p "$S/repo"; cd "$S/repo" && '
               'git init -q . && git -c core.hooksPath=/nonexistent commit -q '
               '--no-verify -m "feat: x"')
    assert "subagent_hook_bypass" not in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                        cwd=ROOT)


def test_a_bypass_in_a_throwaway_repo_via_dash_c_is_not_counted(tmp_path):
    repo = _scratch_repo(tmp_path)
    command = f'git -C "{repo}" commit --no-verify -m x'
    assert "subagent_hook_bypass" not in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                        cwd=ROOT)


def test_a_bypass_whose_row_cwd_is_outside_rc_is_not_counted(tmp_path):
    repo = _scratch_repo(tmp_path)
    assert "subagent_hook_bypass" not in _bypass_checks(
        tmp_path, "git commit --no-verify -m x", COMMIT_OK, cwd=repo)


def test_a_bypass_since_deleted_outside_any_repo_is_not_counted(tmp_path):
    gone = tmp_path / "scratch" / "deleted" / "repo"
    command = f'cd "{gone.as_posix()}" && git commit --no-verify -m x'
    assert "subagent_hook_bypass" not in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                        cwd=ROOT)


@pytest.mark.parametrize("command", [
    "git commit --no-verify -m x",
    'cd "{root}/tools" && git commit --no-verify -m x',
    'git -C "{root}" -c core.hooksPath= commit -m x',
    "cd tools; git push --no-verify origin main",
])
def test_a_bypass_in_rc_is_still_counted(tmp_path, command):
    command = command.format(root=ROOT.as_posix())
    assert "subagent_hook_bypass" in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                    cwd=ROOT)


def test_a_bypass_that_dash_c_points_into_rc_from_outside_is_counted(tmp_path):
    repo = _scratch_repo(tmp_path)
    command = f'git -C "{ROOT.as_posix()}" commit --no-verify -m x'
    assert "subagent_hook_bypass" in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                    cwd=repo)


def test_a_bypass_with_an_unresolvable_target_still_counts(tmp_path):
    command = 'cd "$UNSET_SOMEWHERE/repo" && git commit --no-verify -m x'
    assert "subagent_hook_bypass" in _bypass_checks(tmp_path, command, COMMIT_OK,
                                                    cwd=ROOT)


def test_a_row_without_cwd_falls_back_to_the_session_cwd(tmp_path):
    # The payload cwd is ROOT, which is RC: counted (RM-687's own fixture shape).
    assert "subagent_hook_bypass" in _bypass_checks(
        tmp_path, "git commit --no-verify -m x", COMMIT_OK)


def test_git_common_dir_follows_a_linked_worktree(tmp_path):
    main = tmp_path / "main"
    link = main / ".git" / "worktrees" / "wt1"
    link.mkdir(parents=True)
    (link / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "elsewhere" / "wt1"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {link.as_posix()}\n", encoding="utf-8")
    (worktree / "sub").mkdir()
    want = gate._git_common_dir(main)
    assert want is not None
    assert gate._git_common_dir(worktree / "sub") == want
    assert gate._git_common_dir(worktree / "sub" / "not-yet-made") == want
    assert gate._git_common_dir(tmp_path / "nowhere") != want


def test_rc_root_resolves_to_its_common_dir():
    assert gate._git_common_dir(gate.ROOT) is not None


@pytest.mark.parametrize("raw,want", [
    ("/e/Riot Commander/tools", "E:/Riot Commander/tools"),
    ("/c", "C:/"),
    ("E:/x", "E:/x"),
    ("relative/dir", "relative/dir"),
])
def test_msys_drive_paths_are_made_native(raw, want):
    assert gate._native_path(raw) == want


def test_path_placement_follows_the_host(monkeypatch):
    """CI runs on POSIX, where `/x` is a real absolute path; on Windows a
    non-drive `/x` is Git Bash's own root, so it cannot be placed."""
    monkeypatch.setattr(gate, "_WINDOWS", True)
    assert gate._join(None, "/srv/repo") is None
    assert gate._join(None, "/e/Repo") == "E:/Repo"
    assert gate._join("E:/Repo", "tools") == "E:/Repo/tools"
    monkeypatch.setattr(gate, "_WINDOWS", False)
    assert gate._join(None, "/srv/repo") == "/srv/repo"
    assert gate._join(None, "/e/Repo") == "/e/Repo"
    assert gate._join(None, "tools") is None
    assert gate._join("/srv/repo", "$UNSET_X/x") is None


# ========================================================= (d) count sum

def _audit(claim, runs=(), agent_results=()):
    ev = {"texts": [claim], "bash": [r[0] for r in runs], "edited": [],
          "runs": [{"cmd": c, "output": o} for c, o in runs],
          "agent_results": list(agent_results)}
    return gate.audit(ev)


def _mismatch(findings):
    return [f["claimed"] for f in findings if f["check"] == "count_mismatch"]


def test_a_sum_of_two_counts_in_one_output_block_is_accepted():
    assert _mismatch(_audit(SUM_CLAIM, [(DUAL_CMD, DUAL_OUT)])) == []


def test_an_unrelated_number_beside_that_block_is_still_flagged():
    assert _mismatch(_audit("- **Full suite:** 39183 passed.",
                            [(DUAL_CMD, DUAL_OUT)])) == ["39183"]


def test_a_sum_across_two_separate_blocks_is_still_flagged():
    runs = [("python -m pytest agents/daemon_slayer -q", "10971 passed in 47.70s"),
            ("python -m pytest tests -q", "7 failed, 28211 passed in 314.17s")]
    assert _mismatch(_audit(SUM_CLAIM, runs)) == ["39182"]


TRIPLE = "100 passed in 1.0s\n200 passed in 2.0s\n300 passed in 3.0s"


@pytest.mark.parametrize("claim,flagged", [
    ("500 passed.", []),            # 200 + 300
    ("600 passed.", []),            # all three
    ("100 passed.", []),            # observed outright
    ("450 passed.", ["450"]),       # no subset sums to it
    ("700 passed.", ["700"]),       # needs a count twice
])
def test_subset_sums_within_one_block(claim, flagged):
    assert _mismatch(_audit(claim, [("python -m pytest -q", TRIPLE)])) == flagged


def test_a_repeated_summary_line_cannot_double_a_count():
    out = "537 passed in 12.3s\n537 passed in 12.3s"
    assert _mismatch(_audit("1074 passed.", [("python -m pytest -q", out)])) == ["1074"]


def test_a_large_block_accepts_only_its_total():
    out = "\n".join(f"{n} passed in 0.1s" for n in range(100, 900, 100))  # 8 counts
    runs = [("python -m pytest -q", out)]
    assert _mismatch(_audit("3600 passed.", runs)) == []
    assert _mismatch(_audit("1500 passed.", runs)) == ["1500"]


SEPARATE_RUNS = [("python -m pytest agents/daemon_slayer -q", "10971 passed in 47.70s"),
                 ("python -m pytest tests -q", "7 failed, 28211 passed in 314.17s")]
RESULT_BOTH = ("Suite: daemon_slayer arm 10971 passed, 0 failed. "
               "tests arm 28211 passed, 7 failed.")


def test_a_sum_of_counts_named_in_one_subagent_result_is_accepted():
    assert _mismatch(_audit(SUM_CLAIM, SEPARATE_RUNS, [RESULT_BOTH])) == []


def test_a_subagent_result_cannot_vouch_for_an_unobserved_component():
    runs = [SEPARATE_RUNS[0], ("python -m pytest tests -q", "28210 passed in 314.17s")]
    assert _mismatch(_audit(SUM_CLAIM, runs, [RESULT_BOTH])) == ["39182"]


def test_counts_split_over_two_subagent_results_are_still_flagged():
    results = ["daemon_slayer arm 10971 passed.", "tests arm 28211 passed."]
    assert _mismatch(_audit(SUM_CLAIM, SEPARATE_RUNS, results)) == ["39182"]


def _notification(agent_id, result):
    text = (f"<task-notification>\n<task-id>{agent_id}</task-id>\n"
            "<status>completed</status>\n<summary>Agent finished</summary>\n"
            f"<result>{result}</result>\n</task-notification>")
    return {"type": "user", "uuid": "u-note", "sessionId": SID,
            "message": {"role": "user", "content": text}}


def test_collect_evidence_reads_subagent_results_from_both_transports():
    rows = [_notification(AGENT, RESULT_BOTH),
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_ag", "name": "Agent",
                 "input": {"prompt": "10 passed"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_ag",
                 "content": [{"type": "text", "text": "Foreground: 5 passed."}]}]}},
            {"type": "user", "message": {"role": "user",
                                         "content": "plain prompt, 99 passed"}}]
    ev = gate.collect_evidence(rows)
    assert ev["agent_results"] == [RESULT_BOTH, "Foreground: 5 passed."]


def test_the_measured_sum_is_cleared_end_to_end(tmp_path):
    """Session e4ff80f0 in miniature: main ran nothing, one sub-agent ran the
    dual suite and reported both arms, main summed them."""
    agents = {AGENT: [_pair("toolu_01py", DUAL_CMD, DUAL_OUT, cwd=ROOT)]}
    rows = _main_rows(SUM_CLAIM)
    rows.insert(1, _notification(AGENT, RESULT_BOTH))
    transcript = _session(tmp_path, rows, agents)
    proc, report = _run(tmp_path, transcript)
    assert report["findings"] == [], report["findings"]
    assert proc.stdout == ""


def test_the_measured_sum_plus_one_still_flags_end_to_end(tmp_path):
    agents = {AGENT: [_pair("toolu_01py", DUAL_CMD, DUAL_OUT, cwd=ROOT)]}
    transcript = _session(tmp_path, _main_rows("- **Full suite:** 39183 passed."), agents)
    proc, report = _run(tmp_path, transcript)
    assert "count_mismatch" in _checks(report)
    assert "count_mismatch" in _context(proc)
