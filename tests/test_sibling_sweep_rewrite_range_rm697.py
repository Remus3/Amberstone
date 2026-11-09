"""RM-697 - a ref force-updated across a history rewrite is not rescanned whole.

THE GAP (filed rw2, LEDGER 1701; refreshed s133 research cycle 5)
------------------------------------------------------------------
``tools/sibling_name_sweep.resolve_push_range`` resolves an update of a ref
the remote already holds to ``<new> --not <old remote sha>``. After a history
rewrite the old remote sha is NOT an ancestor of the new one, so that range is
every commit of the rewritten lineage - including the commits the remote
already ADVERTISES under another ref (rw2: 4517 already-public commits, 14
historical findings, a false HALT that forced a delete-then-create).
``tools/credential_history_scan.py --pre-push`` shares the resolver.

THE FIX (acceptance as refreshed: the advertised set, never ``--remotes``)
-------------------------------------------------------------------------
When the old remote sha is present locally and ``git merge-base
--is-ancestor`` says it is NOT an ancestor of the new sha, the range also
excludes what ``git ls-remote`` advertises: ``<new> ^<old> ^a ^b ...``.
Unchanged: a fast-forward keeps the exact ``--not <old>`` range and reads no
ls-remote; ``advertised=None`` or an unknown ancestry keeps today's form (scan
MORE, never less); an ls-remote failure for a rewrite-only push falls back to
today's exact range (it only scans more), while a new-ref line still FAULTs.

The fixture never pushes or fetches: the "remote" is a bare repo borrowing the
clone's objects through ``objects/info/alternates``, its refs set with
``update-ref``, so ``git ls-remote`` advertises exactly what the test says.

The sweep stays ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO; this narrows a
false HALT, it does not prove there are no escapes.

Synthetic placeholders only: the names resolve to nothing, the drive prefix and
the credential-shaped value are ASSEMBLED at run time.
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
from tests._module_view import bind_subprocess  # noqa: E402
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


def _set_remote_refs(remote: Path, refs: dict) -> None:
    for ref in _git(remote, "for-each-ref", "--format=%(refname)").splitlines():
        if ref.strip():
            _git(remote, "update-ref", "-d", ref.strip())
    for ref, sha in refs.items():
        _git(remote, "update-ref", ref, sha)


@pytest.fixture
def rewritten(tmp_path: Path):
    """An old lineage the remote held, its rewrite (already advertised under
    another ref), and one new commit on the rewrite: the forced update."""
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    for key, value in (
        ("user.email", "t@example.invalid"), ("user.name", "t"),
        ("core.autocrlf", "false"), ("commit.gpgsign", "false"),
        ("core.hooksPath", str(tmp_path / "nohooks")),
    ):
        _git(work, "config", key, value)
    old1 = _commit(work, "a.txt", "old one\n" + _LEAK_TEXT, "old one")
    old2 = _commit(work, "b.txt", "old two\n", "old two")
    _git(work, "checkout", "-q", "--orphan", "rw")
    _git(work, "rm", "-q", "-rf", "--cached", ".")
    for stale in ("a.txt", "b.txt"):
        (work / stale).unlink()
    # The rewritten lineage still carries the historical finding: it is
    # already public (advertised), so a rewrite push must not re-raise it.
    rw1 = _commit(work, "a.txt", "rewritten one\n" + _LEAK_TEXT, "rewritten one")
    rw2 = _commit(work, "b.txt", "rewritten two\n", "rewritten two")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    alt = remote / "objects" / "info" / "alternates"
    # Bytes, not write_text: a CRLF line end makes git read a path ending in CR.
    alt.write_bytes(((work / ".git" / "objects").as_posix() + "\n").encode("ascii"))
    _set_remote_refs(remote, {"refs/heads/main": old2, "refs/heads/rewritten": rw2})
    _git(work, "remote", "add", "origin", str(remote))
    return {"work": work, "remote": remote, "old1": old1, "old2": old2,
            "rw1": rw1, "rw2": rw2}


def _armed_root(tmp_path: Path) -> Path:
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps({"repos": _FAKE_REPOS, "participants": _FAKE_PARTICIPANTS}),
        encoding="utf-8",
    )
    return root


def _rev_list(work: Path, args: list) -> list:
    revs = sweep.stdin_revs(args)
    if revs is not None:
        out = subprocess.run(
            ["git", "-C", str(work), "rev-list", "--stdin"], input=revs,
            capture_output=True, text=True, check=True, creationflags=_NW,
        ).stdout
    else:
        out = _git(work, "rev-list", *args)
    return [ln for ln in out.split() if ln]


def _collected(work: Path, line: str) -> tuple:
    stats = sweep.ScanStats()
    blobs = sweep.collect_push_blobs(work, [line], "origin", stats)
    msgs = {b.path for b in blobs if b.source == "COMMIT-MSG"}
    return stats.commits, msgs


def _sweep_main(monkeypatch, tmp_path: Path, work: Path, line: str) -> int:
    monkeypatch.setattr(sweep, "REPO_ROOT", work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(line + "\n"))
    return sweep.main(["--pre-push", "origin", "--config-root", str(_armed_root(tmp_path))])


def _cred_main(monkeypatch, work: Path, line: str) -> int:
    monkeypatch.setattr(chs, "ROOT", work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(line + "\n"))
    return chs.main(["--pre-push", "origin"])


# --------------------------------------------------------------------------
# 1. The defect: the rewrite's already-advertised commits are rescanned
# --------------------------------------------------------------------------
def test_forced_update_across_a_rewrite_scans_only_the_new_commit(rewritten):
    work = rewritten["work"]
    new = _commit(work, "c.txt", _CLEAN_TEXT, "new on the rewrite")
    line = f"refs/heads/main {new} refs/heads/main {rewritten['old2']}"
    specs = sweep.resolve_push_ranges(work, [line], "origin")
    assert len(specs) == 1
    assert _rev_list(work, specs[0].args) == [new], (
        "the rewritten lineage the remote already advertises was rescanned"
    )
    count, msgs = _collected(work, line)
    assert msgs == {new[:12]} and count == 1


def test_forced_update_across_a_rewrite_no_longer_halts_on_public_history(
    rewritten, monkeypatch, tmp_path
):
    work = rewritten["work"]
    new = _commit(work, "c.txt", _CLEAN_TEXT, "new on the rewrite")
    line = f"refs/heads/main {new} refs/heads/main {rewritten['old2']}"
    assert _sweep_main(monkeypatch, tmp_path, work, line) == sweep.EXIT_CLEAN


def test_a_new_leak_on_top_of_the_rewrite_still_halts(rewritten, monkeypatch, tmp_path):
    """Positive control: the narrowed range still scans what is new."""
    work = rewritten["work"]
    new = _commit(work, "c.txt", _LEAK_TEXT, "new leak on the rewrite")
    line = f"refs/heads/main {new} refs/heads/main {rewritten['old2']}"
    assert _sweep_main(monkeypatch, tmp_path, work, line) == sweep.EXIT_HALT


def test_credential_scan_shares_the_narrowed_rewrite_range(rewritten, monkeypatch):
    work = rewritten["work"]
    _git(work, "checkout", "-q", "--detach", rewritten["rw1"])
    keyed = _commit(work, "k.txt", f'KEY = "{_FAKE_KEY}"\n', "historical key")
    _git(work, "checkout", "-q", "rw")
    _git(work, "merge", "-q", "--no-edit", "--no-verify", keyed)
    merged = _git(work, "rev-parse", "HEAD")
    _set_remote_refs(rewritten["remote"], {
        "refs/heads/main": rewritten["old2"], "refs/heads/rewritten": merged,
    })
    new = _commit(work, "c.txt", _CLEAN_TEXT, "new on the rewrite")
    line = f"refs/heads/main {new} refs/heads/main {rewritten['old2']}"
    assert _cred_main(monkeypatch, work, line) == chs.EXIT_CLEAN
    leak = _commit(work, "d.txt", f'KEY2 = "{_FAKE_KEY}"\n', "new key")
    line2 = f"refs/heads/main {leak} refs/heads/main {rewritten['old2']}"
    assert _cred_main(monkeypatch, work, line2) != chs.EXIT_CLEAN


# --------------------------------------------------------------------------
# 2. Unchanged: a fast-forward keeps the exact range and reads no ls-remote
# --------------------------------------------------------------------------
def test_fast_forward_keeps_the_exact_range_without_ls_remote(rewritten, monkeypatch):
    work = rewritten["work"]
    _git(work, "checkout", "-q", "-b", "ff", rewritten["old2"])
    tip = _commit(work, "e.txt", _CLEAN_TEXT, "fast-forward")

    def _boom(*_a, **_k):
        raise AssertionError("ls-remote read for a fast-forward push")

    monkeypatch.setattr(sweep, "remote_advertised", _boom)
    line = f"refs/heads/main {tip} refs/heads/main {rewritten['old2']}"
    specs = sweep.resolve_push_ranges(work, [line], "origin")
    assert [s.args for s in specs] == [[tip, "--not", rewritten["old2"]]]


def test_a_deletion_asks_no_ancestry_and_reads_no_ls_remote(rewritten, monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("a ref deletion publishes nothing; nothing to ask")

    monkeypatch.setattr(sweep, "remote_advertised", _boom)
    line = f"refs/heads/main {_Z} refs/heads/main {rewritten['old2']}"
    assert sweep.resolve_push_ranges(rewritten["work"], [line], "origin", is_ancestor=_boom) == []


def test_resolver_without_an_advertisement_keeps_todays_form():
    """advertised=None: a caller that cannot reach the remote scans MORE."""
    line = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}"
    spec = sweep.resolve_push_range(
        line, "origin", have=lambda s: True, advertised=None,
        is_ancestor=lambda old, new: False,
    )
    assert spec is not None and spec.args == ["a" * 40, "--not", "b" * 40]


def test_resolver_with_an_unknown_ancestry_keeps_todays_form():
    line = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}"
    spec = sweep.resolve_push_range(
        line, "origin", have=lambda s: True, advertised=["c" * 40],
        is_ancestor=lambda old, new: None,
    )
    assert spec is not None and spec.args == ["a" * 40, "--not", "b" * 40]


def test_resolver_on_a_rewrite_excludes_the_old_tip_and_the_advertisement():
    line = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}"
    spec = sweep.resolve_push_range(
        line, "origin", have=lambda s: True, advertised=["b" * 40, "c" * 40],
        is_ancestor=lambda old, new: False,
    )
    assert spec is not None
    assert spec.args == ["a" * 40, "^" + "b" * 40, "^" + "c" * 40]
    assert "--remotes=origin" not in spec.args


def test_resolver_on_a_fast_forward_ignores_the_advertisement():
    line = f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}"
    spec = sweep.resolve_push_range(
        line, "origin", have=lambda s: True, advertised=["c" * 40],
        is_ancestor=lambda old, new: True,
    )
    assert spec is not None and spec.args == ["a" * 40, "--not", "b" * 40]


# --------------------------------------------------------------------------
# 3. ls-remote failure: a rewrite falls back to MORE, a new ref still FAULTs
# --------------------------------------------------------------------------
def test_ls_remote_failure_on_a_rewrite_only_push_scans_the_exact_range(
    rewritten, tmp_path
):
    work = rewritten["work"]
    new = _commit(work, "c.txt", _CLEAN_TEXT, "new on the rewrite")
    _git(work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    line = f"refs/heads/main {new} refs/heads/main {rewritten['old2']}"
    specs = sweep.resolve_push_ranges(work, [line], "origin")
    assert [s.args for s in specs] == [[new, "--not", rewritten["old2"]]]
    assert set(_rev_list(work, specs[0].args)) == {new, rewritten["rw1"], rewritten["rw2"]}


def test_ls_remote_failure_with_a_new_ref_line_is_still_a_fault(rewritten, tmp_path):
    work = rewritten["work"]
    new = _commit(work, "c.txt", _CLEAN_TEXT, "new on the rewrite")
    _git(work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    lines = [
        f"refs/heads/main {new} refs/heads/main {rewritten['old2']}",
        f"refs/heads/topic {new} refs/heads/topic {_Z}",
    ]
    with pytest.raises(sweep.GitFault):
        sweep.resolve_push_ranges(work, lines, "origin")


def test_is_ancestor_reads_git_and_reports_unknown_for_a_missing_sha(rewritten):
    work = rewritten["work"]
    assert sweep._is_ancestor(work, rewritten["old1"], rewritten["old2"]) is True
    assert sweep._is_ancestor(work, rewritten["old2"], rewritten["rw2"]) is False
    assert sweep._is_ancestor(work, "e" * 40, rewritten["rw2"]) is None


def test_a_wedged_git_reads_absent_and_unknown_never_a_hang(monkeypatch, tmp_path):
    """S144-P-302: both ancestry questions pass a timeout, and a TimeoutExpired
    reads as absent / unknown (the scan-MORE direction), never an exception."""
    seen = []

    def wedged(cmd, **kw):
        seen.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    bind_subprocess(monkeypatch, sweep, run=wedged)
    assert sweep._has_object(tmp_path, "a" * 40) is False
    assert sweep._is_ancestor(tmp_path, "a" * 40, "b" * 40) is None
    assert seen == [sweep._SHORT_GIT_TIMEOUT_S] * 2
    assert all(isinstance(t, (int, float)) and t > 0 for t in seen)
