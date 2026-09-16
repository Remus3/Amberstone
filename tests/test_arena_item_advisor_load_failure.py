"""coaches/_arena_item_advisor.py - a failed data load must not be cached forever.

BACKLOG row "item_advisor residuals" (filed 2026-09-11, LEDGER 1398), residual
(b). The three lazy loaders in this module carried the H1 cache-the-failure
pattern that ``item_advisor._load_exclusions`` was just fixed for:

  * ``_load_arena_builds`` (:73-80)  - ``except: cache = {}``
  * ``_load_aram_builds``  (:83-90)  - ``except: cache = {}``
  * ``_load_tags``         (:115-131) - ``except: pass`` then ``cache = out``

Each cache sentinel is ``is None``, so a ``{}`` written on failure is
success-shaped: after ONE transient read error (AV scan / editor lock on
Windows, a deploy that lands the file late) ``recompute_arena_build`` returns
``[]`` for every champion - or runs tank-blind - for the whole process
lifetime, with nothing retrying and nothing logged (the module imported no
logging at all).

No retry backoff is added, matching the shipped ``item_advisor`` fix: the
files are local and small (measured 171-237 KB) and the callers tick at the
coach poll cadence (``_base_coach`` sleeps 1.5 s / 3.0 s), so re-reading a
broken file per call is a stat or a sub-megabyte parse, not a disk storm. The
warning is emitted once per path so a persistent failure does not spam logs.

Mirrors ``tests/test_item_advisor_empty_cache.py``.
"""
from __future__ import annotations

import logging

import pytest

from coaches import _arena_item_advisor as aia

_LOGGER = "coaches._arena_item_advisor"

# (loader attr, path attr, cache attr, a key the REAL file must yield)
_LOADERS = [
    ("_load_arena_builds", "_ARENA_BUILDS_PATH", "_arena_builds_cache"),
    ("_load_aram_builds", "_ARAM_BUILDS_PATH", "_aram_builds_cache"),
    ("_load_tags", "_DDRAGON_PATH", "_tags_cache"),
]

_REAL_PATHS = {path_attr: getattr(aia, path_attr) for _, path_attr, _ in _LOADERS}


@pytest.fixture
def fresh_caches(monkeypatch):
    """Cold caches per test, and no poisoned cache left for the session."""
    for _, _, cache_attr in _LOADERS:
        monkeypatch.setattr(aia, cache_attr, None)
    # Introduced by the fix; ``raising=False`` so the RED run fails on the
    # assertion it is meant to fail on, not on an AttributeError here.
    monkeypatch.setattr(aia, "_WARNED_LOAD_PATHS", set(), raising=False)
    yield


def _missing(tmp_path):
    return tmp_path / "does_not_exist.json"


def _malformed_text(tmp_path):
    p = tmp_path / "malformed.json"
    p.write_text("{not json", encoding="utf-8")
    return p


def _wrong_shape(tmp_path):
    p = tmp_path / "list_shaped.json"
    p.write_text('["Jinx", "Caitlyn"]', encoding="utf-8")
    return p


_BAD_FILES = [_missing, _malformed_text, _wrong_shape]


@pytest.mark.parametrize("loader,path_attr,cache_attr", _LOADERS,
                         ids=[x[0] for x in _LOADERS])
@pytest.mark.parametrize("make_bad", _BAD_FILES, ids=lambda f: f.__name__)
def test_failure_returns_empty_then_retries_on_next_call(
    fresh_caches, monkeypatch, tmp_path, loader, path_attr, cache_attr, make_bad
):
    monkeypatch.setattr(aia, path_attr, make_bad(tmp_path))
    first = getattr(aia, loader)()
    assert first == {}, first
    assert getattr(aia, cache_attr) is None, (
        f"{loader}: failed load was cached as {{}} - the advisor would run "
        "degraded for the process lifetime"
    )
    # File becomes readable again.
    monkeypatch.setattr(aia, path_attr, _REAL_PATHS[path_attr])
    second = getattr(aia, loader)()
    assert second, f"{loader}: second call did not retry the load"


@pytest.mark.parametrize("loader,path_attr,cache_attr", _LOADERS,
                         ids=[x[0] for x in _LOADERS])
def test_failure_warns_once_per_path(
    fresh_caches, monkeypatch, tmp_path, caplog, loader, path_attr, cache_attr
):
    monkeypatch.setattr(aia, path_attr, _missing(tmp_path))
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(3):
            getattr(aia, loader)()
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING and r.name == _LOGGER]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "does_not_exist.json" in warnings[0].getMessage()


@pytest.mark.parametrize("loader,path_attr,cache_attr", _LOADERS,
                         ids=[x[0] for x in _LOADERS])
def test_successful_load_is_still_cached(
    fresh_caches, loader, path_attr, cache_attr
):
    """Guard: the fix must not turn the success path into a per-call read."""
    first = getattr(aia, loader)()
    assert first
    assert getattr(aia, cache_attr) is first
    assert getattr(aia, loader)() is first


def test_recompute_self_heals_after_transient_build_load_failure(
    fresh_caches, monkeypatch, tmp_path
):
    """Public surface: while both build files are unreadable the advisor
    answers [] without raising; once readable, the SAME process recovers."""
    monkeypatch.setattr(aia, "_ARENA_BUILDS_PATH", _missing(tmp_path))
    monkeypatch.setattr(aia, "_ARAM_BUILDS_PATH", _missing(tmp_path))
    kwargs = dict(champion="Jinx", current_items=[], gold=0,
                  alive_opponents=[], hp_pct=100)
    assert aia.recompute_arena_build(**kwargs) == []
    monkeypatch.setattr(aia, "_ARENA_BUILDS_PATH", _REAL_PATHS["_ARENA_BUILDS_PATH"])
    monkeypatch.setattr(aia, "_ARAM_BUILDS_PATH", _REAL_PATHS["_ARAM_BUILDS_PATH"])
    assert aia.recompute_arena_build(**kwargs), "advisor stayed blank after recovery"
