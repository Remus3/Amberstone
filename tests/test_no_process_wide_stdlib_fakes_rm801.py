"""RM-801 guard: no test fakes a SHARED stdlib attribute process-wide.

`monkeypatch.setattr(mod.subprocess, "run", fake)` (likewise `Popen`,
`urllib.request.urlopen`, `socket.socket`) rebinds the attribute on the one
module object every thread in the pytest(-xdist) worker shares. A leftover
server, poller or fixture thread from an earlier test file then calls the fake
too: its calls land in the fake's record and its own I/O breaks. That is the
CI run 39877078008 failure shape (gw0, linux; LEDGER 1758, fix `ea008366b`).

The scoped form rebinds the MODULE UNDER TEST's own global name to a view of
the real module (`tests/_module_view.py`):

    bind_module_view(monkeypatch, mod, "subprocess", run=fake)

Detection is on the AST, never the text (memory
`feedback_importorskip_vs_rm515_guard`): every `*.setattr(...)`,
builtin `setattr(...)`, `patch(...)` / `patch.object(...)` /
`patch.multiple(...)` call (decorators included) and every plain attribute
assignment, in every .py under `tests/` and `agents/daemon_slayer/tests/`. A
patch target is process-wide when its object expression ends in a shared
stdlib module name (`subprocess`, `urllib.request` / `request`, `socket`) -
through an import alias of the test file, or an alias any tracked module of
the repo binds (`ddr.urllib_request` for `from urllib import request as
urllib_request`) - or its dotted string target ends in one
(`"subprocess.run"`, `"tools.x.subprocess.run"`). A non-literal attribute
name on a shared module (`for attr in (...): setattr(subprocess, attr, f)`)
is resolved through a constant for-loop, else flagged. A value wrapped in
`this_thread_only(...)` is the sanctioned thread-scoped form and passes.

RM-815 closed six shapes the RM-801 verifier found it blind to: a
`sys.modules['subprocess']` entry (stored, patched or read through), a plain
alias variable (`sp = mod.subprocess`, also via `importlib.import_module`),
the module's own dict (`setitem(subprocess.__dict__, ...)`, `vars(...)`,
`patch.dict`), `patch.multiple('subprocess', ...)` on a string target, a
keyword-only `patch.object(target=..., attribute=...)`, and `delattr` /
`del` (siblings swept: `delitem`, `setdefault` / `update`, `import sys as
_s`, `from sys import modules`).

RM-880 (a) widened the attribute set to the 25 process-wide sites in 14 files
the RM-815 census found: `os.name` / `os.kill` / `os.killpg`, `os.path.exists`
/ `isfile` / `isdir` (`path` counts only under an `os`: `x.path` is a request's
or a fixture's path far more often than os.path), `shutil.which`,
`socketserver.BaseServer.serve_forever` and `ssl.SSLContext.load_cert_chain`
(class attributes: one patch reaches every instance). A non-literal name
bound by `@pytest.mark.parametrize("NAME", [...])` resolves like a constant
for-loop, scoped to the decorated function. The RM-411 fault helper is ruled
scoped by design (ALLOWLIST below). Still RM-880: the `this_thread_only`
late-thread gap (b), the scope-aware alias pass (c), the tripwires (d).
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import threading
import types
import urllib.request
from functools import lru_cache
from pathlib import Path

import pytest

from tests._module_view import (
    bind_module_view,
    bind_os_path,
    bind_subprocess,
    bind_urlopen,
    bind_which,
    this_thread_only,
)
from tests._repo_walk import iter_repo_files, self_check

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("tests", "agents/daemon_slayer/tests")

# Shared stdlib module (terminal name of the patched object) -> the attributes
# whose process-wide rebinding this guard refuses.
SHARED_ATTRS: dict[str, frozenset[str]] = {
    "subprocess": frozenset({
        "run", "Popen", "call", "check_call", "check_output",
        "getoutput", "getstatusoutput",
    }),
    # `urllib.request` ends in `request`; only urllib.request owns `urlopen`.
    "request": frozenset({"urlopen"}),
    "socket": frozenset({"socket", "create_connection", "getaddrinfo"}),
    # RM-880: the shared attributes the RM-815 census found faked process-wide.
    "os": frozenset({"name", "kill", "killpg"}),
    # `os.path` ends in `path`; read as os.path only under an `os` (_QUALIFIED).
    "path": frozenset({"exists", "isfile", "isdir"}),
    "shutil": frozenset({"which"}),
    # Class attributes: patching one rebinds it for every instance.
    "BaseServer": frozenset({"serve_forever"}),      # socketserver.BaseServer
    "SSLContext": frozenset({"load_cert_chain"}),    # ssl.SSLContext
}

# A terminal that is the shared object only when its parent resolves to the
# named terminal (`os.path`, `mod.os.path`, an `os.path` import alias), never
# a bare `x.path` (`self.path`, a request's path, a fixture's path).
_QUALIFIED = {"path": "os"}

# Import-alias resolution: the module a bare test-file name stands for.
_MODULE_TERMINAL = {
    "subprocess": "subprocess",
    "urllib.request": "request",
    "socket": "socket",
    "os": "os",
    "os.path": "path",
    "shutil": "shutil",
}

# `from <module> import <name> [as <alias>]` forms that bind a terminal.
_FROM_TERMINAL = {
    ("urllib", "request"): "request",
    ("os", "path"): "path",
    ("socketserver", "BaseServer"): "BaseServer",
    ("ssl", "SSLContext"): "SSLContext",
}

# RM-880 ruling on the RM-411 fault helper `tests/_replace_faults.py`
# `scoped_fs_fault` (install, then restore in a finally): SCOPED BY DESIGN,
# kept. It is flagged only because its attribute name is a parameter. That
# name is checked against `_SCOPED_NAMES` (replace / rename / open, else
# ValueError), none of which is in SHARED_ATTRS["os"]
# (`test_the_rm411_ruling_still_holds` pins both facts). The shim is
# PATH-scoped: a call from any thread whose dst / path is outside the test's
# root is delegated to the real function, which the helper proves on entry
# with a control call outside the root. A module view cannot stand in for it:
# the writers under test reach os.replace through many modules
# (core.polled_json and every writer), which is why RM-411 injects the fault
# at the os boundary. The restore line puts back the real function; it fakes
# nothing. Its two RM-411 self-tests (`tests/test_scoped_fs_fault_rm411.py`
# restore lines) resolve through their parametrize lists and are not hits.
_RM411_RULING = ("RM-411 scoped_fs_fault: a path-scoped shim on os.replace / "
                 "os.rename / os.open only (disjoint from the os set), "
                 "delegating every out-of-root call; scoped by design (RM-880)")

# Sites that must stay process-wide with a PLAIN fake, as
# {(relpath, lineno): why}. Every other RM-801 / RM-880 site is scoped through
# a module view, or through this_thread_only where no module-global name
# exists.
ALLOWLIST: dict[tuple[str, int], str] = {
    ("tests/_replace_faults.py", 229): _RM411_RULING,   # install the shim
    ("tests/_replace_faults.py", 234): _RM411_RULING,   # restore the real
}


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Bare names in this file bound to a shared stdlib module."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and a.name in _MODULE_TERMINAL:
                    out[a.asname] = _MODULE_TERMINAL[a.name]
                elif not a.asname:
                    head = a.name.split(".")[0]
                    if head in _MODULE_TERMINAL:
                        out[head] = _MODULE_TERMINAL[head]
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                term = _FROM_TERMINAL.get((node.module, a.name))
                if term:
                    out[a.asname or a.name] = term
    return out


@lru_cache(maxsize=1)
def repo_module_aliases() -> dict[str, str]:
    """Every alias a tracked repo module binds to a shared stdlib module
    (`_sp`, `_ur`, `urllib_request`, ...), so `<mod>.<alias>` in a test is read
    as the shared module. The text check only skips files with no ` as `; the
    AST of each remaining file decides."""
    out: dict[str, str] = {}
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if " as " not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for name, term in _aliases(tree).items():
            if name not in SHARED_ATTRS:
                out[name] = term
    return out


def _normalise_sys(tree: ast.AST) -> ast.AST:
    """Rewrite `import sys as _s` names to `sys` and `from sys import modules
    [as m]` names to `sys.modules`, so one predicate reads every spelling of
    `sys.modules` (RM-815)."""
    sys_names: set[str] = set()
    mod_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            sys_names.update(a.asname for a in node.names
                             if a.name == "sys" and a.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            mod_names.update(a.asname or a.name for a in node.names
                             if a.name == "modules")
    if not (sys_names or mod_names):
        return tree

    class _Rename(ast.NodeTransformer):
        def visit_Name(self, n: ast.Name) -> ast.AST:
            if n.id in sys_names:
                return ast.copy_location(ast.Name("sys", n.ctx), n)
            if n.id in mod_names:
                return ast.copy_location(
                    ast.Attribute(ast.Name("sys", ast.Load()), "modules", n.ctx), n)
            return n

    return ast.fix_missing_locations(_Rename().visit(tree))


def _is_sys_modules(expr: ast.AST) -> bool:
    """`sys.modules` (or `_sys.modules`, `mod.sys.modules`)."""
    if not (isinstance(expr, ast.Attribute) and expr.attr == "modules"):
        return False
    v = expr.value
    name = v.id if isinstance(v, ast.Name) else getattr(v, "attr", "")
    return name.endswith("sys")


def _sys_modules_entry(expr: ast.AST) -> str | None:
    """`sys.modules['subprocess']` / `sys.modules.get('subprocess')` /
    `importlib.import_module('subprocess')` -> the shared-module name it
    stands for (RM-815), else None."""
    key = None
    if isinstance(expr, ast.Subscript) and _is_sys_modules(expr.value):
        key = _str(expr.slice)
    elif (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
          and expr.func.attr == "get" and _is_sys_modules(expr.func.value)
          and expr.args):
        key = _str(expr.args[0])
    elif isinstance(expr, ast.Call) and expr.args:
        # `__import__('x.y')` returns the TOP package, so only an undotted
        # name stands for the module there.
        f = expr.func
        fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        name = _str(expr.args[0])
        if fname == "import_module" or (fname == "__import__" and name
                                        and "." not in name):
            key = name
    return _MODULE_TERMINAL.get(key) if key else None


def _terminal(expr: ast.AST, aliases: dict[str, str],
              attr_aliases: dict[str, str]) -> str | None:
    """The shared-module name EXPR resolves to, or None."""
    entry = _sys_modules_entry(expr)
    if entry:
        return entry
    if isinstance(expr, ast.Name):
        if expr.id in aliases:
            return aliases[expr.id]
        return (expr.id if expr.id in SHARED_ATTRS and expr.id not in _QUALIFIED
                else None)
    if isinstance(expr, ast.Attribute):
        if expr.attr in SHARED_ATTRS:
            parent = _QUALIFIED.get(expr.attr)
            if parent is None:
                return expr.attr
            # RM-880: `x.path` is os.path only under an `os`.
            if _terminal(expr.value, aliases, attr_aliases) == parent:
                return expr.attr
            return None
        return attr_aliases.get(expr.attr)
    return None


def _variable_aliases(tree: ast.AST, aliases: dict[str, str],
                      attr_aliases: dict[str, str]) -> dict[str, str]:
    """ALIASES plus every plain variable bound to a shared module
    (`sp = mod.subprocess`, `b = sp`; RM-815), to a fixpoint. File-wide, not
    scope-aware: a name's FIRST binding wins, so two bindings cannot
    oscillate."""
    out = dict(aliases)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            term = _terminal(value, out, attr_aliases)
            if not term:
                continue
            for t in targets:
                if isinstance(t, ast.Name) and t.id not in out:
                    out[t.id] = term
                    changed = True
    return out


def _module_dict(expr: ast.AST | None, aliases: dict[str, str],
                 attr_aliases: dict[str, str]) -> ast.AST | None:
    """`X.__dict__` / `vars(X)` -> X when X is a shared module (RM-815)."""
    obj = None
    if isinstance(expr, ast.Attribute) and expr.attr == "__dict__":
        obj = expr.value
    elif (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
          and expr.func.id == "vars" and len(expr.args) == 1):
        obj = expr.args[0]
    if obj is not None and _terminal(obj, aliases, attr_aliases):
        return obj
    return None


def _dotted_hit(target: str, attr_aliases: dict[str, str]) -> bool:
    parts = target.split(".")
    if len(parts) < 2:
        return False
    term = parts[-2] if parts[-2] in SHARED_ATTRS else attr_aliases.get(parts[-2])
    if term is None or parts[-1] not in SHARED_ATTRS[term]:
        return False
    parent = _QUALIFIED.get(parts[-2])
    if parent is None:
        return True
    # `"tools.x.os.path.exists"`, never `"tools.x.path.exists"` (RM-880).
    if len(parts) < 3:
        return False
    above = parts[-3] if parts[-3] in SHARED_ATTRS else attr_aliases.get(parts[-3])
    return above == parent


def _loop_constants(tree: ast.AST) -> dict[str, set[str]]:
    """`for NAME in ("a", "b"):` -> {NAME: {"a", "b"}} (unions every loop)."""
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.For, ast.AsyncFor))
                and isinstance(node.target, ast.Name)
                and isinstance(node.iter, (ast.Tuple, ast.List, ast.Set))):
            vals = [_str(e) for e in node.iter.elts]
            if all(v is not None for v in vals):
                out.setdefault(node.target.id, set()).update(vals)
    return out


def _param_constants(tree: ast.AST) -> dict[int, dict[str, set[str]]]:
    """id(node) -> {NAME: {"a", "b"}} for every node inside a function
    decorated `@pytest.mark.parametrize("NAME", ["a", "b"])` (RM-880): a
    parametrized name is a constant for-loop scoped to its function. Only a
    single name over all-literal values; anything else stays unknown."""
    out: dict[int, dict[str, set[str]]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        consts: dict[str, set[str]] = {}
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "parametrize"):
                continue
            kw = {k.arg: k.value for k in dec.keywords if k.arg}
            argname = _str(_arg(dec.args, kw, 0, "argnames"))
            values = _arg(dec.args, kw, 1, "argvalues")
            if (argname is None or "," in argname
                    or not isinstance(values, (ast.List, ast.Tuple, ast.Set))):
                continue
            vals = [_str(e) for e in values.elts]
            if vals and all(v is not None for v in vals):
                consts.setdefault(argname.strip(), set()).update(vals)
        if consts:
            for sub in ast.walk(fn):
                out.setdefault(id(sub), {}).update(consts)
    return out


def _is_patch_func(func: ast.AST) -> bool:
    """`patch`, `mock.patch`, `unittest.mock.patch`."""
    return ((isinstance(func, ast.Name) and func.id == "patch")
            or (isinstance(func, ast.Attribute) and func.attr == "patch"))


def _str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _thread_scoped(value: ast.AST | None) -> bool:
    """VALUE is `this_thread_only(...)` (tests/_module_view.py): the patch
    stays process-wide, but every thread alive at install time (another
    test's leftover server or poller) keeps the real function."""
    if not isinstance(value, ast.Call):
        return False
    f = value.func
    return ((isinstance(f, ast.Name) and f.id == "this_thread_only")
            or (isinstance(f, ast.Attribute) and f.attr == "this_thread_only"))


def _arg(args: list, kw: dict, index: int, name: str) -> ast.AST | None:
    return args[index] if len(args) > index else kw.get(name)


def scan_source(src: str,
                attr_aliases: dict[str, str] | None = None) -> list[tuple[int, str]]:
    """Every process-wide shared-stdlib fake in SRC as (lineno, rendering).

    ATTR_ALIASES maps an attribute name to the shared module it stands for
    (default: every alias the tracked repo binds, `repo_module_aliases()`).
    """
    if attr_aliases is None:
        attr_aliases = repo_module_aliases()
    tree = _normalise_sys(ast.parse(src))
    aliases = _variable_aliases(tree, _aliases(tree), attr_aliases)
    loops = _loop_constants(tree)
    params = _param_constants(tree)
    hits: list[tuple[int, str]] = []

    def names_of(node: ast.AST | None) -> set[str] | None:
        """The attribute name(s) NODE can be; None = unknown (non-literal)."""
        s = _str(node)
        if s is not None:
            return {s}
        if not isinstance(node, ast.Name):
            return None
        found = loops.get(node.id, set()) | params.get(id(node), {}).get(
            node.id, set())
        return found or None

    def obj_attr(obj: ast.AST, names: set[str] | None, line: int,
                 value: ast.AST | None) -> None:
        term = _terminal(obj, aliases, attr_aliases)
        if not term or _thread_scoped(value):
            return
        if names is None:
            hits.append((line, f"{ast.unparse(obj)}.<non-literal name>"))
        for name in sorted((names or set()) & SHARED_ATTRS[term]):
            hits.append((line, f"{ast.unparse(obj)}.{name}"))

    def dotted_target(dotted: str, line: int, value: ast.AST | None) -> None:
        if _dotted_hit(dotted, attr_aliases) and not _thread_scoped(value):
            hits.append((line, dotted))

    def mapping_item(mapping: ast.AST | None, key: ast.AST | None, line: int,
                     value: ast.AST | None) -> None:
        """A store into MAPPING[KEY]: a shared module's `sys.modules` entry,
        or a shared function through the module's own dict (RM-815)."""
        if mapping is None or _thread_scoped(value):
            return
        name = _str(key)
        if _is_sys_modules(mapping) or _str(mapping) == "sys.modules":
            if name in _MODULE_TERMINAL:
                hits.append((line, f"sys.modules[{name!r}]"))
            return
        obj = _module_dict(mapping, aliases, attr_aliases)
        if obj is not None:
            obj_attr(obj, names_of(key), line, value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f, args = node.func, node.args
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            fname = (f.attr if isinstance(f, ast.Attribute)
                     else f.id if isinstance(f, ast.Name) else None)
            if fname in ("setattr", "delattr"):
                first = _arg(args, kw, 0, "target")
                second = _arg(args, kw, 1, "name")
                value = (_arg(args, kw, 2, "value") if fname == "setattr"
                         else None)
                dotted = _str(first)
                if dotted is not None:
                    # A dotted setattr's value is its 2nd argument; a dotted
                    # delattr has none (its 2nd is `raising`).
                    dotted_target(dotted, node.lineno,
                                  second if fname == "setattr" else None)
                elif first is not None and second is not None:
                    obj_attr(first, names_of(second), node.lineno, value)
            elif fname in ("setitem", "delitem") and isinstance(f, ast.Attribute):
                value = (_arg(args, kw, 2, "value") if fname == "setitem"
                         else None)
                mapping_item(_arg(args, kw, 0, "dic"), _arg(args, kw, 1, "name"),
                             node.lineno, value)
            elif (fname in ("setdefault", "update")
                  and isinstance(f, ast.Attribute)):
                # `sys.modules.setdefault('subprocess', m)`,
                # `vars(subprocess).update(run=f)`; mapping_item ignores any
                # other mapping.
                if fname == "setdefault" and args:
                    mapping_item(f.value, args[0], node.lineno,
                                 args[1] if len(args) > 1 else None)
                elif fname == "update":
                    pairs = [(ast.Constant(k), v) for k, v in kw.items()]
                    if args and isinstance(args[0], ast.Dict):
                        pairs += [(k, v) for k, v in zip(args[0].keys,
                                                         args[0].values)
                                  if k is not None]
                    for key, value in pairs:
                        mapping_item(f.value, key, node.lineno, value)
            elif _is_patch_func(f):
                dotted = _str(_arg(args, kw, 0, "target"))
                if dotted is not None:
                    dotted_target(dotted, node.lineno, _arg(args, kw, 1, "new"))
            elif (fname == "object" and isinstance(f, ast.Attribute)
                  and _is_patch_func(f.value)):
                target = _arg(args, kw, 0, "target")
                attribute = _arg(args, kw, 1, "attribute")
                if target is not None and attribute is not None:
                    obj_attr(target, names_of(attribute), node.lineno,
                             _arg(args, kw, 2, "new"))
            elif (fname == "multiple" and isinstance(f, ast.Attribute)
                  and _is_patch_func(f.value)):
                target = _arg(args, kw, 0, "target")
                dotted = _str(target)
                for name, value in kw.items():
                    if name == "target":
                        continue
                    if dotted is not None:
                        dotted_target(f"{dotted}.{name}", node.lineno, value)
                    elif target is not None:
                        obj_attr(target, {name}, node.lineno, value)
            elif (fname == "dict" and isinstance(f, ast.Attribute)
                  and _is_patch_func(f.value)):
                mapping = _arg(args, kw, 0, "in_dict")
                values = _arg(args, kw, 1, "values")
                items = [(k, v) for k, v in kw.items()
                         if k not in ("in_dict", "values", "clear")]
                pairs = [(ast.Constant(k), v) for k, v in items]
                if isinstance(values, ast.Dict):
                    pairs += [(k, v) for k, v in zip(values.keys, values.values)
                              if k is not None]
                for key, value in pairs:
                    mapping_item(mapping, key, node.lineno, value)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign,
                               ast.Delete)):
            if isinstance(node, (ast.Assign, ast.Delete)):
                targets = node.targets
            else:
                targets = [node.target]
            value = getattr(node, "value", None)
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Attribute):
                        obj_attr(sub.value, {sub.attr}, node.lineno, value)
                    elif (isinstance(sub, ast.Subscript)
                          and isinstance(sub.ctx, (ast.Store, ast.Del))):
                        mapping_item(sub.value, sub.slice, node.lineno, value)
    return sorted(set(hits))


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        files += [p for p in (REPO_ROOT / d).rglob("*.py")
                  if "__pycache__" not in p.parts]
    return sorted(files)


