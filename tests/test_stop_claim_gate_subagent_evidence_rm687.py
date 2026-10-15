"""RM-687: credit evidence that lives in THIS session's sub-agent transcripts.

Under kit v10 SUBAGENT-FIRST deny mode the main thread cannot run pytest, gh,
git or Edit, so every such act is a sub-agent's - and a sub-agent's tool rows
are NOT in the main transcript. Measured 2026-10-08 (CLI 2.1.294) on session
9f5488a7: the main transcript held 135 rows, 0 of them isSidechain; the
sub-agent rows live in `<transcript stem>/subagents/agent-<agentId>.jsonl`,
nested agents in the same flat dir. The gate therefore flagged TRUE relayed
claims ("- **Commits:** 2a072d72f, 6e7a4e50b, 0b8511641, pushed.").

Sub-agent evidence is CREDIT-ONLY: it can remove a main-only finding of a
CLEARABLE check, never add one. Every kind pairs a tool_use to its tool_result
by id (sub-agents issue parallel calls, so adjacency is wrong): test runs (the
deferred background mechanism included), successful edits, CI probes, commits
with git's `[<branch> <sha>]` line, merges with a success line and no conflict,
and pushes (a ref-update line inside git's `To <url>` block, an observable
`merge-base --is-ancestor` on a remote-tracking ref, or a dated reflog
`update by push` after session start). A sub-agent hook bypass is reported as
the ADVISORY check subagent_hook_bypass.

Driven END-TO-END like tests/test_stop_claim_gate.py: the gate runs as a
subprocess with the Stop payload on stdin. Row shapes are copied from the
measured transcripts. The NEGATIVE cases are load-bearing - prose, an Agent
prompt, a dry run, a stash push, a rejected push, a failed edit, an empty
commit, a conflicted merge, another session's dir and an unobservable probe
must all still flag.
"""
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import stop_claim_gate as gate

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "tools" / "stop_claim_gate.py"

SID = "9f5488a7-0000-4000-8000-0000000rm687"
START = "2026-10-08T19:21:46.139Z"

PUSH_CLAIM = "- **Commits:** 2a072d72f, 6e7a4e50b, 0b8511641, pushed."

# Measured 2026-10-08, agent-a2b90869b12280345.jsonl (owner/repo anonymised).
PUSH_CMD = ('cd "/e/Example Repo" && timeout 280 git push origin main 2>&1 | tail -8; '
            'git fetch -q origin && git rev-parse --short=9 HEAD origin/main')
PUSH_OUT = ("Exit code 128\n"
            "[sibling-sweep] clean: 10666 bytes, 6 file(s) (0 untracked), 3 commit "
            "message(s), 0 binary/LFS blobs not content-scanned.\r\n"
            "[credential-history] push: 0 finding(s) over 72 added line(s) in 6 "
            "file-commit(s), 0.1s\r\n"
            "remote: \n"
            "To https://github.com/owner/repo.git\n"
            "   00618c625..0b8511641  main -> main\n"
            "fatal: Needed a single revision")
REJECTED_OUT = ("To https://github.com/owner/repo.git\n"
                " ! [rejected]        main -> main (fetch first)\n"
                "error: failed to push some refs to 'https://github.com/owner/repo.git'")

# Measured 2026-10-08, agent-add91de178dd26c09.jsonl (the verifier probe).
ANCESTRY_CMD = ('cd "E:/Example Repo" && git fetch origin main 2>&1; echo "fetch_exit=$?"; '
                'for s in 2a072d72f 6e7a4e50b 0b8511641; do echo "== $s"; git cat-file -t $s; '
                'git merge-base --is-ancestor $s origin/main; echo "ancestor_exit=$?"; done; '
                'git rev-parse origin/main')


def _ancestry_out(code):
    return ("From https://github.com/owner/repo\n"
            " * branch                main       -> FETCH_HEAD\n"
            "fetch_exit=0\n"
            "== 2a072d72f\ncommit\nancestor_exit=" + code + "\n"
            "== 6e7a4e50b\ncommit\nancestor_exit=" + code + "\n"
            "== 0b8511641\ncommit\nancestor_exit=" + code + "\n"
            "0b851164121e7bfcc4a80d5e41e8ca25d82fcfd6")


REFLOG_CMD = 'cd "E:/Example Repo" && git reflog show --date=iso refs/remotes/origin/main | head -4'
REFLOG_OUT = ("0b8511641 refs/remotes/origin/main@{2026-10-08 14:35:01 -0500}: update by push\n"
              "00618c625 refs/remotes/origin/main@{2026-10-08 11:23:21 -0500}: update by push\n"
              "c25553f53 refs/remotes/origin/main@{2026-10-08 10:51:54 -0500}: update by push\n"
              "0adcd5018 refs/remotes/origin/main@{2026-10-08 10:39:25 -0500}: fetch origin: fast-forward")


# ------------------------------------------------------------------ builders

def _main_rows(*texts, start=START):
    """Main-thread rows: a first user row carrying the session start, then one
    assistant text row per claim (timestamped later)."""
    rows = [{"type": "user", "timestamp": start, "sessionId": SID,
             "message": {"role": "user", "content": "continue"}}]
    for i, text in enumerate(texts):
        rows.append({"type": "assistant", "timestamp": f"2026-10-08T23:00:{i:02d}.000Z",
                     "sessionId": SID,
                     "message": {"role": "assistant",
                                 "content": [{"type": "text", "text": text}]}})
    return rows


def _side(agent_id, kind, content, ts="2026-10-08T19:30:00.000Z"):
    return {"parentUuid": None, "isSidechain": True, "agentId": agent_id,
            "type": kind, "message": {"role": kind, "content": content},
            "timestamp": ts, "sessionId": SID}


def _use(tid, command, name="Bash"):
    return {"type": "tool_use", "id": tid, "name": name,
            "input": {"command": command, "description": "probe"}}


def _result(tid, content, is_error=None):
    block = {"type": "tool_result", "tool_use_id": tid, "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return block


def _pair(agent_id, tid, command, output, is_error=None, name="Bash"):
    """One sub-agent tool call and its result, in the measured row shape."""
    return [_side(agent_id, "assistant", [_use(tid, command, name)]),
            _side(agent_id, "user", [_result(tid, output, is_error)])]


def _agent(agent_id, *rows):
    head = _side(agent_id, "user", "Run the task.")
    return [head] + [r for chunk in rows for r in (chunk if isinstance(chunk, list) else [chunk])]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _session(tmp_path, main_rows, agents=None, stem=SID):
    """Lay the session out as measured: <dir>/<sid>.jsonl plus
    <dir>/<stem>/subagents/agent-<id>.jsonl."""
    transcript = tmp_path / (SID + ".jsonl")
    _write_jsonl(transcript, main_rows)
    for agent_id, rows in (agents or {}).items():
        _write_jsonl(tmp_path / stem / "subagents" / ("agent-" + agent_id + ".jsonl"), rows)
    return transcript


def _payload(transcript):
    return json.dumps({"session_id": SID, "transcript_path": str(transcript),
                       "cwd": str(ROOT), "hook_event_name": "Stop",
                       "stop_hook_active": False})


def _run(tmp_path, transcript, arm=False):
    """Invoke the gate exactly as a Stop hook would: JSON on stdin."""
    report = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(GATE), "--report", str(report),
         "--history", str(tmp_path / "history.jsonl")] + (["--arm"] if arm else []),
        input=_payload(transcript), capture_output=True, text=True,
        cwd=str(ROOT), check=False)
    assert proc.returncode == 0, f"the gate must exit 0: {proc.stderr}"
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc, json.loads(report.read_text(encoding="utf-8"))


def _checks(report):
    return {f["check"] for f in report["findings"]}


def _gate_on(tmp_path, claim, *agent_rows, start=START, stem=SID):
    """One claim in main, one sub-agent 'a1' holding AGENT_ROWS."""
    agents = {"a1b2c3": _agent("a1b2c3", *agent_rows)} if agent_rows else {}
    transcript = _session(tmp_path, _main_rows(claim, start=start), agents, stem=stem)
    return _run(tmp_path, transcript)[1]


# ------------------------------------------------------------- 1: real push

def test_push_only_in_subagent_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", PUSH_CMD, PUSH_OUT, is_error=True))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"
    assert report["subagent_push"]["agent"] == "a1b2c3"


def test_push_with_list_content_result_is_credited(tmp_path):
    content = [{"type": "text", "text": PUSH_OUT}]
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", PUSH_CMD, content, is_error=True))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"


def test_everything_up_to_date_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", "git push origin main",
                            "Everything up-to-date\r\n"))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"


# ------------------------------------------------------- 2: no push anywhere

def test_no_push_anywhere_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01st", "git status -s", " M tools/x.py"),
                      _pair("a1b2c3", "toolu_01lg", "git log --oneline -3",
                            "0b8511641 docs\n6e7a4e50b docs\n2a072d72f docs"))
    assert "push_claim_without_push" in _checks(report)
    assert "subagent_push" not in report
    # Loaded (a clearable finding stood and a file existed), nothing cleared.
    assert report["subagent_cleared"] == []


def test_no_subagent_dir_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM)
    assert "push_claim_without_push" in _checks(report)
    assert "subagent_push" not in report
    assert "subagent_cleared" not in report


# --------------------------------------------------------- 3: rejected push

def test_rejected_push_in_subagent_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", "git push origin main", REJECTED_OUT,
                            is_error=True))
    assert "push_claim_without_push" in _checks(report)
    assert "subagent_push" not in report


def test_rejected_push_followed_by_fetch_output_still_flags(tmp_path):
    # A fetch prints ref-update lines of the SAME shape under a `From <url>`
    # header; they must not launder a rejected push in the same command.
    out = (REJECTED_OUT + "\nFrom https://github.com/owner/repo\n"
           "   00618c625..0b8511641  main       -> origin/main")
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", "git push origin main; git fetch origin", out))
    assert "push_claim_without_push" in _checks(report)


# ------------------------------------------------ 4: dry run and stash push

def test_dry_run_push_with_ref_line_still_flags(tmp_path):
    out = "To https://github.com/owner/repo.git\n   00618c625..0b8511641  main -> main"
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01dry", "git push --dry-run origin main", out))
    assert "push_claim_without_push" in _checks(report)


def test_stash_push_still_flags(tmp_path):
    out = ("Saved working directory and index state On main: rm687\n"
           "   00618c625..0b8511641  main -> main")
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01stash", 'git stash push -u -m "rm687"', out))
    assert "push_claim_without_push" in _checks(report)


# ------------------------------------------------ 5: prose and Agent prompts

def test_subagent_prose_never_credits(tmp_path):
    prose = _side("a1b2c3", "assistant", [{"type": "text", "text": "I pushed it."}])
    report = _gate_on(tmp_path, PUSH_CLAIM, prose)
    assert "push_claim_without_push" in _checks(report)


def test_agent_tool_use_prompt_never_credits(tmp_path):
    spawn = _side("a1b2c3", "assistant", [{
        "type": "tool_use", "id": "toolu_01agent", "name": "Agent",
        "input": {"description": "push it", "prompt": "Run git push origin main now.",
                  "command": "git push origin main"}}])
    reply = _side("a1b2c3", "user", [_result(
        "toolu_01agent", "To https://github.com/owner/repo.git\n"
                         "   00618c625..0b8511641  main -> main")])
    report = _gate_on(tmp_path, PUSH_CLAIM, spawn, reply)
    assert "push_claim_without_push" in _checks(report)


# ------------------------------------------------ 6: another session's dir

def test_push_under_a_different_session_dir_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01push", PUSH_CMD, PUSH_OUT, is_error=True),
                      stem="11111111-2222-4333-8444-555555555555")
    assert "push_claim_without_push" in _checks(report)
    assert "subagent_push" not in report


# ------------------------------------------------ pairing is by id, not order

def test_parallel_calls_pair_by_id_not_adjacency(tmp_path):
    # Two calls in ONE assistant row; results arrive in REVERSE order. Pairing
    # by adjacency would give the push the cat's output (a ref-update line).
    agent = "a1b2c3"
    uses = _side(agent, "assistant", [_use("toolu_A", "git push origin main"),
                                       _use("toolu_B", "cat old_push.log")])
    results = _side(agent, "user", [
        _result("toolu_B", "To https://x/r.git\n   00618c625..0b8511641  main -> main"),
        _result("toolu_A", REJECTED_OUT, is_error=True)])
    report = _gate_on(tmp_path, PUSH_CLAIM, uses, results)
    assert "push_claim_without_push" in _checks(report)


def test_parallel_calls_credit_the_real_push_out_of_order(tmp_path):
    agent = "a1b2c3"
    uses = _side(agent, "assistant", [_use("toolu_A", PUSH_CMD),
                                       _use("toolu_B", "git status -s")])
    results = _side(agent, "user", [_result("toolu_B", ""),
                                    _result("toolu_A", PUSH_OUT, is_error=True)])
    report = _gate_on(tmp_path, PUSH_CLAIM, uses, results)
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"


# ------------------------------------------------------------- 7: ancestry

def test_ancestry_measured_probe_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc", ANCESTRY_CMD, _ancestry_out("0"),
                            is_error=False))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "ancestry"


