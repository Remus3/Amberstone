"""Regression guard for the 2026-07-27 skip audit (commit 39aa89ee).

That audit converted 51 always-passing skip guards into real failures but
shipped no machine check, so nothing stopped instance #52. This module is that
check: a static AST pass over every module in the RC-owned test trees that
resolves each skip condition to the set of things it actually depends on, and
fails when a skip fires on something a checkout always has.

The rule, restated mechanically:

    A test may skip only when an ENVIRONMENT CAPABILITY is absent - an OS
    feature, an external binary, an optional third-party import, a network
    endpoint, an opt-in env var, a sibling-repo tree, gitignored machine-local
    state, or the Share mirror path (which deliberately omits data/meta and
    data/meta_build). A tracked-in-git artifact is present in EVERY checkout,
    so a skip gated on one can only fire when the thing under test is broken -
    exactly the moment the test must FAIL.

Two design constraints come from prior guards in this repo that were green over
the very class they existed to catch:

1. The universe is derived from the PRODUCING side. Test modules are globbed
   out of the trees, never listed. `tests/test_no_console_flash_scheduled_tools.py`
   carried a hand-maintained tuple of spawner modules and silently stopped
   covering every file added after it was written.
2. Conditions are RESOLVED, not grepped. That same predecessor searched for a
   literal `0x08000000`, which a module passing the flag to nothing satisfied.
   Here every condition is parsed, its module-level and function-local bindings
   are followed, calls into first-party modules are opened and read, and path
   expressions are evaluated symbolically before being checked against
   `git ls-files`.
"""
from __future__ import annotations

import ast
import fnmatch
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent

# The Share handoff mirrors agents/daemon_slayer/tests verbatim but ships no
# tests/ tree, so this module cannot run there; keying on the mirror PATH rather
# than on file absence follows test_changelog_tracks_engine_version.py:39.
_IS_SHARE_MIRROR = "share" in (p.name.lower() for p in _HERE.parents)

_TEST_TREES = ("tests", "agents/daemon_slayer/tests")

_GIT = shutil.which("git")

if _IS_SHARE_MIRROR:
    pytest.skip("Share/src does not vendor the tests/ tree by design",
                allow_module_level=True)
if _GIT is None:
    pytest.skip("git not on PATH - trackedness is unresolvable without it",
                allow_module_level=True)


# --------------------------------------------------------------------------- #
# Ground truth: what a checkout always has
# --------------------------------------------------------------------------- #
def _git_tracked() -> frozenset[str]:
    out = subprocess.run(
        [_GIT, "ls-files", "-z"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
        timeout=180, check=True,
    ).stdout
    return frozenset(p for p in out.split("\0") if p)


def _suffix_index(tracked: frozenset[str]) -> frozenset[str]:
    """Every segment-boundary suffix of every tracked file AND tracked dir.

    Path expressions in test code are almost never rooted at a literal - they
    hang off `__file__` or a helper constant - so trackedness is decided on the
    resolvable TAIL of the chain.
    """
    out: set[str] = set()
    for rel in tracked:
        parts = rel.split("/")
        n = len(parts)
        for end in range(1, n + 1):
            for start in range(end):
                out.add("/".join(parts[start:end]))
    return frozenset(out)


_TRACKED = _git_tracked()
_TRACKED_SUFFIXES = _suffix_index(_TRACKED)


def _is_tracked_chain(chain: str) -> bool:
    if not chain:
        return False
    if "*" in chain or "?" in chain or "[" in chain:
        pats = (chain, "*/" + chain)
        return any(
            fnmatch.fnmatch(rel, pat) for rel in _TRACKED for pat in pats
        )
    return chain in _TRACKED_SUFFIXES


# --------------------------------------------------------------------------- #
# Skip-construct recognition
# --------------------------------------------------------------------------- #
_DECORATOR_SKIPS = {
    "pytest.mark.skipif", "mark.skipif", "skipif",
    "unittest.skipIf", "skipIf",
    "unittest.skipUnless", "skipUnless",
}
_IMPORTORSKIP = "importorskip"
_BODY_SKIPS = {"pytest.skip", "skip"}
_SKIP_EXC_SUFFIXES = ("SkipTest", "Skipped")

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
           ast.ClassDef, ast.Lambda)
_CALLABLE_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

CAPABILITY = "CAPABILITY"
DEFECT = "DEFECT"
UNRESOLVED = "UNRESOLVED"


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif isinstance(cur, ast.Call):
        parts.append("()")
    else:
        return ""
    return ".".join(reversed(parts))


@dataclass
class _Site:
    rel: str
    line: int
    kind: str
    condition: ast.AST | None
    node: ast.AST

    @property
    def label(self) -> str:
        return f"{self.rel}:{self.line} ({self.kind})"


