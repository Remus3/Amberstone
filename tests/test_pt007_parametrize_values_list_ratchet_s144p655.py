"""S144-P-655 - ruff PT007 (``pytest.mark.parametrize`` values given as a tuple) is held at zero bar named files.

PT007 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 47 findings in 26 files, every one a ``parametrize`` whose values container was a tuple
where ruff's default wants a list (a list of tuples for several argnames). Eighteen findings in 11 test modules were
rewritten with the tuple's brackets swapped for list brackets; the ``ids=`` tuples were left alone (PT007 does not
look at them). The parameter sets are unchanged, so every test id and count stays as before.

Fifteen files stay named in ``_BASELINE`` with their counts, because another lane or a Playwright run owns them:

- ``tests/snapshot_panels/``: 11 browser-rendered modules (18 sites), not re-run from a lane.
- ``tests/test_ds_client_*_s144d2*.py``: four Daemon Slayer client modules (11 sites) belonging to the ds lane's slices.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only shrinks.
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

_RULES = ("PT007",)
# file -> finding count. The baseline only shrinks: a new finding fails, and an entry that stops offending (or
# offends less) fails test_baseline_is_exact.
_BASELINE = {
    "tests/snapshot_panels/test_champ_select_narrow_reflow.py": 3,
    "tests/snapshot_panels/test_history_row_hover_marks_contrast.py": 1,
    "tests/snapshot_panels/test_in_view_header_scope.py": 1,
    "tests/snapshot_panels/test_lobby_mains_top8_narrow_reflow.py": 1,
    "tests/snapshot_panels/test_lobby_narrow_reflow.py": 2,
    "tests/snapshot_panels/test_lobby_reflow_line_fit.py": 1,
    "tests/snapshot_panels/test_match_row_grade_chip_contrast.py": 1,
    "tests/snapshot_panels/test_match_row_time_right_align.py": 1,
    "tests/snapshot_panels/test_replay_narrow_reflow.py": 3,
    "tests/snapshot_panels/test_replay_pick_reveals_main.py": 3,
    "tests/snapshot_panels/test_theme_swap_reads_settled.py": 1,
    "tests/test_ds_client_malformed_rows_s144d26.py": 5,
    "tests/test_ds_client_null_strings_s144d28.py": 2,
    "tests/test_ds_client_onhit_tags_s144d27.py": 3,
    "tests/test_ds_client_post_json_non_object_s144d25.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_pt007_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULES} findings above the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends at its recorded count; one that shrank must be lowered or dropped."""
    stale = {rel: (n, tree_counts.get(rel, 0)) for rel, n in _BASELINE.items() if tree_counts.get(rel, 0) != n}
    assert not stale, f"baseline file: (recorded, measured): {stale}"


def test_converted_files_use_list_values():
    """The conversion is real, not a suppression: one converted site per spelling is a list now."""
    text = (REPO_ROOT / "tests/test_tft_league_side_effect_gate_s134.py").read_text(encoding="utf-8")
    assert '@pytest.mark.parametrize("qid", [1090, 1100, 1130])' in text
    text = (REPO_ROOT / "tests/test_coach_cross_module_cites_s144p54.py").read_text(encoding="utf-8")
    assert '@pytest.mark.parametrize(("rel", "cls", "name", "needle"), [' in text


def test_probe_is_live():
    """PT007 reports a tuple of values and stays quiet on a list."""
    bad = "import pytest\n\n\n@pytest.mark.parametrize('x', (1, 2))\ndef test_a(x):\n    assert x\n"
    good = bad.replace("(1, 2)", "[1, 2]")
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