def test_ancestry_nonzero_exit_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc", ANCESTRY_CMD, _ancestry_out("1"),
                            is_error=False))
    assert "push_claim_without_push" in _checks(report)


def test_ancestry_and_chain_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc",
                            "git merge-base --is-ancestor abc1234 origin/main && echo yes",
                            "yes", is_error=False))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "ancestry"


def test_ancestry_bare_probe_with_redirect_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc",
                            'git merge-base --is-ancestor abc1234 "HEAD@{u}" 2>/dev/null',
                            "", is_error=False))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "ancestry"


def test_ancestry_and_chain_errored_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc",
                            "git merge-base --is-ancestor abc1234 origin/main && echo yes",
                            "Exit code 1", is_error=True))
    assert "push_claim_without_push" in _checks(report)


def test_ancestry_semicolon_echo_done_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc",
                            "git merge-base --is-ancestor abc1234 origin/main; echo done",
                            "done", is_error=False))
    assert "push_claim_without_push" in _checks(report)


def test_ancestry_against_local_ref_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01anc",
                            "git merge-base --is-ancestor abc1234 main",
                            "", is_error=False))
    assert "push_claim_without_push" in _checks(report)


def test_ancestry_unobservable_shapes_still_flag(tmp_path):
    shapes = [
        "git merge-base --is-ancestor abc1234 origin/main || true",
        "git merge-base --is-ancestor abc1234 origin/main | cat",
        # is_error then reflects the LAST statement, not the probe.
        "git merge-base --is-ancestor abc1234 origin/main && echo yes; echo done",
        # a quoted literal is data, not a probe.
        "echo 'git merge-base --is-ancestor abc1234 origin/main'",
    ]
    for i, command in enumerate(shapes):
        sub = tmp_path / f"case{i}"
        sub.mkdir()
        report = _gate_on(sub, PUSH_CLAIM,
                          _pair("a1b2c3", "toolu_01anc", command, "yes\ndone", is_error=False))
        assert "push_claim_without_push" in _checks(report), command


# --------------------------------------------------------------- 8: reflog

def test_reflog_push_after_session_start_is_credited(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01rl", REFLOG_CMD, REFLOG_OUT, is_error=False),
                      start="2026-10-08T19:21:46Z")
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "reflog"


def test_reflog_push_before_session_start_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01rl", REFLOG_CMD, REFLOG_OUT, is_error=False),
                      start="2026-10-08T20:00:00Z")
    assert "push_claim_without_push" in _checks(report)


def test_reflog_undated_or_zoneless_still_flags(tmp_path):
    for i, line in enumerate([
            "0b8511641 refs/remotes/origin/main@{0}: update by push",
            "0b8511641 refs/remotes/origin/main@{2026-10-08 14:35:01}: update by push"]):
        sub = tmp_path / f"case{i}"
        sub.mkdir()
        report = _gate_on(sub, PUSH_CLAIM,
                          _pair("a1b2c3", "toolu_01rl", REFLOG_CMD, line, is_error=False),
                          start="2026-10-08T19:21:46Z")
        assert "push_claim_without_push" in _checks(report), line


def test_reflog_walk_via_git_log_g_is_credited(tmp_path):
    out = "0b8511641 refs/remotes/origin/main@{2026-10-08T14:35:01-05:00}: update by push"
    report = _gate_on(tmp_path, PUSH_CLAIM,
                      _pair("a1b2c3", "toolu_01rl",
                            "git log -g --oneline --date=iso-strict origin/main", out),
                      start="2026-10-08T19:21:46Z")
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "reflog"


# ------------------------------------------------------------- 9: garbage

def _junk_lines():
    return [
        "not json at all",
        "5",
        "[1, 2]",
        '"a string"',
        '{"message": "str"}',
        '{"message": {"content": [1, null, "x"]}}',
        '{"type": "assistant", "message": {"content": [{"type": "tool_use", '
        '"name": "Bash", "id": "t1", "input": "notadict"}]}}',
        '{"type": "assistant", "message": {"content": [{"type": "tool_use", '
        '"name": "Bash", "id": ["unhashable"], "input": {"command": "git push"}}]}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result", '
        '"tool_use_id": ["x"], "content": {"weird": 1}}]}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result", '
        '"tool_use_id": "t1", "content": [5, {"type": "text", "text": 7}]}]}}',
    ]


def test_garbage_and_a_directory_named_like_a_transcript_never_raise(tmp_path):
    transcript = _session(tmp_path, _main_rows(PUSH_CLAIM))
    sub = tmp_path / SID / "subagents"
    (sub / "agent-x.jsonl").mkdir(parents=True)
    with open(sub / "agent-junk.jsonl", "wb") as handle:
        handle.write(b"\xff\xfe\x00 binary junk\n")
        handle.write(("\n".join(_junk_lines()) + "\n").encode("ascii"))
    proc, report = _run(tmp_path, transcript)
    assert "push_claim_without_push" in _checks(report)
    assert "subagent_push" not in report


def test_junk_rows_do_not_void_a_real_push_in_the_same_file(tmp_path):
    transcript = _session(tmp_path, _main_rows(PUSH_CLAIM))
    path = tmp_path / SID / "subagents" / "agent-mixed01.jsonl"
    path.parent.mkdir(parents=True)
    good = _agent("mixed01", _pair("mixed01", "toolu_01push", PUSH_CMD, PUSH_OUT, is_error=True))
    path.write_text("\n".join(_junk_lines() + [json.dumps(r) for r in good]) + "\n",
                    encoding="utf-8")
    report = _run(tmp_path, transcript)[1]
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"] == {"kind": "push", "agent": "mixed01"}


def test_never_raises_when_a_file_scan_blows_up(tmp_path, monkeypatch):
    transcript = _session(tmp_path, _main_rows(PUSH_CLAIM), {
        "a1b2c3": _agent("a1b2c3", _pair("a1b2c3", "t1", PUSH_CMD, PUSH_OUT))})

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(gate, "_scan_subagent_file", boom)
    assert gate.subagent_push_evidence(str(transcript)) is None
    loaded = gate.subagent_evidence(str(transcript))
    assert loaded is not None and loaded["push"] is None and loaded["runs"] == []


def test_agent_label_is_sanitised(tmp_path):
    transcript = _session(tmp_path, _main_rows(PUSH_CLAIM))
    path = tmp_path / SID / "subagents" / "agent-bad id!.jsonl"
    _write_jsonl(path, _agent("x", _pair("x", "t1", PUSH_CMD, PUSH_OUT)))
    assert gate.subagent_push_evidence(str(transcript)) == {"kind": "push", "agent": ""}


# ---------------------------------------------------- 10: merge and commit

def test_merge_claim_inherits_subagent_push(tmp_path):
    report = _gate_on(tmp_path, "Merged to main.",
                      _pair("a1b2c3", "toolu_01push", PUSH_CMD, PUSH_OUT, is_error=True))
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"


def test_merge_claim_without_any_evidence_still_flags(tmp_path):
    report = _gate_on(tmp_path, "Merged to main.",
                      _pair("a1b2c3", "toolu_01st", "git status -s", ""))
    assert "merge_claim_without_merge" in _checks(report)


def test_commit_and_push_relayed_together_are_both_cleared(tmp_path):
    # Round 3 widened check 6 (coordinator order): a sub-agent commit that
    # printed git's `[<branch> <sha>]` line backs a relayed commit claim.
    commit = _pair("a1b2c3", "toolu_01c", "git commit -F msg.txt",
                   "[main 0b8511641] docs: rm687\n 1 file changed")
    report = _gate_on(tmp_path, "I committed the fix and pushed it.", commit,
                      _pair("a1b2c3", "toolu_01push", PUSH_CMD, PUSH_OUT, is_error=True))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert "commit_claim_without_commit" not in _checks(report), report["findings"]
    assert report["subagent_cleared"] == ["commit_claim_without_commit",
                                          "push_claim_without_push"]


# ------------------------------------------------------------- 11: laziness

def test_no_claim_means_no_subagent_scan(tmp_path):
    transcript = _session(tmp_path, _main_rows("All set for the next step."))
    sub = tmp_path / SID / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-junk.jsonl").write_bytes(b"\x00\x01 not json\n{]\n")
    report = _run(tmp_path, transcript)[1]
    assert report["findings"] == []
    assert not [key for key in report if key.startswith("subagent_")], report


def _main_in_process(tmp_path, monkeypatch, transcript):
    calls = []

    def recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(gate, "subagent_evidence", recorder)
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload(transcript)))
    rc = gate.main(["--report", str(tmp_path / "r.json"),
                    "--history", str(tmp_path / "h.jsonl")])
    assert rc == 0
    return calls


def test_scan_is_lazy_in_process(tmp_path, monkeypatch):
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    transcript = _session(quiet, _main_rows("Nothing to report."))
    assert _main_in_process(quiet, monkeypatch, transcript) == []

    claim = tmp_path / "claim"
    claim.mkdir()
    transcript = _session(claim, _main_rows(PUSH_CLAIM))
    calls = _main_in_process(claim, monkeypatch, transcript)
    assert len(calls) == 1
    args = calls[0][0]
    assert args[0] == str(transcript)
    assert str(args[1]) == "2026-10-08 19:21:46.139000+00:00"


# ---------------------------------------------------------- unit helpers

def test_subagent_dir_is_derived_from_the_transcript_stem(tmp_path):
    transcript = tmp_path / (SID + ".jsonl")
    assert gate.subagent_dir(str(transcript)) == tmp_path / SID / "subagents"


def test_session_start_is_earliest_aware_timestamp():
    rows = [5, {"timestamp": "junk"}, {"timestamp": "2026-10-08T19:21:46"},
            {"timestamp": "2026-10-08T23:00:00.000Z"},
            {"timestamp": "2026-10-08T19:21:46.139Z"}, {"no": "ts"}]
    start = gate._session_start(rows)
    assert start is not None and start.tzinfo is not None
    assert start.isoformat() == "2026-10-08T19:21:46.139000+00:00"
    assert gate._session_start([{"timestamp": "2026-10-08T19:21:46"}]) is None
    assert gate._session_start([]) is None


# ===================================================================
# Round 2 - verifier refutation of a8ffe57c0 (2026-10-08): four credited
# fakes and one quadratic regex. Each case below was CREDITED (or hung) by
# that commit and must now flag (or finish fast).
# ===================================================================

# ------------------------------------------- R2.1: dry-run evasion, BOTH paths

def _main_thread_checks(sentence, command):
    """Check 9 / 10 on the MAIN-thread path (audit over the command alone)."""
    ev = {"texts": [sentence], "bash": [command], "edited": [],
          "runs": [], "ci_runs": [], "artifacts": []}
    return {f["check"] for f in gate.audit(ev)}


DRY_RUN_SPELLINGS = [
    "git push -nv origin main",        # bundled short flags
    "git push -vn origin main",
    "git push -fn origin main",
    "git push origin main -nv",
    "git push --dry origin main",      # git accepts an unambiguous prefix
    "git push --dr origin main",
    "git push --dry-ru origin main",
    "git push --dry-run origin main",
    "git push -n origin main",
]


@pytest.mark.parametrize("command", DRY_RUN_SPELLINGS)
def test_main_thread_dry_run_spellings_do_not_back_a_push(command):
    assert not gate._did_push(gate.strip_command_noise(command)), command
    assert "push_claim_without_push" in _main_thread_checks(
        "The agent committed X and pushed.", command), command


REAL_PUSH_SPELLINGS = [
    "git push -o ci.skip origin main",     # -o takes a value; it is not -n
    "git push -onotify origin main",       # attached -o value holding an n
    "git push --push-option=nightly origin main",
    "git push --no-verify origin main",    # a long option with an n in it
    "git push --no-thin origin main",
    "git push --force-with-lease origin main",
    "git push -v origin main",
    "git push -u origin HEAD",
    "git push --delete origin old-branch",
]


@pytest.mark.parametrize("command", REAL_PUSH_SPELLINGS)
def test_main_thread_real_push_spellings_still_back_a_push(command):
    assert gate._did_push(gate.strip_command_noise(command)), command
    assert "push_claim_without_push" not in _main_thread_checks(
        "The agent committed X and pushed.", command), command


@pytest.mark.parametrize("command", ["git push -nv origin main 2>&1",
                                     "git push --dry origin main 2>&1"])
def test_subagent_dry_run_spellings_still_flag(tmp_path, command):
    out = ("Pushing to https://github.com/owner/repo.git\n"
           "To https://github.com/owner/repo.git\n   00618c625..0b8511641  main -> main")
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01dry", command, out))
    assert "push_claim_without_push" in _checks(report), command


# ------------------------------------- R2.2: push evidence is POSITIVELY anchored

def test_rejected_push_then_fetch_tail_still_flags(tmp_path):
    # `| tail -1` cut the fetch's `From <url>` header, leaving only its
    # update line - whose destination is a remote-tracking ref.
    out = REJECTED_OUT + "\n   00618c625..0b8511641  main       -> origin/main"
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair(
        "a1b2c3", "toolu_01push", "git push origin main 2>&1; git fetch origin 2>&1 | tail -1", out))
    assert "push_claim_without_push" in _checks(report)


