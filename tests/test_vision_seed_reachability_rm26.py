# arch: end-to-end reachability of the ultrawide/1440p seed profiles | section=vision-tests | frozen=no
"""RM-26: make the SEED profiles reachable, and pin exactly what that does
and does NOT change.

WHAT THIS DOES NOT DO - read this before believing the seed fixes cropping.
It does not move a single OCR crop rectangle. _scale_bbox
(core/vision_tesseract.py:136-145) already rescales by frame / _BASE_CACHE, and
the legacy path sets _BASE_CACHE = (1920,1080), so legacy boxes were ALREADY
being scaled proportionally to the frame. A derived seed pre-scales the same
boxes by W/1920 and then sets _BASE_CACHE = (W,H); the two cancel exactly.
MEASURED over all 21 regions of data/vision_regions.json against every
SEED_BASES entry: 0 of 21 crop rects differ at native or half-frame, and 1 px
(double int() truncation) for a frame downscaled to 1920x1080.
test_derived_seed_does_not_move_any_crop_rect pins that equivalence, because
the earlier consumer tests all stopped at _regions() and that is precisely why
the inertness went unnoticed. See the repo's "arithmetically INERT seam"
doctrine and feedback_rendered_field_is_not_evidence_of_a_producer.

WHAT IT ACTUALLY CHANGES. load_profile now answers with the native base for a
SEED_BASES resolution instead of [1920,1080], and consumers that key off that
base change behaviour:

  1. ingest_reference_from_path (core/vision_profiles.py:420-423) validates an
     operator-supplied still against load_profile(ck)["base"]. On this machine
     the live config_key is a 2560x1440 key that matches no stored profile, so
     that base moves [1920,1080] -> [2560,1440]: a native 2560x1440 reference
     screenshot that was REJECTED as the wrong size is now ACCEPTED. This is
     the real user-visible improvement.
  2. core/vision_tesseract._regions() stops discarding a tier-2 answer. The
     resulting crops are identical (above), but the region TABLE and _BASE_CACHE
     now describe the native resolution rather than a 1080p fiction.
  3. The calibrator reports source "resolution_seed" instead of "legacy_seed".
     Its ``seeded`` flag is True in BOTH cases, so the operator-visible warning
     is UNCHANGED - this is a label fix, not a UX fix.

The two breaks that made the seed unreachable at all:
  A. CONSUMER FILTER. _regions() accepted only source == "profile", so a tier-2
     answer was discarded outright (a resolver fix is not a consumer fix).
  B. NO SEED FILE. seed_profiles() has no production caller anywhere in the
     tree and data/vision_profiles/ is gitignored + per-machine, so tier 2 had
     nothing on disk to find. load_profile now derives the seed in memory.

PRECEDENCE: a PARSEABLE exact config_key profile always wins; a seed is only
consulted when none exists. An unparseable or zero-byte tier-1 file is treated
as absent and falls through to the seed - unchanged from before this commit,
which already fell through to a tier-2 seed FILE in that case. The invariant is
about a readable profile, not about the path existing; both cases are pinned.

Nothing here reads or writes the machine's real data/vision_profiles/ - the
profiles dir and the legacy baseline are both redirected to tmp_path.
"""
from __future__ import annotations

import json

import pytest

from core import vision_profiles as vp
from core import vision_tesseract as vt

_LEGACY_SRC = {"hp": [800, 900, 1100, 960], "gold": [1380, 1054, 1450, 1078]}
_FULL_KEY_3440 = ("3440x1440|GlobalScale=0.0000|ShowTeamFramesOnLeft=0"
                  "|MirroredScoreboard=0|FlipMiniMap=0|MinimapScale=0.5000")
