"""List, then optionally remove, regenerable bytecode and cache residue (RM-705).

Dry run by default; ``--apply`` removes what the dry run lists. Four classes:

- ``pyc_temp``: ``__pycache__`` names ending ``.pyc.<digits>`` - the
  write-temp files the bytecode cache leaves when its rename does not happen
  (seen under concurrent xdist imports on Windows; not proven, BACKLOG RM-705);
- ``orphan_pyc``: a ``__pycache__/<name>.<tag>.pyc`` whose ``<name>.py`` is
  gone - the rule ``ops/loop/repo_review.py`` already counts;
- ``inbox_pyc``: any .pyc under ``moon_sync_inbox/`` - sibling payloads are
  never imported here (RM-732), so bytecode there is an incident leftover;
- ``nested_pytest_cache``: every ``.pytest_cache`` directory except the root
  one (``pytest.ini`` lives at the root, so the root cache is the live one).

The walk prunes ``.git``, ``.claude/worktrees`` and any nested checkout (a
directory below the root that holds its own ``.git``), never follows a
symlink or a junction, and never lists a path git tracks. A legacy ``x.pyc``
beside its source (outside ``__pycache__``) is out of scope.

Everything removed is regenerable (FLEET-COMMON item 9 allows a plain delete);
the run prints the method before acting.

Usage: python tools/bytecode_hygiene.py [--root DIR] [--apply]
Exit: 0 = listed (or removed); 2 = bad root or an unreadable git index.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_TEMP_RE = re.compile(r"\.pyc\.\d+$")
_INBOX = "moon_sync_inbox"
_CACHE = ".pytest_cache"
_PRUNE_REL = frozenset({".git", ".claude/worktrees"})
_GIT_ENV_DROP = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                           "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                           "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM"})

CLASSES = ("pyc_temp", "orphan_pyc", "inbox_pyc", "nested_pytest_cache")


@dataclass(frozen=True)
class Candidate:
    rel: str
    cls: str
    size: int
    is_dir: bool = False


class GitIndexError(RuntimeError):
    pass


def tracked_paths(root: Path) -> set[str]:
    """Paths git tracks under ``root`` (POSIX, root-relative).

    ``root`` may be a checkout or any folder inside one; git's own discovery
    finds the repository either way. FAIL CLOSED: the empty set is returned
    only when git's probe fails AND neither ``root`` nor any ancestor holds a
    ``.git`` (decided from the filesystem, never from git's error text). Every
    other failure raises: a probe that fails below a ``.git``, an ``ls-files``
    that fails, a root holding its own ``.git``
    that git does not read as that repository's top (a broken ``.git``, which
    git skips to search the parents), and a root inside a ``.git`` directory.
    Inherited GIT_DIR-style and discovery variables (set inside a git hook, or
    a ceiling) are dropped so they cannot redirect or cut short discovery.
    Paths are case-folded (``fold``) because the filesystem may not be
    case-sensitive while git's index is.
    """
    kw = {"creationflags": _NO_WINDOW} if _NO_WINDOW else {}
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}

    def git(*args: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                  check=False, timeout=120, env=env, **kw)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitIndexError(f"git ls-files failed: {exc}") from exc

    resolved = Path(os.path.abspath(root))
    if any(part.casefold() == ".git" for part in resolved.parts):
        raise GitIndexError("git ls-files failed: root is inside a .git directory")
    own_git = (resolved / ".git").exists()
    probe = git("rev-parse", "--is-inside-git-dir", "--show-prefix")
    if probe.returncode != 0:
        if any((d / ".git").exists() for d in (resolved, *resolved.parents)):
            raise GitIndexError("git ls-files failed: " + _err(probe))
        return set()  # in no repository at all: nothing is tracked
    lines = probe.stdout.decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != "false":
        raise GitIndexError("git ls-files failed: root is inside a git directory")
    if own_git and "".join(lines[1:]).strip():
        raise GitIndexError("git ls-files failed: root has a .git that is not its "
                            "repository's top (git found a parent repository)")
    proc = git("ls-files", "-z")
    if proc.returncode != 0:
        raise GitIndexError("git ls-files failed: " + _err(proc))
    return {fold(p) for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


def fold(rel: str) -> str:
    """The comparison key of a root-relative POSIX path (case-insensitive)."""
    return rel.casefold()


def _err(proc: subprocess.CompletedProcess) -> str:
    return proc.stderr.decode("utf-8", "replace").strip()


def _is_link(path: str) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not _is_link(os.path.join(dirpath, d))]
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def _size(path: str) -> int:
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def _classify_pyc(rel: str, name: str, dirpath: str) -> str | None:
    """The class of one file, or None to keep it.

    A temp or .pyc counts only inside ``__pycache__``, except under the inbox,
    where every one counts wherever it sits."""
    in_cache = os.path.basename(dirpath) == "__pycache__"
    in_inbox = rel.split("/", 1)[0] == _INBOX
    if not (in_cache or in_inbox):
        return None
    if _TEMP_RE.search(name):
        return "pyc_temp"
    if not name.endswith(".pyc"):
        return None
    if in_inbox:
        return "inbox_pyc"
    source = os.path.join(os.path.dirname(dirpath), name.split(".", 1)[0] + ".py")
    return None if os.path.exists(source) else "orphan_pyc"


def find_candidates(root: Path, tracked: set[str] | None = None) -> list[Candidate]:
    """Every candidate under ``root``, sorted by path. Lists only; never deletes."""
    root = Path(root)
    if tracked is None:
        tracked = tracked_paths(root)
    tracked = {fold(p) for p in tracked}
    tracked_dirs = {p.rsplit("/", i)[0] for p in tracked for i in range(1, p.count("/") + 1)}
    out: list[Candidate] = []
    top = str(root)
    for dirpath, dirnames, filenames in os.walk(top):
        rel_dir = os.path.relpath(dirpath, top).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if fold(rel) in _PRUNE_REL or fold(d) == ".git" or _is_link(full):
                continue
            if os.path.exists(os.path.join(full, ".git")):
                continue  # a nested checkout or worktree: not ours to clean
            if d == _CACHE:
                if rel_dir and fold(rel) not in tracked_dirs:
                    out.append(Candidate(rel, "nested_pytest_cache", _dir_size(full), True))
                continue  # never descend into a cache, root or nested
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if ".pyc" not in name or fold(rel) in tracked:
                continue
            cls = _classify_pyc(rel, name, dirpath)
            if cls is not None:
                out.append(Candidate(rel, cls, _size(os.path.join(dirpath, name))))
    out.sort(key=lambda c: c.rel)
    return out


def remove(root: Path, cands: list[Candidate]) -> tuple[int, list[str]]:
    """Delete each candidate; drop a ``__pycache__`` dir this run emptied.

    Returns (removed count, error lines)."""
    removed = 0
    errors: list[str] = []
    emptied: set[Path] = set()
    for c in cands:
        p = root / c.rel
        try:
            if c.is_dir:
                shutil.rmtree(p)
            else:
                p.unlink()
                if p.parent.name == "__pycache__":
                    emptied.add(p.parent)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append(f"{c.rel}: {exc}")
    for d in sorted(emptied):
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    return removed, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(REPO), help="tree to clean (default: this checkout)")
    ap.add_argument("--apply", action="store_true", help="remove what the dry run lists")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"bytecode_hygiene: root is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        cands = find_candidates(root)
    except GitIndexError as exc:
        print(f"bytecode_hygiene: {exc}", file=sys.stderr)
        return 2
    for c in cands:
        print(f"{c.cls}\t{c.size}\t{c.rel}{'/' if c.is_dir else ''}")
    for cls in CLASSES:
        sel = [c for c in cands if c.cls == cls]
        print(f"# {cls}: {len(sel)} paths, {sum(c.size for c in sel)} bytes")
    if not args.apply:
        print(f"# dry run: {len(cands)} candidates, nothing removed (--apply to remove)")
        return 0
    print("# method: plain delete (os unlink / shutil.rmtree), regenerable files only")
    removed, errors = remove(root, cands)
    for line in errors:
        print(f"# error: {line}", file=sys.stderr)
    print(f"# removed {removed} of {len(cands)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
