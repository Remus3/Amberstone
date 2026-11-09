"""RM-1536 - ruff PIE810 (two ``startswith`` / ``endswith`` calls joined by ``or``) is held at a
baseline that only shrinks, and the RM-1532 SIM300 / PERF403 baseline lost its sr_draft_profile row.

PIE810 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39):
production code carried 2 sites, ``scripts/fetch_cdragon_pbe.py`` (now one ``startswith`` with a
tuple of prefixes, the same truth table) and ``ops/rc_supervisor.py`` (frozen, ASKS 24: the baseline
row stays until the operator approves a supervisor edit).

The same pass found the P-146 ratchet failing at HEAD: the s144 true-audit landing re-introduced two
yoda comparisons of module globals in ``coaches/sr_draft_profile.py`` and a one-key
``for ... exact[cid] = cid`` loop in ``core/aram_balance_context.py``. Both are rewritten (see
``test_yoda_perf403_c408_ratchet_s144p146.py``).

A baseline entry that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new
finding anywhere else fails ``test_no_new_findings``. Scope: tracked ``.py`` files outside
``tests/``, any ``*/tests/`` directory, ``docs/`` (dated analysis scripts), ``agents/daemon_slayer``
and ``ops/fleet_kit``. The run uses NO config (``--isolated``).
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
    "docs/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
_BASELINE = {
    "ops/rc_supervisor.py": 1,  # FROZEN (ASKS 24)
}
_FIXED = ("scripts/fetch_cdragon_pbe.py",)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out: collections.Counter = collections.Counter()
    for d in _ruff(["--select", "PIE810", "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            out[rel] += 1
    return dict(out)


def test_no_new_findings(counts):
    new = {f: n for f, n in counts.items() if n > _BASELINE.get(f, 0)}
    assert not new, f"ruff PIE810 findings beyond the baseline, file: count: {new}"


def test_baseline_is_exact(counts):
    stale = {f: n for f, n in _BASELINE.items() if counts.get(f, 0) < n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_probe_is_live():
    found = _ruff(
        ["--select", "PIE810", "--stdin-filename", "probe_mod.py", "-"],
        stdin="def f(s):\n    return s.startswith('a') or s.startswith('b')\n",
    )
    assert [d["code"] for d in found] == ["PIE810"], found


def test_tuple_form_equals_or_chain():
    """The premise of the fix: ``startswith`` with a tuple is the ``or`` of the single calls."""
    for cid in ("TFT17_Foo", "TFT_Set17_Bar", "TFT16_Baz", "", "TFT_Set17", "xTFT17_"):
        assert cid.startswith(("TFT17_", "TFT_Set17_")) == (
            cid.startswith("TFT17_") or cid.startswith("TFT_Set17_"))  # noqa: PIE810
