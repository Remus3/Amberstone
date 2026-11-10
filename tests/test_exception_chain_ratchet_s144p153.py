"""RM-1539 - ruff B904 (raise inside except without ``from``) is held at zero in production code.

ruff.toml ignores B904 ("existing RC style"), so a raise that swallowed the original
exception's identity could land unnoticed. Measured 2026-11-05 with ``ruff check --isolated``
(target py39): production code outside the owned paths below carried 9 sites in 5 modules:
the build-planner state codec (3), the UI applier path check, the DS parity fixture loader,
the inbox export failure and the sibling-name sweep git helper (3). Each now chains
(``raise New(...) from exc``), so the traceback shows the root cause under "direct cause"
rather than the misleading "During handling of the above exception, another exception occurred".

The exception TYPE and MESSAGE are unchanged; only ``__cause__`` is set.

Scope: production code. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer`` (the DS
server, lane ds), ``agents/agent3_testing/suite`` and ``tools/ds_cross_eval`` are out of scope.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/agent4_coach_mentor/ui_applier.py",
    "core/build_planner/relax.py",
    "tools/ds_parity_run.py",
    "tools/inbox_responder_export.py",
    "tools/sibling_name_sweep.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", "B904", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff B904 findings beyond the baseline, file: count: {extra}"


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
    """A minimal offender is reported, so an empty tree result is a real scan."""
    probe = (
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        raise RuntimeError('x')\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["B904"]


def test_ui_applier_path_escape_chains_the_cause():
    from agents.agent4_coach_mentor import ui_applier

    with pytest.raises(ui_applier.UIApplyError, match="path escapes project root") as info:
        ui_applier._resolve_target("../../../../outside_the_project_root")
    assert isinstance(info.value.__cause__, ValueError)


def test_relax_state_codec_chains_the_cause():
    from core.build_planner import relax

    with pytest.raises(ValueError, match="malformed state string") as info:
        relax.decode_state("!!!")
    assert info.value.__cause__ is not None


def test_ds_parity_fixture_loader_chains_the_cause(tmp_path):
    from tools import ds_parity_run

    bad = tmp_path / "fixtures.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="bad JSON") as info:
        ds_parity_run.load_fixtures(bad)
    assert isinstance(info.value.__cause__, json.JSONDecodeError)
