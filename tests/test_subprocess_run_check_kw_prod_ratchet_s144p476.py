"""PLW1510 - every production ``subprocess.run`` states ``check=`` (S144-P-476).

ruff.toml does not select PLW1510 and no earlier ratchet covers it (cycles 289 / 340 / 341 / 443
measured it and left it unscanned). A ``subprocess.run`` without ``check=`` leaves the reader to
guess whether a non-zero exit was meant to be ignored or was forgotten. ``check=False`` is the
Python default, so the bytes run and the behaviour are identical; the keyword only records the
intent. Measured 2026-11-08 with ``ruff check --isolated`` (target py39) over the tracked
production tree: 78 findings in 50 files. Slice 1 states ``check=False`` at the 20 sites in
eight modules whose code reads ``returncode`` (or deliberately ignores it) itself; slice 2
(S144-P-477) does the same for eleven more tools/ modules; the rest sit in the baseline below,
which only shrinks. Held back on purpose: ``tools/credential_history_scan.py`` and
``tools/sibling_name_sweep.py`` (another lane branch changed them), the packaging files, and the
gated one-shot probes not yet audited. A baseline row that stops offending fails
``test_baseline_is_exact`` until it is dropped; a new finding anywhere else fails
``test_no_new_findings``.

Baseline rows that are not converted on purpose: ``ops/rc_supervisor.py`` and ``ops/rc_dev_runtime.py``
are frozen files, and ``tools/build_portable.py`` / ``tools/run_packaged_smoke.py`` are the main
session's packaging files, so this slice never edits them.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the
vendored ``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
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

_RULE = "PLW1510"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "coaches/voice_coach.py": 1,
    "core/daemon_slayer_client.py": 1,
    "core/data_retention.py": 1,
    "core/operator_notify.py": 1,
    "dashboard/routes_loop_status.py": 1,
    "game_reader/poller.py": 1,
    "ops/audit/p0_inventory.py": 1,
    "ops/loop/claude_stub.py": 1,
    "ops/loop/done_sentinel.py": 1,
    "ops/loop/drain_waves_2_3.py": 1,
    "ops/loop/executor.py": 4,
    "ops/loop/interrupt.py": 1,
    "ops/loop/lane_launcher.py": 2,
    "ops/loop/loop_controller.py": 2,
    "ops/loop/queue_loop.py": 3,
    "ops/loop/repo_review.py": 2,
    "ops/rc_dev_runtime.py": 1,
    "ops/rc_supervisor.py": 3,
    "scripts/audit_api_surface.py": 1,
    "scripts/install_hooks.py": 1,
    "tools/build_installer.py": 1,
    "tools/build_portable.py": 1,
    "tools/credential_history_scan.py": 1,
    "tools/gated_b29_window_parity.py": 1,
    "tools/gated_lx11_minimap_check.py": 1,
    "tools/p3_ascii_census.py": 1,
    "tools/package_portable.py": 1,
    "tools/run_packaged_smoke.py": 6,
    "tools/scheduled_boot_verify.py": 1,
    "tools/sibling_name_sweep.py": 2,
    "tools/sibling_sweep_ci.py": 1,
}
_FIXED = (
    "dashboard/_vision_watchdog.py",
    "tools/bootstrap_env_check.py",
    "tools/bot_merge_check.py",
    "tools/build_rank_baselines.py",
    "tools/ci_impact_selector.py",
    "tools/ci_watchdog.py",
    "tools/claude_quota_watch.py",
    "tools/dev_cli.py",
    "tools/drift_guard.py",
    "tools/gen_archmap.py",
    "tools/inbox_responder_procs.py",
    "tools/perseus_sync.py",
    "tools/precommit_gate.py",
    "tools/rc_facts.py",
    "tools/replay_chain_watch.py",
    "tools/repo_insights.py",
    "tools/timeline_ingest.py",
    "tools/truth_gate.py",
    "tools/upstream_drift_check.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin,
        check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "import subprocess\nsubprocess.run(['x'])\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
    ok = "import subprocess\nsubprocess.run(['x'], check=False)\n"
    assert not _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=ok)
