r"""Print a dry-run prune manifest of stale IGNORED local files (RM-714).

Each row is one candidate a declared rule matched, with its size and a
consumer verdict:

    <verdict>\t<class>\t<bytes>\t<path>[/]\t<consumers or ->

- ``verdict`` is ``consumed`` when a tracked non-prose file names the
  candidate's basename (``git grep -l -I -F``; ``*.md``, ``.gitignore`` and
  this tool and its test are not readers), else ``orphan``. A consumed row is
  a KEEP until its reader is retired (the filed example:
  ``ops/runtime/e_move_backup`` named by ``ops/migrate/e_move_helpers.py``).
- A directory rule lists the directory as ONE unit; its bytes are the total.

A path is listed only when it is untracked, ignored by git, older than
``--min-age-days`` (default 14; a directory's age is its newest file's), not a
symlink or junction and holds no nested checkout (a ``.git`` at any depth).
A directory that holds a tracked file is refused like a tracked file. Skips are counted on ``#`` lines.

DRY RUN ONLY. This tool has no delete, move or recycle code path at all
(BACKLOG RM-714, REFRESHED 2026-10-25: the first slice lists). Removing what
it lists is an irreversible act that waits for the operator's OK and goes to
the Recycle Bin (FLEET-COMMON item 9, ``core/recycle_bin.py``), never a plain
unlink. The git index reading and size helpers come from RM-705's
``tools/bytecode_hygiene.py`` rather than a second implementation.

Usage: python tools/ignored_prune_manifest.py [--root DIR] [--min-age-days N]
Exit: 0 = listed; 2 = bad root, not a git checkout, or a git read failed.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bytecode_hygiene as bh  # noqa: E402 - sibling tool, path set above

REPO = bh.REPO
GitIndexError = bh.GitIndexError

DEFAULT_MIN_AGE_DAYS = 14.0
_MAX_SHOWN_CONSUMERS = 3
_SELF = ("tools/ignored_prune_manifest.py", "tests/test_ignored_prune_manifest.py")
_NOT_READERS = (":(exclude,glob)**/*.md", ":(exclude,glob)**/.gitignore",
                *(f":(exclude,literal){p}" for p in _SELF))


@dataclass(frozen=True)
class Rule:
    """One candidate class: a root-relative POSIX pattern whose wildcards sit
    in the last segment only, so a rule lists exactly one directory."""

    cls: str
    pattern: str
    reason: str


# The classes filed under RM-714 (BACKLOG.md; docs/audits/2026-10-09-repo-
# review-findings.md section 6). Deliberately NOT listed: the inbox responder's
# held / outbox state (the responder is armed, so that is live state), the
# live ``data/*_shadow.jsonl`` logs (only the backup copy), the partly-tracked
# agent6 auditor dirs (refused as tracked) and agent6 proposals (not ignored).
RULES: tuple[Rule, ...] = (
    Rule("settings_backup", ".claude/settings.json.bak-*", "B01-01 settings backups"),
    Rule("playwright_capture", ".playwright-mcp", "B01-02 browser tool captures"),
    Rule("agent_state_scratch", "agents/state/agent6_test_*", "B06-01 agent6 test output"),
    Rule("shadow_backup", "data/*_backup_shadow.jsonl", "B10-01 shadow log backup copy"),
    Rule("external_review_copy", "docs/EXTERNAL_REVIEW_*.md", "B13-06 docs-root review copies"),
    Rule("external_review_copy", "docs/_archive/EXTERNAL_REVIEW_*.md",
         "B16-02 archived review copies"),
    Rule("archive_leftover", "docs/_archive/2026-05-15-dev-sim-removal",
         "B14-01 dev-sim removal leftovers"),
    Rule("docs_scratch", "docs/_scratch", "B17-01 never-tracked scratch docs"),
    Rule("ui_audit", "docs/ui_audit", "B18-01 UI audit captures"),
    Rule("pytest_dump", "logs/_*.txt", "B18-05 pytest output dumps"),
    Rule("control_scratch", "ops/loop/control/*rw2*", "B22-07 rewrite rw2 leftovers"),
    Rule("control_scratch", "ops/loop/control/drain", "B22-02 drain wave scratch"),
    Rule("control_scratch", "ops/loop/control/progress/Wave*.json",
         "B22-02 drain wave progress"),
    Rule("control_scratch", "ops/loop/control/progress/drain-waves-*.json",
         "B22-02 drain wave progress"),
    Rule("lane_log", "ops/loop/reports/lane_*.log", "B23-01 lane run logs"),
    Rule("runtime_scratch", "ops/runtime/_*.log", "B24-02 underscore scratch logs"),
    Rule("runtime_scratch", "ops/runtime/merge_verify*.txt", "B26-02 merge verify output"),
    Rule("runtime_scratch", "ops/runtime/home_qa_suite.txt", "B25-02 one-off suite output"),
    Rule("runtime_scratch", "ops/runtime/cs_capture.log", "B25-04 one-off capture log"),
    Rule("runtime_scratch", "ops/runtime/monitor_*", "B26-06 monitor scratch"),
    Rule("runtime_capture", "ops/runtime/ui_recon", "B26-04 UI recon captures"),
    Rule("runtime_capture", "ops/runtime/e1_electron44_evidence", "B25-03 probe evidence"),
    Rule("runtime_capture", "ops/runtime/repo_review", "B26-03 repo review run state"),
    Rule("runtime_backup", "ops/runtime/e_move_backup", "B25-01 E-move backup"),
    Rule("tls_screenshot", "ops/tls/_*.png", "B26-11 screenshots beside the certs"),
    Rule("tls_screenshot", "ops/tls/_*.jpeg", "B26-11 screenshots beside the certs"),
    Rule("snapshot_png", "tests/snapshot_panels/screenshots/*.png",
         "B37-01 stale snapshot PNGs"),
)


@dataclass(frozen=True)
class Candidate:
    rel: str
    cls: str
    size: int
    is_dir: bool
    consumers: tuple[str, ...]

    @property
    def verdict(self) -> str:
        return "consumed" if self.consumers else "orphan"


def _git(root: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    kw = {"creationflags": bh._NO_WINDOW} if bh._NO_WINDOW else {}
    env = {k: v for k, v in os.environ.items() if k not in bh._GIT_ENV_DROP}
    try:
        return subprocess.run(["git", "-C", str(root), *args], input=data,
                              capture_output=True, check=False, timeout=300, env=env, **kw)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitIndexError(f"git {args[0]} failed: {exc}") from exc


def _require_repo(root: Path) -> None:
    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0 or probe.stdout.strip() != b"true":
        raise GitIndexError("not a git work tree: " + bh._err(probe))


def _match(root: Path, rule: Rule) -> list[tuple[str, str]]:
    """(rel, full) for each entry the rule names; lists one directory only."""
    parent, _, leaf = rule.pattern.rpartition("/")
    base = Path(root).joinpath(*parent.split("/")) if parent else Path(root)
    if not any(ch in leaf for ch in "*?["):
        full = base / leaf
        return [(rule.pattern, str(full))] if os.path.lexists(full) else []
    try:
        names = sorted(e.name for e in os.scandir(base))
    except OSError:
        return []
    pre = f"{parent}/" if parent else ""
    return [(pre + n, str(base / n)) for n in names if fnmatch.fnmatchcase(n, leaf)]


def _inside_link(root: Path, rel: str) -> bool:
    """True when the entry or any directory between it and the root is a link."""
    cur = Path(root)
    for part in rel.split("/"):
        cur = cur / part
        if bh._is_link(cur):
            return True
    return False


def _newest_mtime(full: str) -> float:
    newest = os.lstat(full).st_mtime
    if not Path(full).is_dir():
        return newest
    for dirpath, dirnames, filenames in os.walk(full):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not bh._is_link(here / d)]
        for name in (*filenames, *dirnames):
            try:
                newest = max(newest, os.lstat(here / name).st_mtime)
            except OSError:
                pass
    return newest


def _holds_checkout(full: str) -> bool:
    """True when a ``.git`` entry sits anywhere inside the directory ``full``
    (a nested checkout or worktree is never ours to list); links not followed."""
    for dirpath, dirnames, filenames in os.walk(full):
        if ".git" in dirnames or ".git" in filenames:
            return True
        dirnames[:] = [d for d in dirnames if not bh._is_link(Path(dirpath) / d)]
    return False


def _ignored(root: Path, rels: list[str]) -> set[str]:
    """The subset of ``rels`` git ignores (a tracked path is never ignored)."""
    if not rels:
        return set()
    proc = _git(root, "check-ignore", "-z", "--stdin",
                data="\0".join(rels).encode("utf-8", "surrogateescape") + b"\0")
    if proc.returncode not in (0, 1):
        raise GitIndexError("git check-ignore failed: " + bh._err(proc))
    return {p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


def consumers_of(root: Path, name: str, cache: dict[str, tuple[str, ...]] | None = None
                 ) -> tuple[str, ...]:
    """Tracked non-prose files that name ``name`` (a literal, case-sensitive)."""
    if cache is not None and name in cache:
        return cache[name]
    proc = _git(root, "grep", "-l", "-I", "-F", "--full-name", "-e", name,
                "--", ".", *_NOT_READERS)
    if proc.returncode not in (0, 1):
        raise GitIndexError("git grep failed: " + bh._err(proc))
    found = tuple(sorted(p for p in proc.stdout.decode("utf-8", "surrogateescape")
                         .splitlines() if p))
    if cache is not None:
        cache[name] = found
    return found


def find_candidates(root: Path, rules: tuple[Rule, ...] | None = None,
                    min_age_days: float = DEFAULT_MIN_AGE_DAYS,
                    skipped: dict[str, int] | None = None,
                    now: float | None = None) -> list[Candidate]:
    """Every candidate the rules match under ``root``, sorted by path.

    Lists only; never deletes. ``skipped`` (optional) receives counts keyed
    ``tracked`` / ``not_ignored`` / ``too_new`` / ``link`` / ``nested_checkout``.
    """
    root = Path(root)
    rules = RULES if rules is None else rules
    skipped = {} if skipped is None else skipped
    _require_repo(root)
    tracked = bh.tracked_paths(root)
    tracked_dirs = {p.rsplit("/", i)[0] for p in tracked for i in range(1, p.count("/") + 1)}
    cutoff = (time.time() if now is None else now) - min_age_days * 86400

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    seen: dict[str, tuple[str, str]] = {}
    for rule in rules:
        for rel, full in _match(root, rule):
            seen.setdefault(rel, (rule.cls, full))
    pending: list[tuple[str, str, str, bool]] = []
    for rel in sorted(seen):
        cls, full = seen[rel]
        key = bh.fold(rel)
        if _inside_link(root, rel):
            skip("link")
            continue
        is_dir = Path(full).is_dir()
        if key in tracked or (is_dir and key in tracked_dirs):
            skip("tracked")
            continue
        if is_dir and _holds_checkout(full):
            skip("nested_checkout")
            continue
        pending.append((rel, cls, full, is_dir))
    ignored = _ignored(root, [rel for rel, *_ in pending])
    cache: dict[str, tuple[str, ...]] = {}
    out: list[Candidate] = []
    for rel, cls, full, is_dir in pending:
        if rel not in ignored:
            skip("not_ignored")
            continue
        if _newest_mtime(full) > cutoff:
            skip("too_new")
            continue
        size = bh._dir_size(full) if is_dir else bh._size(full)
        name = rel.rsplit("/", 1)[-1]
        out.append(Candidate(rel, cls, size, is_dir, consumers_of(root, name, cache)))
    return out


def _row(c: Candidate) -> str:
    shown = list(c.consumers[:_MAX_SHOWN_CONSUMERS])
    if len(c.consumers) > _MAX_SHOWN_CONSUMERS:
        shown.append(f"+{len(c.consumers) - _MAX_SHOWN_CONSUMERS}")
    return "\t".join((c.verdict, c.cls, str(c.size), c.rel + ("/" if c.is_dir else ""),
                      ",".join(shown) or "-"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(REPO), help="checkout to scan (default: this one)")
    ap.add_argument("--min-age-days", type=float, default=DEFAULT_MIN_AGE_DAYS,
                    help="list only entries untouched for this many days (default 14)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"ignored_prune_manifest: root is not a directory: {root}", file=sys.stderr)
        return 2
    skipped: dict[str, int] = {}
    try:
        cands = find_candidates(root, min_age_days=args.min_age_days, skipped=skipped)
    except GitIndexError as exc:
        print(f"ignored_prune_manifest: {exc}", file=sys.stderr)
        return 2
    for c in cands:
        print(_row(c))
    for cls in dict.fromkeys(r.cls for r in RULES):
        sel = [c for c in cands if c.cls == cls]
        if sel:
            kept = sum(1 for c in sel if c.consumers)
            print(f"# {cls}: {len(sel)} paths, {sum(c.size for c in sel)} bytes, "
                  f"{kept} consumed")
    for why in sorted(skipped):
        print(f"# skipped {why}: {skipped[why]}")
    orphan = [c for c in cands if not c.consumers]
    print(f"# orphans: {len(orphan)} paths, {sum(c.size for c in orphan)} bytes")
    print(f"# dry run only: {len(cands)} candidates, nothing moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
