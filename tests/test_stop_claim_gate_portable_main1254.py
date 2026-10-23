"""MAIN FIX 2026-10-21 1254 item #9: tools/stop_claim_gate.py portability and
fail-open defects, found when a second machine adopted RC's Claude hooks.

Measured at main 915300765 before the fix:
  (a) ROOT was `Path(__file__).parent.parent`, so a copy of the hook placed at
      any depth other than <repo>/tools/ resolved the wrong repo root;
  (b) the report, history and seen-set state were fixed under ops/runtime/
      with no single switch to move them;
  (c) `_NOT_A_CHANNEL_CODE` hard-coded RC and DS as THIS tree's own codes, so
      in another tree "RC committed ..." was laundered as the speaker's own
      claim and the tree's real code read as a third party;
  (d) the report write sat outside any guard: an unwritable report path
      exited 1 with a traceback, and an argparse error exited 2, which a Stop
      hook treats as BLOCKING;
  (e) prune_seen() unlinked stale seen-set files directly (fleet rule 9).

The Claude-hook channel may fail OPEN (the git hooks are the authoritative,
fail-closed gate), so every failure here is exit 0 with nothing on stderr;
stdout stays silent except that an armed finding whose report is unwritable
still prints its one feedback line (RM-796).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import stop_claim_gate as gate

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "tools" / "stop_claim_gate.py"

CLAIM = "The full suite passes."


def _transcript(tmp_path, *texts):
    path = tmp_path / "transcript.jsonl"
    rows = [{"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": t}]}} for t in texts]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _run(tmp_path, transcript, *extra):
    payload = json.dumps({"session_id": "portable-test", "cwd": str(ROOT),
                          "transcript_path": str(transcript),
                          "hook_event_name": "Stop", "stop_hook_active": False})
    return subprocess.run([sys.executable, str(GATE), *extra], input=payload,
                          capture_output=True, text=True, cwd=str(tmp_path),
                          check=False)


def _checks(report_path):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return {f["check"] for f in report["findings"]}


# ------------------------------------------------------------ (d) fail open

def test_an_unwritable_report_path_exits_zero_with_no_error_output(tmp_path):
    """(d): exit 0, nothing on stderr. RM-796 (adjudicated 2026-10-23): stdout
    was pinned EMPTY here, which pinned the dropped armed finding; the hook now
    emits its one feedback line, saying the report is unwritable."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    proc = _run(tmp_path, _transcript(tmp_path, CLAIM), "--arm",
                "--report", str(blocker / "r.json"),
                "--history", str(tmp_path / "h.jsonl"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "", proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout
    context = json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]
    assert context.endswith("; report unwritable"), context


def test_an_internal_error_fails_open_and_is_recorded(tmp_path, monkeypatch):
    def boom(_ev):
        raise RuntimeError("synthetic audit crash")

    monkeypatch.setattr(gate, "audit", boom)
    monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps(
        {"session_id": "s", "transcript_path": str(_transcript(tmp_path, CLAIM))})))
    report = tmp_path / "r.json"
    rc = gate.main(["--arm", "--report", str(report),
                    "--history", str(tmp_path / "h.jsonl")])
    assert rc == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["error"] == "internal-error"
    assert data["exception"] == "RuntimeError"


BAD_ARGVS = [
    ["--no-such-flag"],
    ["--own-codes"],  # malformed --own-codes: the value is missing
    ["--history-max", "not-a-number"],
]


@pytest.mark.parametrize("argv", BAD_ARGVS)
def test_a_bad_argument_exits_zero_and_prints_nothing(argv, monkeypatch, capsys):
    """Exit 2 from a Stop hook BLOCKS the stop; argparse exits 2 on a typo and
    writes its usage to stderr. Both must be gone: exit 0, silent."""
    monkeypatch.setattr(sys, "stdin", _Stdin("{}"))
    assert gate.main(argv) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == "", (out.out, out.err)


@pytest.mark.parametrize("argv", BAD_ARGVS)
def test_a_bad_argument_is_silent_end_to_end(argv, tmp_path):
    proc = subprocess.run([sys.executable, str(GATE), *argv], input=b"{}",
                          capture_output=True, cwd=str(tmp_path), check=False)
    assert proc.returncode == 0
    assert proc.stdout == b"" and proc.stderr == b"", (proc.stdout, proc.stderr)


def test_help_still_exits_zero(capsys):
    with pytest.raises(SystemExit) as info:
        gate.main(["--help"])
    assert info.value.code == 0


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


# --------------------------------------------------- (c) configurable codes

@pytest.fixture
def restore_codes():
    yield
    gate.set_own_codes(gate.DEFAULT_OWN_CODES)


