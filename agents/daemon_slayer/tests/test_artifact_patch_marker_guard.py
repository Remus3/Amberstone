# arch: DS artifact patch-marker guard (RM-81 residual) | section=ds-tests | frozen=no
"""Every PER-PATCH DS artifact must carry its own internal patch marker.

RM-81 closed this for ONE artifact: ``cdragon_ability_ratios.json`` now
declares the patch it was extracted at, and ``_load_cdragon_ratio_sidecar``
refuses to trust the DIRECTORY alone. The residual is the same bug class over
the rest of ``data/daemon_slayer/<patch>/``: an artifact with no internal
marker cannot be shown to be stale, so a patch-refresh commit that copies it
forward is undetectable by inspection.

MEASURED 2026-07-24 across all five shipped dirs (16.10.1 .. 16.14.1, 87 feed
rows). The marker is spelled FOUR different ways on disk and the audit that
filed this residual undercounted the healthy artifacts badly:

* ``patch``            cdragon_ability_ratios, cdragon_ratio_drift, pickban_targets
* ``_patch``           ability_staleness, cdragon_spell_stats, wiki_ability_stats,
                       wiki_stats
* ``rc_patch``         the two authored event-mode augment feeds (named in
                       tools/ds_feed_index.KNOWN_STAMP_LAG, not here)
* ``ddragon_version``  manifest
* ``version``          items, champions, scenarios, champion_abilities,
                       build_orders_{sr,aram,arena}
* ``_meta.patch``      enchanter_items

``version`` DOES count as a patch marker here, and that is not a shortcut: RC's
patch identity IS the DDragon version. ``manifest.json`` records
``ddragon_version`` and it equals ``current.txt`` and equals the directory name
in every shipped dir, so ``version`` and the RC patch string are the same value
by construction rather than by coincidence.

That leaves exactly TWO artifacts with no marker of any spelling -
``arena_augments.json`` and ``items_meraki.json`` - both written by
``tools/daemon_slayer_extract.py`` and both genuinely re-fetched every extract
(mutable CommunityDragon / Meraki ``latest`` endpoints). The generator now
stamps them for every future extract, and the merger backfilled the marker into
the CURRENT dir's two copies in place, so ``PENDING_GENERATOR_STAMP`` is empty
and every per-patch artifact in the live dir is covered with no exemption.

Two artifacts declare a NON-matching marker on purpose and must not be reported
red: the authored event-mode augment feeds, whose body has not moved since
16.10.1. The exception list is IMPORTED from ``tools/ds_feed_index.py`` rather
than restated - one source of truth for "known stamp lag", and it keeps their
filenames out of the engine package, which ``tests/test_ds_share_data_snapshot_scope``
scans for as evidence of a real read.

These tests pin:

* the tolerant reader resolves all four top-level spellings plus the nested
  ``_meta.patch`` form, and reports the KEY it matched (not just the value),
* an artifact with no marker reads ``(None, None)`` - an unprovable vintage,
  which the guard treats exactly like a mismatch (the RM-81 contract),
* the guard logs at WARNING and is DEFAULT-OFF for enforcement,
* every per-patch artifact in the CURRENT dir HAS a marker (pending set aside),
* every per-patch artifact's marker MATCHES its dir (known lag aside),
* the unmarked set only ever SHRINKS,
* the generator stamps the two pending artifacts.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import (
    artifact_patch,
    artifact_patch_marker,
    check_artifact_patch,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Artifacts whose marker can only be added by RE-GENERATING them. The generator
# stamps both as of this commit; the shipped 16.14.1 copies predate it. This set
# must only ever shrink - a new name appearing here is a NEW instance of the
# RM-81 bug class and the subset assertion below turns red.
# Emptied by the merger 2026-07-25: both names were stamped in place rather than
# by re-running tools/daemon_slayer_extract.py. A re-extract re-fetches the Meraki
# and CommunityDragon ``latest`` endpoints, which are MUTABLE - it would have
# swapped item content underneath the same build-order regen this commit ships,
# so the two changes could no longer be attributed separately. The generator now
# stamps the field for every FUTURE extract (tools/daemon_slayer_extract.py
# stamp_patch); this pass only backfilled the current patch dir's metadata.
PENDING_GENERATOR_STAMP: frozenset[str] = frozenset()


def _known_stamp_lag() -> frozenset[str]:
    """Authored feeds that declare an older patch ON PURPOSE.

    Imported from tools/ds_feed_index.py so the exception list is not restated.
    """
    path = _REPO_ROOT / "tools" / "ds_feed_index.py"
    spec = importlib.util.spec_from_file_location("_ds_feed_index_for_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(mod.KNOWN_STAMP_LAG)


def _extract_tool():
    """Import tools/daemon_slayer_extract.py by path (tools/ is not a package)."""
    path = _REPO_ROOT / "tools" / "daemon_slayer_extract.py"
    spec = importlib.util.spec_from_file_location("_ds_extract_for_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _live_patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


# --- tolerant reader ---------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expect"),
    [
        ({"patch": "16.14.1"}, ("patch", "16.14.1")),
        ({"_patch": "16.14.1"}, ("_patch", "16.14.1")),
        ({"rc_patch": "16.10.1"}, ("rc_patch", "16.10.1")),
        ({"ddragon_version": "16.14.1"}, ("ddragon_version", "16.14.1")),
        ({"version": "16.14.1"}, ("version", "16.14.1")),
        ({"_meta": {"patch": "16.9.1"}}, ("_meta.patch", "16.9.1")),
    ],
)
def test_reader_resolves_every_shipped_spelling(doc, expect):
    assert artifact_patch_marker(doc) == expect


def test_reader_prefers_the_canonical_spelling_over_version():
    """``patch`` is the canonical stamp; ``version`` is the ambiguous fallback."""
    doc = {"version": "16.13.1", "patch": "16.14.1"}
    assert artifact_patch_marker(doc) == ("patch", "16.14.1")


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"count": 226, "source": "https://example.invalid"},
        {"patch": ""},
        {"patch": 16},
        {"_meta": {"count": 3}},
        ["not", "a", "dict"],
        None,
    ],
)
def test_absent_or_unusable_marker_reads_none(doc):
    """An unprovable vintage - the RM-81 contract treats this like a mismatch."""
    assert artifact_patch_marker(doc) == (None, None)


# --- path-level accessor + guard --------------------------------------------


def _write(root: Path, patch: str, name: str, doc) -> None:
    (root / patch).mkdir(parents=True, exist_ok=True)
    (root / patch / name).write_text(json.dumps(doc), encoding="utf-8")


def test_artifact_patch_reads_the_payloads_own_marker(tmp_path):
    _write(tmp_path, "99.9.9", "arena_augments.json", {"patch": "99.6.6"})
    assert artifact_patch(tmp_path, "99.9.9", "arena_augments.json") == "99.6.6"


def test_artifact_patch_is_none_for_missing_or_unmarked(tmp_path):
    _write(tmp_path, "99.9.9", "unmarked.json", {"count": 1})
    assert artifact_patch(tmp_path, "99.9.9", "unmarked.json") is None
    assert artifact_patch(tmp_path, "99.9.9", "absent.json") is None


def test_guard_passes_on_a_matching_marker(tmp_path, caplog):
    _write(tmp_path, "99.9.9", "a.json", {"patch": "99.9.9"})
    with caplog.at_level(logging.WARNING):
        assert check_artifact_patch(tmp_path, "99.9.9", "a.json") is True
    assert caplog.records == []


def test_guard_warns_on_a_stale_copy(tmp_path, caplog):
    _write(tmp_path, "99.9.9", "a.json", {"patch": "99.6.6"})
    with caplog.at_level(logging.WARNING):
        assert check_artifact_patch(tmp_path, "99.9.9", "a.json") is False
    assert any("99.6.6" in r.getMessage() for r in caplog.records)


def test_guard_warns_on_an_absent_marker(tmp_path, caplog):
    """No marker is not a pass - it is an unprovable vintage."""
    _write(tmp_path, "99.9.9", "a.json", {"count": 1})
    with caplog.at_level(logging.WARNING):
        assert check_artifact_patch(tmp_path, "99.9.9", "a.json") is False
    assert any("no patch marker" in r.getMessage() for r in caplog.records)


def test_guard_enforcement_is_default_off(tmp_path):
    """Characterizes WHICH default ships: detection always, enforcement opt-in.

    DEFAULT-OFF is forced by measurement, not preference - two artifacts on
    disk have no marker at all and two more declare an older patch on purpose,
    so a default-ON guard would raise on shipped 16.14.1 data.
    """
    _write(tmp_path, "99.9.9", "a.json", {"patch": "99.6.6"})
    assert check_artifact_patch(tmp_path, "99.9.9", "a.json") is False
    with pytest.raises(ValueError, match="99.6.6"):
        check_artifact_patch(tmp_path, "99.9.9", "a.json", strict=True)


# --- shipped-data invariants -------------------------------------------------


def _current_dir_artifacts() -> list[str]:
    return sorted(p.name for p in (_DATA_ROOT / _live_patch()).glob("*.json"))


def test_current_patch_dir_is_populated():
    assert len(_current_dir_artifacts()) >= 15


def test_every_per_patch_artifact_carries_a_marker():
    patch = _live_patch()
    missing = [
        name
        for name in _current_dir_artifacts()
        if name not in PENDING_GENERATOR_STAMP
        and artifact_patch(_DATA_ROOT, patch, name) is None
    ]
    assert missing == [], (
        f"artifacts under {patch}/ with no internal patch marker: {missing} - "
        "a copy-forward of these is undetectable by inspection (RM-81 class)"
    )


def test_every_marked_artifact_matches_its_directory():
    patch = _live_patch()
    exempt = PENDING_GENERATOR_STAMP | _known_stamp_lag()
    stale = {
        name: artifact_patch(_DATA_ROOT, patch, name)
        for name in _current_dir_artifacts()
        if name not in exempt
        and artifact_patch(_DATA_ROOT, patch, name) != patch
    }
    assert stale == {}, f"stale-copy artifacts under {patch}/: {stale}"


def test_unmarked_set_only_shrinks():
    """Subset, not equality: a regen legitimately empties this set."""
    patch = _live_patch()
    unmarked = {
        name
        for name in _current_dir_artifacts()
        if artifact_patch(_DATA_ROOT, patch, name) is None
    }
    assert unmarked <= PENDING_GENERATOR_STAMP, (
        f"NEW unmarked artifact(s): {sorted(unmarked - PENDING_GENERATOR_STAMP)}"
    )


def test_known_stamp_lag_artifacts_still_carry_a_marker():
    """Lagging on purpose is fine; carrying NO marker never is."""
    patch = _live_patch()
    present = set(_current_dir_artifacts())
    for name in sorted(_known_stamp_lag() & present):
        assert artifact_patch(_DATA_ROOT, patch, name) is not None, name


# --- generator stamps the pending artifacts ---------------------------------


def test_generator_stamp_helper_uses_the_canonical_spelling():
    stamp_patch = _extract_tool().stamp_patch
    out = stamp_patch({"count": 3, "augments": []}, "16.14.1")
    assert out["patch"] == "16.14.1"
    assert artifact_patch_marker(out) == ("patch", "16.14.1")


def test_generator_stamp_helper_does_not_mutate_the_payload():
    stamp_patch = _extract_tool().stamp_patch
    payload = {"count": 3}
    out = stamp_patch(payload, "16.14.1")
    assert payload == {"count": 3}
    assert out is not payload
    assert out["count"] == 3


def test_generator_stamps_both_pending_artifacts():
    """The write site must stamp exactly the artifacts that lacked a marker."""
    src = (_REPO_ROOT / "tools" / "daemon_slayer_extract.py").read_text(
        encoding="utf-8"
    )
    for name in sorted(PENDING_GENERATOR_STAMP):
        line = next(
            ln for ln in src.splitlines()
            if f'"{name}"' in ln and "_atomic_write_json" in ln
        )
        assert "stamp_patch(" in line, f"{name} write site is not stamped: {line}"
