"""RM-1524 - ruff FURB188 (hand-written prefix/suffix strip) and SIM114 (two branches with
one body) are held at a baseline that only shrinks.

Neither rule is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated``
(target py39, so ``str.removeprefix`` / ``removesuffix`` exist): production code carried 15
FURB188 sites in 13 modules and 7 SIM114 pairs in 7 modules outside the owned paths below.
FURB188 is ruff's own fix (``s[len(p):] if s.startswith(p) else s`` is exactly
``s.removeprefix(p)``). The SIM114 pairs were merged by hand, with explicit parentheses
where ruff's fix left a bare ``a or b and c``.

The baseline is the findings that stay because someone else owns the file: the vendored
fleet kit (byte-pinned to MAIN's MANIFEST), ``ops/launcher`` (packaged-app path, main session)
and ``tools/ddragon_mirror_refresh.py`` (changed on another lane branch; its entry leaves when
that lane lands). A baseline entry that stops offending fails ``test_baseline_is_exact`` until
it is dropped; a new finding anywhere else fails ``test_no_new_findings``.

Scope: production code. ``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope. The
run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("FURB188", "SIM114")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE = {
    "ops/fleet_kit/fleet_claims.py": 3,
    "ops/fleet_kit/fleet_done.py": 1,
    "ops/fleet_kit/fleet_rewrite.py": 1,
    "ops/launcher/updater.py": 1,
    "tools/ddragon_mirror_refresh.py": 1,
}
_FIXED = (
    "agents/agent2_backend/migration_rewind.py",
    "agents/supervisor.py",
    "core/http_host_gate.py",
    "core/live_item_tape.py",
    "dashboard/routes_dictionary.py",
    "ops/loop/inbox_tick.py",
    "ops/loop/lane_progress.py",
    "ops/migrate/e_move_helpers.py",
    "scripts/validate_build_data.py",
    "tft/engine/comps.py",
    "tft/sources/tft_log.py",
    "tft/tft_scouting.py",
    "tools/ascii_escape_py.py",
    "tools/build_third_party_notices.py",
    "tools/ds_feed_watch.py",
    "tools/gated_lx06_events_check.py",
    "tools/inbox_responder_runner.py",
    "tools/md_guard_selector.py",
    "tools/precommit_gate.py",
)


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
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
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
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
                  stdin='def f(s, a, b):\n    if s.startswith("x"):\n        s = s[1:]\n'
                        '    if a:\n        return 1\n    elif b:\n        return 1\n'
                        '    return s\n')
    assert {d["code"] for d in found} == set(_RULES), found


def test_strip_forms_agree():
    """The premise of the FURB188 fix: removeprefix/removesuffix equal the guarded slice."""
    for s in ("", "-", "--5", "5", "b/x", "x.", "..", "abc"):
        for p in ("", "-", "b/", "."):
            old_pre = s[len(p):] if s.startswith(p) else s
            old_suf = s[:-len(p)] if p and s.endswith(p) else s
            assert s.removeprefix(p) == old_pre
            assert s.removesuffix(p) == old_suf
