"""P1-5 golden parity fixtures for game math (core/math_core.py).

Every case in ``tests/golden/game_math_cases.json`` carries an EXTERNAL source
(a League wiki worked example at a pinned revision, or a language reference's
documented example). A golden built from our own implementation proves
nothing, so this runner refuses a case whose source is missing, internal, or
not one of the declared external kinds.

Three things are checked against the SAME golden file:

1. the pure core ``core.math_core`` (the canonical implementation);
2. every duplicate of the same formula elsewhere in the tree (the DS engine's
   resist curve, its penetration pipelines and the three copies of the
   per-level growth curve) - "the same logic in two places is checked against
   the same golden file";
3. the web side: the JavaScript built-ins the dashboards use for display
   rounding (``Math.round`` / ``Number.prototype.toFixed``), run under node
   when node is on PATH.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core import math_core

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden" / "game_math_cases.json"
_DEFAULT_TOL = 1e-9
_EXTERNAL_KINDS = {"wiki", "language-doc"}
_EXTERNAL_HOSTS = (
    "https://wiki.leagueoflegends.com/",
    "https://docs.python.org/",
    "https://developer.mozilla.org/",
    "https://tc39.es/",
)


def _load() -> dict:
    return json.loads(GOLDEN.read_text(encoding="ascii"))


DATA = _load()
CASES = DATA["cases"]
SOURCES = DATA["sources"]


def _close(actual, expected, tol) -> bool:
    if isinstance(expected, str):
        return actual == expected
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if expected == 0 and isinstance(expected, float) and math.copysign(1.0, expected) < 0:
        # -0.0 is a distinct golden (JS Math.round(-0.1) is -0): the sign must match.
        return actual == 0 and math.copysign(1.0, actual) < 0
    return abs(actual - expected) <= tol


def _call(fn_name: str, case: dict):
    fn = getattr(math_core, fn_name)
    return fn(*case.get("args", []), **case.get("kwargs", {}))


# --------------------------------------------------------------------------
# The golden file itself


def test_golden_file_is_large_enough_to_mean_something():
    # Anchor: an EMPTY case list must not pass the per-case runner vacuously.
    assert len(CASES) >= 60


def test_every_case_has_an_external_source():
    ids = set()
    for case in CASES:
        assert case["id"] not in ids, f"duplicate id {case['id']}"
        ids.add(case["id"])
        src = SOURCES.get(case.get("source"))
        assert src is not None, f"{case['id']}: no source - a golden needs an EXTERNAL source"
        assert src["kind"] in _EXTERNAL_KINDS, f"{case['id']}: source kind {src['kind']!r} is not external"
        assert src["url"].startswith(_EXTERNAL_HOSTS), f"{case['id']}: source url is not an external reference"


def test_every_wiki_source_is_pinned_to_a_revision():
    for key, src in SOURCES.items():
        if src["kind"] == "wiki":
            assert "oldid=" in src["url"], f"{key}: wiki source must pin a revision (oldid=)"


def test_every_case_names_a_core_function():
    missing = sorted({c["fn"] for c in CASES if not callable(getattr(math_core, c["fn"], None))})
    assert missing == []


def test_rejected_cases_are_not_silently_reused():
    rejected = {r["id"] for r in DATA.get("rejected", [])}
    assert rejected.isdisjoint({c["id"] for c in CASES})
    for r in DATA.get("rejected", []):
        assert r.get("why"), f"{r['id']}: a rejected golden must say why"


# --------------------------------------------------------------------------
# 1. The pure core


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_core_matches_golden(case):
    actual = _call(case["fn"], case)
    assert _close(actual, case["expected"], case.get("tol", _DEFAULT_TOL)), (
        f"{case['id']}: got {actual!r}, external source says {case['expected']!r}"
    )


BOUNDARY = [c for c in CASES if c.get("boundary")]


def test_rounding_boundary_cases_are_listed():
    """The boundary list is its own test so a thinning of it is visible."""
    ids = {c["id"] for c in BOUNDARY}
    rounding = {c["id"] for c in BOUNDARY if c["fn"] in {"round_half_even", "js_math_round", "to_fixed", "hud_health"}}
    assert len(rounding) >= 10, sorted(rounding)
    # Each rounding mode has at least one exact-tie or binary-tie case.
    for fn in ("round_half_even", "js_math_round", "to_fixed"):
        assert any(c["fn"] == fn for c in BOUNDARY), fn
    assert {"py-round-0.5", "js-round-neg20.5", "js-fixed-2.55", "py-round-2.675", "spec-fixed-2.5"} <= ids
    # An exact binary tie per mode, or a ties-to-even / ties-up swap survives.
    assert any(c["fn"] == "to_fixed" and c["id"].startswith("spec-fixed") for c in BOUNDARY)


@pytest.mark.parametrize("case", BOUNDARY, ids=[c["id"] for c in BOUNDARY])
def test_rounding_boundary_case(case):
    actual = _call(case["fn"], case)
    assert _close(actual, case["expected"], case.get("tol", _DEFAULT_TOL))


def test_half_even_and_half_up_genuinely_diverge_on_the_goldens():
    """Python round() and JS toFixed/Math.round must differ on at least one golden
    tie - otherwise the boundary set is not exercising the divergence it exists for."""
    assert math_core.round_half_even(0.5, 0) != math_core.js_math_round(0.5)


# --------------------------------------------------------------------------
# 2. Duplicates of the same formula elsewhere in the tree


def _ds():
    from agents.daemon_slayer import _item_proc_heal, dps, ehp, effects, stats
    from agents.daemon_slayer._effects_types import ItemEffect

    return dps, ehp, _item_proc_heal, effects, stats, ItemEffect


def _mitigation_impls():
    dps, ehp, proc_heal, _effects, _stats, _ie = _ds()
    return {
        "dps._armor_factor": dps._armor_factor,
        "ehp._armor_factor": ehp._armor_factor,
        "_item_proc_heal._magic_mitigation_factor": proc_heal._magic_mitigation_factor,
        "math_core.damage_multiplier": math_core.damage_multiplier,
    }


MITIGATION = [c for c in CASES if c["fn"] in {"post_mitigation_damage", "effective_health"}]


@pytest.mark.parametrize("case", MITIGATION, ids=[c["id"] for c in MITIGATION])
def test_every_resist_curve_copy_matches_golden(case):
    for name, factor in _mitigation_impls().items():
        raw, resist = case["args"]
        actual = raw * factor(resist) if case["fn"] == "post_mitigation_damage" else raw / factor(resist)
        assert _close(actual, case["expected"], case.get("tol", _DEFAULT_TOL)), f"{name}: {case['id']} got {actual}"


def _growth_impls():
    from core import ds_burst_target, enemy_aware_stats

    _dps, _ehp, _ph, _eff, stats, _ie = _ds()
    return {
        "stats.growth_multiplier": stats.growth_multiplier,
        "ds_burst_target._growth": ds_burst_target._growth,
        "enemy_aware_stats._riot_growth_multiplier": enemy_aware_stats._riot_growth_multiplier,
        "math_core.growth_multiplier": math_core.growth_multiplier,
    }


GROWTH = [c for c in CASES if c["fn"] == "stat_at_level"]


@pytest.mark.parametrize("case", GROWTH, ids=[c["id"] for c in GROWTH])
def test_every_growth_curve_copy_matches_golden(case):
    base, growth, level = case["args"]
    for name, mult in _growth_impls().items():
        actual = base + growth * mult(level)
        assert _close(actual, case["expected"], case.get("tol", _DEFAULT_TOL)), f"{name}: {case['id']} got {actual}"


def _ds_pipeline_applicable(case: dict) -> bool:
    """The DS pipelines model TOTAL resist only (no base/bonus split, no
    bonus-only penetration), so only cases expressible in that shape apply."""
    if case["fn"] != "effective_resist":
        return False
    kw = case.get("kwargs", {})
    return case["args"][1] == 0 and not kw.get("bonus_pct_pens")


DS_PEN = [c for c in CASES if _ds_pipeline_applicable(c)]

# Golden disagreements in the DS engine, found by this file. Each is a real
# engine defect against the external source; it is pinned strict-xfail so the
# fix flips this test red until the entry is removed (Tier-2 engine change,
# carried in the hand-off - not fixed inside P1-5).
DS_KNOWN_DIVERGENCE = {
    # Wiki: once flat reduction takes the resist to zero or below, percent
    # reduction and all penetration are skipped. DS applies percent reduction
    # to the negative value (-2 * 0.7 = -1.4), shrinking the amplification.
    "mr-target-b",
}


def _armor_effect(ItemEffect, kw):
    keep = 1.0
    for p in kw.get("pct_reductions", []):
        keep *= 1.0 - p
    pkeep = 1.0
    for p in kw.get("pct_pens", []):
        pkeep *= 1.0 - p
    return ItemEffect(
        item_id="golden", name="golden",
        armor_reduction_flat=kw.get("flat_reduction", 0.0),
        armor_reduction_pct=1.0 - keep,
        armor_pen_pct=1.0 - pkeep,
        armor_pen_flat=kw.get("flat_pen", 0.0),
        mr_reduction_flat=kw.get("flat_reduction", 0.0),
        mr_reduction_pct=1.0 - keep,
        magic_pen_pct=1.0 - pkeep,
        magic_pen_flat=kw.get("flat_pen", 0.0),
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(c, marks=pytest.mark.xfail(strict=True, reason="DS engine diverges from the external source"))
        if c["id"] in DS_KNOWN_DIVERGENCE else c
        for c in DS_PEN
    ],
    ids=[c["id"] for c in DS_PEN],
)
def test_ds_penetration_pipelines_match_golden(case):
    _dps, _ehp, _ph, effects, _stats, ItemEffect = _ds()
    resist = case["args"][0]
    eff = _armor_effect(ItemEffect, case.get("kwargs", {}))
    tol = case.get("tol", _DEFAULT_TOL)
    got_armor = effects.effective_target_armor(resist, [eff])
    got_mr = effects.effective_target_mr(resist, [eff])
    assert _close(got_armor, case["expected"], tol), f"effective_target_armor {case['id']} got {got_armor}"
    assert _close(got_mr, case["expected"], tol), f"effective_target_mr {case['id']} got {got_mr}"


def test_ds_known_divergence_ids_are_real_cases():
    assert DS_KNOWN_DIVERGENCE <= {c["id"] for c in DS_PEN}


# --------------------------------------------------------------------------
# 3. The web side: the JS built-ins the dashboards round with


JS_CASES = [c for c in CASES if c.get("js")]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_js_builtins_match_the_same_golden_file():
    assert len(JS_CASES) >= 15
    exprs = ",".join(c["js"] for c in JS_CASES)
    script = (
        "const v=[" + exprs + "];"
        "process.stdout.write(JSON.stringify(v.map(x=>typeof x==='number'"
        "?{n:x,neg0:Object.is(x,-0)}:{s:x})));"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=60, creationflags=flags, check=True
    ).stdout
    got = json.loads(out)
    for case, val in zip(JS_CASES, got):
        if "s" in val:
            actual = val["s"]
        else:
            actual = -0.0 if val["neg0"] else val["n"]
        assert _close(actual, case["expected"], case.get("tol", _DEFAULT_TOL)), f"node {case['id']} got {actual!r}"
        # And the Python port of the same JS semantics agrees with node.
        assert _close(_call(case["fn"], case), actual, case.get("tol", _DEFAULT_TOL)), case["id"]


# --------------------------------------------------------------------------
# Freshness helper


def test_freshness_fresh_within_window():
    f = math_core.freshness(100.0, 8.0, now=105.0)
    assert f.fresh is True and f.age_s == 5.0 and f.reason == "fresh"


def test_freshness_stale_past_window():
    f = math_core.freshness(100.0, 8.0, now=108.5)
    assert f.fresh is False and f.reason == "stale"


def test_freshness_window_edge_is_inclusive():
    assert math_core.freshness(100.0, 8.0, now=108.0).fresh is True


@pytest.mark.parametrize("bad", [None, True, False, "100", float("nan"), float("inf"), 0, -5])
def test_freshness_unknown_timestamp_fails_closed(bad):
    f = math_core.freshness(bad, 8.0, now=105.0)
    assert f.fresh is False and f.reason == "unknown"


def test_freshness_future_beyond_skew_fails_closed():
    f = math_core.freshness(120.0, 8.0, now=100.0)
    assert f.fresh is False and f.reason == "future"


def test_freshness_small_future_jitter_reads_age_zero():
    f = math_core.freshness(102.0, 8.0, now=100.0)
    assert f.fresh is True and f.age_s == 0.0


def test_freshness_rejects_a_nonpositive_window():
    with pytest.raises(ValueError):
        math_core.freshness(100.0, 0, now=100.0)


def test_liveclient_snapshot_age_uses_the_shared_freshness_rules(monkeypatch):
    """The live-data read path (core/liveclient_cache.Snapshot) delegates its
    fail-closed age to the shared helper, so the two cannot drift."""
    from core import liveclient_cache as lc

    monkeypatch.setattr(lc.time, "time", lambda: 1000.0)
    assert lc.Snapshot(data={}, ts=995.0).age_s == 5.0
    assert lc.Snapshot(data={}, ts=995.0).is_fresh(8.0) is True
    assert lc.Snapshot(data={}, ts=900.0).is_fresh(8.0) is False
    assert lc.Snapshot(data={}, ts=None).age_s == lc._UNKNOWN_AGE_S
    assert lc.Snapshot(data={}, ts=2000.0).age_s == lc._UNKNOWN_AGE_S
    assert lc.Snapshot(data=None).is_fresh(8.0) is False