def _all_hits() -> list[tuple[str, int, str]]:
    out = []
    for path in _scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line, what in scan_source(path.read_text(encoding="utf-8")):
            out.append((rel, line, what))
    return out


# ------------------------------------------------------------- the guard


def test_no_test_fakes_a_shared_stdlib_attribute_process_wide():
    offenders = [h for h in _all_hits() if (h[0], h[1]) not in ALLOWLIST]
    assert not offenders, (
        f"{len(offenders)} process-wide stdlib fake(s); scope each to the "
        "module under test with tests/_module_view.py bind_subprocess("
        "monkeypatch, mod, run=fake) / bind_urlopen(monkeypatch, mod, fake) / "
        "bind_which(monkeypatch, mod, fake) / bind_os_path(monkeypatch, mod, "
        "exists=fake) / bind_module_view(monkeypatch, mod, 'os', name='nt') / "
        "bind_stdlib(...), a class attribute on the code under test's own "
        "subclass, or this_thread_only(fake, real) where no module-local "
        "name exists (RM-801, RM-880):\n"
        + "\n".join(f"  {r}:{n}: {w}" for r, n, w in offenders))


def test_every_allowlist_entry_still_matches_a_live_site():
    live = {(r, n) for r, n, _w in _all_hits()}
    stale = sorted(set(ALLOWLIST) - live)
    assert not stale, f"stale RM-801 allowlist entries: {stale}"
    assert all(why.strip() for why in ALLOWLIST.values())


