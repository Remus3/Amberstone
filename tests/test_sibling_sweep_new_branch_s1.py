"""S1 - a NEW remote ref is scanned against what the remote really advertises.

THE GAP (kit v19 parity, CS FIX 2026-10-18-1213 item 2)
-------------------------------------------------------
``tools/sibling_name_sweep.resolve_push_range`` resolved the first push of a
ref (remote sha all zeros), and a remote sha this clone does not hold, to
``<local_sha> --not --remotes=<remote>``: everything not reachable from the
LOCAL remote-tracking refs. Those refs are a cache, not the remote. After a
branch is deleted on the remote (or the remote is deleted and recreated, or
rewritten) a clone that has not pruned still carries
``refs/remotes/<remote>/<branch>`` naming commits the remote no longer has. A
new branch built on such a commit is then scanned as if those commits were
already public, so their bytes leave the machine unscanned.
``tools/credential_history_scan.py --pre-push`` imported the same resolver and
carried the same gap.

The fix mirrors ``ops/fleet_kit/fleet_identity.py`` v19: when any pushed line
needs it, ``git ls-remote <remote>`` is read once, the advertised shas present
locally are excluded (``<local_sha> ^a ^b ...``), and an ls-remote failure is a
FAULT (exit 3), never a fallback to the tracking refs.

The sweep stays ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO; this closes one
named escape, it does not prove there are none.

Synthetic placeholders only: the names below resolve to nothing, the drive
prefix is ASSEMBLED at run time (``_D``) so this file never trips the sweep's
config-free structural arm, and the credential-shaped value is assembled too.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# HARD imports, deliberately: an absent gate must not read as a green run.
from tools import credential_history_scan as chs  # noqa: E402
from tools import sibling_name_sweep as sweep  # noqa: E402

_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_Z = "0" * 40
_D = "C:" + "\\"
_FAKE_NAMES = ["Glimmerquay Basin", "Thornvessel", "Ospreyhollow Reach"]
_FAKE_REPOS = [_D + n for n in _FAKE_NAMES]
_FAKE_PARTICIPANTS = {"GQB": _FAKE_REPOS[0], "TVL": _FAKE_REPOS[1], "OHR": _FAKE_REPOS[2]}
_LEAK_TEXT = _D + _FAKE_NAMES[0] + "\\ops\\loop\\slots.py\n"
_FAKE_KEY = "sk-" + "ant-" + "R4" * 12  # anthropic shape, assembled
_CLEAN_TEXT = "an ordinary line of prose\n"


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.delenv("RC_SIBLING_SWEEP_BYPASS", raising=False)
    monkeypatch.setenv("RC_SIBLING_SWEEP_RUN_LOG", str(tmp_path / "runlog" / "runs.jsonl"))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, creationflags=_NW,
    ).stdout.strip()


def _commit(repo: Path, name: str, body: str, msg: str) -> str:
    (repo / name).write_text(body, encoding="ascii")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _new_clone(tmp_path: Path, remote: Path, name: str) -> Path:
    work = tmp_path / name
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    for key, value in (
        ("user.email", "t@example.invalid"), ("user.name", "t"),
        ("core.autocrlf", "false"), ("commit.gpgsign", "false"),
        ("core.hooksPath", str(tmp_path / "nohooks")),
    ):
        _git(work, "config", key, value)
    _git(work, "remote", "add", "origin", str(remote))
    return work


@pytest.fixture()
def pushenv(tmp_path: Path):
    """A bare remote plus one clone whose `main` is already on the remote."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    work = _new_clone(tmp_path, remote, "work")
    base = _commit(work, "README.txt", "base\n", "base")
    _git(work, "push", "-q", "--no-verify", "origin", "main")
    return remote, work, base


def _armed_root(tmp_path: Path) -> Path:
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps({"repos": _FAKE_REPOS, "participants": _FAKE_PARTICIPANTS}),
        encoding="utf-8",
    )
    return root


def _stale_tracking_push(remote: Path, work: Path, body: str) -> tuple:
    """A planted commit on NO remote ref, still named by a local tracking ref.

    The clone pushes `feature` (so refs/remotes/origin/feature names the
    planted commit), then the REMOTE loses the ref - deleted from another
    clone, or the remote recreated - and this clone never prunes. A new
    branch on top of the planted commit is then pushed for the first time.
    """
    _git(work, "checkout", "-q", "-b", "feature")
    planted = _commit(work, "notes.txt", body, "planted")
    _git(work, "push", "-q", "--no-verify", "origin", "feature")
    _git(remote, "update-ref", "-d", "refs/heads/feature")
    assert _git(work, "rev-parse", "refs/remotes/origin/feature") == planted
    assert "refs/heads/feature" not in _git(work, "ls-remote", "origin")
    _git(work, "checkout", "-q", "-b", "topic")
    tip = _commit(work, "more.txt", _CLEAN_TEXT, "clean follow-up")
    return planted, tip


