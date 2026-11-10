"""s144 true-audit of web_dashboard.py - the :8888 dashboard entry shim.

main.py imports web_dashboard at boot inside ``try/except Exception`` and
calls ``start_dashboard``; any exception raised while the module imports
means the whole :8888 dashboard never starts (one warning line in the log).
The module starts the hot-reload watcher as an import-time side effect, so
the watcher's failure modes ARE the dashboard's failure modes. Findings
pinned here:

  1. ``start_watcher`` raising OSError (``ops/runtime`` mkdir) or
     RuntimeError (thread start) aborted the import - a dev-convenience
     thread took the whole dashboard down. Now logged, never raised.
  2. ``ImportError`` of ``core.hot_reload`` was swallowed with a bare
     ``pass``: edits silently stopped auto-restarting RC. Now one warning.
  3. A second execution of the module (re-import after a failed import)
     started a SECOND watcher - two threads writing restart_trigger.txt.
     Now a live watcher thread is detected and reused.
  4. The module docstring claimed read-only, no auth, an iPad display and
     tkinter overlays; all false at HEAD.

Every load below executes the real ``web_dashboard.py`` source under a
throwaway module name, so ``sys.modules["web_dashboard"]`` (which other
tests patch) is never touched. ``core.hot_reload.start_watcher`` is the
conftest no-op stand-in unless a test replaces it, so nothing here starts
a real watcher or writes ``restart_trigger.txt``.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
import threading
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "web_dashboard.py"
LOGGER = "rc.web_dashboard"


def _load():
    """Execute web_dashboard.py fresh under a unique module name."""
    name = f"_web_dashboard_probe_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


@pytest.fixture
def hot_reload(monkeypatch):
    from core import hot_reload as mod
    calls: list[Path] = []

    def _fake(project_root):
        calls.append(project_root)
        return threading.Thread(target=lambda: None, name="never-started")

    monkeypatch.setattr(mod, "start_watcher", _fake)
    mod._probe_calls = calls  # type: ignore[attr-defined]
    yield mod


def _no_live_watcher() -> None:
    live = [t.name for t in threading.enumerate()
            if t.name == "hot-reload-watcher" and t.is_alive()]
    assert not live, f"a real watcher is alive in the test process: {live}"


# --- characterization ---------------------------------------------------

def test_happy_path_starts_the_watcher_once_on_the_module_dir(hot_reload):
    _no_live_watcher()
    _load()
    assert hot_reload._probe_calls == [SRC.parent]


REEXPORTS = {
    "start_dashboard": ("dashboard.server", "start_dashboard"),
    "_DualProtocolHTTPServer": ("dashboard.server", "_DualProtocolHTTPServer"),
    "_Handler": ("dashboard._handler", "Handler"),
    "_SUPERVISOR_ORIGIN": ("dashboard._handler", "SUPERVISOR_ORIGIN"),
    "_SUPERVISOR_PROXY_PATHS": ("dashboard._handler", "SUPERVISOR_PROXY_PATHS"),
    "_build_state": ("dashboard._state_builder", "build_state"),
    "_MODE_TO_FILE": ("dashboard._state_builder", "MODE_TO_FILE"),
    "_lcu_summary": ("dashboard._liveclient", "lcu_summary"),
    "_liveclient_summary": ("dashboard._liveclient", "liveclient_summary"),
    "_atomic_write_json": ("dashboard._writers", "atomic_write_json"),
    "_force_vision_scan": ("dashboard._writers", "force_vision_scan"),
    "_set_pregame": ("dashboard._writers", "set_pregame"),
    "_diagnostics_cached": ("dashboard._diagnostics", "diagnostics_cached"),
    "_DIAG_CACHE": ("dashboard._diagnostics", "_DIAG_CACHE"),
    "_DIAG_LOCK": ("dashboard._diagnostics", "_DIAG_LOCK"),
    "_DIAG_TTL_S": ("dashboard._diagnostics", "_DIAG_TTL_S"),
    "_champ_select_brief_via_coach": ("dashboard._champ_select", "brief_via_coach"),
    "_compute_asset_hash": ("dashboard._static", "compute_asset_hash"),
    "_icon_svg_bytes": ("dashboard._static", "icon_svg_bytes"),
    "_inject_asset_hash": ("dashboard._static", "inject_asset_hash"),
    "_legacy_index_html": ("dashboard._static", "legacy_index_html"),
    "_manifest_bytes": ("dashboard._static", "manifest_bytes"),
    "_resolve_safe_icon": ("dashboard._static", "resolve_safe_icon"),
    "_DB_CONN_LOCAL": ("dashboard._context", "DB_CONN_LOCAL"),
    "_read_json": ("dashboard._context", "read_json"),
    "_ro_conn": ("dashboard._context", "ro_conn"),
    "SESSION_GAP_S": ("dashboard.builders", "SESSION_GAP_S"),
    "_agg_session": ("dashboard.builders", "_agg_session"),
    "_build_diagnostics": ("dashboard.builders", "_build_diagnostics"),
    "_group_sessions": ("dashboard.builders", "_group_sessions"),
    "_home_streaks": ("dashboard.builders", "_home_streaks"),
    "_home_tonight_pick": ("dashboard.builders", "_home_tonight_pick"),
    "_home_trends_14d": ("dashboard.builders", "_home_trends_14d"),
    "_load_match_rows": ("dashboard.builders", "_load_match_rows"),
    "_ts_to_epoch": ("dashboard.builders", "_ts_to_epoch"),
}


@pytest.mark.parametrize("name", sorted(REEXPORTS))
def test_every_historical_name_is_the_source_object(hot_reload, name):
    mod = _load()
    src_mod, src_name = REEXPORTS[name]
    assert getattr(mod, name) is getattr(importlib.import_module(src_mod), src_name)


def test_reexport_table_is_not_vacuous():
    assert len(REEXPORTS) == 35


def test_vision_token_is_the_canonical_resolver_value(hot_reload):
    from core.vision_token import get_vision_token
    assert _load()._VISION_TOKEN == get_vision_token()


# --- finding 1: a watcher start failure never aborts the import ----------

@pytest.mark.parametrize("exc", [
    PermissionError(13, "Access is denied", "ops/runtime"),
    FileExistsError(17, "exists as a file", "ops/runtime"),
    RuntimeError("can't start new thread"),
])
def test_watcher_start_failure_is_logged_not_raised(hot_reload, monkeypatch,
                                                     caplog, exc):
    def _boom(project_root):
        raise exc

    monkeypatch.setattr(hot_reload, "start_watcher", _boom)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        mod = _load()
    assert callable(mod.start_dashboard)
    msgs = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert any(type(exc).__name__ in m and "hot-reload" in m for m in msgs), msgs


def test_an_unexpected_watcher_error_still_surfaces(hot_reload, monkeypatch):
    """Narrow, not blind: a programming error in the watcher is not hidden."""
    def _bug(project_root):
        raise TypeError("bug in start_watcher")

    monkeypatch.setattr(hot_reload, "start_watcher", _bug)
    with pytest.raises(TypeError, match="bug in start_watcher"):
        _load()


# --- finding 2: an absent hot_reload module is reported, not silent -------

def test_missing_hot_reload_module_logs_one_warning(hot_reload, monkeypatch,
                                                    caplog):
    monkeypatch.setitem(sys.modules, "core.hot_reload", None)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        mod = _load()
    assert callable(mod.start_dashboard)
    msgs = [r.getMessage() for r in caplog.records
            if r.name == LOGGER and "hot-reload" in r.getMessage()]
    assert len(msgs) == 1, msgs
    assert "ImportError" in msgs[0] or "ModuleNotFoundError" in msgs[0], msgs


# --- finding 3: one watcher per process ---------------------------------

def test_a_live_watcher_thread_is_reused_not_doubled(hot_reload):
    _no_live_watcher()
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="hot-reload-watcher",
                         daemon=True)
    t.start()
    try:
        _load()
        _load()
    finally:
        stop.set()
        t.join(timeout=5)
    assert hot_reload._probe_calls == []


def test_a_dead_watcher_thread_does_not_block_a_restart(hot_reload):
    t = threading.Thread(target=lambda: None, name="hot-reload-watcher")
    t.start()
    t.join(timeout=5)
    assert not t.is_alive()
    _load()
    assert hot_reload._probe_calls == [SRC.parent]


def test_thread_name_matches_core_hot_reload():
    """The reuse check keys on the name core.hot_reload gives its thread."""
    mod = _load()
    src = (ROOT / "core" / "hot_reload.py").read_text(encoding="utf-8")
    names = re.findall(r'name="([^"]+)"', src)
    assert names == [mod._HOT_RELOAD_THREAD_NAME], names


# --- finding 4: the docstring says what the module is ---------------------

def test_docstring_drops_the_false_claims_and_names_the_gates(hot_reload):
    doc = _load().__doc__ or ""
    low = doc.lower()
    for false in ("ipad", "tkinter", "no auth", "read-only http"):
        assert false not in low, false
    for true in ("start_dashboard", "rc_dash_token", "hot-reload"):
        assert true in low, true


def test_source_is_ascii_lf_and_single_spaced():
    raw = SRC.read_bytes()
    assert raw.isascii()
    assert b"\r" not in raw
    assert b"\n\n\n\n" not in raw, "three blank lines in a row"
