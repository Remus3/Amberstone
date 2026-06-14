"""Shared pytest fixtures for the RC test suite.

`reset_cs_retention_between_tests` - `dashboard._state_builder.build_state()`
holds a *process-global* last-champ_select across the fast no-draft
(ARAM / Mayhem / Arena) champ-select -> game transition (see
`dashboard/_cs_retention.py`). That persistence is correct in
production (the dashboard polls at 500ms and the view must survive the
transient loss) but it bleeds across `build_state()` test calls in a
single pytest process: a test that supplies a champ_select caches it,
then a later test expecting *no* champ_select gets the stale one
re-spliced. This autouse fixture resets the cache before every test so
isolation lives in exactly one place rather than scattered per-file
setUps. Lazy import keeps conftest collection dependency-free for
test runs that never touch the dashboard.

`redirect_shadow_paths_to_tmp` - the det-coach + HZ-C1/C2 shadow writers
default their jsonl target to a module-level `SHADOW_PATH` constant under
the repo's real data/ dir, and the dashboard state-builder calls them with
NO path argument. Any test that exercises `build_state()` therefore
appended junk rows (my_champion="Champ0", mode="client") to the PRODUCTION
shadow logs on every suite run (HZ-D4 root cause 2). Both writers read the
module global at call time (`target = path if path is not None else
SHADOW_PATH`), so monkeypatching the module attribute redirects every
default-path write to tmp_path. Explicit `path=` arguments (the normal
test seam) are unaffected. Modules that fail to import are skipped so
conftest collection stays dependency-free.
"""
from __future__ import annotations

import importlib

import pytest

_SHADOW_MODULES = (
    "core.hz_choice_shadow",
    "core.hz_build_shadow",
    "core.det_coach_shadow",
)


@pytest.fixture(autouse=True)
def reset_cs_retention_between_tests():
    try:
        from dashboard._cs_retention import reset_cs_retention
    except Exception:
        yield
        return
    reset_cs_retention()
    yield


@pytest.fixture(autouse=True)
def redirect_shadow_paths_to_tmp(monkeypatch, tmp_path):
    """Suite hermeticity: no test may append to the repo's real shadow logs
    (data/det_coach_shadow.jsonl / hz_choice_shadow.jsonl /
    hz_build_shadow.jsonl). See the module docstring for the HZ-D4 root
    cause. monkeypatch restores the real SHADOW_PATH after each test."""
    for mod_name in _SHADOW_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, "SHADOW_PATH"):
            fname = mod_name.rsplit(".", 1)[-1] + ".jsonl"
            monkeypatch.setattr(mod, "SHADOW_PATH", tmp_path / "shadow" / fname)
