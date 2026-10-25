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
`del`. The attribute set itself (`os.name`, `shutil.which`, class methods)
is NOT widened here; that census is its own row.
"""
from __future__ import annotations

import ast
import subprocess
import threading
import types
import urllib.request
from functools import lru_cache
from pathlib import Path

import pytest

from tests._module_view import bind_subprocess, bind_urlopen, this_thread_only
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
}

# Import-alias resolution: the module a bare test-file name stands for.
_MODULE_TERMINAL = {
    "subprocess": "subprocess",
    "urllib.request": "request",
    "socket": "socket",
}

# Sites that must stay process-wide with a PLAIN fake, as
# {(relpath, lineno): why}. Empty: every RM-801 site is scoped through a
# module view, or through this_thread_only where no module-global name exists.
ALLOWLIST: dict[tuple[str, int], str] = {}


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
        elif isinstance(node, ast.ImportFrom) and node.module == "urllib":
            for a in node.names:
                if a.name == "request":
                    out[a.asname or a.name] = "request"
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
        return expr.id if expr.id in SHARED_ATTRS else None
    if isinstance(expr, ast.Attribute):
        if expr.attr in SHARED_ATTRS:
            return expr.attr
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
    return term is not None and parts[-1] in SHARED_ATTRS[term]


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
    tree = ast.parse(src)
    aliases = _variable_aliases(tree, _aliases(tree), attr_aliases)
    loops = _loop_constants(tree)
    hits: list[tuple[int, str]] = []

    def names_of(node: ast.AST | None) -> set[str] | None:
        """The attribute name(s) NODE can be; None = unknown (non-literal)."""
        s = _str(node)
        if s is not None:
            return {s}
        if isinstance(node, ast.Name) and node.id in loops:
            return loops[node.id]
        return None

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
            elif fname == "setitem" and isinstance(f, ast.Attribute):
                mapping_item(_arg(args, kw, 0, "dic"), _arg(args, kw, 1, "name"),
                             node.lineno, _arg(args, kw, 2, "value"))
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
        "bind_stdlib(...), or this_thread_only(fake, real) where no "
        "module-local name exists (RM-801):\n"
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
