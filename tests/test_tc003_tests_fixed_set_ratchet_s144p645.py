"""S144-P-645 - ruff TC003 (a stdlib import used only in annotations) is held at zero in a named set of test modules.

TC003 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39):
94 findings tree-wide, 68 of them in ``tests/`` (``from pathlib import Path`` used only in test-function signatures).
Twenty-eight of those modules (14 in S144-P-645, 14 more in S144-P-646; ones no other lane branch changed) now carry the import under ``if TYPE_CHECKING:``;
each has ``from __future__ import annotations``, so the annotation is never evaluated at runtime.

Scope is the named ``_FIXED`` set, not the tree: the remaining ~40 test modules and ~12 production modules are further
slices, and a tree baseline would be a long exception list rather than a ratchet. Move a module into ``_FIXED`` when its
finding is fixed. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("TC003",)
_FIXED = (
    "tests/test_adaptation_hint_aggregates_true_audit_s144.py",
    "tests/test_adaptation_hint_champion_true_audit_s144.py",
    "tests/test_adaptation_hint_facade_s144p490.py",
    "tests/test_adaptation_hint_session_true_audit_s144.py",
    "tests/test_advisory_sweeper_true_audit_s144t152.py",
    "tests/test_aram_archetype_override.py",
    "tests/test_aram_balance_context_hardening_s144.py",
    "tests/test_builders_lcu_enrich_hardening_s144t217.py",
    "tests/test_coaching_data_no_clobber_rm278.py",
    "tests/test_cold_streak_detector_true_audit_s144.py",
    "tests/test_db_schema_true_audit_s144t172.py",
    "tests/test_death_patterns_loader_hardening_s144t133.py",
    "tests/test_det_coach_shadow_report.py",
    "tests/test_det_coach_shadow_report_true_audit_s144t174.py",
    # S144-P-646: the next fourteen.
    "tests/test_ds_ability_data_status_rm95.py",
    "tests/test_game_ingest_hardening_s144t163.py",
    "tests/test_gen_archmap_gitignored_file_s144d14.py",
    "tests/test_host_allowlist_rm759.py",
    "tests/test_host_head_defects_rm773.py",
    "tests/test_input_parser_true_audit_s144.py",
    "tests/test_insight_detector_true_audit_s144t151.py",
    "tests/test_item_wpa_audit_s144.py",
    "tests/test_laning_verdicts_true_audit_s144.py",
    "tests/test_league_settings.py",
    "tests/test_loop_controller_disarm_rm506.py",
    "tests/test_macro_response_shadow_report.py",
    "tests/test_md_guard_selector_bound_argv_s144q40b.py",
    "tests/test_md_guard_selector_option_args_s144q41.py",
)


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


def test_fixed_files_exist_and_are_unique():
    """An empty or misspelt entry would pass vacuously: every named file is a real tracked-style path."""
    assert len(set(_FIXED)) == len(_FIXED)
    missing = [rel for rel in _FIXED if not (REPO_ROOT / rel).is_file()]
    assert not missing, missing


def test_fixed_files_have_no_tc003_finding():
    found = _ruff(list(_FIXED))
    by_file: dict[str, int] = {}
    for d in found:
        rel = relative_posix(Path(d["filename"]).resolve())
        by_file[rel] = by_file.get(rel, 0) + 1
    assert not by_file, f"ruff {_RULES} findings, file: count: {by_file}"


def test_fixed_files_keep_the_future_import():
    """The guarantee that makes the move safe: with PEP 563 annotations the moved name is never evaluated."""
    lacking = [rel for rel in _FIXED
               if "from __future__ import annotations" not in (REPO_ROOT / rel).read_text(encoding="utf-8")]
    assert not lacking, lacking


def test_probe_is_live():
    """TC003 fires on an annotation-only stdlib import and stays quiet under ``TYPE_CHECKING``."""
    bad = (
        "from __future__ import annotations\n"
        "from pathlib import Path\n"
        "def f(p: Path) -> None:\n"
        "    return None\n"
    )
    good = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pathlib import Path\n"
        "def f(p: Path) -> None:\n"
        "    return None\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
