"""RM-752: one TLS protocol floor for every ssl.SSLContext RC builds itself.

Measured 2026-10-20 (session 125) on Python 3.14.4 / OpenSSL 3.0.19: a bare
``ssl.SSLContext(PROTOCOL_TLS_SERVER | PROTOCOL_TLS_CLIENT)`` already reports
``minimum_version == TLSv1_2`` (CPython 3.10+ sets it in the constructor). So
a behaviour test of the form "the context's floor is >= TLSv1_2" passes on
the UNFIXED tree and proves nothing - the trap this file is built around.
Two discriminators replace it:

* the floor is read from ONE constant, ``core.tls_policy.TLS_MIN_VERSION``;
  patching that constant to TLSv1_3 must move every site that routes through
  the factories (a site still on the interpreter default stays at TLSv1_2,
  so the patched assertion fails on the unfixed tree);
* an AST enumeration of every tracked production ``.py`` finds every
  ``SSLContext(...)`` construction and allows it only inside the helper or
  at a site carrying a recorded exemption.

Decision (docs/OPERATIONS.md "TLS protocol floor (RM-752)"): the floor is
TLSv1_2, not TLSv1_3-only - this box's curl.exe builds and PowerShell 5.1
use Schannel, which on Windows 10 has no TLS 1.3 client, so a 1.3-only
:8888 / :8895 refuses them (measured: curl rc=35).
"""
from __future__ import annotations

import ast
import importlib.util
import ssl
import sys
from pathlib import Path

import pytest

from core import tls_policy
from tests import _repo_walk
from tests._module_view import bind_module_view

_REPO = Path(__file__).resolve().parents[1]


class _NoCertChainContext(ssl.SSLContext):
    """A real SSLContext whose cert load succeeds with no file on disk."""

    def load_cert_chain(self, *a, **k):
        return None

# The seven RM-752 sites (BACKLOG "Session 120 filings"), by file and the
# factory each must call (count = number of contexts the file builds).
_HELPER_SITES = {
    "mc/server.py": ("server_context", 1),
    "dashboard/server.py": ("server_context", 1),
    "tools/calibrate_vision.py": ("client_context_noverify", 1),
    "tools/match_monitor.py": ("client_context_noverify", 1),
    "tools/lcu_agent.py": ("client_context_noverify", 2),
}

# Every SSLContext construction allowed to remain, with its reason. Anything
# else in production code must go through core.tls_policy.
_ALLOWED_CONSTRUCTIONS = {
    # the helper itself: server_context() + client_context_noverify()
    "core/tls_policy.py": 2,
    # served to C:\RC-Agent\ with no repo above it (phase_watcher_install.ps1),
    # so it cannot import core/; it sets the same floor inline (asserted below)
    "tools/phase_watcher.py": 1,
    # RM-752 KEEP decision: the :2999 Live Client floor stays TLSv1 until a
    # live in-game probe measures what :2999 negotiates (docs/OPERATIONS.md)
    "tools/liveclient_relay.py": 1,
}


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    return ("tests" in parts[:-1] or parts[-1].startswith("test_")
            or parts[-1] == "conftest.py")


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Name) and f.id == name) or (
                isinstance(f, ast.Attribute) and f.attr == name):
            out.append(node)
    return out


def _parse(rel: str) -> ast.AST:
    return ast.parse((_REPO / rel).read_text(encoding="utf-8"), filename=rel)