@dataclass
class _Signals:
    """Everything a skip condition was measured to depend on."""

    platform: bool = False
    env: bool = False
    binary: bool = False
    optional_import: bool = False
    network: bool = False
    tree_shape: bool = False
    external_tree: bool = False
    tracked: set = field(default_factory=set)
    untracked: set = field(default_factory=set)
    firstparty_import: set = field(default_factory=set)

    def merge(self, other: "_Signals") -> None:
        self.platform |= other.platform
        self.env |= other.env
        self.binary |= other.binary
        self.optional_import |= other.optional_import
        self.network |= other.network
        self.tree_shape |= other.tree_shape
        self.external_tree |= other.external_tree
        self.tracked |= other.tracked
        self.untracked |= other.untracked
        self.firstparty_import |= other.firstparty_import

    @property
    def capability(self) -> bool:
        return (self.platform or self.env or self.binary
                or self.optional_import or self.network
                or self.tree_shape or self.external_tree)

    def evidence(self) -> str:
        bits = [n for n in ("platform", "env", "binary", "optional_import",
                            "network", "tree_shape", "external_tree")
                if getattr(self, n)]
        if self.tracked:
            bits.append("tracked=" + ",".join(sorted(self.tracked)))
        if self.untracked:
            bits.append("untracked=" + ",".join(sorted(self.untracked)))
        if self.firstparty_import:
            bits.append("first-party import="
                        + ",".join(sorted(self.firstparty_import)))
        return "; ".join(bits) or "nothing resolvable"


def _classify(sig: _Signals) -> str:
    # A capability signal wins: `not SIDECAR.is_dir() or sys.platform != "win32"`
    # cannot fire on a healthy checkout no matter what else it touches.
    if sig.capability:
        return CAPABILITY
    if sig.firstparty_import or sig.tracked:
        return DEFECT
    if sig.untracked:
        return CAPABILITY
    return UNRESOLVED


# --------------------------------------------------------------------------- #
# Module model: parents, scopes, bindings, imports
# --------------------------------------------------------------------------- #
_OPTIONAL_IMPORT_EXC = {"ImportError", "ModuleNotFoundError", "Exception",
                        "OSError", "AttributeError"}


class _Model:
    """Parsed module plus the lookup tables condition resolution needs."""

    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        try:
            self.rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            self.rel = path.name
        self.tree = ast.parse(source, filename=str(path))
        self.parent: dict[ast.AST, ast.AST] = {}
        self.assigns: dict[ast.AST, dict[str, list[ast.expr]]] = {}
        self.funcs: dict[ast.AST, dict[str, ast.AST]] = {}
        self.imports: dict[str, str] = {}
        self.optional_names: set[str] = set()
        self._index()

    # -- indexing ----------------------------------------------------------
    def _index(self) -> None:
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        for scope in [n for n in ast.walk(self.tree) if isinstance(n, _SCOPES)]:
            assigns: dict[str, list[ast.expr]] = {}
            funcs: dict[str, ast.AST] = {}
            body = getattr(scope, "body", [])
            if not isinstance(body, list):
                body = [body]
            self._scan_body(body, assigns, funcs, guarded=False)
            self.assigns[scope] = assigns
            self.funcs[scope] = funcs

    def _scan_body(self, stmts, assigns, funcs, guarded: bool) -> None:
        for st in stmts:
            if isinstance(st, _CALLABLE_SCOPES):
                funcs[st.name] = st
                continue
            if isinstance(st, ast.ClassDef):
                funcs[st.name] = st
                continue
            if isinstance(st, ast.Assign):
                for tgt in st.targets:
                    if isinstance(tgt, ast.Name):
                        assigns.setdefault(tgt.id, []).append(st.value)
                        if guarded:
                            self.optional_names.add(tgt.id)
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                if st.value is not None:
                    assigns.setdefault(st.target.id, []).append(st.value)
                    if guarded:
                        self.optional_names.add(st.target.id)
            elif isinstance(st, (ast.Import, ast.ImportFrom)):
                self._record_import(st, guarded)
            elif isinstance(st, ast.Try):
                inner = guarded or _try_swallows_import(st)
                self._scan_body(st.body, assigns, funcs, inner)
                for h in st.handlers:
                    self._scan_body(h.body, assigns, funcs, inner)
                self._scan_body(st.orelse, assigns, funcs, guarded)
                self._scan_body(st.finalbody, assigns, funcs, guarded)
                continue
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(st, attr, None)
                if isinstance(sub, list) and not isinstance(st, ast.Try):
                    self._scan_body(sub, assigns, funcs, guarded)

    def _record_import(self, st, guarded: bool) -> None:
        if isinstance(st, ast.Import):
            for a in st.names:
                bound = a.asname or a.name.split(".")[0]
                self.imports[bound] = a.name
                if guarded:
                    self.optional_names.add(bound)
        else:
            base = st.module or ""
            for a in st.names:
                bound = a.asname or a.name
                self.imports[bound] = f"{base}.{a.name}" if base else a.name
                if guarded:
                    self.optional_names.add(bound)

    # -- lookups -----------------------------------------------------------
    def scope_of(self, node: ast.AST) -> ast.AST:
        cur = self.parent.get(node)
        while cur is not None and not isinstance(cur, _SCOPES):
            cur = self.parent.get(cur)
        return cur if cur is not None else self.tree

    def scope_chain(self, node: ast.AST) -> list[ast.AST]:
        chain: list[ast.AST] = []
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, _SCOPES):
                chain.append(cur)
            cur = self.parent.get(cur)
        if self.tree not in chain:
            chain.append(self.tree)
        return chain

    def lookup(self, name: str, scope: ast.AST) -> list[ast.expr]:
        for sc in self.scope_chain(scope):
            hit = self.assigns.get(sc, {}).get(name)
            if hit:
                return hit
        return []

    def lookup_func(self, name: str, scope: ast.AST):
        for sc in self.scope_chain(scope):
            hit = self.funcs.get(sc, {}).get(name)
            if hit is not None:
                return hit
        return None

    def file_segments(self) -> list[str]:
        return self.rel.split("/")


