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
  thread and every thread started after it get the fake, except a thread
  whose nearest already-alive ancestor another test FILE started: a leftover
  server's per-request handler thread gets the real one too, by the creator
  lineage a passive audit hook records (RM-880 b). This file's own server
  fixture still hands the fake to its handler threads. Prefer a view wherever
  one exists: a raw `_thread` start has no recorded creator.

RM-880 widened the guard to `os.name` / `os.kill` / `os.killpg`,
`os.path.exists|isfile|isdir`, `shutil.which` and two class attributes:

- `bind_module_view(monkeypatch, mod, "os", name="posix", killpg=fake)` for
  MOD's own `os`; `bind_which(monkeypatch, mod, fake)` for its `shutil.which`;
  `bind_os_path(monkeypatch, mod, exists=fake)` for its `os.path` (a view of
  `os` whose `path` is a view of `ntpath` / `posixpath`).
- A class attribute (`socketserver.BaseServer.serve_forever`,
  `ssl.SSLContext.load_cert_chain`) is faked on the class the code under test
  builds - its own subclass, or a subclass handed in through a view of its
  module - never on the shared base every other instance inherits from.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import types
import urllib.request
import weakref

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


def bind_module_view(monkeypatch, module, name: str, /,
                     **overrides) -> ModuleView:
    """Rebind MODULE.<NAME> (a module it imported) to a view with OVERRIDES.

    The leading parameters are positional-only, so an override may itself be
    called `name` (`bind_module_view(mp, mod, "os", name="nt")`, RM-880)."""
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


def bind_which(monkeypatch, module, fake) -> int:
    """MODULE's own `shutil.which` only (RM-880); see bind_stdlib."""
    return bind_stdlib(monkeypatch, module, shutil, which=fake)


def bind_os_path(monkeypatch, module, **overrides) -> ModuleView:
    """MODULE's own `os.path.<name>` only (RM-880).

    `os.path` is `ntpath` / `posixpath`, a module of its own, so bind_stdlib
    cannot reach it through `os`: MODULE's `os` becomes a view whose `path` is
    a view of the real (or already-viewed) `os.path` with OVERRIDES.
    """
    assert overrides, "nothing to fake"
    current = getattr(module, "os", None)
    assert isinstance(current, types.ModuleType) and _root(current) is os, (
        f"{getattr(module, '__name__', module)!r} does not resolve the os "
        "module as `os`")
    return bind_module_view(monkeypatch, module, "os",
                            path=ModuleView(current.path, **overrides))


# Thread -> (the thread that started it, the test FILE running when it was
# started), recorded by a passive audit hook (RM-880 b). Audit hooks cannot be
# removed, so it is installed once, at import (collection, before any test
# starts a thread); it only reads, so a test that patches
# `threading.Thread.start` neither hides a start from it nor is changed by it.
_LINEAGE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_LINEAGE_LOCK = threading.Lock()
_LINEAGE_HOOKED = False
_UNRECORDED = (None, _MISSING)


def _current_test_file():
    """The test file pytest is running now (`PYTEST_CURRENT_TEST` is
    `<file>::<name> (<phase>)`), or None outside a test."""
    nodeid = os.environ.get("PYTEST_CURRENT_TEST")
    return nodeid.split("::", 1)[0] if nodeid else None


def _record_lineage(event: str, args: tuple) -> None:
    if event != "_thread.start_joinable_thread":
        return
    try:
        started = getattr(args[0], "__self__", None)  # Thread._bootstrap
        if isinstance(started, threading.Thread):
            entry = (threading.current_thread(), _current_test_file())
            with _LINEAGE_LOCK:
                _LINEAGE[started] = entry
    except Exception:  # noqa: BLE001 - a raising audit hook aborts the start
        pass


def _ensure_lineage_hook() -> None:
    global _LINEAGE_HOOKED
    with _LINEAGE_LOCK:
        if not _LINEAGE_HOOKED:
            sys.addaudithook(_record_lineage)
            _LINEAGE_HOOKED = True


def _lineage_of(thread):
    with _LINEAGE_LOCK:
        return _LINEAGE.get(thread, _UNRECORDED)


_ensure_lineage_hook()


def this_thread_only(fake, real):
    """FAKE for the installing thread and every thread started after it; REAL
    for each thread already alive at install time (another test's leftover
    server or poller). A thread started after install inherits from the
    nearest ancestor that was alive at install (RM-880 b): one this test FILE
    started (its own server fixture) passes FAKE on to a per-request handler
    thread as before, one another file or nobody recorded started (a leftover
    server of an earlier file) passes REAL. A thread with no recorded creator
    (a raw `_thread` start) keeps the pre-RM-880 answer, FAKE. For a
    process-wide patch where no module-local name exists; prefer
    bind_subprocess / bind_urlopen wherever one does."""
    _ensure_lineage_hook()
    installer = threading.current_thread()
    owner_file = _current_test_file()
    foreign = frozenset(t for t in threading.enumerate() if t is not installer)

    def _wants_real(thread) -> bool:
        if thread in foreign:
            return True
        seen = set()
        while thread is not installer and thread not in seen:
            seen.add(thread)
            creator, _ = _lineage_of(thread)
            if creator is None:
                return False
            if creator in foreign:
                # Unrecorded (started before the hook) is _MISSING: foreign.
                return _lineage_of(creator)[1] != owner_file
            thread = creator
        return False

    def scoped(*args, **kwargs):
        target = real if _wants_real(threading.current_thread()) else fake
        return target(*args, **kwargs)

    scoped.fake = fake
    scoped.real = real
    return scoped
