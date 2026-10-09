"""tools/ci_impact_selector.py - the push CI impact slice (PERF-AUDIT item 1).

MAIN's PERF-AUDIT of 2026-10-08 measured push CI running the full dual suite
(~38.5k tests, 22-45 min) on every non-.md push, with 45 pct of push runs
cancelled by a newer push. The fix keeps the fast guards on every push, runs
the full dual suite on PR / workflow_dispatch / nightly, and gives a push an
IMPACT-SELECTED slice instead: the test modules a path->test map ties to the
files the push changed.

The two error directions are not symmetric, same as tools/md_guard_selector.py:
a false positive costs a few seconds of CI, a false negative ships a red tree
that only the nightly sees. So the map errs wide, and every case where it
cannot see the coupling at all (test infrastructure, dependency pins, the CI
mechanism itself, an unresolvable push base) escalates the push to the FULL
dual suite rather than to a smaller slice.

Unit cases run on a fabricated universe; the live cases at the bottom run the
real selector against this checkout's git index, so a refactor that quietly
stops mapping a real coupling reds here rather than in a nightly.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SELECTOR_PATH = _REPO / "tools" / "ci_impact_selector.py"


def _load_selector():
    spec = importlib.util.spec_from_file_location("ci_impact_selector", _SELECTOR_PATH)
    assert spec is not None and spec.loader is not None, _SELECTOR_PATH
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules.
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


sel = _load_selector()


# ---------------------------------------------------------------------------
# A fabricated universe. Every test module's TEXT is given, so each case can
# say exactly which coupling it exercises.
# ---------------------------------------------------------------------------
_TEXTS = {
    "core/__init__.py": "",
    "core/game_snapshot.py": "def build():\n    return {}\n",
    "agents/daemon_slayer/dps.py": "X = 1\n",
    "tools/dps_extra.py": "Y = 2\n",
    "tests/_helpers.py": "def x():\n    return 1\n",
    "tests/conftest.py": "",
    "tests/test_snapshot_dotted.py": "from core.game_snapshot import build\n",
    "tests/test_snapshot_stem.py": "from core import game_snapshot\n",
    "tests/test_unrelated.py": "import json\n\ndef test_x():\n    assert json\n",
    "tests/test_uses_helper.py": "from tests._helpers import x\n",
    "tests/test_lane_widget.py": 'ROOT = None\nPKG = ROOT / "lane-widget" / "package.json"\n',
    "tests/test_items_feed.py": 'P = "data/daemon_slayer"\nF = "items.json"\n',
    "tests/test_only_dps_extra.py": "from tools import dps_extra\n",
    "tests/test_reads_md.py": 'DOC = "docs/X.md"\n',
    "tests/sub/test_in_sub.py": "def test_y():\n    pass\n",
    "agents/daemon_slayer/tests/test_dps.py": "from agents.daemon_slayer import dps\n",
    "lane-widget/src/new_thing.js": "module.exports = 1;\n",
    "lane-widget/package.json": "{}\n",
    "data/daemon_slayer/16.19/items.json": "{}\n",
    "docs/X.md": "# x\n",
}
_TRACKED = sorted(_TEXTS)


def _select(changed, tracked=_TRACKED, texts=_TEXTS):
    return sel.select_impacted(list(changed), list(tracked), texts.get)


# ---- test-module identification -------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("tests/test_a.py", True),
    ("tests/sub/deeper/test_b.py", True),
    ("agents/daemon_slayer/tests/test_c.py", True),
    ("tests/c_test.py", True),
    ("tests/_helpers.py", False),
    ("tests/conftest.py", False),
    ("tools/tests/test_d.py", False),          # its own CI step, not this slice
    ("agents/agent3_testing/suite/test_e.py", False),  # declared NOT wired (RM-407)
    ("core/test_like_name.py", False),
])
def test_is_test_module(path, expected):
    assert sel.is_test_module(path) is expected


# ---- the escalations -------------------------------------------------------

@pytest.mark.parametrize("path", [
    "conftest.py",
    "tests/conftest.py",
    "tests/snapshot_panels/conftest.py",
    "agents/daemon_slayer/tests/conftest.py",
    "pytest.ini",
    "requirements.txt",
    "requirements.lock",
    ".github/ci/requirements-ci.txt",
    ".github/ci/requirements-ci.in",
    ".github/workflows/ci.yml",
    "tools/ci_impact_selector.py",
])
def test_infrastructure_paths_escalate_to_the_full_suite(path):
    assert sel.full_trigger_reason(path), path
    out = _select([path, "core/game_snapshot.py"])
    assert out.mode == sel.MODE_FULL, (path, out)
    assert out.modules == []


@pytest.mark.parametrize("path", [
    "core/game_snapshot.py",
    "tests/test_unrelated.py",
    "lane-widget/src/new_thing.js",
    ".github/workflows/docs-guards.yml",
    "docs/X.md",
])
def test_ordinary_paths_do_not_escalate(path):
    assert sel.full_trigger_reason(path) is None


def test_a_push_too_wide_to_map_escalates():
    changed = [f"core/m{i}.py" for i in range(sel.MAX_CHANGED_PATHS + 1)]
    out = _select(changed)
    assert out.mode == sel.MODE_FULL
    assert str(sel.MAX_CHANGED_PATHS) in out.detail


# ---- the map ---------------------------------------------------------------

def test_a_changed_test_module_selects_itself():
    out = _select(["tests/test_unrelated.py"])
    assert out.mode == sel.MODE_SLICE
    assert "tests/test_unrelated.py" in out.modules


def test_a_source_module_selects_importers_by_dotted_name_and_by_stem():
    out = _select(["core/game_snapshot.py"])
    assert out.mode == sel.MODE_SLICE
    assert "tests/test_snapshot_dotted.py" in out.modules
    assert "tests/test_snapshot_stem.py" in out.modules
    assert "tests/test_unrelated.py" not in out.modules


def test_the_stem_match_is_word_bounded():
    """`dps` must not select a module that only names `dps_extra`, and the
    reverse - an underscore is a word character, not a boundary."""
    out = _select(["agents/daemon_slayer/dps.py"])
    assert "agents/daemon_slayer/tests/test_dps.py" in out.modules
    assert "tests/test_only_dps_extra.py" not in out.modules
    out = _select(["tools/dps_extra.py"])
    assert out.modules == ["tests/test_only_dps_extra.py"]


def test_a_package_init_selects_the_package_importers():
    out = _select(["core/__init__.py"])
    assert "tests/test_snapshot_dotted.py" in out.modules
    assert "tests/test_snapshot_stem.py" in out.modules
    assert "tests/test_unrelated.py" not in out.modules


def test_a_shared_test_helper_selects_the_modules_that_import_it():
    out = _select(["tests/_helpers.py"])
    assert out.modules == ["tests/test_uses_helper.py"]


def test_an_asset_tree_file_selects_the_harness_naming_that_tree():
    """lane-widget/ holds no Python, so its coupling to tests is the PATH,
    and a brand-new file in it is named by no test at all - the tree is."""
    out = _select(["lane-widget/src/new_thing.js"])
    assert out.modules == ["tests/test_lane_widget.py"]


def test_a_data_file_selects_by_directory_and_by_basename():
    out = _select(["data/daemon_slayer/16.19/items.json"])
    assert "tests/test_items_feed.py" in out.modules
    assert "tests/test_unrelated.py" not in out.modules


def test_markdown_is_left_to_docs_guards():
    """docs-guards.yml fires on any push carrying a .md and runs every module
    that reads one, so a .md in a mixed push is not this selector's job."""
    out = _select(["docs/X.md"])
    assert out.mode == sel.MODE_NONE
    assert out.modules == []