def _try_swallows_import(node: ast.Try) -> bool:
    if not any(isinstance(s, (ast.Import, ast.ImportFrom))
               for s in ast.walk(node)):
        return False
    for h in node.handlers:
        if h.type is None:
            return True
        for name in _exc_names(h.type):
            if name in _OPTIONAL_IMPORT_EXC:
                return True
    return False


def _exc_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Tuple):
        out: list[str] = []
        for e in node.elts:
            out.extend(_exc_names(e))
        return out
    dotted = _dotted(node)
    return [dotted.rsplit(".", 1)[-1]] if dotted else []


_MODEL_CACHE: dict[Path, _Model | None] = {}


def _model_for(path: Path) -> _Model | None:
    key = path.resolve()
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    model: _Model | None = None
    try:
        model = _Model(key, key.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        model = None
    _MODEL_CACHE[key] = model
    return model


def _first_party_file(dotted: str) -> Path | None:
    """Resolve an import target to a file in THIS repo, or None if third party."""
    if not dotted:
        return None
    parts = dotted.split(".")
    while parts:
        cand = _REPO_ROOT.joinpath(*parts).with_suffix(".py")
        if cand.is_file():
            return cand
        pkg = _REPO_ROOT.joinpath(*parts) / "__init__.py"
        if pkg.is_file():
            return pkg
        parts = parts[:-1]
    return None


# --------------------------------------------------------------------------- #
# Symbolic path evaluation
# --------------------------------------------------------------------------- #
_ABS = "\x00abs\x00"
_PASSTHROUGH_CALLS = {"resolve", "absolute", "expanduser", "as_posix",
                      "abspath", "realpath", "normpath", "strip", "rstrip"}
_PATHY_CALLS = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath",
                "fspath"}


def _is_abs_literal(s: str) -> bool:
    return bool(s) and (s.startswith("/")
                        or (len(s) > 1 and s[1] == ":" and s[0].isalpha()))


def _segments(expr: ast.AST, model: _Model, scope: ast.AST,
              seen: frozenset, depth: int) -> list[str] | None:
    """Evaluate a path expression to segments; None marks an opaque segment."""
    if depth > 12:
        return None

    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        raw = expr.value.replace("\\", "/")
        if _is_abs_literal(raw):
            return [_ABS + raw.rstrip("/")]
        return [p for p in raw.split("/") if p not in ("", ".")]

    if isinstance(expr, ast.JoinedStr):
        out: list[str] = []
        for part in expr.values:
            got = _segments(part, model, scope, seen, depth + 1)
            out.extend(got if got is not None else [None])
        return out

    if isinstance(expr, ast.FormattedValue):
        return [None]

    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _segments(expr.left, model, scope, seen, depth + 1)
        right = _segments(expr.right, model, scope, seen, depth + 1)
        return (left if left is not None else [None]) + \
               (right if right is not None else [None])

    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return model.file_segments()
        if expr.id in seen:
            return None
        bound = model.lookup(expr.id, scope)
        if len(bound) == 1:
            return _segments(bound[0], model, scope,
                             seen | {expr.id}, depth + 1)
        return None

    if isinstance(expr, ast.Attribute):
        if expr.attr == "parent":
            base = _segments(expr.value, model, scope, seen, depth + 1)
            return base[:-1] if base else None
        if expr.attr in ("parents", "parts", "name", "stem", "suffix"):
            return None
        return _cross_module_segments(expr, model, scope, seen, depth)

    if isinstance(expr, ast.Call):
        return _call_segments(expr, model, scope, seen, depth)

    return None


def _cross_module_segments(expr: ast.Attribute, model: _Model, scope,
                           seen: frozenset, depth: int) -> list[str] | None:
    if not isinstance(expr.value, ast.Name):
        return None
    target = _resolve_module(expr.value.id, model)
    if target is None:
        return None
    bound = target.assigns.get(target.tree, {}).get(expr.attr)
    if bound and len(bound) == 1:
        return _segments(bound[0], target, target.tree, seen, depth + 1)
    return None


def _resolve_module(alias: str, model: _Model) -> _Model | None:
    dotted = model.imports.get(alias)
    if not dotted:
        return None
    path = _first_party_file(dotted)
    if path is None or path.resolve() == model.path:
        return None
    return _model_for(path)


