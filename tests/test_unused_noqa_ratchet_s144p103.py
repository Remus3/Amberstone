"""RM-1403 - a `# noqa: BLE001` that suppresses nothing is dropped, and a ratchet holds it.

ruff's BLE001 (blind except) does not flag a handler that re-raises or logs with
``log.exception``. Measured 2026-11-04 with ``ruff check --extend-select RUF100``
over the tree: 45 `# noqa: BLE001` directives sat on handlers BLE001 never
flagged (they ended in ``raise ... from exc``, ``raise`` or ``log.exception``).
A stale suppression hides the day somebody edits that handler to swallow the
error: the marker still says "blind except is deliberate here" when nobody
decided that.

Ten modules were cleaned in RM-1403, fourteen more in RM-1404 and seven more in RM-1405 (FIXED). The rest are in the shrinking
_BASELINE (rel path -> why it is not in this slice). The ratchet:

- a FIXED module carries no unused noqa again;
- any other tracked .py with an unused noqa fails unless it is in _BASELINE;
- a _BASELINE entry that no longer offends fails until it is dropped.

Only unused-because-the-rule-did-not-fire directives count (`unused:` in
ruff's message); a `non-enabled:` directive (a rule the config ignores, kept
for a stricter lint run) is deliberate and out of scope.

RM-1974 (a), re-measured 2026-11-07 on one tree: ruff 0.15.16 read 5 unused
directives (the 3 _BASELINE files plus a `# noqa: B018` in two test modules);
ruff 0.17.2 and 0.17.3 read those 5 plus 30 `# noqa: BLE001` in 21 production
modules, every one on a handler that logs with ``exc_info=True``, which 0.17's
BLE001 no longer flags. The 30 directives (any rationale text kept as a plain
comment) and the 2 B018 ones (B018 never fires on a subscript) were dropped; 20
of the 21 production modules joined FIXED (dashboard/routes_last_match.py was
already in FIXED), so 22 FIXED lines were added counting the two B018 test
modules; the _BASELINE is unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files
from tests._ruff_version import MEASURED_RUFF, fail_if_the_landing_box_moved, ruff_minor

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

FIXED = (
    "agents/agent2_backend/file_ingest.py",
    "agents/agent2_backend/pipeline/orchestrator.py",
    "agents/agent7_context/warm_session.py",
    "core/aram_coach_shadow.py",
    "core/archetype_picks.py",
    "core/arena_coach_shadow.py",
    "core/build_order_precompute.py",
    "core/champ_select_shadow.py",
    "core/comp_coverage.py",
    "core/det_coach_shadow.py",
    "core/ds_coach_shadow.py",
    "core/focus_board_live.py",
    "core/hz_choice_shadow.py",
    "core/live_benchmark_band_shadow.py",
    "core/live_game_gate.py",
    "core/macro_response_shadow.py",
    "core/operator_notify.py",
    "core/precomputed_anvil_advisor.py",
    "core/precomputed_replay_narrative.py",
    "core/replay_narrative_shadow.py",
    "core/replay_seek.py",
    "dashboard/routes_archetype.py",
    "dashboard/routes_auto_accept.py",
    "dashboard/routes_ban_suggest.py",
    "dashboard/routes_coach_choice.py",
    "dashboard/routes_ds_shape.py",
    "dashboard/routes_item_wpa.py",
    "dashboard/routes_last_match.py",
    "dashboard/routes_ops_panels.py",
    "dashboard/routes_player_snapshot.py",
    "dashboard/routes_post_game_wpa.py",
    "dashboard/routes_recordings.py",
    "dashboard/routes_rune_wpa.py",
    "dashboard/routes_skill_wpa.py",
    "dashboard/routes_sr_draft.py",
    "dashboard/routes_summspell_wpa.py",
    "dashboard/routes_tft.py",
    "lib/game_data/fetch.py",
    "ops/loop/lane_launcher.py",
    "tests/snapshot_panels/test_settings_spend_gate_focus.py",
    "tests/snapshot_panels/test_settings_spend_gate_residue.py",
    "tests/test_build_order_precompute.py",
    "tests/test_decision_detector_lane8_cycle12.py",
    "tests/test_first_element_slice_test_code_ratchet_s144p167.py",
    "tests/test_sorted_first_min_test_code_ratchet_s144p168.py",
    "tft/tft_scouting.py",
    "tft/tft_state_reader.py",
    "tools/gated_lx11_minimap_check.py",
    "tools/hotkey_listener.py",
    "tools/live_write_tracer.py",
    "tools/precommit_gate.py",
    "tools/spec_watch.py",
    "vision_server/_inference.py",
)

# rel path -> why it may keep an unused noqa. Only shrinks.
_BASELINE = {
    "dashboard/routes_draft_score.py": "another lane branch changed it",
    "dashboard/routes_session_hygiene.py": "another lane branch changed it",
    "tools/upstream_drift_check.py": "another lane branch changed it",
}


def _unused_noqa_by_file() -> dict[str, list[int]]:
    """rel path -> row numbers of `noqa` directives whose rule never fired."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--extend-select", "RUF100",
         "--no-fix", "--no-cache", "--output-format", "json", "."],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    diagnostics = json.loads(proc.stdout)
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    out: dict[str, list[int]] = {}
    for d in diagnostics:
        if d["code"] != "RUF100" or "unused:" not in d["message"]:
            continue
        rel = Path(d["filename"]).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        if rel in tracked:
            out.setdefault(rel, []).append(d["location"]["row"])
    return out


@pytest.fixture(scope="module")
def found() -> dict[str, list[int]]:
    # RM-1657: which directive is "unused" is a fact about one ruff, not the tree.
    # The ASCII + LF half below needs no ruff and runs everywhere.
    minor = ruff_minor()
    if minor != MEASURED_RUFF:
        fail_if_the_landing_box_moved(minor)
        pytest.skip(f"ruff {minor} differs from the measured {MEASURED_RUFF} (RM-1657)")
    return _unused_noqa_by_file()


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_has_no_unused_noqa(found, rel):
    assert rel not in found, f"{rel} carries an unused noqa again at rows {found[rel]} (RM-1403)"


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_no_new_unused_noqa_outside_the_baseline(found):
    new = sorted(set(found) - set(_BASELINE))
    assert not new, f"unused `# noqa` in {new}: drop the directive (the handler re-raises or logs)"


def test_baseline_only_shrinks(found):
    healed = sorted(rel for rel in _BASELINE if rel not in found)
    assert not healed, f"no longer offend, drop from _BASELINE: {healed}"


def test_baseline_entries_are_tracked_files():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel


def test_the_probe_is_not_vacuous(found):
    # The baseline is non-empty by construction, so an empty result means the
    # ruff run or the tracked-file filter broke, not that the tree is clean.
    assert found, "ruff reported no unused noqa at all - the probe is broken"
