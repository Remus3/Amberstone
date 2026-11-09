"""RM-1538 - ruff FURB167 (a short regular-expression flag alias such as ``re.I``) is held at zero
in production code, apart from three named files.

The rule is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target
py39): production code carried 136 FURB167 sites in 23 files (``re.I`` 92+, ``re.M``, ``re.S`` and
one ``re.A``, also through the ``_re`` alias in ``coaches/aram_coach.py``). 20 files were rewritten to
the long names (``re.IGNORECASE``, ``re.MULTILINE``, ``re.DOTALL``, ``re.ASCII``) in this slice; the
alias and the long name are the same ``re.RegexFlag`` member, so no pattern changes, and every
rewritten module compares equal as an AST once the alias names are mapped.

Three files stay on a named baseline that only shrinks, each because it is not this lane's to edit:
``tools/ds_feed_watch.py`` (``lane/ds`` carries an unlanded change to it, RM-1508),
``tools/build_portable.py`` and ``ops/launcher/updater.py`` (PKG, main-session owned per
``ops/loop/control/lane_exclusions_s144.txt``). A baseline entry that stops offending fails
``test_baseline_is_exact`` until it is dropped.

Scope: production code. ``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite, ``tools/ds_cross_eval`` and the vendored
``ops/fleet_kit`` are out of scope. The run uses NO config (``--isolated``) so a per-file-ignore
cannot hide a finding.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULE = "FURB167"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
    "ops/fleet_kit/",
)
# Only shrinks. See the module docstring for why each file is here.
_BASELINE = frozenset({
    "tools/ds_feed_watch.py",
    "tools/build_portable.py",
    "ops/launcher/updater.py",
})
_FIXED = (
    "coaches/aram_coach.py",
    "core/live_session_recorder.py",
    "core/ops_panels.py",
    "dashboard/routes_recordings.py",
    "docs/_rescore/band_recompute.py",
    "lib/game_data/sources.py",
    "ops/audit/item_ah_drift_check.py",
    "ops/audit/item_pen_drift_check.py",
    "scripts/wakeup_prune.py",
    "tft/cv/profile.py",
    "tools/atlas_fonts.py",
    "tools/bot_merge_check.py",
    "tools/build_third_party_notices.py",
    "tools/drift_guard.py",
    "tools/gated_lx11_minimap_check.py",
    "tools/perseus_sync.py",
    "tools/repo_insights.py",
    "tools/sibling_name_sweep.py",
    "tools/stop_claim_gate.py",
    "tools/tft_cv_accuracy.py",
)
_ALIAS_NAMES = frozenset("IMSXAUL")


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_findings() -> list[tuple[str, int]]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            out.append((rel, d["location"]["row"]))
    return out


def test_no_new_findings(tree_findings):
    new = [f for f in tree_findings if f[0] not in _BASELINE]
    assert not new, f"ruff {_RULE} findings outside the baseline (file, line): {new}"


def test_baseline_is_exact(tree_findings):
    """A baseline file that no longer offends must be dropped, so the set only shrinks."""
    still = {rel for rel, _ in tree_findings}
    assert sorted(_BASELINE - still) == [], "drop these from _BASELINE: they are clean now"
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert tracked >= _BASELINE


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_lf_and_alias_free(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    text = raw.decode("ascii")
    assert b"\r" not in raw
    aliases = [n.lineno for n in ast.walk(ast.parse(text))
               if isinstance(n, ast.Attribute) and n.attr in _ALIAS_NAMES
               and isinstance(n.value, ast.Name) and n.value.id in ("re", "_re")]
    assert aliases == [], (rel, aliases)


def test_probe_is_live():
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    found = _ruff(
        ["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"],
        stdin="import re\nX = re.compile('a', re.I | re.M)\n",
    )
    assert {d["code"] for d in found} == {_RULE}, found


def test_alias_and_long_name_are_the_same_flag():
    """The premise of the rewrite: each alias is the very member its long name returns."""
    assert re.I is re.IGNORECASE
    assert re.M is re.MULTILINE
    assert re.S is re.DOTALL
    assert re.A is re.ASCII
    assert re.X is re.VERBOSE
    assert re.U is re.UNICODE
    assert re.compile(r"a", re.I | re.M) == re.compile(r"a", re.IGNORECASE | re.MULTILINE)