def _call_segments(expr: ast.Call, model: _Model, scope,
                   seen: frozenset, depth: int) -> list[str] | None:
    fname = _dotted(expr.func)
    tail = fname.rsplit(".", 1)[-1]
    args = expr.args

    if tail in _PATHY_CALLS and args:
        return _segments(args[0], model, scope, seen, depth + 1)
    if tail == "join" and fname.endswith("path.join"):
        out: list[str] = []
        for a in args:
            got = _segments(a, model, scope, seen, depth + 1)
            out.extend(got if got is not None else [None])
        return out
    if tail == "joinpath" and isinstance(expr.func, ast.Attribute):
        out = _segments(expr.func.value, model, scope, seen, depth + 1) or [None]
        for a in args:
            got = _segments(a, model, scope, seen, depth + 1)
            out = out + (got if got is not None else [None])
        return out
    if tail == "dirname" and args:
        base = _segments(args[0], model, scope, seen, depth + 1)
        return base[:-1] if base else None
    if tail == "basename" and args:
        base = _segments(args[0], model, scope, seen, depth + 1)
        return base[-1:] if base else None
    if tail in _PASSTHROUGH_CALLS:
        if isinstance(expr.func, ast.Attribute):
            return _segments(expr.func.value, model, scope, seen, depth + 1)
        if args:
            return _segments(args[0], model, scope, seen, depth + 1)
    if tail in ("sorted", "list", "next", "str"):
        if args:
            return _segments(args[0], model, scope, seen, depth + 1)
    if tail in ("glob", "iglob", "rglob"):
        if fname.endswith("glob.glob") or fname.endswith("glob.iglob"):
            return _segments(args[0], model, scope, seen, depth + 1) if args else None
        if isinstance(expr.func, ast.Attribute):
            base = _segments(expr.func.value, model, scope, seen, depth + 1) or [None]
            pat = _segments(args[0], model, scope, seen, depth + 1) if args else None
            return base + (pat if pat is not None else [None])
    return None


def _record_chain(segs: list[str] | None, sig: _Signals) -> None:
    """Turn evaluated segments into a tracked / untracked verdict."""
    if not segs:
        return
    for s in segs:
        if s and s.startswith(_ABS):
            root = s[len(_ABS):]
            try:
                inside = _REPO_ROOT.resolve().is_relative_to(Path(root))
            except (OSError, ValueError):
                inside = False
            if not inside:
                sig.external_tree = True
                return
    tail: list[str] = []
    for s in reversed(segs):
        if s is None or s.startswith(_ABS):
            break
        tail.append(s)
    if not tail:
        return
    chain = "/".join(reversed(tail))
    if _is_tracked_chain(chain):
        sig.tracked.add(chain)
    else:
        sig.untracked.add(chain)


# --------------------------------------------------------------------------- #
# Condition resolution
# --------------------------------------------------------------------------- #
_PLATFORM_DOTTED = {"sys.platform", "os.name", "platform.system",
                    "platform.machine", "platform.release"}
_ENV_CALLS = {"getenv", "environ"}
_NETWORK_TOKENS = {"urlopen", "urlretrieve", "create_connection", "socket",
                   "gethostbyname", "connect", "getaddrinfo"}
_NETWORK_ROOTS = {"requests", "httpx", "urllib", "socket", "http", "aiohttp"}
_PATH_PREDICATES = {"exists", "is_file", "is_dir", "is_symlink", "isfile",
                    "isdir", "islink", "read_text", "read_bytes", "stat",
                    "listdir", "iterdir", "open"}


class _Ctx:
    """Accumulator plus the set of path expressions already accounted for.

    Without the consumed set, walking `ROOT / "data" / "rewind_history.db"`
    records the inner `ROOT / "data"` slice too, and `data` is a tracked
    directory - so a gitignored corpus reads as a tracked artifact. Only the
    outermost path expression is a real reference.
    """

    def __init__(self) -> None:
        self.sig = _Signals()
        self.consumed: set[int] = set()

    def take(self, expr: ast.AST | None, model: _Model, scope: ast.AST,
             seen: frozenset) -> None:
        if expr is None or id(expr) in self.consumed:
            return
        for n in ast.walk(expr):
            self.consumed.add(id(n))
        _record_chain(_segments(expr, model, scope, seen, 0), self.sig)


_MAX_RESOLUTION_DEPTH = 8


def _collect(node: ast.AST, model: _Model, scope: ast.AST, ctx: _Ctx,
             seen: frozenset, depth: int) -> None:
    """Walk a condition (or a whole region) accumulating what it depends on.

    `depth` counts RESOLUTION steps only - following a binding, entering a
    helper, crossing a module. Walking into a child node is free, otherwise a
    gate a few statements deep in a helper falls off the end of the budget and
    silently reads as unresolvable.
    """
    if node is None:
        return
    sig = ctx.sig

    if isinstance(node, ast.Attribute):
        dotted = _dotted(node)
        if dotted in _PLATFORM_DOTTED:
            sig.platform = True
        if dotted.split(".")[-1] == "environ" or dotted.startswith("environ"):
            sig.env = True
        if node.attr in ("parents", "parts") and _derives_from_file(
                node.value, model, scope, seen, 0):
            sig.tree_shape = True
        if node.attr in _PATH_PREDICATES:
            ctx.take(node.value, model, scope, seen)
        _cross_module_attr(node, model, ctx, seen, depth)

    elif isinstance(node, ast.Call):
        _collect_call(node, model, scope, ctx, seen, depth)

    elif isinstance(node, ast.Name):
        if node.id in model.optional_names:
            sig.optional_import = True
        if node.id not in seen and depth < _MAX_RESOLUTION_DEPTH:
            for bound in model.lookup(node.id, scope):
                _collect(bound, model, scope, ctx, seen | {node.id}, depth + 1)

    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        _collect_import(node, sig)
        return

    elif isinstance(node, ast.Try):
        if _try_swallows_import(node):
            for st in node.body:
                if isinstance(st, (ast.Import, ast.ImportFrom)):
                    _collect_import(st, sig)

    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        ctx.take(node, model, scope, seen)

    for child in ast.iter_child_nodes(node):
        _collect(child, model, scope, ctx, seen, depth)