_FULL_KEY_1080 = ("1920x1080|GlobalScale=0.0000|ShowTeamFramesOnLeft=0"
                  "|MirroredScoreboard=0|FlipMiniMap=0|MinimapScale=0.5000")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Redirect the profile store AND the legacy baseline into tmp_path so no
    assertion depends on what this machine happens to have calibrated."""
    d = tmp_path / "profiles"
    monkeypatch.setattr(vp, "PROFILES_DIR", d)
    legacy = tmp_path / "vision_regions.json"
    legacy.write_text(json.dumps(_LEGACY_SRC) + "\n", encoding="utf-8")
    monkeypatch.setattr(vp, "_LEGACY_REGIONS", legacy)
    return d


# ---------------------------------------------------------------- resolver ---

def test_seed_base_with_no_seed_file_is_derived_not_legacy(isolated):
    """B: 3440x1440 is a SEED_BASES entry. With no seed file on disk it must
    still resolve to a scaled seed, never to the unscaled 1080p baseline."""
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "resolution_seed"
    assert prof["seed_origin"] == "derived"
    assert prof["base"] == [3440, 1440]
    assert prof["resolution_key"] == "3440x1440"
    # proportionally scaled, NOT the unscaled 1920x1080 rectangle
    assert prof["regions"]["hp"] != _LEGACY_SRC["hp"]
    left = prof["regions"]["hp"][0]
    assert 1400 < left < 1470, left


def test_a_seed_file_wins_over_the_in_memory_derive(isolated):
    """A real seed FILE is authoritative over the derive; seed_origin says so."""
    vp.save_profile("3440x1440", {"hp": [11, 22, 33, 44]}, [3440, 1440])
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "resolution_seed"
    assert prof["seed_origin"] == "file"
    assert prof["regions"] == {"hp": [11, 22, 33, 44]}


def test_a_readable_exact_profile_always_beats_the_derived_seed(isolated):
    """PRECEDENCE: a calibrated per-config profile must never be shadowed."""
    vp.save_profile(_FULL_KEY_3440, {"hp": [1, 2, 3, 4]}, [3440, 1440])
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "profile"
    assert prof["regions"] == {"hp": [1, 2, 3, 4]}
    assert "seed_origin" not in prof


def test_an_unparseable_exact_profile_is_treated_as_absent(isolated):
    """The invariant is about a READABLE profile. A corrupt tier-1 file falls
    through to the seed - which is what the pre-2b code did too (it fell to a
    tier-2 seed FILE), so this is not a regression, but the stated rule has to
    say "parseable" or it claims more than the code delivers."""
    isolated.mkdir(parents=True, exist_ok=True)
    vp.profile_path(_FULL_KEY_3440).write_text("{not json", encoding="utf-8")
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "resolution_seed"
    assert prof["seed_origin"] == "derived"


def test_a_zero_byte_exact_profile_is_treated_as_absent(isolated):
    """Same for a truncated / zero-byte write."""
    isolated.mkdir(parents=True, exist_ok=True)
    vp.profile_path(_FULL_KEY_3440).write_text("", encoding="utf-8")
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "resolution_seed"


def test_an_empty_but_valid_exact_profile_still_wins(isolated):
    """``{}`` PARSES, so it is a real tier-1 hit and the seed is not consulted.
    (_regions() then ignores it separately, because it requires truthy
    regions.)"""
    isolated.mkdir(parents=True, exist_ok=True)
    vp.profile_path(_FULL_KEY_3440).write_text("{}", encoding="utf-8")
    prof = vp.load_profile(_FULL_KEY_3440)
    assert prof["source"] == "profile"
    assert prof["regions"] == {}


def test_1920x1080_is_still_deliberately_not_seeded(isolated):
    """The 1080p exclusion holds: it is the SOURCE baseline, so seeding it
    could only ever be an identity write over the hand calibration."""
    assert [1920, 1080] not in vp.SEED_BASES
    prof = vp.load_profile(_FULL_KEY_1080)
    assert prof["source"] == "legacy_seed"
    assert prof["base"] == [1920, 1080]


def test_non_seed_resolution_still_falls_to_legacy(isolated):
    """A resolution nobody seeded keeps the tier-3 behaviour unchanged."""
    prof = vp.load_profile("7680x2160|GlobalScale=0.0000")
    assert prof["source"] == "legacy_seed"
    assert prof["base"] == [1920, 1080]


# ---------------------------------------------------------------- consumer ---

def _fake_profile(monkeypatch, prof):
    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: prof)
    vt.reload_regions()


def test_ocr_consumer_honours_a_resolution_seed(monkeypatch):
    """A: the OCR hot path must USE a tier-2 seed instead of discarding it."""
    _fake_profile(monkeypatch, {
        "config_key": _FULL_KEY_3440,
        "base": [3440, 1440],
        "regions": {"hp": [1433, 1199, 1970, 1279]},
        "source": "resolution_seed",
        "resolution_key": "3440x1440",
        "seed_origin": "derived",
    })
    regions = vt._regions()
    assert regions.get("hp") == [1433, 1199, 1970, 1279]
    # the seed base must drive _scale_bbox, not the 1920 default
    assert vt._BASE_CACHE == (3440, 1440)
    vt.reload_regions()


def test_ocr_consumer_still_prefers_an_exact_profile(monkeypatch):
    """Regression guard: tier 1 behaviour in the consumer is unchanged."""
    _fake_profile(monkeypatch, {
        "config_key": "2560x1440|X",
        "base": [2560, 1440],
        "regions": {"gold": [1463, 1407, 1549, 1433]},
        "source": "profile",
    })
    regions = vt._regions()
    assert regions.get("gold") == [1463, 1407, 1549, 1433]
    assert vt._BASE_CACHE == (2560, 1440)
    vt.reload_regions()


def test_calibrator_labels_a_resolution_seed_as_seeded(monkeypatch):
    """The calibrator's ``seeded`` flag drives the only "these are untuned,
    drag them onto the HUD" warning the operator ever sees. A tier-2 seed is
    exactly that, so it must not be reported as a finished calibration."""
    from dashboard import routes_vision_calibrator as rc

    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: {
        "config_key": _FULL_KEY_3440,
        "base": [3440, 1440],
        "regions": {"hp": [1433, 1199, 1970, 1279]},
        "source": "resolution_seed",
        "resolution_key": "3440x1440",
        "seed_origin": "derived",
    })
    payload = rc._profile_regions_payload()
    assert payload["source"] == "resolution_seed"
    assert payload["seeded"] is True
    # already at the native base - it must NOT be rescaled like a legacy seed
    assert payload["base"] == [3440, 1440]
    assert payload["regions"]["hp"] == [1433, 1199, 1970, 1279]


def test_calibrator_still_reports_an_exact_profile_as_not_seeded(monkeypatch):
    """Regression guard: a real calibration keeps seeded False."""
    from dashboard import routes_vision_calibrator as rc

    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: {
        "config_key": "2560x1440|X",
        "base": [2560, 1440],
        "regions": {"gold": [1463, 1407, 1549, 1433]},
        "source": "profile",
    })
    payload = rc._profile_regions_payload()
    assert payload["source"] == "profile"
    assert payload["seeded"] is False


def test_ocr_consumer_still_rejects_a_legacy_seed(tmp_path, monkeypatch):
    """legacy_seed must NOT short-circuit the legacy file path: that path reads
    the file's own ``_base`` metadata, which load_profile's tier 3 discards.

    POSITIVE assertion on purpose - "the seed key is absent" would also pass if
    _regions() returned {} for an unrelated reason. This proves the legacy
    branch actually RAN by pinning both its regions and the _base it alone
    honours (feedback_negative_assertion_rules_out_without_pinning_down)."""
    legacy = tmp_path / "vision_regions.json"
    legacy.write_text(json.dumps({"_base": [2560, 1440],
                                  "rm26_from_file": [7, 8, 9, 10]}),
                      encoding="utf-8")
    monkeypatch.setattr(vt, "_REGIONS_FILE", legacy)
    _fake_profile(monkeypatch, {
        "config_key": "whatever",
        "base": [1920, 1080],
        "regions": {"rm26_from_profile": [1, 2, 3, 4]},
        "source": "legacy_seed",
    })
    regions = vt._regions()
    assert regions == {"rm26_from_file": [7, 8, 9, 10]}
    assert "rm26_from_profile" not in regions
    # only the legacy branch reads the file's own _base
    assert vt._BASE_CACHE == (2560, 1440)
    vt.reload_regions()


def test_derived_seed_does_not_move_any_crop_rect(isolated):
    """THE TEST THAT WOULD HAVE CAUGHT THE INERT SEAM.

    Every other consumer test stops at _regions(). _scale_bbox then rescales by
    frame / _BASE_CACHE, and pre-scaling the boxes by W/1920 while setting
    _BASE_CACHE to (W,H) cancels exactly against leaving them at 1080p with
    _BASE_CACHE (1920,1080). So the seed changes the region TABLE and changes
    NO CROP. Pinned so nobody re-derives the false "ultrawide was cropping
    unscaled 1080p boxes" story from the region table alone."""
    legacy = {k: v for k, v in json.loads(
        vp._LEGACY_REGIONS.read_text(encoding="utf-8")).items()
        if isinstance(v, list) and len(v) == 4}
    assert legacy, "the redirected baseline must carry real boxes"
    for w, h in vp.SEED_BASES:
        derived = vp.derive_scaled_regions(legacy, [1920, 1080], [w, h])
        for frame in ((w, h), (w // 2, h // 2)):
            vt._BASE_CACHE = (1920, 1080)
            before = {k: vt._scale_bbox(v, *frame) for k, v in legacy.items()}
            vt._BASE_CACHE = (w, h)
            after = {k: vt._scale_bbox(v, *frame) for k, v in derived.items()}
            assert before == after, f"{w}x{h} frame={frame}"
    vt.reload_regions()
