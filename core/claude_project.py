"""Claude Code's per-project directory for THIS checkout, resolved at run time.

Claude Code keeps a project's transcripts and memory under
``<home>/.claude/projects/<slug>``, where ``<slug>`` is the checkout's absolute
path with every non-alphanumeric character replaced by ``-``. Baking a slug
literal into a tracked file publishes the machine's checkout path, and it goes
stale the day the checkout moves (it did: the C: -> E: move left three readers
pointing at a slug that no longer received writes).

A linked worktree resolves to its MAIN checkout, because the memory and the
operator's transcripts live under the main checkout's slug, not under the
throwaway worktree path an agent happens to run from.

Pure helpers, stdlib only, no I/O beyond reading one ``.git`` link file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]

REPO_ROOT = Path(__file__).resolve().parent.parent

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def project_slug(path: PathLike) -> str:
    """Claude Code's directory name for a project rooted at ``path``."""
    return _NON_ALNUM.sub("-", str(path))


def main_checkout(root: Optional[PathLike] = None) -> Path:
    """The main working tree for ``root`` (default: this checkout).

    A linked worktree has a ``.git`` FILE reading ``gitdir: <main>/.git/worktrees/<name>``;
    anything else (a main checkout, an unreadable or unexpected link) is
    returned unchanged. Never raises: every caller resolves at import time
    with no handler of its own (dashboard/routes_loop_monitor.py:55,
    tools/drift_guard.py:79, tools/perseus_sync.py:62) or as a config default
    (ops/loop/loop_controller.py:175).
    """
    base = Path(root) if root is not None else REPO_ROOT
    dotgit = base / ".git"
    if not dotgit.is_file():
        return base
    try:
        line = dotgit.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        # Git writes the link as UTF-8. A link that cannot be read, or that is
        # not UTF-8, is an unreadable link: this checkout stands for itself.
        return base
    if not line.startswith("gitdir:"):
        return base
    gitdir = Path(line[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = base / gitdir
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return base


def project_dir(root: Optional[PathLike] = None, home: Optional[PathLike] = None) -> Path:
    """``<home>/.claude/projects/<slug of the main checkout>``."""
    home_dir = Path(home) if home is not None else Path.home()
    return home_dir / ".claude" / "projects" / project_slug(main_checkout(root))