def _derives_from_file(expr: ast.AST | None, model: _Model, scope: ast.AST,
                       seen: frozenset, depth: int) -> bool:
    """True when the expression traces back to this module's own __file__."""
    if expr is None or depth > _MAX_RESOLUTION_DEPTH:
        return False
    for n in ast.walk(expr):
        if not isinstance(n, ast.Name):
            continue
        if n.id == "__file__":
            return True
        if n.id in seen:
            continue
        for bound in model.lookup(n.id, scope):
            if _derives_from_file(bound, model, scope, seen | {n.id},
                                  depth + 1):
                return True
    return False


def _collect_import(node: ast.AST, sig: _Signals) -> None:
    if isinstance(node, ast.Import):
        targets = [a.name for a in node.names]
    else:
        base = node.module or ""
        targets = [f"{base}.{a.name}" if base else a.name for a in node.names]
    for dotted in targets:
        if _first_party_file(dotted) is not None:
            sig.firstparty_import.add(dotted)
        else:
            sig.optional_import = True


def _cross_module_attr(node: ast.Attribute, model: _Model, ctx: _Ctx,
                       seen: frozenset, depth: int) -> None:
    if not isinstance(node.value, ast.Name) or depth >= _MAX_RESOLUTION_DEPTH:
        return
    target = _resolve_module(node.value.id, model)
    if target is None:
        return
    _enter_symbol(target, node.attr, model, ctx, seen, depth)


def _enter_symbol(target: _Model, symbol: str, model: _Model, ctx: _Ctx,
                  seen: frozenset, depth: int) -> None:
    key = f"{target.rel}::{symbol}"
    if key in seen:
        return
    if symbol in target.optional_names:
        ctx.sig.optional_import = True
    fn = target.funcs.get(target.tree, {}).get(symbol)
    if fn is not None:
        _collect(fn, target, fn, ctx, seen | {key}, depth + 1)
        return
    for bound in target.assigns.get(target.tree, {}).get(symbol, []):
        _collect(bound, target, target.tree, ctx, seen | {key}, depth + 1)


def _positional_params(fn: ast.AST) -> list[str]:
    args = getattr(fn, "args", None)
    if args is None:
        return []
    return [a.arg for a in list(args.posonlyargs) + list(args.args)]


def _enter_local_function(fn: ast.AST, call: ast.Call, model: _Model,
                          ctx: _Ctx, seen: frozenset, depth: int) -> None:
    """Descend into a helper with its ARGUMENTS bound to its parameters.

    `if not _lane_counts(LW_ROOT):` says nothing until LW_ROOT reaches the
    parameter the helper joins its paths onto.
    """
    key = f"{model.rel}::{getattr(fn, 'name', '?')}"
    if key in seen or depth >= _MAX_RESOLUTION_DEPTH:
        return
    saved = model.assigns.get(fn, {})
    overlay = dict(saved)
    for param, arg in zip(_positional_params(fn), call.args):
        overlay.setdefault(param, [arg])
    model.assigns[fn] = overlay
    try:
        _collect(fn, model, fn, ctx, seen | {key}, depth + 1)
    finally:
        model.assigns[fn] = saved


def _collect_call(node: ast.Call, model: _Model, scope: ast.AST,
                  ctx: _Ctx, seen: frozenset, depth: int) -> None:
    sig = ctx.sig
    fname = _dotted(node.func)
    tail = fname.rsplit(".", 1)[-1]
    root = fname.split(".")[0]

    if fname in ("shutil.which", "which", "distutils.spawn.find_executable"):
        sig.binary = True
    if tail in _ENV_CALLS or fname.startswith("os.environ"):
        sig.env = True
    if tail in ("find_spec", "import_module", "importorskip", "util.find_spec"):
        sig.optional_import = True
    if tail in _NETWORK_TOKENS or root in _NETWORK_ROOTS:
        sig.network = True
    if tail in _PATH_PREDICATES and isinstance(node.func, ast.Attribute):
        ctx.take(node.func.value, model, scope, seen)
    if tail in _PATH_PREDICATES and node.args and fname.startswith(
            ("os.path.", "path.", "os.")):
        ctx.take(node.args[0], model, scope, seen)
    if tail in ("glob", "iglob", "rglob"):
        ctx.take(node, model, scope, seen)

    # A gate is routinely a helper call; open the helper and read it.
    if isinstance(node.func, ast.Name):
        local = model.lookup_func(node.func.id, scope)
        if local is not None:
            _enter_local_function(local, node, model, ctx, seen, depth)
        else:
            imported = _resolve_module(node.func.id, model)
            if imported is not None:
                _enter_symbol(imported, node.func.id, model, ctx, seen, depth)
    elif isinstance(node.func, ast.Attribute):
        _cross_module_attr(node.func, model, ctx, seen, depth)


