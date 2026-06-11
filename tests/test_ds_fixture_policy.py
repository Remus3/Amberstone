"""Guard: DS golden-fixture snapshot policy (deep-audit P2b, gemini ruling B).

data/daemon_slayer/ keeps exactly TWO permanent frozen fixture dirs that
pinned tests may load from disk:

    16.10.1  (champion_abilities / items_meraki / arena_augments pins +
              DataSnapshot.load(patch="16.10.1") snapshot tests)
    16.11.1  (cdragon_spell_stats / passive-override / wiki_stats pins)

Policy (ruled 2026-06-11, ops/loop/control/_gemini_out_p2b_fixtures.txt):
- NEW test pins must target 16.11.1 (the newest frozen fixture). Never
  mint a new permanent snapshot dir for a test pin.
- 16.9.1 was retired the same cycle (its single consumer repointed to
  16.10.1 after an empty purchasable-item-set delta check); it must not
  come back.
- The live patch dir (data/daemon_slayer/current.txt) is NOT a fixture -
  it moves on every patch refresh and unpinned DataSnapshot.load() calls
  resolve it. There is no automated pruner for data/daemon_slayer patch
  dirs; this guard is the retention contract.
"""
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "daemon_slayer"

FROZEN_FIXTURES = ("16.10.1", "16.11.1")
RETIRED_FIXTURES = ("16.9.1",)


def test_frozen_fixture_dirs_present():
    missing = [p for p in FROZEN_FIXTURES if not (_DATA / p).is_dir()]
    assert not missing, (
        f"frozen DS fixture dir(s) missing: {missing} - pinned suites "
        "load these from disk; restore from a peer checkout or re-extract"
    )


def test_retired_fixture_dirs_stay_gone():
    revived = [p for p in RETIRED_FIXTURES if (_DATA / p).exists()]
    assert not revived, (
        f"retired DS fixture dir(s) reappeared: {revived} - 16.9.1 was "
        "retired by the P2b ruling (new pins target 16.11.1); delete it"
    )
