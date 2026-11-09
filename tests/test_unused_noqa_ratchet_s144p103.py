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

RM-2035 (2026-11-07): the three _BASELINE rows ("another lane branch changed
it") were stale once the lanes landed; ruff 0.17.3 still read one unused
`# noqa: BLE001` in each (dashboard/routes_draft_score.py,
dashboard/routes_session_hygiene.py, tools/upstream_drift_check.py, all on a
handler that calls log.exception). The directives were dropped (rationale kept
as a plain comment), the three modules joined FIXED and _BASELINE is empty, so
the anti-vacuity check now plants an unused directive on stdin instead of
relying on a non-empty baseline.
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
    "dashboard/routes_draft_score.py",
    "dashboard/routes_ds_shape.py",
    "dashboard/routes_item_wpa.py",
    "dashboard/routes_last_match.py",
    "dashboard/routes_ops_panels.py",
    "dashboard/routes_player_snapshot.py",
    "dashboard/routes_post_game_wpa.py",
    "dashboard/routes_recordings.py",
    "dashboard/routes_rune_wpa.py",
    "dashboard/routes_session_hygiene.py",
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
    "tools/upstream_drift_check.py",
    "vision_server/_inference.py",
)

# rel path -> why it may keep an unused noqa. Only shrinks; empty since RM-2035.
_BASELINE: dict[str, str] = {}

# RM-2035: the positive control a run over the tree can no longer give once the
# baseline is empty. The same handler shape as the dropped directives (a BLE001
# suppression on a handler that re-raises), fed to the same ruff command on
# stdin under a tracked-looking path, so the tree is never written. The marker
# word is spliced in so ruff does not read this file's own line as a directive.
_PROBE_REL = "dashboard/_rm2035_unused_noqa_probe.py"
_NOQA = "noqa"
_PROBE_SRC = (
    "def f():\n"
    "    try:\n"
    "        return 1\n"
    f"    except Exception:  # {_NOQA}: BLE001\n"
    "        raise\n"
)


def _ruff_diagnostics(*target: str, stdin: str | None = None) -> list[dict]:
    """ruff's JSON diagnostics with RUF100 on, run from the repo root."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--extend-select", "RUF100",
         "--no-fix", "--no-cache", "--output-format", "json", *target],
        cwd=REPO_ROOT, input=stdin, capture_output=True, text=True, timeout=300,
        check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _unused_rows(diagnostics: list[dict], tracked: set[str]) -> dict[str, list[int]]:
    """rel path -> row numbers of `noqa` directives whose rule never fired."""
    out: dict[str, list[int]] = {}
    for d in diagnostics:
        if d["code"] != "RUF100" or "unused:" not in d["message"]:
            continue
        rel = Path(d["filename"]).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        if rel in tracked:
            out.setdefault(rel, []).append(d["location"]["row"])
    return out


def _unused_noqa_by_file() -> dict[str, list[int]]:
    """rel path -> row numbers of `noqa` directives whose rule never fired."""
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    return _unused_rows(_ruff_diagnostics("."), tracked)


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
    # RM-2035: the baseline is empty, so a clean tree reads `found == {}` and a
    # broken ruff run or path filter would read the same. The same command and
    # filter must still find a planted unused directive at its own row.
    diagnostics = _ruff_diagnostics("--stdin-filename", _PROBE_REL, "-", stdin=_PROBE_SRC)
    assert _unused_rows(diagnostics, {_PROBE_REL}) == {_PROBE_REL: [4]}, diagnostics
    # ...and the tracked-file filter must still know the FIXED modules.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert set(FIXED) <= tracked, sorted(set(FIXED) - tracked)
