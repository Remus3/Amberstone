"""Emit the test modules that read a tracked `.md` file off disk.

Why this exists
---------------
MEASURED 2026-07-27, re-derived 2026-09-06. `.github/workflows/ci.yml` carries
`paths-ignore: ['**/*.md']` (the 2026-06-30 MINUTE SAVER), so a docs-only commit
triggers NO workflow. `codspeed.yml` carried the same filter and was the second
half of that sentence until it was deleted on 2026-09-06 - see
docs/OPERATIONS.md "Why CodSpeed was dropped". Its removal does not weaken this
tool's reason to exist: one workflow declining `.md` is enough. But dozens of test modules
read tracked `.md` files off disk and assert on their CONTENT, so a `.md`-only
commit can turn a `.py` guard RED with nothing watching. `b412c2d8` did exactly
that to `tests/test_loop_director_context_caps.py`, and `ae829bb2` - the fix -
also ran no CI, so the fix's own green was never machine-confirmed.

`.github/workflows/docs-guards.yml` fires on the COMPLEMENT of that filter and
runs whatever THIS script prints. The minute saver survives: a prose edit that
no guard reads still skips the full suite.

Selection rule
--------------
A test module is selected when its AST contains a single-line, whitespace-free
string literal ending in `.md` that resolves against `git ls-files` - either as
a segment-boundary suffix of a tracked `.md` path (`ORCHESTRATION_PLAN.md`,
`docs/LEDGER.md`, `agents/daemon_slayer/CHANGELOG.md` all resolve), or as a
glob pattern that matches at least one tracked `.md` path (`**/*.md`, the shape
the repo-wide ASCII-hygiene guards use).

Two deliberate design choices, both scar-driven:

1. **The universe comes from the PRODUCING side.** Tracked `.md` paths come out
   of `git ls-files`; test modules are globbed out of the test trees. Nothing
   is hand-listed. A curated list is green over its own blind spot - the
   `SCHEDULED_SPAWNERS` failure (memory
   `reference_guard_derives_universe_from_wrong_side`).

2. **No disk-IO heuristic.** An earlier cut of this scan also required an IO
   call (`read_text` / `open` / `glob` / ...) in the module, on the theory that
   naming a `.md` is not reading one. That heuristic immediately proved the
   point: it dropped `tests/test_doc_size_budget.py`, which reads CLAUDE.md and
   ROADMAP.md through `.stat().st_size` - an IO name that was not on the list.
   The two error directions are not symmetric. A false positive costs a few
   seconds of CI on a module that mentions a doc it does not read; a false
   negative IS the defect this whole file exists to close. So the IO
   requirement is gone and mere reference selects.

Usage
-----
    python tools/md_guard_selector.py            # one repo-relative path per line
    python tools/md_guard_selector.py --json     # JSON array
    python tools/md_guard_selector.py --explain   # path + the literals that hit

Exits 1 when the selection is empty, because an empty pytest argv is a silent
no-op and this script's whole job is to not be silently green.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Both RC-owned test trees. DS modules read agents/daemon_slayer/CHANGELOG.md
# and CC_CONDITIONAL_NOTES.md, which are just as .md-fragile as tests/.
TEST_TREES = ("tests", "agents/daemon_slayer/tests")


def _git_tracked(repo_root: Path) -> list:
    """Every tracked path, repo-relative, forward-slashed."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is not on PATH - trackedness is unresolvable without it")
    out = subprocess.run(
        [git, "ls-files", "-z"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=300, check=True,
    ).stdout
    return [p.replace("\\", "/") for p in out.split("\0") if p]


def _md_suffix_index(tracked_md) -> frozenset:
    """Every segment-boundary suffix of every tracked `.md` path.

    Test code almost never spells a doc path from the repo root - it hangs the
    basename off a `_REPO / "docs"` expression - so `ORCHESTRATION_PLAN.md`
    must resolve just as `docs/ORCHESTRATION_PLAN.md` does. Same technique as
    `tests/test_skip_condition_hygiene.py`.
    """
    suffixes = set()
    for path in tracked_md:
        parts = path.split("/")
        for i in range(len(parts)):
            suffixes.add("/".join(parts[i:]))
    return frozenset(suffixes)


def _is_path_like(text: str) -> bool:
    """A path token, not prose that happens to name a doc.

    `"CLAUDE.md"` selects; `"test file must be 7-bit ASCII per CLAUDE.md"` does
    not. Without this, every docstring citing a doc would select its module.
    """
    if not text or len(text) > 300:
        return False
    if len(text.splitlines()) != 1:
        return False
    if any(ch in text for ch in " \t\r\n'\"()[]{},;"):
        return False
    return text.lower().endswith(".md")


def _string_literals(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _hits(literal: str, md_suffixes, tracked_md) -> bool:
    normalized = literal.replace("\\", "/").lstrip("./")
    if normalized in md_suffixes:
        return True
    if "*" in normalized or "?" in normalized:
        # A glob selects if it matches any tracked .md, either rooted at the
        # repo or as a bare-name pattern. `**/*.md` needs the explicit
        # basename fallback - fnmatch has no recursive-glob semantics.
        bare = normalized.rsplit("/", 1)[-1]
        for path in tracked_md:
            if fnmatch.fnmatch(path, normalized) or fnmatch.fnmatch(path, bare):
                return True
            if fnmatch.fnmatch(path.rsplit("/", 1)[-1], bare):
                return True
    return False


def select_md_guard_modules(repo_root: Path = REPO_ROOT, explain: bool = False):
    """Repo-relative paths of every test module that references a tracked `.md`.

    With ``explain=True`` returns ``{path: [literals]}`` instead of a list.
    """
    tracked = _git_tracked(repo_root)
    tracked_md = [p for p in tracked if p.lower().endswith(".md")]
    md_suffixes = _md_suffix_index(tracked_md)

    modules = [
        p for p in tracked
        if p.endswith(".py") and any(p.startswith(tree + "/") for tree in TEST_TREES)
    ]

    found = {}
    for rel in modules:
        try:
            source = (repo_root / rel).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            # Unparseable modules are py_compile's problem, not this scan's.
            continue
        hits = sorted({
            lit for lit in _string_literals(tree)
            if _is_path_like(lit) and _hits(lit, md_suffixes, tracked_md)
        })
        if hits:
            found[rel] = hits

    if explain:
        return dict(sorted(found.items()))
    return sorted(found)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit a JSON array")
    parser.add_argument("--explain", action="store_true",
                        help="emit each path with the literals that selected it")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repo root")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.explain:
        detail = select_md_guard_modules(root, explain=True)
        selected = list(detail)
    else:
        detail = None
        selected = select_md_guard_modules(root)

    if not selected:
        print(
            "md_guard_selector: selected 0 modules - refusing to emit an empty "
            "pytest argv. Either the test trees moved or the scan is broken.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(detail if detail is not None else selected, indent=2))
    elif detail is not None:
        for path, literals in detail.items():
            print(f"{path}\t{','.join(literals)}")
    else:
        for path in selected:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