def _commit_flagged(sentence):
    ev = {"texts": [sentence], "bash": [], "edited": [], "runs": [],
          "ci_runs": [], "artifacts": []}
    return "commit_claim_without_commit" in {f["check"] for f in gate.audit(ev)}


def test_default_own_codes_are_rc_and_ds():
    assert gate.DEFAULT_OWN_CODES == ("RC", "DS")


def test_own_codes_decide_who_is_the_speaker(restore_codes):
    assert gate.set_own_codes(["XY"]) == ("XY",)
    assert _commit_flagged("XY committed the adoption."), "own code: the speaker"
    assert not _commit_flagged("RC committed the adoption."), "RC is a sibling here"
    gate.set_own_codes(gate.DEFAULT_OWN_CODES)
    assert _commit_flagged("RC committed the adoption.")
    assert not _commit_flagged("XY committed the adoption.")


def test_own_codes_reject_shapes_a_code_cannot_take(restore_codes):
    assert gate.set_own_codes(["xy", " AB ", "TOOLONG", "A", "C1", ""]) == ("XY", "AB")


def test_acronyms_stay_refused_whatever_the_own_codes(restore_codes):
    gate.set_own_codes([])
    assert _commit_flagged("THE COMMITTED FIX IS IN MAIN.")


def test_own_codes_flag_end_to_end(tmp_path):
    report = tmp_path / "r.json"
    proc = _run(tmp_path, _transcript(tmp_path, "XY committed the adoption."),
                "--own-codes", "XY", "--report", str(report),
                "--history", str(tmp_path / "h.jsonl"))
    assert proc.returncode == 0, proc.stderr
    assert "commit_claim_without_commit" in _checks(report)
    proc = _run(tmp_path, _transcript(tmp_path, "XY committed the adoption."),
                "--report", str(report), "--history", str(tmp_path / "h.jsonl"))
    assert proc.returncode == 0, proc.stderr
    assert "commit_claim_without_commit" not in _checks(report)


# -------------------------------------------------- (a) root, (b) state dir

def test_root_is_the_nearest_git_ancestor_of_the_hook(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    hook = repo / ".claude" / "hooks" / "stop_claim_gate.py"
    assert gate.find_root(hook) == repo
    hook = repo / "stop_claim_gate.py"
    assert gate.find_root(hook) == repo


def test_a_linked_worktree_git_file_counts(tmp_path):
    wt = tmp_path / "wt"
    (wt / "tools").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert gate.find_root(wt / "tools" / "stop_claim_gate.py") == wt


def test_no_git_within_the_search_depth_falls_back_to_the_parent_of_tools(tmp_path):
    deep = tmp_path.joinpath(*(f"d{i}" for i in range(gate.ROOT_SEARCH_DEPTH + 2)))
    hook = deep / "tools" / "stop_claim_gate.py"
    assert gate.find_root(hook) == deep


def test_live_root_is_this_checkout():
    assert gate.ROOT == ROOT


def test_state_dir_moves_report_and_history(tmp_path):
    state = tmp_path / "state"
    proc = _run(tmp_path, _transcript(tmp_path, CLAIM), "--state-dir", str(state))
    assert proc.returncode == 0, proc.stderr
    assert "tests_pass_without_run" in _checks(state / "stop_claim_report.json")
    assert (state / "stop_claim_history.jsonl").exists()


# ------------------------------------------------------ (e) prune by moving

def test_prune_moves_stale_seen_files_and_never_unlinks(tmp_path, monkeypatch):
    for i in range(6):
        path = tmp_path / f"s{i}.json"
        path.write_text(json.dumps({"keys": [str(i)]}), encoding="utf-8")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))

    def refuse(self, *a, **k):
        raise AssertionError(f"prune_seen unlinked {self}")

    monkeypatch.setattr(Path, "unlink", refuse)
    gate.prune_seen(tmp_path, keep=2)
    kept = sorted(p.name for p in tmp_path.glob("*.json"))
    assert kept == ["s4.json", "s5.json"]
    moved = sorted((tmp_path / gate.PRUNED_DIRNAME).iterdir())
    assert len(moved) == 4
    bodies = sorted(json.loads(p.read_text(encoding="utf-8"))["keys"][0] for p in moved)
    assert bodies == ["0", "1", "2", "3"], "content survives the move"


def test_a_second_prune_never_overwrites_an_earlier_move(tmp_path):
    for round_ in range(2):
        for i in range(3):
            path = tmp_path / f"s{i}.json"
            path.write_text(json.dumps({"round": round_}), encoding="utf-8")
            os.utime(path, (1_000_000 + 10 * round_ + i,) * 2)
        gate.prune_seen(tmp_path, keep=1)
    moved = list((tmp_path / gate.PRUNED_DIRNAME).iterdir())
    assert len(moved) == 4, sorted(p.name for p in moved)