def _collected_commits(work: Path, line: str) -> tuple:
    stats = sweep.ScanStats()
    blobs = sweep.collect_push_blobs(work, [line], "origin", stats)
    msgs = {b.path for b in blobs if b.source == "COMMIT-MSG"}
    return stats.commits, msgs, blobs


def _sweep_main(monkeypatch, tmp_path: Path, work: Path, line: str) -> int:
    monkeypatch.setattr(sweep, "REPO_ROOT", work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(line + "\n"))
    return sweep.main(["--pre-push", "origin", "--config-root", str(_armed_root(tmp_path))])


def _cred_main(monkeypatch, work: Path, line: str) -> int:
    monkeypatch.setattr(chs, "ROOT", work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(line + "\n"))
    return chs.main(["--pre-push", "origin"])


# --------------------------------------------------------------------------
# 1. The gap: a commit only a STALE tracking ref names is scanned
# --------------------------------------------------------------------------
def test_new_branch_scans_a_commit_only_a_stale_tracking_ref_names(pushenv):
    remote, work, _base = pushenv
    planted, tip = _stale_tracking_push(remote, work, _LEAK_TEXT)
    count, msgs, _blobs = _collected_commits(work, f"refs/heads/topic {tip} refs/heads/topic {_Z}")
    assert planted[:12] in msgs, "the planted commit is on no remote ref and was not scanned"
    assert tip[:12] in msgs
    assert count == 2


def test_new_branch_over_a_stale_tracking_ref_halts_end_to_end(pushenv, monkeypatch, tmp_path):
    remote, work, _base = pushenv
    _planted, tip = _stale_tracking_push(remote, work, _LEAK_TEXT)
    rc = _sweep_main(monkeypatch, tmp_path, work, f"refs/heads/topic {tip} refs/heads/topic {_Z}")
    assert rc == sweep.EXIT_HALT


def test_unknown_remote_sha_also_scans_against_the_advertisement(pushenv):
    """The second zeros-equivalent case: a remote sha this clone cannot resolve."""
    remote, work, _base = pushenv
    planted, tip = _stale_tracking_push(remote, work, _LEAK_TEXT)
    line = f"refs/heads/topic {tip} refs/heads/topic {'e' * 40}"
    count, msgs, _blobs = _collected_commits(work, line)
    assert planted[:12] in msgs
    assert count == 2


# --------------------------------------------------------------------------
# 2. Kit semantics: what the remote ADVERTISES is not rescanned
# --------------------------------------------------------------------------
def test_new_branch_does_not_rescan_commits_the_remote_advertises(pushenv, monkeypatch, tmp_path):
    remote, work, base = pushenv
    on_remote = _commit(work, "old.txt", _LEAK_TEXT, "already public")
    _git(work, "push", "-q", "--no-verify", "origin", "main")
    _git(work, "checkout", "-q", "-b", "topic2")
    tip = _commit(work, "new.txt", _CLEAN_TEXT, "clean")
    line = f"refs/heads/topic2 {tip} refs/heads/topic2 {_Z}"
    count, msgs, _blobs = _collected_commits(work, line)
    assert msgs == {tip[:12]}
    assert on_remote[:12] not in msgs and base[:12] not in msgs
    assert count == 1
    assert _sweep_main(monkeypatch, tmp_path, work, line) == sweep.EXIT_CLEAN


def test_an_advertised_sha_this_clone_lacks_is_dropped_not_a_fault(pushenv, tmp_path):
    """ls-remote names a commit pushed from ANOTHER clone; `^<absent sha>`
    would make rev-list fail, so only shas present locally are excluded."""
    remote, work, _base = pushenv
    other = _new_clone(tmp_path, remote, "other")
    _git(other, "fetch", "-q", "origin", "main")
    _git(other, "checkout", "-q", "-b", "elsewhere", "FETCH_HEAD")
    foreign = _commit(other, "x.txt", _CLEAN_TEXT, "from another clone")
    _git(other, "push", "-q", "--no-verify", "origin", "elsewhere")
    _git(work, "checkout", "-q", "-b", "topic3")
    tip = _commit(work, "y.txt", _CLEAN_TEXT, "clean")
    advertised = sweep.remote_advertised(work, "origin")
    assert foreign not in advertised
    count, msgs, _blobs = _collected_commits(work, f"refs/heads/topic3 {tip} refs/heads/topic3 {_Z}")
    assert msgs == {tip[:12]} and count == 1


