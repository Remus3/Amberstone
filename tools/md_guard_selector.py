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
root reading still selects, so this can only add a module. An option's
separate value (`-x <pattern>`) is also read as git reads it, not as a
pathspec, and a `cwd=` reaches an argv wrapped in a call (RM-1147); both
are extra readings, so they too only add. So does a `cwd=` reaching an argv
bound to a name (`cmd = [...]; run(cmd, cwd=...)`, RM-1146 (2)), read only
in the scope Python resolves the name to.

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
        return _md_pathspec(spec, md_suffixes) or _md_pathspec(_climb_free(spec), md_suffixes)
    return _md_pathspec(path, tracked_md)


def _climb_free(spec) -> str:
    """RM-1146 (2): `spec` normalised with its leading `..` segments dropped
    (`sub/../guide.md` -> `guide.md`, `..` -> `.`). In an unknown directory a
    climb can land anywhere, so this reads at least what any one directory
    reads - which is what lets a bound argv's many directories collapse to
    the any-directory reading (None) without losing one a git run makes.
    Not covered, by measurement (round-4 verifier): a directory holding a
    glob character (`cwd="[d]"`), whose joined path fnmatch reads as a glob;
    such a match is spurious (git reads the directory literally)."""
    parts = posixpath.normpath(spec.replace("\\", "/")).split("/")
    while parts and parts[0] == "..":
        parts.pop(0)
    return "/".join(parts) or "."


# RM-1147 (a): the `git ls-files` options whose value is the NEXT word.
_LS_FILES_VALUE_SHORT = frozenset("xX")
_LS_FILES_VALUE_LONG = ("exclude", "exclude-from", "exclude-per-directory", "with-tree", "format")


def _ls_files_operands(words) -> list:
    """RM-1147 (a): the pathspecs `git ls-files` reads from `words`. An
    option's separate value (`-x <pattern>`, `--exclude-from <file>`,
    `--format <format>`, also at the end of a short cluster `-tx <pattern>`
    or after an abbreviation `--form`) is not one; after `--` every word is."""
    specs, i = [], 0
    while i < len(words):
        word = words[i]
        i += 1
        if word == "--":
            specs.extend(words[i:])
            break
        if word.startswith("--"):
            # `--exclude=x` and `--no-with-tree` name no option here.
            if any(long.startswith(word[2:]) for long in _LS_FILES_VALUE_LONG):
                i += 1
        elif word.startswith("-") and len(word) > 1:
            for j, ch in enumerate(word[1:], 1):
                if ch in _LS_FILES_VALUE_SHORT:
                    if j == len(word) - 1:   # `-tx <pattern>`, not `-tx<pattern>`
                        i += 1
                    break
        else:
            specs.append(word)
    return specs


def _ls_files_reaches_md(after, consts, tracked_md, base="", md_suffixes=()) -> bool:
    """The argv elements after `ls-files`: no pathspec walks the whole index;
    otherwise any pathspec that can match a `.md` (an unreadable one included),
    read from the root AND from `base`, the directory git resolves it in
    (RM-1145; "" = the root, None = unreadable). The root reading still
    selects, so a wrongly read base widens the run but never drops a walker.
    RM-1147 (a): the words are also read with each option's value skipped,
    as git parses them; the old every-non-dash-word reading still selects."""
    words = []
    for node in after:
        got = _const_strings(node, consts)
        if got is None:
            return True
        words.extend(got)
    specs = [s for s in words if not s.startswith("-")]
    if _specs_reach_md(specs, tracked_md, base, md_suffixes):
        return True
    operands = _ls_files_operands(words)
    return operands != specs and _specs_reach_md(operands, tracked_md, base, md_suffixes)


def _specs_reach_md(specs, tracked_md, base, md_suffixes) -> bool:
    if not specs or any(_md_pathspec(s, tracked_md) for s in specs):
        return True
    if _magic_reaches_md(specs, tracked_md, base, md_suffixes):
        return True
    if base == "":
        return False
    return any(_md_pathspec_in(s, base, tracked_md, md_suffixes) for s in specs)


