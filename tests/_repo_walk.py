"""Shared repo-root enumeration for tests/ guards that sweep the whole tree.

Why this module exists
----------------------
Ten guards under ``tests/`` walk the REPO ROOT rather than a subdirectory, and
each one grew its own skip set by hand. Measured 2026-09-07 the sets disagree:
four of the ten skip ``_archive``/``.git``/``node_modules`` but NOT ``.claude``,
and none of those four skip ``python-embed`` (1842 .py files on disk, ZERO of
them tracked) or ``moon_sync_inbox`` (51 .py files, gitignored, sibling-repo
mail). A guard whose needle happens not to appear in vendored bytes is green by
luck, not by construction - and the day a worktree, an embedded interpreter or
an inbound payload does carry the needle, the guard fires on code the repo does
not own.

Ground truth for "what is a worktree here", probed rather than assumed
---------------------------------------------------------------------
``git worktree list`` puts every live lane worktree OUTSIDE the checkout, under
``C:/rc-worktrees/rc-lane-<name>`` (plus ``C:/rc-worktrees/rm343-base``), so the
common case does NOT nest. But ``.claude/worktrees/`` exists in the repo root
(empty at probe time) and is the in-tree convention, and
``moon_sync_inbox/from-CS-verbatim/.claude`` is a nested sibling-repo payload.
Both nest, so both are excluded by segment name here.

Relative, never absolute
------------------------
Segment matching runs against the path RELATIVE to ``root``. Matching absolute
parts is a live trap: when the checkout ITSELF lives under
``.claude/worktrees/<id>/`` every file has ``.claude`` in ``p.parts`` and the
walker returns nothing - which reads exactly like a clean tree. The comment at
``tests/test_target_state_caller_p1l4.py:198`` records that same trap.

Empty is never clean
--------------------
An empty enumeration and a spotless repo produce the identical verdict in every
guard that consumes this module, so the walker refuses to be silently vacuous:
``self_check()`` proves it still reaches known files, and
``tests/test_repo_walk.py`` runs it. Call ``self_check()`` from any guard that
wants the proof inline.

Tracked-set primary, directory skips as backstop
------------------------------------------------
``git ls-files`` is the authority - "not tracked by git" already removes
``python-embed``, ``moon_sync_inbox``, ``_scratch``, ``__pycache__``, every
nested worktree's ignored files and most build output. The explicit
``EXCLUDED_DIRS`` set is kept anyway so the walker still behaves sanely when git
is absent, the checkout is not a work tree, or the call fails - see
``tracked_relpaths()``, which returns ``None`` rather than an empty set on
failure so a git error can never masquerade as "nothing is tracked".

Scoped, never rglob-then-filter
-------------------------------
The first version did ``base.rglob(pattern)`` and post-filtered every hit.
``rglob`` never prunes, so each call descended every excluded tree on disk
before throwing the hits away - measured 2026-09-19 on Legion at 22500
``os.scandir`` calls and 5.08 s per call for 2479 yielded files, 16760 of those
calls under ``.claude/worktrees`` (40 agent worktrees) and 1008 under
``ops/runtime/responder_export``. Sixteen guards paid that per call. Now the
tracked path iterates the INDEX and stats each entry (no directory is
enumerated at all), and the git-absent path is an ``os.walk`` that prunes
``EXCLUDED_DIRS`` at directory level. ``tests/test_repo_walk.py`` records
``os.scandir`` during both walks to prove neither enters a scratch tree, and
checks the tracked path equals ``{index and on disk and not excluded}``.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# Path SEGMENT names, matched against the path relative to the walk root.
EXCLUDED_DIRS = frozenset({
    # version control + agent scaffolding
    ".git",
    ".claude",
    "worktrees",
    "rc-worktrees",
    # dated / archived artifacts (docs/_archive and any sibling _archive)
    "_archive",
    # third-party and vendored trees
    "node_modules",
    "python-embed",
    "moon_sync_inbox",
    # caches and virtualenvs
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    # runtime exports: the inbox responder writes a full COPY OF THE REPO to
    # ops/runtime/responder_export/<sha>/, gitignored and untracked. The
    # tracked-set filter already removes it, so this entry only matters on the
    # fallback path (git absent or the index read failing) - which is exactly
    # the path RM-394's five red guards were on. One entry here, in the one
    # shared list, is the alternative to five per-guard hand-lists.
    "responder_export",
    # scratch + build output
    "_scratch",
    "build",
    "dist",
})


def is_excluded(rel: Path | str) -> bool:
    """True when a repo-relative path sits under an excluded directory.

    ``rel`` must be RELATIVE to the walk root; passing an absolute path is the
    trap described in this module's docstring.
    """
    parts = Path(rel).parts if not isinstance(rel, str) else tuple(
        rel.replace("\\", "/").split("/"))
    return any(part in EXCLUDED_DIRS for part in parts)


@lru_cache(maxsize=8)
def tracked_relpaths(root: str = "") -> Optional[frozenset[str]]:
    """Every path in the git INDEX for ``root``, as forward-slash relatives.

    Returns ``None`` - not an empty set - when git is unavailable or the call
    fails. Callers must treat ``None`` as "no tracked filter available" and fall
    back to the directory skips; an empty frozenset would filter EVERYTHING out
    and present as a clean tree.
    """
    base = Path(root) if root else REPO_ROOT
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(base),
            capture_output=True,
            encoding=None,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    entries = {part for part in raw.split("\0") if part}
    if not entries:
        return None
    return frozenset(entries)


def _name_matches(name: str, pattern: str) -> bool:
    """Basename glob match with the platform's case rule.

    ``fnmatch.fnmatch`` normcases both sides, so it is case-insensitive on
    Windows and case-sensitive on POSIX - the same default ``Path.rglob`` used
    before the walk was scoped, which keeps the yielded set identical.
    """
    return fnmatch.fnmatch(name, pattern)


def _walk_pruned(base: Path) -> Iterator[tuple[Path, str]]:
    """Every regular file under ``base`` as ``(dir, name)``, never entering an
    excluded directory. Symlinked directories are listed but not followed, and
    unreadable directories are skipped - both match the rglob defaults.
    """
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        here = Path(dirpath)
        for name in filenames:
            yield here, name


def iter_repo_files(
    root: Path | str = REPO_ROOT,
    patterns: Iterable[str] = ("*.py",),
    tracked_only: bool = True,
) -> Iterator[Path]:
    """Yield absolute paths under ``root`` matching any of ``patterns``.

    Excludes ``EXCLUDED_DIRS`` always, and untracked files when ``tracked_only``
    and the git index is readable. Order is stable (sorted per pattern) and no
    path is yielded twice even when two patterns overlap.

    Excluded directories are never DESCENDED: with a readable index the index
    itself is the candidate list and no directory is enumerated at all; without
    one, ``os.walk`` prunes at directory level. ``patterns`` are basename globs
    (``*.py``, ``test_*.py``), as every consumer passes.
    """
    patterns = tuple(patterns)
    for pattern in patterns:
        # Basename globs only. A pattern with a directory component or `**`
        # would match NOTHING against a basename and yield an empty walk that
        # reads as clean - the exact vacuity this module exists to prevent.
        if "/" in pattern or "\\" in pattern or "**" in pattern:
            raise ValueError(
                f"iter_repo_files takes basename globs only, got {pattern!r}"
            )
    base = Path(root).resolve()
    tracked = tracked_relpaths(str(base)) if tracked_only else None
    if tracked is not None:
        candidates: list[Path] = [
            base / rel for rel in tracked if not is_excluded(rel)
        ]
    else:
        candidates = [
            here / name for here, name in _walk_pruned(base)
            if not is_excluded((here / name).relative_to(base))
        ]
    seen: set[Path] = set()
    for pattern in patterns:
        matches = sorted(p for p in candidates if _name_matches(p.name, pattern))
        for path in matches:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            yield path


def repo_files(
    root: Path | str = REPO_ROOT,
    patterns: Iterable[str] = ("*.py",),
    tracked_only: bool = True,
) -> list[Path]:
    """``iter_repo_files`` as a sorted list."""
    return sorted(iter_repo_files(root, patterns, tracked_only))


def relative_posix(path: Path, root: Path | str = REPO_ROOT) -> str:
    """Forward-slash repo-relative path, for offender messages."""
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


# Files every healthy checkout carries, used to prove the walker is not vacuous.
# Long-lived TRACKED paths only: a file that is merely on disk (a brand-new,
# unstaged module - this one included, until it is committed) is invisible to
# `git ls-files` and would make the anchor check fail for the wrong reason.
_ANCHORS = (
    "web_dashboard.py",
    "conftest.py",
    "core/build_order.py",
)


def self_check(root: Path | str = REPO_ROOT) -> None:
    """Raise unless the walker actually reaches known files.

    An empty listing and a clean tree are the same output to every consumer, so
    this is the whole reason the module exists. Guards may call it directly;
    ``tests/test_repo_walk.py`` calls it too.
    """
    base = Path(root).resolve()
    found = {relative_posix(p, base) for p in iter_repo_files(base, ("*.py",))}
    if len(found) < 100:
        raise AssertionError(
            "tests/_repo_walk enumeration collapsed: only "
            f"{len(found)} tracked .py under {base}. A vacuous walker makes "
            "every consuming guard pass for the wrong reason - fix the walker, "
            "do not relax this bound."
        )
    missing = [a for a in _ANCHORS if a not in found]
    if missing:
        raise AssertionError(
            "tests/_repo_walk enumeration is missing anchor file(s) "
            f"{missing} under {base}. Either EXCLUDED_DIRS grew too broad or "
            "the git index read failed open."
        )