def test_a_normal_push_of_a_known_remote_sha_does_not_call_ls_remote(pushenv, monkeypatch):
    _remote, work, base = pushenv
    tip = _commit(work, "z.txt", _CLEAN_TEXT, "clean")

    def _boom(*_a, **_k):
        raise AssertionError("ls-remote read for a push that names a known remote sha")

    monkeypatch.setattr(sweep, "remote_advertised", _boom)
    count, msgs, _blobs = _collected_commits(work, f"refs/heads/main {tip} refs/heads/main {base}")
    assert msgs == {tip[:12]} and count == 1


# --------------------------------------------------------------------------
# 3. Fail closed: ls-remote failing is a FAULT, never the tracking-ref range
# --------------------------------------------------------------------------
def test_ls_remote_failure_on_a_new_ref_is_a_fault(pushenv, monkeypatch, tmp_path):
    _remote, work, _base = pushenv
    _git(work, "checkout", "-q", "-b", "topic4")
    tip = _commit(work, "w.txt", _CLEAN_TEXT, "clean")
    _git(work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    line = f"refs/heads/topic4 {tip} refs/heads/topic4 {_Z}"
    with pytest.raises(sweep.GitFault):
        sweep.collect_push_blobs(work, [line], "origin", sweep.ScanStats())
    assert _sweep_main(monkeypatch, tmp_path, work, line) == sweep.EXIT_FAULT
    assert _cred_main(monkeypatch, work, line) == chs.EXIT_FAULT


# --------------------------------------------------------------------------
# 4. The pure resolver
# --------------------------------------------------------------------------
def test_resolver_excludes_only_the_advertised_shas_on_a_new_ref():
    spec = sweep.resolve_push_range(
        f"refs/heads/n {'a' * 40} refs/heads/n {_Z}", "origin",
        have=lambda s: True, advertised=["b" * 40, "c" * 40],
    )
    assert spec is not None
    assert spec.args == ["a" * 40, "^" + "b" * 40, "^" + "c" * 40]
    assert "--remotes=origin" not in spec.args


def test_resolver_on_an_empty_remote_scans_the_whole_branch():
    spec = sweep.resolve_push_range(
        f"refs/heads/n {'a' * 40} refs/heads/n {_Z}", "origin",
        have=lambda s: True, advertised=[],
    )
    assert spec is not None and spec.args == ["a" * 40]


def test_a_long_exclusion_list_goes_to_git_on_stdin_not_argv():
    """Every advertised sha is one argv word; a large remote would overrun the
    Windows command-line cap, so a plain-rev list is fed with --stdin."""
    revs = ["a" * 40] + ["^" + format(i, "040x") for i in range(2000)]
    assert sweep.stdin_revs(revs) == "\n".join(revs) + "\n"
    assert sweep.stdin_revs(["a" * 40, "--not", "b" * 40]) is None


# --------------------------------------------------------------------------
# 5. The credential scan shares the resolver and so shares the fix
# --------------------------------------------------------------------------
def test_credential_scan_new_branch_over_a_stale_tracking_ref_halts(pushenv, monkeypatch):
    remote, work, _base = pushenv
    _planted, tip = _stale_tracking_push(remote, work, f'KEY = "{_FAKE_KEY}"\n')
    rc = _cred_main(monkeypatch, work, f"refs/heads/topic {tip} refs/heads/topic {_Z}")
    assert rc == chs.EXIT_HALT


def test_credential_scan_does_not_rescan_what_the_remote_advertises(pushenv, monkeypatch):
    _remote, work, _base = pushenv
    _commit(work, "cfg.py", f'KEY = "{_FAKE_KEY}"\n', "already public")
    _git(work, "push", "-q", "--no-verify", "origin", "main")
    _git(work, "checkout", "-q", "-b", "topic5")
    tip = _commit(work, "b.py", "def f():\n    return 2\n", "clean")
    rc = _cred_main(monkeypatch, work, f"refs/heads/topic5 {tip} refs/heads/topic5 {_Z}")
    assert rc == chs.EXIT_CLEAN
