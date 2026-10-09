"""Pick the test modules a push touched - the push CI impact slice.

Why this exists
---------------
MAIN's PERF-AUDIT of 2026-10-08, item 1 (HIGH): push CI ran the full dual
suite (`pytest tests/ agents/daemon_slayer/tests/`, ~38.5k tests, 22-45 min)
on every non-.md push, and 119 of 265 push runs (45 pct) were cancelled by a
newer push before they finished. The fix it ordered: keep the ~2 min fast
guards on every push, run the full dual suite on PR, on the merge/batch
cadence (workflow_dispatch) and nightly, and give a push an impact-selected
slice - "pytest-testmon or a path->test map like tools/md_guard_selector.py".
This is the path->test map. testmon was not taken: it needs a coverage
database carried between runs (a cache that a cancelled run can leave stale)
and a new hashed dependency, and its answer cannot be read off the source.

The map
-------
For every path the push changed (`git diff --name-only --no-renames
<before> <after>`), a test module under `tests/` or `agents/daemon_slayer/tests/`
is selected when:

* it IS the changed path (a changed test module runs itself);
* the changed path is Python and the module names it - by its dotted module
  name (`core.game_snapshot`) or by its stem as a whole word (`game_snapshot`;
  `from core import game_snapshot` and `tools / "game_snapshot.py"` both say
  it). A package `__init__.py` maps to the package's own name;
* the changed path is NOT Python and the module names its basename
  (`items.json`, `ci.yml`, `pre-push`) or one of its parent directories of two
  or more segments (`data/daemon_slayer`);
* the changed path sits in a top-level tree that holds no Python at all
  (`lane-widget/`, `rc-shell/`, `web/`, `data/`, `.githooks/`, ...) and the
  module carries a string literal naming that tree (`"lane-widget"`). Such a
  tree's coupling to the tests is its PATH, and a brand-new file in it is named
  by no test - the tree is.

`.md` paths are skipped: `.github/workflows/docs-guards.yml` fires on every
push carrying a `.md` and runs every module that reads one
(tools/md_guard_selector.py).

The error directions are not symmetric - a false positive costs seconds of CI,
a false negative ships a red tree that only the nightly sees - so the map errs
wide (whole-word text match, not an import graph), and anything it cannot see
through ESCALATES the push to the full dual suite: test infrastructure
(`conftest.py`, `pytest.ini`), dependency pins, the CI workflow, this file, a
push wider than MAX_CHANGED_PATHS, and a push base git cannot resolve (a new
branch, a force push, a shallow clone).

What is NOT claimed: a slice is not the suite. Coupling through runtime data
the source never spells (a JSON key, an env var, a subprocess of a subprocess)
is invisible to this map. That is what the full dual suite on PR, dispatch and
nightly is for.

Usage
-----
    python tools/ci_impact_selector.py --base <sha> --head <sha> \\
        [--out FILE] [--github-output FILE] [--explain]
    python tools/ci_impact_selector.py --paths core/x.py tools/y.py [--explain]

`--out` gets one module path per line (a pytest `@argfile`), empty unless the
mode is `slice`. `--github-output` gets `mode=<slice|full|none>` and
`count=<n>`. Exit status is 0 for every mode; a crash is a bug and fails loud.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two trees the full dual suite runs. tools/tests and
# oss/win32_atomic_io/tests have their own always-on CI steps, and
# agents/agent3_testing/suite is declared NOT wired (RM-407) - none of them
# belongs in this slice.
TEST_TREES = ("tests", "agents/daemon_slayer/tests")

MODE_SLICE = "slice"
MODE_FULL = "full"
MODE_NONE = "none"

# A push this wide is a batch landing, and a batch runs the batch suite.
MAX_CHANGED_PATHS = 300

_FULL_EXACT = {
    "pytest.ini": "pytest configuration reaches every module",
    "pyproject.toml": "may carry pytest configuration",
    "setup.cfg": "may carry pytest configuration",
    "tox.ini": "may carry pytest configuration",
    "requirements.txt": "runtime dependency pins reach every module",
    "requirements.lock": "runtime dependency lock reaches every module",
    ".github/workflows/ci.yml": "the CI mechanism itself - an edit to it re-runs the whole mechanism",
    "tools/ci_impact_selector.py": "this map - an edit to it re-runs everything it maps",
}
_FULL_GLOBS = (
    (".github/ci/requirements-*", "a hashed CI install set reaches every module"),
)
_ZERO_SHA = re.compile(r"^0+$")


def _norm(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _in_test_tree(path: str) -> bool:
    return any(path.startswith(tree + "/") for tree in TEST_TREES)


def is_test_module(path: str) -> bool:
    """A file pytest collects under the two dual-suite trees (default
    `python_files`: test_*.py and *_test.py)."""
    path = _norm(path)
    if not path.endswith(".py") or not _in_test_tree(path):
        return False
    base = path.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py")


def full_trigger_reason(path: str) -> Optional[str]:
    """Why this path escalates a push to the full dual suite, or None."""
    path = _norm(path)
    if path in _FULL_EXACT:
        return _FULL_EXACT[path]
    for pattern, why in _FULL_GLOBS:
        if fnmatch.fnmatch(path, pattern):
            return why
    if path.rsplit("/", 1)[-1] == "conftest.py" and (path == "conftest.py" or _in_test_tree(path)):
        return "a conftest.py reaches every module below it"
    return None


@dataclass
class Selection:
    mode: str
    modules: List[str] = field(default_factory=list)
    reasons: Dict[str, List[str]] = field(default_factory=dict)
    detail: str = ""


@dataclass(frozen=True)
class _TextNeedle:
    label: str
    words: frozenset  # every \w+ run in the needle - a cheap set prefilter
    pattern: "re.Pattern[str]"


def _text_needle(label: str, literal: str, before: str, after: str) -> _TextNeedle:
    rx = re.compile(f"(?<!{before}){re.escape(literal)}(?!{after})")
    return _TextNeedle(label, frozenset(re.findall(r"\w+", literal)), rx)


def _needles_for(path: str, asset_trees: frozenset):
    """(text needles, asset-tree names) that tie `path` to a test module."""
    text: List[_TextNeedle] = []
    trees: List[str] = []
    parts = path.split("/")
    if path.endswith(".py"):
        mod = parts[:-1] + [parts[-1][:-3]]
        if mod[-1] == "__init__":
            mod = mod[:-1]
        if mod:
            dotted = ".".join(mod)
            if len(mod) > 1:
                text.append(_text_needle(f"imports {dotted}", dotted, r"[\w.]", r"\w"))
            text.append(_text_needle(f"names {mod[-1]}", mod[-1], r"\w", r"\w"))
        return text, trees
    base = parts[-1]
    text.append(_text_needle(f"names {base}", base, r"[\w.\-]", r"[\w\-]"))
    for i in range(len(parts) - 1, 1, -1):
        parent = "/".join(parts[:i])
        text.append(_text_needle(f"names {parent}/", parent, r"[\w.\-]", r"[\w\-]"))
    if len(parts) > 1 and parts[0] in asset_trees:
        trees.append(parts[0])
    return text, trees


def _string_literals(text: str) -> List[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [m.group(2) for m in re.finditer(r"(['\"])([^'\"\n]*)\1", text)]
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _names_tree(literals: Iterable[str], tree: str) -> bool:
    for lit in literals:
        lit = _norm(lit)
        if lit == tree or lit.startswith(tree + "/"):
            return True
    return False


def select_impacted(changed: Iterable[str], tracked: Iterable[str],
                    read_text: Callable[[str], Optional[str]]) -> Selection:
    """Map changed paths to test modules. Pure: git and disk come in as data."""
    changed = sorted({_norm(p) for p in changed if p and p.strip()})
    tracked = [_norm(p) for p in tracked]
    if len(changed) > MAX_CHANGED_PATHS:
        return Selection(MODE_FULL, detail=(
            f"{len(changed)} changed paths is over MAX_CHANGED_PATHS={MAX_CHANGED_PATHS} - "
            "a batch landing runs the batch suite"))
    for path in changed:
        why = full_trigger_reason(path)
        if why:
            return Selection(MODE_FULL, detail=f"{path}: {why}")
    relevant = [p for p in changed if not p.lower().endswith(".md")]
    if not relevant:
        return Selection(MODE_NONE, detail="no non-.md path changed (docs-guards.yml owns .md)")

    tracked_set = set(tracked)
    top_with_py = {p.split("/", 1)[0] for p in tracked if "/" in p and p.endswith(".py")}
    asset_trees = frozenset(p.split("/", 1)[0] for p in tracked if "/" in p) - top_with_py

    reasons: Dict[str, List[str]] = {}
    for path in relevant:
        if is_test_module(path) and path in tracked_set:
            reasons.setdefault(path, []).append("changed test module")

    text_needles: Dict[str, _TextNeedle] = {}
    tree_needles: Dict[str, str] = {}
    for path in relevant:
        text, trees = _needles_for(path, asset_trees)
        for needle in text:
            text_needles.setdefault(needle.label, needle)
        for tree in trees:
            tree_needles.setdefault(f"names the {tree}/ tree", tree)

    for mod in (p for p in tracked if is_test_module(p)):
        source = read_text(mod)
        if source is None:
            continue
        words = set(re.findall(r"\w+", source))
        for label, needle in text_needles.items():
            if needle.words <= words and needle.pattern.search(source):
                reasons.setdefault(mod, []).append(label)
        if tree_needles:
            literals = None
            for label, tree in tree_needles.items():
                if not set(re.findall(r"\w+", tree)) <= words:
                    continue
                if literals is None:
                    literals = _string_literals(source)
                if _names_tree(literals, tree):
                    reasons.setdefault(mod, []).append(label)

    selected = sorted(reasons)
    detail = f"{len(relevant)} changed path(s) -> {len(selected)} test module(s)"
    return Selection(MODE_SLICE if selected else MODE_NONE, selected,
                     {m: reasons[m] for m in selected}, detail)


# ---------------------------------------------------------------------------
# git and disk
# ---------------------------------------------------------------------------

def _git() -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is not on PATH - the push range is unresolvable without it")
    return git


def git_tracked(root: Path) -> List[str]:
    out = subprocess.run([_git(), "ls-files", "-z"], cwd=str(root), capture_output=True,
                         text=True, timeout=300, check=True).stdout
    return [_norm(p) for p in out.split("\0") if p]


def disk_reader(root: Path) -> Callable[[str], Optional[str]]:
    def read(rel: str) -> Optional[str]:
        try:
            return (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return read


def changed_paths(root: Path, base: str, head: str) -> Optional[List[str]]:
    """Paths changed between `base` and `head`, or None when the range cannot
    be resolved (no base, the all-zero base of a new ref, a base this clone
    does not hold) - which the caller escalates to the full suite."""
    base, head = (base or "").strip(), (head or "").strip()
    if not base or not head or _ZERO_SHA.match(base):
        return None
    git = _git()
    for ref in (base, head):
        probe = subprocess.run([git, "cat-file", "-e", f"{ref}^{{commit}}"], cwd=str(root),
                               capture_output=True, text=True, timeout=60)
        if probe.returncode != 0:
            return None
    diff = subprocess.run([git, "diff", "--name-only", "--no-renames", base, head],
                          cwd=str(root), capture_output=True, text=True, timeout=300)
    if diff.returncode != 0:
        return None
    return [_norm(p) for p in diff.stdout.splitlines() if p.strip()]


def _write(path: Optional[str], text: str, *, append: bool = False) -> None:
    if not path:
        return
    with open(path, "a" if append else "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT), help="repo root")
    parser.add_argument("--base", default="", help="push base sha (github.event.before)")
    parser.add_argument("--head", default="", help="push head sha (GITHUB_SHA)")
    parser.add_argument("--paths", nargs="*", default=None,
                        help="changed paths given directly instead of a git range")
    parser.add_argument("--out", default=None, help="write the selected modules here, one per line")
    parser.add_argument("--github-output", default=None, help="append mode= and count= here")
    parser.add_argument("--explain", action="store_true", help="print each module with its reasons")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.paths is not None:
        changed: Optional[List[str]] = list(args.paths)
    else:
        changed = changed_paths(root, args.base, args.head)
    if changed is None:
        result = Selection(MODE_FULL, detail=(
            f"push range {args.base or '<none>'}..{args.head or '<none>'} is not resolvable "
            "(new ref, force push or missing history) - running the full dual suite"))
    else:
        result = select_impacted(changed, git_tracked(root), disk_reader(root))

    _write(args.out, "".join(m + "\n" for m in result.modules) if result.mode == MODE_SLICE else "")
    _write(args.github_output, f"mode={result.mode}\ncount={len(result.modules)}\n", append=True)
    print(f"ci_impact_selector: mode={result.mode} - {result.detail}")
    if changed is not None and args.explain:
        for path in sorted(set(changed)):
            print(f"  changed: {path}")
    if args.explain:
        for mod in result.modules:
            print(f"  {mod}\t{'; '.join(result.reasons.get(mod, []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
