"""
scripts/precommit_pycompile.py - pre-commit guard.

AUDIT 2026-04-28 (proposal 4.1): compile every staged .py file before
the commit lands. CLAUDE.md already mandates py_compile before any
restart; a syntax error under pythonw.exe crashes silently. Catching it
here keeps a broken file from ever entering history.

What is compiled is the STAGED BLOB, read from the index git hands the hook
(GIT_INDEX_FILE is honoured, so `git commit -a` and `git commit --only` are
covered), never the working-tree copy. S144-T-709 (2026-11-09) measured the
old working-tree read: a broken file staged and then fixed or deleted in the
working tree committed the broken bytes with "py_compile OK", and a good file
staged and then broken refused a correct commit.

- Listed: added, copied, modified, renamed and TYPE-CHANGED entries (a symlink
  replaced by a regular file is status T, which the old ACMR filter dropped).
- Skipped: symlink (120000) and gitlink (160000) entries - their blob is a
  link target or a commit id, not Python source.
- Compiled in memory with `compile(..., dont_inherit=True)`, which is what
  py_compile does underneath (PEP 263 coding cookie and UTF-8 BOM honoured),
  so no `__pycache__/*.pyc` is written into the tree being committed.
- A git failure (no git, not a repository, a missing blob) is a one-line
  refusal with exit 1, never a traceback and never a pass.

Install once per clone:
    git config core.hooksPath .githooks

The repo-tracked .githooks/pre-commit shim invokes this script.
"""
from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SKIP_MODES = frozenset({"120000", "160000"})  # symlink, gitlink
_GIT_TIMEOUT_S = 60


class GitError(RuntimeError):
    """A git call failed; the staged content cannot be established."""


def _git(args: list[str], stdin: bytes | None = None) -> bytes:
    """Run git in ROOT and return stdout bytes; every failure is a GitError."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(ROOT), input=stdin, capture_output=True,
            timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise GitError(f"git {args[0]} exited {proc.returncode}: {tail[0]}")
    return proc.stdout


def staged_python_entries() -> list[tuple[str, str]]:
    """(repo-relative path, staged blob id) for every staged regular .py file.

    Parsed from `git diff --cached --raw -z --no-renames --no-abbrev`:
    `:<old mode> <new mode> <old id> <new id> <status>\\0<path>\\0` per record.
    """
    out = _git(["diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev",
                "--diff-filter=ACMRT"])
    fields = out.split(b"\0")
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(fields):
        meta = fields[i]
        i += 1
        if not meta.startswith(b":"):
            continue
        parts = meta[1:].decode("ascii", "replace").split()
        if len(parts) < 5:
            raise GitError("git diff --raw: malformed record")
        npaths = 2 if parts[4][:1] in ("R", "C") else 1
        if i + npaths > len(fields):
            raise GitError("git diff --raw: truncated record")
        # RM-830: -z output is raw UTF-8 (no C-quoting), decoded here, not by the locale.
        path = fields[i + npaths - 1].decode("utf-8", "replace")
        i += npaths
        if not path:
            raise GitError("git diff --raw: empty path")
        new_mode, new_id = parts[1], parts[3]
        if path.endswith(".py") and new_mode not in _SKIP_MODES:
            entries.append((path, new_id))
    return entries


def staged_python_files() -> list[Path]:
    """Absolute paths of the staged regular .py files (display and callers only)."""
    return [ROOT / rel for rel, _ in staged_python_entries()]


def read_blobs(ids: list[str]) -> dict[str, bytes]:
    """Blob id -> content, in one `git cat-file --batch` call."""
    if not ids:
        return {}
    unique = list(dict.fromkeys(ids))
    out = _git(["cat-file", "--batch"], stdin="".join(f"{b}\n" for b in unique).encode("ascii"))
    blobs: dict[str, bytes] = {}
    pos = 0
    for want in unique:
        nl = out.find(b"\n", pos)
        if nl < 0:
            raise GitError("git cat-file: truncated output")
        header = out[pos:nl].decode("ascii", "replace").split()
        if (len(header) != 3 or header[0] != want or header[1] != "blob"
                or not header[2].isdigit()):
            raise GitError(f"git cat-file: no blob for {want[:12]}")
        size = int(header[2])
        start = nl + 1
        if start + size > len(out):
            raise GitError("git cat-file: truncated blob")
        blobs[want] = out[start:start + size]
        pos = start + size + 1
    return blobs


def _describe(exc: BaseException, rel: str) -> str:
    """The error text, built from the exception alone, naming `rel`.

    No traceback formatter: it re-reads the source line through linecache,
    i.e. from the WORKING-TREE file, which showed the fixed line under the
    staged error.
    """
    if not isinstance(exc, SyntaxError):
        return f"{type(exc).__name__}: {exc}"
    where = f", line {exc.lineno}" if isinstance(exc.lineno, int) else ""
    lines = [f'File "{rel}"{where}']
    text = (exc.text or "").rstrip("\r\n")
    if text.strip():
        lines.append(f"  {text.strip()}")
        if isinstance(exc.offset, int) and 0 < exc.offset <= len(text) + 1:
            indent = len(text) - len(text.lstrip())
            lines.append("  " + " " * max(exc.offset - 1 - indent, 0) + "^")
    lines.append(f"{type(exc).__name__}: {exc.msg}")
    return "\n".join(lines)


def compile_error(source: bytes, rel: str) -> str | None:
    """None if `source` compiles as `rel`, else the error text (no absolute path).

    The code object is named `<staged:rel>`, a name no file on disk carries:
    given a real file name, CPython fills SyntaxError.text by reading that
    line back from DISK (the working tree), not from `source`. Compile-time
    warnings (an invalid escape sequence, say) are re-emitted on stderr as one
    line each, without the source line the default warning printer would read.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        try:
            compile(source, f"<staged:{rel}>", "exec", dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            return _describe(exc, rel)
    for w in caught:
        print(f"pre-commit: {rel}:{w.lineno}: {w.category.__name__}: {w.message}",
              file=sys.stderr)
    return None


def main() -> int:
    try:
        entries = staged_python_entries()
        blobs = read_blobs([blob for _, blob in entries])
    except GitError as exc:
        print(f"pre-commit: py_compile cannot read the staged files - {exc}", file=sys.stderr)
        return 1
    if not entries:
        return 0
    failed: list[tuple[str, str]] = []
    for rel, blob in entries:
        msg = compile_error(blobs[blob], rel)
        if msg is not None:
            failed.append((rel, msg))
    if failed:
        print(f"pre-commit: py_compile failed on {len(failed)} file(s):", file=sys.stderr)
        for rel, msg in failed:
            print(f"  {rel}:", file=sys.stderr)
            for line in msg.splitlines():
                print(f"    {line}", file=sys.stderr)
        print(
            "\nFix the syntax errors above, stage the fix, and re-run `git commit`.\n"
            "The STAGED copy is what is checked, not the working tree. To bypass\n"
            "(rarely correct), pass --no-verify.",
            file=sys.stderr,
        )
        return 1
    print(f"pre-commit: py_compile OK ({len(entries)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
