"""S144-P-493 - no test takes an underscore-named fixture as a parameter (PT019), outside a shrinking baseline.

A fixture named ``_x`` says "I run for my side effect, I hand you no value". A test that lists ``_x`` in its
signature gets the same fixture as ``@pytest.mark.usefixtures("_x")`` would give it, but the signature then reads as
if the test used a value, and the two spellings drift. ruff's PT019 reports it; the repo's ruff.toml does not select
the rule, so nothing noticed.

Measured 2026-11-09 with ``ruff check --isolated --select PT019`` over every tracked ``.py``: 84 findings in 19
files. 27 were fixtures that really hand over nothing (``_no_side_effects``, ``_isolate_sentinel``,
``_restore_module`` ...); they became ``@pytest.mark.usefixtures`` in seven files (S144-P-493). What is left in
``_BASELINE`` (rel path -> count) is of two kinds, and neither is a safe mechanical edit:

- a fixture that DOES return a value its tests read (``seed, live = _paths``): the underscore is wrong, the fix is
  to rename the fixture and every use, which needs a per-file check that the new name collides with nothing;
- a ``mock.patch`` decorator argument spelled ``_`` in a ``unittest.TestCase`` (tests/test_archetype_dispatcher.py):
  ruff misreads it as a fixture, and ``usefixtures`` would be wrong there.
tests/test_p2w2_ds_h.py is a file another lane branch changed.

The ratchet runs ruff with NO config, so the repo's rule selection cannot hide a hit:

- a file outside ``_BASELINE`` has no PT019 finding;
- a ``_BASELINE`` file may not gain one, and an entry whose count dropped fails until it is lowered or dropped.

Fix a hit by ``usefixtures`` (a side-effect fixture) or by renaming the fixture (a value fixture); never an inline
``noqa``.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

# Only shrinks. Value-returning fixtures with an underscore name, plus one mock.patch "_" argument.
_BASELINE = {
    "tests/test_archetype_dispatcher.py": 7,  # mock.patch argument "_" in unittest.TestCase methods
    "tests/test_data_pipeline_lf_writes.py": 4,
    "tests/test_data_pipeline_rank_tiers.py": 6,
    "tests/test_health_all_obs_keep_warm_s144q49.py": 4,
    "tests/test_legacy_index_kept_route_rm726.py": 1,
    "tests/test_loop_control_400_no_echo_s144q57.py": 1,
    "tests/test_p2w2_ds_h.py": 2,  # lane/ds changed this file
    "tests/test_personal_build_wr_true_audit_s144t154.py": 6,
    "tests/test_precomputed_anvil_advisor.py": 7,
    "tests/test_rm484_offline_tools_rate_limit.py": 4,
    "tests/test_silent_except_tracker_heatmap_loglevel.py": 2,
    "tests/test_tft_coach_board_star_notation_s136.py": 1,
    "tests/test_tft_coach_prompt_sources_s136.py": 6,
    "tests/test_tft_league_side_effect_gate_s134.py": 2,
    "tests/test_tracked_writer_lf_bytes.py": 1,
    "tools/tests/test_upstream_drift_check.py": 3,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", "PT019", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _tracked_counts() -> Counter:
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: Counter = Counter()
    for d in _ruff([".", "--exclude", "data,logs,ops/runtime"]):
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            counts[rel] += 1
    return counts


def test_no_new_underscore_fixture_parameter_and_the_baseline_only_shrinks():
    counts = _tracked_counts()
    new = {f: n for f, n in counts.items() if f not in _BASELINE}
    assert not new, f"a test takes an underscore fixture as a parameter (use usefixtures): {sorted(new.items())}"
    grew = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] > cap}
    assert not grew, f"a baselined file gained a PT019 hit (found, cap): {grew}"
    healed = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] < cap}
    assert not healed, f"lower or drop these _BASELINE entries (found, cap): {healed}"


def test_the_probe_is_live():
    """The isolated run flags the shape (the repo config would hide it), so an empty tree result is a clean tree,
    not a dead probe."""
    code = "def test_a(_fix):\n    assert True\n"
    assert {d["code"] for d in _ruff(["--stdin-filename", "test_x.py", "-"], stdin=code)} == {"PT019"}


def test_the_safe_spellings_are_not_flagged():
    code = (
        "import pytest\n\n\n"
        '@pytest.mark.usefixtures("_fix")\n'
        "def test_a():\n    assert True\n\n\n"
        "def test_b(paths):\n    assert paths\n"
    )
    assert _ruff(["--stdin-filename", "test_x.py", "-"], stdin=code) == []


def test_ruff_toml_does_not_select_the_rule():
    """This ratchet exists because ruff.toml leaves PT019 off; if the rule is ever selected the ordinary lint
    covers it and this file should be retired, not left as a second copy."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    select_block = text.split("\nselect = [", 1)[1].split("\n]", 1)[0]
    assert '"PT' not in select_block and '"ALL"' not in select_block


def test_baseline_files_exist():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel
