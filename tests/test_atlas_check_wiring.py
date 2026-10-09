"""Guards that `tools/atlas_build.py --check` actually RUNS somewhere.

atlas.html is generated from the git index (MAIN 2246 section 6), so it goes
stale whenever a module is added, removed or renamed and nobody re-runs the
generator. tests/test_atlas_dust.py pins freshness inside the full suite; the
merger's follow-up to slice W-E wires the same check into the two places the
other drift checks run:

* tools/drift_guard.py `check_atlas_fresh`, part of `run_all`, run at every
  /done;
* the `check` job of .github/workflows/ci.yml, as a FAST GUARD step (no `if:`,
  above the push impact slice), because a push that adds a module may select
  no atlas test at all.

Each wiring is exercised both ways - a fresh page is clean, a stale or
unbuildable one is a breach - so neither can decay into always-passing. The
end-to-end case uses the REAL generator on a synthetic git tree.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import drift_guard  # noqa: E402

BUILDER = REPO / "tools" / "atlas_build.py"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
FIXED_STAMP = {"commit": "0000000", "date": "2026-01-01", "commits": 1}


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_build_wiring_under_test", BUILDER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree_with_page_and_builder(root: Path) -> None:
    (root / "tools").mkdir()
    (root / drift_guard.ATLAS_PAGE).write_text("<html></html>\n", encoding="ascii")
    (root / drift_guard.ATLAS_BUILDER).write_text("# stand-in\n", encoding="ascii")


# --------------------------------------------------------------------------
# drift_guard.check_atlas_fresh - both verdicts, with an injected checker
# --------------------------------------------------------------------------

def test_a_tree_without_the_page_or_the_generator_has_nothing_to_check() -> None:
    called = []
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        assert drift_guard.check_atlas_fresh(root, checker=called.append) == []
        (root / drift_guard.ATLAS_PAGE).write_text("x\n", encoding="ascii")
        assert drift_guard.check_atlas_fresh(root, checker=called.append) == []
    assert called == [], "the checker ran on a tree that has nothing to check"


def test_a_fresh_page_is_clean() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _tree_with_page_and_builder(root)
        assert drift_guard.check_atlas_fresh(root, checker=lambda r: (0, "")) == []


def test_a_stale_page_is_a_breach_naming_the_fix() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _tree_with_page_and_builder(root)
        out = drift_guard.check_atlas_fresh(
            root, checker=lambda r: (1, "atlas.html is stale. Run: python tools/atlas_build.py"))
    assert [f.kind for f in out] == ["atlas-stale"]
    assert "tools/atlas_build.py" in out[0].message


def test_an_unbuildable_page_or_a_crashed_checker_is_a_breach_never_a_pass() -> None:
    def boom(_root):
        raise RuntimeError("generator exploded")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _tree_with_page_and_builder(root)
        unbuildable = drift_guard.check_atlas_fresh(root, checker=lambda r: (2, "atlas_build: x"))
        crashed = drift_guard.check_atlas_fresh(root, checker=boom)
    assert [f.kind for f in unbuildable] == ["atlas-build"]
    assert [f.kind for f in crashed] == ["atlas-build"]
    assert "generator exploded" in crashed[0].message


def test_run_all_includes_the_atlas_check() -> None:
    sentinel = drift_guard.Finding("atlas-stale", "sentinel from the patched check")
    with tempfile.TemporaryDirectory() as d, \
            mock.patch.object(drift_guard, "check_atlas_fresh", return_value=[sentinel]) as m:
        findings = drift_guard.run_all(Path(d))
    assert m.called, "run_all never calls check_atlas_fresh"
    assert sentinel in findings


def test_the_default_checker_is_the_generators_own_check_page() -> None:
    check = drift_guard._load_atlas_checker(REPO)
    assert check.__name__ == "check_page"
    assert check.__module__ == "_drift_guard_atlas_build"


# --------------------------------------------------------------------------
# end to end: the REAL generator on a synthetic git tree
# --------------------------------------------------------------------------

def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "core.autocrlf=false", *args],
                   check=True, capture_output=True)


SYNTH = {
    "pkg/__init__.py": '"""Synthetic package for the atlas wiring test."""\n',
    "pkg/alpha.py": '"""Alpha module."""\nfrom pkg import beta\n',
    "pkg/beta.py": '"""Beta module."""\nimport os\n',
    "tools/runner.py": '"""Runner."""\nimport pkg.alpha\n',
}


def _synthetic_repo(root: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    _git(root, "add", "-A")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_the_real_check_flags_a_module_added_without_a_re_render() -> None:
    # Two trees, not one tree edited in place: tests/_repo_walk caches the
    # index per root for the life of the process (lru_cache), and the real
    # check always runs in a fresh process.
    ab = _load_builder()
    template = (REPO / "atlas.html").read_text(encoding="utf-8")

    def check(r):
        return ab.check_page(r, min_modules=0)

    # The generator itself is in both trees: check_atlas_fresh skips a tree
    # without it, which would make both drift_guard verdicts below vacuous.
    base = dict(SYNTH, **{drift_guard.ATLAS_BUILDER: BUILDER.read_text(encoding="utf-8")})
    with tempfile.TemporaryDirectory(prefix="atlas_wiring_a_") as a, \
            tempfile.TemporaryDirectory(prefix="atlas_wiring_b_") as b:
        before, after = Path(a), Path(b)
        _synthetic_repo(before, base)
        _synthetic_repo(after, dict(base, **{"pkg/gamma.py": '"""Gamma module."""\n'}))
        page = ab.build_page(before, template=template, stamp=FIXED_STAMP)
        for root in (before, after):
            (root / "atlas.html").write_text(page, encoding="ascii", newline="\n")

        assert ab.check_page(before, min_modules=0) == (0, "")
        assert drift_guard.check_atlas_fresh(before, checker=check) == []

        code, message = ab.check_page(after, min_modules=0)
        assert code == 1 and message == ab.STALE_MESSAGE
        out = drift_guard.check_atlas_fresh(after, checker=check)
        assert [f.kind for f in out] == ["atlas-stale"]

        # The stamp in the page is reused, so a re-render makes it fresh again.
        stamp = ab.parse_data(page)["stamp"]
        assert stamp == FIXED_STAMP
        fresh = ab.build_page(after, template=page, stamp=stamp)
        (after / "atlas.html").write_text(fresh, encoding="ascii", newline="\n")
        assert ab.check_page(after, min_modules=0) == (0, "")


def test_check_page_reports_an_unreadable_page_as_unbuildable() -> None:
    ab = _load_builder()
    with tempfile.TemporaryDirectory() as d:
        code, message = ab.check_page(Path(d), min_modules=0)
    assert code == 2 and "atlas.html" in message


def test_the_cli_check_exit_code_follows_check_page() -> None:
    ab = _load_builder()
    for verdict in ((0, ""), (1, ab.STALE_MESSAGE), (2, "atlas_build: x")):
        with mock.patch.object(ab, "check_page", return_value=verdict):
            assert ab.main(["--check"]) == verdict[0]


# --------------------------------------------------------------------------
# CI: a fast-guard step in the `check` job
# --------------------------------------------------------------------------

def _ci_steps() -> list[dict]:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    return doc["jobs"]["check"]["steps"]


def test_ci_check_job_runs_the_atlas_check_as_a_fast_guard() -> None:
    steps = _ci_steps()
    names = [s.get("name", "") for s in steps]
    hits = [i for i, s in enumerate(steps)
            if "python tools/atlas_build.py --check" in (s.get("run") or "")]
    assert len(hits) == 1, f"expected one atlas --check step in the check job, found {len(hits)}"
    step = steps[hits[0]]
    assert "if" not in step, "the atlas check must run on every event, not only some"
    assert step.get("continue-on-error") in (None, False), "a soft-failing guard reports nothing"
    impact = names.index("push impact slice: select")
    assert hits[0] < impact, "the atlas check must sit with the fast guards, above the impact slice"


def test_ci_yml_text_names_the_check_exactly_once() -> None:
    # A text-level pin that does not depend on pyyaml being installed.
    text = CI_YML.read_text(encoding="utf-8")
    assert text.count("python tools/atlas_build.py --check") == 1
