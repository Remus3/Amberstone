"""S144-P-547 - ruff PTH118 (os.path.join) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 54 findings in 26 files outside the vendored kit
(``ops/fleet_kit/``, fenced). Thirteen sites in ten files were converted to ``Path`` joins (three vision-profile tests, the minimap-corpus test, the hook-log
test, the boots-catalog test, the recordings test, ``tools/freeze_witness.py``, ``tools/p3_ascii_census.py`` and
``tools/ds_cc_conditional_to_json.py``); they are pinned clean in ``_FIXED``. Where a value is printed or handed on as a
string, the ``Path`` join is wrapped in ``str()`` so the consumer sees the same type.

The rest stays in ``_BASELINE`` (41 findings in 16 files), each for a stated reason:

- ``ops/rc_supervisor.py`` is frozen (ASKS 24); ``tests/test_pth100_pth120_ratchet_s144p531.py`` holds the old spelling as
  an oracle; ``tools/precommit_gate.py`` and ``tools/live_write_tracer.py`` are the commit gate and the write tracer, which
  keep a hand-written path each (the gate feeds ``compile()`` a filename).
- The rest (``tools/perseus_sync.py``, ``tools/perseus_recall.py``, ``tools/logger_leak_census.py``,
  ``tests/test_inbox_responder_runner.py``, the ops/audit and ops/migrate one-shots, ``core/hot_reload.py``,
  ``dashboard/routes_vision_calibrator.py``, two tests) are unconverted sites awaiting a per-site look.

The baseline only shrinks: ANY new finding, or one above a baselined file's count, fails
``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a
finding, and ``--preview`` because the PTH family differs under it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PTH118"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "agents/daemon_slayer/tests/test_geometry_item232.py": 1,
    "core/hot_reload.py": 1,
    "dashboard/routes_vision_calibrator.py": 1,
    "ops/audit/opponent_prior_gonogo.py": 2,
    "ops/audit/p2w5_partition.py": 1,
    "ops/audit/p2w5h2_partition.py": 1,
    "ops/migrate/e_move_helpers.py": 1,
    "ops/rc_supervisor.py": 2,  # FROZEN (ASKS 24)
    "tests/test_inbox_responder_runner.py": 12,
    "tests/test_no_process_wide_stdlib_fakes_rm801.py": 1,
    "tests/test_pth100_pth120_ratchet_s144p531.py": 5,  # holds the old spelling as an oracle
    "tools/live_write_tracer.py": 1,
    "tools/logger_leak_census.py": 3,
    "tools/perseus_recall.py": 2,
    "tools/perseus_sync.py": 6,
    "tools/precommit_gate.py": 1,
}
_FIXED = (
    "tests/test_build_order_boots.py",
    "tests/test_hook_invocation_log.py",
    "tests/test_minimap_blob_detect_precision.py",
    "tests/test_routes_recordings_hardening_s144.py",
    "tests/test_vision_profile_2560_ocr_boxes.py",
    "tests/test_vision_profile_derive.py",
    "tests/test_vision_profile_seeds.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/freeze_witness.py",
    "tools/p3_ascii_census.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: the rule fires on the pattern the baseline exists for."""
    probe = "import os\nos.path.join('a', 'b')\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["PTH118"]


@pytest.mark.parametrize("parts", [
    ("data", "vision_profiles"),
    ("data", "daemon_slayer", "16.12.1", "items.json"),
    ("agents", "daemon_slayer", "cc_conditional_registry.json"),
    ("private", "x.mp4"),
    ("x.json",),
])
def test_a_path_join_of_plain_components_matches_os_path_join(parts):
    """Every converted site joins a root with plain relative components (no absolute component, no embedded
    separator), where ``Path`` and ``os.path.join`` agree on this platform."""
    root = str(Path(__file__).absolute().parents[1])
    assert str(Path(root).joinpath(*parts)) == os.path.join(root, *parts)  # noqa: PTH118 - the old spelling is the control
    assert str(Path(*parts)) == os.path.join(*parts)  # noqa: PTH118 - the old spelling is the control


def test_path_join_diverges_from_os_path_join_on_an_absolute_component_and_a_forward_slash():
    """Why a mechanical rewrite is not free: ``Path`` normalises ``/`` to the native separator on Windows, and both
    drop the left side for an absolute right-hand component only on the platform's own rules. The converted sites avoid
    both inputs; a site that could see them stays baselined."""
    if os.sep == "\\":
        assert str(Path("a", "b/c")) == "a\\b\\c"
        assert os.path.join("a", "b/c") == "a\\b/c"  # noqa: PTH118 - the old spelling is the control
    else:
        assert str(Path("a", "b/c")) == os.path.join("a", "b/c")  # noqa: PTH118 - the old spelling is the control


def test_minimap_refdirs_adds_the_primary_checkout_only_inside_a_worktree(monkeypatch, tmp_path):
    """The converted ``_refdirs`` finds the primary checkout by the ``.claude/worktrees`` path segments, as the
    old ``os.sep`` string split did."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL.Image")
    import tests.test_minimap_blob_detect_precision as mod

    rel = Path("data") / "vision_calib_reference"
    wt = tmp_path / "primary" / ".claude" / "worktrees" / "lane" / "tests" / "x.py"
    monkeypatch.setattr(mod, "__file__", str(wt))
    assert mod._refdirs() == [wt.parents[1] / rel, tmp_path / "primary" / rel]

    plain = tmp_path / "plain" / "tests" / "x.py"
    monkeypatch.setattr(mod, "__file__", str(plain))
    assert mod._refdirs() == [plain.parents[1] / rel]

    lookalike = tmp_path / "x.claude" / "worktrees" / "lane" / "tests" / "x.py"
    monkeypatch.setattr(mod, "__file__", str(lookalike))
    assert mod._refdirs() == [lookalike.parents[1] / rel]
