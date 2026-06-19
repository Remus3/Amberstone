"""First safe slice of the D1 full de-dup: pin _build_expected determinism.

Before un-tracking the 362-file Share/src mirror and switching CI from a
`--check` drift gate to a build-time generate step, we must prove the generator
is deterministic AND already byte-identical to what is committed. This test is
the safety net: it is pure (no git, no network, no outward gist surface), so it
ships safely on its own as the foundation slice.

The de-dup is FORBIDDEN to proceed until this is green and stays green:
  1. _build_expected() returns the same bytes on repeated calls (deterministic).
  2. The committed on-disk Share/src already matches it (_check == 0 drift).
  3. Every tracked Share/src path is reproduced by the generator (no committed
     file falls outside the generate set - that would be silently dropped when
     the directory is un-tracked and rebuilt).

(3) is the load-bearing new invariant: today --check tolerates extra on-disk
files only via the documented pyc/log skip. Once Share/src is rebuilt from
scratch at every checkout, ANY tracked path the generator does not emit would
vanish. This test makes that gap fail loudly now, while the files still exist.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools import ds_share_sync as sync

# Relpaths under Share/src that are legitimately NOT part of the deterministic
# generate set (gitignored run-artifacts the --check mode already skips). Keep
# in lock-step with sync._check's skip predicate (pyc / __pycache__ / *.log /
# logs dir). If a real source file ever lands here it must be added to the
# generator, not to this allowlist.
def _is_artifact(rel: str) -> bool:
    parts = rel.split("/")
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or "logs" in parts
        or rel.endswith(".pyc")
        or rel.endswith(".log")
    )


def test_build_expected_is_deterministic():
    """Same input -> same output: two generations are byte-identical."""
    first = sync._build_expected()
    second = sync._build_expected()
    assert first == second
    # Sanity: the mirror is non-trivial (regression tripwire if it collapses).
    assert len(first) > 300


def test_committed_share_src_matches_generator():
    """The committed on-disk Share/src has zero drift from the generator.

    _check returns the count of drifted paths; 0 means the deterministic
    rebuild is byte-identical to what is checked in - the precondition that
    makes un-tracking + regenerate-at-checkout safe.
    """
    expected = sync._build_expected()
    assert sync._check(expected) == 0


def test_every_tracked_src_path_is_reproduced():
    """Every git-tracked Share/src/<path> is emitted by _build_expected().

    Guards the un-tracking step: a committed source file the generator does not
    reproduce would be silently lost when Share/src is rebuilt from scratch.
    """
    repo = Path(sync._REPO)
    out = subprocess.run(
        ["git", "ls-files", "Share/src"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    )
    tracked = [
        ln.strip()[len("Share/src/"):]
        for ln in out.stdout.splitlines()
        if ln.strip().startswith("Share/src/")
    ]
    assert tracked, "expected tracked Share/src files (the mirror is committed today)"

    expected = sync._build_expected()
    missing = [
        rel for rel in tracked
        if not _is_artifact(rel) and rel not in expected
    ]
    assert not missing, (
        "tracked Share/src paths NOT reproduced by _build_expected (would be "
        f"lost on regenerate-at-checkout): {missing}"
    )


def test_is_transient_skips_pytest_cache():
    """The transient-artifact skip predicate excludes .pytest_cache as well as
    __pycache__ / *.pyc (slice-3: the pytest cache dir is gitignored and must
    never enter the deterministic generate set)."""
    assert sync._is_transient(Path("agents/daemon_slayer/tests/.pytest_cache/v/cache/lastfailed"))
    assert sync._is_transient(Path("agents/daemon_slayer/__pycache__/dps.cpython-314.pyc"))
    assert sync._is_transient(Path("x/y.pyc"))
    # Real source must NOT be skipped (no over-broad match).
    assert not sync._is_transient(Path("agents/daemon_slayer/dps.py"))
    assert not sync._is_transient(Path("agents/daemon_slayer/tests/test_dps.py"))


def test_build_expected_excludes_pytest_cache():
    """_build_expected emits no .pytest_cache path even when one exists in the
    live engine dir (slice-3 regression: rglob picked them up because _is_pyc
    skipped only __pycache__/.pyc, leaking 5 transient paths into the mirror)."""
    expected = sync._build_expected()
    leaked = [rel for rel in expected if ".pytest_cache" in rel.split("/")]
    assert not leaked, f"transient .pytest_cache paths leaked into the generate set: {leaked}"
