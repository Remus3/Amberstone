"""ops/loop/lane_launcher.py - a REUSED lane worktree keeps pre-pin CRLF (RM-343).

WHAT WAS ACTUALLY WRONG, measured 2026-09-06 rather than inherited from the row.
The filed row reads "every lane WORKTREE materializes 1884 LF-normalized tracked
files with CRLF", which puts the blame on ``git worktree add``. That is NOT what
happens. A fresh ``git worktree add`` today produces LF and passes
``tests/test_text_line_endings.py`` with zero files reported - proven by doing it.

The real mechanism is STALENESS, and it lives on the reuse path here:

  * EOL conversion is decided at MATERIALIZATION time, by the ``.gitattributes``
    in force at that moment. ``core.autocrlf=true`` on this fleet (it comes from
    the SYSTEM gitconfig, ``C:/Program Files/Git/etc/gitconfig``, not from
    ``.git/config``) writes CRLF for every tracked text path not pinned
    ``eol=lf``.
  * ``fa0e7ea74`` (2026-09-03, RM-284 follow-on) widened the pin from ``.py`` and
    ``.md`` to ``.json``, ``.js``, ``.css`` and 13 more. Worktrees materialized
    BEFORE that commit already had those files on disk as CRLF.
  * Updating the branch afterwards does not fix them. Git only rewrites a
    working-tree file when its CONTENT changes, and the blob was LF all along -
    so the file is never re-materialized and keeps its CRLF forever.
  * ``git status`` reports the tree CLEAN throughout, because git normalizes
    CRLF to LF on read for a ``text``-marked path. The condition is invisible to
    every git-based check and to the pre-commit gate.

``ensure_worktree`` returns a reused worktree untouched, which is deliberate and
must stay that way (a worktree per fire would leak a directory and a branch on
every click). That correct decision is also what makes the staleness permanent:
nothing in the launcher ever re-materializes a lane checkout, so every future
``.gitattributes`` pin widening strands every existing lane the same way.

WHY THE FILTER IS ASKED OF GIT AND NEVER INFERRED FROM A SUFFIX. The LFS
payloads under ``data/daemon_slayer/laning_scenarios/`` match ``*.json`` but
carry ``-text`` from the LFS rule, so git deliberately does not convert them.
A suffix filter reports all 7 as offenders on a correct tree - it did exactly
that to the first draft of this cycle's probe, and the same trap produced a
false failure on the first run of ``tests/test_text_line_endings.py``
(memory ``feedback_data_filter_vs_evaluator_filter``). The evaluator filter has
to be ``git check-attr``, requiring BOTH ``text: set`` and ``eol: lf``.

NOT A COMMIT OF 1884 PATHS. The row explicitly forbids closing this by
re-materializing the tracked files inside a feature branch, and this does not:
re-materializing changes no blob, so ``git status`` stays clean and nothing is
staged. The repair happens in the working tree at lane-fire time.
"""
from __future__ import annotations

import importlib
import os
import subprocess

import pytest

launcher = importlib.import_module("ops.loop.lane_launcher")

CRLF_JSON = b'{\r\n  "a": 1\r\n}\r\n'
LF_JSON = b'{\n  "a": 1\n}\n'


def _env() -> dict:
    return {**os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _run(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True, env=_env())


@pytest.fixture
def repo(tmp_path):
    """A real git repo pinning *.json eol=lf, with an LFS-shaped -text sibling."""
    r = tmp_path / "repo"
    r.mkdir()
    _run(["init", "-q"], r)
    # The pin under test, plus the -text rule that must keep winning.
    (r / ".gitattributes").write_bytes(
        b"*.json text eol=lf\n"
        b"payload/*.json -text\n"
    )
    (r / "a.json").write_bytes(LF_JSON)
    (r / "b.json").write_bytes(LF_JSON)
    (r / "payload").mkdir()
    # Committed WITH CRLF and marked -text, exactly like the LFS payloads.
    (r / "payload" / "keep.json").write_bytes(CRLF_JSON)
    _run(["add", "-A"], r)
    _run(["commit", "-qm", "init"], r)
    return r


def _query(args, cwd) -> str:
    """Run a read-only `git` query and return stdout, or FAIL if git failed.

    RM-393: the callers below assert on emptiness, and a failing `git` also
    yields an empty stdout with the diagnostic on stderr, where
    `capture_output` swallows it. Inspecting the return code is what separates
    "git ran and saw no change" from "git failed and printed nothing".
    `check=True` would do it too, but the message an `AssertionError` carries
    here names the command AND the swallowed stderr, which is the whole
    diagnostic a caller would otherwise lose.
    """
    p = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, env=_env())
    assert p.returncode == 0, (
        f"git {' '.join(args)} failed with rc={p.returncode} in {cwd} - an "
        f"empty stdout here is a FAILURE, not an empty answer. stderr: "
        f"{p.stderr.strip()!r}")
    return p.stdout