def test_the_walk_is_not_vacuous():
    files = _scanned_files()
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    assert len(files) > 500, len(files)
    assert "tests/_module_view.py" in rels
    assert any(r.startswith("agents/daemon_slayer/tests/") for r in rels)


# ---------------------------------------- the detector, on synthetic sources


_FLAGGED = [
    "monkeypatch.setattr(mod.subprocess, 'run', f)",
    "monkeypatch.setattr(mod.subprocess, 'Popen', f)",
    "monkeypatch.setattr(subprocess, 'check_output', f)",
    "monkeypatch.setattr(lc.urllib.request, 'urlopen', f)",
    "monkeypatch.setattr(urllib.request, 'urlopen', f)",
    "monkeypatch.setattr(m.socket, 'socket', f)",
    "monkeypatch.setattr('subprocess.run', f)",
    "monkeypatch.setattr('tools.x.subprocess.Popen', f)",
    "mp.setattr(target=subprocess, name='run', value=f)",
    "setattr(subprocess, 'run', f)",
    "mock.patch('subprocess.run')",
    "unittest.mock.patch('urllib.request.urlopen', f)",
    "patch('tools.x.subprocess.run', f)",
    "mock.patch.object(subprocess, 'Popen', f)",
    "patch.object(mod.subprocess, 'run')",
    "patch.multiple(subprocess, run=f)",
    "subprocess.run = f",
    "mod.urllib.request.urlopen = f",
]

