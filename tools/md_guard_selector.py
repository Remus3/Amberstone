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

A `test_*.py` module is ALSO selected when its git-index enumeration can
include a `.md` (RM-1107, `index_walk_reasons`): a `git ls-files` argv with
no pathspec or a `.md`-reaching one, a `tests._repo_walk.tracked_relpaths`
call, or an `iter_repo_files` / `repo_files` glob that matches a `.md`. Such a
guard names no `.md` at all - `tests/test_text_line_endings.py` reads every
tracked file - so the literal rule alone left it unwatched on a docs push.
A pathspec is also read in the directory git resolves it in (RM-1145): a
constant `-C <dir>` is joined, and an unreadable `-C` or `cwd=` (or a helper
whose directory is not visible) matches it against every `.md` suffix. The
root reading still selects, so this can only add a module.

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
import posixpath
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
        encoding="utf-8", errors="replace",   # RM-830: UTF-8 names, never the locale
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


_DOT_PREFIXES = ("./", "../", "/")


def _strip_dot_prefix(path: str) -> str:
    """Drop leading `./`, `../` and `/` SEGMENTS - a prefix, never a character
    set. RM-763: `lstrip("./")` also ate the dot that starts a name, so
    `.github/CONTRIBUTING.md` became `github/CONTRIBUTING.md` and never
    resolved against the tracked path."""
    previous = None
    while previous != path:
        previous = path
        for prefix in _DOT_PREFIXES:
            path = path.removeprefix(prefix)
    return path


def _hits(literal: str, md_suffixes, tracked_md) -> bool:
    normalized = _strip_dot_prefix(literal.replace("\\", "/"))
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


def _md_pathspec(spec: str, tracked_md) -> bool:
    """A `git ls-files` pathspec (or a basename glob) that can match a tracked
    `.md`: `.`, a directory holding one, or a glob matching one."""
    spec = _strip_dot_prefix(spec.replace("\\", "/"))
    if spec in ("", "."):
        return True
    if any(ch in spec for ch in "*?["):
        bare = spec.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(p, spec) or fnmatch.fnmatch(p.rsplit("/", 1)[-1], bare)
                   for p in tracked_md)
    prefix = spec.rstrip("/") + "/"
    return any(p == spec or p.startswith(prefix) for p in tracked_md)


def _module_constants(tree: ast.AST) -> dict:
    """Top-level `NAME = "x"` / `NAME = ("a", "b")` bindings, so a pattern or
    pathspec held in a module constant resolves like an inline literal."""
    out = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
    return out


def _const_strings(node, consts, _depth=0):
    """The string values an argument expression stands for, or None when they
    cannot be read statically (the caller then assumes the wide reading)."""
    if _depth > 3:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and node.id in consts:
        return _const_strings(consts[node.id], consts, _depth + 1)
    if isinstance(node, ast.Starred):
        return _const_strings(node.value, consts, _depth + 1)
    if isinstance(node, (ast.Tuple, ast.List)):
        values = []
        for elt in node.elts:
            got = _const_strings(elt, consts, _depth + 1)
            if got is None:
                return None
            values.extend(got)
        return values
    return None


_UNREADABLE = object()


def _join_rel(base, part):
    """`base` / `part` as a normalised repo-relative path ("" = the root), or
    None when `part` is absolute or the result leaves the repo."""
    part = part.replace("\\", "/")
    if base is None or part.startswith("/") or part[1:2] == ":":
        return None
    path = posixpath.normpath(posixpath.join(base, part)) if (base or part) else "."
    if path == ".." or path.startswith("../"):
        return None
    return "" if path == "." else path


def _ls_files_base(before, consts, base=""):
    """RM-1145: the directory git resolves an `ls-files` pathspec in, after
    the argv's own `-C <dir>` flags (`before` = the elements ahead of
    `ls-files`), starting from `base` ("" = the root, None = unreadable). A
    constant `-C` is joined; anything else, or a starred element that may hide
    a `-C`, makes it None."""
    tokens = []
    for node in before:
        got = _const_strings(node, consts)
        if got is None:
            if isinstance(node, ast.Starred):
                return None
            tokens.append(_UNREADABLE)
        else:
            tokens.extend(got)
    for i, token in enumerate(tokens):
        if token == "-C":
            value = tokens[i + 1] if i + 1 < len(tokens) else _UNREADABLE
            base = None if value is _UNREADABLE else _join_rel(base, value)
    return base


def _md_pathspec_in(spec, base, tracked_md, md_suffixes) -> bool:
    """`_md_pathspec` for a spec git resolves in directory `base`: None means
    any directory, so the spec is matched against every `.md` suffix."""
    path = _join_rel(base, spec)
    if path is None:
        return _md_pathspec(spec, md_suffixes)
    return _md_pathspec(path, tracked_md)


def _ls_files_reaches_md(after, consts, tracked_md, base="", md_suffixes=()) -> bool:
    """The argv elements after `ls-files`: no pathspec walks the whole index;
    otherwise any pathspec that can match a `.md` (an unreadable one included),
    read from the root AND from `base`, the directory git resolves it in
    (RM-1145; "" = the root, None = unreadable). The root reading still
    selects, so a wrongly read base widens the run but never drops a walker."""
    specs = []
    for node in after:
        got = _const_strings(node, consts)
        if got is None:
            return True
        specs.extend(s for s in got if not s.startswith("-"))
    if not specs or any(_md_pathspec(s, tracked_md) for s in specs):
        return True
    if base == "":
        return False
    return any(_md_pathspec_in(s, base, tracked_md, md_suffixes) for s in specs)