# --------------------------------------------------------------------------- #
# Site discovery
# --------------------------------------------------------------------------- #
def _skip_sites(model: _Model) -> list[_Site]:
    sites: list[_Site] = []
    for node in ast.walk(model.tree):
        if isinstance(node, ast.Raise):
            exc = node.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            name = _dotted(target).rsplit(".", 1)[-1] if target is not None else ""
            if name.endswith(_SKIP_EXC_SUFFIXES):
                sites.append(_Site(model.rel, node.lineno, "raise SkipTest",
                                   None, node))
            continue
        if not isinstance(node, ast.Call):
            continue
        fname = _canonical_call(_dotted(node.func), model)
        tail = fname.rsplit(".", 1)[-1]
        if fname in _DECORATOR_SKIPS or tail in ("skipif", "skipIf", "skipUnless"):
            cond = node.args[0] if node.args else _kw(node, "condition")
            sites.append(_Site(model.rel, node.lineno, fname, cond, node))
        elif tail == _IMPORTORSKIP:
            cond = node.args[0] if node.args else None
            sites.append(_Site(model.rel, node.lineno, "importorskip",
                               cond, node))
        elif fname in _BODY_SKIPS or tail == "skipTest":
            sites.append(_Site(model.rel, node.lineno, fname or tail,
                               None, node))
    sites.sort(key=lambda s: (s.rel, s.line))
    return sites


def _canonical_call(fname: str, model: _Model) -> str:
    """Rewrite an aliased module head back to its real name.

    ``pytest.skip`` is matched on the FULL dotted chain rather than the tail,
    because a bare ``.skip`` tail would collect unrelated calls. That makes
    ``import pytest as _p`` + ``_p.skip(...)`` invisible to the scanner - not
    misclassified, absent - which is the one evasion a guard must not have.
    """
    head, sep, rest = fname.partition(".")
    origin = model.imports.get(head)
    if origin and sep:
        return origin + "." + rest
    return fname


def _kw(node: ast.Call, name: str):
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return None


def _context_conditions(model: _Model, node: ast.AST) -> list[ast.AST]:
    """The nearest guards around a bare skip: enclosing if / while / except."""
    out: list[ast.AST] = []
    cur: ast.AST | None = node
    parent = model.parent.get(cur)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, (ast.If, ast.While)):
            out.append(parent.test)
        elif isinstance(parent, ast.ExceptHandler):
            if parent.type is not None:
                out.append(parent.type)
            grand = model.parent.get(parent)
            if isinstance(grand, ast.Try):
                out.extend(grand.body)
        elif isinstance(parent, ast.Assert):
            out.append(parent.test)
        cur, parent = parent, model.parent.get(parent)
    return out


def _signals_for(model: _Model, site: _Site) -> _Signals:
    scope = model.scope_of(site.node)

    if site.kind == "importorskip":
        sig = _Signals()
        cond = site.condition
        if isinstance(cond, ast.Constant) and isinstance(cond.value, str):
            if _first_party_file(cond.value) is not None:
                sig.firstparty_import.add(cond.value)
            else:
                sig.optional_import = True
        else:
            sig.optional_import = True
        return sig

    if site.condition is not None:
        ctx = _Ctx()
        _collect(site.condition, model, scope, ctx, frozenset(), 0)
        return ctx.sig

    # Bare skip: nearest guards first, then widen to the enclosing function.
    near = _Ctx()
    for cond in _context_conditions(model, site.node):
        _collect(cond, model, scope, near, frozenset(), 0)
    if _classify(near.sig) != UNRESOLVED:
        return near.sig
    if isinstance(scope, _CALLABLE_SCOPES):
        wide = _Ctx()
        _collect(scope, model, scope, wide, frozenset(), 0)
        near.sig.merge(wide.sig)
    return near.sig


# --------------------------------------------------------------------------- #
# The scan
# --------------------------------------------------------------------------- #
def _iter_modules() -> list[Path]:
    out: list[Path] = []
    for tree in _TEST_TREES:
        out.extend(sorted((_REPO_ROOT / tree).rglob("*.py")))
    return out


@dataclass
class _Finding:
    site: _Site
    verdict: str
    evidence: str
    gates_on: frozenset


def scan_source(rel: str, source: str) -> list[_Finding]:
    """Classify every skip construct in one module's source."""
    model = _Model(_REPO_ROOT / rel, source)
    model.rel = rel
    findings: list[_Finding] = []
    for site in _skip_sites(model):
        sig = _signals_for(model, site)
        findings.append(_Finding(
            site, _classify(sig), sig.evidence(),
            frozenset(sig.tracked | sig.firstparty_import),
        ))
    return findings


def scan_tree() -> list[_Finding]:
    findings: list[_Finding] = []
    for path in _iter_modules():
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        findings.extend(
            scan_source(rel, path.read_text(encoding="utf-8", errors="replace"))
        )
    return findings


# --------------------------------------------------------------------------- #
# Reviewed exemptions
# --------------------------------------------------------------------------- #
# Each entry is a reviewed exemption: the module, the EXACT tracked artifacts
# its skip is excused for, and why. Keyed by module rather than by line so a
# moved site stays covered, but pinned to the artifact set so a NEW skip in the
# same module - or the same skip re-aimed at a different tracked file - still
# fails. The three tests below assert every entry still exists on disk, still
# flags, and is still excusing exactly what it claims, so neither a deleted
# file nor a fixed one can rot an exemption into a silent pass.
_ALLOWLIST: dict[str, tuple[frozenset, str]] = {
    "tests/test_ds_ability_data_status_rm95.py": (
        frozenset({"data/daemon_slayer", "data/daemon_slayer/current.txt"}),
        "FUTURE row in docs/SKIPIF_AUDIT_2026-07-27.md - the skip pins an RM-95 "
        "finding to patch 16.14.1 and is decidable against tracked current.txt "
        "today, but converting it turns CI red on the next patch bump. Needs a "
        "re-pin policy, not a mechanical flip.",
    ),
}


