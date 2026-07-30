"""Guard: the TFT roll constants must declare which SET they describe, and
their staleness must stay LOUD.

BACKGROUND (all MEASURED in-repo, none of it corrected from third-party data)
----------------------------------------------------------------------------
tft/tft_data.py opens with "Currently seeded for TFT Set 14", yet the TFT lane
loads data/meta/tft_set17_meta.json ("_set": 17) and tft_coach_engine.py reads
TIER_ODDS out of tft_data.py to tell the player their roll odds. So a Set 14
table is answering Set 17 questions.

The source of truth for tier odds and pool sizes is the IN-CLIENT display.
That is live-gated: a headless run cannot read it, and third-party aggregator
tables are not a substitute (two reviewed sources disagreed on the L7-L9
rows). So this slice does NOT correct the numbers. It makes the mismatch
impossible to miss and impossible to change silently.

These are CHARACTERIZATION assertions. They pin what is true today. When the
operator verifies the tables in client and corrects them, several of these
SHOULD go red - that is the point. Update them together with the fix and flip
CONSTANTS_SET_VERIFIED.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from tft import tft_roll_odds as ro

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_META = REPO_ROOT / "data" / "meta" / "tft_set17_meta.json"


def _lane_set() -> int:
    return int(json.loads(LIVE_META.read_text(encoding="utf-8"))["_set"])


def _constants_modules():
    """Every tft/*.py that defines a TIER_ODDS table, discovered off disk."""
    found = []
    for path in sorted((REPO_ROOT / "tft").glob("*.py")):
        if path.name == "__init__.py":
            continue
        if "TIER_ODDS = {" not in path.read_text(encoding="utf-8"):
            continue
        found.append(importlib.import_module(f"tft.{path.stem}"))
    return found


MODULES = _constants_modules()


def test_discovery_found_the_constants_modules():
    names = {m.__name__ for m in MODULES}
    assert names == {"tft.tft_data", "tft.tft_pbe_data"}, (
        "a new TFT constants module appeared (or one vanished); it must also "
        f"declare CONSTANTS_SET / CONSTANTS_SET_VERIFIED. Found: {sorted(names)}"
    )


@pytest.mark.parametrize("mod", MODULES, ids=lambda m: m.__name__)
def test_every_constants_module_declares_its_set(mod):
    assert isinstance(getattr(mod, "CONSTANTS_SET", None), int), (
        f"{mod.__name__} ships TIER_ODDS with no CONSTANTS_SET. Constants "
        "that do not say which set they are for cannot be detected as stale."
    )
    assert isinstance(getattr(mod, "CONSTANTS_SET_VERIFIED", None), bool)


@pytest.mark.parametrize("mod", MODULES, ids=lambda m: m.__name__)
def test_verified_implies_current_and_complete(mod):
    """The one hard gate: you may not mark a STALE table as verified.

    Green today (nothing is verified). It fires the moment someone flips
    CONSTANTS_SET_VERIFIED on a module whose declared set is not the lane's,
    or on one missing a table.
    """
    if not mod.CONSTANTS_SET_VERIFIED:
        return
    lane = _lane_set()
    assert mod.CONSTANTS_SET == lane, (
        f"{mod.__name__} claims in-client verification but declares set "
        f"{mod.CONSTANTS_SET} while the lane is on set {lane}"
    )
    assert ro.load_constants(mod).complete, (
        f"{mod.__name__} claims verification but is missing a table"
    )


@pytest.mark.parametrize("mod", MODULES, ids=lambda m: m.__name__)
def test_a_stale_module_is_never_silently_stale(mod):
    """Declared set != lane set must surface as a reported problem."""
    lane = _lane_set()
    problems = ro.constants_health()["problems"]
    if mod.CONSTANTS_SET == lane:
        return
    assert any(
        mod.__name__ in p and "STALE" in p for p in problems
    ), f"{mod.__name__} is stale (set {mod.CONSTANTS_SET} vs lane {lane}) but constants_health() did not say so"


# -- the measured discrepancy table, pinned ----------------------------------

def test_measured_lane_set_is_17():
    assert _lane_set() == 17


def test_measured_tft_data_declares_set_14_against_a_set_17_lane():
    from tft import tft_data

    assert tft_data.CONSTANTS_SET == 14
    assert _lane_set() == 17


def test_measured_neither_module_is_in_client_verified():
    """Live-gated. Flipping either of these requires an operator, in client."""
    for mod in MODULES:
        assert mod.CONSTANTS_SET_VERIFIED is False, (
            f"{mod.__name__} was marked verified - if that is real, update "
            "this expectation in the same commit"
        )


def test_measured_set14_and_set17_modules_ship_identical_tables():
    """Evidence the Set 17 module was COPIED, not re-derived.

    Two modules that declare different sets have byte-identical TIER_ODDS and
    POOL_SIZES. At least one of them is wrong; nothing in the repo can say
    which. This test breaks as soon as either is corrected.
    """
    from tft import tft_data, tft_pbe_data

    assert tft_data.CONSTANTS_SET != tft_pbe_data.CONSTANTS_SET
    assert tft_data.TIER_ODDS == tft_pbe_data.TIER_ODDS
    assert tft_data.POOL_SIZES == tft_pbe_data.POOL_SIZES


def test_measured_set17_module_cannot_answer_pool_questions():
    """tft_pbe_data.py has POOL_SIZES but no UNITS_PER_COST.

    So the Set 17 module cannot size a cost pool at all, and tft_roll_odds
    has to fall back to the Set 14 module's UNITS_PER_COST.
    """
    from tft import tft_pbe_data

    assert hasattr(tft_pbe_data, "POOL_SIZES")
    assert not hasattr(tft_pbe_data, "UNITS_PER_COST")
    assert ro.load_constants(tft_pbe_data).units_per_cost is None


def test_measured_patch_notes_contradict_the_l7_three_cost_odds():
    """The repo's OWN Set 17 patch notes disagree with its own tier table.

    data/meta/tft_set17_meta.json records the 17.1 change as
    "3-cost 16%->19% at lv7", i.e. Set 17 level-7 3-cost odds are 19 percent.
    TIER_ODDS[7][3] says 33 percent - a Set 14 number. This is the single
    most concrete piece of evidence that the tables are for the wrong set,
    and it needs no external source to see.
    """
    from tft import tft_data, tft_pbe_data

    meta = json.loads(LIVE_META.read_text(encoding="utf-8"))
    note = meta["_patch_notes_17.1"]["shop_lv7"]
    pcts = [int(x) for x in re.findall(r"(\d+)%", note)]
    assert pcts == [16, 19], f"patch note text moved: {note!r}"
    from_pct, to_pct = pcts

    for mod in (tft_data, tft_pbe_data):
        table_pct = round(mod.TIER_ODDS[7][3] * 100)
        assert table_pct == 33, f"{mod.__name__} L7 3-cost moved to {table_pct}"
        assert table_pct not in (from_pct, to_pct), (
            f"{mod.__name__} TIER_ODDS[7][3] = {table_pct}% but the Set 17 "
            f"patch notes say the value went {from_pct}% -> {to_pct}%. "
            "OPERATOR: verify L7 in client and correct the table."
        )


def test_constants_health_reports_every_known_problem():
    report = ro.constants_health()
    assert report["lane_set"] == 17
    assert set(report["modules"]) == {"tft.tft_data", "tft.tft_pbe_data"}
    blob = " | ".join(report["problems"])
    assert "STALE" in blob
    assert "not in-client verified" in blob
    assert "UNITS_PER_COST" in blob
    assert "IDENTICAL TIER_ODDS" in blob
    assert "IDENTICAL POOL_SIZES" in blob


def test_constants_health_accepts_an_explicit_lane_set():
    """Pure enough to reason about without touching disk state."""
    report = ro.constants_health(lane_set=14)
    assert report["lane_set"] == 14
    assert not any(
        "tft.tft_data" in p and "STALE" in p for p in report["problems"]
    )
    assert any("tft.tft_pbe_data" in p and "STALE" in p for p in report["problems"])
