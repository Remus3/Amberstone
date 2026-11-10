"""S144-P-271 - ruff RUF005 (``a + [x]`` / ``a + (x,)`` where ``[*a, x]`` / ``(*a, x)`` does) held at zero in ``core/`` and ``tools/``.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 331 findings tree-wide, 16 of them under ``core/``
in 11 modules. RUF005 is not in ``ruff.toml``. The fix is a pure spelling change for the shapes found here: the
operands were already a list / tuple of the same kind, and unpacking is the more tolerant of the two (``+`` raises on a
tuple + list mix, unpacking does not), so a call that worked still returns an equal value of the same type.

S144-P-271 held ``core/``; S144-P-272 added ``tools/`` (26 more findings in 16 modules, one under tools/tests/). ``_SCOPE``
grows one directory per later slice (dashboard/, ops/ ... then tests/); S144-P-504 added ``tft/`` (5 findings) and ``scripts/`` (4 findings), listed in ``_FIXED_P504``. S144-P-647 added ``dashboard/``, ``lcu/``, ``vision_server/``,
``ops/audit/`` and the one ``ops/loop/`` module without a sibling lane's edit (6 findings in 5 modules, ``_FIXED_P647``); the rest of
``ops/loop/``, ``ops/launcher/`` (PKG-owned) and ``agents/`` (Daemon Slayer plus a supervisor another lane edits) still carry findings
and join when their owners release them. Nothing under a scoped prefix may have a finding and there is no baseline. The run uses NO config
(``--isolated``), so a per-file-ignore cannot hide a finding.
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

# Directories held at zero RUF005 findings. A new entry means that whole directory was swept first.
_SCOPE = (
    "core/", "tools/", "tft/", "scripts/",
    "dashboard/", "lcu/", "vision_server/", "ops/audit/", "ops/loop/lane_run_ledger.py",
)
_FIXED = (
    "core/build_order_precompute.py",
    "core/build_order_variants.py",
    "core/build_planner/planner.py",
    "core/focus_board_live.py",
    "core/hud_settings.py",
    "core/laning_scenario_precompute.py",
    "core/log_scrub.py",
    "core/opening_tendency.py",
    "core/prom_metrics.py",
    "core/riot_api_cache.py",
    "core/vod_retention.py",
    "tools/aram_shadow_report.py",
    "tools/build_third_party_notices.py",
    "tools/champion_loadout_cleanup_pollution_item213.py",
    "tools/champion_loadout_sweep_item_s8.py",
    "tools/ci_impact_selector.py",
    "tools/dev_cli.py",
    "tools/gated_g240_ratio_spot.py",
    "tools/gated_g312_aram_debounce_lag.py",
    "tools/gated_g506_debounce_lag.py",
    "tools/gated_rm881_duo_lobby.py",
    "tools/inbox_responder_runner.py",
    "tools/inbox_responder_spawn.py",
    "tools/outbound_reciprocity_check.py",
    "tools/rc_facts.py",
    "tools/repo_insights.py",
    "tools/tests/test_roster_decap_a26.py",
)
_FIXED_P504 = (
    "scripts/repair_match_db_column_types.py",
    "scripts/repair_tft_match_rows.py",
    "scripts/tft_patch_delta.py",
    "scripts/wakeup_prune.py",
    "tft/assets/icon_cache.py",
    "tft/rounds/accuracy.py",
    "tft/rounds/schema.py",
    "tft/sources/tft_log.py",
    "tft/tft_prompt.py",
)
_FIXED_P647 = (
    "dashboard/_deterministic_coaching.py",
    "lcu/draft_log.py",
    "ops/audit/item_pen_drift_check.py",
    "ops/loop/lane_run_ledger.py",
    "vision_server/_inference.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", "RUF005", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return rel.startswith(_SCOPE)


@pytest.fixture(scope="module")
def tracked() -> set[str]:
    files = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len({f for f in files if _in_scope(f)}) > 100, "the tracked-file walk found almost no scoped module"
    return files


def test_no_scoped_module_has_a_concatenation_finding(tracked):
    found = sorted(
        f"{relative_posix(Path(d['filename']).resolve())}:{d['location']['row']}"
        for d in _ruff(["."])
        if _in_scope(relative_posix(Path(d["filename"]).resolve()))
    )
    assert not found, f"RUF005 findings under {_SCOPE}: {found}"


def test_the_fixed_modules_are_tracked_and_in_scope(tracked):
    for rel in (*_FIXED, *_FIXED_P504, *_FIXED_P647):
        assert rel in tracked, rel
        assert _in_scope(rel), rel


@pytest.mark.parametrize("src", [
    "def f(a):\n    return a + [1]\n",
    "def f(a):\n    return a + (1,)\n",
    "def f(a):\n    return ('x',) + a\n",
    "def f(a):\n    return list(a) + ['x']\n",
])
def test_the_rule_fires_on_each_shape_fixed(src):
    """A positive control per shape: a rule that silently stopped firing would pass the ratchet for nothing."""
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=src)
    assert {d["code"] for d in found} == {"RUF005"}, (src, found)