def _call_base(call: ast.Call, consts):
    """The directory a call runs its argv in: "" (the root, pytest's cwd)
    unless it passes `cwd=` - joined when constant, else None - or `**kwargs`,
    which may hold one (None)."""
    base = ""
    for kw in call.keywords:
        if kw.arg is None:
            return None
        if kw.arg == "cwd":
            got = _const_strings(kw.value, consts)
            base = _join_rel("", got[0]) if got is not None and len(got) == 1 else None
    return base


_INDEX_LISTERS = frozenset({"tracked_relpaths"})
_GLOB_WALKERS = frozenset({"iter_repo_files", "repo_files"})

# s144 L5 merger: docs-guards.yml checks out at fetch-depth: 1 on purpose, so
# a module that also asks git for HISTORY cannot run there. The same markers
# tests/test_ci_checkout_history_depth.py uses (_HISTORY_MARKERS). Applied to
# the index-walk route only: such a module stays in the full suite
# (fetch-depth: 0), exactly as before the RM-1107 widening selected it.
_HISTORY_MARKERS = ("cat-file", "--diff-filter", "rev-list")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def index_walk_reasons(tree: ast.AST, tracked_md, md_suffixes=None) -> list:
    """RM-1107: why this module's git-index enumeration can include a `.md`.

    The rule reads the ENUMERATION, never the filter after it: RM-273's guard
    names only `.xml` (an exemption) and still reads every tracked `.md`.
    - an argv literal holding `"ls-files"` (passed anywhere, or bound to a
      name), or a helper call `f("ls-files", ...)`, with no pathspec or a
      pathspec that can match a `.md`. The pathspec is read from the root
      and from the directory git resolves it in (RM-1145): the argv's
      `-C` flags and the call's `cwd=`, joined when constant; an unreadable
      one, or a helper call (its directory is not visible), reads it in any
      directory - against every segment-boundary suffix of a tracked `.md`;
    - a call to `tests._repo_walk.tracked_relpaths` (the whole index);
    - `iter_repo_files` / `repo_files` with a basename glob matching a `.md`
      (their default is `*.py`, so a bare call does not select).
    An argument that cannot be read statically takes the wide reading: a
    false positive costs CI seconds, a false negative is this file's defect.
    """
    consts = _module_constants(tree)
    if md_suffixes is None:
        md_suffixes = _md_suffix_index(tracked_md)
    # RM-1145: the directory each call runs its argv in (`cwd=`). ast.walk
    # is breadth-first, so a call is met before the argv list inside it.
    call_bases = {}
    reasons = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            elts = node.elts
            for i, elt in enumerate(elts):
                if isinstance(elt, ast.Constant) and elt.value == "ls-files":
                    base = _ls_files_base(elts[:i], consts, call_bases.get(id(node), ""))
                    if _ls_files_reaches_md(elts[i + 1:], consts, tracked_md, base,
                                            md_suffixes):
                        reasons.add("<index walk: git ls-files>")
                    break
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            args = node.args
            argvs = [*args[:1], *(kw.value for kw in node.keywords if kw.arg == "args")]
            if any(isinstance(a, (ast.List, ast.Tuple)) for a in argvs):
                call_base = _call_base(node, consts)
                for argv in argvs:
                    call_bases[id(argv)] = call_base
            # RM-1145: a helper call with git's global flags ahead of the verb,
            # `f("-C", "dir", "ls-files", ...)` - string literals, or any value
            # right after a `-C`. Checked on its own, so it only adds.
            verb = next((i for i, a in enumerate(args[1:], 1)
                         if isinstance(a, ast.Constant) and a.value == "ls-files"), None)
            if verb is not None and all(
                    (isinstance(a, ast.Constant) and isinstance(a.value, str))
                    or (j and isinstance(args[j - 1], ast.Constant) and args[j - 1].value == "-C")
                    for j, a in enumerate(args[:verb])) \
                    and _ls_files_reaches_md(args[verb + 1:], consts, tracked_md, None,
                                             md_suffixes):
                reasons.add("<index walk: git ls-files>")
            if args and isinstance(args[0], ast.Constant) and args[0].value == "ls-files":
                # A helper's own `-C` / `cwd=` is not visible here: any directory.
                if _ls_files_reaches_md(args[1:], consts, tracked_md, None, md_suffixes):
                    reasons.add("<index walk: git ls-files>")
            elif name in _INDEX_LISTERS:
                reasons.add(f"<index walk: {name}>")
            elif name in _GLOB_WALKERS:
                pattern = args[1] if len(args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "patterns"), None)
                if pattern is None:
                    continue
                globs = _const_strings(pattern, consts)
                if globs is None or any(_md_pathspec(g, tracked_md) for g in globs):
                    reasons.add(f"<index walk: {name}>")
    return sorted(reasons)


def select_md_guard_modules(repo_root: Path = REPO_ROOT, explain: bool = False):
    """Repo-relative paths of every test module that references a tracked `.md`,
    or whose git-index enumeration can include one (RM-1107).

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
        # Only modules pytest collects: a helper that walks the index is
        # reached through the test modules that call it.
        if (rel.rsplit("/", 1)[-1].startswith("test_")
                and not any(m in source for m in _HISTORY_MARKERS)):
            hits.extend(index_walk_reasons(tree, tracked_md, md_suffixes))
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