_CLEAN = [
    "bind_module_view(monkeypatch, mod, 'subprocess', run=f)",
    "monkeypatch.setattr(mod, 'subprocess', view)",
    "monkeypatch.setattr(mod, 'run', f)",
    "monkeypatch.setattr(mod, 'urlopen', f)",
    "monkeypatch.setattr(mod.subprocess_helpers, 'run', f)",
    "monkeypatch.setattr(subprocess, 'TimeoutExpired', f)",
    "monkeypatch.setattr('tools.x.run', f)",
    "mock.patch('tools.x._run')",
    "x = subprocess.run",
    "subprocess.run(['git'])",
    "'monkeypatch.setattr(subprocess, \"run\", f)'",
    # thread-scoped (tests/_module_view.py this_thread_only)
    "monkeypatch.setattr(subprocess, 'run', this_thread_only(f, real))",
    "monkeypatch.setattr('subprocess.run', this_thread_only(f, real))",
    "mock.patch('subprocess.Popen', this_thread_only(f, real))",
    "mock.patch('subprocess.Popen', new=mv.this_thread_only(f, real))",
    "mock.patch.object(subprocess, 'run', new=this_thread_only(f, real))",
    "subprocess.run = this_thread_only(f, real)",
]


def test_the_detector_flags_every_process_wide_form():
    missed = [s for s in _FLAGGED if not scan_source(s)]
    assert not missed, missed