def test_ref_line_without_a_to_header_still_flags(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair(
        "a1b2c3", "toolu_01push", "git push origin main 2>&1 | tail -1",
        "   00618c625..0b8511641  main -> main"))
    assert "push_claim_without_push" in _checks(report)


@pytest.mark.parametrize("dst", ["origin/main", "refs/remotes/origin/main", "FETCH_HEAD"])
def test_fetch_shaped_destination_never_credits(tmp_path, dst):
    out = "To https://github.com/owner/repo.git\n   00618c625..0b8511641  main -> " + dst
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01push",
                                                  "git push origin main", out))
    assert "push_claim_without_push" in _checks(report), dst


def test_ref_line_after_the_push_block_closed_still_flags(tmp_path):
    # git prints every ref status line straight after `To <url>`; a ref-shaped
    # line after the rejection's `error:` line is not push status.
    out = REJECTED_OUT + "\n   00618c625..0b8511641  main -> main"
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair(
        "a1b2c3", "toolu_01push", "git push origin main 2>&1; cat old.log", out))
    assert "push_claim_without_push" in _checks(report)


def test_verbose_and_multi_ref_push_is_credited(tmp_path):
    out = ("Pushing to https://github.com/owner/repo.git\n"
           "To https://github.com/owner/repo.git\n"
           " ! [rejected]        side -> side (fetch first)\n"
           "   00618c625..0b8511641  main -> main\n"
           "error: failed to push some refs to 'https://github.com/owner/repo.git'")
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01push",
                                                  "git push -v origin main side", out))
    assert "push_claim_without_push" not in _checks(report), report["findings"]
    assert report["subagent_push"]["kind"] == "push"


# ----------------------------------------- R2.3: a backgrounded call never credits

BG_LAUNCH = ("Command running in background with ID: b1x. Output is being written "
             "to: C:/x/b1x.output")


def _bg_pair(agent_id, tid, command, output):
    rows = _pair(agent_id, tid, command, output, is_error=False)
    rows[0]["message"]["content"][0]["input"]["run_in_background"] = True
    return rows


def test_backgrounded_ancestry_probe_never_credits(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM, _bg_pair(
        "a1b2c3", "toolu_01bg", "git merge-base --is-ancestor abc1234 origin/main", BG_LAUNCH))
    assert "push_claim_without_push" in _checks(report)


def test_backgrounded_push_never_credits_even_with_push_output(tmp_path):
    report = _gate_on(tmp_path, PUSH_CLAIM, _bg_pair(
        "a1b2c3", "toolu_01bg", PUSH_CMD, PUSH_OUT))
    assert "push_claim_without_push" in _checks(report)


def test_background_launch_result_never_credits(tmp_path):
    # No run_in_background flag in the input, but the RESULT is a launch handoff.
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair(
        "a1b2c3", "toolu_01bg", "git merge-base --is-ancestor abc1234 origin/main && echo yes",
        BG_LAUNCH, is_error=False))
    assert "push_claim_without_push" in _checks(report)


# -------------------------------------------------- R2.4: no quadratic blowup