def _status(cwd) -> str:
    return _query(["status", "--porcelain"], cwd)


def _content_diff(cwd) -> str:
    """What git sees as a real CONTENT change, filters applied."""
    return _query(["diff", "--name-only"], cwd)


# --------------------------------------------------------------- the query helpers
def test_the_query_helpers_refuse_to_read_a_failure_as_an_empty_answer(tmp_path):
    """RM-393: an empty stdout must never be reported as "git saw no change".

    Both helpers consume `stdout` from a `git` spawn. When git FAILS it exits
    non-zero with a zero-length stdout and the diagnostic on stderr, which
    `capture_output` swallows - so every consumer below that asserts against
    `""` would pass for the wrong reason. That is not a live false-GREEN today;
    git works here and those arms pass honestly. It is an assertion that cannot
    fail for the reason it exists to catch, and this arm is what makes it able
    to.

    The failure is manufactured with a `.git` gitfile pointing at a path that
    does not exist, which exits 128 no matter what sits above `tmp_path` - a
    plain non-repo directory would depend on no ancestor being a repo.
    """
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_bytes(b"gitdir: nowhere\n")

    with pytest.raises(AssertionError, match="git status --porcelain"):
        _status(broken)
    with pytest.raises(AssertionError, match="git diff --name-only"):
        _content_diff(broken)


def test_the_query_helpers_still_report_a_genuine_empty_answer(repo):
    """Positive control: the gate above must not turn "no change" into a raise.

    Without this, both helpers could satisfy the arm above by raising
    unconditionally, and every emptiness assertion in this module would go red
    for a new wrong reason instead of the old one.
    """
    assert _status(repo) == "", "a clean committed repo has no porcelain output"
    assert _content_diff(repo) == "", "a clean committed repo has no content diff"


# --------------------------------------------------------------- the invisibility
def test_a_crlf_pinned_file_is_content_identical_to_its_blob(repo):
    """The property that makes this defect survive every content-based check.

    If this ever fails, the whole row is moot - git would be reporting a real
    change and no separate repair would be needed.
    """
    (repo / "a.json").write_bytes(CRLF_JSON)
    assert _content_diff(repo) == "", (
        "git normalizes CRLF to LF on read for a text-marked path, so a "
        "CRLF-only difference must NOT read as a content change")


def test_git_status_is_the_WRONG_oracle_for_this_condition(repo):
    """Measured 2026-09-06, and it is why the repair must not filter on status.

    `git status` consults cached stat info, and a CRLF rewrite changes the file
    SIZE - so status reports ` M` for a file whose filtered content is
    byte-identical to its blob, and keeps reporting it on a second run. Using
    status as the "is this file dirty" filter would therefore skip every file
    this repair exists to fix, and the fix would ship inert.

    A long-lived worktree whose index stat cache has since been refreshed
    reports CLEAN instead - which is what the real lane worktrees show, and why
    the condition is invisible there. Both readings are the same content fact;
    only `git diff` reports it honestly in both trees.
    """
    (repo / "a.json").write_bytes(CRLF_JSON)
    assert _status(repo).strip() == "M a.json", (
        "if git status ever stops reporting a CRLF-only file as modified, the "
        "warning in this test is obsolete - but never switch the repair filter "
        "to status on the strength of that")
    assert _content_diff(repo) == "", "git diff must still see no content change"


def _materialize_stale(repo, rel: str) -> None:
    """Reproduce a pre-pin materialization faithfully. This distinction is the
    whole reason the first version of this fix shipped INERT against real trees.

    Writing CRLF alone leaves the index STAT stale, and git then happily rewrites
    the file on the first `checkout-index -f`. That is NOT what a real stale
    worktree looks like. `git add` records the CRLF file's stat against the
    unchanged LF blob - content identical, `git status` CLEAN, and git therefore
    convinced the file is up to date. In that state `checkout-index -f` returns 0
    and does NOTHING, and so does
    `git checkout --pathspec-from-file` (both measured 2026-09-06 on
    C:/rc-worktrees/rc-lane-ds at git 2.53.0). Only deleting the file first
    forces git to write it.
    """
    (repo / rel).write_bytes(CRLF_JSON)
    _run(["add", rel], repo)


def test_repair_is_not_fooled_by_a_matching_index_stat(repo):
    """The regression that a naive `checkout-index -f` passes and reality fails.

    Measured: against the five real lane worktrees the first implementation
    reported `repaired=1916` and a re-probe immediately found the same 1916 still
    stale - a returncode of 0 with zero effect.
    """
    _materialize_stale(repo, "a.json")
    assert _status(repo) == "", \
        "the real condition reads CLEAN to git - that is why it survives"
    assert launcher.renormalize_eol(repo) == ["a.json"]
    assert (repo / "a.json").read_bytes() == LF_JSON, \
        "a repair that returns paths it did not actually rewrite is worse than " \
        "no repair - it reports success and leaves the tree stale"


