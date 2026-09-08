"""Tracked-only export of `origin/main` - the cwd the responder spawn reads.

PUBLIC-PROJECTION PRINCIPLE: every byte the spawned session can read must be a
projection of bytes already reachable from `origin/main`. The checkout is NOT
such a set - it carries gitignored files, other parties' inbox notes and
thousands of reflog-only commits - so the spawn never runs in it.

Every git process here is issued through the INJECTED `runner`, a closure the
runner slice builds over `procs.popen_capture` that prepends the configured git
executable as argv[0] and binds the environment, the cwd and the cycle's kill
budget. This module therefore names no executable, no PATH and no environment,
and contains no literal process spawn of its own.

`ref` is `origin/main` rather than `HEAD` on purpose: a local commit that has
not been pushed is not public, and a HEAD export would be a second, weaker
definition of "public".
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tarfile
from pathlib import Path

EXPORT_DIR_NAME = "responder_export"
KEEP_EXPORTS = 2
CHECK_IGNORE_TIMEOUT_S = 30

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_SHA12_RE = re.compile(r"^[0-9a-f]{12}$")


class ExportFailed(Exception):
    """Typed export error. `detail` is one of `no-origin-main`, `timeout`,
    `oversize`, `exc:<cls>`; the runner files it as `runner-failed /
    export:<detail>` and leaves the note pending with attempts unchanged."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _run_git(runner, args, timeout_s):
    """One git process through the injected runner, with the two non-exit
    failure modes lifted into `ExportFailed` before the caller sees a result."""
    res = runner(list(args), timeout_s=timeout_s)
    if res.exc is not None:
        raise ExportFailed(f"exc:{type(res.exc).__name__}")
    if res.timed_out:
        raise ExportFailed("timeout")
    return res


def _prune(export_root: Path, keep_final: Path) -> None:
    """Keep the newest `KEEP_EXPORTS` exports plus the one just returned."""
    if not export_root.is_dir():
        return
    entries = [p for p in export_root.iterdir() if p.is_dir() and _SHA12_RE.match(p.name)]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keep = [keep_final] if keep_final in entries else []
    for entry in entries:
        if len(keep) >= KEEP_EXPORTS:
            break
        if entry not in keep:
            keep.append(entry)
    for entry in entries:
        if entry not in keep:
            shutil.rmtree(entry, ignore_errors=True)


def ensure_export(repo_root, state_root, *, ref: str = "origin/main", runner, timeout_s, max_bytes) -> Path:
    """Return a directory holding the tracked tree of `ref`, exporting it first
    if it is not already cached.

    Two git processes on a cache miss (`rev-parse` for the sha12, then
    `archive`), one on a cache hit. Nothing is written to disk until the
    payload has passed the `max_bytes` check, so an oversize or timed-out
    export leaves no directory behind.
    """
    repo_root = Path(repo_root)
    export_root = Path(state_root) / "ops" / "runtime" / EXPORT_DIR_NAME

    res = _run_git(runner, ["rev-parse", ref], timeout_s)
    if res.exit_code != 0:
        raise ExportFailed("no-origin-main")
    sha = res.stdout.decode("ascii", "replace").strip()
    if not _SHA_RE.match(sha):
        raise ExportFailed("no-origin-main")

    final = export_root / sha[:12]
    if final.is_dir():
        _prune(export_root, final)
        return final

    res = _run_git(runner, ["archive", "--format=tar", ref], timeout_s)
    if res.exit_code != 0:
        raise ExportFailed("no-origin-main")
    if len(res.stdout) > max_bytes:
        raise ExportFailed("oversize")

    tmp_dir = export_root / f".tmp-{sha[:12]}-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        tmp_dir.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(res.stdout), mode="r:") as tar:
            tar.extractall(tmp_dir, filter="data")
        os.rename(tmp_dir, final)
    except FileExistsError:
        # A sibling cycle finished the same sha first. Its rename was atomic,
        # so `final` is complete; drop our copy and use theirs.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _prune(export_root, final)
        return final
    except (OSError, tarfile.TarError, ValueError, EOFError) as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ExportFailed(f"exc:{type(exc).__name__}")

    _prune(export_root, final)
    return final


def export_is_clean(export_dir, repo_root, *, runner, timeout_s: int = CHECK_IGNORE_TIMEOUT_S) -> bool:
    """Test oracle: True when zero exported paths are ignored by `repo_root`.

    One process per path, because `-q` is only valid with a single pathname
    (measured: git 2.53 exits 128 with `--quiet is only valid with a single
    pathname` on a batch). It short-circuits on the first ignored path, so the
    refutation is cheap and only a clean export pays the full walk. `runner` is
    required and injected for the same reason as in `ensure_export`: this
    module issues no process of its own.
    """
    export_dir = Path(export_dir)
    rels = sorted(
        str(p.relative_to(export_dir)).replace("\\", "/")
        for p in export_dir.rglob("*")
        if p.is_file()
    )
    for rel in rels:
        res = runner(["check-ignore", "-q", "--", rel], timeout_s=timeout_s)
        if res.exit_code == 0:
            return False
    return True