def test_the_detector_resolves_import_aliases():
    assert scan_source("import subprocess as sp\nsp.run = f\n")
    assert scan_source("from urllib import request as r\n"
                       "monkeypatch.setattr(r, 'urlopen', f)\n")
    assert scan_source("import urllib.request as ur\n"
                       "monkeypatch.setattr(ur, 'urlopen', f)\n")
    assert not scan_source("import mymod as subp\nsubp.run = f\n")


def test_the_detector_passes_every_scoped_form():
    wrong = [s for s in _CLEAN if scan_source(s)]
    assert not wrong, wrong


def test_a_thread_scoped_patch_with_a_plain_fake_is_still_flagged():
    assert scan_source("monkeypatch.setattr(subprocess, 'run', wrap(f))")
    assert scan_source("mock.patch('subprocess.run', side_effect=f)")


def test_the_detector_reads_a_repo_module_alias_as_the_shared_module():
    # tools/ddragon_mirror_refresh.py: `from urllib import request as
    # urllib_request` - its test patched ddr.urllib_request.urlopen (RM-801
    # verifier finding; the attribute name alone hides the module).
    alias = {"urllib_request": "request", "_sp": "subprocess"}
    assert scan_source("monkeypatch.setattr(ddr.urllib_request, 'urlopen', f)", alias)
    assert scan_source("monkeypatch.setattr('t.ddr.urllib_request.urlopen', f)", alias)
    assert scan_source("mod._sp.Popen = f", alias)
    assert not scan_source("monkeypatch.setattr(ddr.urllib_request, 'urlopen', f)", {})
    assert not scan_source("monkeypatch.setattr(ddr, 'urllib_request', view)", alias)


def test_the_repo_alias_walk_is_not_vacuous():
    self_check()
    found = repo_module_aliases()
    assert found.get("urllib_request") == "request", found
    assert found.get("_sp") == "subprocess", found
    assert found.get("_ur") == "request", found


