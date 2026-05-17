"""Shared pytest fixtures for the RC test suite.

`reset_cs_retention_between_tests` — `dashboard._state_builder.build_state()`
holds a *process-global* last-champ_select across the fast no-draft
(ARAM / Mayhem / Arena) champ-select → game transition (see
`dashboard/_cs_retention.py`). That persistence is correct in
production (the dashboard polls at 500ms and the view must survive the
transient loss) but it bleeds across `build_state()` test calls in a
single pytest process: a test that supplies a champ_select caches it,
then a later test expecting *no* champ_select gets the stale one
re-spliced. This autouse fixture resets the cache before every test so
isolation lives in exactly one place rather than scattered per-file
setUps. Lazy import keeps conftest collection dependency-free for
test runs that never touch the dashboard.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_cs_retention_between_tests():
    try:
        from dashboard._cs_retention import reset_cs_retention
    except Exception:
        yield
        return
    reset_cs_retention()
    yield
