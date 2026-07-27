"""Regression tests for A1 - poisoned arena augment name-map cache.

Spec: docs/specs/2026-07-19-silent-except-triage.md section 2a (A1) + section 4.

The defect: ``coaches.arena_coach._augment_name_map`` built ``out`` inside a
``try`` but assigned ``_AUG_NAME_MAP_CACHE = out`` OUTSIDE it. Any failure -
total OR mid-loop - pinned an empty or partially built map into the
process-lifetime cache, so ``_resolve_augment_apiname`` returned ``None``
forever and augment persistence was skipped for the rest of the process.

Per the section-4 rule these tests MUST fail while the error is swallowed:
  - recovery shape: fault, call, un-fault, call again, assert the second call
    succeeds (fails while a failed/partial result is cached),
  - observability shape: assert a record at level >= WARNING (fails while the
    only record is DEBUG).
"""

import json
import logging
from pathlib import Path

import pytest

from coaches import arena_coach


@pytest.fixture(autouse=True)
def _reset_augment_cache():
    """The cache is process-lifetime module state - isolate every test."""
    arena_coach._AUG_NAME_MAP_CACHE = None
    yield
    arena_coach._AUG_NAME_MAP_CACHE = None


@pytest.fixture
def arena_warnings():
    """Collect >= WARNING records straight off the module logger.

    Attaching to the logger itself rather than using caplog avoids any
    dependence on propagation config from core.log_setup.
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Collect(level=logging.WARNING)
    arena_coach.logger.addHandler(handler)
    prior = arena_coach.logger.level
    arena_coach.logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        arena_coach.logger.removeHandler(handler)
        arena_coach.logger.setLevel(prior)


def _snapshot_present() -> bool:
    snap_dir = arena_coach._APP_DIR / "data" / "daemon_slayer"
    if not snap_dir.is_dir():
        return False
    return any(
        (p / "arena_augments.json").exists()
        for p in snap_dir.iterdir()
        if p.is_dir()
    )


def test_arena_augment_snapshot_is_committed() -> None:
    """Meta-guard: the snapshot every test below reads is TRACKED.

    2026-07-27 skip audit: this module used to hang a module-wide
    ``skipif(not _snapshot_present())`` off that same lookup.
    data/daemon_slayer/<patch>/arena_augments.json is committed for every
    vendored patch (16.10.1 .. 16.14.1), so the condition could only ever be
    true when the committed snapshot had been deleted - i.e. exactly when the
    cache tests matter - and the whole module would have gone green by
    skipping. Pinning it as its own assertion keeps the requirement visible
    without gating the suite behind it.
    """
    assert _snapshot_present(), (
        "no data/daemon_slayer/*/arena_augments.json on disk - the tracked "
        "Arena augment snapshot is missing from this checkout"
    )


def _expected_keys_from_disk() -> list[str]:
    """Display-name keys of the newest snapshot, read without the cache."""
    snap_dir = arena_coach._APP_DIR / "data" / "daemon_slayer"
    patches = sorted(
        [p for p in snap_dir.iterdir() if p.is_dir()],
        key=arena_coach._patch_dir_key, reverse=True,
    )
    for patch_dir in patches:
        f = patch_dir / "arena_augments.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        keys = []
        for aug in data.get("augments") or []:
            api = str(aug.get("apiName") or "").strip()
            name = str(aug.get("name") or "").strip()
            if api and name:
                keys.append(name.lower().replace(" ", ""))
        return keys
    return []


class _PartialList(list):
    """Yields ``n_ok`` items then raises - simulates a mid-loop failure."""

    def __init__(self, items, n_ok):
        super().__init__(items)
        self._n_ok = n_ok

    def __iter__(self):
        for i, item in enumerate(list.__iter__(self)):
            if i >= self._n_ok:
                raise RuntimeError("simulated mid-loop augment parse failure")
            yield item


def test_total_failure_is_not_cached_and_map_recovers(monkeypatch):
    """RECOVERY shape - a total build failure must not poison the cache."""
    real_iterdir = Path.iterdir

    def _boom(self):
        raise OSError("simulated snapshot dir failure")

    monkeypatch.setattr(Path, "iterdir", _boom)
    first = arena_coach._augment_name_map()
    assert first == {}, "a failed build should yield an empty map on that call"

    monkeypatch.setattr(Path, "iterdir", real_iterdir)
    second = arena_coach._augment_name_map()
    assert second, (
        "the failed build was cached for the process lifetime - the map never "
        "recovers once the fault is removed (A1 cache poisoning)"
    )


def test_partial_build_is_not_cached_and_map_recovers(monkeypatch):
    """RECOVERY shape - the worse case: a PARTIALLY built map gets pinned.

    Only some augments silently stop resolving, so the symptom reads as bad
    data rather than a crash.
    """
    real_loads = json.loads

    def _partial_loads(*args, **kwargs):
        data = real_loads(*args, **kwargs)
        if isinstance(data, dict) and data.get("augments"):
            data["augments"] = _PartialList(data["augments"], n_ok=2)
        return data

    monkeypatch.setattr(arena_coach.json, "loads", _partial_loads)
    first = arena_coach._augment_name_map()
    monkeypatch.undo()

    full = arena_coach._augment_name_map()
    assert len(full) > len(first), (
        "the partially built map was cached for the process lifetime - some "
        "augments never resolve again (A1 cache poisoning, partial case)"
    )


def test_partial_build_resolves_every_augment_after_recovery(monkeypatch):
    """A resolver miss caused by the partial cache is operator-invisible."""
    real_loads = json.loads

    def _partial_loads(*args, **kwargs):
        data = real_loads(*args, **kwargs)
        if isinstance(data, dict) and data.get("augments"):
            data["augments"] = _PartialList(data["augments"], n_ok=1)
        return data

    # Read the newest snapshot directly so the expected key is derived from
    # disk, never from the (possibly poisoned) cache under test.
    expected_keys = _expected_keys_from_disk()
    assert len(expected_keys) > 1, "snapshot too small to exercise a partial build"

    monkeypatch.setattr(arena_coach.json, "loads", _partial_loads)
    arena_coach._augment_name_map()
    monkeypatch.undo()

    unresolved = [
        k for k in expected_keys
        if arena_coach._resolve_augment_apiname(k) is None
    ]
    assert not unresolved, (
        f"{len(unresolved)} of {len(expected_keys)} augments no longer resolve "
        "after a partial build was cached (A1 - the symptom looks like bad "
        "data, not a crash)"
    )


def test_build_failure_logs_at_warning(monkeypatch, arena_warnings):
    """OBSERVABILITY shape - a DEBUG line cannot satisfy this."""

    def _boom(self):
        raise OSError("simulated snapshot dir failure")

    monkeypatch.setattr(Path, "iterdir", _boom)
    arena_coach._augment_name_map()

    assert arena_warnings, (
        "augment name-map build failure is invisible - it is only logged at "
        "DEBUG, so no operator, alert, or health surface ever sees it"
    )
    assert any(
        "augment" in r.getMessage().lower() for r in arena_warnings
    ), "the WARNING record should name the augment name map"
