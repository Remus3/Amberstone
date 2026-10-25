"""pytest temp-dir hygiene for BOTH suites: the TEMP-1 basetemp guard and the
RM-878 per-run temp root.

TEMP-1 - refuse a ``--basetemp`` inside a Claude session scratchpad.
Why: MAIN measured 2026-10-09 that long-lived sessions passed ``--basetemp``
INSIDE the session scratchpad, one per run, so a scratchpad reached 8.5k
entries. pytest's retention (``pytest.ini``: ``tmp_path_retention_policy =
failed``, ``tmp_path_retention_count = 1``) does not reap an explicit basetemp
that changes per run, and MAIN's cleaner skips live sessions, so the copies
never went away. Temp file count is boot time on this box.
Rule: use the default tmp_path. If a run truly needs an explicit basetemp, use
the ONE fixed path ``<scratchpad>/pytest-basetemp`` - pytest clears it at the
start of each run, so a scratchpad holds at most one basetemp. Any other
basetemp inside a scratchpad is a usage error raised from
``pytest_configure`` (before any basetemp directory is created). A scratchpad
is the harness layout ``<..>/claude/<project>/<session>/scratchpad`` (names
compared case-insensitively). Because pytest ``rm_rf``s a given basetemp at
session start (``_pytest/tmpdir.py`` ``getbasetemp``), two runs sharing the
fixed path still collide; the default tmp_path below is the concurrent-safe
choice.

RM-878 - one temp root per run. pytest's default root is
``<temp>/pytest-of-<user>`` (``_pytest/tmpdir.py`` ``getbasetemp``): ONE
directory per user, shared by every pytest process of every tree and worktree
on the box. pytest's own retention sweep (``_pytest/pathlib.py``
``cleanup_numbered_dir``, run at exit) spares a numbered run dir only while it
holds a ``.lock`` (``ensure_deletable``: no lock means deletable), the lock is
taken only when ``keep != 0`` (``make_numbered_dir_with_cleanup``), and any
other actor that sweeps that root follows no lock at all - so a live run's
basetemp could vanish mid-run (LEDGER 1847: 145 setup ERRORs, each
``FileNotFoundError`` on the run's own ``pytest-146``). The fix keeps pytest's
design and only moves the ROOT: a top-level run claims a fresh
``<temp>/pytest-rc/<token>`` and points ``PYTEST_DEBUG_TEMPROOT`` (the variable
``getbasetemp`` reads) at it, so pytest's numbered dirs, lock and ``failed`` /
count-1 retention all run inside a root no other run sweeps.
  - Liveness: the claim holds ``<root>/.alive`` open for the run's life. On
    Windows an open file cannot be unlinked by another process; elsewhere the
    holder keeps an exclusive ``flock``. Either way the OS releases it when the
    process dies, killed or not.
  - xdist: workers get ``<controller basetemp>/popen-gwN`` from xdist and
    inherit the variable, so they and any nested pytest a test spawns share the
    controller's root. A worker never claims.
  - Reaping: at unconfigure a run removes its own root unless a failed test's
    tmp_path is kept in it; every new claim then removes the roots of dead runs
    (killed, or finished with failures), keeping the newest
    ``tmp_path_retention_count - 1`` of them, which is pytest's count-1 rule
    across roots. An unmarked root younger than ``GRACE_S`` is spared (it may be
    mid-claim); a link or junction is never followed.
  - The claim stands aside when the caller already chose (``--basetemp``, or
    ``PYTEST_DEBUG_TEMPROOT`` set by CI, a debugging run or an outer RC run)
    and when the system temp dir is inside a session scratchpad (TEMP-1); then
    pytest's default applies unchanged.

The rootdir ``conftest.py`` re-exports ``pytest_configure`` and
``pytest_unconfigure`` so both reach BOTH suites; an xdist worker is skipped by
both. Pinned by ``tests/test_pytest_basetemp_scratchpad_temp1.py`` (TEMP-1) and
``tests/test_pytest_per_run_temproot_rm878.py`` (RM-878).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest

FIXED_NAME = "pytest-basetemp"

TEMPROOT_VAR = "PYTEST_DEBUG_TEMPROOT"
RUN_BASE_NAME = "pytest-rc"
MARKER_NAME = ".alive"
GRACE_S = 60.0
_NUMBERED = re.compile(r"pytest-\d+")
_CLAIM = pytest.StashKey()  # the RunRoot this config claimed


def _scratchpad_root(path: Path):
    """Return the scratchpad ancestor (inclusive) of ``path``, or None."""
    chain = [path, *path.parents]
    for node in chain:
        if node.name.lower() != "scratchpad":
            continue
        ups = list(node.parents)
        if len(ups) >= 3 and ups[2].name.lower() == "claude":
            return node
    return None


def basetemp_problem(value):
    """Return a refusal message for ``value`` (a basetemp), or None if it is fine."""
    if not value:
        return None
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    root = _scratchpad_root(path)
    if root is None:
        return None
    rel = path.parts[len(root.parts):]
    if rel and rel[0].lower() == FIXED_NAME:
        return None
    return (
        "--basetemp inside a session scratchpad is refused (MAIN FIX TEMP-1): "
        "each run left a full tmp tree that is never reaped. Drop --basetemp "
        "(default tmp_path, retention failed/1), or use the ONE fixed path "
        f"<scratchpad>/{FIXED_NAME}, which pytest clears at the start of each run."
    )


# ---- RM-878: the per-run root --------------------------------------------------

class RunRoot:
    """A claimed per-run temp root and the open marker that proves its owner lives."""

    def __init__(self, path: Path, handle) -> None:
        self.path = path
        self._handle = handle

    def close(self) -> None:
        """Release the liveness marker (the root then reads as dead)."""
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None


def run_base(temp_dir=None) -> Path:
    """``<system temp>/pytest-rc``: the parent of every per-run root."""
    return Path(temp_dir or tempfile.gettempdir()).resolve() / RUN_BASE_NAME


def _hold(marker: Path):
    fh = open(marker, "w", encoding="ascii")  # noqa: SIM115 - held for the run
    try:
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        if os.name != "nt":
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise
    return fh


def claim_run_root(base: Path):
    """Create and hold a fresh run root under ``base``; None if that fails."""
    try:
        base.mkdir(parents=True, exist_ok=True)
        for _ in range(16):
            path = base / secrets.token_hex(3)
            try:
                path.mkdir()
            except FileExistsError:
                continue
            try:
                return RunRoot(path, _hold(path / MARKER_NAME))
            except OSError:
                _rmtree(path)
                return None
    except OSError:
        return None
    return None


def owner_alive(root: Path):
    """True if a live process holds ``root``'s marker, False if the marker is
    there but unheld (its owner is gone), None if there is no marker.

    On Windows the probe IS an unlink attempt, so a dead root loses its marker.
    """
    marker = root / MARKER_NAME
    if os.name == "nt":
        try:
            os.unlink(marker)
        except FileNotFoundError:
            return None
        except OSError:
            return True
        return False
    import fcntl
    try:
        fd = os.open(marker, os.O_RDONLY)
    except FileNotFoundError:
        return None
    except OSError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def _rmtree(path: Path) -> bool:
    """Remove a tree without following links, clearing read-only bits."""

    def _onexc(func, p, exc):
        if isinstance(exc, FileNotFoundError):
            return
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_onexc)
        else:  # pragma: no cover - RC runs 3.12+
            shutil.rmtree(path, onerror=lambda f, p, ei: _onexc(f, p, ei[1]))
    except OSError:
        pass
    return not os.path.lexists(path)


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())
    except OSError:
        return True


def sweep_dead_roots(base: Path, own=None, keep_dead: int = 0, now=None):
    """Remove dead run roots under ``base``, keeping the newest ``keep_dead``.

    A root is dead when its marker is unheld, or when it has no marker and is
    older than ``GRACE_S``. Live roots, ``own``, files and links are never
    touched. Returns the removed roots.
    """
    now = time.time() if now is None else now
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    dead = []
    for p in entries:
        if own is not None and p == own:
            continue
        try:
            if _is_link(p) or not p.is_dir():
                continue
            mtime = p.lstat().st_mtime  # before the probe, which may touch it
        except OSError:
            continue
        alive = owner_alive(p)
        if alive:
            continue
        if alive is None and now - mtime < GRACE_S:
            continue
        dead.append((mtime, p))
    dead.sort(key=lambda item: item[0], reverse=True)
    return [p for _, p in dead[max(keep_dead, 0):] if _rmtree(p)]


def _keeps_failures(root: Path) -> bool:
    """True if a numbered run dir in ``root`` holds anything but its lock."""
    for user_dir in root.glob("pytest-of-*"):
        try:
            runs = [r for r in user_dir.iterdir()
                    if _NUMBERED.fullmatch(r.name) and not _is_link(r) and r.is_dir()]
        except OSError:
            continue
        for run in runs:
            try:
                if any(e.name != ".lock" for e in run.iterdir()):
                    return True
            except OSError:
                return True
    return False


def release_run_root(claim: RunRoot, keep_failures: bool = True) -> bool:
    """Drop the marker; remove the root unless it keeps a failed test's dirs.
    Returns True if the root is gone."""
    claim.close()
    if keep_failures and _keeps_failures(claim.path):
        return False
    return _rmtree(claim.path)


def _retention_keep(config) -> int:
    """pytest's own ``keep`` (``tmpdir.py``): the count, or 0 under policy none."""
    try:
        count = int(config.getini("tmp_path_retention_count"))
        policy = config.getini("tmp_path_retention_policy")
    except (ValueError, TypeError):
        return 1
    return 0 if policy == "none" else max(count, 0)


def _claim_for(config) -> None:
    if getattr(config.option, "basetemp", None):
        return  # whoever named the basetemp owns it (TEMP-1)
    if os.environ.get(TEMPROOT_VAR):
        return  # the caller (CI, a debug run, an outer RC run) chose the root
    base = run_base()
    if _scratchpad_root(base) is not None:
        return  # never root per-run trees inside a session scratchpad
    claim = claim_run_root(base)
    if claim is None:
        return  # pytest falls back to its default root
    sweep_dead_roots(base, own=claim.path,
                     keep_dead=max(_retention_keep(config) - 1, 0))
    os.environ[TEMPROOT_VAR] = str(claim.path)
    config.stash[_CLAIM] = claim


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if hasattr(config, "workerinput"):
        return
    problem = basetemp_problem(getattr(config.option, "basetemp", None))
    if problem:
        raise pytest.UsageError(problem)
    _claim_for(config)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    claim = config.stash.get(_CLAIM, None)
    if claim is None:
        return
    del config.stash[_CLAIM]
    if os.environ.get(TEMPROOT_VAR) == str(claim.path):
        del os.environ[TEMPROOT_VAR]
    release_run_root(claim, keep_failures=_retention_keep(config) > 0)