_SHORT_MAGIC = {"/": "top", "!": "exclude", "^": "exclude"}
_PLAIN_MAGIC = frozenset({"top", "literal", "glob"})


def _pathspec_magic(spec):
    """RM-1146 (4): a pathspec's magic words and the path after them, or
    (None, spec) for a plain one. `:(top,glob)x` is the long form, `:/x`,
    `:!x`, `:^x` and `:/!:x` the short form."""
    if not spec.startswith(":"):
        return None, spec
    if spec.startswith(":("):
        close = spec.find(")")
        if close < 0:
            return {"?"}, ""
        return {w.split(":", 1)[0].strip() for w in spec[2:close].split(",")}, spec[close + 1:]
    i = 1
    words = set()
    while i < len(spec) and spec[i] in _SHORT_MAGIC:
        words.add(_SHORT_MAGIC[spec[i]])
        i += 1
    if spec[i:i + 1] == ":":
        i += 1
    return words, spec[i:]


def _magic_reaches_md(specs, tracked_md, base, md_suffixes) -> bool:
    """RM-1146 (4): the magic pathspecs among `specs`, read by their magic.
    An exclude adds no path, so an argv of excludes only lists the directory
    git runs in (`base`); `top` reads from the root whatever `-C` says;
    `literal` / `glob` read the path like a plain spec (wider, never
    narrower); any other magic (`icase`, `attr`) takes the wide reading."""
    positive = False
    for spec in specs:
        words, rest = _pathspec_magic(spec)
        if words is None:
            positive = True
            continue
        if "exclude" in words:
            continue
        if not words <= _PLAIN_MAGIC:
            return True
        positive = True
        if _md_pathspec(rest, tracked_md):
            return True
        if "top" not in words and base != "" \
                and _md_pathspec_in(rest, base, tracked_md, md_suffixes):
            return True
    if positive:
        return False
    return base == "" or _md_pathspec_in(".", base, tracked_md, md_suffixes)


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


def _add_operands(node, chained) -> list:
    """RM-1146 (1): the operands of an `a + b + c` chain, left to right;
    each inner `+` node is recorded in `chained` so it is not read again.
    Iterative: a long `"a" + "a" + ...` chain must not hit the recursion
    limit."""
    operands, stack = [], [node]
    while stack:
        item = stack.pop()
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add):
            chained.add(id(item))
            stack.extend((item.right, item.left))
        else:
            operands.append(item)
    return operands


def _outer_argvs(nodes) -> list:
    """RM-1147 (b): the outermost lists, tuples and `+` chains inside
    `nodes` - an argv wrapped in a call such as `list(...)` or `tuple(...)`.
    Not descended into, so a chain's operands keep their chain reading."""
    found, stack = [], list(nodes)
    while stack:
        item = stack.pop()
        if isinstance(item, (ast.List, ast.Tuple)) or \
                (isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add)):
            found.append(item)
        else:
            stack.extend(ast.iter_child_nodes(item))
    return found


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_TYPE_ALIAS = getattr(ast, "TypeAlias", ())
# RM-1146 (2): past this many directories for one bound argv, also read it
# in any directory (None, the widest reading of what git lists - see
# `_climb_free`) and record no more, so the readings stay bounded.
_MAX_BASES = 8


class _Scope:
    """One Python scope: the names it binds and its `name = value` bindings."""

    __slots__ = ("assigns", "declared", "kind", "parent", "stores")

    def __init__(self, kind, parent):
        # "module" | "function" | "class" | "comprehension" | "annotation"
        # (PEP 695: type parameters and a `type X = ...` value).
        self.kind = kind
        self.parent = parent
        self.stores = set()
        self.declared = {}          # name -> "global" | "nonlocal"
        self.assigns = []           # (name, value node, scope it is read in)