def test_repair_is_idempotent_against_a_real_stale_shape(repo):
    """A second pass must find nothing left, which is what proves the first worked."""
    _materialize_stale(repo, "a.json")
    _materialize_stale(repo, "b.json")
    assert sorted(launcher.renormalize_eol(repo)) == ["a.json", "b.json"]
    assert launcher.renormalize_eol(repo) == [], "residual after repair must be 0"


# --------------------------------------------------------------- detection + repair
def test_renormalize_is_a_noop_on_a_clean_worktree(repo):
    assert launcher.renormalize_eol(repo) == []


def test_renormalize_repairs_a_crlf_pinned_file(repo):
    (repo / "a.json").write_bytes(CRLF_JSON)
    repaired = launcher.renormalize_eol(repo)
    assert repaired == ["a.json"]
    assert (repo / "a.json").read_bytes() == LF_JSON, \
        "the repaired file must be LF on disk, matching its blob byte for byte"


def test_renormalize_reports_every_offender_not_just_the_first(repo):
    (repo / "a.json").write_bytes(CRLF_JSON)
    (repo / "b.json").write_bytes(CRLF_JSON)
    assert sorted(launcher.renormalize_eol(repo)) == ["a.json", "b.json"]
    assert (repo / "b.json").read_bytes() == LF_JSON


# --------------------------------------------------------------- the evaluator filter
def test_a_minus_text_payload_with_crlf_is_left_alone(repo):
    """A suffix filter would 'repair' this and corrupt an LFS payload.

    payload/keep.json matches *.json but carries -text, so git does not convert
    it and its CRLF is CORRECT. This is the trap that made a suffix-filtered
    probe report 7 offenders against a clean tree.
    """
    before = (repo / "payload" / "keep.json").read_bytes()
    assert b"\r\n" in before
    assert launcher.renormalize_eol(repo) == []
    assert (repo / "payload" / "keep.json").read_bytes() == before


# --------------------------------------------------------------- safety
def test_renormalize_never_discards_uncommitted_work(repo):
    """A file git DOES see as modified must never be re-materialized.

    Re-materializing restores the blob, so doing this to genuinely edited work
    would silently delete it. The CRLF-only case is safe precisely because git
    reports it clean; anything git reports dirty is out of scope by definition.
    """
    edited = b'{\r\n  "a": 2,\r\n  "mine": true\r\n}\r\n'
    (repo / "b.json").write_bytes(edited)
    assert _content_diff(repo).strip() == "b.json", \
        "b.json should read as a real content change to git"
    assert launcher.renormalize_eol(repo) == []
    assert (repo / "b.json").read_bytes() == edited, \
        "uncommitted work must survive untouched"


def test_renormalize_repairs_the_clean_file_beside_a_dirty_one(repo):
    """Skipping the dirty file must not abandon the rest of the tree."""
    (repo / "a.json").write_bytes(CRLF_JSON)
    (repo / "b.json").write_bytes(b'{\r\n  "a": 2,\r\n  "mine": true\r\n}\r\n')
    assert launcher.renormalize_eol(repo) == ["a.json"]
    assert (repo / "a.json").read_bytes() == LF_JSON


def test_renormalize_never_raises_when_git_fails(repo, monkeypatch):
    """A repair failure must not kill the lane - it is a cleanup, not a gate."""
    monkeypatch.setattr(launcher, "_git",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert launcher.renormalize_eol(repo) == []


def test_renormalize_refuses_a_path_that_is_not_a_worktree(tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert launcher.renormalize_eol(plain) == []


# --------------------------------------------------------------- the reuse path
def test_ensure_worktree_repairs_a_stale_reused_worktree(repo, tmp_path):
    """The integration: the reuse branch is where the staleness lives."""
    base = tmp_path / "wts"
    wt = launcher.ensure_worktree("queue", base=base, root=repo)
    assert (wt / "a.json").read_bytes() == LF_JSON

    # Manufacture exactly what a pre-pin materialization leaves behind.
    (wt / "a.json").write_bytes(CRLF_JSON)
    assert _content_diff(wt) == "", "the stale state carries no content change"

    again = launcher.ensure_worktree("queue", base=base, root=repo)
    assert again == wt, "reuse must still reuse - do not fork a worktree"
    assert (wt / "a.json").read_bytes() == LF_JSON, \
        "a reused worktree must be re-materialized against current attributes"


def test_ensure_worktree_still_reuses_and_does_not_recreate(repo, tmp_path):
    """Guards the guard: the repair must not turn reuse into re-creation."""
    base = tmp_path / "wts"
    first = launcher.ensure_worktree("queue", base=base, root=repo)
    marker = first / "untracked_marker.txt"
    marker.write_text("survives", encoding="utf-8")
    second = launcher.ensure_worktree("queue", base=base, root=repo)
    assert second == first
    assert marker.is_file(), \
        "reuse must keep the existing checkout, untracked files included"