_PERF_SCRIPT = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
base = Path(sys.argv[2])
transcript = base / "s.jsonl"
transcript.write_text("{}\n", encoding="utf-8")
sub = base / "s" / "subagents"
sub.mkdir(parents=True)
out = "To https://x/r.git\n" + " \t" * 100000 + "\n" + " " * 200000 + "x\n"
rows = [
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1",
        "name": "Bash", "input": {"command": "git push origin main"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result",
        "tool_use_id": "t1", "content": out}]}},
]
(sub / "agent-perf.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                                      encoding="utf-8")
began = time.perf_counter()
credit = gate.subagent_push_evidence(str(transcript))
print(json.dumps({"elapsed": time.perf_counter() - began, "credit": credit}))
"""


def test_200k_whitespace_line_in_a_push_result_is_fast(tmp_path):
    try:
        proc = subprocess.run([sys.executable, "-c", _PERF_SCRIPT, str(ROOT), str(tmp_path)],
                              capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        pytest.fail("a 200k-char whitespace line took over 30s (quadratic regex)")
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["elapsed"] < 1.0, result
    assert result["credit"] is None


def test_overlong_result_line_is_skipped_not_matched():
    long_ref = " " * 1001 + "00618c625..0b8511641  main -> main"
    assert not gate._push_output_ok("To https://x/r.git\n" + long_ref)
    assert gate._push_output_ok("To https://x/r.git\n   00618c625..0b8511641  main -> main")


# ===================================================================
# Round 3 - GENERALISED, CREDIT-ONLY sub-agent evidence (coordinator scope
# add, 2026-10-08). Under SUBAGENT-FIRST deny the main thread cannot run
# pytest, gh, git or Edit, so every relayed result flagged. For EACH clearable
# check: claim + evidence only in a sub-agent -> cleared; claim + no evidence
# anywhere -> still flagged. Sub-agent evidence only ever REMOVES a main-only
# finding; it never adds one.
# ===================================================================

def _tool_pair(agent_id, tid, name, inp, output, is_error=None):
    """One sub-agent call of ANY tool and its result, in the measured shape."""
    return [_side(agent_id, "assistant",
                  [{"type": "tool_use", "id": tid, "name": name, "input": inp}]),
            _side(agent_id, "user", [_result(tid, output, is_error)])]


def _main_call(tid, command, output):
    """A MAIN-thread Bash call and its result (main rows pair by order)."""
    return [{"type": "assistant", "timestamp": "2026-10-08T22:00:00.000Z", "sessionId": SID,
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}},
            {"type": "user", "timestamp": "2026-10-08T22:00:01.000Z", "sessionId": SID,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": tid, "content": output}]}}]


def _gate_rows(tmp_path, main_rows, *agent_rows, arm=False):
    agents = {"a1b2c3": _agent("a1b2c3", *agent_rows)} if agent_rows else {}
    transcript = _session(tmp_path, main_rows, agents)
    return _run(tmp_path, transcript, arm=arm)


def _with_main_call(texts, command, output):
    rows = _main_rows(*texts)
    rows[1:1] = _main_call("toolu_main1", command, output)
    return rows


SUITE_CMD = "python -m pytest tests -q -p no:cacheprovider"
SUITE_537 = "........\n537 passed in 12.3s"
UNRELATED = ("toolu_01st", "git status -s", " M tools/x.py")


# --------------------------------------------- tests_pass_without_run (check 1)

def test_relayed_tests_pass_and_count_cleared_by_subagent_run(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass.", "537 passed."),
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    checks = _checks(report)
    assert "tests_pass_without_run" not in checks, report["findings"]
    assert "count_mismatch" not in checks, report["findings"]
    assert report["subagent_cleared"] == ["tests_pass_without_run"]


def test_tests_pass_with_no_run_anywhere_still_flags(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass.", "537 passed."),
                        _pair("a1b2c3", *UNRELATED))[1]
    assert "tests_pass_without_run" in _checks(report)


def test_subagent_run_without_a_passed_count_does_not_back_a_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass."),
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD,
                              "ERROR collecting tests/x.py\n1 error in 0.40s"))[1]
    assert "tests_pass_without_run" in _checks(report)


# ------------------------------------------------------- vacuous_run (check 8)

def test_vacuous_main_run_cleared_by_a_real_subagent_run(tmp_path):
    rows = _with_main_call(["The tests pass."], "python -m pytest -q", "no tests ran in 0.01s")
    report = _gate_rows(tmp_path, rows,
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    assert "vacuous_run" not in _checks(report), report["findings"]


def test_vacuous_main_run_with_vacuous_subagent_run_still_flags(tmp_path):
    rows = _with_main_call(["The tests pass."], "python -m pytest -q", "no tests ran in 0.01s")
    report = _gate_rows(tmp_path, rows,
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, "no tests ran in 0.02s"))[1]
    assert "vacuous_run" in _checks(report)


# ------------------------------------- full_suite_claim_over_filtered_run (7)

def test_full_suite_claim_cleared_by_an_unfiltered_subagent_run(tmp_path):
    rows = _with_main_call(["The full suite passes."],
                           "python -m pytest tests/test_x.py -q", "3 passed in 0.50s")
    report = _gate_rows(tmp_path, rows,
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    assert "full_suite_claim_over_filtered_run" not in _checks(report), report["findings"]


def test_full_suite_claim_with_only_filtered_runs_still_flags(tmp_path):
    rows = _with_main_call(["The full suite passes."],
                           "python -m pytest tests/test_x.py -q", "3 passed in 0.50s")
    report = _gate_rows(tmp_path, rows, _pair(
        "a1b2c3", "toolu_01py", "python -m pytest tests/test_y.py -q", "4 passed in 0.20s"))[1]
    assert "full_suite_claim_over_filtered_run" in _checks(report)


# ----------------------------------------------------- count_mismatch (check 2)

def test_count_mismatch_cleared_when_a_subagent_observed_the_count(tmp_path):
    rows = _with_main_call(["537 passed."], "python -m pytest tests/test_x.py -q",
                           "10 passed in 1.00s")
    report = _gate_rows(tmp_path, rows,
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    assert "count_mismatch" not in _checks(report), report["findings"]
    assert report["subagent_cleared"] == ["count_mismatch"]


def test_count_mismatch_with_a_different_subagent_count_still_flags(tmp_path):
    rows = _with_main_call(["537 passed."], "python -m pytest tests/test_x.py -q",
                           "10 passed in 1.00s")
    report = _gate_rows(tmp_path, rows, _pair(
        "a1b2c3", "toolu_01py", SUITE_CMD, "536 passed in 12.3s"))[1]
    assert "count_mismatch" in _checks(report)


def test_subagent_evidence_never_adds_a_finding(tmp_path):
    # Main ran nothing, so "540 passed" had nothing to contradict. The
    # sub-agent observed 537 - merged, that WOULD be a count_mismatch, but
    # sub-agent evidence is credit-only and may not add it.
    report = _gate_rows(tmp_path, _main_rows("All tests pass.", "540 passed."),
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    assert "count_mismatch" not in _checks(report), report["findings"]
    assert report["findings"] == []
    assert report["subagent_cleared"] == ["tests_pass_without_run"]


# --------------------------------------------- file_claim_without_edit (check 3)

WT_FILE = "E:/Example Repo/.claude/worktrees/agent-x/tools/foo_rm687.py"


@pytest.mark.parametrize("name,inp", [
    ("Edit", {"file_path": WT_FILE, "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": WT_FILE, "content": "x = 1\n"}),
    ("MultiEdit", {"file_path": WT_FILE, "edits": [{"old_string": "a", "new_string": "b"}]}),
])
def test_file_claim_cleared_by_a_successful_subagent_edit(tmp_path, name, inp):
    report = _gate_rows(tmp_path, _main_rows("I updated tools/foo_rm687.py."), _tool_pair(
        "a1b2c3", "toolu_01ed", name, inp, "The file has been updated successfully."))[1]
    assert "file_claim_without_edit" not in _checks(report), report["findings"]


def test_failed_subagent_edit_does_not_back_a_file_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("I updated tools/foo_rm687.py."), _tool_pair(
        "a1b2c3", "toolu_01ed", "Edit",
        {"file_path": WT_FILE, "old_string": "a", "new_string": "b"},
        "<tool_use_error>String to replace not found in file.</tool_use_error>",
        is_error=True))[1]
    assert "file_claim_without_edit" in _checks(report)


def test_file_claim_with_no_edit_anywhere_still_flags(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("I updated tools/foo_rm687.py."),
                        _pair("a1b2c3", *UNRELATED))[1]
    assert "file_claim_without_edit" in _checks(report)


# --------------------------------------------- ci_claim_without_probe (check 4)

GH_LIST = ('GH="C:/Program Files/GitHub CLI/gh.exe"; "$GH" run list --limit 3')


def test_ci_claim_cleared_by_a_subagent_ci_probe(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("CI is green."), _pair(
        "a1b2c3", "toolu_01ci", GH_LIST, "completed\tsuccess\tCI\tmain\tpush\t123"))[1]
    assert "ci_claim_without_probe" not in _checks(report), report["findings"]


def test_ci_claim_with_no_probe_anywhere_still_flags(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("CI is green."), _pair("a1b2c3", *UNRELATED))[1]
    assert "ci_claim_without_probe" in _checks(report)


def test_backgrounded_subagent_ci_probe_does_not_back_a_ci_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("CI is green."),
                        _bg_pair("a1b2c3", "toolu_01ci", GH_LIST, BG_LAUNCH))[1]
    assert "ci_claim_without_probe" in _checks(report)


# ------------------------------------------ commit_claim_without_commit (check 6)

def test_commit_claim_cleared_by_a_subagent_commit(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("I committed the fix."), _pair(
        "a1b2c3", "toolu_01c", 'git commit -F "C:/tmp/msg.txt"',
        "pre-commit: py_compile OK (2 file(s))\n"
        "[worktree-agent-x 35e6e2531] fix(gate): rm687\n 2 files changed"))[1]
    assert "commit_claim_without_commit" not in _checks(report), report["findings"]
    assert report["subagent_cleared"] == ["commit_claim_without_commit"]


def test_nothing_to_commit_does_not_back_a_commit_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("I committed the fix."), _pair(
        "a1b2c3", "toolu_01c", "git commit -am wip",
        "On branch main\nnothing to commit, working tree clean", is_error=True))[1]
    assert "commit_claim_without_commit" in _checks(report)


def test_merge_no_ff_made_by_backs_a_commit_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("I committed the fix."), _pair(
        "a1b2c3", "toolu_01m", "git merge --no-ff lane/x -m merge",
        "Merge made by the 'ort' strategy.\n tools/x.py | 2 +-"))[1]
    assert "commit_claim_without_commit" not in _checks(report), report["findings"]


# -------------------------------------------- merge_claim_without_merge (10)

def test_merge_claim_cleared_by_a_subagent_fast_forward(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01m", "git merge --ff-only worktree-agent-x",
        "Updating 00618c625..0b8511641\nFast-forward\n tools/x.py | 2 +-"))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


def test_conflicted_subagent_merge_does_not_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01m", "git merge lane/x",
        "Auto-merging tools/x.py\nCONFLICT (content): Merge conflict in tools/x.py\n"
        "Automatic merge failed; fix conflicts and then commit the result.",
        is_error=True))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_pr_merge_backs_a_merge_claim_unless_it_errored(tmp_path):
    ok = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01m", '"$GH" pr merge 12 --squash', "Merged pull request #12",
        is_error=False))[1]
    assert "merge_claim_without_merge" not in _checks(ok), ok["findings"]
    sub = tmp_path / "errored"
    sub.mkdir()
    bad = _gate_rows(sub, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01m", '"$GH" pr merge 12 --squash', "X Pull request is not mergeable",
        is_error=True))[1]
    assert "merge_claim_without_merge" in _checks(bad)


# s110 C9: the STAGED merge. Since kit v12 fleet_gitlock wraps only `git commit`
# / `git push`, so the sanctioned merge is `git merge --no-ff --no-commit` and
# then a gitlock-wrapped `git commit` whose commit is the merge commit. Measured
# twice in session 110: a true relayed merge claim flagged.
STAGE_CMD = 'cd "E:/Example Repo" && git merge --no-ff --no-commit worktree-agent-x'
STAGE_OUT = ("Auto-merging tools/x.py\n"
             "Automatic merge went well; stopped before committing as requested")
LOCKED_COMMIT_CMD = ('cd "E:/Example Repo" && python ops/fleet_kit/fleet_gitlock.py run '
                     '--owner 4befe5bd-0000-4000-8000-000000000c9.a1b2c3 -- '
                     'git commit -F "C:/tmp/merge_msg.txt"')
LOCKED_COMMIT_OUT = ("pre-commit: py_compile OK (1 file(s))\n"
                     "[main 35e6e2531] merge: worktree-agent-x (s110 c9)")
STAGE_CONFLICT_OUT = ("Auto-merging tools/x.py\n"
                      "CONFLICT (content): Merge conflict in tools/x.py\n"
                      "Automatic merge failed; fix conflicts and then commit the result.")
UNMERGED_COMMIT_OUT = ("error: Committing is not possible because you have unmerged files.\n"
                       "hint: Fix them up in the work tree, and then use 'git add/rm <file>'\n"
                       "fatal: Exiting because of an unresolved conflict.")


def test_staged_merge_then_gitlock_commit_backs_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01st", *UNRELATED[1:]),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]
    assert report["subagent_cleared"] == ["merge_claim_without_merge"]


def test_staged_merge_and_commit_in_one_call_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", STAGE_CMD + " && " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\n" + LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


def test_staged_merge_with_no_commit_does_not_back_a_merge_claim(tmp_path):
    # A staged-but-uncommitted merge is not a merge.
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01st", *UNRELATED[1:]))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("commit_out", [
    "GITLOCK: the command must be git commit or git push",
    "precommit_gate: BLOCKED - banned glyph in tools/x.py",
    "",
])
def test_staged_merge_with_a_failed_commit_does_not_back_a_merge_claim(tmp_path, commit_out):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, commit_out,
                              is_error=True))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", [
    'cd "E:/Example Repo" && git merge --abort',
    'cd "E:/Example Repo" && git merge --quit',
    'cd "E:/Example Repo" && git reset --hard HEAD',
])
def test_staged_merge_undone_before_the_commit_does_not_back_a_merge_claim(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_commit_before_the_staged_merge_does_not_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_one_call_commit_line_before_the_staged_line_does_not_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", LOCKED_COMMIT_CMD + " && " + STAGE_CMD,
        LOCKED_COMMIT_OUT + "\n" + STAGE_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_staged_merge_and_commit_in_different_subagents_do_not_pair(tmp_path):
    transcript = _session(tmp_path, _main_rows("Merged to main."), {
        "a1b2c3": _agent("a1b2c3", _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT)),
        "d4e5f6": _agent("d4e5f6", _pair("d4e5f6", "toolu_01cm",
                                         LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))})
    report = _run(tmp_path, transcript)[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_conflicted_no_commit_merge_does_not_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_CONFLICT_OUT,
                              is_error=True),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNMERGED_COMMIT_OUT,
                              is_error=True))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_conflicted_no_commit_merge_alone_does_not_back_a_merge_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_CONFLICT_OUT, is_error=True))[1]
    assert "merge_claim_without_merge" in _checks(report)


# RM-740 (f): more than `merge --abort` / `--quit` and `git reset` drop
# MERGE_HEAD. Measured 2026-10-15 on git 2.53.0.windows.3 in a scratch repo,
# after a clean `git merge --no-ff --no-commit` (the "stopped before committing"
# state), reading .git/MERGE_HEAD after each command: every BRANCH-mode `git
# checkout` drops it (with or without -f / --force, to the same branch, another
# branch, --detach, -b / -B / --orphan), and so does a `git stash` that saves the
# whole tree (bare, push or save, with no pathspec). A PATH-mode checkout, a
# pathspec stash, `stash list` / `create` / `show` / `pop`, `git switch` (fatal
# while merging) and `git restore` keep it.
UNRELATED_COMMIT_OUT = "[main 4c1d2e3f0] docs: unrelated fix"
REPO_CD = 'cd "E:/Example Repo" && '

# (command, git dropped MERGE_HEAD) - the measured table, gate reads it the same.
MERGE_HEAD_MEASURED = [
    ("git checkout -f", True), ("git checkout --force", True),
    ("git checkout -f HEAD", True), ("git checkout -f main", True),
    ("git checkout -qf", True), ("git checkout -fq", True),
    ("git checkout --force main", True), ("git checkout -f other", True),
    ("git checkout main", True), ("git checkout HEAD", True), ("git checkout other", True),
    ("git checkout --detach", True), ("git checkout -B newb", True),
    ("git checkout -b newb2", True), ("git checkout -m other", True),
    ("git checkout --orphan o", True), ("git checkout -q", True),
    ("git checkout --quiet", True),
    ("git -C repo checkout -f", True), ("git checkout -f 2>&1", True),
    ("git checkout -f main *>&1", True), ("git checkout -f *>&1", True),
    ("git stash *>&1", True), ("git stash *> out.txt", True),
    ("git checkout -f main 2>$null", True),
    ("git checkout -f -- a.txt", False), ("git checkout -f .", False),
    ("git checkout -- a.txt", False), ("git checkout .", False),
    ("git checkout --ours b.txt", False), ("git checkout --theirs b.txt", False),
    ("git checkout HEAD -- a.txt", False), ("git checkout feat -- b.txt", False),
    ("git checkout -f HEAD -- a.txt", False), ("git checkout --no-overlay -- a.txt", False),
    ("git stash", True), ("git stash push -m x", True), ("git stash save x", True),
    ("git stash -u", True), ("git stash -m y", True), ("git stash --staged", True),
    ("git stash -S", True), ("git stash -k", True), ("git stash --keep-index", True),
    ("git stash -q", True), ("git stash push", True),
    ("git stash push -m x -- a.txt", False), ("git stash push b.txt", False),
    ("git stash create", False), ("git stash list", False), ("git stash show", False),
    ("git switch -f other", False), ("git switch --discard-changes other", False),
    ("git switch other", False), ("git restore --staged .", False),
    ("git restore --staged --worktree .", False), ("git rm -q --cached b.txt", False),
    ("git reset --hard", True), ("git reset", True), ("git reset HEAD", True),
    ("git reset --merge", True), ("git reset -q", True), ("git reset --mixed", True),
    ("git merge --abort", True), ("git merge --quit", True),
    # RM-740 (f) known gaps, measured 2026-10-15 (s117), same git and method.
    # Gap 1: a bare TRAILING `--` ends the revisions, so it is branch mode and
    # drops MERGE_HEAD; only a pathspec AFTER `--` selects path mode.
    ("git checkout main --", True), ("git checkout -f --", True),
    ("git checkout HEAD --", True), ("git checkout --", True), ("git checkout feat --", True),
    ("git checkout main -- 2>&1", True),
    ('git checkout main -- "a.txt"', False), ("git checkout -- 'b.txt'", False),
    ("git stash push --", True), ("git stash --", True),
    ('git stash push -- "b.txt"', False),
    # Gap 3: `--soft` / `--keep` die while a merge is staged ("Cannot do a soft
    # reset in the middle of a merge"), and a pathspec reset keeps MERGE_HEAD
    # (the later commit has two parents) and never moves HEAD. A reset with
    # `--` and no pathspec, `-N` and an empty --pathspec-from-file are whole
    # resets and drop it.
    ("git reset --soft", False), ("git reset --soft HEAD", False), ("git reset --soft @", False),
    ("git reset --keep", False), ("git reset --keep HEAD", False),
    ("git reset --soft -q", False), ("git reset -q --keep", False),
    ("git reset -- b.txt", False), ("git reset HEAD b.txt", False),
    ("git reset HEAD -- b.txt", False), ("git reset -q -- b.txt", False),
    ("git reset -- .", False), ('git reset -q -- "b.txt"', False),
    ("git reset --", True), ("git reset HEAD --", True), ("git reset -N", True),
    ("git reset --pathspec-from-file=/dev/null", True), ("git reset -- 2>&1", True),
    # s117 verifier REFUTE of 463d166c8 (measured, same git and method): a
    # quoted or unexpanded word may be an option or a subcommand, so it must
    # never read as a path or a second argument; an option's VALUE is not a
    # path either; an unquoted `$F` after `--` can expand to nothing.
    ('git checkout "-b" newb', True), ('git checkout "-f" main', True),
    ('git checkout "--detach" HEAD', True), ('git checkout "main" "-f"', True),
    ('git stash "push"', True), ('git stash "save"', True),
    ('git reset "--hard" HEAD', True), ('git reset -q "--hard" HEAD', True),
    ('git reset "--merge" HEAD', True), ("git reset 'HEAD' \"--hard\"", True),
    ('git reset "--hard" HEAD~1', True), ("git reset $M HEAD", True),
    ("git reset --pathspec-from-file e.lst HEAD", True),
    ('git "reset" --hard', True), ('git stash push "-m" msg', True),
    ("git checkout --pathspec-from-file=/dev/null", True),
    ("git checkout --pathspec-from-file /dev/null", True),
    ("git checkout --conflict merge main", True), ("git checkout --conflict=merge main", True),
    ("git stash push -qm msg", True), ("git stash push -m msg b.txt", False),
    ("git stash save -- b.txt", True), ("git stash push -m -- b.txt", False),
    ("git stash push -m --", True), ("git stash -- b.txt", False),
    ("git checkout main -- $F", True),
    # An option VALUE that may expand to nothing shifts the next word into the
    # value slot (measured, M empty: `-m $M b.txt` makes b.txt the message).
    ("git stash push -m $M b.txt", True),
    # s117 verifier REFUTE of 6089352a3 (measured, bash and powershell.exe
    # 5.1): a pathspec word that expands to ZERO words leaves git a bare `--`
    # (or one argument), a whole reset / checkout / stash. Brace `{,}`, an
    # unquoted glob under nullglob, `${X:+...}` with X unset, and in PowerShell
    # 5.1 an empty `''` or `@()` (5.1 drops empty arguments) all drop it; so
    # does the same word BEFORE `--`, where it was a second argument.
    ('git reset -- ${X:+"a.txt"}', True), ("git reset -- {,}", True),
    ("git reset -- zz*", True), ("git reset -- ''", True), ("git reset -- @()", True),
    ('git checkout main -- ${X:+"a.txt"}', True), ("git checkout main -- {,}", True),
    ("git checkout main -- zz*", True), ("git checkout main -- ''", True),
    ("git checkout main -- @()", True),
    ('git stash push -- ${X:+"a.txt"}', True), ("git stash push -- {,}", True),
    ("git stash push -- zz*", True), ("git stash push -- ''", True),
    ("git stash push -- @()", True),
    ("git reset HEAD zz*", True), ("git reset HEAD {,}", True), ("git reset @() HEAD", True),
    ("git checkout main zz*", True), ("git checkout zz*", True), ("git stash push zz*", True),
    ("git reset -- 'b.txt'", False),
    # s117 verifier REFUTE of 37aea4ab5 (measured): a shell joins `\ ` into one
    # word (`git reset :/ma\in2` is one commit-search revision: a whole reset,
    # and with --hard HEAD moves), extglob `+(zz)` vanishes under nullglob, and
    # PowerShell 5.1 passes nothing for `(@())`. A token starting with `#` is a
    # comment, so `-- #a.txt` leaves a bare `--`.
    ("git reset :/ma\\in2", True), ("git reset --hard :/in\\it", True),
    ("git checkout :/fe\\at", True), ("git stash push -m my\\ msg", True),
    ("git reset -- +(zz)", True), ("git reset HEAD +(zz)", True),
    ("git checkout main -- +(zz)", True), ("git stash push -- +(zz)", True),
    ("git reset -- (@())", True), ("git checkout main -- (@())", True),
    ("git stash push -- (@())", True),
    ("git reset -- #a.txt", True), ("git reset -- a.txt #b.txt", False),
    # A wholly quoted allowlisted word is that word (measured KEPT, s117).
    ('git checkout "main" -- a.txt', False), ('git stash push -m msg "b.txt"', False),
    # s117 verifier REFUTE of 4766ed062 (measured): git takes a unique prefix
    # of a long option and the LAST mode wins, so `--soft --ha` is --hard;
    # `xargs git reset --soft` runs with --hard appended; a redirect does not
    # end git's arguments (`git reset --soft 2>&1 --hard` is --hard); `--orph`
    # is --orphan; `git stash branch` checks a branch out.
    ("git reset --soft --ha", True), ("git reset --soft --mix", True),
    ("git reset --soft HEAD --ha", True), ("git reset --keep HEAD --h", True),
    ("git reset --soft @ --mi", True), ("git reset --keep --mixe", True),
    ("echo --hard | xargs git reset --soft", True),
    ("git checkout --orph newb main", True),
    ("git reset --soft 2>&1 --hard", True), ("git reset --soft 2>/dev/null --hard", True),
    ("git reset --soft &>/dev/null --hard", True), ("git stash branch sb", True),
]

# Where the command line alone cannot tell git's two modes apart, the gate reads
# one of them on purpose, always STRICT (gate un-stages, git kept MERGE_HEAD):
# a single bare argument may be a branch or a path; `git reset --soft` /
# `--keep` to any commit but HEAD dies while the merge is staged but, run after
# the concluding commit, moves HEAD off the merge commit (test iii-reset-soft
# below); `reset -p` without a pathspec; a quoted or unexpanded word before
# `--` (it may be an option); a branch-only option before `--`; an option
# value that may expand to nothing (`-m $M`, `--conflict $S`). LENIENT (gate
# keeps, git dropped): none since s117 (`--pathspec-from-file` on checkout
# was, and is now measured above).
MERGE_HEAD_READ_ON_PURPOSE = [
    ("git checkout -f a.txt", True), ("git reset b.txt", True),
    ("git reset --soft HEAD~1", True), ("git reset --keep feat", True),
    ("git reset -p", True),
    ("git checkout -b -- a.txt", True), ('git reset "--hard" -- b.txt', True),
    ("git checkout --conflict $S main", True), ("git stash push -m $M -- b.txt", True),
    # "$@" / "${ARR[@]}" with nothing to expand: zero words in POSIX bash (a
    # whole reset, per the s117 verifier); the MSYS bash here passed one empty
    # word instead (git: "empty string is not a valid pathspec", kept). Strict.
    ('git reset -- "$@"', True), ('git reset -- "${ARR[@]}"', True),
    ('git checkout main -- "$@"', True), ('git checkout main -- "${ARR[@]}"', True),
    ('git stash push -- "$@"', True), ('git stash push -- "${ARR[@]}"', True),
    # An EMPTY quoted word: bash passes it (git: "empty string is not a valid
    # pathspec", kept, measured), PowerShell 5.1 drops it (measured with `''`:
    # a whole reset / checkout / stash). And `"$F"`: one word in bash, nothing
    # in PowerShell 5.1 when F is empty. Strict.
    ('git checkout main -- ""', True), ('git reset -- ""', True),
    ('git stash push -- ""', True), ('git reset -- "$F"', True),
    # Orchestrator ruling (s117, after three leaking denylist rounds): only an
    # ALLOWLISTED word ([A-Za-z0-9_./][A-Za-z0-9_./-]*, bare or quoted whole)
    # counts as a path or a rev; git keeps MERGE_HEAD in these, the gate drops.
    ('git reset -- "*.zz"', True), ("git reset HEAD~1 -- b.txt", True),
    # Orchestrator ruling (s117, final shape): a reset / checkout / stash keeps
    # credit only in an EXACT grammar with exact option spellings (see
    # _reset_keeps / _checkout_keeps / _stash_keeps). Git keeps MERGE_HEAD in
    # these (measured: fatal, path mode, or read-only), the gate drops.
    ("git reset --mixed -- b.txt", True), ("git reset --hard -- b.txt", True),
    ("git reset --soft -- b.txt", True), ("git reset --keep -- b.txt", True),
    ("git reset --keep --merg", True), ("git reset --soft --me", True),
    ("git reset --ha --soft", True), ("git stash pop", True), ("git stash b.txt", True),
    ('git checkout -- "$P" b.txt', True), ("git reset -- a.txt 2>&1", True),
]


# DECISION (orchestrator, s117, after the round-5 verifier refute of
# 6ca81b47c): `git reset` is deny-all again, as before (f) - every form
# un-stages, including the forms git measurably keeps MERGE_HEAD in (`--soft`,
# `--keep HEAD`, `-- a.txt`, `HEAD a.txt`). The tables above still record what
# git measurably DOES; the gate reads every reset as a drop on top of that.
# Alternatives: the exact grammars G1-G3 (five verification rounds, each
# leaked). Why: shell grammar is open-ended, and a false credit outranks a
# false flag. Reverses if: the gate gains a real shell parser (e.g. bashlex)
# with measured coverage, or an operator ruling.
RESET_CALL = re.compile(r"(?<![\w.-])git(?:\.exe)?\s+reset(?![\w.-])", re.I)


def _gate_reads_drop(command, drops):
    return drops or bool(RESET_CALL.search(command))


@pytest.mark.parametrize("command, drops", MERGE_HEAD_MEASURED + MERGE_HEAD_READ_ON_PURPOSE)
def test_merge_unstaged_matches_the_measured_merge_head_table(command, drops):
    assert bool(gate._merge_unstaged(command)) is _gate_reads_drop(command, drops), command


@pytest.mark.parametrize("command, drops", MERGE_HEAD_MEASURED + MERGE_HEAD_READ_ON_PURPOSE)
def test_the_staged_merge_step_reads_the_table_the_same(command, drops):
    # The step reads the command with each quoted literal as a word
    # (_step_command), not the raw text the table test above passes.
    slotted = gate._step_command(command)
    assert bool(gate._merge_unstaged(slotted)) is _gate_reads_drop(command, drops), slotted


def test_staged_merge_then_checkout_force_then_an_unrelated_commit_flags(tmp_path):
    # The RM-740 (f) acceptance sequence: `git checkout -f` dropped MERGE_HEAD,
    # so the later commit is an ordinary one and backs no merge claim.
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01co", REPO_CD + "git checkout -f", ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo, output", [
    ("git checkout --force main", "Already on 'main'"),
    ("git checkout main", "M\ttools/x.py\nAlready on 'main'"),
    ("git checkout lane/other", "M\ttools/x.py\nSwitched to branch 'lane/other'"),
    ("git stash", "Saved working directory and index state WIP on main: 0ecbe46 main"),
    ("git stash push -m park", "Saved working directory and index state On main: park"),
])
def test_branch_checkout_or_whole_tree_stash_unstages_the_merge(tmp_path, undo, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, output),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("keep, output, is_error", [
    ("git checkout HEAD -- tools/x.py", "", None),
    ('git checkout worktree-agent-x -- "tools/x.py"', "", None),
    ("git checkout .", "Updated 0 paths from the index", None),
    ("git checkout --theirs tools/x.py", "Updated 0 paths from the index", None),
    ("git switch -f other", 'fatal: cannot switch branch while merging\n'
                            'Consider "git merge --quit" or "git worktree add".', True),
    ("git stash list", "", None),
    ("git stash push -- tools/x.py", "No local changes to save", None),
    ("git restore --staged tools/x.py", "", None),
])
def test_path_checkout_or_pathspec_stash_keeps_the_staged_merge(tmp_path, keep, output, is_error):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01kp", REPO_CD + keep, output, is_error=is_error),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


@pytest.mark.parametrize("before", [
    "git checkout main", "git checkout -f main", "git stash",
])
def test_a_checkout_before_the_staged_merge_in_one_call_keeps_it(tmp_path, before):
    # The common merger shape `git checkout main && git merge --no-ff --no-commit`:
    # a checkout / stash BEFORE the merge in the same call clears nothing that
    # merge stages (and the pre-(f) gate credited it too).
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", REPO_CD + before + " && " + STAGE_CMD,
                              "Already on 'main'\n" + STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


def test_a_reset_anywhere_in_the_staging_call_still_unstages_it(tmp_path):
    # `git reset` / `merge --abort` keep the pre-(f) whole-call rule unchanged.
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg",
                              REPO_CD + "git reset --hard HEAD && " + STAGE_CMD,
                              "HEAD is now at 1a09d82 x\n" + STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# RM-740 (f) round 2 (verifier REFUTE, 2026-10-15): in ONE call, a success line
# that cannot be tied to a commit made before the drop must not credit the
# staged merge. The pre-(f) gate refused (i)-(iii) (a reset / abort anywhere in
# the call); the first (f) cut credited all three.
@pytest.mark.parametrize("command, output", [
    ("git commit -F m.txt; git merge --abort; git commit --allow-empty -m z",
     "precommit_gate: BLOCKED\n[main 4c1d2e3f0] z"),
    ("git commit -F m.txt || git reset --hard && git commit --allow-empty -m z",
     "precommit_gate: BLOCKED\nHEAD is now at 1a09d82 x\n[main 4c1d2e3f0] z"),
    ("git commit -m m; git reset --soft HEAD~1; git commit -m z",
     "[main 1111111] m\n[main 2222222] z"),
], ids=["i-abort", "ii-reset-hard", "iii-reset-soft"])
def test_one_call_reset_or_abort_between_commits_does_not_back_a_merge_claim(
        tmp_path, command, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cx", REPO_CD + command, output))[1]
    assert "merge_claim_without_merge" in _checks(report)


# Same shape with a checkout between the commits, and with the success line
# from another commit-creating command: the line cannot be attributed to a
# commit made before the drop, so no credit (the pre-(f) gate credited both).
@pytest.mark.parametrize("command, output", [
    ("git commit -F m.txt; git checkout -f; git commit --allow-empty -m z",
     "precommit_gate: BLOCKED\n[main 4c1d2e3f0] z"),
    ("git commit -F m.txt; git checkout -f; git cherry-pick 4c1d2e3f0",
     "precommit_gate: BLOCKED\n[main 5d2e3f4a1] z"),
], ids=["iv-checkout-commit", "checkout-cherry-pick"])
def test_one_call_checkout_between_commits_does_not_back_a_merge_claim(
        tmp_path, command, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cx", REPO_CD + command, output))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", [
    "git checkout -f main *>&1", "git checkout -f *>&1", "git stash *>&1",
])
def test_powershell_all_streams_redirect_does_not_hide_the_drop(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_checkout_between_staged_merge_and_commit_in_one_call_flags(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", STAGE_CMD + " && git checkout -f && " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\n" + UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_checkout_after_the_concluding_commit_in_one_call_keeps_the_credit(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cm",
                              LOCKED_COMMIT_CMD + " && git checkout lane/next",
                              LOCKED_COMMIT_OUT + "\nSwitched to branch 'lane/next'"))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


def test_a_drop_after_a_failed_commit_still_unstages(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cf", LOCKED_COMMIT_CMD + " ; git checkout -f",
                              "precommit_gate: BLOCKED - banned glyph in tools/x.py",
                              is_error=True),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# RM-740 (f) known gap 1 (s117): a bare trailing `--` is branch mode (measured:
# drops MERGE_HEAD). The gate read it as path mode because strip_command_noise
# blanks a quoted pathspec after `--`; the staged-merge step now reads a quoted
# literal as an argument, so `-- "<path>"` still keeps (path mode).
@pytest.mark.parametrize("undo, output", [
    ("git checkout main --", "M\ttools/x.py\nAlready on 'main'"),
    ("git checkout -f --", ""),
    ('git checkout "main" --', "M\ttools/x.py\nAlready on 'main'"),
    ("git stash push --", "Saved working directory and index state WIP on main: 0ecbe46 x"),
    ("git stash --", "Saved working directory and index state WIP on main: 0ecbe46 x"),
], ids=["checkout-main", "checkout-f", "checkout-quoted-main", "stash-push", "stash"])
def test_bare_trailing_double_dash_is_branch_mode_and_unstages(tmp_path, undo, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, output),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("sep", [" ; ", ";", " && ", " || ", " | ", "\n", " & "],
                         ids=["semi", "semi-tight", "and", "or", "pipe", "newline", "amp"])
@pytest.mark.parametrize("command, drops", [
    ("git checkout main --", True), ("git stash push --", True), ("git reset --", True),
    ("git reset HEAD --", True), ("git checkout main -- a.txt", False),
    ("git stash push -- a.txt", False), ("git reset -- a.txt", True),
    ("git reset --soft", True), ("git reset --keep HEAD", True),
])
def test_double_dash_and_reset_reading_ends_at_every_separator(command, drops, sep):
    # Sibling sweep (s117): the argument scan stops at each statement break,
    # so the next statement can neither supply nor hide a pathspec. Every
    # reset is a drop (deny-all decision above).
    assert bool(gate._merge_unstaged(command + sep + "git status -s")) is drops


def test_bare_trailing_double_dash_in_the_staging_call_unstages(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", STAGE_CMD + " && git checkout main -- && " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\nAlready on 'main'\n" + UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("keep", [
    'git checkout HEAD -- "tools/x.py"', "git checkout -- 'tools/x.py'",
    'git stash push -- "tools/x.py"', 'git stash push -m "park" -- "tools/x.py"',
])
def test_quoted_pathspec_after_double_dash_keeps_the_staged_merge(tmp_path, keep):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01kp", REPO_CD + keep, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


# RM-740 (f) known gap 2 (s117): the drop-before-merge exemption read the LAST
# merge in the call as the stager. A later merge that staged nothing - skipped
# by `||` or a failed `&&`, or already up to date (measured: `git checkout main;
# git merge --no-ff --no-commit <merged>` leaves MERGE_HEAD dropped and the
# next commit has ONE parent) - made a drop after the real staging merge read
# as before it.
LATER_MERGE_STAGED_NOTHING = [
    (STAGE_CMD + " ; git checkout main || git merge --no-ff --no-commit other ; "
     + LOCKED_COMMIT_CMD, STAGE_OUT + "\nAlready on 'main'\n" + UNRELATED_COMMIT_OUT),
    (STAGE_CMD + " ; git stash || git merge --no-ff --no-commit other ; " + LOCKED_COMMIT_CMD,
     STAGE_OUT + "\nSaved working directory and index state WIP on main: 0ecbe46 x\n"
     + UNRELATED_COMMIT_OUT),
    (STAGE_CMD + " ; git checkout main ; false && git merge --no-ff --no-commit other ; "
     + LOCKED_COMMIT_CMD, STAGE_OUT + "\nAlready on 'main'\n" + UNRELATED_COMMIT_OUT),
    (STAGE_CMD + " ; git checkout main ; git merge --no-ff --no-commit old ; "
     + LOCKED_COMMIT_CMD, STAGE_OUT + "\nAlready on 'main'\nAlready up to date.\n"
     + UNRELATED_COMMIT_OUT),
]
LATER_MERGE_IDS = ["or-skipped-checkout", "or-skipped-stash", "and-skipped", "up-to-date"]


@pytest.mark.parametrize("command, output", LATER_MERGE_STAGED_NOTHING[:3],
                         ids=LATER_MERGE_IDS[:3])
def test_a_drop_before_a_later_merge_that_staged_nothing_still_unstages(
        tmp_path, command, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mc", REPO_CD + command, output))[1]
    assert "merge_claim_without_merge" in _checks(report)


# The staged-merge step alone, so the up-to-date shape is pinned too: end to
# end, check 10 credits an "Already up to date." line on its own, by design
# (test_existing_merge_success_forms_still_back_a_merge_claim).
@pytest.mark.parametrize("command, output", LATER_MERGE_STAGED_NOTHING, ids=LATER_MERGE_IDS)
def test_staged_merge_step_reads_the_first_merge_when_one_staged_nothing(command, output):
    found = gate._new_subagent_evidence()
    gate._staged_merge_step(found, command, output)
    assert found["merge"] is False and found["staged_merge"] is False


def test_a_drop_between_two_merges_that_both_staged_keeps_the_later_stage(tmp_path):
    # Measured: `git stash; git merge --no-ff --no-commit <branch>` re-stages
    # (MERGE_HEAD back, the next commit has two parents), so a drop before the
    # LAST merge is still before the merge when every merge printed its line.
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc",
        REPO_CD + STAGE_CMD + " ; git stash ; " + STAGE_CMD + " ; " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\nSaved working directory and index state WIP on main: 0ecbe46 x\n"
        + STAGE_OUT + "\n" + LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


# RM-740 (f) known gap 3 (s117): every `git reset` form denies credit. Five
# rounds narrowed it to the forms measured to keep MERGE_HEAD; each round
# leaked, so it is deny-all again (decision record above): even the forms git
# keeps MERGE_HEAD in still un-stage the merge.
@pytest.mark.parametrize("keep, output, is_error", [
    ("git reset --soft", "fatal: Cannot do a soft reset in the middle of a merge.", True),
    ("git reset --keep HEAD", "fatal: Cannot do a keep reset in the middle of a merge.", True),
    ("git reset -q -- tools/x.py", "", None),
    ("git reset HEAD tools/x.py", "Unstaged changes after reset:\nM\ttools/x.py", None),
    ('git reset HEAD -- "tools/x.py"', "Unstaged changes after reset:\nM\ttools/x.py", None),
    ("git reset --soft @", "", None), ("git reset -q --soft HEAD", "", None),
    ("git reset --keep --quiet @", "", None), ("git reset tools/x.py tools/y.py", "", None),
    ("git reset -- 'tools/x.py'", "", None), ("git reset -- tools/x.py & git status -s", "", None),
], ids=["soft", "keep-head", "q-dashdash-path", "head-path", "head-dashdash-quoted",
        "soft-at", "q-soft-head", "keep-quiet-at", "two-paths", "dashdash-single-quoted",
        "dashdash-background"])
def test_every_reset_form_still_unstages_the_merge(tmp_path, keep, output, is_error):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01kp", REPO_CD + keep, output, is_error=is_error),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


def test_a_pathspec_reset_in_the_staging_call_still_unstages(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc",
        STAGE_CMD + " && git reset -q -- tools/x.py && " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\n" + LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# Round 7 (verifier refute of 0b89d2148): a `git""` merge hides from the
# slotted text, so this call's staged line was not seen there and a merge
# staged in an EARLIER call paired with a commit line printed BEFORE this
# call's staged line - a one-parent commit (real git) credited as the merge.
# The pre-(f) gate counts only commit lines after the staged line: deny.
@pytest.mark.parametrize("second, output", [
    ('git"" checkout main && git commit --allow-empty -m single && '
     'git"" merge --no-ff --no-commit feat',
     "Already on 'main'\n[main 1a2b3c4] single\nAuto-merging a.txt\n" + STAGE_OUT),
    ('git commit -m m && git"" merge --no-ff --no-commit feat2',
     "[main 1a2b3c4] m\nAuto-merging a.txt\n" + STAGE_OUT),
], ids=["checkout-single-commit", "commit-then-hidden-merge"])
def test_a_commit_before_a_hidden_staging_merge_never_credits(tmp_path, second, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", "git merge --no-ff --no-commit feat",
                              STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cx", REPO_CD + second, output))[1]
    assert "merge_claim_without_merge" in _checks(report)


# The conjunction, pinned (round 7, orchestrator ruling): the staged-merge
# credit is given only when the pre-(f) reading of the same evidence also
# credits it in the same call, so it can never exceed pre-(f) by construction.
def test_the_staged_merge_credit_needs_the_pre_f_reading(monkeypatch):
    def credit(pre_f_says):
        if pre_f_says is not None:
            monkeypatch.setattr(gate, "_pre_f_staged_step", lambda *args: pre_f_says)
        found = gate._new_subagent_evidence()
        gate._staged_merge_step(found, STAGE_CMD, STAGE_OUT)
        gate._staged_merge_step(found, LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT)
        return found["merge"]
    assert credit(None) is True
    assert credit(False) is False


# An independent oracle: the pre-(f) staged-merge step as it stood at
# 1a1fa703d (copied, not imported), over seeded cross-call sequences with the
# quoted-git shapes. The gate may credit LESS, never more.
def _pre_f_oracle(calls):
    reset = re.compile(gate._GIT_LEAD + r"reset(?![\w.-])", re.I)
    found = {"merge": False, "staged": False}
    for command, output in calls:
        blank = gate.strip_command_noise(command)
        if reset.search(blank) or any(gate._MERGE_NO_OP.search(m.group(1))
                                      for m in gate._EV_GIT_MERGE.finditer(blank)):
            found["staged"] = False
            continue
        lines = gate._output_lines(output)
        staged_at = -1
        if gate._did_merge(blank) and not gate._MERGE_BAD.search(output):
            staged_at = next((i for i, line in enumerate(lines)
                              if line is not None and gate._MERGE_STAGED.match(line)), -1)
            if staged_at >= 0:
                found["staged"] = True
        if not found["staged"] or not gate.EV_COMMIT.search(blank):
            continue
        if any(line is not None and gate._COMMIT_LINE.match(line) for line in lines[staged_at + 1:]):
            found["merge"] = True
            found["staged"] = False
    return found["merge"]


def test_the_staged_merge_credit_never_exceeds_the_pre_f_oracle():
    import random
    rng = random.Random(117)
    gits = ["git", 'git""', '"git"', "g''it", 'git -C "x"', 'git -C"$R"', 'git --git-dir="x"',
            "git --git-dir=x", "git ''", "env git", "git.exe"]
    def one():
        g, k = rng.choice(gits), rng.random()
        if k < 0.3:
            return g + " merge --no-ff --no-commit " + rng.choice(["feat", '"feat"']), STAGE_OUT
        if k < 0.55:
            return g + " commit " + rng.choice(["-m m", '-m "x y"', "--allow-empty -m s"]), (
                "[main 1a2b3c4] m")
        if k < 0.65:
            return g + " checkout " + rng.choice(["main", "-- a.txt", '"main"']), "Already on 'main'"
        if k < 0.72:
            return g + " stash " + rng.choice(["", "push -- a.txt", "list"]), "Saved"
        if k < 0.80:
            return g + " reset " + rng.choice(["--soft HEAD", "--hard", '"--hard"']), ""
        if k < 0.85:
            return g + " merge " + rng.choice(["--abort", '"--abort"']), ""
        return "echo " + rng.choice(['"' + STAGE_OUT.splitlines()[-1] + '"', "x"]), ""
    seps = [" && ", " || ", "; ", "\n", " \\\n", " | "]
    wider = []
    for _ in range(3000):
        calls = []
        for _c in range(rng.randint(1, 4)):
            parts = [one() for _p in range(rng.randint(1, 3))]
            text = parts[0][0]
            for part in parts[1:]:
                text += rng.choice(seps) + part[0]
            calls.append((text, "\n".join(p[1] for p in parts if p[1])))
        found = gate._new_subagent_evidence()
        for command, output in calls:
            gate._staged_merge_step(found, command, output)
        if found["merge"] and not _pre_f_oracle(calls):
            wider.append(calls)
    assert not wider, wider[:3]


# Round 6: credit is never wider than the pre-(f) reading (quoted literals
# blanked). There `--git-dir="x"` breaks the merge match, so the slotted text
# alone must not stage a merge the pre-(f) gate never saw.
def test_a_merge_only_the_slotted_text_sees_does_not_stage(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg",
                              REPO_CD + 'git --git-dir="x" merge --no-ff --no-commit lane',
                              STAGE_OUT),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# Round-5 refute: a reset the slotted text cannot see must still deny, as in
# the pre-(f) reading (a quoted literal glued to `git` or to an option).
@pytest.mark.parametrize("undo", [
    'git"" reset --hard', "git'' reset --hard", 'git --git-dir"=$D" reset --hard',
    'git -C"$R" reset --hard', 'git"" merge --abort',
])
def test_a_reset_hidden_from_the_slotted_text_still_unstages(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", [
    "git reset --", "git reset HEAD --", "git reset tools/x.py", "git reset -N",
    "git reset --soft HEAD~1", "git reset --keep origin/main", "git reset --hard",
    'git reset "HEAD"', "git reset --pathspec-from-file=nul",
])
def test_reset_forms_that_drop_merge_head_or_move_head_still_unstage(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# s117 verifier REFUTE of 463d166c8: reading a quoted literal as a word made a
# quoted option or subcommand count as a path / second argument, so each of
# these (git drops MERGE_HEAD in every one, measured) credited a merge the
# parent gate refused. The last five are the same class, pre-existing on the
# parent too: an unresolved subcommand, a quoted `-m`, an option's value read
# as a path, and an unquoted variable after `--` that expands to nothing.
QUOTED_TOKEN_DROPS = [
    'git checkout "-b" newb', 'git checkout "-f" main', 'git checkout "--detach" HEAD',
    'git checkout "main" "-f"', 'git stash "push"', 'git stash "save"',
    'git reset "--hard" HEAD', 'git reset -q "--hard" HEAD', 'git reset "--merge" HEAD',
    "git reset 'HEAD' \"--hard\"", 'git reset "--hard" HEAD~1',
    ": > e.lst; git reset --pathspec-from-file e.lst HEAD", "M=--hard; git reset $M HEAD",
    'git "reset" --hard', 'git stash push "-m" msg', "git checkout --conflict merge main",
    "git stash push -qm msg", "F=; git checkout main -- $F",
    "git stash save -- tools/x.py", "git checkout --pathspec-from-file /dev/null",
    "M=; git stash push -m $M tools/x.py",
]

# s117 verifier REFUTE of 6089352a3: a pathspec that expands to zero words.
# The reset forms are new false credits of 6089352a3 (the pre-(f) gate denied
# every reset); the checkout / stash twins and the before-`--` forms were
# credited by the parent too. Each must deny the merge credit.
VANISHING_PATHSPEC_DROPS = [
    'set --; git reset -- "$@"', 'git reset -- "${ARR[@]}"', 'git reset -- ${X:+"a.txt"}',
    "git reset -- {,}", "shopt -s nullglob; git reset -- zz*", "git reset -- ''",
    "git reset -- @()",
    'set --; git checkout main -- "$@"', 'git checkout main -- "${ARR[@]}"',
    'git checkout main -- ${X:+"a.txt"}', "git checkout main -- {,}",
    "shopt -s nullglob; git checkout main -- zz*", "git checkout main -- ''",
    "git checkout main -- @()",
    'set --; git stash push -- "$@"', 'git stash push -- "${ARR[@]}"',
    'git stash push -- ${X:+"a.txt"}', "git stash push -- {,}",
    "shopt -s nullglob; git stash push -- zz*", "git stash push -- ''",
    "git stash push -- @()",
    "shopt -s nullglob; git reset HEAD zz*", "git reset HEAD {,}", "git reset @() HEAD",
    "shopt -s nullglob; git checkout main zz*", "shopt -s nullglob; git checkout zz*",
    "shopt -s nullglob; git stash push zz*",
    # s117 verifier REFUTE of 37aea4ab5 (each denied by the pre-(f) gate):
    "git reset :/base\\ two", "git reset --hard :/base\\ two",
    "shopt -s extglob nullglob\ngit reset -- +(zz)",
    "shopt -s extglob nullglob\ngit reset HEAD +(zz)", "git reset -- (@())",
    "git checkout :/base\\ two", "git stash push -m my\\ msg",
    "shopt -s extglob nullglob\ngit checkout main -- +(zz)",
    "shopt -s extglob nullglob\ngit stash push -- +(zz)",
    "git checkout main -- (@())", "git stash push -- (@())", "git reset -- #a.txt",
]


# Orchestrator ruling (s117): an ALLOWLIST, not a denylist. A word counts as a
# path, or as a rev in reset path mode, only when it is bare and matches
# [A-Za-z0-9_./][A-Za-z0-9_./-]* or is wholly single- / double-quoted with such
# an inside. Property: put any word outside it in any keep form's word slot and
# the gate must read a drop (raw text and the step's _step_command text). A
# `#x` token is a comment, not a word (it ends the arguments: `git reset --soft
# #x` IS `git reset --soft`), so it is pinned by the table rows instead.
NON_ALLOWLISTED_WORDS = [
    ":/base\\", "+(zz)", "(@())", "~", "~/x", "a@b", "HEAD~1", "x^", "!x", "$X", "%X%",
    "`x`", "*.py", "{a,b}", "{,}", "a?b", "[ab]", '""', "''", '"a b"', "'x y'", "'$x'",
    '"-b"', "-", "a\\", "@()", '"${A[@]}"', "'a'\"b\"$c", "a=b", "a,b", "a>b",
    '"*.zz"', "a:b", "a+b", "(x)", "!", "a%b",
]
KEEP_FORM_TEMPLATES = [
    "git reset -- {w}", "git reset -q -- {w}", "git reset HEAD {w}", "git reset HEAD -- {w}",
    "git reset {w} -- a.txt", "git reset {w} a.txt", "git reset --soft {w}",
    "git reset --keep {w}", "git checkout main -- {w}", "git checkout HEAD -- {w}",
    "git checkout {w} -- a.txt", "git checkout main {w}", "git checkout {w}",
    "git stash push -- {w}", "git stash push {w}", "git stash {w} -- a.txt",
    "git stash push -m {w} -- a.txt",
]


@pytest.mark.parametrize("word", NON_ALLOWLISTED_WORDS)
def test_a_word_outside_the_allowlist_never_keeps_the_staged_merge(word):
    kept = []
    for template in KEEP_FORM_TEMPLATES:
        if word == "-" and "-m {w}" in template:
            continue  # `-m -` is a one-word message: a true keep
        command = template.format(w=word)
        for text in (command, gate._step_command(command)):
            if not gate._merge_unstaged(text):
                kept.append(text)
    assert not kept, kept


@pytest.mark.parametrize("keep", [
    "git checkout main -- tools/x.py", "git stash push -- tools/x.py",
    "git checkout main -- 'tools/x.py'", "git checkout -q -- \"tools/x.py\"",
    "git checkout -f HEAD -- tools/x.py", "git checkout --theirs tools/x.py",
    "git stash push -q -m park -- tools/x.py", "git stash -- tools/x.py",
    "git stash list", "git checkout main -- tools/x.py & git status -s",
])
def test_the_allowlisted_keep_forms_stay_credited(tmp_path, keep):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01kp", REPO_CD + keep, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, LOCKED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


# Orchestrator ruling (s117, final shape): a `git reset` keeps credit ONLY in
# G1 `git reset [-q|--quiet] (--soft|--keep) [HEAD|@]`, G2 `git reset
# [-q|--quiet] [HEAD|<allowlisted rev>] -- <allowlisted path>...` or G3 `git
# reset [-q|--quiet] <allowlisted> <allowlisted>...`, with EXACT option
# spellings. Measured: git takes any unique prefix of a long option and the
# last mode wins (`--soft --ha` is --hard; --h/--ha/--har, --mi/--mix/--mixe
# and --me/--mer/--merg are unique, --m is ambiguous).
RESET_OTHER_SPELLINGS = [
    "--h", "--ha", "--har", "--hard", "--mi", "--mix", "--mixe", "--mixed", "--me", "--mer",
    "--merg", "--merge", "--so", "--sof", "--ke", "--kee", "--qu", "--quie", "-qq", "-N",
    "--no-refresh", "--refresh", "-p", "--patch", "--recurse-submodules", "-U3",
    "--pathspec-from-file=nul", "--intent-to-add",
]
RESET_KEEP_FORMS = [
    "--soft", "--keep", "--soft HEAD", "--keep HEAD", "--soft @", "--keep @", "-q --soft",
    "--quiet --keep HEAD", "-- a.txt", "-q -- a.txt", "HEAD -- a.txt", "HEAD a.txt",
    "a.txt b.txt",
]


@pytest.mark.parametrize("spelling", RESET_OTHER_SPELLINGS)
def test_any_other_reset_option_spelling_denies_every_keep_form(spelling):
    kept = []
    for keep in RESET_KEEP_FORMS:
        for command in (f"git reset {keep} {spelling}", f"git reset {spelling} {keep}"):
            for text in (command, gate._step_command(command)):
                if not gate._merge_unstaged(text):
                    kept.append(text)
    assert not kept, kept


# The same exact-option rule for the checkout and stash keep forms.
CHECKOUT_OTHER_SPELLINGS = [
    "--orph", "--orp", "--orphan", "--det", "--detach", "-b", "-B", "-m", "--merge", "-t",
    "--track", "--guess", "--conflict=merge", "-l", "--ignore-other-worktrees", "-U3",
    "--recurse-submodules", "--our", "--their", "--pat", "-qf", "--progress",
]
CHECKOUT_KEEP_FORMS = ["main -- a.txt", "-- a.txt", "main a.txt", ".", "--theirs a.txt"]
STASH_OTHER_SPELLINGS = [
    "-k", "--keep-index", "-u", "--include-untracked", "-a", "--all", "-S", "--staged",
    "-p", "--patch", "--me", "--mess", "--message=x", "-mx", "-qm", "--pathspec-from-file=f",
    "--quie",
]
STASH_KEEP_FORMS = ["push -- a.txt", "push a.txt", "push -m x -- a.txt", "-- a.txt"]


@pytest.mark.parametrize("spelling", CHECKOUT_OTHER_SPELLINGS + STASH_OTHER_SPELLINGS)
def test_any_other_checkout_or_stash_option_spelling_denies_the_keep_forms(spelling):
    commands = []
    if spelling in CHECKOUT_OTHER_SPELLINGS:
        commands += [f"git checkout {spelling} {keep}" for keep in CHECKOUT_KEEP_FORMS]
    if spelling in STASH_OTHER_SPELLINGS:
        commands += ["git stash " + keep.replace("push", "push " + spelling, 1)
                     if keep.startswith("push") else f"git stash {spelling} {keep}"
                     for keep in STASH_KEEP_FORMS]
    kept = [text for command in commands
            for text in (command, gate._step_command(command)) if not gate._merge_unstaged(text)]
    assert not kept, kept


# The `git` word must head a simple command (only a separator or the start of
# the line before it, no global option): as an argument to xargs / env / time
# / nohup / command / sh -c, or inside a quoted string or heredoc that a shell
# runs, git's real argv is not the one on the line.
NOT_AT_COMMAND_HEAD = [
    "echo --hard | xargs git reset --soft", "env git reset --soft", "nohup git reset --soft HEAD",
    "time git reset --keep", "command git reset --soft", "sh -c git reset --soft",
    "timeout 60 git reset -- tools/x.py", "X=1 git reset --soft", "(git reset --soft)",
    "{ git reset --soft; }", "! git reset --soft", "git -C . reset --soft",
    "git -c x.y=z reset --soft", "git --no-pager reset -- tools/x.py",
    "bash -c 'git reset --hard'", 'sh -c "git checkout main"',
    "bash <<'EOF'\ngit reset --hard\nEOF", "xargs git checkout -- tools/x.py",
    "env git stash push -- tools/x.py",
    # A shell function or alias named git makes the line's argv a lie, too.
    "g=git; git() { $g reset --hard; }; git reset --soft",
    "function git { & $g reset --hard }; git reset --soft",
    "shopt -s expand_aliases; alias git='git reset --hard; git'; git reset --soft",
    "Set-Alias git Reset-Thing; git reset --soft", "New-Alias -Name git x; git reset --soft",
]


@pytest.mark.parametrize("undo", NOT_AT_COMMAND_HEAD)
def test_git_not_at_command_head_never_keeps_the_staged_merge(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


# Round-5 refute of 6ca81b47c: a backslash-newline (bash) or backtick-newline
# (PowerShell) CONTINUES the line, so the `git` after it is an argument of the
# wrapper before it, not a command head. Measured (bash script files and
# powershell.exe 5.1): each of these drops MERGE_HEAD.
LINE_CONTINUATION_DROPS = [
    'f(){ "$1" "$2" main; }; f \\\ngit checkout -- tools/x.py',
    'f(){ "$1" "$2"; }; f \\\ngit stash push -- tools/x.py',
    "echo -b x | xargs \\\ngit checkout main",
    "function f { & $args[0] $args[1] main }; f `\ngit checkout -- tools/x.py",
    "function f { & $args[0] $args[1] }; f `\ngit stash push -- tools/x.py",
    'f(){ "$1" "$2" main; }; f \\\r\ngit checkout -- tools/x.py',
    "echo --hard | xargs \\\ngit reset --soft",
    'f(){ "$@" --hard; }; f \\\ngit reset --soft',
    "function f { & $args[0] $args[1] $args[2] --hard }; f `\ngit reset --soft",
]


@pytest.mark.parametrize("undo", LINE_CONTINUATION_DROPS)
def test_git_after_a_line_continuation_is_not_a_command_head(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", LINE_CONTINUATION_DROPS)
def test_a_line_continuation_reads_as_a_drop_in_raw_and_step_text(undo):
    assert gate._merge_unstaged(undo) and gate._merge_unstaged(gate._step_command(undo))


def test_a_plain_newline_still_starts_a_command():
    # A newline WITHOUT a continuation character is a separator, as before.
    command = "echo done\ngit checkout main -- tools/x.py"
    assert not gate._merge_unstaged(command)
    assert not gate._merge_unstaged(gate._step_command(command))


@pytest.mark.parametrize("undo", [
    "git reset --soft --ha", "git reset --keep HEAD --h", "git reset --soft @ --mi",
    "git reset --soft 2>&1 --hard", "git reset --soft &>/dev/null --hard",
    "git checkout --orph newb main", "git stash branch sb",
])
def test_abbreviated_or_redirected_reset_forms_unstage(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", VANISHING_PATHSPEC_DROPS)
def test_a_pathspec_that_may_expand_to_nothing_never_keeps_the_merge(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", VANISHING_PATHSPEC_DROPS)
def test_a_pathspec_that_may_expand_to_nothing_in_the_staging_call_unstages(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", STAGE_CMD + " ; " + undo + " ; " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\n" + UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", QUOTED_TOKEN_DROPS)
def test_a_quoted_or_unresolved_token_never_reads_as_a_path(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01mg", STAGE_CMD, STAGE_OUT),
                        _pair("a1b2c3", "toolu_01un", REPO_CD + undo, ""),
                        _pair("a1b2c3", "toolu_01cm", LOCKED_COMMIT_CMD, UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("undo", QUOTED_TOKEN_DROPS)
def test_a_quoted_or_unresolved_token_in_the_staging_call_unstages(tmp_path, undo):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."), _pair(
        "a1b2c3", "toolu_01mc", STAGE_CMD + " ; " + undo + " ; " + LOCKED_COMMIT_CMD,
        STAGE_OUT + "\n" + UNRELATED_COMMIT_OUT))[1]
    assert "merge_claim_without_merge" in _checks(report)


@pytest.mark.parametrize("command, output", [
    ("git merge --ff-only worktree-agent-x",
     "Updating 00618c625..0b8511641\nFast-forward\n tools/x.py | 2 +-"),
    ("git merge --no-ff worktree-agent-x -m merge",
     "Merge made by the 'ort' strategy.\n tools/x.py | 2 +-"),
    ("git merge worktree-agent-x", "Already up to date."),
])
def test_existing_merge_success_forms_still_back_a_merge_claim(tmp_path, command, output):
    report = _gate_rows(tmp_path, _main_rows("Merged to main."),
                        _pair("a1b2c3", "toolu_01m", command, output))[1]
    assert "merge_claim_without_merge" not in _checks(report), report["findings"]


# ------------------------------------------- deferred background test runs

def test_backgrounded_subagent_pytest_read_later_backs_a_tests_claim(tmp_path):
    launch = _bg_pair("a1b2c3", "toolu_01bg", SUITE_CMD, BG_LAUNCH)
    read = _pair("a1b2c3", "toolu_01rd", "tail -3 C:/x/b1x.output",
                 "........\n537 passed in 12.3s")
    report = _gate_rows(tmp_path, _main_rows("All tests pass.", "537 passed."),
                        launch, read)[1]
    checks = _checks(report)
    assert "tests_pass_without_run" not in checks, report["findings"]
    assert "count_mismatch" not in checks, report["findings"]


def test_backgrounded_subagent_pytest_never_read_does_not_back_a_claim(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass."),
                        _bg_pair("a1b2c3", "toolu_01bg", SUITE_CMD, BG_LAUNCH))[1]
    assert "tests_pass_without_run" in _checks(report)


# --------------------------------------------- subagent_hook_bypass (advisory)

def test_subagent_no_verify_is_an_advisory_finding_that_never_blocks(tmp_path):
    out = "To https://github.com/owner/repo.git\n   00618c625..0b8511641  main -> main"
    proc, report = _gate_rows(tmp_path, _main_rows(PUSH_CLAIM), _pair(
        "a1b2c3", "toolu_01p", "git push --no-verify origin main", out), arm=True)
    checks = _checks(report)
    assert "subagent_hook_bypass" in checks
    assert "hook_bypass" not in checks          # check 5 stays main-bash-only
    assert "push_claim_without_push" not in checks
    assert report["blocked"] is False
    assert proc.stdout == ""                    # no Stop feedback emitted


def test_subagent_bypass_is_not_loaded_without_a_clearable_finding(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("Nothing to report."), _pair(
        "a1b2c3", "toolu_01p", "git commit --no-verify -m x", "[main abc1234] x"))[1]
    assert report["findings"] == []
    assert not [key for key in report if key.startswith("subagent_")], report


# --------------------------------------------------------- budget and API

def test_total_bytes_budget_reads_newest_first(tmp_path, monkeypatch):
    transcript = _session(tmp_path, _main_rows(PUSH_CLAIM))
    sub = tmp_path / SID / "subagents"
    old = sub / "agent-old01.jsonl"
    new = sub / "agent-new01.jsonl"
    _write_jsonl(old, _agent("old01", _pair("old01", "t1", PUSH_CMD, PUSH_OUT)))
    _write_jsonl(new, _agent("new01", _pair("new01", "t2", "git status -s", "")))
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_800_000_000, 1_800_000_000))
    monkeypatch.setattr(gate, "SUBAGENT_TOTAL_MAX", new.stat().st_size + 1)
    assert gate.subagent_push_evidence(str(transcript)) is None
    monkeypatch.setattr(gate, "SUBAGENT_TOTAL_MAX", 256 * 1024 * 1024)
    assert gate.subagent_push_evidence(str(transcript)) == {"kind": "push", "agent": "old01"}
    assert gate.SUBAGENT_FILE_MAX == 64 * 1024 * 1024


# ---------------------------- round 3b: re-verifier refutation of 35e6e2531
# Four HONEST-output cases (not forgery) that were credited, plus a quadratic
# command regex.

ANC = "git merge-base --is-ancestor abc1234 origin/main"


@pytest.mark.parametrize("command,output", [
    (ANC + "; echo $?; git status --porcelain | wc -l", "1\n0"),
    (ANC + "; echo $?; git rev-list --count abc1234..HEAD", "1\n0"),
    (ANC + "; echo $?", "0"),                       # bare: never credits
    (ANC + '; echo "=$?"', "=0"),                   # prefix without a letter
    (ANC + "; Write-Output $LASTEXITCODE", "0"),
])
def test_status_echo_needs_a_lettered_prefix(tmp_path, command, output):
    assert gate._pair_credit(command, output, False, None) is None, command
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01anc", command, output,
                                                  is_error=False))
    assert "push_claim_without_push" in _checks(report), command


def test_lettered_status_echo_still_credits():
    assert gate._pair_credit(ANC + '; echo "rc=$?"', "rc=0", False, None) == "ancestry"
    assert gate._pair_credit(ANC + '; Write-Output "rc=$LASTEXITCODE"', "rc=0",
                             False, None) == "ancestry"


def test_any_dry_run_push_in_the_call_voids_push_credit(tmp_path):
    command = "git push -n backup main 2>&1; git push origin main 2>&1"
    output = ("To https://b.example/r\n   1111111..2222222  main -> main\n"
              "To https://github.com/owner/repo.git\n"
              " ! [rejected]        main -> main (fetch first)\n"
              "error: failed to push some refs to https://github.com/owner/repo.git")
    assert gate._pair_credit(command, output, True, None) is None
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01p", command, output))
    assert "push_claim_without_push" in _checks(report)


@pytest.mark.parametrize("command,dst", [
    ("git push upstream main 2>&1 | head -2; git fetch upstream 2>&1 | tail -1",
     "upstream/main"),
    ("git push upstream main 2>&1 | head -2; git pull upstream main 2>&1 | tail -1",
     "upstream/main"),
    ("git push backup main 2>&1 | head -2; git fetch --all 2>&1 | tail -1", "backup/main"),
    ("git push backup main 2>&1 | head -2; git remote update 2>&1 | tail -1", "backup/main"),
    ("git push mirror main 2>&1 | head -2; git fetch --prune mirror 2>&1 | tail -1",
     "mirror/main"),
])
def test_fetch_from_any_parsed_remote_never_credits(tmp_path, command, dst):
    output = ("To https://github.com/owner/repo.git\n"
              " ! [rejected]        main -> main (fetch first)\n"
              "   1111111..2222222  main       -> " + dst)
    assert gate._pair_credit(command, output, False, None) is None, command
    report = _gate_on(tmp_path, PUSH_CLAIM, _pair("a1b2c3", "toolu_01p", command, output))
    assert "push_claim_without_push" in _checks(report), command


def test_honest_push_beside_a_fetch_of_another_remote_still_credits():
    command = "git fetch upstream; git push origin main 2>&1"
    output = ("From https://github.com/up/repo\n   aaaaaaa..bbbbbbb  main -> upstream/main\n"
              "To https://github.com/owner/repo.git\n   1111111..2222222  main -> main")
    assert gate._pair_credit(command, output, False, None) == "push"


_CMD_PERF_SCRIPT = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
anc = "git merge-base --is-ancestor abc1234 origin/main"
cmds = [anc + " " * 100000 + "x", anc + "\t " * 50000 + "; echo x",
        "git push origin main" + " " * 100000 + "x",
        # just under COMMAND_PARSE_MAX, so the tail walker itself runs:
        anc + " " * 19900 + "x", anc + " \t" * 9900 + "; echo x"]
began = time.perf_counter()
credits = [gate._pair_credit(c, "", False, None) for c in cmds]
print(json.dumps({"elapsed": time.perf_counter() - began, "credits": credits}))
"""


def test_100k_spaces_in_a_command_is_fast():
    try:
        proc = subprocess.run([sys.executable, "-c", _CMD_PERF_SCRIPT, str(ROOT)],
                              capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        pytest.fail("100k spaces in a command took over 60s (quadratic command regex)")
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["elapsed"] < 1.0, result
    assert result["credits"] == [None] * 5


def test_overlong_command_is_not_parsed_for_ancestry():
    padded = ANC + " && echo yes" + " " * 20001
    assert gate._pair_credit(padded, "yes", False, None) is None
    assert gate._pair_credit(ANC + " && echo yes", "yes", False, None) == "ancestry"


# ---------------------------- round 4: re-verifier refutation of 5d76475b3

OOM = ("INTERNALERROR> Traceback (most recent call last):\nINTERNALERROR> MemoryError\n"
       "==== 3 passed, 22 failed in 301.10s ====")
XDIST = ("INTERNALERROR> Traceback (most recent call last):\n"
         "INTERNALERROR> RuntimeError: Unexpectedly no active workers available\n"
         "==== 1200 passed in 301.10s ====")


@pytest.mark.parametrize("output", [OOM, XDIST, "1 passed\nno tests ran in 0.01s"])
def test_vacuous_subagent_run_never_credits(tmp_path, output):
    # The same output in the MAIN thread scores vacuous_run (RM-490); from a
    # sub-agent it must not clear tests_pass_without_run.
    report = _gate_rows(tmp_path, _main_rows("Tests pass."), _pair(
        "a1b2c3", "toolu_01py", "python -m pytest tests -q -n 8", output))[1]
    assert "tests_pass_without_run" in _checks(report), output
    assert report["subagent_cleared"] == []


def test_filtered_subagent_run_replaces_with_the_narrower_full_suite_flag(tmp_path):
    # Main ran nothing; the sub-agent ran only `-k x`. tests_pass_without_run
    # is cleared, but the SAME sentence now carries the narrower flag.
    report = _gate_rows(tmp_path, _main_rows("The full suite passes."), _pair(
        "a1b2c3", "toolu_01py", "python -m pytest tests -q -k x", "5 passed in 0.20s"))[1]
    checks = _checks(report)
    assert "full_suite_claim_over_filtered_run" in checks, report["findings"]
    assert "tests_pass_without_run" not in checks
    assert report["subagent_cleared"] == ["tests_pass_without_run"]


def test_count_on_an_already_flagged_sentence_is_replaced_not_dropped(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass: 540 passed."),
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    found = [f for f in report["findings"] if f["check"] == "count_mismatch"]
    assert found and found[0]["claimed"] == "540", report["findings"]
    assert found[0]["quote"] == "All tests pass: 540 passed."
    assert "tests_pass_without_run" not in _checks(report)


def test_cleared_sentence_with_no_narrower_finding_stays_clear(tmp_path):
    report = _gate_rows(tmp_path, _main_rows("All tests pass: 537 passed."),
                        _pair("a1b2c3", "toolu_01py", SUITE_CMD, SUITE_537))[1]
    assert report["findings"] == []
    assert report["subagent_cleared"] == ["tests_pass_without_run"]


def test_credit_only_merge_unit():
    main = [{"check": "tests_pass_without_run", "quote": "S1", "claimed": "", "observed": ""},
            {"check": "hook_bypass", "quote": "git x --no-verify", "claimed": "", "observed": ""}]
    merged = [{"check": "full_suite_claim_over_filtered_run", "quote": "S1", "claimed": "",
               "observed": "pytest -k x"},
              {"check": "count_mismatch", "quote": "S2", "claimed": "540", "observed": "537"},
              {"check": "hook_bypass", "quote": "git x --no-verify", "claimed": "", "observed": ""}]
    kept, cleared = gate.credit_only(main, merged)
    assert [f["check"] for f in kept] == ["hook_bypass", "full_suite_claim_over_filtered_run"]
    assert cleared == ["tests_pass_without_run"]


def test_non_string_edit_target_is_ignored(tmp_path):
    path = tmp_path / "agent-junk.jsonl"
    _write_jsonl(path, _tool_pair("j", "t1", "Edit", {"file_path": {"x": 1}}, "ok")
                 + _tool_pair("j", "t2", "Write", {"file_path": "tools/ok.py"}, "ok"))
    assert gate._scan_subagent_file(path)["edited"] == ["tools/ok.py"]


def test_clearable_set_is_exactly_the_coordinator_list():
    assert gate.CLEARABLE == frozenset({
        "tests_pass_without_run", "vacuous_run", "full_suite_claim_over_filtered_run",
        "count_mismatch", "file_claim_without_edit", "ci_claim_without_probe",
        "commit_claim_without_commit", "push_claim_without_push",
        "merge_claim_without_merge"})
    assert "subagent_hook_bypass" in gate.ADVISORY_CHECKS
