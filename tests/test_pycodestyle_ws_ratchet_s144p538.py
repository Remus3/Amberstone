"""S144-P-538 - ruff W391 / E228 / E262 / E271 (pycodestyle whitespace) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): nine findings tree-wide, none of them in the
ruff.toml selection, so nothing stopped a tenth. Three were fixed here (a spaced modulo in an f-string, an over-spaced
inline comment in a table, one in a size-threshold dict); the six that remain sit in files this lane may not edit
(``_BASELINE``, each row names why). The baseline only shrinks: ANY new finding, or one above a baselined file's count,
fails ``test_no_file_exceeds_its_baseline``, and a baselined file that stops offending fails
``test_the_baseline_only_shrinks`` until its row is dropped. The run uses NO config (``--isolated``) so a per-file-ignore
cannot hide a finding.
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

_RULES = "W391,E228,E262,E271"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each row is a file this lane does not own, not an exemption.
_BASELINE: dict[str, int] = {
    "ops/rc_supervisor.py": 1,                 # FROZEN (CLAUDE.md frozen list): a trailing blank line
    "tft/tft_coach_engine.py": 1,              # unscheduled (BACKLOG RM-381 holds this file this session)
    "tools/run_packaged_smoke.py": 1,          # PKG, main session owns
    "web_dashboard.py": 1,                     # another lane branch (lane/true-audit) changed it
    "agents/daemon_slayer/ability_dps.py": 1,  # another lane branch (lane/ds) changed it
    "coaches/replay_coach.py": 1,              # another lane branch (lane/true-audit) changed it
}
_FIXED = (
    "agents/agent2_backend/game_ingest.py",
    "agents/agent3_testing/suite/test_game_ingest.py",
    "scripts/db_size_monitor.py",
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
    """A positive control: each of the four rules fires on the pattern it exists for."""
    probe = (
        "x = 7\n"
        "y = x%2\n"                      # E228
        "z = 1  #two spaces then no gap\n"  # E262
        "if  x:\n"                       # E271
        "    pass\n"
        "\n"                             # W391 (trailing blank line)
    )
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == set(_RULES.split(","))


def test_the_table_comment_edits_changed_no_value():
    """The two comment edits sit inside literals the tree reads: the dict values must be untouched."""
    spec = importlib.util.spec_from_file_location("_s144p538_dbsize", REPO_ROOT / "scripts" / "db_size_monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DEFAULT_THRESHOLDS == {
        "rewind_history.db": 2 * 1024 ** 3,
        "logs": 500 * 1024 ** 2,
        "data/spend": 50 * 1024 ** 2,
    }
    ingest = importlib.util.spec_from_file_location(
        "_s144p538_ingest", REPO_ROOT / "agents" / "agent2_backend" / "game_ingest.py")
    mod = importlib.util.module_from_spec(ingest)
    try:
        ingest.loader.exec_module(mod)
    except ImportError:
        pytest.skip("game_ingest needs its package context")
    assert mod.GAME_MODE_TO_DB["CLASSIC"] == "sr_ranked"
    assert mod.GAME_MODE_TO_DB["RANKED_SOLO"] == "sr_ranked"
