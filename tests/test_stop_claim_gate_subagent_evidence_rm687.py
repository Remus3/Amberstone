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
PUSH_CMD = ('cd "/e/Riot Commander" && timeout 280 git push origin main 2>&1 | tail -8; '
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
ANCESTRY_CMD = ('cd "E:/Riot Commander" && git fetch origin main 2>&1; echo "fetch_exit=$?"; '
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


REFLOG_CMD = 'cd "E:/Riot Commander" && git reflog show --date=iso refs/remotes/origin/main | head -4'
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

WT_FILE = "E:/Riot Commander/.claude/worktrees/agent-x/tools/foo_rm687.py"


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
