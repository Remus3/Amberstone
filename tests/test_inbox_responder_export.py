"""Arms for the responder's tracked-only export - the spawn cwd.

The PUBLIC-PROJECTION PRINCIPLE says every byte the spawned session can read
must already be reachable from `origin/main`. The checkout is not such a set:
it carries gitignored secrets, other parties' inbox notes and thousands of
reflog-only commits. So the spawn cwd is an EXPORT of `origin/main`, and these
arms are what makes that claim checkable rather than asserted.

The oversize arm passes its OWN small `max_bytes` (4096) and a stub runner
returning 4097 bytes. A fixture sized from the constant under test is an
amplifier: it would pass against any constant, including a mutated one, and
the 2 GiB default would have to be allocated to redden.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.inbox_responder_export import (  # noqa: E402
    ExportFailed,
    ensure_export,
    export_is_clean,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "tools" / "inbox_responder_export.py"


# ---------------------------------------------------------------- stub procs

@dataclass
class StubResult:
    """Duck-typed stand-in for `procs.ProcResult` (S0 owns the real one)."""

    exit_code: int | None = 0
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    survived_kill: bool = False
    kill_skipped: bool = False
    wall_ms: int = 1
    # Matches procs.ProcResult: the seam records the exception CLASS NAME, not
    # the exception object. A stub carrying an object here would be a shape the
    # production runner never produces.
    exc: str | None = None


@dataclass
class StubRunner:
    """Returns a canned result per git verb; records every call."""

    results: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def __call__(self, args, *, timeout_s):
        self.calls.append((list(args), timeout_s))
        return self.results.get(args[0], StubResult())


@dataclass
class RealRunner:
    """Issues real git processes, exactly as the runner's gate-8 closure does:
    it prepends the git executable and binds cwd, so the module under test
    never names git, PATH or any environment."""

    repo_root: Path
    calls: list = field(default_factory=list)

    def __call__(self, args, *, timeout_s):
        self.calls.append((list(args), timeout_s))
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.repo_root),
            capture_output=True,
            timeout=timeout_s,
        )
        return StubResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A real repo with an `origin`, a pushed main, gitignored content and one
    unpushed local commit. The path carries a real space on purpose."""
    origin = tmp_path / "origin bare.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    work = tmp_path / "work repo"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "rc@example.invalid")
    _git(work, "config", "user.name", "RC Test")
    _git(work, "config", "commit.gpgsign", "false")

    (work / ".gitignore").write_text("secret.txt\nmoon_sync_inbox/\n", encoding="ascii")
    (work / "tracked.txt").write_text("public\n", encoding="ascii")
    (work / "secret.txt").write_text("sk-not-public\n", encoding="ascii")
    (work / "moon_sync_inbox").mkdir()
    (work / "moon_sync_inbox" / "note.md").write_text("someone else's note\n", encoding="ascii")
    _git(work, "add", ".gitignore", "tracked.txt")
    _git(work, "commit", "-m", "public tree")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-u", "origin", "main")

    (work / "unpushed.txt").write_text("not public yet\n", encoding="ascii")
    _git(work, "add", "unpushed.txt")
    _git(work, "commit", "-m", "local only")
    return work


def _export_root(state_root: Path) -> Path:
    return state_root / "ops" / "runtime" / "responder_export"


def _sha_dirs(state_root: Path) -> list:
    root = _export_root(state_root)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


# ------------------------------------------------------------- happy arms

def test_export_is_tracked_only_and_clean(fixture_repo: Path, tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = RealRunner(fixture_repo)

    out = ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    assert out.is_dir()
    assert out.parent == _export_root(state_root)
    assert re.fullmatch(r"[0-9a-f]{12}", out.name)

    head = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=str(fixture_repo), capture_output=True, check=True,
    ).stdout.decode("ascii").strip()
    assert out.name == head[:12]

    assert (out / "tracked.txt").is_file()
    assert (out / ".gitignore").is_file()
    assert not (out / "secret.txt").exists()
    assert not (out / "moon_sync_inbox").exists()
    assert not (out / "unpushed.txt").exists()
    assert not (out / ".git").exists()

    assert export_is_clean(out, fixture_repo, runner=runner) is True
    # One process per path: `-q` is only valid with a single pathname, so a
    # batched call would exit 128 and read as "clean" for every path at once.
    checks = [c[0] for c in runner.calls if c[0][0] == "check-ignore"]
    assert checks == [["check-ignore", "-q", "--", ".gitignore"],
                      ["check-ignore", "-q", "--", "tracked.txt"]]


