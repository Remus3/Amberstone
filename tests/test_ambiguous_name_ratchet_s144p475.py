"""S144-P-475 - no tracked ``.py`` binds ``l`` / ``O`` / ``I`` as a name (E741), outside a shrinking baseline.

ruff.toml ignores E741 ("common in short math/callbacks") for the WHOLE tree. Measured 2026-11-08 with
``ruff check --isolated --select E741`` over every tracked ``.py``: 36 findings in 22 files, every one the letter
``l`` (a left coordinate in a ``l, t, r, b = box`` unpack, a comprehension variable for a line / lean / message, or a
response variable). ``l`` is the one letter indistinguishable from ``1`` and ``I`` in many fonts, and in a
``l, t, r, b`` unpack the single letters are exactly why a swapped pair goes unseen. The 8 production files below
became ``left`` / ``top`` / ``right`` / ``bottom`` (or ``ln`` / ``lean`` / ``msg`` / ``lcu``): agents/_minimap_bbox.py,
coaches/_base_coach.py, core/aram_comp_verdict.py, core/vision_profiles.py, core/vision_tesseract.py,
tools/bootstrap_env_check.py, tools/match_monitor.py, tools/screen_agent.py. What is left is held in ``_BASELINE``
(rel path -> count), which only shrinks; it is empty since the s159 landing (the true-audit lane's
coaches/replay_coach.py, held there while it sat on another lane branch, binds none). The DS test file
agents/daemon_slayer/tests/test_engine_concurrency_p1l15.py (8 hits, the lambda default ``l=lvl``) became ``lv`` in
S144-P-491.
The 11 test files that held 13 hits became ``left`` / ``ln`` in S144-P-485 (tests/fu01_minimap/
test_http_override.py, test_aram_coach_shadow_choices_native_emit, test_lcu_cmd_payload_schema_rm296a,
test_minimap_geometry, test_replay_narrative_shadow, test_tft_cv_ocr_fields, test_vision_anchor_model_rm26,
test_vision_profile_2560_ocr_boxes, test_vision_profile_derive, test_vision_profile_seeds,
test_vision_tesseract_halved_frame_r98).

The ratchet runs ruff with NO config, so the waiver cannot hide a hit, over the tracked files only:

- a file outside ``_BASELINE`` binds no ambiguous name;
- a ``_BASELINE`` file may not gain one, and an entry whose count dropped fails until it is lowered or dropped.

Fix a hit by renaming; never an inline ``noqa``.
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

# Empty since the s159 landing: the true-audit lane's coaches/replay_coach.py binds no ambiguous name, so its
# row was dropped. Only shrinks; a new finding anywhere fails.
_BASELINE: dict[str, int] = {}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", "E741", *args],
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


def test_no_new_ambiguous_name_and_the_baseline_only_shrinks():
    counts = _tracked_counts()
    new = {f: n for f, n in counts.items() if f not in _BASELINE}
    assert not new, f"an ambiguous name is bound (rename it): {sorted(new.items())}"
    grew = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] > cap}
    assert not grew, f"a baselined file gained an ambiguous name (found, cap): {grew}"
    healed = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] < cap}
    assert not healed, f"lower or drop these _BASELINE entries (found, cap): {healed}"


@pytest.mark.parametrize(
    "code",
    [
        "l = 1\n",
        "def g(box):\n    l, t, r, b = box\n    return l\n",
        "x = [l for l in 'ab']\n",
        "O = 0\n",
    ],
)
def test_the_probe_is_live(code):
    """The isolated run flags each shape (the repo config would hide it), so an empty tree result is a clean tree,
    not a dead probe."""
    assert {d["code"] for d in _ruff(["--stdin-filename", "x.py", "-"], stdin=code)} == {"E741"}


def test_the_safe_spellings_are_not_flagged():
    code = "left, top, right, bottom = (1, 2, 3, 4)\nlines = [ln for ln in 'ab']\nlean = 1\n"
    assert _ruff(["--stdin-filename", "x.py", "-"], stdin=code) == []


def test_ruff_toml_still_waives_the_rule():
    """The ratchet exists because ruff.toml waives E741; if the waiver is lifted the ordinary lint covers it and
    this file should be retired, not left as a second copy."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    ignore_block = text.split("\nignore = [", 1)[1].split("\n]", 1)[0]
    assert '"E741"' in ignore_block


def test_baseline_files_exist():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel
