"""RM-1692 - ruff PT018 (compound assert) and RUF036 (None not last in a union) are held at zero in the production code.

Neither rule is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39) over the
tracked production code: four findings outside the test directories and the DS engine package.

- ``lib/scrapers/_base.py``, ``tools/web_ascii_sweep.py`` and ``tools/credential_history_scan.py`` each carried one
  ``assert a and b`` (the first two with a message). Each is now two asserts; the message, where there was one,
  is kept on both halves, so the failing text a caller sees is unchanged.
- ``ops/loop/headless_env.py`` spelled ``Union[str, None, _Absent]``; it is now ``Union[str, _Absent, None]``
  (same type, None last).

Out of scope, as for the RET ratchet: ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer/`` (the
engine package: ``effects.py`` still has one RUF036 on a quoted annotation, a ds-lane FILING) and the
``agents/agent3_testing/suite`` test suite. The vendored kit under ``ops/fleet_kit/`` is in scope but clean.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("PT018", "RUF036")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
)
_FIXED = (
    "lib/scrapers/_base.py",
    "ops/loop/headless_env.py",
    "tools/credential_history_scan.py",
    "tools/web_ascii_sweep.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_findings() -> list[str]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            out.append(f"{rel}:{d['location']['row']} {d['code']}")
    return sorted(out)


def test_production_code_holds_zero(tree_findings):
    assert not tree_findings, f"ruff {_RULES} findings in the production code: {tree_findings}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


_PROBES = (
    ("PT018", "def f(a, b):\n    assert a and b\n"),
    ("RUF036", "from typing import Union\n\n\ndef f(x: Union[str, None, int]) -> None:\n    pass\n"),
)


@pytest.mark.parametrize("rule,probe", _PROBES)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--select", rule, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {rule}


def test_scraper_base_still_refuses_an_unset_site_or_base_url_with_the_same_message():
    from lib.scrapers._base import ScraperBase

    class NoSite(ScraperBase):
        base_url = "https://example.invalid"

    class NoBase(ScraperBase):
        site = "x"

    for cls in (NoSite, NoBase, ScraperBase):
        with pytest.raises(AssertionError, match="subclass must set site and base_url"):
            cls()


def test_ascii_sweep_merge_still_flags_a_coverage_gap():
    from tools import web_ascii_sweep as w

    ok = [w.Span(0, 2, "a"), w.Span(2, 5, "b")]
    assert w._merge(ok, 5) == ok
    with pytest.raises(AssertionError, match="span coverage is not total"):
        w._merge([w.Span(1, 5, "a")], 5)
    with pytest.raises(AssertionError, match="span coverage is not total"):
        w._merge([w.Span(0, 4, "a")], 5)


def test_fetch_ends_with_an_explicit_false(tmp_path):
    """retries < 0 skips the loop; fetch returned None, now False (the annotated bool)."""
    from scripts import cache_ddragon_assets as c

    assert c.fetch("https://example.invalid/x.png", tmp_path / "x.png", retries=-1) is False
