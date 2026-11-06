"""RM-1681 - ruff C420 (a dict comprehension that is ``dict.fromkeys``) is held at zero in the test code.

C420 is not selected by ruff.toml. tests/test_dict_fromkeys_ratchet_s144p137.py holds PRODUCTION code at a
baseline and declares the test directories out of scope; this ratchet is the test-code half. Measured
2026-11-05 with ``ruff check --isolated --line-length 120`` (target py39): 39 findings in 24 modules under
``tests/``, ``agents/daemon_slayer/tests/`` and ``tools/tests/``. 37 findings in 23 modules were fixed to
``dict.fromkeys(iterable, value)``; the 2 in the p137 ratchet keep the comprehension on purpose (it is the
premise of ``test_fromkeys_equals_the_comprehension``) and carry a reasoned ``noqa``.

Equivalence: ruff flags only a comprehension whose value does not depend on the loop variable and is a
constant or a name. A name-bound value is the same single object under both spellings, so the dict contents,
key order and duplicate-key handling are identical; only a CALL value (``[]``) would differ, and ruff does not
flag that form. No baseline: every finding is fixed or carries a noqa. The run uses NO config (``--isolated``)
so a per-file-ignore cannot hide a finding.
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

_RULES = ("C420",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
_FIXED = (
    "agents/daemon_slayer/tests/test_assumed_share_exposure.py",
    "agents/daemon_slayer/tests/test_per_item_shield_route_seams_rm118.py",
    "tests/test_comp_coverage.py",
    "tests/test_ds_wiki_stats_mode_floor_s134d03.py",
    "tests/test_event_patterns.py",
    "tests/test_gated_ds_flag_eyeball.py",
    "tests/test_gated_lx01_draft_check.py",
    "tests/test_gated_tft_live_keys.py",
    "tests/test_live_benchmark_band_report.py",
    "tests/test_liveclient_championstats_ingestion.py",
    "tests/test_lobby_mains_averaged.py",
    "tests/test_loop_executor_git_paths_rm861.py",
    "tests/test_match_db_backfill.py",
    "tests/test_postmortem_analyze.py",
    "tests/test_prod_artifact_guard_writer_rm148.py",
    "tests/test_riot_api_negative_cache_rm163.py",
    "tests/test_rm175_aram_table_known_wrong.py",
    "tests/test_root_walkers_prune.py",
    "tests/test_routes_loadout_lane8_cycle38.py",
    "tests/test_routes_player_snapshot_hardening.py",
    "tests/test_tft_rounds_store.py",
    "tools/tests/test_upstream_drift_check.py",
    "tools/tests/test_wiki_stats_extract.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_c420_finding_in_the_test_code(tree_counts):
    assert not tree_counts, f"ruff {_RULES} findings in the test code, file: count: {tree_counts}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_uses_dict_fromkeys(rel):
    assert "dict.fromkeys(" in (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "def f(keys):\n    return {k: 0 for k in keys}\n"
    good = "def f(keys):\n    return dict.fromkeys(keys, 0)\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []


def test_a_name_bound_value_is_one_shared_object_either_way():
    """The equivalence premise: a comprehension over a name also shares one object, so the swap changes nothing."""
    shared = []
    comp = {k: shared for k in ("a", "b")}  # noqa: C420 - the comprehension is the premise
    assert comp == dict.fromkeys(("a", "b"), shared)
    assert comp["a"] is comp["b"] is dict.fromkeys(("a", "b"), shared)["a"]
    assert list(dict.fromkeys(("b", "a", "b"), 1)) == list({k: 1 for k in ("b", "a", "b")})  # noqa: C420 - premise
