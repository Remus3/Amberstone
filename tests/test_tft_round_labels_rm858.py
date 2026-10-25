"""RM-858: the live analysis loop takes its god rounds from the resolved
set's round schedule (RM-855), not from Set 17 tables applied to every set.

RM-292 (b): this file also pinned the same fix in tft/tft_pbe_engine.py
`_build_prompt`; that engine was deleted with the unreachable PBE coach
subsystem (tests/test_rm292b_pbe_coach_retired.py), so its three tests went
with it. The state reader's schedule, which the live path reads, is pinned
by tests/test_tft_round_schedule_rm855.py.

Before RM-858:
  tft/tft_live_analysis.py `TftLiveAnalysis._GOD_ROUNDS` (pre-fix :403)
      hard-coded {(2,4),(3,4),(4,4)} and `_loop` (pre-fix :484) ran a vision
      cycle every 20 s on those rounds for every set.

After RM-858 the reader asks `tft/tft_state_reader.py` `round_schedule()`
(RM-855), which serves the Set 17 Realm of the Gods tables only for Set 17
with that mechanic and the neutral schedule for every other set.

The Set 17 test fails first on its ROUTING assertion (pre-fix the reader
never called `round_schedule`); its cycle assertions pin Set 17 behaviour
as unchanged. Each Set 18 / unknown-set test fails first on a vision cycle
the pre-fix reader produced from the Set 17 tables.

Every name used here, cited at the fix tree:
  tft/tft_live_analysis.py  `TftLiveAnalysis` :401, `_AUGMENT_ROUNDS` :415,
      `_CAROUSEL_EVENTS` :416, `_is_god_round` :490, `_loop` :500 and the
      attributes it reads (`_running`, `_force_flag`, `_last_round`,
      `_last_vision`, `_round_start_time`, `_scanned_planning`, `_ai_bar`,
      all set in `__init__` :417-426; `_coach_state` via
      `_is_carousel_or_spectate` :487), the god / augment branch :507, the
      module-level `time` import :10, and `_run_cycle` :525.
  tft/tft_state_reader.py  `round_schedule` :271.
  tft/tft_set.py  `ROOT` :38, `FALLBACK_SET` :42, `ENV_PIN` :43,
      `clear_live_set` :110, `resolve_set` :140.
  tft/tft_pbe_data.py  `PVE_ROUNDS` :64, `GOD_ROUNDS` :65.

Each test writes its own data/meta under tmp_path and points `tft_set.ROOT`
at it (the RM-855 test's fixture shape, tests/test_tft_round_schedule_rm855.py).
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path

import pytest

from tft import tft_live_analysis as tla
from tft import tft_pbe_data as pbe
from tft import tft_set
from tft import tft_state_reader

GOD_ROUNDS = sorted(pbe.GOD_ROUNDS)
PVE_ROUNDS = sorted(pbe.PVE_ROUNDS)
AUGMENT_ROUNDS = sorted(tla.TftLiveAnalysis._AUGMENT_ROUNDS)

# The one Realm of the Gods record in the tracked Set 17 meta
# (data/meta/tft_set17_meta.json `_patch_notes_17.1`).
_GODS_NOTES = {
    "carousel": "REMOVED - replaced by Realm of the Gods",
    "realm_of_gods": "Stage X-4 = God offering. Stage 4-7 = God Boon armory.",
}


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    """No noted live set and no env pin leaks between tests."""
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


@pytest.fixture
def calls(monkeypatch):
    """Wrap the real round_schedule and record every call."""
    seen: list = []
    real = tft_state_reader.round_schedule

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(tft_state_reader, "round_schedule", spy)
    return seen


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("ascii") + b"\n")


@pytest.fixture
def two_sets(tmp_path, monkeypatch):
    """A Set 17 skeleton meta with its Realm of the Gods record, a Set 18
    skeleton meta and a Set 18 CommunityDragon extract."""
    meta = tmp_path / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {
        "_set": 17, "_note": "SKELETON - UNVERIFIED",
        "all_traits": ["Anima", "Meeple"], "unit_costs": {"Jinx": 1},
        "comps": {}, "_patch_notes_17.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set18_meta.json", {
        "_set": 18, "_note": "SKELETON - UNVERIFIED", "comps": {},
    })
    _write(meta / "tft_set18_cdragon.json", {
        "_set": 18, "champions": ["Kobuko"], "all_traits": ["Fae"],
        "augments": [{"name": "Hard Bargain",
                      "desc": "Gain @Gold@ gold each carousel round."}],
    })
    monkeypatch.setattr(tft_set, "ROOT", tmp_path)
    return tmp_path


def _unknown_roots(tmp_path, monkeypatch):
    """Yield the two unknown-set shapes, with tft_set.ROOT pointed at each:
    an ingested Set 19 whose meta even records Realm of the Gods, and nothing
    ingested at all (the resolver falls back to FALLBACK_SET with no data)."""
    s19 = tmp_path / "s19"
    meta = s19 / "data" / "meta"
    _write(meta / "tft_set19_meta.json", {
        "_set": 19, "_note": "SKELETON - UNVERIFIED", "comps": {},
        "_patch_notes_19.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set19_cdragon.json", {"_set": 19, "champions": ["X"]})
    monkeypatch.setattr(tft_set, "ROOT", s19)
    assert tft_set.resolve_set() == 19
    yield "set19"
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(tft_set, "ROOT", empty)
    assert tft_set.resolve_set() == tft_set.FALLBACK_SET
    yield "nothing-ingested"


# -- tft/tft_live_analysis.py ------------------------------------------------

def _cycles_at(monkeypatch, sr) -> int:
    """Run ONE `_loop` tick at round sr with no force scan, no carousel state
    and no planning-window scan pending; return how many vision cycles ran."""
    la = object.__new__(tla.TftLiveAnalysis)  # skip __init__ (SDK client, vision reader)
    la._running = True
    la._force_flag = False
    la._last_round = sr
    la._last_vision = 0.0
    la._round_start_time = 0.0   # -> ra = 999: outside the 1.5-3.5 s planning window
    la._scanned_planning = False
    la._ai_bar = None
    la._coach_state = {}
    ran: list = []
    la._run_cycle = lambda: ran.append(sr)

    def _stop(_s):
        la._running = False

    monkeypatch.setattr(tla, "time", types.SimpleNamespace(time=time.time, sleep=_stop))
    la._loop()
    return len(ran)


def test_live_analysis_set17_god_rounds_unchanged_and_from_round_schedule(two_sets, monkeypatch, calls):
    monkeypatch.setenv(tft_set.ENV_PIN, "17")
    assert tft_set.resolve_set() == 17
    for sr in GOD_ROUNDS:
        assert _cycles_at(monkeypatch, sr) == 1, sr
    for sr in AUGMENT_ROUNDS:
        assert _cycles_at(monkeypatch, sr) == 1, sr
    for sr in PVE_ROUNDS + [(3, 1), (5, 1)]:
        assert _cycles_at(monkeypatch, sr) == 0, sr
    assert calls, "the live analysis never asked round_schedule() for god rounds"


def test_live_analysis_set18_runs_no_god_round_cycle(two_sets, monkeypatch):
    assert tft_set.resolve_set() == 18
    for sr in GOD_ROUNDS:
        assert _cycles_at(monkeypatch, sr) == 0, sr
    # _AUGMENT_ROUNDS stays for every set (RM-858 decision): a scan cadence,
    # not a label; Set 18's augment rounds are unverified (LT-01).
    for sr in AUGMENT_ROUNDS:
        assert _cycles_at(monkeypatch, sr) == 1, sr


def test_live_analysis_unknown_set_runs_no_god_round_cycle(tmp_path, monkeypatch):
    for shape in _unknown_roots(tmp_path, monkeypatch):
        for sr in GOD_ROUNDS:
            assert _cycles_at(monkeypatch, sr) == 0, (shape, sr)