def test_a_deleted_test_module_is_never_handed_to_pytest():
    out = _select(["tests/test_gone.py"])
    assert "tests/test_gone.py" not in out.modules
    assert out.mode == sel.MODE_NONE


def test_nothing_changed_is_none_not_full():
    out = _select([])
    assert out.mode == sel.MODE_NONE
    assert out.modules == []


def test_selection_is_only_ever_tracked_test_modules():
    every = [p for p in _TRACKED if not sel.full_trigger_reason(p)]
    out = _select(every)
    assert out.mode == sel.MODE_SLICE
    assert out.modules == sorted(set(out.modules))
    for mod in out.modules:
        assert mod in _TRACKED and sel.is_test_module(mod), mod


def test_every_selected_module_carries_a_reason():
    out = _select(["core/game_snapshot.py", "lane-widget/src/new_thing.js"])
    assert set(out.reasons) == set(out.modules)
    assert all(out.reasons[m] for m in out.modules)


# ---- git plumbing and the CLI ---------------------------------------------

def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", f"core.hooksPath={root / '.nohooks'}", *args],
        cwd=str(root), check=True, capture_output=True, text=True,
    )


def _head(root):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def mini_repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".nohooks").mkdir(parents=True)
    _git(root, "init", "-q")
    for rel in ("core/game_snapshot.py", "tests/test_snapshot_dotted.py",
                "tests/test_unrelated.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(_TEXTS[rel], encoding="utf-8")
    _git(root, "add", "core", "tests")
    _git(root, "commit", "-q", "-m", "base")
    base = _head(root)
    (root / "core" / "game_snapshot.py").write_text("def build():\n    return 1\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "change")
    return root, base, _head(root)


def test_changed_paths_reads_the_push_range(mini_repo):
    root, base, head = mini_repo
    assert sel.changed_paths(root, base, head) == ["core/game_snapshot.py"]


@pytest.mark.parametrize("base", ["", "0" * 40, "f" * 40, "not-a-sha"])
def test_an_unresolvable_base_answers_none(mini_repo, base):
    root, _base, head = mini_repo
    assert sel.changed_paths(root, base, head) is None


def test_cli_writes_the_argfile_and_the_step_output(mini_repo, tmp_path):
    root, base, head = mini_repo
    out_file, gh_out = tmp_path / "impact.txt", tmp_path / "gh_output"
    rc = sel.main(["--root", str(root), "--base", base, "--head", head,
                   "--out", str(out_file), "--github-output", str(gh_out)])
    assert rc == 0
    assert out_file.read_text(encoding="utf-8").splitlines() == ["tests/test_snapshot_dotted.py"]
    lines = gh_out.read_text(encoding="utf-8").splitlines()
    assert "mode=slice" in lines and "count=1" in lines


def test_cli_escalates_an_unresolvable_base_to_full(mini_repo, tmp_path):
    root, _base, head = mini_repo
    out_file, gh_out = tmp_path / "impact.txt", tmp_path / "gh_output"
    rc = sel.main(["--root", str(root), "--base", "0" * 40, "--head", head,
                   "--out", str(out_file), "--github-output", str(gh_out)])
    assert rc == 0
    assert "mode=full" in gh_out.read_text(encoding="utf-8").splitlines()
    assert out_file.read_text(encoding="utf-8") == ""


def test_cli_paths_mode_needs_no_git_range(mini_repo, tmp_path):
    root, _base, _head_sha = mini_repo
    gh_out = tmp_path / "gh_output"
    rc = sel.main(["--root", str(root), "--paths", "tests/test_unrelated.py",
                   "--github-output", str(gh_out)])
    assert rc == 0
    assert "mode=slice" in gh_out.read_text(encoding="utf-8").splitlines()


# ---- live: this checkout's real index ---------------------------------------

def _live(changed):
    return sel.select_impacted(changed, sel.git_tracked(_REPO), sel.disk_reader(_REPO))


def test_live_universe_is_not_vacuous():
    mods = [p for p in sel.git_tracked(_REPO) if sel.is_test_module(p)]
    assert len(mods) > 1000, len(mods)
    assert any(p.startswith("agents/daemon_slayer/tests/") for p in mods)


@pytest.mark.parametrize("changed,must_select", [
    ("tools/md_guard_selector.py", "tests/test_ci_docs_guard_coverage.py"),
    ("lane-widget/src/main.js", "tests/test_lane_widget_node_suite.py"),
    ("rc-shell/package.json", "tests/test_rc_shell_node_suite_rm342.py"),
    ("tools/sibling_sweep_ci.py", "tests/test_ci_sibling_sweep_tree_wiring.py"),
    (".githooks/pre-push", "tests/test_credential_history_scan_rm492.py"),
    (".github/workflows/docs-guards.yml", "tests/test_ci_docs_guard_coverage.py"),
])
def test_live_couplings_are_mapped(changed, must_select):
    out = _live([changed])
    assert out.mode == sel.MODE_SLICE, (changed, out.detail)
    assert must_select in out.modules, (changed, len(out.modules))


def test_live_ci_workflow_edit_runs_the_whole_tree():
    assert _live([".github/workflows/ci.yml"]).mode == sel.MODE_FULL