def test_the_detector_resolves_a_non_literal_attribute_name():
    loop = ("for attr in ('run', 'Popen'):\n"
            "    monkeypatch.setattr(subprocess, attr, f)\n")
    assert scan_source(loop)
    assert scan_source("monkeypatch.setattr(subprocess, pick(), f)")
    assert scan_source("setattr(subprocess, name, f)")
    assert not scan_source("for attr in ('TimeoutExpired',):\n"
                           "    monkeypatch.setattr(subprocess, attr, f)\n")
    assert not scan_source("for attr in ('run', 'Popen'):\n"
                           "    monkeypatch.setattr(subprocess, attr,\n"
                           "        this_thread_only(f, getattr(subprocess, attr)))\n")


def test_the_detector_covers_getaddrinfo():
    assert scan_source("monkeypatch.setattr(socket, 'getaddrinfo', f)")


# RM-815: the six shapes the RM-801 verifier found the detector blind to.
_FLAGGED_RM815 = {
    "sys.modules entry": [
        "monkeypatch.setitem(sys.modules, 'subprocess', fake_mod)",
        "sys.modules['subprocess'] = fake_mod",
        "monkeypatch.setattr(sys.modules['subprocess'], 'run', f)",
        "sys.modules['urllib.request'].urlopen = f",
        "monkeypatch.setattr(sys.modules.get('socket'), 'socket', f)",
        "mock.patch.dict(sys.modules, {'socket': fake_mod})",
        "mock.patch.dict('sys.modules', subprocess=fake_mod)",
        "import sys as _s\n_s.modules['subprocess'] = fake_mod",
        "from sys import modules\nmodules['socket'] = fake_mod",
        "from sys import modules as mm\nmonkeypatch.setattr(mm['subprocess'], 'run', f)",
        "sys.modules.setdefault('subprocess', fake_mod)",
        "sys.modules.update({'urllib.request': fake_mod})",
        "monkeypatch.delitem(sys.modules, 'subprocess')",
    ],
    "plain alias variable": [
        "sp = mod.subprocess\nmonkeypatch.setattr(sp, 'run', f)",
        "sp = subprocess\nsp.Popen = f",
        "a = mod.subprocess\nb = a\nb.run = f",
        "s = sys.modules['socket']\nmonkeypatch.setattr(s, 'socket', f)",
        "sp = importlib.import_module('subprocess')\nsp.run = f",
        "monkeypatch.setattr(__import__('socket'), 'socket', f)",
    ],
    "the module dict": [
        "monkeypatch.setitem(subprocess.__dict__, 'run', f)",
        "monkeypatch.setitem(vars(mod.subprocess), 'Popen', f)",
        "subprocess.__dict__['run'] = f",
        "mock.patch.dict(subprocess.__dict__, {'run': f})",
        "mock.patch.dict(vars(socket), socket=f)",
        "monkeypatch.delitem(subprocess.__dict__, 'run')",
        "vars(subprocess).update(run=f)",
    ],
    "patch.multiple on a string target": [
        "patch.multiple('subprocess', run=f)",
        "mock.patch.multiple('tools.x.subprocess', Popen=f)",
        "mock.patch.multiple(target='urllib.request', urlopen=f)",
    ],
    "keyword-only patch.object": [
        "mock.patch.object(target=subprocess, attribute='run', new=f)",
        "patch.object(mod.subprocess, attribute='Popen')",
    ],
    "delattr": [
        "monkeypatch.delattr(subprocess, 'run')",
        "monkeypatch.delattr('subprocess.run')",
        "delattr(mod.socket, 'socket')",
        "del subprocess.run",
    ],
}

_CLEAN_RM815 = [
    "monkeypatch.setitem(sys.modules, 'mypkg', fake_mod)",
    "monkeypatch.setitem(sys.modules, 'subprocess_helpers', fake_mod)",
    "sys.modules['tools.x'] = fake_mod",
    "x = sys.modules['subprocess']",
    "u = __import__('urllib.request')\nu.urlopen = f",
    "import sys as _s\n_s.modules['mypkg'] = fake_mod",
    "sys.modules.update({'mypkg': fake_mod})",
    "sys.modules.setdefault('mypkg', fake_mod)",
    "cfg.update(run=f)",
    "monkeypatch.delitem(os.environ, 'run')",
    "m = importlib.import_module('tools.x')\nm.run = f",
    "mock.patch.dict(sys.modules, {'mypkg': fake_mod})",
    "sp = mod.helpers\nmonkeypatch.setattr(sp, 'run', f)",
    "run = subprocess.run\nrun.x = 1",
    "monkeypatch.setitem(subprocess.__dict__, 'TimeoutExpired', f)",
    "monkeypatch.setitem(mod.__dict__, 'run', f)",
    "monkeypatch.setitem(os.environ, 'run', '1')",
    "mock.patch.dict(os.environ, {'run': '1'})",
    "patch.multiple('tools.x', run=f)",
    "patch.multiple('subprocess', TimeoutExpired=f)",
    "mock.patch.object(target=mod, attribute='subprocess', new=view)",
    "monkeypatch.delattr(mod, 'subprocess')",
    "monkeypatch.delattr(subprocess, 'TimeoutExpired')",
    "monkeypatch.delattr('tools.x.run')",
    "del mod.run",
    "mock.patch.object(target=subprocess, attribute='run',"
    " new=this_thread_only(f, real))",
    "patch.multiple('subprocess', run=this_thread_only(f, real))",
    "monkeypatch.setitem(subprocess.__dict__, 'run', this_thread_only(f, real))",
]


@pytest.mark.parametrize("shape", sorted(_FLAGGED_RM815))
def test_the_detector_flags_each_rm815_shape(shape):
    missed = [s for s in _FLAGGED_RM815[shape] if not scan_source(s)]
    assert not missed, missed


