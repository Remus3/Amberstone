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
"""
from __future__ import annotations

import socket
import types


class ModuleView(types.ModuleType):
    """REAL module, except the names given as OVERRIDES."""

    def __init__(self, real: types.ModuleType, **overrides) -> None:
        super().__init__(real.__name__)
        self._real = real
        self.__dict__.update(overrides)

    def __getattr__(self, name: str):
        # Only reached for names not set on the view (AF_INET, TimeoutExpired, ...).
        return getattr(self._real, name)


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
