"""Bind a fake to ONE module's own global name for a shared module, never to
the shared module itself.

`monkeypatch.setattr(mod.socket, "socket", Fake)` (or `mod.subprocess, "run"`,
`mod.urllib.request, "urlopen"`) rebinds the attribute on the process-wide
module object, so every thread in the pytest(-xdist) worker - a leftover
server or poller from an earlier test file, a fixture's thread - gets the
fake too: its calls land in the fake's record and its own I/O breaks. CI run
39877078008 (gw0, linux): a 0.6 s budget assertion over a fake socket's
recorded timeouts read [0.5997.., 2.0, 3, 3, ...]; only the first was the
probe's. Rebinding the module's OWN name (`mod.socket`) to a view of the real
module reaches exactly the code under test and nothing else.

RM-801 (guard `tests/test_no_process_wide_stdlib_fakes_rm801.py`) moved every
test onto these helpers:

- `bind_subprocess(monkeypatch, mod, run=fake)` / `Popen=` and
  `bind_urlopen(monkeypatch, mod, fake)` rebind every name in MOD's globals
  that resolves the shared module (`import subprocess`, `import subprocess as
  _sp`, `import urllib.request`, `from urllib import request`) or the faked
  function itself (`from subprocess import run`). The view is DEEP: the shared
  module's own functions are re-bound to see the fake too (`run`,
  `check_output`, `call` reach a faked `Popen`; `check_output` reaches a faked
  `run`), exactly what the old process-wide patch gave MOD and nothing else.
- `this_thread_only(fake, real)` is the fallback where no module-local name
  exists (a function-local import, a module loaded under an unknown name, an
  any-module tripwire): it keeps the process-wide rebinding but hands every
  thread that was ALREADY alive when it was installed the real function, so a
  leftover server or poller of another test keeps its own I/O. The installing
  thread and every thread started after it get the fake - including a thread
  a leftover server starts later (a per-request handler thread), which is the
  one gap a module view does not have; prefer a view wherever one exists.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import types
import urllib.request

_MISSING = object()


def _rebound_functions(real: types.ModuleType, overrides: dict) -> dict:
    """Copies of REAL's own functions whose globals see OVERRIDES."""
    own = vars(real)
    scope = dict(own)
    scope.update(overrides)
    out = {}
    for name, obj in own.items():
        if name in overrides or not isinstance(obj, types.FunctionType):
            continue
        if obj.__globals__ is not own:
            continue
        fn = types.FunctionType(obj.__code__, scope, obj.__name__,
                                obj.__defaults__, obj.__closure__)
        fn.__kwdefaults__ = (dict(obj.__kwdefaults__)
                             if obj.__kwdefaults__ else None)
        fn.__qualname__ = obj.__qualname__
        fn.__doc__ = obj.__doc__
        fn.__module__ = obj.__module__
        fn.__dict__.update(obj.__dict__)
        out[name] = fn
    scope.update(out)
    return out


class ModuleView(types.ModuleType):
    """REAL module, except the names given as OVERRIDES.

    DEEP also re-binds REAL's own functions so their internal lookups see the
    overrides (a view of `subprocess` with `Popen=Fake` makes its `run` build
    a Fake). A view of a view flattens onto the real module.
    """

    def __init__(self, real: types.ModuleType, *, deep: bool = False,
                 **overrides) -> None:
        if isinstance(real, ModuleView):
            overrides = {**real._overrides, **overrides}
            deep = deep or real._deep
            real = real._real
        super().__init__(real.__name__)
        self._real = real
        self._overrides = dict(overrides)
        self._deep = deep
        if deep:
            self.__dict__.update(_rebound_functions(real, overrides))
        self.__dict__.update(overrides)

    def __getattr__(self, name: str):
        # Only reached for names not set on the view (AF_INET, TimeoutExpired, ...).
        return getattr(self._real, name)


def _root(obj):
    return obj._real if isinstance(obj, ModuleView) else obj


def bind_module_view(monkeypatch, module, name: str, **overrides) -> ModuleView:
    """Rebind MODULE.<NAME> (a module it imported) to a view with OVERRIDES."""
    real = getattr(module, name)
    assert isinstance(real, types.ModuleType), f"{module.__name__}.{name} is not a module"
    view = ModuleView(real, **overrides)
    monkeypatch.setattr(module, name, view)
    return view


def bind_socket_class(monkeypatch, module, socket_cls) -> None:
    """Make MODULE's `socket.socket(...)` build SOCKET_CLS; nothing else sees it."""
    assert getattr(module, "socket", None) is socket, (
        f"{module.__name__} does not resolve the socket module as `socket`")
    bind_module_view(monkeypatch, module, "socket", socket=socket_cls)


def bind_stdlib(monkeypatch, module, real: types.ModuleType, **overrides) -> int:
    """Fake OVERRIDES of the shared module REAL inside MODULE's globals only.

    Every global of MODULE that is REAL (under any alias, or already a view
    of it) becomes a deep view; one that is REAL's parent package (`urllib`
    for `urllib.request`) becomes a view whose child is that deep view; one
    that IS a faked function (`from subprocess import run`) becomes the fake.
    Returns how many globals were rebound and refuses zero: a binding that
    reaches nothing would leave the code under test on the real function.
    """
    assert overrides, "nothing to fake"
    pkg_name, _, leaf = real.__name__.rpartition(".")
    pkg = sys.modules.get(pkg_name) if pkg_name else None
    hits = 0
    for name, value in list(vars(module).items()):
        if name.startswith("__"):
            continue
        root = _root(value)
        if isinstance(value, types.ModuleType) and root is real:
            monkeypatch.setattr(module, name,
                                ModuleView(value, deep=True, **overrides))
            hits += 1
        elif (pkg is not None and isinstance(value, types.ModuleType)
              and root is pkg and isinstance(getattr(value, leaf, None),
                                             types.ModuleType)):
            child = ModuleView(getattr(value, leaf), deep=True, **overrides)
            monkeypatch.setattr(module, name, ModuleView(value, **{leaf: child}))
            hits += 1
        else:
            for attr, fake in overrides.items():
                if value is getattr(real, attr, _MISSING):
                    monkeypatch.setattr(module, name, fake)
                    hits += 1
    assert hits, (f"{getattr(module, '__name__', module)!r} holds no name for "
                  f"{real.__name__} or {sorted(overrides)}")
    return hits


def bind_subprocess(monkeypatch, module, **overrides) -> int:
    """MODULE's own `subprocess` (run=, Popen=, ...) only; see bind_stdlib."""
    return bind_stdlib(monkeypatch, module, subprocess, **overrides)


def bind_urlopen(monkeypatch, module, fake) -> int:
    """MODULE's own `urllib.request.urlopen` only; see bind_stdlib."""
    return bind_stdlib(monkeypatch, module, urllib.request, urlopen=fake)


def this_thread_only(fake, real):
    """FAKE for the installing thread and every thread started after it; REAL
    for each thread already alive at install time (another test's leftover
    server or poller). For a process-wide patch where no module-local name
    exists; prefer bind_subprocess / bind_urlopen wherever one does."""
    foreign = frozenset(t for t in threading.enumerate()
                        if t is not threading.current_thread())

    def scoped(*args, **kwargs):
        target = real if threading.current_thread() in foreign else fake
        return target(*args, **kwargs)

    scoped.fake = fake
    scoped.real = real
    return scoped