def test_export_is_clean_says_false_when_an_ignored_path_is_present(
    fixture_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    runner = RealRunner(fixture_repo)
    out = ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    (out / "secret.txt").write_text("planted\n", encoding="ascii")

    assert export_is_clean(out, fixture_repo, runner=runner) is False


def test_cache_hit_runs_only_rev_parse(fixture_repo: Path, tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = RealRunner(fixture_repo)

    first = ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)
    assert [c[0][0] for c in runner.calls] == ["rev-parse", "archive"]

    second = ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)
    assert second == first
    assert [c[0][0] for c in runner.calls] == ["rev-parse", "archive", "rev-parse"]


def test_prune_keeps_the_last_two_exports(fixture_repo: Path, tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = RealRunner(fixture_repo)
    final = ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    root = _export_root(state_root)
    newer = root / ("a" * 12)
    older = root / ("b" * 12)
    for extra in (newer, older):
        extra.mkdir()
        (extra / "stale.txt").write_text("old export\n", encoding="ascii")
    now = os.stat(final).st_mtime
    os.utime(newer, (now + 100, now + 100))
    os.utime(older, (now - 100, now - 100))

    ensure_export(fixture_repo, state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    assert final.is_dir()
    assert newer.is_dir()
    assert not older.exists()
    assert len(_sha_dirs(state_root)) == 2


def test_a_sibling_that_won_the_rename_is_adopted_not_clobbered(tmp_path: Path) -> None:
    """The slot is not held around the export, so two cycles can export the
    same sha at once. The rename is atomic, so a `final` that already exists is
    a COMPLETE sibling export - adopt it rather than failing the cycle."""
    state_root = tmp_path / "state"
    sha12 = "c0ffee123456"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        member = tarfile.TarInfo("tracked.txt")
        member.size = 7
        tar.addfile(member, io.BytesIO(b"public\n"))

    class RacingRunner(StubRunner):
        def __call__(self, args, *, timeout_s):
            result = super().__call__(args, timeout_s=timeout_s)
            if args[0] == "archive":
                sibling = _export_root(state_root) / sha12
                sibling.mkdir(parents=True)
                (sibling / "tracked.txt").write_text("sibling won\n", encoding="ascii")
            return result

    runner = RacingRunner({
        "rev-parse": StubResult(stdout=b"c0ffee123456f890abcdef1234567890abcdef12\n"),
        "archive": StubResult(stdout=buf.getvalue()),
    })

    out = ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    assert out.name == sha12
    assert (out / "tracked.txt").read_text(encoding="ascii") == "sibling won\n"
    assert _sha_dirs(state_root) == [sha12]


def test_a_rename_oserror_with_no_winner_still_raises(tmp_path: Path, monkeypatch) -> None:
    """The adopt branch must not swallow a real rename fault.

    It catches OSError rather than FileExistsError, because the errno for
    renaming onto an existing non-empty directory is not portable (Windows
    raises FileExistsError, POSIX raises ENOTEMPTY / ENOTDIR / EEXIST) - which
    is why catching FileExistsError alone was green on Windows and red in Linux
    CI. That widening is only safe if the branch decides on the STATE of the
    destination, so this arm drives an OSError where NO winner exists and
    asserts the export still fails loudly.
    """
    state_root = tmp_path / "state"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        member = tarfile.TarInfo("tracked.txt")
        member.size = 5
        tar.addfile(member, io.BytesIO(b"ours\n"))
    runner = StubRunner({
        "rev-parse": StubResult(stdout=b"c0ffee123456f890abcdef1234567890abcdef12\n"),
        "archive": StubResult(stdout=buf.getvalue()),
    })

    def exploding_rename(src, dst):
        raise OSError(39, "Directory not empty")

    import tools.inbox_responder_export as export_mod

    monkeypatch.setattr(export_mod.os, "rename", exploding_rename)

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    assert caught.value.detail == "exc:OSError"
    assert _sha_dirs(state_root) == []


# ------------------------------------------------------------- failure arms

def test_no_origin_main_against_a_real_repo_without_a_remote(tmp_path: Path) -> None:
    work = tmp_path / "no remote repo"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "rc@example.invalid")
    _git(work, "config", "user.name", "RC Test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "a.txt").write_text("a\n", encoding="ascii")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-m", "only local")

    state_root = tmp_path / "state"
    with pytest.raises(ExportFailed) as caught:
        ensure_export(work, state_root, runner=RealRunner(work), timeout_s=60, max_bytes=4096 * 1024)

    assert caught.value.detail == "no-origin-main"
    assert _sha_dirs(state_root) == []


def test_no_origin_main_when_rev_parse_exits_nonzero(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = StubRunner({"rev-parse": StubResult(exit_code=128, stderr=b"fatal: bad revision\n")})

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == "no-origin-main"
    assert [c[0][0] for c in runner.calls] == ["rev-parse"]
    assert _sha_dirs(state_root) == []


def test_oversize_archive_never_reaches_disk(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = StubRunner({
        "rev-parse": StubResult(stdout=b"c0ffee1234567890abcdef1234567890abcdef12\n"),
        "archive": StubResult(stdout=b"x" * 4097),
    })

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == "oversize"
    assert [c[0][0] for c in runner.calls] == ["rev-parse", "archive"]
    assert not _export_root(state_root).exists()


def test_a_payload_at_the_limit_is_not_oversize(tmp_path: Path) -> None:
    """The comparison is strictly greater-than: 4096 bytes under a 4096 cap is
    accepted (and then fails on its own merits as a tar), so the oversize arm
    above is pinning the boundary, not merely 'something went wrong'."""
    state_root = tmp_path / "state"
    runner = StubRunner({
        "rev-parse": StubResult(stdout=b"c0ffee1234567890abcdef1234567890abcdef12\n"),
        "archive": StubResult(stdout=b"x" * 4096),
    })

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail != "oversize"
    assert caught.value.detail.startswith("exc:")


def test_timeout_on_rev_parse(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = StubRunner({"rev-parse": StubResult(exit_code=None, timed_out=True)})

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == "timeout"
    assert [c[0][0] for c in runner.calls] == ["rev-parse"]
    assert not _export_root(state_root).exists()


def test_timeout_on_archive(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = StubRunner({
        "rev-parse": StubResult(stdout=b"c0ffee1234567890abcdef1234567890abcdef12\n"),
        "archive": StubResult(exit_code=None, timed_out=True),
    })

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == "timeout"
    assert not _export_root(state_root).exists()


def test_runner_exception_is_reported_as_exc(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runner = StubRunner({"rev-parse": StubResult(exit_code=None, exc="OSError")})

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == "exc:OSError"
    assert not _export_root(state_root).exists()


def test_runner_exception_detail_matches_the_real_procs_seam(tmp_path: Path) -> None:
    """The stub above must carry the shape `procs.popen_capture` really returns.

    Drives a REAL ProcResult - built by spawning a binary that does not exist,
    so no process is created - through the same failure path. Guards the
    `exc:str` regression, where `type(res.exc).__name__` on an already-string
    field filed every runner fault under one meaningless detail.
    """
    from tools import inbox_responder_procs as procs

    real = procs.popen_capture(
        ["C:\\this-binary-does-not-exist-rc-responder.exe", "rev-parse"],
        cwd=str(tmp_path),
        env={},
        stdin_bytes=b"",
        timeout_s=5,
        kill_budget=procs.KillBudget(1),
    )
    assert isinstance(real.exc, str), "procs records the class name, not the object"

    state_root = tmp_path / "state"

    def runner(_args, *, timeout_s):  # noqa: ARG001 - signature parity with the seam
        return real

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096)

    assert caught.value.detail == f"exc:{real.exc}"
    assert caught.value.detail != "exc:str"


def test_crafted_link_entry_is_rejected_by_the_data_filter(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        member = tarfile.TarInfo("tracked.txt")
        member.size = 7
        tar.addfile(member, io.BytesIO(b"public\n"))
        link = tarfile.TarInfo("escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../escape.txt"
        link.size = 0
        tar.addfile(link)

    state_root = tmp_path / "state"
    runner = StubRunner({
        "rev-parse": StubResult(stdout=b"c0ffee1234567890abcdef1234567890abcdef12\n"),
        "archive": StubResult(stdout=buf.getvalue()),
    })

    with pytest.raises(ExportFailed) as caught:
        ensure_export(tmp_path / "repo", state_root, runner=runner, timeout_s=60, max_bytes=4096 * 1024)

    assert caught.value.detail.startswith("exc:")
    assert "escape.txt" not in caught.value.detail
    assert not (tmp_path / "escape.txt").exists()
    assert _sha_dirs(state_root) == []
    root = _export_root(state_root)
    assert not root.exists() or list(root.iterdir()) == []


# ------------------------------------------------------------------- census

def test_module_carries_no_literal_subprocess_call() -> None:
    """Every git process goes through the injected runner. The console-flash
    guard lists only `inbox_responder_procs.py`, and it FAILS a listed file
    with no literal spawn - so a literal call here would have to be listed,
    and listing it would redden that guard."""
    source = MODULE_PATH.read_text(encoding="ascii")
    assert "subprocess" not in source
    assert "os.environ" not in source