def test_the_detector_passes_the_rm815_clean_forms():
    wrong = [(s, scan_source(s)) for s in _CLEAN_RM815 if scan_source(s)]
    assert not wrong, wrong


def test_an_alias_variable_rebound_twice_keeps_its_first_module():
    # First binding wins, so two bindings of one name cannot oscillate.
    src = "a = subprocess\na = socket\na.run = f\na.socket = g\n"
    assert scan_source(src) == [(3, "a.run")]


# RM-880 (a): the widened attribute set, one entry per attribute family, each
# in the shapes its census sites used (and the RM-801 / RM-815 shapes).
_FLAGGED_RM880 = {
    "os.name / kill / killpg": [
        "monkeypatch.setattr(procs.os, 'name', 'nt')",
        "monkeypatch.setattr(os, 'name', 'posix')",
        "os.name = 'nt'",
        "mock.patch('tools.x.os.name', 'nt')",
        "import os as _o\n_o.killpg = f",
        "monkeypatch.setattr(procs.os, 'killpg', f, raising=False)",
        "mock.patch.object(os, 'kill', f)",
        "monkeypatch.setattr('os.kill', f)",
        "monkeypatch.setitem(sys.modules, 'os', fake_mod)",
    ],
    "os.path.exists / isfile / isdir": [
        "monkeypatch.setattr(pr.os.path, 'exists', f)",
        "monkeypatch.setattr(os.path, 'isfile', f)",
        "import os.path as osp\nosp.isdir = f",
        "from os import path\nmonkeypatch.setattr(path, 'exists', f)",
        "from os import path as p\np.isfile = f",
        "mock.patch('os.path.exists', return_value=True)",
        "mock.patch('tools.x.os.path.isdir', f)",
        "p = mod.os.path\nmonkeypatch.setattr(p, 'exists', f)",
    ],
    "shutil.which": [
        "monkeypatch.setattr(bec.shutil, 'which', f)",
        "mock.patch('agents.supervisor.shutil.which', return_value='/x')",
        "mock.patch.object(eph.shutil, 'which', return_value=None)",
        "shutil.which = f",
        "import shutil as _sh\n_sh.which = f",
    ],
    "socketserver.BaseServer.serve_forever": [
        "mock.patch.object(socketserver.BaseServer, 'serve_forever', f)",
        "from socketserver import BaseServer\nBaseServer.serve_forever = f",
        "mock.patch('socketserver.BaseServer.serve_forever', f)",
    ],
    "ssl.SSLContext.load_cert_chain": [
        "monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain', f)",
        "from ssl import SSLContext as C\nmonkeypatch.setattr(C, 'load_cert_chain', f)",
        "mock.patch('ssl.SSLContext.load_cert_chain')",
    ],
    "a parametrized name over a shared attribute": [
        "@pytest.mark.parametrize('attr', ['name', 'sep'])\n"
        "def test_x(attr):\n    setattr(os, attr, f)\n",
        # the list binds only inside its own function
        "@pytest.mark.parametrize('name', ['replace'])\n"
        "def test_a(name):\n    pass\n"
        "def helper(name):\n    setattr(os, name, f)\n",
    ],
}

_CLEAN_RM880 = [
    "bind_module_view(monkeypatch, procs, 'os', name='nt')",
    "monkeypatch.setattr(procs, 'os', view)",
    "bind_which(monkeypatch, bec, f)",
    "bind_os_path(monkeypatch, pr, exists=f)",
    "monkeypatch.setattr(mod._MatchDBHTTPServer, 'serve_forever', f)",
    "bind_module_view(monkeypatch, tls_policy, 'ssl', SSLContext=Sub)",
    "monkeypatch.setattr(mod, 'which', f)",
    # `path` is os.path only under an `os`
    "monkeypatch.setattr(self.path, 'exists', f)",
    "monkeypatch.setattr(fake.path, 'isfile', f)",
    "path.exists = f",
    "mock.patch('tools.x.path.exists', f)",
    # reads and calls are not patches
    "x = os.name",
    "os.kill(pid, 9)",
    "shutil.which('git')",
    "monkeypatch.setattr(shutil, 'which', this_thread_only(f, shutil.which))",
    # a parametrize list disjoint from the os set (the RM-411 self-test shape)
    "@pytest.mark.parametrize('name', ['replace', 'rename'])\n"
    "def test_x(name):\n    setattr(os, name, real)\n",
    "@pytest.mark.parametrize(argnames='name', argvalues=('open',))\n"
    "def test_y(name):\n    setattr(os, name, real)\n",
]


@pytest.mark.parametrize("family", sorted(_FLAGGED_RM880))
def test_the_detector_flags_each_rm880_attribute(family):
    missed = [s for s in _FLAGGED_RM880[family] if not scan_source(s)]
    assert not missed, missed


def test_the_detector_passes_the_rm880_clean_forms():
    wrong = [(s, scan_source(s)) for s in _CLEAN_RM880 if scan_source(s)]
    assert not wrong, wrong


def test_the_rm880_attribute_set_is_pinned():
    # Narrowing any family back would re-open a census site unseen.
    assert SHARED_ATTRS["os"] >= {"name", "kill", "killpg"}
    assert SHARED_ATTRS["path"] >= {"exists", "isfile", "isdir"}
    assert SHARED_ATTRS["shutil"] >= {"which"}
    assert SHARED_ATTRS["BaseServer"] >= {"serve_forever"}
    assert SHARED_ATTRS["SSLContext"] >= {"load_cert_chain"}


