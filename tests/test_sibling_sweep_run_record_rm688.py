"""RM-688 - every sibling-name sweep run leaves ONE redacted JSONL run record.

WHY THIS EXISTS
---------------
Before RM-688 ``tools/sibling_name_sweep.py`` wrote to disk only on its two
BYPASS paths. A clean pre-push run, a HALT and every FAULT left no trace, so a
push that ran the gate and came back clean was indistinguishable, after the
fact, from ``git push --no-verify`` - which skips ``.githooks/pre-push``
entirely. The run record is the after-the-fact signal: a pushed range with no
matching record is a range the gate never saw. It does NOT make ``--no-verify``
detectable in real time, and nothing here claims it does.

THE RECORD MUST NOT BECOME THE LEAK
-----------------------------------
The record lands in ``ops/runtime/`` and is gitignored, but the same rule as the
report applies: it carries enums, ints, bools, an ISO time and validated hex
only. Nothing derived from file content, file paths, ref NAMES, the remote name,
the remote URL or a finding literal. Case 2 and case 5 assert that directly.

The names below are SYNTHETIC placeholders invented for this file; they
resolve to nothing. Drive prefixes are ASSEMBLED at run time (``_D``) so this
file never trips the sweep's own config-free structural arm.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# A HARD import, deliberately: an absent sweep must not read as a green run.
from tools import sibling_name_sweep as sweep  # noqa: E402

_ENV = "RC_SIBLING_SWEEP_RUN_LOG"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NOTICE = "[sibling-sweep] run record could not be written."

_D = "C:" + "\\"
_FAKE_NAMES = ["Vorpalyx Delta", "Quillmarsh", "Brindlewick Spur"]
_FAKE_REPOS = [_D + n for n in _FAKE_NAMES]
_FAKE_PARTICIPANTS = {"VXD": _FAKE_REPOS[0], "QMH": _FAKE_REPOS[1], "BWS": _FAKE_REPOS[2]}

_KEYS = {
    "v", "ts", "arm", "explain", "cfg", "verdict", "exit", "hits",
    "commits", "files", "bytes", "range", "head", "worktree", "bypass_env",
}


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.delenv("RC_SIBLING_SWEEP_BYPASS", raising=False)


@pytest.fixture()
def run_log(monkeypatch, tmp_path: Path) -> Path:
    log = tmp_path / "runlog" / "sibling_sweep_runs.jsonl"
    monkeypatch.setenv(_ENV, str(log))
    return log


def _armed_root(tmp_path: Path) -> Path:
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps({"repos": _FAKE_REPOS, "participants": _FAKE_PARTICIPANTS}),
        encoding="utf-8",
    )
    return root


def _fault_root(tmp_path: Path) -> Path:
    root = tmp_path / "faultroot"
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text("{not json", encoding="utf-8")
    return root


def _clean_file(tmp_path: Path) -> Path:
    p = tmp_path / "cleanprobe_rm688.txt"
    p.write_text("an ordinary line of prose\n", encoding="utf-8")
    return p


def _leak_file(tmp_path: Path) -> Path:
    p = tmp_path / "leakprobe_rm688.txt"
    p.write_text(
        _D + _FAKE_NAMES[0] + "\\ops\\loop\\slots.py\n"
        + "see " + _FAKE_NAMES[1] + " for the other half\n",
        encoding="utf-8",
    )
    return p


def _lines(log: Path) -> list:
    if not log.exists():
        return []
    return [ln for ln in log.read_text(encoding="ascii").splitlines() if ln.strip()]


def _records(log: Path) -> list:
    return [json.loads(ln) for ln in _lines(log)]


def _scan(tmp_path: Path, target: Path, root: Path, *extra: str) -> int:
    return sweep.main(["--scan-file", str(target), "--config-root", str(root), *extra])


def _scenario(tmp_path: Path, kind: str) -> int:
    if kind == "clean":
        return _scan(tmp_path, _clean_file(tmp_path), _armed_root(tmp_path))
    if kind == "hit":
        return _scan(tmp_path, _leak_file(tmp_path), _armed_root(tmp_path))
    if kind == "fault":
        return _scan(tmp_path, _clean_file(tmp_path), _fault_root(tmp_path))
    raise AssertionError(kind)


def _git(cwd: Path, *args: str) -> str:
    hooks = cwd.parent / "_no_hooks_rm688"
    hooks.mkdir(exist_ok=True)
    proc = subprocess.run(
        [
            "git",
            "-c", f"core.hooksPath={hooks}",
            "-c", "user.name=sweep-test",
            "-c", "user.email=sweep-test@example.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
        creationflags=_NO_WINDOW,
    )
    return proc.stdout


# --------------------------------------------------------------------------
# 1. clean run -> exactly one ASCII line with the full key set
# --------------------------------------------------------------------------
def test_clean_scan_file_run_appends_one_record(tmp_path, run_log):
    rc = _scenario(tmp_path, "clean")
    assert rc == sweep.EXIT_CLEAN
    raw = run_log.read_bytes()
    assert all(b < 128 for b in raw), "the run record is not pure ASCII"
    assert raw.endswith(b"\n") and b"\r" not in raw
    lines = _lines(run_log)
    assert len(lines) == 1, lines
    rec = json.loads(lines[0])
    assert set(rec) == _KEYS, sorted(set(rec) ^ _KEYS)
    assert rec["v"] == 1
    assert rec["verdict"] == "clean"
    assert rec["exit"] == 0
    assert rec["arm"] == "scan-file"
    assert rec["cfg"] == "ARMED"
    assert rec["explain"] is False
    assert rec["hits"] == 0
    assert rec["files"] == 1
    assert rec["bytes"] > 0
    assert rec["range"] == []
    assert rec["bypass_env"] is False
    assert isinstance(rec["worktree"], bool)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", rec["ts"]), rec["ts"]
    # REPO_ROOT is the real checkout here, so HEAD resolves.
    assert rec["head"] is None or re.fullmatch(r"[0-9a-f]{12}", rec["head"]), rec["head"]


# --------------------------------------------------------------------------
# 2. a HIT is recorded as a hit, and the record carries no name / path
# --------------------------------------------------------------------------
def test_hit_record_carries_no_name_no_filename_no_path(tmp_path, run_log):
    target = _leak_file(tmp_path)
    rc = _scan(tmp_path, target, _armed_root(tmp_path))
    assert rc == sweep.EXIT_HALT
    lines = _lines(run_log)
    assert len(lines) == 1, lines
    rec = json.loads(lines[0])
    assert rec["verdict"] == "hit"
    assert rec["exit"] == 2
    assert rec["hits"] >= 1
    assert rec["cfg"] == "ARMED"

    line = lines[0]
    low = line.lower()
    tight_line = re.sub(r"[\s_\-]", "", low)
    for name in _FAKE_NAMES:
        assert name.lower() not in low
        tight = re.sub(r"[\s_\-]", "", name.lower())
        assert tight not in tight_line
        for word in name.lower().split():
            assert word not in low, word
    assert target.name.lower() not in low
    assert target.stem.lower() not in low
    assert "/" not in line
    assert "\\" not in line


# --------------------------------------------------------------------------
# 3. BYPASS: verdict bypass, exit unchanged, bypass log unchanged
# --------------------------------------------------------------------------
def test_bypass_is_recorded_and_bypass_log_behaviour_is_unchanged(
    tmp_path, run_log, monkeypatch, capsys
):
    monkeypatch.setenv("RC_SIBLING_SWEEP_BYPASS", "1")
    fake_root = tmp_path / "fake_repo_root"
    fake_root.mkdir()
    monkeypatch.setattr(sweep, "REPO_ROOT", fake_root)
    rc = _scan(tmp_path, _leak_file(tmp_path), _armed_root(tmp_path))
    err = capsys.readouterr().err
    assert rc == sweep.EXIT_CLEAN, err
    assert "BYPASS engaged - proceeding anyway." in err
    bypass_log = fake_root / sweep.BYPASS_LOG
    assert bypass_log.is_file()
    assert "BYPASS" in bypass_log.read_text(encoding="utf-8")
    recs = _records(run_log)
    assert len(recs) == 1
    assert recs[0]["verdict"] == "bypass"
    assert recs[0]["exit"] == 0
    assert recs[0]["bypass_env"] is True
    assert recs[0]["hits"] >= 1
    # The run record never lands beside the bypass log when redirected.
    assert not (fake_root / "ops" / "runtime" / "sibling_sweep_runs.jsonl").exists()


def test_degraded_pre_push_bypass_is_recorded_as_bypass(tmp_path, run_log, monkeypatch):
    monkeypatch.setenv("RC_SIBLING_SWEEP_BYPASS", "1")
    fake_root = tmp_path / "fake_repo_root"
    fake_root.mkdir()
    noconfig = tmp_path / "noconfig"
    noconfig.mkdir()
    monkeypatch.setattr(sweep, "REPO_ROOT", fake_root)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(noconfig)])
    assert rc == sweep.EXIT_CLEAN
    recs = _records(run_log)
    assert len(recs) == 1
    assert recs[0]["cfg"] == "DEGRADED"
    assert recs[0]["verdict"] == "bypass"
    assert recs[0]["arm"] == "pre-push"


def test_degraded_pre_push_without_bypass_is_recorded_as_fault(tmp_path, run_log, monkeypatch):
    fake_root = tmp_path / "fake_repo_root"
    fake_root.mkdir()
    noconfig = tmp_path / "noconfig"
    noconfig.mkdir()
    monkeypatch.setattr(sweep, "REPO_ROOT", fake_root)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(noconfig)])
    assert rc == sweep.EXIT_FAULT
    recs = _records(run_log)
    assert len(recs) == 1
    assert recs[0]["verdict"] == "fault"
    assert recs[0]["exit"] == 3
    assert recs[0]["cfg"] == "DEGRADED"


# --------------------------------------------------------------------------
# 4. FAULT config -> verdict fault, exit 3
# --------------------------------------------------------------------------
def test_fault_config_is_recorded_as_fault(tmp_path, run_log):
    rc = _scenario(tmp_path, "fault")
    assert rc == sweep.EXIT_FAULT
    recs = _records(run_log)
    assert len(recs) == 1
    assert recs[0]["verdict"] == "fault"
    assert recs[0]["exit"] == 3
    assert recs[0]["cfg"] == "FAULT"
    assert recs[0]["hits"] == 0


# --------------------------------------------------------------------------
# 5. --pre-push: the range is recorded as hex only; no ref / remote / URL
# --------------------------------------------------------------------------
def test_pre_push_records_hex_range_and_no_ref_remote_or_url(tmp_path, run_log, monkeypatch):
    repo = tmp_path / "pushrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.txt").write_text("fixture one\n", encoding="utf-8")
    _git(repo, "add", "README.txt")
    _git(repo, "commit", "-q", "--no-verify", "-m", "fixture one")
    first = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "README.txt").write_text("fixture two\n", encoding="utf-8")
    _git(repo, "add", "README.txt")
    _git(repo, "commit", "-q", "--no-verify", "-m", "fixture two")
    second = _git(repo, "rev-parse", "HEAD").strip()

    ref = "refs/heads/rangeprobe-branch"
    url = "https://example.invalid/x.git"
    monkeypatch.setattr(sweep, "REPO_ROOT", repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{ref} {second} {ref} {first}\n"))
    rc = sweep.main(
        ["--pre-push", "origin", url, "--config-root", str(_armed_root(tmp_path))]
    )
    assert rc == sweep.EXIT_CLEAN
    lines = _lines(run_log)
    assert len(lines) == 1, lines
    rec = json.loads(lines[0])
    assert rec["arm"] == "pre-push"
    assert rec["verdict"] == "clean"
    assert rec["range"] == [f"{first[:12]}..{second[:12]}"]
    assert rec["commits"] == 1
    assert rec["head"] == second[:12]
    line = lines[0]
    for forbidden in ("rangeprobe", "refs", "heads", "origin", "example.invalid", url, "https"):
        assert forbidden not in line, forbidden
    assert "/" not in line and "\\" not in line


def test_pre_push_range_skips_non_hex_lines_and_caps_at_sixteen(tmp_path, run_log, monkeypatch):
    """Field validation is part of the redaction: a non-hex 2nd/4th field is
    dropped, never echoed. Zeros (a first push or a delete) are hex."""
    zeros = "0" * 40
    good = "ab" * 20
    lines_in = [f"refs/heads/r{i} {good} refs/heads/r{i} {zeros}" for i in range(20)]
    lines_in.insert(0, "refs/heads/x NOTHEX refs/heads/x NOTHEX")

    def _fake_collect(_root, _ref_lines, _remote, _stats):
        return [sweep.Blob("HUNK", "some/tracked/file.py", "M", "an ordinary line\n")]

    monkeypatch.setattr(sweep, "collect_push_blobs", _fake_collect)
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines_in) + "\n"))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(_armed_root(tmp_path))])
    assert rc == sweep.EXIT_CLEAN
    rec = _records(run_log)[0]
    assert len(rec["range"]) == 16
    assert all(r == f"{zeros[:12]}..{good[:12]}" for r in rec["range"])
    assert "NOTHEX" not in run_log.read_text(encoding="ascii")


# --------------------------------------------------------------------------
# 6. an unwritable record path never changes the outcome
# --------------------------------------------------------------------------
def test_unwritable_record_path_keeps_exit_code_and_prints_one_notice(
    tmp_path, monkeypatch, capsys
):
    good = tmp_path / "good" / "runs.jsonl"
    monkeypatch.setenv(_ENV, str(good))
    rc_ok = _scenario(tmp_path, "clean")
    first_err = capsys.readouterr().err
    assert _NOTICE not in first_err
    # The record's PARENT directory is occupied by a regular file, so both the
    # mkdir and the open must fail.
    blocker = tmp_path / "blocker_is_a_file"
    blocker.write_text("not a directory\n", encoding="ascii")
    monkeypatch.setenv(_ENV, str(blocker / "sub" / "runs.jsonl"))
    rc_bad = _scenario(tmp_path, "clean")
    err = capsys.readouterr().err
    assert rc_bad == rc_ok == sweep.EXIT_CLEAN
    assert err.count(_NOTICE) == 1, err
    assert len(_lines(good)) == 1


# --------------------------------------------------------------------------
# 7. exit-code invariance: clean / hit / fault, writable vs unwritable
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind,expected",
    [("clean", 0), ("hit", 2), ("fault", 3)],
)
def test_exit_code_is_invariant_to_the_record_path(tmp_path, monkeypatch, capsys, kind, expected):
    good = tmp_path / "good" / "runs.jsonl"
    wdir = tmp_path / "w"
    wdir.mkdir()
    monkeypatch.setenv(_ENV, str(good))
    rc_ok = _scenario(wdir, kind)
    blocker = tmp_path / "blocker_is_a_file"
    blocker.write_text("x\n", encoding="ascii")
    monkeypatch.setenv(_ENV, str(blocker / "runs.jsonl"))
    udir = tmp_path / "u"
    udir.mkdir()
    rc_bad = _scenario(udir, kind)
    err = capsys.readouterr().err
    assert rc_ok == rc_bad == expected
    assert len(_lines(good)) == 1
    assert err.count(_NOTICE) == 1


# --------------------------------------------------------------------------
# 8. a linked worktree resolves the record into the MAIN checkout
# --------------------------------------------------------------------------
def _fake_linked_worktree(tmp_path: Path):
    main = tmp_path / "mainco"
    gitdir = main / ".git" / "worktrees" / "x"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="ascii")
    wt = tmp_path / "linkedwt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return main, wt


def test_run_log_path_resolves_to_the_main_tree_from_a_linked_worktree(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    main, wt = _fake_linked_worktree(tmp_path)
    monkeypatch.setattr(sweep, "REPO_ROOT", wt)
    got = sweep.run_log_path()
    assert got == main / "ops" / "runtime" / "sibling_sweep_runs.jsonl"
    assert wt not in got.parents


def test_run_log_path_in_the_main_tree_and_under_the_env_override(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    main, _wt = _fake_linked_worktree(tmp_path)
    monkeypatch.setattr(sweep, "REPO_ROOT", main)
    assert sweep.run_log_path() == main / "ops" / "runtime" / "sibling_sweep_runs.jsonl"
    override = tmp_path / "elsewhere" / "r.jsonl"
    monkeypatch.setenv(_ENV, str(override))
    assert sweep.run_log_path() == override


def test_record_written_from_a_linked_worktree_lands_in_the_main_tree(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    main, wt = _fake_linked_worktree(tmp_path)
    monkeypatch.setattr(sweep, "REPO_ROOT", wt)
    rc = _scenario(tmp_path, "clean")
    assert rc == sweep.EXIT_CLEAN
    recs = _records(main / "ops" / "runtime" / "sibling_sweep_runs.jsonl")
    assert len(recs) == 1
    assert recs[0]["worktree"] is True
    assert not (wt / "ops").exists()


# --------------------------------------------------------------------------
# 9. append, never overwrite
# --------------------------------------------------------------------------
def test_two_runs_append_two_lines(tmp_path, run_log):
    assert _scenario(tmp_path, "clean") == sweep.EXIT_CLEAN
    other = tmp_path / "second"
    other.mkdir()
    assert _scenario(other, "hit") == sweep.EXIT_HALT
    recs = _records(run_log)
    assert [r["verdict"] for r in recs] == ["clean", "hit"]


# --------------------------------------------------------------------------
# 10. the live record is gitignored
# --------------------------------------------------------------------------
def test_live_record_path_is_gitignored():
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q",
         "ops/runtime/sibling_sweep_runs.jsonl"],
        capture_output=True,
        creationflags=_NO_WINDOW,
    )
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# 11. conftest redirects the record away from the live tree
# --------------------------------------------------------------------------
def test_conftest_redirects_the_run_record_out_of_the_repo():
    # Read to a local first: asserting on os.environ.get(...) directly makes
    # pytest render the whole environment on failure.
    value = os.environ.get(_ENV)
    assert value, f"{_ENV} is not set under pytest"
    resolved = Path(value).resolve()
    roots = [REPO_ROOT.resolve()]
    main = sweep.main_working_tree(REPO_ROOT)
    if main is not None:
        roots.append(main.resolve())
    for root in roots:
        assert root != resolved and root not in resolved.parents, resolved
    assert sweep.run_log_path().resolve() == resolved


# --------------------------------------------------------------------------
# Structure: usage errors are not runs; an unexpected exception still records
# --------------------------------------------------------------------------
def test_usage_error_is_not_recorded(run_log):
    assert sweep.main([]) == sweep.EXIT_USAGE
    assert _lines(run_log) == []


def test_unexpected_exception_propagates_and_is_recorded_as_fault(
    tmp_path, run_log, monkeypatch
):
    def _boom(*_a, **_k):
        raise RuntimeError("synthetic failure inside the scan")

    monkeypatch.setattr(sweep, "_run_scan", _boom)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        _scenario(tmp_path, "clean")
    recs = _records(run_log)
    assert len(recs) == 1
    assert recs[0]["verdict"] == "fault"
    assert recs[0]["exit"] is None
    assert "synthetic" not in run_log.read_text(encoding="ascii")


def test_explain_run_is_recorded_by_findings(tmp_path, run_log, capsys):
    rc = _scan(tmp_path, _leak_file(tmp_path), _armed_root(tmp_path), "--explain", "0")
    capsys.readouterr()
    assert rc == sweep.EXIT_HALT
    rec = _records(run_log)[0]
    assert rec["explain"] is True
    assert rec["verdict"] == "hit"
    # --explain prints the literal to stderr by design; the record never does.
    low = run_log.read_text(encoding="ascii").lower()
    for name in _FAKE_NAMES:
        assert name.lower() not in low
