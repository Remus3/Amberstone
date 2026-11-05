"""RM-1403 - a `# noqa: BLE001` that suppresses nothing is dropped, and a ratchet holds it.

ruff's BLE001 (blind except) does not flag a handler that re-raises or logs with
``log.exception``. Measured 2026-11-04 with ``ruff check --extend-select RUF100``
over the tree: 45 `# noqa: BLE001` directives sat on handlers BLE001 never
flagged (they ended in ``raise ... from exc``, ``raise`` or ``log.exception``).
A stale suppression hides the day somebody edits that handler to swallow the
error: the marker still says "blind except is deliberate here" when nobody
decided that.

Ten modules are cleaned in this slice (FIXED). The rest are in the shrinking
_BASELINE (rel path -> why it is not in this slice). The ratchet:

- a FIXED module carries no unused noqa again;
- any other tracked .py with an unused noqa fails unless it is in _BASELINE;
- a _BASELINE entry that no longer offends fails until it is dropped.

Only unused-because-the-rule-did-not-fire directives count (`unused:` in
ruff's message); a `non-enabled:` directive (a rule the config ignores, kept
for a stricter lint run) is deliberate and out of scope.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

FIXED = (
    "core/archetype_picks.py",
    "core/build_order_precompute.py",
    "core/operator_notify.py",
    "core/replay_seek.py",
    "lib/game_data/fetch.py",
    "tft/tft_state_reader.py",
    "tools/hotkey_listener.py",
    "tools/live_write_tracer.py",
    "tools/precommit_gate.py",
    "tools/spec_watch.py",
)

# rel path -> why it may keep an unused noqa. Only shrinks.
_BASELINE = {
    "agents/agent2_backend/file_ingest.py": "later slice",
    "agents/agent2_backend/pipeline/orchestrator.py": "later slice",
    "agents/agent7_context/warm_session.py": "later slice",
    "dashboard/routes_archetype.py": "later slice",
    "dashboard/routes_auto_accept.py": "later slice",
    "dashboard/routes_ban_suggest.py": "later slice",
    "dashboard/routes_coach_choice.py": "later slice",
    "dashboard/routes_draft_score.py": "another lane branch changed it",
    "dashboard/routes_item_wpa.py": "later slice",
    "dashboard/routes_last_match.py": "later slice",
    "dashboard/routes_ops_panels.py": "later slice",
    "dashboard/routes_post_game_wpa.py": "later slice",
    "dashboard/routes_rune_wpa.py": "later slice",
    "dashboard/routes_session_hygiene.py": "another lane branch changed it",
    "dashboard/routes_skill_wpa.py": "later slice",
    "dashboard/routes_summspell_wpa.py": "later slice",
    "ops/loop/lane_launcher.py": "later slice",
    "tests/snapshot_panels/test_settings_spend_gate_focus.py": "later slice",
    "tests/snapshot_panels/test_settings_spend_gate_residue.py": "later slice",
    "tests/test_build_order_precompute.py": "later slice",
    "tests/test_decision_detector_lane8_cycle12.py": "later slice",
    "tools/gated_lx11_minimap_check.py": "later slice",
    "tools/upstream_drift_check.py": "another lane branch changed it",
    "vision_server/_inference.py": "later slice",
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