def test_the_rm411_ruling_still_holds():
    """The ALLOWLIST ruling rests on two facts; a change to either voids it."""
    from tests import _replace_faults as rf
    assert set(rf._SCOPED_NAMES).isdisjoint(SHARED_ATTRS["os"]), (
        "scoped_fs_fault now reaches a name in the os set: re-rule it")
    lines = (REPO_ROOT / "tests" / "_replace_faults.py").read_text(
        encoding="utf-8").splitlines()
    for (rel, n), why in ALLOWLIST.items():
        assert rel == "tests/_replace_faults.py" and why == _RM411_RULING
        assert lines[n - 1].strip().startswith("setattr(os, name, "), (
            rel, n, lines[n - 1])


# ------------------------------------------- the scoping helpers themselves


def _module(name: str, src: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    exec(compile(src, name, "exec"), vars(mod))  # noqa: S102 - fixed source
    return mod


class _FakePopen:
    made: list = []

    def __init__(self, argv, **_kw):
        self.made.append(list(argv))
        self.args, self.returncode = argv, 7

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def communicate(self, input=None, timeout=None):  # noqa: A002
        return ("out", "")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


def test_bind_subprocess_is_deep_and_reaches_only_the_module(monkeypatch):
    real_run, real_popen = subprocess.run, subprocess.Popen
    _FakePopen.made = []
    mod = _module("rm801_fake_sp", "import subprocess as _sp\n"
                  "def go():\n"
                  "    return _sp.run(['x'], capture_output=True, text=True)\n")
    assert bind_subprocess(monkeypatch, mod, Popen=_FakePopen) == 1
    got = mod.go()
    assert _FakePopen.made == [["x"]]
    assert got.returncode == 7 and got.stdout == "out"
    # The shared module - every other thread's view - is untouched.
    assert subprocess.run is real_run and subprocess.Popen is real_popen
    assert mod._sp.TimeoutExpired is subprocess.TimeoutExpired


def test_bind_subprocess_layers_and_binds_a_from_import(monkeypatch):
    mod = _module("rm801_fake_from",
                  "import subprocess\nfrom subprocess import run\n")
    assert bind_subprocess(monkeypatch, mod, run=lambda *a, **k: "one") == 2
    bind_subprocess(monkeypatch, mod, check_output=lambda *a, **k: "two")
    assert mod.subprocess.run() == "one" and mod.run() == "one"
    assert mod.subprocess.check_output() == "two"
    monkeypatch.undo()
    assert mod.subprocess is subprocess and mod.run is subprocess.run


@pytest.mark.parametrize("src", [
    "import urllib.request\ndef go(u):\n    return urllib.request.urlopen(u)\n",
    "from urllib import request\ndef go(u):\n    return request.urlopen(u)\n",
    "import urllib.request as ur\ndef go(u):\n    return ur.urlopen(u)\n",
    "from urllib.request import urlopen\ndef go(u):\n    return urlopen(u)\n",
])
def test_bind_urlopen_covers_every_import_form(monkeypatch, src):
    real = urllib.request.urlopen
    mod = _module("rm801_fake_url", src)
    assert bind_urlopen(monkeypatch, mod, lambda u, **k: ("fake", u)) >= 1
    assert mod.go("http://x") == ("fake", "http://x")
    assert urllib.request.urlopen is real


def test_bind_stdlib_refuses_a_binding_that_reaches_nothing(monkeypatch):
    mod = _module("rm801_fake_none", "import os\n")
    with pytest.raises(AssertionError, match="holds no name"):
        bind_subprocess(monkeypatch, mod, run=lambda *a, **k: None)


def test_this_thread_only_spares_threads_alive_at_install():
    go, done = threading.Event(), threading.Event()
    seen = {}
    box = {}

    def leftover():
        go.wait(5)
        seen["leftover"] = box["scoped"]()
        done.set()

    t = threading.Thread(target=leftover, daemon=True)
    t.start()
    box["scoped"] = scoped = this_thread_only(lambda: "fake", lambda: "real")
    go.set()
    assert done.wait(5)
    assert seen["leftover"] == "real"
    assert scoped() == "fake"
    late = []
    t2 = threading.Thread(target=lambda: late.append(scoped()))
    t2.start()
    t2.join(5)
    assert late == ["fake"]


def test_bind_which_reaches_only_the_module(monkeypatch):
    real = shutil.which
    mod = _module("rm880_fake_which", "import shutil as _sh\n"
                  "def go():\n    return _sh.which('claude')\n")
    assert bind_which(monkeypatch, mod, lambda *_a, **_k: "/fake/claude") == 1
    assert mod.go() == "/fake/claude"
    assert shutil.which is real
    assert mod._sh.rmtree is not None and mod._sh.Error is shutil.Error


def test_bind_os_path_reaches_only_the_module_and_layers(monkeypatch):
    real_exists, real_isdir = os.path.exists, os.path.isdir
    mod = _module("rm880_fake_os_path", "import os\n"
                  "def go(p):\n    return os.path.exists(p), os.path.isdir(p)\n")
    bind_os_path(monkeypatch, mod, exists=lambda p: "yes")
    bind_os_path(monkeypatch, mod, isdir=lambda p: "dir")
    assert mod.go("nowhere-rm880") == ("yes", "dir")
    assert mod.os.sep == os.sep and mod.os.path.join("a", "b") == os.path.join("a", "b")
    assert os.path.exists is real_exists and os.path.isdir is real_isdir
    monkeypatch.undo()
    assert mod.os is os


def test_bind_module_view_on_os_leaves_the_shared_module(monkeypatch):
    real_name = os.name
    mod = _module("rm880_fake_os", "import os\n"
                  "def go():\n    return os.name, os.killpg(1, 9)\n")
    bind_module_view(monkeypatch, mod, "os", name="rm880",
                     killpg=lambda pid, sig: (pid, sig))
    assert mod.go() == ("rm880", (1, 9))
    assert os.name == real_name and getattr(os, "killpg", None) is not mod.os.killpg
