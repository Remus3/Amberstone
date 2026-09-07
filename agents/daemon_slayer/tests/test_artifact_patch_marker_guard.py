# arch: DS artifact patch-marker guard (RM-81 residual) | section=ds-tests | frozen=no
"""Every PER-PATCH DS artifact must carry its own internal patch marker.

RM-81 closed this for ONE artifact: ``cdragon_ability_ratios.json`` now
declares the patch it was extracted at, and ``_load_cdragon_ratio_sidecar``
refuses to trust the DIRECTORY alone. The residual is the same bug class over
the rest of ``data/daemon_slayer/<patch>/``: an artifact with no internal
marker cannot be shown to be stale, so a patch-refresh commit that copies it
forward is undetectable by inspection.

MEASURED 2026-07-24, re-measured 2026-08-15 across all six shipped dirs
(16.10.1 .. 16.15.1, 107 feed rows - both numbers re-derived from disk and from
tools/ds_feed_index.json, which agree; the line here previously said five dirs
and 87 rows and had gone stale by a whole patch). The marker is spelled FOUR
different ways on disk and the audit that filed this residual undercounted the
healthy artifacts badly:

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

That 2026-07-24 pass left exactly TWO artifacts with no marker of any spelling -
``arena_augments.json`` and ``items_meraki.json`` - both written by
``tools/daemon_slayer_extract.py`` against the mutable CommunityDragon / Meraki
``latest`` endpoints. The generator now stamps them for every future extract,
and the merger backfilled the marker into the CURRENT dir's two copies in place.
Re-measured 2026-08-15: ZERO of the 20 artifacts in the live dir lack a marker,
``PENDING_GENERATOR_STAMP`` is empty, and nothing is exempt.

``items_meraki.json`` used to be described here as "genuinely re-fetched every
extract", which invited reading a re-fetch as a refresh. Both halves are true
and they are not the same claim: its ``fetched_at`` has moved on every one of
the six extracts while its BODY has been byte-identical in all six dirs (feed
index body_md5 ``73446cf8`` throughout). It is precisely the artifact that makes
a body-hash-only staleness check cry wolf forever, which is why RM-213's
``artifact_refresh_verdict`` needs body AND vintage rather than either alone.

Two artifacts declare a NON-matching marker on purpose and must not be reported
red: the authored event-mode augment feeds, whose body has not moved since
16.10.1. The exception list is IMPORTED from ``tools/ds_feed_index.py`` rather
than restated - one source of truth for "known stamp lag", so the filenames
appear once and this module cannot drift from the registry it describes.

These tests pin:

* the tolerant reader resolves all four top-level spellings plus the nested
  ``_meta.patch`` form, and reports the KEY it matched (not just the value),
* an artifact with no marker reads ``(None, None)`` - an unprovable vintage,
  which the guard treats exactly like a mismatch (the RM-81 contract),
* the guard logs at WARNING and is DEFAULT-OFF for enforcement,
* every per-patch artifact in the CURRENT dir HAS a marker (pending set aside),
* every per-patch artifact's marker MATCHES its dir (known lag aside),
* the unmarked set only ever SHRINKS,
* the generator stamps the two historically-unmarked artifacts.

RM-213 adds the SECOND axis, in the tmp_path-only block at the bottom: a marker
that MATCHES its directory is not evidence of a refresh, because the marker is
exactly the field a copy-forward rewrites. Those tests pin
``artifact_vintage`` / ``artifact_body_fingerprint`` /
``artifact_refresh_verdict`` / ``check_artifact_refresh`` on synthetic
documents only - the cross-dir assertion over shipped data lives in
``tests/test_ds_feed_index.py``, which is where the previous-patch baseline is
actually available (the engine package alone carries a single patch dir, so it
can never read a previous-patch baseline off disk).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import (
    _BODY_STRIP_KEYS,
    _VINTAGE_KEYS,
    artifact_body_fingerprint,
    artifact_patch,
    artifact_patch_marker,
    artifact_refresh_verdict,
    artifact_vintage,
    check_artifact_patch,
    check_artifact_refresh,
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

    DEFAULT-OFF is forced by measurement, not preference - two artifacts
    declare an older patch ON PURPOSE (tools/ds_feed_index.KNOWN_STAMP_LAG), so
    a default-ON guard would raise on the shipped current dir.

    Re-measured 2026-08-15: the OTHER half of the old justification here -
    "two artifacts on disk have no marker at all" - is now false, and zero of
    the 20 live artifacts lack a marker. The reason survives on the lag pair
    alone; test_every_per_patch_artifact_carries_a_marker is what actually
    holds the unmarked count at zero, so correcting the prose weakens nothing.
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


# The two artifacts that carried no marker when the RM-81 residual was filed.
# They are NOT in PENDING_GENERATOR_STAMP - that set is empty because both were
# backfilled in place - so a write-site guard has to name them by literal or
# check nothing at all.
HISTORICALLY_UNMARKED: tuple[str, ...] = (
    "arena_augments.json",
    "items_meraki.json",
)


def test_generator_stamps_the_historically_unmarked_artifacts():
    """The write sites must stamp exactly the artifacts that lacked a marker.

    Was ``test_generator_stamps_both_pending_artifacts``, which looped over
    ``sorted(PENDING_GENERATOR_STAMP)`` - an EMPTY frozenset since 2026-07-25.
    It asserted over zero artifacts while its name promised two, so deleting
    ``stamp_patch(`` from either write site left it green.

    Of the two honest options - assert the pending set is empty, or pin the two
    names by literal - this takes the literals. Emptiness is true by
    construction and says nothing about the generator, which is the thing the
    test name is about; the literals keep the guard the name advertises.
    """
    src = (_REPO_ROOT / "tools" / "daemon_slayer_extract.py").read_text(
        encoding="utf-8"
    )
    for name in HISTORICALLY_UNMARKED:
        sites = [
            ln for ln in src.splitlines()
            if f'"{name}"' in ln and "_atomic_write_json" in ln
        ]
        assert len(sites) == 1, f"{name}: expected one write site, got {sites}"
        assert "stamp_patch(" in sites[0], (
            f"{name} write site is not stamped: {sites[0]}"
        )


# --- RM-213: the refresh axis (tmp_path / synthetic only) --------------------
#
# Everything below is deliberately fixture-only. The cross-dir assertion over
# shipped data needs the PREVIOUS patch dir, which the engine package cannot
# see (it carries a single dir), so it lives in tests/test_ds_feed_index.
# These pin the mechanism, not the corpus.

# The three timestamp shapes actually present under data/daemon_slayer/, each
# with and without microseconds. Measured 2026-08-15: 'Z' (ability_staleness
# _generated_at, mayhem source_generated_at), '-0500' (items_meraki /
# arena_augments / manifest), '+00:00' (cherry_augments fetched_at). A single
# strptime format rejects three of these six; datetime.fromisoformat takes all.
_ON_DISK_VINTAGE_SHAPES: tuple[str, ...] = (
    "2026-07-18T11:59:22Z",
    "2026-05-18T02:21:07.268643Z",
    "2026-07-30T18:24:22-0500",
    "2026-05-13T17:42:46.123456-0500",
    "2026-05-18T03:58:33+00:00",
    "2026-05-18T03:58:33.339013+00:00",
)


def _sample_doc(
    *, leaf: float = 60.0, vintage: str | None = "2026-07-18T11:59:22Z"
) -> dict:
    """A synthetic artifact with content at depth plus strippable noise.

    The nested ``patch`` / ``fetched_at`` keys are what prove the fingerprint
    strips RECURSIVELY rather than only at the top level.
    """
    doc: dict = {
        "patch": "99.9.9",
        "_note": "prose - never content",
        "count": 2,
        "data": {"Aatrox": {"Q": {"total_ad_pct": [leaf, 67.5], "patch": "99.9.9"}}},
        "rows": [{"champion": "Zac", "fetched_at": "2026-01-01T00:00:00Z"}],
    }
    if vintage is not None:
        doc["_generated_at"] = vintage
    return doc


@pytest.mark.parametrize("key", _VINTAGE_KEYS)
def test_vintage_reader_resolves_every_shipped_spelling(key):
    """Parametrized over the CONSTANT, so a seventh spelling is covered free."""
    assert artifact_vintage({key: "2026-07-18T11:59:22Z", "count": 1}) == (
        key,
        "2026-07-18T11:59:22Z",
    )


@pytest.mark.parametrize("stamp", _ON_DISK_VINTAGE_SHAPES)
def test_vintage_reader_parses_every_shipped_offset_shape(stamp):
    """Every shape on disk parses, carries tzinfo, and is returned VERBATIM."""
    assert artifact_vintage({"_generated_at": stamp}) == ("_generated_at", stamp)
    assert datetime.fromisoformat(stamp).tzinfo is not None


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"count": 226, "source": "https://example.invalid"},
        {"_generated_at": ""},
        {"_generated_at": 20260718},
        {"_generated_at": "sometime last Tuesday"},
        {"_generated_at": "16.15.1"},
        ["not", "a", "dict"],
        None,
    ],
)
def test_vintage_reader_is_none_for_absent_or_unusable(doc):
    """Unparseable is UNPROVABLE, not "now" - the artifact_patch_marker contract."""
    assert artifact_vintage(doc) == (None, None)


def test_body_fingerprint_ignores_marker_and_wall_clock():
    """A relabel plus a re-stamp must not move the fingerprint by one bit."""
    base = artifact_body_fingerprint(_sample_doc())
    relabelled = _sample_doc()
    relabelled["patch"] = "99.6.6"
    relabelled["_patch"] = "99.6.6"
    relabelled["fetched_at"] = "2030-01-01T00:00:00Z"
    relabelled["_generated_at"] = "2030-01-01T00:00:00Z"
    relabelled["data"]["Aatrox"]["Q"]["patch"] = "1.2.3"
    relabelled["rows"][0]["fetched_at"] = "2030-01-01T00:00:00Z"
    assert artifact_body_fingerprint(relabelled) == base


def test_body_fingerprint_changes_when_real_content_changes():
    """Pairs with the test above - alone, either one passes on a constant."""
    assert artifact_body_fingerprint(_sample_doc(leaf=60.0)) != (
        artifact_body_fingerprint(_sample_doc(leaf=61.0))
    )


def test_verdict_body_moved():
    prior = artifact_body_fingerprint(_sample_doc(leaf=60.0))
    assert artifact_refresh_verdict(
        _sample_doc(leaf=61.0),
        prior_body=prior,
        prior_vintage="2026-07-18T11:59:22Z",
    ) == "body-moved"


def test_verdict_vintage_moved():
    """The items_meraki shape: re-run every extract, returns identical bytes."""
    doc = _sample_doc(vintage="2026-07-30T18:24:22-0500")
    assert artifact_refresh_verdict(
        doc,
        prior_body=artifact_body_fingerprint(doc),
        prior_vintage="2026-07-16T08:59:07-0500",
    ) == "vintage-moved"


def test_verdict_frozen():
    """The ability_staleness shape: body AND generation stamp both unmoved."""
    doc = _sample_doc()
    assert artifact_refresh_verdict(
        doc,
        prior_body=artifact_body_fingerprint(doc),
        prior_vintage="2026-07-18T11:59:22Z",
    ) == "frozen"


def test_verdict_unprovable():
    """The scenarios / wiki_* shape: no generation stamp to reason from."""
    doc = _sample_doc(vintage=None)
    assert artifact_refresh_verdict(
        doc, prior_body=artifact_body_fingerprint(doc), prior_vintage=None
    ) == "unprovable"


def test_verdict_no_baseline_is_its_own_answer():
    """Absent baseline is a NAMED verdict, distinguishable from all four others."""
    verdict = artifact_refresh_verdict(
        _sample_doc(), prior_body=None, prior_vintage=None
    )
    assert verdict == "no-baseline"
    assert verdict not in {"body-moved", "vintage-moved", "frozen", "unprovable"}


def test_check_artifact_refresh_warns_and_is_default_off(tmp_path, caplog):
    """Detection always, enforcement opt-in - same contract as the marker guard."""
    doc = _sample_doc()
    _write(tmp_path, "99.9.9", "a.json", doc)
    kwargs = {
        "prior_body": artifact_body_fingerprint(doc),
        "prior_vintage": "2026-07-18T11:59:22Z",
    }
    with caplog.at_level(logging.WARNING):
        assert check_artifact_refresh(tmp_path, "99.9.9", "a.json", **kwargs) is False
    warned = [r.getMessage() for r in caplog.records]
    assert any("a.json" in m and "frozen" in m for m in warned), warned
    with pytest.raises(ValueError, match="frozen"):
        check_artifact_refresh(tmp_path, "99.9.9", "a.json", strict=True, **kwargs)


def test_check_artifact_refresh_passes_with_no_baseline(tmp_path, caplog):
    """A missing previous dir is a TESTED pass, never a silent skip."""
    _write(tmp_path, "99.9.9", "a.json", _sample_doc())
    with caplog.at_level(logging.WARNING):
        assert check_artifact_refresh(
            tmp_path, "99.9.9", "a.json", prior_body=None, prior_vintage=None
        ) is True
    assert caplog.records == []


def test_marker_rewrite_alone_does_not_clear_the_refresh_check(tmp_path):
    """RM-213 IN ONE TEST: the copy-forward that the marker guard cannot see.

    Take an artifact generated at 99.6.6, copy it forward into the 99.9.9 dir,
    and rewrite NOTHING except the patch key. check_artifact_patch goes green -
    the marker now matches its directory, which is exactly why 10 of the 20
    shipped artifacts pass it on a body that never moved. The refresh check is
    what stays red.
    """
    original = _sample_doc()
    original["patch"] = "99.6.6"
    prior_body = artifact_body_fingerprint(original)
    _, prior_vintage = artifact_vintage(original)

    copied_forward = dict(original)
    copied_forward["patch"] = "99.9.9"
    _write(tmp_path, "99.9.9", "a.json", copied_forward)

    assert check_artifact_patch(tmp_path, "99.9.9", "a.json") is True
    assert check_artifact_refresh(
        tmp_path,
        "99.9.9",
        "a.json",
        prior_body=prior_body,
        prior_vintage=prior_vintage,
    ) is False


def test_vintage_keys_agree_with_the_feed_index_wall_clock_set():
    """Parity for a DELIBERATE duplication.

    The engine package must not import from tools/, so abilities.py restates
    ds_feed_index's key names. Subset, not equality, for the vintage set: the
    engine may narrow what it treats as a generation stamp, but must never
    invent a key the index does not strip - that would make a fingerprint
    computed here incomparable with a stored body_md5 row.

    Also pins the FULL strip set, since the docstring claim that a caller may
    pass a stored index row straight in as ``prior_body`` depends on the two
    canonicalisations being identical, not merely similar.
    """
    path = _REPO_ROOT / "tools" / "ds_feed_index.py"
    spec = importlib.util.spec_from_file_location("_ds_feed_index_parity", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert len(set(_VINTAGE_KEYS)) == len(_VINTAGE_KEYS), "duplicate vintage key"
    assert set(_VINTAGE_KEYS) <= set(mod._WALL_CLOCK), (
        f"vintage keys the feed index does not strip: "
        f"{sorted(set(_VINTAGE_KEYS) - set(mod._WALL_CLOCK))}"
    )
    assert set(_BODY_STRIP_KEYS) == set(mod._STRIP), (
        f"canonicalisation drift: engine-only="
        f"{sorted(set(_BODY_STRIP_KEYS) - set(mod._STRIP))} "
        f"index-only={sorted(set(mod._STRIP) - set(_BODY_STRIP_KEYS))}"
    )