def _excused(finding: _Finding) -> bool:
    entry = _ALLOWLIST.get(finding.site.rel)
    if entry is None or not finding.gates_on:
        return False
    return finding.gates_on <= entry[0]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_universe_is_globbed_not_listed():
    """The producing side is the glob; a hand list is how a guard goes blind."""
    mods = _iter_modules()
    assert len(mods) > 400, f"only {len(mods)} test modules found - glob broke"
    rels = {m.resolve().relative_to(_REPO_ROOT).as_posix() for m in mods}
    assert "tests/test_skip_condition_hygiene.py" in rels
    assert any(r.startswith("agents/daemon_slayer/tests/") for r in rels)


def test_tracked_index_resolves_known_paths():
    """Trackedness comes from git, and the suffix index must preserve it."""
    assert _is_tracked_chain("data/daemon_slayer/current.txt")
    assert _is_tracked_chain("web/legacy_index.html")
    assert _is_tracked_chain("ops/rc_config.json")
    assert not _is_tracked_chain("data/rewind_history.db")
    assert not _is_tracked_chain("dist/daemon_slayer_bundle.json")
    assert not _is_tracked_chain("_archive/2026-05-01-audit/tft/comp_control.py")


def test_every_skip_gates_on_an_environment_capability():
    """The guard itself: no skip may fire on something a checkout always has."""
    bad = [
        f"  {f.site.label} -> {f.verdict}: {f.evidence}"
        for f in scan_tree()
        if f.verdict != CAPABILITY and not _excused(f)
    ]
    assert not bad, (
        "skip constructs that do not gate on an absent environment "
        "capability - a skip here is an always-passing guard, and the thing "
        "under test being absent must FAIL instead (see "
        "docs/SKIPIF_AUDIT_2026-07-27.md):\n" + "\n".join(bad)
    )


def test_allowlisted_modules_still_exist():
    """A deleted file must not rot an exemption into a silent pass."""
    missing = [rel for rel in _ALLOWLIST if not (_REPO_ROOT / rel).is_file()]
    assert not missing, (
        f"allowlisted modules no longer on disk: {missing} - delete the "
        "_ALLOWLIST entries with them"
    )


def test_allowlisted_modules_still_flag():
    """An exemption that no longer excuses anything is dead weight."""
    stale = []
    for rel in _ALLOWLIST:
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        if all(f.verdict == CAPABILITY for f in scan_source(rel, src)):
            stale.append(rel)
    assert not stale, (
        f"_ALLOWLIST entries that no longer flag: {stale} - the underlying "
        "skip was fixed or removed, so drop the exemption"
    )


def test_allowlist_excuses_exactly_what_it_claims():
    """The pinned artifact set must still be the one being excused."""
    drifted = []
    for rel, (claimed, _) in _ALLOWLIST.items():
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        actual: set = set()
        for f in scan_source(rel, src):
            if f.verdict != CAPABILITY:
                actual |= set(f.gates_on)
        if actual != set(claimed):
            drifted.append(f"{rel}: claims {sorted(claimed)}, flags "
                           f"{sorted(actual)}")
    assert not drifted, (
        "allowlist entries no longer describe the skip they exempt - re-review "
        "each before re-pinning:\n" + "\n".join(drifted)
    )