def _load_fresh(rel: str, alias: str):
    """Execute a module file under a private name so its MODULE-LEVEL
    contexts are rebuilt now (a cached import keeps the old ones)."""
    spec = importlib.util.spec_from_file_location(alias, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(alias, None)
    return mod


@pytest.fixture
def floor_13(monkeypatch):
    """Move the shared floor to TLSv1_3 so a site on the interpreter default
    (TLSv1_2) is distinguishable from a site that follows the constant, and
    let load_cert_chain succeed without a certificate on disk."""
    monkeypatch.setattr(tls_policy, "TLS_MIN_VERSION", ssl.TLSVersion.TLSv1_3)
    # The contexts tls_policy builds skip the cert load: its OWN `ssl` name
    # hands out a subclass, never the shared ssl.SSLContext every other
    # thread's context inherits load_cert_chain from (RM-880).
    bind_module_view(monkeypatch, tls_policy, "ssl",
                     SSLContext=_NoCertChainContext)
    return ssl.TLSVersion.TLSv1_3


# -- the helper ----------------------------------------------------------------

def test_floor_constant_is_tls12():
    assert tls_policy.TLS_MIN_VERSION is ssl.TLSVersion.TLSv1_2


def test_server_context_shape():
    ctx = tls_policy.server_context()
    assert ctx.protocol == ssl.PROTOCOL_TLS_SERVER
    assert ctx.minimum_version == tls_policy.TLS_MIN_VERSION


def test_client_context_noverify_shape():
    ctx = tls_policy.client_context_noverify()
    assert ctx.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.minimum_version == tls_policy.TLS_MIN_VERSION


def test_factories_read_the_constant_at_call_time(floor_13):
    assert tls_policy.server_context().minimum_version == floor_13
    assert tls_policy.client_context_noverify().minimum_version == floor_13


# -- the sites follow the constant (fails on the unfixed tree) -----------------

def test_mc_server_context_follows_floor(floor_13):
    import mc.server as mc_server
    assert mc_server._ssl_context().minimum_version == floor_13


def test_dashboard_tls_context_follows_floor(floor_13, tmp_path):
    import dashboard.server as dash_server
    ctx = dash_server._tls_context(tmp_path / "c.pem", tmp_path / "k.pem")
    assert ctx.protocol == ssl.PROTOCOL_TLS_SERVER
    assert ctx.minimum_version == floor_13


def test_lcu_agent_contexts_follow_floor(floor_13):
    mod = _load_fresh("tools/lcu_agent.py", "_lcu_agent_rm752")
    assert mod._ssl_ctx.minimum_version == floor_13
    assert mod._dash_ssl_ctx.minimum_version == floor_13
    assert mod._ssl_ctx.verify_mode == ssl.CERT_NONE
    assert mod._dash_ssl_ctx.verify_mode == ssl.CERT_NONE


def test_match_monitor_context_follows_floor(floor_13):
    mod = _load_fresh("tools/match_monitor.py", "_match_monitor_rm752")
    assert mod._NOVERIFY.minimum_version == floor_13
    assert mod._NOVERIFY.verify_mode == ssl.CERT_NONE


def test_phase_watcher_sets_the_floor_explicitly():
    """Standalone served agent: inline floor. The runtime value alone would
    pass on the unfixed tree (interpreter default), so the explicit
    assignment is asserted on the AST too."""
    mod = _load_fresh("tools/phase_watcher.py", "_phase_watcher_rm752")
    assert mod._ssl_ctx_lcu.minimum_version == tls_policy.TLS_MIN_VERSION
    tree = _parse("tools/phase_watcher.py")
    pinned = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Attribute)
        and n.targets[0].attr == "minimum_version"
        and ast.unparse(n.value) == "ssl.TLSVersion.TLSv1_2"
    ]
    assert len(pinned) == 1, "phase_watcher must pin minimum_version inline"
    assert tls_policy.TLS_MIN_VERSION is ssl.TLSVersion.TLSv1_2, (
        "floor moved: update the inline pin in tools/phase_watcher.py too")


@pytest.mark.parametrize("rel", sorted(_HELPER_SITES))
def test_each_site_calls_its_factory(rel):
    factory, count = _HELPER_SITES[rel]
    tree = _parse(rel)
    assert len(_calls_named(tree, factory)) == count, (
        f"{rel}: expected {count} call(s) to core.tls_policy.{factory}()")
    assert _calls_named(tree, "SSLContext") == [], (
        f"{rel}: builds its own ssl.SSLContext; use core.tls_policy")


# -- no new site can bypass the helper -----------------------------------------

def test_every_production_sslcontext_is_the_helper_or_exempt():
    _repo_walk.self_check()
    scanned: set[str] = set()
    found: dict[str, int] = {}
    for path in _repo_walk.iter_repo_files(patterns=("*.py",)):
        rel = _repo_walk.relative_posix(path)
        if _is_test_path(rel):
            continue
        scanned.add(rel)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        n = len(_calls_named(tree, "SSLContext"))
        if n:
            found[rel] = n
    # Anti-vacuity: an empty or partial walk must not read as clean.
    assert len(scanned) > 300, f"walk reached only {len(scanned)} files"
    missing = (set(_HELPER_SITES) | set(_ALLOWED_CONSTRUCTIONS)) - scanned
    assert not missing, f"walk never reached: {sorted(missing)}"
    assert found == _ALLOWED_CONSTRUCTIONS, (
        "every production ssl.SSLContext(...) must come from core.tls_policy "
        f"(or carry a recorded exemption); found {found}")