def _bind_args(args: ast.arguments, scope) -> None:
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
        if arg is not None:
            scope.stores.add(arg.arg)


def _collect_scopes(tree):
    """RM-1146 (2): every scope of the module, and each call with the scope
    it runs in. Iterative, so a deep tree cannot hit the recursion limit."""
    module = _Scope("module", None)
    scopes, calls = [module], []
    stack = [(tree, module)]
    while stack:
        node, scope = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            # The name, decorators, defaults and bases belong to the outer scope.
            # PEP 695 type parameters live in a scope of their own around it.
            holder = scope
            params = getattr(node, "type_params", None)
            if params:
                holder = _Scope("annotation", scope)
                holder.stores.update(param.name for param in params)
                scopes.append(holder)
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            inner = _Scope(kind, holder)
            scopes.append(inner)
            outer = list(getattr(node, "decorator_list", []))
            if isinstance(node, ast.ClassDef):
                stack.extend((part, holder) for part in
                             (*node.bases, *(kw.value for kw in node.keywords)))
            else:
                outer += [*node.args.defaults, *(d for d in node.args.kw_defaults if d)]
                _bind_args(node.args, inner)
            if not isinstance(node, ast.Lambda):
                scope.stores.add(node.name)
            body = [node.body] if isinstance(node, ast.Lambda) else node.body
            stack.extend((part, scope) for part in outer)
            stack.extend((part, inner) for part in body)
            continue
        if isinstance(node, _COMPREHENSIONS):
            # Its targets are its own; the first iterable is read outside it.
            inner = _Scope("comprehension", scope)
            scopes.append(inner)
            for i, gen in enumerate(node.generators):
                stack.append((gen.iter, inner if i else scope))
                stack.extend((part, inner) for part in (gen.target, *gen.ifs))
            elts = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
            stack.extend((part, inner) for part in elts)
            continue
        if isinstance(node, _TYPE_ALIAS):
            # `type X[T] = value`: the value is read in an annotation scope.
            holder = _Scope("annotation", scope)
            holder.stores.update(param.name for param in node.type_params)
            scopes.append(holder)
            scope.stores.add(node.name.id)
            stack.append((node.value, holder))
            continue
        if isinstance(node, ast.NamedExpr):
            # A walrus binds in the nearest scope that is not a comprehension.
            owner = scope
            while owner.kind == "comprehension" and owner.parent is not None:
                owner = owner.parent
            owner.stores.add(node.target.id)
            owner.assigns.append((node.target.id, node.value, scope))
            stack.append((node.value, scope))
            continue
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            kind = "global" if isinstance(node, ast.Global) else "nonlocal"
            scope.declared.update(dict.fromkeys(node.names, kind))
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            scope.stores.add(node.id)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            scope.stores.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            scope.stores.add(node.rest)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            scope.stores.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            scope.assigns.extend((t.id, node.value, scope) for t in node.targets
                                 if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and node.value is not None \
                and isinstance(node.target, ast.Name):
            scope.assigns.append((node.target.id, node.value, scope))
        elif isinstance(node, ast.Call):
            calls.append((node, scope))
        stack.extend((child, scope) for child in ast.iter_child_nodes(node))
    return scopes, calls


def _resolve(scope, name, first=True):
    """The scope whose binding of `name` a read in `scope` sees, as Python
    resolves it, or None when no scope binds it. An enclosing class body is
    skipped whole, its `global` included - except by a read made directly
    in an annotation scope just inside it (PEP 695). `first=False` skips
    `scope` itself when it is a class (a `nonlocal` never binds there)."""
    start = prev = scope
    while scope is not None:
        if first or scope.kind != "class" or (prev is start and start.kind == "annotation"):
            declared = scope.declared.get(name)
            if declared == "global":
                while scope.parent is not None:
                    scope = scope.parent
                return scope
            if declared != "nonlocal" and name in scope.stores:
                return scope
        prev, scope, first = scope, scope.parent, False
    return None


def _bound_argv_bases(tree, consts) -> dict:
    """RM-1146 (2): the `cwd=` of a call whose argv is reached through a
    name - `cmd = [...]; run(cmd, cwd=...)`, `args=cmd`, a walrus, a name
    wrapped in `list(...)` or used as a `+` operand, an alias `cmd = base` -
    keyed by the bound list, tuple or `+` chain. A name is read only in the
    scope Python resolves it to, never a same-named binding elsewhere. An
    extra reading: the root one still selects first."""
    # Exact gate: a bound reading needs an `"ls-files"` list element and a
    # call that runs outside the root (`cwd=` or `**kwargs`); most test
    # modules have neither, so they skip the scope walk.
    verb = outside = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "ls-files":
            verb = True
        elif isinstance(node, ast.keyword) and node.arg in ("cwd", None):
            outside = True
        if verb and outside:
            break
    else:
        return {}
    scopes, calls = _collect_scopes(tree)
    values = {}
    for scope in scopes:
        for name, value, written in scope.assigns:
            owner = scope
            if scope.declared.get(name) == "global":
                owner = _resolve(scope, name)
            elif scope.declared.get(name) == "nonlocal":
                owner = _resolve(scope.parent, name, first=False)
            if owner is not None:
                owner.stores.add(name)
                # The value is read where it is written, not where it binds.
                values.setdefault((id(owner), name), []).append((value, written))
    bound = {}
    # A binding is followed once per directory, and past _MAX_BASES
    # directories once more in any directory (None): an alias cycle ends, and
    # many calls reading one name cost a bounded number of walks.
    walked = {}
    for call, scope in calls:
        argvs = [*call.args[:1], *(kw.value for kw in call.keywords if kw.arg == "args")]
        call_base = _call_base(call, consts) if argvs else ""
        if call_base == "":
            continue
        stack = [(argv, scope, False, call_base) for argv in argvs]
        while stack:
            node, where, via_name, base = stack.pop()
            if isinstance(node, (ast.List, ast.Tuple)) or \
                    (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
                # A literal at the call site already has its call's reading.
                if via_name:
                    bases = bound.setdefault(id(node), [])
                    if None in bases or base in bases:
                        pass
                    elif len(bases) >= _MAX_BASES:
                        bases.append(None)
                    else:
                        bases.append(base)
                if isinstance(node, ast.BinOp):
                    stack.extend((op, where, via_name, base)
                                 for op in _add_operands(node, set())
                                 if not isinstance(op, (ast.List, ast.Tuple)))
            elif isinstance(node, ast.Name):
                owner = _resolve(where, node.id)
                if owner is None:
                    continue
                key = (id(owner), node.id)
                seen = walked.setdefault(key, set())
                if None in seen or base in seen:
                    continue
                if len(seen) >= _MAX_BASES:
                    base = None
                seen.add(base)
                stack.extend((value, written, True, base)
                             for value, written in values.get(key, ()))
            elif isinstance(node, ast.NamedExpr):
                stack.append((node.value, where, True, base))
            elif isinstance(node, ast.Starred):
                stack.append((node.value, where, via_name, base))
            elif isinstance(node, ast.Call):
                stack.extend((part, where, via_name, base)
                             for part in (*node.args, *(kw.value for kw in node.keywords)))
    return bound


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
      directory - against every segment-boundary suffix of a tracked `.md`.
      An argv concatenated from lists is read as one, and a magic pathspec
      (`:(exclude)`, `:!`, `:(top)`, ...) by its magic (RM-1146). An
      option's value (`-x <pattern>`, `--format <format>`) is not a
      pathspec, and a `cwd=` reaches an argv wrapped in `list(...)`
      (RM-1147) or bound to a name, in the name's own scope only
      (RM-1146 (2));
    - a call to `tests._repo_walk.tracked_relpaths` (the whole index);
    - `iter_repo_files` / `repo_files` with a basename glob matching a `.md`
      (their default is `*.py`, so a bare call does not select).
    An argument that cannot be read statically takes the wide reading: a
    false positive costs CI seconds, a false negative is this file's defect.
    """
    consts = _module_constants(tree)
    # RM-1146 (3): read more than once, so a one-shot iterator is not spent.
    tracked_md = list(tracked_md)
    if md_suffixes is None:
        md_suffixes = _md_suffix_index(tracked_md)
    # RM-1145: the directory each call runs its argv in (`cwd=`). ast.walk
    # is breadth-first, so a call is met before the argv list inside it.
    call_bases = {}
    # RM-1146 (1): the elements a `[...] + [...]` operand follows, and the
    # directory its whole chain runs in (kept apart from `call_bases`, so the
    # list's own reading stays what it was).
    argv_prefix = {}
    chain_bases = {}
    chained = set()
    # RM-1147 (b): the `cwd=` of a call whose argv is wrapped in another
    # call, `run(list([...] + [...]), cwd=...)`, for the outermost lists and
    # chains inside it. An extra reading: the old ones still select first.
    wrap_bases = {}
    # RM-1146 (2): the `cwd=` of each call whose argv is bound to a name,
    # keyed by the bound literal (a pre-pass: the binding can come first).
    bound_bases = _bound_argv_bases(tree, consts)
    reasons = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) \
                and id(node) not in chained:
            # One argv in pieces: each list operand reads the operands ahead
            # of it (an unreadable one may hold a `-C`, like a starred
            # element) and the call's `cwd=` reaches every operand.
            bases = [call_bases.get(id(node), "")]
            if id(node) in wrap_bases:
                bases.append(wrap_bases[id(node)])
            bases.extend(bound_bases.get(id(node), ()))
            before = []
            for operand in _add_operands(node, chained):
                if isinstance(operand, (ast.List, ast.Tuple)):
                    argv_prefix[id(operand)] = list(before)
                    chain_bases[id(operand)] = bases
                    before.extend(operand.elts)
                else:
                    before.append(ast.Starred(value=operand, ctx=ast.Load()))
        elif isinstance(node, (ast.List, ast.Tuple)):
            elts = node.elts
            for i, elt in enumerate(elts):
                if isinstance(elt, ast.Constant) and elt.value == "ls-files":
                    # The list's own reading first, then (RM-1146) the one
                    # after the operands ahead of it - so the chain only adds.
                    readings = [(elts[:i], call_bases.get(id(node), ""))]
                    if id(node) in wrap_bases:
                        readings.append((elts[:i], wrap_bases[id(node)]))
                    readings.extend((elts[:i], base) for base in bound_bases.get(id(node), ()))
                    if id(node) in argv_prefix:
                        readings.extend((argv_prefix[id(node)] + elts[:i], base)
                                        for base in chain_bases[id(node)])
                    for before, start in readings:
                        base = _ls_files_base(before, consts, start)
                        if _ls_files_reaches_md(elts[i + 1:], consts, tracked_md, base,
                                                md_suffixes):
                            reasons.add("<index walk: git ls-files>")
                            break
                    break
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            args = node.args
            argvs = [*args[:1], *(kw.value for kw in node.keywords if kw.arg == "args")]
            if any(isinstance(a, (ast.List, ast.Tuple, ast.BinOp)) for a in argvs):
                call_base = _call_base(node, consts)
                for argv in argvs:
                    call_bases[id(argv)] = call_base
            wrapped = [a for a in argvs if isinstance(a, ast.Call)]
            if wrapped:
                call_base = _call_base(node, consts)
                if call_base != "":
                    for inner in _outer_argvs(wrapped):
                        wrap_bases.setdefault(id(inner), call_base)
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