# --- mutation probes: the teeth, pinned in-suite ---------------------------- #
_DEFECT_MUTATIONS = {
    "mark_skipif_on_tracked_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
@pytest.mark.skipif(not (REPO / "data" / "daemon_slayer" / "current.txt").exists(),
                    reason="no patch pointer")
def test_thing():
    assert True
''',
    "bare_skip_on_tracked_path": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        pytest.skip("config absent")
    assert p.read_text()
''',
    "aliased_pytest_bare_skip_on_tracked_path": '''
import pytest as _p
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    p = REPO / "ops" / "rc_config.json"
    if not p.is_file():
        _p.skip("config absent")
    assert p.read_text()
''',
    "unittest_skipunless_on_tracked_path": '''
import os
import unittest
class T(unittest.TestCase):
    @unittest.skipUnless(os.path.exists("web/legacy_index.html"), "absent")
    def test_thing(self):
        self.assertTrue(True)
''',
    "helper_gate_reading_a_tracked_file": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def _patch():
    return (REPO / "data" / "daemon_slayer" / "current.txt").read_text().strip()
def test_thing():
    if _patch() != "16.14.1":
        pytest.skip("pinned")
    assert True
''',
    "importorskip_on_a_first_party_module": '''
import pytest
mod = pytest.importorskip("core.build_order")
def test_thing():
    assert mod
''',
    "skiptest_raise_on_tracked_path": '''
import unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
class T(unittest.TestCase):
    def test_thing(self):
        p = REPO / "data" / "daemon_slayer" / "current.txt"
        if not p.exists():
            raise unittest.SkipTest("no pointer")
        self.assertTrue(p.read_text())
''',
}

_CAPABILITY_CONTROLS = {
    "platform": '''
import sys
import pytest
@pytest.mark.skipif(sys.platform != "win32", reason="win32 only")
def test_thing():
    assert True
''',
    "external_binary": '''
import shutil
import pytest
NODE = shutil.which("node")
def test_thing():
    if not NODE:
        pytest.skip("node not on PATH")
    assert NODE
''',
    "gitignored_artifact": '''
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def test_thing():
    db = REPO / "data" / "rewind_history.db"
    if not db.is_file():
        pytest.skip("machine-local corpus absent")
    assert db
''',
    "env_opt_in": '''
import os
import unittest
@unittest.skipUnless(os.environ.get("RC_LIVE_LOBBY"), "opt-in")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
''',
    "optional_third_party": '''
import pytest
np = pytest.importorskip("numpy")
def test_thing():
    assert np
''',
    "share_mirror_path": '''
import unittest
from pathlib import Path
_IS_SHARE_MIRROR = "share" in (p.name.lower() for p in Path(__file__).resolve().parents)
@unittest.skipIf(_IS_SHARE_MIRROR, "Share/src does not vendor data/meta")
class T(unittest.TestCase):
    def test_thing(self):
        self.assertTrue(True)
''',
}


@pytest.mark.parametrize("name", sorted(_DEFECT_MUTATIONS))
def test_mutation_defective_skip_is_flagged(name):
    """Teeth check: each synthetic always-pass guard must be caught."""
    findings = scan_source("tests/test_mutant.py", _DEFECT_MUTATIONS[name])
    assert findings, f"{name}: no skip site found at all"
    assert any(f.verdict == DEFECT for f in findings), (
        f"{name}: the guard did not flag a skip gated on tracked state - "
        + "; ".join(f"{f.verdict}:{f.evidence}" for f in findings)
    )


@pytest.mark.parametrize("name", sorted(_CAPABILITY_CONTROLS))
def test_mutation_capability_skip_is_not_flagged(name):
    """False-positive side: a legitimate capability skip must stay green."""
    findings = scan_source("tests/test_mutant.py", _CAPABILITY_CONTROLS[name])
    assert findings, f"{name}: no skip site found at all"
    bad = [f"{f.verdict}:{f.evidence}" for f in findings
           if f.verdict != CAPABILITY]
    assert not bad, f"{name}: legitimate capability skip flagged - {bad}"


def test_mutation_on_a_real_module_goes_red_then_green(tmp_path):
    """The same probe against a REAL module's text, on disk, both ways."""
    real = _REPO_ROOT / "tests" / "test_pro_match_index.py"
    clean = real.read_text(encoding="utf-8")
    baseline = scan_source("tests/test_pro_match_index.py", clean)
    assert baseline, "no skip sites in the control module"
    assert all(f.verdict == CAPABILITY for f in baseline), (
        "control module is not clean: "
        + "; ".join(f"{f.site.label}={f.verdict}" for f in baseline)
    )

    mutant = tmp_path / "test_mutated.py"
    mutant.write_text(clean + _DEFECT_MUTATIONS["bare_skip_on_tracked_path"],
                      encoding="utf-8")
    after = scan_source("tests/test_pro_match_index.py",
                        mutant.read_text(encoding="utf-8"))
    assert any(f.verdict == DEFECT for f in after), (
        "injecting a skip gated on tracked ops/rc_config.json did not flag: "
        + "; ".join(f"{f.site.label}={f.verdict}" for f in after)
    )


def test_allowlist_does_not_excuse_a_different_defect():
    """An exemption covers one reviewed artifact, not the whole module."""
    rel = next(iter(_ALLOWLIST))
    src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = src + _DEFECT_MUTATIONS["unittest_skipunless_on_tracked_path"]
    fresh = [f for f in scan_source(rel, injected)
             if f.verdict != CAPABILITY and not _excused(f)]
    assert fresh, (
        f"injecting a skip on tracked web/legacy_index.html into the "
        f"allowlisted {rel} was swallowed by its exemption"
    )


def test_known_real_sites_classify_as_documented():
    """Anchors from the audit table, so a classifier regression is loud."""
    by_module: dict[str, list[_Finding]] = {}
    for f in scan_tree():
        by_module.setdefault(f.site.rel, []).append(f)

    def verdicts(rel):
        return {f.verdict for f in by_module.get(rel, [])}

    # network liveness, external binary, sibling repo, win32, gitignored data
    assert verdicts("tests/test_build_order_variants.py") == {CAPABILITY}
    assert verdicts("tests/test_coach_choices_trigger_render.py") == {CAPABILITY}
    assert verdicts("tests/test_loop_concurrency.py") == {CAPABILITY}
    assert verdicts("tests/test_hotkey_lowlevel_decoder.py") == {CAPABILITY}
    assert verdicts("tests/test_pro_match_index.py") == {CAPABILITY}
    assert verdicts(
        "agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py"
    ) == {CAPABILITY}

    # Guards ABOUT skips must not be mistaken for skip sites.
    stack = by_module.get(
        "agents/daemon_slayer/tests/test_stack_ramp_schema_126.py", [])
    assert not stack, f"BurstSkipTests misread as a skip site: {stack}"
