"""RM-1680 - six small ruff idiom rules are held at zero in the test code.

None of the rules is in ruff.toml's ``select``. Measured 2026-11-05 with
``ruff check --isolated --line-length 120`` (target py39): 27 findings in 24 test modules under
``tests/``, ``agents/daemon_slayer/tests/`` and ``tools/tests/``: 23 fixed in 20 modules, 2 kept on purpose
(``noqa``), 2 baselined.

- SIM114 (8 of 9): ``if`` / ``elif`` arms with one identical body, merged into one parenthesised ``or``
  condition (order preserved, so every short-circuit is unchanged).
- FURB110 (3 of 4): ``x if x else y`` became ``x or y``. For ``raise last if last else RuntimeError(..)``
  the truth test is on an exception instance, which is always truthy unless it defines ``__bool__``.
- FURB188 (3 of 5): a ``startswith`` / ``endswith`` guard plus a slice became ``removeprefix`` /
  ``removesuffix`` (py39 has both). The fixed operands are non-empty literals or a non-empty pattern.
- FURB171 (2): ``x in ("a",)`` became ``x == "a"``.
- PLC0207 (3): ``s.split(sep)[0]`` became ``s.split(sep, maxsplit=1)[0]`` (same first element).
- RUF046 (4): ``int(round(x))`` became ``round(x)`` (one-argument ``round`` already returns an int).

Two lines keep a pre-fix spelling ON PURPOSE as the premise of an older ratchet
(tests/test_ternary_or_ratchet_s144p143.py, tests/test_removeprefix_merged_branch_ratchet_s144p135.py)
and carry a reasoned ``noqa``. Two findings sat in files another owner holds (tests/conftest.py, the
launcher test) and were baselined below; RM-1746 later merged the tests/conftest.py branch, so only the
launcher row stays. Scope is the test directories only; production modules are left
to their owners. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = "SIM114,FURB110,FURB188,FURB171,PLC0207,RUF046"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {
    "tests/test_launcher_key_read_rm810.py": 1,  # FURB188; launcher test, PKG-owned
}
_FIXED = (
    "agents/daemon_slayer/tests/test_engine_concurrency_p1l15.py",
    "agents/daemon_slayer/tests/test_server_routes_p1l8.py",
    "tests/snapshot_panels/test_overlay_draft_elo_visible.py",
    "tests/test_api_key_single_lookup_env_apikey.py",
    "tests/test_batch_system_tools_rm826.py",
    "tests/test_ds_live_route_gate.py",
    "tests/test_fleet_test_guard_lane_driver_rm874.py",
    "tests/test_gated_lx09_mark_check.py",
    "tests/test_gated_y01_chain_report.py",
    "tests/test_item_proc_heal_symbol_cites_s144d33.py",
    "tests/test_overlay_default_layout_collision.py",
    "tests/test_player_gpi.py",
    "tests/test_r69_r74_symbol_cites_s144d33.py",
    "tests/test_repin_subagent_cli_rm795.py",
    "tests/test_rm876_structural_mount_spellings.py",
    "tests/test_routes_state_health_scrub.py",
    "tests/test_self_cast_log.py",
    "tests/test_sibling_sweep_prefilter_f2.py",
    "tests/test_timing_bounds_use_budget_u5.py",
    "tests/test_vision_monitor_cwd_s144q11.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", _RULES, *args],
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


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """Each rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = (
        "def f(n, a, b, v, p, s, x):\n"
        "    if a:\n"
        "        n.add(1)\n"
        "    elif b:\n"
        "        n.add(1)\n"
        "    w = v if v else 3\n"
        "    t = s[len(p):] if s.startswith(p) else s\n"
        "    u = x in ('k',)\n"
        "    h = 'a|b'.split('|')[0]\n"
        "    r = int(round(x))\n"
        "    return w, t, u, h, r\n"
    )
    good = (
        "def f(n, a, b, v, p, s, x):\n"
        "    if a or b:\n"
        "        n.add(1)\n"
        "    w = v or 3\n"
        "    t = s.removeprefix(p)\n"
        "    u = x == 'k'\n"
        "    h = 'a|b'.split('|', maxsplit=1)[0]\n"
        "    r = round(x)\n"
        "    return w, t, u, h, r\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert sorted(d["code"] for d in found) == sorted(_RULES.split(","))
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
