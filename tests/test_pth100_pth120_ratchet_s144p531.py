"""S144-P-531 - ruff PTH100 / PTH120 (os.path.abspath / os.path.dirname) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 44 PTH100 and 36 PTH120 findings. Eight
modules spelled their repo root ``os.path.dirname(os.path.dirname(os.path.abspath(__file__)))``; they now spell
``str(Path(__file__).absolute().parents[1])``. ``Path.absolute()`` is the exact ``os.path.abspath`` counterpart (no
symlink or subst-drive resolution, unlike ``Path.resolve()``, which ruff's fix suggests and which would change the
string on a junctioned checkout), and the ``str()`` keeps every ``os.path.join`` consumer working on the same type.

The rest sits in ``_BASELINE`` (41 findings in 19 files): hand-written paths (``live_write_tracer``, the lane
launcher, the conftest helpers, the DS geometry tests) each need their own look, not a mechanical rewrite. The
baseline only shrinks: ANY new finding, or one above a baselined file's count, fails ``test_no_file_exceeds_its_baseline``.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding, and ``--preview`` because both
rules are preview-only in this ruff.
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

_RULES = "PTH100,PTH120"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings (both rules together). Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "agents/daemon_slayer/tests/test_effects_expansion.py": 1,
    "agents/daemon_slayer/tests/test_geometry_item232.py": 3,
    "core/hot_reload.py": 2,
    "core/vod_retention.py": 2,
    "dashboard/routes_recordings.py": 2,
    "dashboard/routes_vision_calibrator.py": 2,
    "ops/loop/lane_launcher.py": 2,
    "ops/loop/lanes.py": 2,
    "ops/migrate/e_move_helpers.py": 1,
    "tests/_basetemp_guard.py": 1,
    "tests/_crlf_text_layer.py": 1,
    "tests/conftest.py": 2,
    "tests/test_ds_antitank_hint.py": 1,
    "tests/test_guard_grading_rc_facts.py": 2,
    "tests/test_inbox_responder_runner.py": 3,
    "tests/test_repin_subagent_cli_rm795.py": 1,
    "tests/test_shadow_archive_split_rm859.py": 1,
    "tools/live_write_tracer.py": 11,
    "tools/stop_claim_gate.py": 1,
}
# The OLD spelling, kept as bare references (an oracle for the behaviour pins below, not a call site ruff reads).
_OLD_ABSPATH = os.path.abspath
_OLD_DIRNAME = os.path.dirname
_FIXED = (
    "tests/test_minimap_blob_detect_precision.py",
    "tests/test_vision_profile_2560_ocr_boxes.py",
    "tests/test_vision_profile_derive.py",
    "tests/test_vision_profile_seeds.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/logger_leak_census.py",
    "tools/p3_ascii_census.py",
    "tools/perseus_sync.py",
    # S144-P-532: the three-level spelling, str(Path(__file__).absolute().parents[2]).
    "ops/audit/ds_latency_probe.py",
    "ops/audit/opponent_prior_gonogo.py",
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
    """A positive control: both rules fire on the pattern they exist for."""
    probe = "import os\nroot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {"PTH100", "PTH120"}


def test_the_new_spelling_is_the_old_string():
    """Behaviour pin: absolute().parents[1] is the old dirname(dirname(abspath)) string, for this file and for a
    relative __file__ (the case where abspath and a resolve-based spelling would differ from a naive parent)."""
    here = str(Path(__file__).absolute().parents[1])
    assert here == _OLD_DIRNAME(_OLD_DIRNAME(_OLD_ABSPATH(__file__)))
    rel = os.path.join("tests", "x.py")
    assert str(Path(rel).absolute().parents[1]) == _OLD_DIRNAME(_OLD_DIRNAME(_OLD_ABSPATH(rel)))
    assert here == str(REPO_ROOT) or os.path.normcase(here) == os.path.normcase(str(REPO_ROOT.absolute()))


@pytest.mark.parametrize("rel,attr", [
    ("tools/p3_ascii_census.py", "ROOT"),
    ("tools/perseus_sync.py", "REPO"),
])
def test_converted_tool_roots_keep_the_old_value(rel, attr):
    spec = importlib.util.spec_from_file_location("_s144p531_" + attr, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = _OLD_DIRNAME(_OLD_DIRNAME(_OLD_ABSPATH(REPO_ROOT / rel)))
    assert getattr(module, attr) == old


def test_the_three_level_spelling_is_the_old_string():
    """S144-P-532: ops/audit/ reaches the repo root with parents[2]; same string as the old three-dirname form,
    for this file and for a relative path."""
    here = str(Path(__file__).absolute().parents[1] / "ops" / "audit" / "x.py")
    assert str(Path(here).absolute().parents[2]) == _OLD_DIRNAME(_OLD_DIRNAME(_OLD_DIRNAME(_OLD_ABSPATH(here))))
    rel = os.path.join("ops", "audit", "x.py")
    assert str(Path(rel).absolute().parents[2]) == _OLD_DIRNAME(_OLD_DIRNAME(_OLD_DIRNAME(_OLD_ABSPATH(rel))))


def test_the_audit_probe_root_is_the_repo_root():
    spec = importlib.util.spec_from_file_location("_s144p532_gonogo", REPO_ROOT / "ops/audit/opponent_prior_gonogo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert os.path.normcase(module._ROOT) == os.path.normcase(str(REPO_ROOT.absolute()))
    source = (REPO_ROOT / "ops/audit/ds_latency_probe.py").read_text(encoding="utf-8")
    assert "str(Path(__file__).absolute().parents[2])" in source
